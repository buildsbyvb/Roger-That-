"""
Roe - better and faster speech recognition for Hindi (replaces transcribe_clean in voice_assistant.py).

What it fixes
  1. Hindi shown in English: Whisper sometimes guesses the wrong language for Hindi (Urdu, Punjabi, Marathi,
     or even English) and then writes an English "translation". Now, if the language probabilities say
     "Hindi-like", it listens again as Hindi, so you get your real Hindi words.
  2. Slow Hindi: Whisper used to retry a Hindi sentence several times when it was not sure
     (temperature fallback) and wrote time stamps nobody needs. Both are switched off.
Set SHOW_TIMING = True to see how long listening took and which language was used.
"""
import difflib
import re
import threading
import time

try:
    import hindi_fix
except Exception:                       # the assistant must work even if this helper file is missing
    hindi_fix = None
try:
    import wake_words
except Exception:
    wake_words = None

_big = {"model": None}

# ---------------- Settings you can change ----------------
HINDI_LIKE = ("hi", "ur")   # only Hindi and Urdu count as Hindi (Whisper often calls spoken Hindi "Urdu")
HINDI_SURE = 0.80        # Hindi is used straight away only if Hindi+Urdu together are at least this likely
SHORT_AUDIO = 2.5        # seconds. Short phrases ("deactivate voice", "pause") are guessed badly, so English gets help
EN_BONUS = 0.20          # when it is unclear, English gets this much extra credit (English is the main language)
SHORT_BONUS = 0.25       # extra English credit for very short phrases
MIN_LOGPROB_EN = -1.1    # English words the model is less sure of than this are thrown away (was -1.5: gibberish got through)
MIN_LOGPROB_HI = -1.6    # Hindi scores are naturally lower (the old -1.4 plus the English limit threw real Hindi away), so more forgiving
NO_SPEECH_MAX = 0.5      # a piece the model thinks is "no speech" above this is thrown away (was 0.6)
MAX_COMPRESSION = 2.4    # text that repeats itself (the classic "gibberish loop") is thrown away
HINDI_BEAM = 3           # when the sentence is Hindi, search harder than English
HINDI_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"   # much better Hindi than "small" and still quick.
                         # (this full name works on every faster-whisper version; first run downloads ~1.6 GB once.
                         # None = use the normal model. If it cannot load, the normal model is used, silently.)
PHANTOM_MIN_SCORE = -0.5 # "thank you", "bye", "you" ... are only believed if the model is VERY sure (they are Whisper's favourite ghosts)
FIX_HINDI_WORDS = True   # repair near-miss spellings of command words (see hindi_fix.py)
HINDI_QUICK = True       # short Hindi sentences are heard by the normal model first (about 3x faster than the big one).
                         # If the words are one of Roe's own Hindi commands we are done at once; otherwise the big model listens too.
HINDI_QUICK_SECS = 6.0   # only sentences up to this many seconds use the quick way
HINDI_QUICK_BEAM = 2     # search width of the quick Hindi pass (the big model uses HINDI_BEAM)
SHOW_TIMING = False      # True = print "(heard in 1.2 s, language hi)" after every sentence
# ---------------------------------------------------------


def _run(model, audio, language, prompt, beam_size):
    segments, info = model.transcribe(
        audio, language=language, beam_size=beam_size, initial_prompt=prompt,
        condition_on_previous_text=False,
        temperature=0.0,              # one try only: no slow retries
        without_timestamps=True,      # no time stamps: fewer words to write = faster
        no_speech_threshold=NO_SPEECH_MAX,
        compression_ratio_threshold=MAX_COMPRESSION)
    heard = language or getattr(info, "language", None) or "en"     # auto-detect: judge Hindi by the HINDI limit, not the English one
    min_lp = MIN_LOGPROB_HI if heard in HINDI_LIKE else MIN_LOGPROB_EN
    kept, scores = [], []
    for s in segments:
        if s.no_speech_prob >= NO_SPEECH_MAX or s.avg_logprob <= min_lp:
            continue
        if getattr(s, "compression_ratio", 0) > MAX_COMPRESSION:      # looping / repeated nonsense
            continue
        kept.append(s.text.strip())
        scores.append(s.avg_logprob)
    score = sum(scores) / len(scores) if scores else -9.0
    return " ".join(kept).strip(), info, score


USE_GPU = True           # False = never use the graphics card (use this if she closes or crashes on CUDA problems)


def pick_device():
    """('cuda','float16') when an NVIDIA graphics card is usable (3-5x faster), else ('cpu','int8')."""
    if not USE_GPU:
        return "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def load_model(name):
    """Loads a Whisper model on the best device and runs a REAL test sentence (silence, both English and
    auto-language, like the real thing), so a broken graphics-card setup is found NOW and the processor is
    used instead, instead of crashing on your first word. Also means the first real sentence is not slow."""
    import os
    import numpy as np
    from faster_whisper import WhisperModel
    threads = max(2, (os.cpu_count() or 4) - 1)
    dev, ct = pick_device()
    quiet = np.zeros(16000, dtype=np.float32)
    for d, c in ((dev, ct), ("cpu", "int8")):
        try:
            m = WhisperModel(name, device=d, compute_type=c, cpu_threads=threads)
            for lang in ("en", None, "hi"):                 # the results MUST be read, or nothing actually runs
                segs, _ = m.transcribe(quiet, language=lang, beam_size=2, without_timestamps=True)
                list(segs)
            return m
        except Exception:
            if d == "cpu":
                raise
    return None


_big_lock = threading.Lock()


def _hindi_model(default):
    """The model used for the big Hindi pass (the normal one, or HINDI_MODEL when you set it)."""
    if not HINDI_MODEL:
        return default
    with _big_lock:                                # loaded ONCE, even if start-up and a sentence ask at the same time
        if _big["model"] is None:
            try:
                _big["model"] = load_model(HINDI_MODEL)
            except Exception:
                _big["model"] = default            # no message: the normal model is used for Hindi
    return _big["model"]


def preload_hindi(default):
    """Loads the Hindi model in the background at start-up, so the first Hindi sentence is not slow."""
    if HINDI_MODEL:
        threading.Thread(target=_hindi_model, args=(default,), daemon=True).start()


def _hindi_pass(model, audio, prompt, beam_size):
    hp = (hindi_fix.PROMPT if hindi_fix else "") or prompt
    text, _, score = _run(_hindi_model(model), audio, "hi", hp, max(beam_size, HINDI_BEAM))
    if FIX_HINDI_WORDS and hindi_fix and text:
        text = hindi_fix.fix(text)
    return text, score


def _hindi_text(model, audio, prompt, beam_size, secs):
    """Hindi text for this audio, as fast as possible.
    A short sentence is heard by the normal model first. If that is one of Roe's own Hindi commands (time, weather,
    brightness, volume, windows ...) we are done: no waiting for the big model. If not, the big model listens as before."""
    if HINDI_QUICK and hindi_fix and secs <= HINDI_QUICK_SECS:
        text, _, score = _run(model, audio, "hi", hindi_fix.PROMPT or prompt, HINDI_QUICK_BEAM)
        if text:
            if FIX_HINDI_WORDS:
                text = hindi_fix.fix(text)
            if hindi_fix.understood(text) or (wake_words and wake_words.detect(text)[0]):
                return text, score
        if not HINDI_MODEL:                         # no bigger model: this is the answer
            return text, score
    return _hindi_pass(model, audio, prompt, beam_size)


def _probs(info):
    try:
        return dict(getattr(info, "all_language_probs", None) or [])
    except Exception:
        return {}


def _detect(model, audio):
    """(chance of English, chance of Hindi/Urdu, most likely language) from a quick language check that writes no words.
    None if this faster-whisper version cannot do that (then transcribe() listens once, as before)."""
    try:
        res = model.detect_language(audio)
        top, prob, allp = res[0], res[1], res[2]
        probs = dict(allp or []) or {top: prob}
    except Exception:
        return None
    return probs.get("en", 0.0), sum(probs.get(l, 0.0) for l in HINDI_LIKE), top


_VOICE_WORDS = ("deactivate", "activate")


def _voice_command(text):
    """True if the English text sounds like "activate voice" / "deactivate voice" (small mishearings allowed)."""
    toks = re.findall(r"[a-z]+", (text or "").lower())
    has_act = any(difflib.SequenceMatcher(None, t, w).ratio() >= 0.78 for t in toks for w in _VOICE_WORDS)
    has_voice = any(difflib.SequenceMatcher(None, t, "voice").ratio() >= 0.7 for t in toks)
    return has_act and (has_voice or len(toks) == 1)


# Whisper's favourite "ghost" sentences: it writes them when it hears silence or noise.
PHANTOMS = {"thank you", "thanks", "thank you very much", "thanks for watching", "thank you for watching", "you",
            "bye", "the end", "so", "uh", "um", "hmm", "mm", "mhm", "oh", "ah", "subtitles by the amara org community",
            "please subscribe", "like and subscribe", "see you next time", "i m sorry", "yeah",
            "धन्यवाद", "शुक्रिया", "थैंक यू", "आपका धन्यवाद", "बस", "हम्म", "सब्सक्राइब करें", "सबटाइटल", "अरे", "हाँ हाँ"}
PHANTOM_PARTS = ("subscribe", "amara.org", "thanks for watching", "www.", "subtitles", "सब्सक्राइब", "चैनल को")


def _words(text):
    return re.findall(r"[\w\u0900-\u097F]+", (text or "").lower())


def _looks_like_gibberish(text):
    """Repeated words ("ha ha ha ha ha") or one word over and over."""
    w = _words(text)
    if len(w) >= 4 and len(set(w)) / float(len(w)) < 0.4:
        return True
    run = 1
    for a, b in zip(w, w[1:]):
        run = run + 1 if a == b else 1
        if run >= 4:
            return True
    return False


def _is_prompt_echo(text, prompt):
    """The model sometimes just reads its hint back (the list of example commands). Real speech never does that."""
    tw, pw = _words(text), _words(prompt)
    if len(tw) < 6 or not pw:
        return False
    m = difflib.SequenceMatcher(None, tw, pw, autojunk=False).find_longest_match(0, len(tw), 0, len(pw))
    return m.size >= 6 and m.size >= 0.9 * len(tw)


def _is_ghost(text, score, secs, prompt):
    low = " ".join(_words(text))
    if any(p in (text or "").lower() for p in PHANTOM_PARTS):
        return True
    if low in PHANTOMS and not (score > PHANTOM_MIN_SCORE and secs >= 0.7):
        return True
    return _looks_like_gibberish(text) or _is_prompt_echo(text, prompt)


def transcribe(model, audio, language, prompt, state, beam_size=1, allowed=("en", "hi"), _t0=None):
    """Same job as the old transcribe_clean: returns the text ('' if it was only noise or a ghost sentence).

    ENGLISH IS THE MAIN LANGUAGE. Hindi is used only when the sound is clearly Hindi. When it is unclear
    (short phrases, noisy room) both languages are tried and the better one wins, with English favoured.

    HOW IT IS FAST: the language is found first by a quick check that writes no words. A sentence that is clearly English
    (or clearly the same language as the one before it) is then heard ONCE. A short Hindi sentence is first heard by the
    normal model, and only goes to the big Hindi model when it is not one of Roe's own commands (see _hindi_text)."""
    t0 = _t0 or time.time()
    secs = len(audio) / 16000.0
    score = -9.0
    all_prompt = prompt + " " + ((hindi_fix.PROMPT if hindi_fix else "") or "")
    if language is not None:                                  # a fixed language was asked for
        text, info, score = _run(model, audio, language, prompt, beam_size)
        if language == "hi" and text and FIX_HINDI_WORDS and hindi_fix:
            text = hindi_fix.fix(text)
        final = language
    else:
        short = secs < SHORT_AUDIO
        was_hindi = state.get("lang") == "hi"
        det = _detect(model, audio)
        first_text, first_score = None, -9.0
        if det is not None:
            p_en, p_hi, top = det
        else:                                                 # older faster-whisper: listen once with auto-detect, then decide
            first_text, info, first_score = _run(model, audio, None, prompt, beam_size)
            top = getattr(info, "language", None) or "en"
            probs = _probs(info)
            p_en = probs.get("en", 0.0)
            p_hi = sum(probs.get(l, 0.0) for l in HINDI_LIKE)
            if not probs:                                     # no probabilities: trust the guessed language
                p_en, p_hi = (1.0, 0.0) if top == "en" else (0.0, 1.0) if top in HINDI_LIKE else (0.5, 0.0)

        def english():
            if first_text is not None and top == "en":        # already heard as English: no second pass
                return first_text, first_score
            t, _, sc = _run(model, audio, "en", prompt, beam_size)
            return t, sc

        def hindi():
            return _hindi_text(model, audio, prompt, beam_size, secs)

        if top == "en" and p_en >= p_hi:
            text, score = english()                           # clearly English: done, no second pass
            final = "en"
        elif p_hi >= HINDI_SURE and not (short and p_hi < 0.95):
            text, score = hindi()                             # clearly Hindi
            final = "hi"
        elif was_hindi and p_hi >= 0.5 and p_hi > p_en:
            text, score = hindi()                             # same language as the sentence before
            final = "hi"
        elif p_hi < 0.15:
            text, score = english()                           # no sign of Hindi at all (an odd language guessed from noise)
            final = "en"
        else:
            # unclear (a short phrase, a noisy room): English is the main language, but when it leans Hindi and the Hindi words
            # are one of Roe's own commands, that is the answer at once (no second pass). Otherwise listen both ways.
            text, final, hi_text, hi_score = "", None, None, -9.0
            if p_hi > p_en:
                hi_text, hi_score = hindi()
                if hi_text and hindi_fix and hindi_fix.understood(hi_text):
                    text, final, score = hi_text, "hi", hi_score
            if final is None:
                en_text, en_score = english()
                if _voice_command(en_text) or (wake_words and wake_words.detect(en_text)[0]):
                    text, final, score = en_text, "en", en_score   # Hello Roe / Bye Roe / activate voice: always English
                else:
                    if hi_text is None:
                        hi_text, hi_score = hindi()
                    en_total = en_score + EN_BONUS + (SHORT_BONUS if short else 0.0)
                    known = bool(hi_text and hindi_fix and p_hi > p_en and hindi_fix.understood(hi_text))
                    if hi_text and ((p_hi > p_en and hi_score > en_total) or known):
                        text, final, score = hi_text, "hi", hi_score
                    else:
                        text, final, score = en_text, "en", en_score
                        if not en_text and hi_text:
                            text, final, score = hi_text, "hi", hi_score
        state["lang"] = final if text else state.get("lang")
    if text and _is_ghost(text, score, secs, all_prompt):     # a made-up sentence from silence / noise / the hint
        if SHOW_TIMING:
            print("(ignored a ghost sentence: %s)" % text)
        return ""
    if SHOW_TIMING and text:
        print("(heard in %.1f s, language %s, confidence %.2f)" % (time.time() - t0, final, score))
    if not re.search(r"\w", text):
        return ""
    return text

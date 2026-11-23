"""
Roe - Step 10: a natural voice chatbot with web search

  Say  "Hello Roe" (or "activate voice")   -> it wakes up (you hear a beep).
  Then just talk, one thing after another. No wake word needed again:
       "what's the weather?"           "and tomorrow?"
       "latest cricket news"           "how do I make paneer butter masala"
       "set a timer for 10 minutes"    "remind me to call mom at 6 pm"
       "play Tum Hi Ho"                "play a song"        "play kesariya on youtube"
       "pause"   "next song"   "change the song"   "resume"
       "open the first link"           "turn on bluetooth"  "close chrome"
  Say  "Bye Roe" / "Bye bye Roe" (or "deactivate voice")  -> it goes to sleep (lower beep). It also sleeps by itself
       after a few minutes of silence.

New in Step 8
  * It waits until you FINISH speaking (voice activity detection) and ignores noise.
  * You can INTERRUPT it: start talking while it speaks and it stops at once.
  * It remembers the last few things you said (follow-up questions work).
  * It searches the internet when needed and speaks a short summary; the full text and
    the links are shown on screen.
  * Natural voice (Microsoft neural voice) with the Windows voice as backup.

NEW: PHONE CONTROL MODE
  Say  "control phone"   -> your phone screen opens on the laptop and everything you say now controls the PHONE
                            ("open whatsapp", "scroll", "play the second video", "call daddy", "click a picture" ...).
  Say  "activate voice"  -> the phone screen closes and you are back to normal laptop commands.
  (See phone_control.py for the full list.  Start straight in phone mode with:  py -3.11 voice_assistant.py --phone)

Risky commands (delete, shutdown, restart) still ask "Are you sure?" and wait for "yes".

STOP the program: click on the black window and press Ctrl + C.
Needs these files in the same folder: wake_listen.py, actions.py, brain.py, llm.py,
vad.py, voice_out.py, web_tools.py, music.py, reminders.py
"""
import difflib
import logging
import os
import random
import re
import sys
import time
import warnings

# Silence the harmless Hugging Face messages (model download notices, "no symlinks" warning, progress bars).
# These must be set BEFORE faster_whisper / huggingface_hub are imported.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
warnings.filterwarnings("ignore", module="huggingface_hub")
warnings.filterwarnings("ignore", message=".*unauthenticated.*")
for _name in ("huggingface_hub", "huggingface_hub.file_download", "huggingface_hub.utils._http", "faster_whisper"):
    logging.getLogger(_name).setLevel(logging.ERROR)

import sounddevice as sd
from faster_whisper import WhisperModel

import actions
import brain
import features
import speech_fix
import llm
import music
import personality
import reminders
import vad
import voice_out
import wake_words
import web_tools
try:
    import phone_control
except Exception as _e:                      # a broken phone file must never stop the laptop assistant
    print("(Note: phone control was not loaded: %s)" % _e)

    class phone_control:                     # does-nothing stand-in
        ACTIVE = False
        WHISPER_PROMPT = ""
        wants_enter = staticmethod(lambda t: False)
        enter = staticmethod(lambda: "Phone control is not available.")
        leave = staticmethod(lambda quiet=False: "")
        handle = staticmethod(lambda t: "Phone control is not available.")
from wake_listen import BLOCK, MIC_DEVICE, RATE, beep, callback, clear_queue

# ---------------- Settings you can change ----------------
SHOW_DETAILS = False     # False = the screen shows only what you said and the answer.
                          # True = also shows technical lines (what was heard, which brain, timing).
SPEECH_MODEL = "small"    # how well it hears you: "base" = faster but mishears more,
                          # "small" = better (recommended), "medium" = best but slow
SESSION_LANGUAGE = None   # None = detects English / Hindi / Hinglish by itself.
                          # "en" = English only (a bit more accurate for English).
SPEAK_REPLIES = True      # False = only print replies, do not speak them
BARGE_IN = True           # True = the moment you speak she stops and does what you say.
                          # Works best with HEADPHONES. With laptop speakers it still works (she learns how loud
                          # her own voice is), but if she stops by herself raise ECHO_MULT in vad.py (e.g. 2.5).
BEAM_SIZE = 2             # 1 = fastest. 2 = good balance (recommended). 3+ = slower, tiny gain
REMIND_AFTER = 20         # seconds of silence after which she says "I am still here"
REMIND_MAX = 3            # how many reminders in one quiet stretch (then she stays quiet until she sleeps)
SPEAK_GOODBYE = True      # she says "Bye bye!" when you put the voice to sleep
IDLE_SLEEP_MINUTES = 5    # goes back to sleep after this long without a command
MAX_LINKS = 2             # how many source links are shown under a web answer
WAKE_MATCH = 0.70         # how close the words must be to "activate voice"
ACTIVATE_WHILE_ON_SLEEPS = True   # True = if she is already ON and hears just "activate voice", she goes to sleep at once
                          # (the speech model very often drops the "de" of "deactivate"). False = she asks yes/no first.
SLEEP_MATCH = 0.75        # how close the words must be to "deactivate voice" (lower = easier to hear)
# ---------------------------------------------------------

WAKE = "activate voice"
SLEEP = "deactivate voice"
SLEEP_ALIASES = ("stop listening", "go to sleep", "voice off", "sleep mode", "deactivate", "voice band",
                 "stop voice", "turn off voice", "switch off voice", "band karo voice", "sone jao", "so jao")
YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "confirm", "haan", "han", "ha", "ok", "okay",
             "हाँ", "हां", "हा", "जी", "जी हाँ", "जी हां", "ठीक", "ठीक है", "ओके"}
NO_WORDS = {"no", "nope", "nahi", "nahin", "cancel", "stop", "नहीं", "नही", "ना", "मत", "रहने दो"}
STOP_PHRASES = {"stop", "stop it", "stop talking", "ruko", "bas", "bas karo", "chup", "chup raho",
                "quiet", "enough", "okay stop"}
ALLOWED_LANGS = ("en", "hi")
PROMPT = ("Hello Roe, Bye Roe, bye bye Roe, activate voice, deactivate voice, phone control, stop phone control, "
          "Spotify, YouTube, play a song, pause, next song, weather, set a timer, remind me, "
          "open downloads folder, turn on bluetooth, wifi off, close chrome, set volume to 50, brightness 50 percent")
WAKE_PROMPT = "Hello Roe. Hey Roe. Activate voice."       # used while she is asleep: she only has to catch the wake words

# These already speak by themselves, so the reply is not spoken twice.
ALREADY_SPOKEN = {"read", "stop_reading"}

BOLD, RESET = "\033[1m", "\033[0m"      # bold text on the screen for the important lines


def bold(text):
    return BOLD + text + RESET


speaker = None
listener = None
STATE = {"pending": None, "interrupted": False, "barged": False, "lang": None, "confirm_sleep": False}


# ------------------------------------------------------------------
# Understanding the wake / sleep words (unchanged from Step 7)
# ------------------------------------------------------------------
def to_pairs(text):
    """[(original word, clean lowercase word), ...] without empty words."""
    pairs = []
    for tok in re.findall(r"\S+", text):
        clean = re.sub(r"[^\w]", "", tok.lower())
        if clean:
            pairs.append((tok, clean))
    return pairs


def best_match(pairs, phrase):
    """How close is the best group of words to the phrase? Returns (score, start)."""
    n = len(phrase.split())
    best = (0.0, -1)
    for i in range(0, len(pairs) - n + 1):
        chunk = " ".join(c for _, c in pairs[i:i + n])
        r = difflib.SequenceMatcher(None, chunk, phrase).ratio()
        if r > best[0]:
            best = (r, i)
    return best


# Whisper sometimes writes "deactivate voice" with Hindi letters, or drops the "de".
# These are turned into plain English words first, so the words can be compared properly.
DEV_WAKE = {
    "डीएक्टिवेट": "deactivate", "डी एक्टिवेट": "deactivate", "डिएक्टिवेट": "deactivate",
    "डीऐक्टिवेट": "deactivate", "डी-एक्टिवेट": "deactivate", "डीएक्टिव": "deactivate",
    "डिएक्टिव": "deactivate", "डीएक्टीवेट": "deactivate", "डिएक्टीवेट": "deactivate",
    "एक्टिवेट": "activate", "ऐक्टिवेट": "activate", "एक्टीवेट": "activate", "एक्टिव": "activate",
    "ऐक्टिव": "activate",
    "वॉइस": "voice", "वॉयस": "voice", "वोइस": "voice", "वाइस": "voice", "वॉईस": "voice",
    "वोईस": "voice", "आवाज़": "voice", "आवाज": "voice",
    "बंद": "band", "बन्द": "band",
    "डी एक्टिवेट": "deactivate", "डी एक्टिव": "deactivate", "डिऐक्टिवेट": "deactivate", "डीऐक्टिव": "deactivate",
    "डिएक्टिवेट": "deactivate", "डीएक्टिवेट": "deactivate", "डी-एक्टिवेट": "deactivate", "डी एक्टीवेट": "deactivate",
    "ऐक्टिवेट": "activate", "एक्टीवेट": "activate", "एक्टिवेट": "activate",
    "वॉइस": "voice", "वाॅइस": "voice", "वायस": "voice", "वोयस": "voice", "वाइज": "voice", "वॉयस": "voice",
}


def fix_wake_words(text):
    t = text
    for k in sorted(DEV_WAKE, key=len, reverse=True):
        t = t.replace(k, " %s " % DEV_WAKE[k])
    t = t.lower()
    # "de activate", "the activate", "dee-activate", "deactive", "deactivated" -> deactivate
    t = re.sub(r"\b(?:de|di|dee|dea|the|d)[\s\-]*activate[ds]?\b", "deactivate", t)
    t = re.sub(r"\b(?:deactive|dactivate|deactivated|deactivating|inactivate)\b", "deactivate", t)
    t = re.sub(r"\b(?:activated|activating|active)\b(?=\s+(?:voice|vois|voise|voyce))", "activate", t)
    t = re.sub(r"\b(?:vois|voise|voyce|voic|voys|voyse|boice|voiced|voices)\b", "voice", t)
    # a heard word that is clearly closer to "deactivate" than to "activate" (e.g. "deactivit", "deactivating")
    def _fix_word(m):
        w = m.group(0)
        if w in ("deactivate", "activate") or len(w) < 6:
            return w
        rd = difflib.SequenceMatcher(None, w, "deactivate").ratio()
        ra = difflib.SequenceMatcher(None, w, "activate").ratio()
        if w.startswith(("de", "di", "dee", "dea")) and rd >= 0.8 and rd > ra:
            return "deactivate"
        if w.startswith(("act", "ac")) and ra >= 0.85 and ra > rd:
            return "activate"
        return w
    t = re.sub(r"[a-z]+", _fix_word, t)
    return t


SLEEP_PATTERNS = (r"\bvoice\s+(?:off|band|stop|sleep|disable|deactivate)\b",
                  r"\b(?:turn|switch)\s+off\s+(?:the\s+)?voice\b",
                  r"\b(?:disable|stop)\s+(?:the\s+)?voice\b")


def analyse(text):
    """Returns (how close to 'activate voice', how close to 'deactivate voice', sleep alias?, words after wake, kind).
    kind comes from wake_words.py: 'wake' | 'sleep' | 'phone_on' | 'phone_off' | None."""
    text = fix_wake_words(text)
    pairs = to_pairs(text)
    w, wi = best_match(pairs, WAKE)
    d, _ = best_match(pairs, SLEEP)
    joined = " ".join(c for _, c in pairs)
    alias = any(a in joined for a in SLEEP_ALIASES) or any(re.search(p, joined) for p in SLEEP_PATTERNS)
    if "deactivate" in joined.split():                     # the word itself was heard: it can never be a wake-up
        d, w = max(d, 1.0), min(w, 0.6)
    if features.not_wake(joined):          # e.g. "activate mouse"
        w = min(w, 0.5)
        d = min(d, 0.5)
        alias = False
    rest = " ".join(o for o, _ in pairs[wi + 2:]) if wi >= 0 else ""
    kind, rest2 = wake_words.detect(text)              # "Hello Roe" / "Bye Roe" / "phone control" ... (see wake_words.py)
    if kind == "wake":
        w, d, alias, rest = 1.0, 0.0, False, rest2
    elif kind == "sleep":
        w, d, alias = 0.0, 1.0, True
    return w, d, alias, rest, kind


# ------------------------------------------------------------------
# Speech to text
# ------------------------------------------------------------------
def transcribe_clean(model, audio, language=None, prompt=PROMPT):
    """Speech to text (see speech_fix.py: better Hindi detection, faster Hindi)."""
    try:
        return speech_fix.transcribe(model, audio, language, prompt, STATE, BEAM_SIZE, ALLOWED_LANGS)
    except Exception as e:                  # a speech-model problem must never close the assistant
        print("(speech error, ignored: %s: %s)" % (type(e).__name__, str(e)[:120]))
        return ""


# ------------------------------------------------------------------
# Speaking
# ------------------------------------------------------------------
def say(message, speak=True, extra=""):
    """Shows the reply as text, then speaks it. If you start talking, she stops AT ONCE and listens to you.
    Returns True if it was interrupted."""
    print("\nRoe:", message)
    if extra:
        print(extra)
    if STATE["barged"]:                # you already interrupted during this turn: nothing more is spoken, she listens
        return True
    STATE["interrupted"] = False
    if not (SPEAK_REPLIES and speak and message):
        return False
    if not speaker.speak(message):
        return False
    if BARGE_IN:
        listener.barge_reset(lambda: speaker.first_play)
    while speaker.is_playing():
        if BARGE_IN and listener.poll_barge_in():
            speaker.stop()
            STATE["interrupted"] = True
            STATE["barged"] = True     # the rest of this turn stays silent; your words are handled next
            return True
        time.sleep(0.01)
    clear_queue()                      # do not let the microphone hear the assistant itself
    listener.carry.clear()
    return False


def sources_text(c):
    """One or two links under a web answer. They are only shown, never spoken."""
    if c["action"] != "web" or not web_tools.last["sources"]:
        return ""
    lines = ["  Sources:"]
    for i, (title, url) in enumerate(web_tools.last["sources"][:MAX_LINKS], 1):
        lines.append("   %d. %s\n      %s" % (i, title[:60], url))
    return "\n".join(lines)


# ------------------------------------------------------------------
# One command
# ------------------------------------------------------------------
def handle_command(text):
    norm = actions.normalize(text)
    words = set(norm.split()) | {w.strip("।?.,!") for w in text.split()}
    hindi = brain.is_hindi(text, STATE["lang"])

    def L(message):                                    # the sentence in her language
        return brain.to_hindi(message) if hindi else message

    # "stop phone control" / "phone control" (also mis-heard spellings and Hindi, see wake_words.py)
    _k = wake_words.detect(text)[0]
    if _k == "quit":                                   # "quit program" / "exit Roe": closes everything
        say(L("Closing the program. Bye bye!"))
        raise KeyboardInterrupt
    if _k == "phone_off" and phone_control.ACTIVE:
        say(L(phone_control.leave()) or L("Phone control is off."))
        return
    if _k == "phone_off" and not phone_control.ACTIVE:
        say(L("Phone control is not on."))
        return
    if _k == "phone_on" and not phone_control.ACTIVE:
        say(L(phone_control.enter()))
        return
    if _k == "phone_on" and phone_control.ACTIVE:
        say(L("Phone control is already on."))
        return

    # PHONE MODE: while it is on, everything you say goes to the phone
    if phone_control.ACTIVE:
        reply = phone_control.handle(text)
        if reply:
            say(personality.decorate(L(reply), None, hindi))      # sometimes a light "Aye aye, captain!"
        return
    if phone_control.wants_enter(text):
        say(L(phone_control.enter()))
        return

    # waiting for "yes" after a risky command
    if features.has_followup():          # e.g. "first or second?" after a screen click
        _r = features.followup(text, hindi)
        if _r is not None:
            say(_r)
            return
    if STATE["pending"]:
        pending, STATE["pending"] = STATE["pending"], None
        if words & YES_WORDS and not (words & NO_WORDS):
            say(L(brain.run(pending)))
        else:
            say(L("Okay, cancelled."))
        return

    # "stop" right after you interrupted it just means: be quiet and listen
    if STATE["interrupted"] and norm in STOP_PHRASES:
        STATE["interrupted"] = False
        return

    c, source = brain.understand(text, hindi)
    if c is None:
        say(L("Sorry, I did not catch that. Could you say it again?"))
        return
    if SHOW_DETAILS:
        print("(understood by %s: %s%s)" % (source, c["action"], ", Hindi" if hindi else ""))
    if c["risky"]:
        STATE["pending"] = c
        say(L("%s Are you sure? Say yes or no." % c["say"]))
        return
    result = brain.run(c)
    if hindi and c["action"] not in ALREADY_SPOKEN and c["action"] not in features.NO_TRANSLATE:
        result = brain.to_hindi(result)
    brain.remember(text, c, result)
    result = personality.decorate(result, c["action"], hindi)       # sometimes a light "Roger that!" in front
    if c["action"] == "stop_reading":
        speaker.stop()
    say(result, speak=c["action"] not in ALREADY_SPOKEN, extra=sources_text(c))


# ------------------------------------------------------------------
# "I am still here" reminder and goodbye
# ------------------------------------------------------------------
REMINDERS_EN = ["I am still here and listening.",
                "Just a reminder, I am active. Tell me what you need.",
                "Still with you! Say Bye Roe when you want me to stop.",
                "I am awake and listening, whenever you are ready."]
REMINDERS_HI = ["मैं अभी भी यहीं हूँ और सुन रही हूँ।",
                "बस याद दिला रही हूँ, मैं एक्टिव हूँ। बताइए क्या करना है।",
                "मैं आपके साथ हूँ! रुकने के लिए 'बाय रो' बोलिए।"]
BYES_EN = ["Bye bye!", "Goodbye! Say Hello Roe when you need me.", "See you soon!"]
BYES_HI = ["बाय बाय!", "फिर मिलते हैं!", "अलविदा! ज़रूरत हो तो 'हेलो रो' बोलिए।"]
_last_line = {"r": "", "b": ""}


def _pick(options, key):
    choices = [o for o in options if o != _last_line[key]] or options
    _last_line[key] = random.choice(choices)
    return _last_line[key]


def remind_active():
    """She says she is still active (after REMIND_AFTER seconds without you speaking)."""
    hindi = STATE.get("lang") == "hi"
    if phone_control.ACTIVE:
        msg = ("फोन कंट्रोल अभी चालू है। बंद करने के लिए 'स्टॉप फोन कंट्रोल' बोलिए।" if hindi else
               "Phone control is still on. Say stop phone control to end it.")
    else:
        msg = _pick(REMINDERS_HI if hindi else REMINDERS_EN, "r")
    print(bold("(voice is still ON)"))
    say(msg)


def say_bye():
    if SPEAK_GOODBYE:
        say(_pick(BYES_HI if STATE.get("lang") == "hi" else BYES_EN, "b"))


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
def main():
    global speaker, listener
    try:                                   # show Hindi letters (and never crash if the screen cannot)
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    try:
        os.system("chcp 65001 >nul")       # console code page UTF-8
        os.system("")                      # switches on bold text in the Windows console
    except Exception:
        pass
    brain.VERBOSE = SHOW_DETAILS
    model = speech_fix.load_model(SPEECH_MODEL)          # best device (graphics card if there is one) + warm-up
    speech_fix.preload_hindi(model)                      # the bigger Hindi model loads in the background
    speaker = voice_out.Speaker()
    listener = vad.Listener()
    reminders.on_ring = speaker.speak
    missed = reminders.load()

    ai_on = brain.USE_GROQ and llm.available()
    if SHOW_DETAILS:
        print("Model ready.")
        print("  AI brain (Groq)  : %s" % ("ON" if ai_on else "OFF (no GROQ_API_KEY) - keyword matcher only"))
        print("  Voice detection  : %s" % ("Silero VAD + volume gate" if listener.vad_ok
                                           else "volume gate only (Silero not found)"))
        print("  Spoken voice     : %s" % ("neural voice (edge-tts)" if speaker.engine == "neural"
                                           else "Windows voice  (%s)" % (speaker.problem or "turned off")))
        print("  Web search       : %s" % ("ON" if web_tools.have_search()
                                           else "OFF (run: py -3.11 -m pip install ddgs)"))
        print("  Spotify auto-play: %s\n" % ("API keys found" if music.spotify_api_configured()
                                             else "OFF (opens the Spotify search page instead)"))
    else:                                  # only tell her about things that are NOT working
        if not ai_on:
            print("Note: no GROQ_API_KEY found, so only simple commands will work.")
        if speaker.engine != "neural":
            print("Note: using the Windows voice (%s)." % (speaker.problem or "neural voice turned off"))
        if not web_tools.have_search():
            print("Note: web search is OFF (run: py -3.11 -m pip install ddgs).")

    active = False
    last_active = time.time()
    try:
        with sd.InputStream(samplerate=RATE, channels=1, blocksize=BLOCK,
                            dtype="float32", device=MIC_DEVICE, callback=callback):
            print("Measuring the room noise - please stay quiet for one second...")
            listener.calibrate(1.0)
            for m in missed:
                say("While I was closed, I missed this: %s" % m)
            print('Ready. Say  ' + bold('"Hello Roe"') + '  (or ' + bold('"activate voice"') + ')  to start.   (Ctrl+C to quit)\n')

            def go_sleep(by_idle=False):
                """Voice OFF (used by 'Bye Roe', 'deactivate voice' and the long-silence timeout)."""
                nonlocal active
                if not by_idle:
                    say_bye()
                active = False
                STATE["pending"] = None
                brain.forget()
                beep(700, 150)
                print(bold('Voice is OFF.') + ' Say ' + bold('"Hello Roe"') + ' (or ' + bold('"activate voice"')
                      + ') to start again.\n')

            if "--phone" in sys.argv:                      # started from the phone shortcut
                active = True
                last_active = time.time()
                beep(1200, 100)
                print('Voice is ON in PHONE mode. Say ' + bold('"Hello Roe"') + ' to control the laptop instead.\n')
                say(phone_control.enter())

            reminded = 0                                   # "I am still here" reminders given in this quiet stretch
            while True:
                audio = listener.listen(
                    wait_seconds=REMIND_AFTER if active else None,
                    ignore_while=speaker.is_playing,
                    on_barge_in=speaker.stop if BARGE_IN else None,
                    sound_started=lambda: speaker.first_play)

                if audio is None:                              # nobody spoke for REMIND_AFTER seconds
                    if active:
                        if time.time() - last_active > IDLE_SLEEP_MINUTES * 60:
                            phone_control.leave(quiet=True)
                            print('(no commands for %d minutes)' % IDLE_SLEEP_MINUTES)
                            go_sleep(by_idle=True)
                        elif reminded < REMIND_MAX:
                            reminded += 1
                            remind_active()                    # "I am still here and listening."
                            print()
                    continue

                reminded = 0
                STATE["barged"] = False                        # you are talking now, so she may answer again
                t0 = time.time()
                if active:
                    text = transcribe_clean(model, audio, SESSION_LANGUAGE,
                                            phone_control.WHISPER_PROMPT if phone_control.ACTIVE else PROMPT)
                else:
                    text = transcribe_clean(model, audio, "en", WAKE_PROMPT)
                clear_queue()
                if not text:
                    continue
                w, d, alias, rest, kind = analyse(text)

                if not active:
                    if kind == "wake" or (w >= WAKE_MATCH and w >= d and kind != "sleep"):
                        active = True
                        last_active = time.time()
                        beep(1200, 100)
                        print(bold('Voice is ON.') + ' Say ' + bold('"Bye Roe"') + ' (or ' + bold('"deactivate voice"')
                              + ') to stop.  Say ' + bold('"phone control"') + ' to control your phone.\n')
                        say(features.greeting())
                        if len(rest.split()) >= 2:
                            handle_command(rest)
                    elif SHOW_DETAILS:
                        print("(sleeping) heard: %s" % text)
                    continue

                # ----- active -----
                last_active = time.time()
                print('You: %s' % features.show_text(text) + (("   (%.1f s)" % (time.time() - t0)) if SHOW_DETAILS else ""))
                if STATE["confirm_sleep"]:                     # she was asked: switch the voice off?
                    STATE["confirm_sleep"] = False
                    low = {x.strip("।?.,!") for x in fix_wake_words(text).split()}
                    if (low & YES_WORDS and not (low & NO_WORDS)) or (d >= SLEEP_MATCH and d > w) or alias:
                        phone_control.leave(quiet=True)
                        go_sleep()
                    else:
                        say("Okay, I will keep listening.")
                    print()
                    continue
                if kind == "wake":                             # "Hello Roe" while she is already on = "yes, I am here"
                    if phone_control.ACTIVE:
                        say(phone_control.leave())             # back to the laptop (same as "activate voice" in phone mode)
                    else:
                        say(_pick(["Yes, I am here.", "I am listening.", "Yes? What can I do for you?"], "r"))
                    if len(rest.split()) >= 2:
                        handle_command(rest)
                    print()
                    continue
                if phone_control.ACTIVE:
                    if (d >= SLEEP_MATCH and d > w) or alias:      # "Bye Roe" / "deactivate voice": close the phone AND sleep
                        phone_control.leave(quiet=True)
                    elif w >= WAKE_MATCH and w >= d and len(rest.split()) < 3:     # "activate voice": back to the laptop
                        say(phone_control.leave())
                        if len(rest.split()) >= 2:
                            handle_command(rest)
                        print()
                        continue
                if (d >= SLEEP_MATCH and d > w) or alias:
                    go_sleep()
                elif w >= 0.9 and w >= d and len(rest.split()) < 2 and ACTIVATE_WHILE_ON_SLEEPS:
                    go_sleep()                                 # "activate voice" while already on = a mis-heard "deactivate voice"
                elif w >= 0.9 and w >= d and len(rest.split()) < 2:
                    # Voice is already on. "activate voice" is very often "deactivate voice" with the
                    # "de" lost by the speech recogniser, so ask instead of guessing.
                    STATE["confirm_sleep"] = True
                    say("I am already on. Do you want me to switch the voice off? Say yes or no.")
                else:
                    handle_command(rest if (w >= 0.9 and w >= d) else text)
                last_active = time.time()
                print()
    except KeyboardInterrupt:
        print("\nStopped with Ctrl+C.")
        speaker.stop()
    finally:
        phone_control.leave(quiet=True)


def _hard_exit_on_ctrl_c():
    """Ctrl+C (or closing the window) ends the program AT ONCE, even if the speech model or the graphics card
    is busy. Windows runs this in its own thread, so it works when the normal Ctrl+C would be stuck."""
    try:
        import ctypes
        handler_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

        def handler(event):
            if event in (0, 1, 2, 5, 6):               # Ctrl+C, Ctrl+Break, window closed, logoff, shutdown
                try:
                    phone_control.leave(quiet=True)    # closes the phone screen window if it is open
                except Exception:
                    pass
                os._exit(0)
            return 0
        _hard_exit_on_ctrl_c.keep = handler_type(handler)      # must stay alive
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_hard_exit_on_ctrl_c.keep, True)
    except Exception:
        pass                                           # not Windows: normal Ctrl+C is used


if __name__ == "__main__":
    _hard_exit_on_ctrl_c()
    try:
        main()
    finally:
        sys.stdout.flush()
        os._exit(0)                  # make sure nothing (speech model, graphics card, background threads) keeps her open

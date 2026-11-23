"""
ROGER THAT - performance test (fills Table 4.2 "Actual Value" column)
Free: uses faster-whisper (open source) + Groq free API. Run on your own laptop.

Run:   python performance_test.py
It will ask you to speak a few sentences, then print and save the numbers.
"""
import os
import re
import sys
import time
import statistics

import numpy as np
import requests
import sounddevice as sd
from faster_whisper import WhisperModel

SR = 16000
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"   # same model as ROGER THAT

ENGLISH = [
    "open google chrome",
    "what is the weather today",
    "set a timer for five minutes",
    "turn off bluetooth",
    "play some music",
]
HINDI = [
    "क्रोम खोलो",
    "आज मौसम कैसा है",
    "पाँच मिनट का टाइमर लगाओ",
    "ब्लूटूथ बंद करो",
    "गाना चलाओ",
]
REPEATS = 10  # for the stability test


# ---------- helpers ----------
def get_groq_key():
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key and os.path.exists(".env"):
        for line in open(".env", encoding="utf-8", errors="ignore"):
            if line.strip().startswith("GROQ_API_KEY"):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key:
        key = input("Paste your Groq API key (it is not saved): ").strip()
    return key


def load_model():
    """Try GPU first; if the GPU files are missing, fall back to CPU automatically."""
    silence = np.zeros(SR, dtype="float32")
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            print("Trying Whisper 'small' on GPU (float16)...")
            m = WhisperModel("small", device="cuda", compute_type="float16")
            m.transcribe(silence, language="en")  # forces the GPU libraries to load
            list(m.transcribe(silence, language="en")[0])
            print("Using GPU.")
            return m, "GPU"
    except Exception as e:
        print("GPU not usable (" + str(e)[:80] + ")")
        print("Switching to CPU - this is fine, results are just a bit slower.")
    print("Loading Whisper 'small' on CPU (int8)...")
    return WhisperModel("small", device="cpu", compute_type="int8"), "CPU"


def record():
    """Press Enter to start, Enter again to stop. Returns float32 audio."""
    chunks = []

    def cb(indata, frames, t, status):
        chunks.append(indata.copy())

    input("   Press Enter, then speak ... ")
    with sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=cb):
        input("   (recording) press Enter when you finish speaking ")
    stop_time = time.perf_counter()
    audio = np.concatenate(chunks).flatten() if chunks else np.zeros(SR, dtype="float32")
    return audio, stop_time


def transcribe(model, audio, lang):
    t0 = time.perf_counter()
    segs, _ = model.transcribe(audio, language=lang, beam_size=1)
    text = " ".join(s.text.strip() for s in segs).strip()
    return text, time.perf_counter() - t0


def ask_llm(key, text):
    t0 = time.perf_counter()
    r = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": "Reply in one short sentence."},
                {"role": "user", "content": text or "hello"},
            ],
            "max_completion_tokens": 200,
        },
        timeout=40,
    )
    r.raise_for_status()
    return time.perf_counter() - t0


def norm(s):
    s = s.lower()
    s = re.sub(r"[.,!?;:\"'()\[\]{}\-।|]", " ", s)
    return s.split()


def wer(ref, hyp):
    r, h = norm(ref), norm(hyp)
    if not r:
        return 0.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)


def avg(x):
    return statistics.mean(x) if x else float("nan")


# ---------- tests ----------
def speech_test(model, key, sentences, lang, label):
    print(f"\n=== {label} test: read each sentence aloud ===")
    stt, llm, e2e, wers = [], [], [], []
    for i, ref in enumerate(sentences, 1):
        print(f"\n[{i}/{len(sentences)}] Say:  {ref}")
        audio, stop = record()
        text, t_stt = transcribe(model, audio, lang)
        try:
            t_llm = ask_llm(key, text)
        except Exception as e:
            print("   Groq error:", e)
            t_llm = float("nan")
        total = time.perf_counter() - stop
        w = wer(ref, text) * 100
        print(f"   Heard : {text}")
        print(f"   STT {t_stt:.2f}s | LLM {t_llm:.2f}s | End-to-end {total:.2f}s | WER {w:.0f}%")
        stt.append(t_stt)
        llm.append(t_llm)
        e2e.append(total)
        wers.append(w)
    return stt, llm, e2e, wers


def stability_test(model, key):
    print(f"\n=== Stability test: one sentence, {REPEATS} repeated runs ===")
    print("Say:  open google chrome")
    audio, _ = record()
    ok, times = 0, []
    for n in range(1, REPEATS + 1):
        t0 = time.perf_counter()
        try:
            text, _ = transcribe(model, audio, "en")
            ask_llm(key, text)
            ok += 1
            times.append(time.perf_counter() - t0)
            print(f"   run {n}: OK  ({times[-1]:.2f}s)")
        except Exception as e:
            print(f"   run {n}: FAILED ({e})")
    return ok, times


def ask_int(q):
    while True:
        try:
            return int(input(q).strip())
        except ValueError:
            print("   Please type a whole number.")


def main():
    key = get_groq_key()
    model, device = load_model()
    # warm-up so model start-up time is not counted
    transcribe(model, np.zeros(SR, dtype="float32"), "en")

    e_stt, e_llm, e_e2e, e_wer = speech_test(model, key, ENGLISH, "en", "ENGLISH")
    h_stt, h_llm, h_e2e, h_wer = speech_test(model, key, HINDI, "hi", "HINDI")
    ok, times = stability_test(model, key)

    print("\n=== Command success rate (test in ROGER THAT itself) ===")
    print("Now use ROGER THAT for real: try about 20 different commands")
    print("(open app, Wi-Fi, volume, weather, music, phone call...).")
    tested = ask_int("How many commands did you test? ")
    worked = ask_int("How many worked correctly?       ")
    rate = 100 * worked / tested if tested else 0

    all_stt = e_stt + h_stt
    all_llm = [x for x in e_llm + h_llm if x == x]
    all_e2e = e_e2e + h_e2e
    lines = [
        "VALUES FOR TABLE 4.2 (Actual Value column)",
        f"Speech-to-text time          : {avg(all_stt):.2f} s average",
        f"LLM response time            : {avg(all_llm):.2f} s average",
        f"End-to-end response time     : {avg(all_e2e):.2f} s average (speech end to LLM reply)",
        f"English transcription WER    : {avg(e_wer):.1f} %",
        f"Hindi/Hinglish WER           : {avg(h_wer):.1f} %",
        f"Command execution success    : {rate:.0f} % ({worked}/{tested})",
        f"Repeated interaction stability: {ok}/{REPEATS} runs OK, "
        f"{(min(times) if times else 0):.2f}-{(max(times) if times else 0):.2f} s",
        "",
        f"Tested on: {device}, "
        "Whisper small, Groq " + GROQ_MODEL,
        "Note: end-to-end does not include text-to-speech playback.",
    ]
    print("\n" + "=" * 60)
    print("\n".join(lines))
    print("=" * 60)
    with open("results.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\nSaved to results.txt in this folder.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")

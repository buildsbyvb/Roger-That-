"""
Roe - Step 4: Microphone listening + wake phrase "activate voice"

How it works:
  1. It listens to your microphone all the time (nothing is saved).
  2. When you say "activate voice", it beeps and says: LISTENING.
  3. Then say your command, for example "open my downloads folder".
     It prints what it heard. (Actions come in a later step.)
  You can also say it in one go: "activate voice open my downloads folder".

STOP: click on the black command window and press Ctrl + C.

First run downloads the speech model (about 140 MB). It needs internet
ONE time only. After that it works offline.
"""
import difflib
import queue
import re
import threading
import time

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

try:
    import winsound
except ImportError:
    winsound = None

# ---------------- Settings you can change ----------------
WAKE_PHRASE = "activate voice"
MODEL_SIZE = "base"        # "tiny" = faster but less accurate, "small" = slower but better
MIC_DEVICE = None          # None = default microphone
MIN_VOLUME = 0.012         # raise it (e.g. 0.02) if background noise triggers it
SILENCE_END = 0.8          # seconds of silence that end a sentence
MAX_SECONDS = 8            # longest sentence it will record
COMMAND_WAIT = 8           # seconds it waits for your command after the wake phrase
WAKE_MATCH = 0.70          # how close the heard words must be to the wake phrase (0 to 1)
# ---------------------------------------------------------

RATE = 16000
BLOCK = 480                # 30 milliseconds
audio_q = queue.Queue()


def beep(freq=1200, ms=80):
    if winsound is not None:
        threading.Thread(target=winsound.Beep, args=(freq, ms), daemon=True).start()


def callback(indata, frames, time_info, status):
    audio_q.put(indata[:, 0].copy())


def clear_queue():
    while not audio_q.empty():
        try:
            audio_q.get_nowait()
        except queue.Empty:
            break


def find_wake(text):
    """Looks for the wake phrase in text (allows small mishearings).
    Returns (found, words_after_the_phrase)."""
    words = re.sub(r"[^\w\s]", " ", text.lower()).split()
    n = len(WAKE_PHRASE.split())
    for i in range(0, max(len(words) - n + 1, 0)):
        chunk = " ".join(words[i:i + n])
        if difflib.SequenceMatcher(None, chunk, WAKE_PHRASE).ratio() >= WAKE_MATCH:
            return True, " ".join(words[i + n:])
    return False, ""


def record_sentence(wait_seconds=None):
    """Waits for speech, records until you stop talking. Returns audio or None."""
    pre = []                 # small memory of audio just before speech starts
    voiced = []
    speaking = False
    loud_blocks = 0
    silent_blocks = 0
    start = time.time()
    blocks_per_sec = RATE / BLOCK

    while True:
        try:
            block = audio_q.get(timeout=0.2)
        except queue.Empty:
            if wait_seconds and not speaking and time.time() - start > wait_seconds:
                return None
            continue
        volume = float(np.sqrt(np.mean(block ** 2)))
        loud = volume > MIN_VOLUME

        if not speaking:
            pre.append(block)
            pre = pre[-10:]                      # keep last 0.3 s
            loud_blocks = loud_blocks + 1 if loud else 0
            if loud_blocks >= 3:
                speaking = True
                voiced = list(pre)
                silent_blocks = 0
            elif wait_seconds and time.time() - start > wait_seconds:
                return None
        else:
            voiced.append(block)
            silent_blocks = 0 if loud else silent_blocks + 1
            too_long = len(voiced) / blocks_per_sec > MAX_SECONDS
            if silent_blocks / blocks_per_sec >= SILENCE_END or too_long:
                audio = np.concatenate(voiced)
                if len(audio) / RATE < 0.4:      # too short = just a noise
                    speaking, voiced, loud_blocks = False, [], 0
                    continue
                return audio.astype(np.float32)


def transcribe(model, audio, language):
    segments, info = model.transcribe(
        audio, language=language, beam_size=1,
        initial_prompt="activate voice" if language == "en" else None,
        condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments).strip()


def main():
    print("Loading speech model '%s' (first time it downloads, please wait)..." % MODEL_SIZE)
    model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    print("Model ready.\n")

    try:
        with sd.InputStream(samplerate=RATE, channels=1, blocksize=BLOCK,
                            dtype="float32", device=MIC_DEVICE, callback=callback):
            print('Say  "%s"  to wake me up.  (Ctrl+C to stop)\n' % WAKE_PHRASE)
            while True:
                # ---------- sleeping: wait for the wake phrase ----------
                audio = record_sentence()
                t0 = time.time()
                heard = transcribe(model, audio, "en")
                found, rest = find_wake(heard)
                clear_queue()
                if not found:
                    print("(ignored) heard: %s" % heard)
                    continue

                beep()
                print("WAKE PHRASE DETECTED  (took %.1f s)" % (time.time() - t0))

                # ---------- awake: get the command ----------
                if len(rest.split()) >= 2:
                    command = rest          # said in one go
                else:
                    print("LISTENING... say your command")
                    audio = record_sentence(wait_seconds=COMMAND_WAIT)
                    if audio is None:
                        print("I heard nothing. Going back to sleep.\n")
                        continue
                    t0 = time.time()
                    command = transcribe(model, audio, None)   # auto language
                    clear_queue()
                    print("(took %.1f s)" % (time.time() - t0))

                print('COMMAND HEARD: "%s"\n' % command)
                print('Say  "%s"  to wake me up again.\n' % WAKE_PHRASE)
    except KeyboardInterrupt:
        print("\nStopped with Ctrl+C.")


if __name__ == "__main__":
    main()

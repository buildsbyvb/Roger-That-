# Roe update: hearing, speed, Hindi, wake words, "I am still here"

HOW TO INSTALL: copy ALL files from this folder into your project folder and replace the old ones.
NEW file: wake_words.py.   CHANGED: voice_assistant.py, speech_fix.py, hindi_fix.py, vad.py, voice_out.py, brain.py.
No new pip packages needed. Run as before (py -3.11 voice_assistant.py).

## 1. New wake / sleep / phone phrases (wake_words.py)
| Say                                              | What happens             |
|--------------------------------------------------|--------------------------|
| Hello Roe / Hey Roe / Hi Roe / activate voice    | voice ON                 |
| Bye Roe / Bye bye Roe / Goodbye Roe / deactivate voice | voice OFF (she says "Bye bye!") |
| phone control                                    | phone control ON         |
| stop phone control                               | back to the laptop       |
Hindi works too: हेलो रो, बाय रो, फोन कंट्रोल, फोन कंट्रोल बंद करो.
Mis-hearings are accepted: "Roe" written as row / ro / rho / roh / rose ..., "bye" as by / buy / bai, "stop" as stock.
The phrase must be at the START of the sentence, so "tell him hello roe" does not wake her.
Test it without a microphone:  py -3.11 wake_words.py
"Hello Roe" while she is already ON just answers "Yes, I am here."

## 2. Hearing correctly (speech_fix.py, vad.py, hindi_fix.py)
* Ghost sentences ("Thank you.", "Please subscribe", "ha ha ha ha", the hint read back) are now thrown away.
  "Thank you" / "bye" are only believed when the model is very sure (PHANTOM_MIN_SCORE).
* Stricter confidence: MIN_LOGPROB_EN -1.1 (was -1.5), NO_SPEECH_MAX 0.5 (was 0.6), repeated-text filter.
* The voice detector is stricter about what counts as a voice (NOISE_MULT 2.5, MIN_SPEECH 0.35, VAD threshold 0.5).
* The hint given to Whisper is shorter (long hints were being read back as gibberish).
* While asleep she listens with a hint of just "Hello Roe. Hey Roe. Activate voice."

## 3. Hindi (speech_fix.py, hindi_fix.py)
* Hindi sentences are now heard by a much better model: HINDI_MODEL = "large-v3-turbo" (top of speech_fix.py).
  It downloads once (~1.6 GB) and loads in the background at start-up. If it cannot load, the normal model is used.
* If you speak Hindi twice in a row she stays in Hindi (no second guess).
* Shorter Hindi hint (was echoed back as gibberish).
* If your laptop is slow or has little RAM, set HINDI_MODEL = None.

## 4. Speed (voice_assistant.py, speech_fix.py, brain.py, voice_out.py)
* Uses your NVIDIA graphics card automatically if there is one (3-5x faster), otherwise the processor.
* Model is warmed up at start (the first sentence is no longer slow).
* Clearly-English sentences are heard ONCE (no second pass); beam size 3 -> 2.
* Simple commands ("pause", "next song", "volume 50", "what is the time", "scroll down", "how are you") skip the AI
  and run instantly (brain.py FAST_PATH). Everything else still goes to the AI, which now gives up after 6 s (was 10).
* The first part of a spoken reply is shorter, so her voice starts sooner. Voice speed +10%.
* After every answer you see:  (answer ready 1.4 s after you stopped talking)  - turn off with SHOW_TIMING = False.
HONEST NOTE: on a laptop without a graphics card, a long question to the AI or a Hindi sentence can still take more than
3 seconds. The timing line tells you exactly where the time goes.

## 5. "I am still here" reminder (voice_assistant.py)
After REMIND_AFTER = 20 seconds of silence she says one of a few short lines ("I am still here and listening.", ...).
In Hindi if you were speaking Hindi; in phone mode she says "Phone control is still on...".
REMIND_MAX = 3 reminders in one quiet stretch, then she stays quiet until she goes to sleep (IDLE_SLEEP_MINUTES = 5).
Set REMIND_MAX = 99 if you want a reminder every 20 s forever.

## NOT TESTED WITH A REAL MICROPHONE
I had no microphone, GPU or phone. Tested offline: wake-phrase detection (English + Hindi), the ghost filter, the instant
command path, and that every file loads. Please try: Hello Roe, a few English commands, a Hindi command, stay silent for
20 s, phone control / stop phone control, Bye Roe.
If she still mishears English, set SPEECH_MODEL = "medium" in voice_assistant.py (slower, most accurate).

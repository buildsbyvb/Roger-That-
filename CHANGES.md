# Roe - what changed (copy these files over your project folder, replacing the old ones)

NEW FILES:   personality.py, hindi_fix.py
CHANGED:     brain.py, voice_assistant.py, greetings.py, phone_control.py, phone_link.py, smart_pick.py,
             speech_fix.py, actions.py, hindi_fast.py (+ every "Do It" is now "Roe")

1. Fun replies      personality.py. About 45% of finished tasks start with "Aye aye, captain!", "Roger that!", "On it!" ...
                    Change CHANCE (0 = never, 1 = always) or the phrase lists inside the file.
2. Videos on phone  phone_control.py. The screen is now read up to 3 times in 2 styles (YouTube keeps playing previews, so
                    Android often returned nothing), and videos are found 3 ways (description, 16:9 thumbnails, ids).
3. SMS              phone_link.py + phone_control.py. "S M S", "S.M.S", "as MS", "text message", "messages app" all mean SMS now,
                    and the message opens in the phone's OWN default messages app. SMS_AUTO_SEND = False in phone_link.py
                    if you only want it written (draft) and not sent.
4. Hindi            hindi_fix.py + speech_fix.py. Hindi hint for Whisper, wider search for Hindi, mis-spelt command words are
                    repaired, many more Hindi words/numbers (दूसरा, तीसरा, वीडियो, एसएमएस ...).
                    For the best Hindi set HINDI_MODEL = "medium" at the top of speech_fix.py (slower, downloads ~1.5 GB once).
5. Inside apps      Phone: "open images" / "open the third folder" / "tap downloads" taps what is written on the screen.
                    Laptop: "open <word>" first clicks that exact word on the window in front (smart_pick.open_visible).

NOT TESTED ON YOUR PHONE: I had no phone. The parsing was tested offline with fake screens. Please try each case once.

---
## Language fix (English first, Hindi second)
Files changed: speech_fix.py, voice_assistant.py, vad.py  (copy over the old ones)

1. English is the main language. Hindi is used only when the sound is clearly Hindi.
   Before, Hindi + Urdu + Punjabi + Marathi + Bengali ... were all counted as "Hindi", and a Hindi word list was added
   to the hint, so short English phrases like "deactivate voice" were written in Hindi. Now only Hindi/Urdu count.
2. When it is unclear (short phrase, noisy room) she listens both ways and keeps the better one, English favoured.
   "activate voice" / "deactivate voice" are always taken as English.
3. If you speak Hindi (clear Hindi), she writes Hindi and answers in Hindi. English in = English out.
4. "deactivate voice" is easier to hear: many more spellings (English + Devanagari), mis-heard words like
   "deactivit / deactivated / the activate" are repaired, and also "deactivate", "voice off", "stop voice",
   "go to sleep", "आवाज़ बंद" work. SLEEP_MATCH lowered 0.80 -> 0.75.
5. "Voice is ON / OFF" and the wake/sleep words are shown in BOLD on the screen.
6. Fewer mishearings: BEAM_SIZE 1 -> 3, and END_SILENCE 0.45 -> 0.55 (sentences were sometimes cut in half).
   If she feels slow, set BEAM_SIZE = 2 in voice_assistant.py. If she cuts you off, raise END_SILENCE in vad.py.
Tip: SPEECH_MODEL = "small" is the minimum for good accuracy. "medium" is best (slower).

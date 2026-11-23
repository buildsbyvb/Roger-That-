# Roe update: Hindi now works, understands basic Hindi, answers in Hindi, and is faster

HOW TO INSTALL: copy these 4 files into your project folder and replace the old ones:
    hindi_fix.py   hindi_fast.py   speech_fix.py   brain.py      (brain.py: only 9 lines added, in understand())
Nothing else changed. No new pip packages. Run as before.

## 1. Why Hindi was not heard at all (speech_fix.py)
When she listened with automatic language detection and found Hindi, the words were checked against the ENGLISH
confidence limit (-1.1). Hindi always scores lower, so every Hindi word was thrown away, the sentence became empty,
and the Hindi pass never even started. Now Hindi found by auto-detect is judged by the Hindi limit (MIN_LOGPROB_HI = -1.6).
(Tested against your old file with a simulated model: old = empty text for every Hindi sentence, new = heard.)

## 2. Basic Hindi is understood instantly (hindi_fix.py)  - no internet, no AI
Works in Devanagari and in Hindi written with English letters. Spelling does not have to be perfect.
| You say                                         | She does                         |
|-------------------------------------------------|----------------------------------|
| समय क्या हुआ है / अभी कितने बजे हैं / टाइम बताओ   | tells the time                   |
| आज की तारीख क्या है / आज क्या दिन है             | tells the date                   |
| मौसम कैसा है / कल का मौसम / पुणे का मौसम / बारिश होगी क्या | weather (today / tomorrow / a city) |
| ब्राइटनेस बढ़ाओ / कम करो / पचास करो / फुल करो     | brightness up / down / to a level|
| आवाज़ बढ़ाओ / कम करो / वॉल्यूम 30 करो / म्यूट करो  | volume                           |
| विंडो (या टैब) मिनिमाइज़ / मैक्सिमाइज़ करो, क्रोम मिनिमाइज़ करो | minimize / maximize (a named app too) |
| सब मिनिमाइज़ करो / डेस्कटॉप दिखाओ                  | show the desktop                 |
| नया टैब खोलो / अगला टैब / पिछला टैब / टैब बंद करो  | tabs                             |
| नीचे / ऊपर स्क्रॉल करो, स्क्रीनशॉट लो, रिफ्रेश करो, पीछे जाओ | scroll, screenshot, refresh, back |
| गाना रोको / अगला गाना / गाना बदलो / गाना चलाओ     | music (a song NAME still goes to the AI) |
| वाईफाई / ब्लूटूथ चालू / बंद करो, लैपटॉप लॉक करो   | Wi-Fi, Bluetooth, lock           |
| पाँच मिनट का टाइमर लगाओ, टाइमर रद्द करो           | timers                           |
| तुम कैसी हो / तुम्हारा नाम क्या है / किसने बनाया / धन्यवाद / नमस्ते | small talk, answered in Hindi |
Anything else in Hindi still goes to the AI exactly as before.

## 3. Her answers come back in Hindi at once (hindi_fast.py)
Time, date, weather (today and tomorrow), brightness, volume level, music, Wi-Fi/Bluetooth, window and app messages
now have a ready Hindi sentence, so the slow "ask the AI to translate" step is skipped.

## 4. Faster (speech_fix.py)
* The language is checked first by a quick check that writes no words (the old way wrote a whole sentence first, and for Hindi
  threw it away and did it again with the big model).
* A short Hindi sentence is heard by your normal model first. If it is one of the commands above she is done immediately. Only
  other Hindi sentences go to the big Hindi model (HINDI_MODEL). Switch off with HINDI_QUICK = False.
* The big Hindi model is loaded only once (start-up and your first Hindi sentence used to load it twice).
* A Hindi warm-up at start, so the first Hindi sentence is not slow.
* The Whisper hint now holds the new everyday commands (time, weather, brightness, volume, window).
English behaviour is the same as before (checked with the same test sentences on your old and new files).

## 5. ADD YOUR OWN SENTENCES
Open hindi_fix.py and find MY_SENTENCES (near the middle). Add lines like:
    "टाइम बताओ": "time",
    "बाहर का मौसम कैसा है": "weather",
    "तुम्हारा नाम क्या है": ("reply", "मेरा नाम रो है।"),
The list of action names is written right above it. Close spellings also match.

## NOT TESTED WITH A REAL MICROPHONE
I had no microphone, no Whisper model and no Windows. Tested offline: the Hindi command matcher (100+ sentences), the instant
Hindi replies, the full path from sentence to Hindi answer, that none of the new commands is mistaken for "Bye Roe" /
"Hello Roe" / phone control, and the speech logic with a simulated Whisper. Please try each command in the table once.
If a Hindi command is heard but not understood, tell me the exact words she printed and I will add them.

"""
Roe - a little personality.

When Roe finishes a TASK (open an app, play a song, change the volume, scroll ...), she sometimes adds a short,
polite, light phrase in front of the normal answer:

    "Aye aye, captain! Opening Chrome."        "Roger that! Volume set to 50."        "Consider it done. Opening Spotify."

Rules that keep it professional (change them below if you like):
  * only now and then (CHANCE, and at least MIN_GAP plain replies in between), never the same phrase twice in a row,
  * never for errors, questions, long answers, web answers, small talk, or risky things (delete / shutdown),
  * if the AI already started its reply with a phrase like this, nothing is added again.
"""
import random
import re

# ---------------- Settings you can change ----------------
ENABLED = True
CHANCE = 0.18            # only now and then: about 1 casual task in 5 or 6. 0 = never, 1 = always
MIN_GAP = 3              # at least this many plain replies between two phrases
# ---------------------------------------------------------

EN = ["Aye aye, captain!", "Roger that!", "On it!", "Consider it done.", "Right away!", "Your wish is my command.",
      "Coming right up!", "Leave it to me.", "Absolutely!", "Wilco!", "Say no more."]
HI = ["जी, अभी करती हूँ!", "जो हुक्म!", "बिल्कुल, अभी!", "जी कप्तान!", "समझ गई, अभी लीजिए!", "आप बस कहिए, हो जाएगा!"]

# Only CASUAL tasks may get a phrase. Serious or exact things stay formal: timers, alarms, reminders, lock, type,
# close, bluetooth/wifi, messages, calls, answers, web results, weather, time, date ... are NOT in this list on purpose.
TASK_ACTIONS = {"open_folder", "open_named", "search", "open_website", "play", "play_current", "media",
                "volume", "set_volume", "brightness", "scroll", "click", "window", "open_result", "pick_item",
                "pause", "resume"}
# phone replies (no action name): only these casual ones may get a phrase; messages, calls, battery stay formal
_PHONE_FUN = re.compile(r"^(?:opening|playing|scrolling|volume|brightness|tapped|going|switched|switching)\b", re.I)

_ALREADY = re.compile(r"aye aye|roger that|\bon it\b|consider it done|right away|your wish|coming right up|leave it to me|"
                      r"wilco|say no more|absolutely|जी,|हुक्म|बिल्कुल|कप्तान", re.I)
_BAD = re.compile(r"^\s*(?:sorry|i could not|i cannot|i can not|i do not|i did not|i can only|i can pick|tell me|which app|"
                  r"there is no|your phone did not|windows did not|not able|could not|unable|please |are you sure|"
                  r"okay, cancelled|क्षमा|माफ़|माफ)", re.I)

_last = {"phrase": "", "decorated": False, "since": 99}


def decorate(text, action=None, hindi=False):
    """Returns text, sometimes with a short friendly phrase in front. action=None means a phone reply."""
    try:
        if not ENABLED or not text or len(text) > 140 or _ALREADY.search(text[:60]) or _BAD.match(text):
            _last["decorated"] = False
            return text
        if (action is not None and action not in TASK_ACTIONS) or (action is None and not _PHONE_FUN.match(text)):
            _last["decorated"] = False
            return text
        _last["since"] += 1
        if _last["since"] <= MIN_GAP or random.random() > CHANCE:     # only now and then, never close together
            _last["decorated"] = False
            return text
        pool = [p for p in (HI if hindi else EN) if p != _last["phrase"]]
        phrase = random.choice(pool)
        _last.update(phrase=phrase, decorated=True, since=0)
        return "%s %s" % (phrase, text)
    except Exception:
        return text

"""
Roe - the four "big" phrases, made much easier to hear.

    Hello Roe  / Hey Roe / Hi Roe / activate voice      -> wake up (voice ON)
    Bye Roe    / Bye bye Roe / Goodbye Roe / deactivate voice   -> go to sleep (voice OFF)
    phone control                                       -> start controlling the phone
    quit program / exit Roe / close Roger That          -> closes the whole program
    stop phone control                                  -> back to the laptop

Why a separate file?  The speech model does not know the name "Roe", so it writes row, ro, rho, roh, rose, raw ...
and "bye" comes out as by / buy / bi / bai.  detect() knows all of these, also the Hindi spellings
(हेलो रो, बाय रो, फोन कंट्रोल ...), and returns what the person meant.

detect(text) -> (kind, rest)
    kind : "wake" | "sleep" | "phone_on" | "phone_off" | "quit" | None
    rest : the words said AFTER the phrase ("hello roe open youtube" -> "open youtube"), '' if nothing.

The old phrases "activate voice" / "deactivate voice" are still handled by voice_assistant.py.
"""
import difflib
import re

# ---------------- Words you can add to ----------------
# Everything the speech model may write for the name "Roe":
ROE = r"(?:roe|row|ro|rho|roh|rowe|roo|rou|roa|raw|rau|rose|rowan|rowh|ruo|rooh|road|rho|ro+w|rou|ru)"
HELLO = r"(?:hello|hallo|helo|hullo|hellow|hellooo*|ello|halo|hey|hi|hai|hay|hye|heyy+|hii+|yellow|hell\s*o)"
BYE = r"(?:bye|by|buy|bi|bai|baai|bhai|byee+|bie|goodbye|good\s*bye|gud\s*bye|gudbye|good\s*by)"
STOP = r"(?:stop|stock|stopp|stob|stap|top|stopped|stopping|end|exit|quit|close|leave|off|disable|cancel)"
PHONE = r"(?:phone|mobile|fone|foam|phon|phones|cell|cellphone|smartphone)"
CONTROL = r"(?:control|controls|controlling|controle|kontrol|contro|mode)"

# Devanagari (Hindi) spellings -> plain English letters, so one set of rules covers both
HINDI_MAP = {
    "हेलो": "hello", "हैलो": "hello", "हेल्लो": "hello", "हलो": "hello", "हाय": "hi", "हे": "hey", "हेय": "hey",
    "बाय": "bye", "बाई": "bye", "बाय-बाय": "bye bye", "गुडबाय": "goodbye", "गुड बाय": "goodbye", "अलविदा": "goodbye",
    "रोए": "roe", "रोय": "roe", "रौ": "roe", "रोह": "roe", "रो": "roe", "रॉ": "roe", 
    "फोन": "phone", "फ़ोन": "phone", "मोबाइल": "mobile", "कंट्रोल": "control", "कन्ट्रोल": "control",
    "बंद": "stop", "बन्द": "stop", "रोको": "stop", "रुको": "stop", "खत्म": "stop", "ख़त्म": "stop",
    "एक्टिवेट": "activate", "डीएक्टिवेट": "deactivate", "डिएक्टिवेट": "deactivate", "वॉइस": "voice", "वॉयस": "voice",
}
# -------------------------------------------------------

_DEV = "\u0900-\u097F"
# whole Hindi words only (so "रो" inside "करो" is never touched)
_hindi_rx = re.compile(r"(?<![%s])(%s)(?![%s])" % (_DEV, "|".join(re.escape(k.strip()) for k in
                       sorted(HINDI_MAP, key=len, reverse=True)), _DEV))
_hindi_lookup = {k.strip(): v for k, v in HINDI_MAP.items()}


def clean(text):
    """Lower case, whole Hindi words -> English letters, punctuation -> spaces (Hindi letters are kept)."""
    t = (text or "").replace("।", " ")
    t = _hindi_rx.sub(lambda m: " %s " % _hindi_lookup[m.group(1)], t)
    t = t.lower()
    t = re.sub(r"[^\w\s%s]" % _DEV, " ", t)
    return re.sub(r"\s+", " ", t).strip()


# --- exact-ish patterns (checked first) ---
_WAKE_RX = re.compile(r"\b%s\s+%s\b" % (HELLO, ROE))
_WAKE_FUSED = re.compile(r"\b(?:hello|hallo|helo|hey|hi)(?:roe|row|ro|rho|roh)\b")
_SLEEP_RX = re.compile(r"\b%s(?:\s+%s)?\s+%s\b" % (BYE, BYE, ROE))
_SLEEP_FUSED = re.compile(r"\b(?:bye|goodbye|byebye)(?:roe|row|ro|rho|roh)\b")
_BYE_ALONE = re.compile(r"^(?:bye\s+bye|byebye|goodbye|good\s*bye|bye\s+bye\s+bye)$")

_PHONE_ON = re.compile(r"\b%s\s*%s\b|\b%s\s+(?:my\s+|the\s+|meri\s+|mera\s+)?%s\b|\b%s\s+ko\s+control\b" %
                       (PHONE, CONTROL, r"control", PHONE, PHONE))
_PHONE_OFF_BEFORE = re.compile(r"\b%s\s+(?:the\s+|my\s+)?(?:%s\s*%s|%s)\b|\b%s\s+%s(?:ling)?\b|\b%s\s+controlling\b" %
                               (STOP, PHONE, CONTROL, PHONE, STOP, CONTROL, STOP))
_PHONE_OFF_AFTER = re.compile(r"\b%s\s*%s\s+(?:stop|off|end|band|bandh|ruko|khatam|disable|close)\b" % (PHONE, CONTROL))
_QUIT = re.compile(r"\b(?:quit|exit|close|terminate|shut\s*down|shutdown|stop)\s+(?:the\s+)?(?:program|app|application|assistant|roe|roger\s+that)\b")
_LAPTOP_MODE = re.compile(r"\b(?:laptop|computer|pc)\s+mode\b|\bback\s+to\s+(?:the\s+)?(?:laptop|computer)\b")

# fuzzy fallback targets (used only when the exact patterns fail)
_FUZZ = (("wake", "hello roe", 0.80), ("sleep", "bye roe", 0.80), ("sleep", "bye bye roe", 0.80))


def _fuzzy(s):
    words = s.split()
    best = (None, 0.0, 0, 0)
    for kind, phrase, cut in _FUZZ:
        n = len(phrase.split())
        for i in range(0, len(words) - n + 1):
            chunk = " ".join(words[i:i + n])
            r = difflib.SequenceMatcher(None, chunk, phrase).ratio()
            first = words[i]                       # the first word must be a real hello / bye, not just similar
            if kind == "wake" and difflib.SequenceMatcher(None, first, "hello").ratio() < 0.7:
                continue
            if kind == "sleep" and not re.fullmatch(BYE, first):
                continue
            if r >= cut and r > best[1] and i <= 2:       # the phrase must be at the start
                best = (kind, r, i + n, i)
    if best[0]:
        return best[0], " ".join(words[best[2]:])
    return None, ""


def _at_start(s, m):
    """True if at most 2 other words come before the phrase ("okay hello roe" yes, "tell him hello roe" no)."""
    return len(s[:m.start()].split()) <= 2


def detect(text):
    """Returns (kind, rest). See the top of this file."""
    s = clean(text)
    if not s:
        return None, ""

    # 0) "quit program" / "exit Roe" / "close Roger That": closes the whole program
    if _QUIT.search(s):
        return "quit", ""

    # 1) phone control (checked first so "stop phone control" never counts as "phone control")
    if _PHONE_OFF_BEFORE.search(s) and re.search(r"%s|control|mode" % PHONE, s) or _PHONE_OFF_AFTER.search(s) \
            or _LAPTOP_MODE.search(s):
        return "phone_off", ""
    if _PHONE_ON.search(s):
        return "phone_on", ""

    # 2) bye roe  (before hello roe: "bye" and "hi" are close in sound)
    m = _SLEEP_RX.search(s) or _SLEEP_FUSED.search(s)
    if m and _at_start(s, m):
        return "sleep", s[m.end():].strip()
    if _BYE_ALONE.match(s):
        return "sleep", ""

    # 3) hello roe
    m = _WAKE_RX.search(s) or _WAKE_FUSED.search(s)
    if m and _at_start(s, m):
        return "wake", s[m.end():].strip()

    # 4) small mishearings
    kind, rest = _fuzzy(s)
    return kind, rest


def is_phone_on(text):
    return detect(text)[0] == "phone_on"


def is_phone_off(text):
    return detect(text)[0] == "phone_off"


if __name__ == "__main__":                      # python wake_words.py  -> quick self-test, no microphone needed
    tests = ["Hello Roe", "hello, row", "Hey Ro open YouTube", "hallo rho", "Bye Roe", "by row", "Bye bye Roe",
             "buy buy roe", "goodbye roe", "bye bye", "हेलो रो", "बाय रो", "बाय बाय रो", "phone control",
             "control my phone", "फोन कंट्रोल", "stop phone control", "stock phone control", "फोन कंट्रोल बंद करो",
             "phone control off", "open youtube", "play baby by justin", "what is the time", "hi there"]
    for t in tests:
        print("%-28s -> %s" % (t, detect(t)))

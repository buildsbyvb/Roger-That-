"""
Do It - shows what you said in Hindi as Hindi written in English letters (Hinglish).

Whisper writes Hindi in Devanagari. The program needs that to understand you, so it is NOT changed.
Only the line "You: ..." on the screen is converted, with a small built-in converter (no internet, no package).
Example:  "मुझे गाना बजाओ"  ->  "mujhe gaana bajao"

HINDI_DISPLAY = "roman"        -> mujhe gaana bajao            (default)
HINDI_DISPLAY = "both"         -> mujhe gaana bajao  (मुझे गाना बजाओ)
HINDI_DISPLAY = "devanagari"   -> मुझे गाना बजाओ
"""
import re
import unicodedata

HINDI_DISPLAY = "roman"

_CONS = {"क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh",
         "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t", "थ": "th", "द": "d",
         "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r",
         "ल": "l", "ळ": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h"}
_NUKTA = {"ज": "z", "फ": "f", "ड": "r", "ढ": "rh", "क": "q", "ख": "kh", "ग": "g"}
_MATRA = {"ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri", "े": "e", "ै": "ai",
          "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e", "ॆ": "e", "ॊ": "o"}
_VOWEL = {"अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri", "ए": "e", "ऐ": "ai",
          "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e"}
_DIGITS = {ord(c): str(i) for i, c in enumerate("०१२३४५६७८९")}
_LABIAL = set("पफबभम")


def _word(w):
    """One Devanagari word -> list of [text, kind] pieces; kind 'a' = inherent vowel that may be dropped."""
    out = []
    i, n = 0, len(w)
    while i < n:
        c = w[i]
        if c in _CONS:
            base = _CONS[c]
            j = i + 1
            if j < n and w[j] == "़":
                base = _NUKTA.get(c, base)
                j += 1
            if j < n and w[j] == "्":                         # half letter: no vowel
                out.append([base, "c"])
                i = j + 1
                continue
            if j < n and w[j] in _MATRA:
                out.append([base + _MATRA[w[j]], "m"])        # explicit vowel
                i = j + 1
                continue
            out.append([base + "a", "a"])                      # inherent "a" (may be dropped)
            i = j
        elif c in _VOWEL:
            out.append([_VOWEL[c], "v"])
            i += 1
        elif c in "ंँ":
            nxt = w[i + 1] if i + 1 < n else ""
            out.append(["m" if nxt in _LABIAL else "n", "n"])
            i += 1
        elif c == "ः":
            out.append(["h", "n"])
            i += 1
        elif c == "़":
            i += 1
        else:
            out.append([c, "x"])
            i += 1
    # drop the inherent "a" at the end of the word (kitaaba -> kitaab) and in the middle (karanaa -> karnaa)
    if len(out) > 1 and out[-1][1] == "a":
        out[-1][0] = out[-1][0][:-1]
        out[-1][1] = "d"
    for k in range(1, len(out) - 1):
        if (out[k][1] == "a" and out[k - 1][1] in ("a", "m", "v") and out[k + 1][1] in ("m", "v")):
            out[k][0] = out[k][0][:-1]
            out[k][1] = "d"
    return out


def roman(text):
    """Devanagari -> Hinglish letters. Anything that is not Devanagari stays as it is."""
    if not text or not re.search(r"[\u0900-\u097F]", text):
        return text
    text = unicodedata.normalize("NFD", text).translate(_DIGITS).replace("।", ".")
    parts = re.split(r"([\u0900-\u097F]+)", text)
    res = []
    for p in parts:
        if p and re.match(r"[\u0900-\u097F]", p):
            pieces = _word(p)
            s = "".join(x[0] for x in pieces)
            if s.endswith("aa") and len(s) > 2:                # word end: aa -> a, ee -> i  (ka, hai, ki)
                s = s[:-1]
            elif s.endswith("ee") and len(s) > 2 and pieces[-1][1] == "m":
                s = s[:-2] + "i"
            s = s.replace("chchh", "chh")
            res.append(s)
        else:
            res.append(p)
    return "".join(res)


def show(text):
    """What to print after 'You:'."""
    if HINDI_DISPLAY == "devanagari" or not re.search(r"[\u0900-\u097F]", text or ""):
        return text
    r = roman(text)
    return "%s  (%s)" % (r, text) if HINDI_DISPLAY == "both" else r

"""
Roe - "who made you?" answer (formal and polite), English and Hindi.

Say: "who made you", "who created you", "who is your creator", "tumhe kisne banaya", "तुम्हें किसने बनाया"
Roe answers with the fixed sentence below, in the language you spoke. It works without internet.
Change CREATOR (or the sentences) if you want.
"""
import re

# ---------------- Settings you can change ----------------
CREATOR = "Vaibhavi"
CREATOR_HI = "वैभवी"
# ---------------------------------------------------------

ACTIONS = set()          # this feature uses the normal "answer" action, so it has no action of its own

ANSWER_EN = ("I was created by %s as her capstone project. "
             "It would be my pleasure to assist you." % CREATOR)
ANSWER_HI = ("मुझे %s ने अपने कैपस्टोन प्रोजेक्ट के रूप में बनाया है। "
             "आपकी सहायता करके मुझे बहुत प्रसन्नता होगी।" % CREATOR_HI)

PROMPT = ""              # the AI is told below through EXTRA_RULE

EXTRA_RULE = ('IDENTITY: if asked who made, created, built or developed you, answer (action "answer") formally and '
              'politely that you were created by %s as her capstone project. Never say "a student" or '
              '"final-year project".' % CREATOR)

_EN = [r"\bwho\b.*\b(?:made|created|built|developed|designed|programmed|invented)\b.*\b(?:you|u)\b",
       r"\bwho(?:'s| is| was)?\b.*\byour\b.*\b(?:creator|developer|maker|builder|programmer|owner)\b"]
_HI_ROMAN = [r"\bkisne\b.*\b(?:banaya|banai|banaye|banayi|create|design|develop)",
             r"\b(?:tumhara|aapka|tera)\b.*\b(?:creator|developer|maker)\b.*\bkaun\b"]
_HI_DEV = [r"किसने.*(?:बनाया|बनाई|बनाए|तैयार)", r"(?:तुम्हारा|आपका).*(?:निर्माता|क्रिएटर|डेवलपर).*कौन"]


def parse(text, hindi=False):
    t = text.strip().lower()
    dev = any(re.search(p, t) for p in _HI_DEV)
    rom = any(re.search(p, t) for p in _HI_ROMAN)
    eng = any(re.search(p, t) for p in _EN)
    if not (dev or rom or eng):
        return None
    reply = ANSWER_HI if (dev or rom or (hindi and not eng)) else ANSWER_EN
    return {"action": "answer", "arg": reply, "say": reply, "risky": False}


def to_command(action, args, reply):
    return None


def run(c):
    return None

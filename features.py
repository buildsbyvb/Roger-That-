"""
Roe - the "feature plug-in list".

Every new feature lives in its OWN file (screen_reader.py, ...). This small file loads them and gives
brain.py and voice_assistant.py ONE place to ask. Adding a feature later = add its file name to
MODULE_NAMES below. If a feature file cannot be loaded (for example a package is missing), the rest of
Roe still works and one note is printed.

A feature file must have:  ACTIONS (set), PROMPT (text for the AI), parse(text, hindi), to_command(action, args, reply),
run(command).  Optional: NO_TRANSLATE (set), has_followup(), followup(text, hindi).
"""
import importlib

# ---------------- Add new feature files here ----------------
MODULE_NAMES = ["smart_pick", "walk_guard", "identity", "phone_link"]   # smart_pick must stay FIRST
# ------------------------------------------------------------

_mods = []
for _n in MODULE_NAMES:
    try:
        _mods.append(importlib.import_module(_n))
    except Exception as _e:                          # a broken feature must never stop Roe
        print("(Note: feature '%s' was not loaded: %s)" % (_n, _e))

ACTIONS = set()
NO_TRANSLATE = set()
PROMPT = ""
for _m in _mods:
    ACTIONS |= set(_m.ACTIONS)
    NO_TRANSLATE |= set(getattr(_m, "NO_TRANSLATE", ()))
    if _m.PROMPT:
        PROMPT += ("\n" if PROMPT else "") + _m.PROMPT
EXTRA_RULES = "\n".join(getattr(_m, "EXTRA_RULE", "") for _m in _mods if getattr(_m, "EXTRA_RULE", ""))


def add_to_prompt(system):
    """Adds the feature actions to the Groq prompt (just before 'WHEN TO USE web:')."""
    add = (PROMPT + "\n\n" if PROMPT else "")
    if add and add.strip() in system:
        add = ""
    marker = "WHEN TO USE web:"
    if add:
        system = system.replace(marker, add + marker, 1) if marker in system else system + "\n" + add
    if EXTRA_RULES and EXTRA_RULES not in system:
        system += "\n" + EXTRA_RULES
    return system


def parse(text, hindi=False):
    for m in _mods:
        c = m.parse(text, hindi)
        if c is not None:
            return c
    return None


def to_command(action, args, reply):
    for m in _mods:
        if action in m.ACTIONS:
            return m.to_command(action, args, reply)
    return None


def run(c):
    for m in _mods:
        if c["action"] in m.ACTIONS:
            return m.run(c)
    return None


def has_followup():
    return any(getattr(m, "has_followup", lambda: False)() for m in _mods)


def followup(text, hindi=False):
    for m in _mods:
        f = getattr(m, "followup", None)
        if f is not None:
            r = f(text, hindi)
            if r is not None:
                return r
    return None


def greeting():
    """A different hello each time you say 'activate voice' (see greetings.py)."""
    try:
        import greetings
        return greetings.greeting()
    except Exception:
        return "Hello!"


def not_wake(joined):
    """True if the sentence is about a feature (for example 'activate mouse') and must NOT wake the voice."""
    import re
    return any(getattr(m, "NOT_WAKE", None) and re.search(m.NOT_WAKE, joined) for m in _mods)


def show_text(text):
    """What is printed after 'You:'. Hindi is shown in English letters (see hindi_display.py)."""
    try:
        import hindi_display
        return hindi_display.show(text)
    except Exception:
        return text


def quick_hindi(message):
    """Instant Hindi for common replies (see hindi_fast.py). None = ask the AI to translate."""
    try:
        import hindi_fast
        return hindi_fast.quick(message)
    except Exception:
        return None

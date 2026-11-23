"""
Roe - Step 10: The "brain" (short human answers + small talk + volume/brightness + web search + music + reminders)

understand(text) -> (command, source)
    Sends what you said, together with the last few turns of the conversation,
    to Groq (Llama AI). Groq picks ONE action from a FIXED list. Python checks the
    choice before anything runs. If Groq is offline, has no key, or answers badly,
    the keyword matcher is used instead, so the demo never dies.

remember(text, command, result)
    Call after running a command, so follow-up questions work
    ("weather in Pune" ... "and tomorrow?").

run(command) -> sentence
    Does the command. Questions, web search, weather, timers/alarms/reminders,
    music, Wi-Fi / Bluetooth and close-app are done here.
    Everything else goes to actions.execute.

Needs: actions.py, llm.py, reminders.py, web_tools.py, music.py in the same folder,
and the environment variable GROQ_API_KEY (optional: without it the keyword matcher is used).
SAFETY: the AI never runs code. It can only pick an action name from the list and fill in
simple values. Risky actions (delete, shutdown, restart) are marked risky by THIS file,
not by the AI, and always ask "Are you sure?".
"""
import json
import os
import random
import re
import subprocess
import time

import actions
import llm
import music
import reminders
import web_tools
import features

# ---------------- Settings you can change ----------------
GROQ_MODEL = "openai/gpt-oss-20b"          # the FAST model (answers sooner). For smarter but slower use
                                           # "openai/gpt-oss-120b". llm.py falls back to the other by itself.
USE_GROQ = True                            # False = keyword matcher only (backup mode)
GROQ_TIMEOUT = 6                           # seconds to wait for Groq
MEMORY_TURNS = 6                           # how many earlier exchanges it remembers
MEMORY_MINUTES = 10                        # forgets the conversation after this much silence
VERBOSE = False                            # True = also print technical lines (set by voice_assistant.py)
# ---------------------------------------------------------

web_tools.GROQ_MODEL = GROQ_MODEL

SYSTEM = """You are "Roe", a friendly voice assistant living on the user's Windows laptop, like Siri or Google
Assistant: warm, natural, a little playful, never robotic. Your name is Roe. If asked what you are, say you are Roe, a voice
assistant created by Vaibhavi as her capstone project (never say "a student" or "final-year project").
The user speaks English, Hindi or Hinglish, casually, with an Indian accent. The speech recogniser often mishears words
(for example "sign which" = "sandwich", "whether" = "weather"): work out what the user most likely said from the sound of
the words and the context, and act on that.
Use the conversation so far to understand follow-ups and words like "it", "that", "there", "again", "also", "the same"
(after "weather in Pune", "and tomorrow?" means weather, place Pune, day tomorrow).
Pick exactly ONE action. Answer with ONLY a JSON object: {"action": "<n>", "args": {...}, "reply": "<short sentence>"}
"reply" is spoken aloud by a female voice.
LANGUAGE: the last line of this prompt says whether the user is speaking English or Hindi. If English, reply in English.
If Hindi (or Hinglish, Hindi mixed with English), write "reply" in natural spoken Hindi in Devanagari script and use
feminine forms because you are a woman ("मैं खोल रही हूँ"). Keep app, song and place names as they are. Everything inside
"args" (query, song, name, place, text) stays in English letters, so for example a song is "Tum Hi Ho", never Devanagari.
Always fill "reply" with a short friendly confirmation of what you are doing (except for web, where it stays empty).
PERSONALITY: keep every confirmation plain, short and professional. Do NOT add catchphrases or jokes to confirmations
(the program itself adds a light phrase now and then). Only tell a joke when the user asks for one.

HOW LONG TO ANSWER: by default ONE short sentence (or just one word when that is the whole answer). Only when the user
says explain, in detail, elaborate, tell me more, step by step (or clearly wants a long answer) give up to 5 short sentences.
Never use lists, markdown, brackets, citation numbers like [1], or links in a reply.

SMALL TALK: for "how are you", "what is your name", "thank you", "hello", "good morning", "tell me a joke", "who made you",
"are you real" and similar, use answer and reply the way a friendly human assistant would: warm, short, natural.
Example: "I'm doing great, thanks for asking! What can I do for you?"

ACTIONS (use only these names):
open_folder   args: folder = downloads | documents | desktop | pictures | music | videos | "" (File Explorer)
open_named    args: name (app or file name), kind = "app" | "file"       e.g. open spotify, open word, open resume file
close_app     args: name (the app to close, e.g. "chrome", "spotify")
search        args: query                                                  (just opens a Google page in the browser)
open_website  args: url                                                    e.g. "youtube.com"
play          args: song, service = "spotify" | "youtube"                  (ONLY when the user said a song NAME: "play X" = spotify;
                                                                            "play X on youtube" = youtube)
play_current  args: {}   "play the song", "play music", "play it", "play the song on spotify", "gaana chalao" when the
                         user did NOT say a song name. It continues the song that is already loaded. NEVER pick or
                         suggest a song yourself (no famous or popular songs).
media         args: key = pause | resume | next | previous                 ("change the song", "skip" = next)
volume        args: level = 0 to 100 ("set volume to 50", "volume 30 percent")  OR  direction = up | down | mute
brightness    args: level = 5 to 100 ("brightness 50", "keep my brightness on 50%")  OR  direction = up | down
scroll        args: direction = up | down | top | bottom, amount = little | normal | lot
type          args: text                                                   (types the words on screen)
click         args: kind = left | double | right
key           args: name = close_window | close_tab | new_tab | next_tab | prev_tab | back | forward | refresh | screenshot | select_all | copy | paste | undo | save | enter | notifications | quick_settings | switch_window
window        args: do = minimize | maximize | restore | show_desktop, name = the window or app the user named
                    ("minimize chrome" -> name "chrome"; "maximize spotify" -> name "spotify"), or "" if no name
                    was said. NEVER ask the user to click on a window: just do it.
radio         args: device = wifi | bluetooth, state = on | off
timer         args: seconds (a whole number; 5 minutes = 300)
alarm         args: time = "HH:MM" in 24-hour format (7 pm = "19:00")
reminder      args: message (what to remind, e.g. "call mom"), and EITHER seconds (whole number) OR time = "HH:MM" (24-hour)
cancel_timers args: {}                                                     (stops all timers, alarms and reminders)
list_timers   args: {}                                                     ("what alarms do I have?")
weather       args: place, day = today | tomorrow | day_after
                    place = the city or area the user NAMED in this sentence ("weather in Pune" -> "Pune"). If the user
                    named NO place, place MUST be "" (empty): the program then uses Kharghar, Navi Mumbai. Never guess or
                    invent a place. Only a clear follow-up ("and tomorrow?", "and there?") keeps the earlier place.
web           args: query, kind = general | news | recipe | tutorial, detail = true | false
                    (searches the internet, speaks a short answer and shows the sources. detail = true ONLY if the user
                    asked to explain / in detail. Leave "reply" empty for web.)
open_result   args: number (1 to 5)                                        ("open the first link" after a web search)
time / date / lock / stop_reading     args: {}
read          args: what = selection | all                                 (read text on screen aloud)
power         args: do = shutdown | restart | delete | cancel_shutdown
answer        args: {}   Chat and small talk, jokes, maths, translations, opinions, writing help, questions about yourself.
                         Put the complete short answer in "reply".

WEATHER FIRST: anything about weather, temperature, heat, cold, rain, humidity, "how hot is it", "is it raining",
"will it rain", "do I need an umbrella", "mausam", "garmi", "thand", "barish" is the weather action (never web, never answer).
WHEN TO USE web: real-world facts (who / what / when / where questions about people, places, capitals, science, history,
sports, companies), news, scores, prices, "latest" or "today" things, anyone's current job, recipes, tutorials and how-to
questions. Write "query" so it makes sense alone, with the corrected words (add the topic from earlier turns).
Use answer for chat, small talk, jokes, maths, translations and anything about yourself.
Polite or indirect requests mean the same as direct ones: "could you please open Spotify", "can you open the downloads
folder", "I want to listen to Tum Hi Ho", "would you mind setting a timer" are all commands.
Rules: output JSON only. Never invent action names. If unsure, use answer (or web for facts)."""

# ------------------------------------------------------------------
# Conversation memory
# ------------------------------------------------------------------
SYSTEM = features.add_to_prompt(SYSTEM)

_history = []                      # [(user text, assistant JSON text), ...]
_mem = {"t": 0.0}


def forget():
    _history.clear()


_warned = set()


def _warn_once(msg):
    """Tell her ONCE if the AI brain is not working (instead of spamming every sentence)."""
    if msg not in _warned:
        _warned.add(msg)
        print("(Note: the AI brain is not working: %s. Using the simpler keyword matcher.)" % msg)


def _json_from(raw):
    """Finds the JSON object inside Groq's answer (even if it added extra words)."""
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except ValueError:
        pass
    i, j = raw.find("{"), raw.rfind("}")
    if 0 <= i < j:
        try:
            obj = json.loads(raw[i:j + 1])
            return obj if isinstance(obj, dict) else None
        except ValueError:
            return None
    return None


def clean_reply(text):
    """No [1] citation numbers, no markdown marks, no stray spaces."""
    text = re.sub(r"\[\s*\d+(?:\s*[,-]\s*\d+)*\s*\]", "", text)
    text = re.sub(r"\[(?:citation needed|note \d+|[a-z])\]", "", text, flags=re.I)
    text = re.sub(r"[*#`_~]", "", text)
    text = re.sub(r"\s+([.,!?])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _level(v, low=0):
    """'50', 50, '50%' -> 50 (kept between low and 100). None if it is not a number."""
    try:
        n = int(round(float(str(v).strip().rstrip("%"))))
    except (TypeError, ValueError):
        return None
    return max(low, min(100, n))


def remember(text, c, result):
    """Stores one exchange. c = the command that was run, result = what was said back."""
    obj = dict(c.get("obj") or {"action": c["action"], "args": {}})
    obj["reply"] = (result or "")[:250]
    _history.append((text, json.dumps(obj, ensure_ascii=False)))
    del _history[:-MEMORY_TURNS]
    _mem["t"] = time.time()


# ------------------------------------------------------------------
# Asking Groq
# ------------------------------------------------------------------
def _ask_groq(text, hindi=False):
    """Returns a dict from Groq, or None. The reason for None is in llm.last_error."""
    if time.time() - _mem["t"] > MEMORY_MINUTES * 60:
        forget()
    now = time.strftime("%A %d %B %Y, %I:%M %p")
    lang = ("The user is speaking HINDI right now: write reply in Hindi (Devanagari script, feminine forms)."
            if hindi else "The user is speaking ENGLISH right now: write reply in English.")
    messages = [{"role": "system", "content": SYSTEM + "\nCurrent date and time: " + now + "\n" + lang}]
    for user, assistant in _history:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": text})
    raw = llm.chat(messages, model=GROQ_MODEL, json_mode=True, max_tokens=400,
                   temperature=0.2, timeout=GROQ_TIMEOUT)
    if raw is None:
        return None
    obj = _json_from(raw)
    if obj is None:
        llm.last_error["msg"] = "Groq did not answer in JSON"
    return obj


# ------------------------------------------------------------------
# Checking what Groq chose (only fixed actions pass)
# ------------------------------------------------------------------
def _cmd(action, arg=None, say="", risky=False):
    return {"action": action, "arg": arg, "say": say, "risky": risky}


def _s(v, n=200):
    return str(v).strip()[:n] if v is not None else ""


def to_command(obj):
    """Turns Groq's answer into a command the program can run, or None if it is not allowed."""
    if not isinstance(obj, dict):
        return None
    a = _s(obj.get("action")).lower()
    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
    reply = clean_reply(_s(obj.get("reply"), 700))
    _f = features.to_command(a, args, reply)
    if _f is not None:
        return _f

    def g(k, allowed=None, default=None):
        v = _s(args.get(k)).lower()
        if allowed is None:
            return v
        return v if v in allowed else default

    if a == "answer":
        return _cmd("answer", reply, reply or "I am not sure.") if reply else None
    if a == "open_folder":
        f = g("folder")
        if f == "":
            return _cmd("open_folder", "", reply or "Opening File Explorer.")
        if f in actions.FOLDERS:
            return _cmd("open_folder", actions.FOLDERS[f], reply or "Opening your %s folder." % f)
        return None
    if a == "open_named":
        name = _s(args.get("name"), 60)
        if not name:
            return None
        return _cmd("open_named", (name, g("kind", ("app", "file"), "app")), reply)
    if a == "close_app":
        name = re.sub(r"[^\w .-]", "", _s(args.get("name"), 40)).strip()
        return _cmd("close_app", name, reply or "Closing %s." % name) if len(name) >= 3 else None
    if a == "search":
        q = _s(args.get("query"))
        return _cmd("search", q, reply or "Searching Google for %s." % q) if q else None
    if a == "open_website":
        u = _s(args.get("url"))
        if not re.match(r"^https?://", u):
            u = "https://" + u
        if re.match(r"^https?://[\w-]+(\.[\w-]+)*\.[a-z]{2,}(/\S*)?$", u, re.I):
            return _cmd("open_url", u, reply or "Opening the website.")
        return None
    if a == "play":
        song = _s(args.get("song"), 100)
        if not song or music.is_generic(song):                # no real song name = the current song
            return _cmd("play_current", say=reply or "Playing.")
        service = g("service", ("spotify", "youtube"), "spotify")
        return _cmd("play", (song, service), reply or "Playing %s." % song)
    if a in ("play_current", "play_random"):                  # play_random no longer exists
        return _cmd("play_current", say=reply or "Playing.")
    if a == "media":
        k = g("key", ("pause", "resume", "next", "previous"))
        m = {"pause": "pause", "resume": "play_current", "next": "next_song", "previous": "prev_song"}.get(k)
        if m == "next_song" or m == "prev_song":
            return _cmd(m, say=actions.MEDIA[m][1])
        return _cmd(m, say=reply or ("Paused." if m == "pause" else "Playing.")) if m else None
    if a == "volume":
        lvl = _level(args.get("level"))
        if lvl is not None:
            return _cmd("set_volume", lvl, "Volume set to %d percent." % lvl)
        d = g("direction", ("up", "down", "mute"))
        words = {"up": "Volume up.", "down": "Volume down.", "mute": "Toggling mute."}
        return _cmd("volume", d, words[d]) if d else None
    if a == "brightness":
        lvl = _level(args.get("level"), low=5)
        if lvl is not None:
            return _cmd("brightness", (lvl, ""), "")
        d = g("direction", ("up", "down"))
        return _cmd("brightness", (None, d), "") if d else None
    if a == "scroll":
        d = g("direction", ("up", "down", "top", "bottom"), "down")
        if d in ("top", "bottom"):
            return _cmd(d, say=actions.HOTKEYS[d][1])
        amt = {"little": 300, "normal": 600, "lot": 1500}[g("amount", ("little", "normal", "lot"), "normal")]
        return _cmd("scroll", amt if d == "up" else -amt, "Scrolling %s." % d)
    if a == "type":
        t = _s(args.get("text"), 500)
        return _cmd("type", t, "Typing: %s" % t) if t else None
    if a == "click":
        k = g("kind", ("left", "double", "right"), "left")
        return _cmd({"left": "click", "double": "double_click", "right": "right_click"}[k],
                    say={"left": "Clicking.", "double": "Double clicking.", "right": "Right clicking."}[k])
    if a == "key":
        n = g("name")
        return _cmd(n, say=actions.HOTKEYS[n][1]) if n in actions.HOTKEYS else None
    if a == "window":
        d = g("do", ("minimize", "maximize", "restore", "show_desktop"))
        if d == "show_desktop":
            return _cmd("show_desktop", say=actions.HOTKEYS["show_desktop"][1])
        name = re.sub(r"[^\w .-]", "", _s(args.get("name"), 40)).strip()
        return _cmd("window", (d, name), "") if d else None
    if a == "radio":
        dev = g("device", ("wifi", "bluetooth"))
        st = g("state", ("on", "off"))
        if dev and st:
            label = "Wi-Fi" if dev == "wifi" else "Bluetooth"
            return _cmd("radio", (dev, st == "on"), "Turning %s %s." % (label, st))
        return None
    if a == "timer":
        try:
            sec = int(float(args.get("seconds")))
        except (TypeError, ValueError):
            return None
        return _cmd("timer", sec, "") if 1 <= sec <= 86400 else None
    if a == "alarm":
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", _s(args.get("time")))
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return _cmd("alarm", (int(m.group(1)), int(m.group(2))), "")
        return None
    if a == "cancel_timers":
        return _cmd("cancel_timers", say="Cancelled all timers, alarms and reminders.")
    if a in ("time", "date", "lock", "stop_reading"):
        say = {"time": "", "date": "", "lock": "Locking the laptop.", "stop_reading": "Okay, stopped reading."}[a]
        return _cmd(a, say=say)
    if a == "read":
        return _cmd("read", g("what", ("selection", "all"), "selection"), "Reading aloud.")
    if a == "power":
        d = g("do", ("shutdown", "restart", "delete", "cancel_shutdown"))
        if d == "cancel_shutdown":
            return _cmd("cancel_shutdown", say="Cancelling the shutdown.")
        if d == "shutdown":
            return _cmd("shutdown", say="I will shut down the laptop in 30 seconds.", risky=True)
        if d == "restart":
            return _cmd("restart", say="I will restart the laptop in 30 seconds.", risky=True)
        if d == "delete":
            return _cmd("delete", say="I will delete the selected file.", risky=True)
        return None
    if a == "web":
        q = _s(args.get("query"), 150)
        kind = g("kind", ("general", "news", "recipe", "tutorial"), "general")
        detail = _s(args.get("detail")).lower() in ("true", "yes", "1")
        return _cmd("web", (q, kind, detail), "") if q else None
    if a == "weather":
        place = re.sub(r"[^\w .,'-]", "", _s(args.get("place"), 60)).strip()
        day = {"today": 0, "tomorrow": 1, "day_after": 2}[g("day", ("today", "tomorrow", "day_after"), "today")]
        return _cmd("weather", (place, day), "")
    if a == "reminder":
        msg = _s(args.get("message"), 150) or "your reminder"
        due = None
        try:
            sec = args.get("seconds")
            if sec not in (None, ""):
                sec = int(float(sec))
                if 1 <= sec <= 7 * 86400:
                    due = time.time() + sec
        except (TypeError, ValueError):
            due = None
        if due is None:
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", _s(args.get("time")))
            if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
                due = reminders.next_occurrence(int(m.group(1)), int(m.group(2)))
        return _cmd("reminder", ("Reminder: " + msg.rstrip(".") + ".", due), "") if due else None
    if a == "list_timers":
        return _cmd("list_timers", say="")
    if a == "open_result":
        try:
            n = int(float(args.get("number", 1)))
        except (TypeError, ValueError):
            return None
        return _cmd("open_result", n, "") if 1 <= n <= 5 else None
    return None


# ------------------------------------------------------------------
# Backup keyword understanding (used when Groq is not available)
# ------------------------------------------------------------------
_UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}
_NOT_APPS = {"tab", "window", "this", "that", "it", "the", "app", "file", "folder", "bluetooth",
             "wifi", "music", "song", "gaana", "reading", "volume", "voice", "listening", "laptop",
             "computer", "pc", "everything", "all"}
_NOT_SONGS = {"volume", "awaz", "awaaz", "sound", "light", "brightness"}
_ORDINALS = {"first": 1, "1st": 1, "one": 1, "second": 2, "2nd": 2, "two": 2, "third": 3, "3rd": 3,
             "three": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5}


def _to_24h(h, mi, ap):
    ap = (ap or "").replace(" ", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return (h, mi) if h < 24 and mi < 60 else None


_TALK = [
    (r"\b(how are you|how r you|how do you do|how are you doing|kaise ho|kaisi ho|kya haal)\b",
     ["I'm doing great, thanks for asking! What can I do for you?",
      "I'm good, thank you! How can I help?"]),
    (r"\b(what is your name|what's your name|whats your name|your name|who are you|tum kaun ho|aapka naam)\b",
     ["I'm Roe, your voice assistant. Roger that, always at your service!"]),
    (r"\b(who made you|who created you|who built you|who made u)\b",
     ["I was created by Vaibhavi as her capstone project."]),
    (r"^(?:thanks|thank you|thank you so much|thanks a lot|shukriya|dhanyavad|thanks do it)$",
     ["You're welcome!", "Anytime!", "Happy to help!"]),
    (r"^(?:hello|hi|hey|hey there|hi there|hello there|namaste|hey do it|hi do it)$",
     ["Hi there! What can I do for you?", "Hello! How can I help?"]),
    (r"^good (?:morning|afternoon|evening)(?: do it)?$", ["Hello! Hope you're having a lovely day."]),
    (r"^good night(?: do it)?$", ["Good night! Sleep well."]),
]



# ------------------------------------------------------------------
# Jokes: a different one every time (a shuffled deck: no repeat until all have been told)
# ------------------------------------------------------------------
JOKES = [
    "Why did the computer go to the doctor? Because it had a virus!",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "Why was the laptop cold? It left its Windows open.",
    "There are only 10 kinds of people: those who understand binary and those who do not.",
    "Why did the developer go broke? Because he used up all his cache.",
    "My Wi-Fi and I have a lot in common. We both drop out when it matters most.",
    "Why do Java developers wear glasses? Because they cannot C sharp.",
    "A SQL query walks into a bar, goes up to two tables and asks: can I join you?",
    "Why did the smartphone need glasses? It lost all its contacts.",
    "What is a computer's favourite snack? Microchips.",
    "Why was the JavaScript developer sad? Because he did not know how to null his feelings.",
    "I changed my password to incorrect, so whenever I forget it, the computer says: your password is incorrect.",
    "Why did the keyboard go to school? To improve its typing.",
    "How does a computer get drunk? It takes screenshots.",
    "Why did the assistant cross the road? To get to the other site.",
    "Debugging: being the detective in a crime movie where you are also the murderer.",
    "Why did the Python programmer not get a job? Because he did not meet the requirements.txt.",
    "What do you call a computer that sings? A Dell-a-bration, I mean, a Dell.",
    "Why do robots never panic? They have nerves of steel.",
    "There is no place like 127.0.0.1.",
    "Why did the cloud break up with the server? It needed more space.",
    "I asked my laptop for a joke and it said: let me restart and think about it.",
    "Why was the mouse afraid of the keyboard? It kept getting hit with keys.",
]
_deck = []
_JOKE_RX = re.compile(r"\b(?:tell me a joke|tell a joke|say a joke|tell me another joke|another joke|one more joke|"
                      r"make me laugh|joke suna\w*|ek joke|joke batao|funny joke|crack a joke)\b|जोक|चुटकुला")


def next_joke():
    """The next joke from a shuffled deck. Never the same joke twice in a row, none repeats until all are told."""
    global _deck
    if not _deck:
        last = _joke_state["last"]
        _deck = JOKES[:]
        random.shuffle(_deck)
        if _deck and _deck[-1] == last and len(_deck) > 1:      # the joke told last must not come first again
            _deck[0], _deck[-1] = _deck[-1], _deck[0]
    j = _deck.pop()
    _joke_state["last"] = j
    return j


_joke_state = {"last": ""}


def parse_smalltalk(t):
    for pattern, replies in _TALK:
        if re.search(pattern, t):
            r = random.choice(replies)
            return _cmd("answer", r, r)
    return None


def parse_volume_brightness(t):
    if re.search(r"\b(timers?|alarms?|remind\w*)\b", t):
        return None
    num = re.search(r"\b(\d{1,3})\b", t)
    full = re.search(r"\b(full|max|maximum|hundred)\b", t)
    if re.search(r"\bbrightness\b|\bbrighter\b|\bdimmer\b|\bdim\b", t):
        if num:
            return _cmd("brightness", (_level(num.group(1), low=5), ""), "")
        if full:
            return _cmd("brightness", (100, ""), "")
        if re.search(r"\b(up|increase|more|higher|raise|brighter|badhao|badha)\b", t):
            return _cmd("brightness", (None, "up"), "")
        if re.search(r"\b(down|decrease|less|lower|reduce|dim|dimmer|kam|ghatao)\b", t):
            return _cmd("brightness", (None, "down"), "")
    if re.search(r"\b(volume|awaz|awaaz)\b", t):
        if num:
            lvl = _level(num.group(1))
            return _cmd("set_volume", lvl, "Volume set to %d percent." % lvl)
        if full:
            return _cmd("set_volume", 100, "Volume set to 100 percent.")
    return None


def parse_extra(text):
    t = actions.normalize(text)
    words = t.split()

    talk = parse_smalltalk(t) or parse_volume_brightness(t)
    if talk:
        return talk

    # --- what timers / alarms / reminders do I have?
    if re.search(r"\b(timers?|alarms?|reminders?)\b", t) and \
            re.search(r"\b(what|which|list|show|any|how many|kitne|konse|kaun se)\b", t):
        return _cmd("list_timers", say="")

    # --- timers and alarms
    has_timer = bool(re.search(r"\btimers?\b", t))
    has_alarm = bool(re.search(r"\balarms?\b", t))
    if has_timer or has_alarm or re.search(r"\breminders?\b", t):
        if re.search(r"\b(cancel|stop|delete|remove|clear|band|hatao)\b", t):
            return _cmd("cancel_timers", say="Cancelled all timers, alarms and reminders.")
    if has_timer or has_alarm:
        if has_timer:
            total = 0
            for n, u in re.findall(r"(\d+)\s*(second|sec|minute|min|hour|hr)", t):
                total += int(n) * _UNITS[u]
            if "half an hour" in t:
                total = 1800
            if total:
                return _cmd("timer", min(total, 86400), "")
        else:
            m = re.search(r"(\d{1,2})(?:[: ](\d{2}))?\s*(am|pm|a m|p m|baje)?", t)
            if m:
                hm = _to_24h(int(m.group(1)), int(m.group(2) or 0), m.group(3))
                if hm:
                    return _cmd("alarm", hm, "")

    # --- reminders: "remind me to call mom in 10 minutes" / "... at 6 30 pm"
    m = re.match(r"^(?:please )?remind me (?:to |that )?(.+?) in (\d+) ?(second|sec|minute|min|hour|hr)s?$", t)
    if m:
        sec = int(m.group(2)) * _UNITS[m.group(3)]
        if 1 <= sec <= 7 * 86400:
            return _cmd("reminder", ("Reminder: " + m.group(1) + ".", time.time() + sec), "")
    m = re.match(r"^(?:please )?remind me (?:to |that )?(.+?) at (\d{1,2})(?: (\d{2}))? ?(am|pm|a m|p m)?$", t)
    if m:
        hm = _to_24h(int(m.group(2)), int(m.group(3) or 0), m.group(4))
        if hm:
            return _cmd("reminder", ("Reminder: " + m.group(1) + ".", reminders.next_occurrence(*hm)), "")

    # --- close an app
    m = re.match(r"^(?:please )?(?:close|quit|exit)\s+(.+)$", t) or \
        re.match(r"^(.+?)\s+(?:band karo|band kar do|close karo)$", t)
    if m:
        name = " ".join(w for w in m.group(1).split() if w not in ("the", "my", "app", "please"))
        if name and len(name) >= 3 and not (set(name.split()) & _NOT_APPS):
            return _cmd("close_app", name, "Closing %s." % name)

    # --- music: "play the song" (no name) = the CURRENT song, "play X" = Spotify, "play X on youtube"
    if re.search(r"\b(change|switch)\b.*\b(song|track|gaana)\b", t) or \
            re.search(r"\b(song|gaana) (?:change|badlo|badal)\b", t):
        return _cmd("next_song", say=actions.MEDIA["next_song"][1])
    m = re.match(r"^(?:please )?play (.+)$", t) or \
        re.match(r"^(.+?)\s+(?:bajao|chalao|laga do|lagao)$", t)
    if m and not re.search(r"\b(next|previous|pause|resume|skip|again)\b", t) \
            and not (set(t.split()) & _NOT_SONGS):
        service = "youtube" if re.search(r"\b(youtube|you tube)\b", t) else "spotify"
        song = actions._clean_song(m.group(1))
        if not song or music.is_generic(song):
            return _cmd("play_current", say="Playing.")
        return _cmd("play", (song, service), "Playing %s." % song)

    # --- open the Nth search result
    m = re.search(r"\bopen (?:the )?(\w+) (?:link|result|website|page)\b", t)
    if m and m.group(1) in _ORDINALS:
        return _cmd("open_result", _ORDINALS[m.group(1)], "")

    # --- recipes go through the web summary (not just a Google page)
    if re.search(r"\brecipes?\b", t) and not re.search(r"\bgoogle\b", t):
        return _cmd("web", (t, "recipe", _wants_detail(t)), "")

    # --- weather (no place said = Kharghar; a place said = that place)
    if re.search(r"\b(weather|mausam|temperature|temp|barish|baarish|rain|raining|garmi|thand|humid|humidity|"
                 r"umbrella|how hot|how cold|kitna garam|kitni garmi|kitni thand)\b", t) and \
            not re.search(r"\b(recipe|news|song|play)\b", t):
        day = 2 if re.search(r"\bday after tomorrow\b", t) else (1 if re.search(r"\b(tomorrow|kal)\b", t) else 0)
        place = ""
        m = (re.search(r"\b(?:in|at|for|of)\s+([a-z][a-z ]{1,30}?)(?:\s+(?:today|tomorrow|now|right now|kal|aaj))?$", t) or
             re.search(r"^([a-z][a-z ]{1,30}?)\s+(?:ka|ki|ke|me|mein)\s+(?:mausam|weather|temperature|temp|barish)", t) or
             re.search(r"\b(?:weather|temperature|temp|mausam)\s+(?:in|at|of|for)\s+([a-z][a-z ]{1,30}?)(?:\s+(?:today|tomorrow|now|right now|kal|aaj))?\b", t))
        if m:
            skip = {"the", "today", "tomorrow", "now", "right", "here", "my", "area", "city", "this", "place",
                    "kharghar", "me", "mein", "aaj", "kal"}
            place = " ".join(w for w in m.group(1).split() if w not in skip)
            if re.search(r"\bkharghar\b", m.group(1)):
                place = ""
        return _cmd("weather", (place, day), "")
    return None


def _wants_detail(t):
    return bool(re.search(r"\b(explain|in detail|detailed|elaborate|tell me more|step by step|samjhao)\b", t))


def parse_question(text):
    """Last backup: a question we have no action for -> search the web."""
    t = actions.normalize(text)
    d = _wants_detail(t)
    if re.search(r"\b(news|headlines|khabar|khabrein|samachar)\b", t):
        return _cmd("web", (t, "news", d), "")
    if re.search(r"\brecipes?\b", t):
        return _cmd("web", (t, "recipe", d), "")
    if re.match(r"^(?:how to|how do i|how can i|kaise)\b", t):
        return _cmd("web", (t, "tutorial", d), "")
    if re.match(r"^(?:what|who|when|where|why|how|which|tell me|define|explain|search for|find|kya|kaun|kab|kahan|kyun)\b", t):
        return _cmd("web", (t, "general", d), "")
    return None


_HINDI_WORDS = {"kholo", "khol", "karo", "bajao", "chalao", "lagao", "kya", "kaise", "kaisi", "kaun",
                "kab", "kahan", "kyun", "mujhe", "batao", "bataiye", "dikhao", "suno", "nahi", "nahin",
                "mausam", "gaana", "awaz", "awaaz", "badhao", "ghatao", "hatao", "dhundo", "chahiye",
                "kholiye", "kijiye", "dijiye", "samjhao", "ruko", "sunao", "likho", "padho"}


def is_hindi(text, lang=None):
    """True if she spoke Hindi or Hinglish (Whisper said 'hi', Devanagari letters, or Hindi words)."""
    if lang == "hi" or re.search(r"[\u0900-\u097F]", text):
        return True
    return bool(set(re.findall(r"[a-z]+", text.lower())) & _HINDI_WORDS)


def to_hindi(message):
    """English sentence -> spoken Hindi (Devanagari, female). If that is not possible, the
    English sentence is returned unchanged, so something is always said."""
    _q = features.quick_hindi(message)
    if _q:
        return _q
    if not message or re.search(r"[\u0900-\u097F]", message) or not llm.available():
        return message
    out = llm.chat(
        [{"role": "system", "content": "Translate the user's sentence into natural, simple spoken Hindi in "
          "Devanagari script. The speaker is a woman (use feminine forms like 'रही हूँ'). Keep app names, "
          "song names, place names, numbers and units as they are. Reply with ONLY the translation."},
         {"role": "user", "content": message}],
        model=GROQ_MODEL, max_tokens=300, temperature=0.2, timeout=8)
    out = clean_reply(out) if out else ""
    return out if re.search(r"[\u0900-\u097F]", out) else message      # no Hindi letters = keep English


# Simple, unmistakable commands are understood by the keyword matcher at once (no waiting for the AI).
# This is what makes "pause", "volume 50", "what is the time", "scroll down" answer in well under a second.
FAST_PATH = True
FAST_ACTIONS = {"pause", "resume", "next_song", "prev_song", "set_volume", "brightness", "time", "date", "scroll",
                "show_desktop", "screenshot", "back", "forward", "refresh", "new_tab", "close_tab", "next_tab",
                "prev_tab", "notifications", "quick_settings", "select_all", "copy", "paste", "undo", "save",
                "top", "bottom", "close_window", "list_timers", "answer"}
FAST_MAX_WORDS = 6


def _fast(text):
    """A command from the keyword matcher, only when it is short and the action is a safe, simple one."""
    if not FAST_PATH or len(text.split()) > FAST_MAX_WORDS:
        return None
    try:
        c = parse_extra(text) or actions.parse(text)
    except Exception:
        return None
    if c is not None and c.get("action") in FAST_ACTIONS and not c.get("risky"):
        return c
    return None


def understand(text, hindi=False):
    """Returns (command or None, where it came from). hindi=True: she spoke Hindi, reply in Hindi."""
    if _JOKE_RX.search(text.lower()) or _JOKE_RX.search(actions.normalize(text)):     # jokes: never the same one twice
        r = next_joke()
        c = _cmd("answer", r, r)
        c["obj"] = {"action": "answer", "args": {}, "reply": r}
        c["hindi"] = hindi
        return c, "joke list"
    if hindi:                                     # basic Hindi (time, weather, brightness, volume, tabs ...): instant, no AI
        try:
            import hindi_fix
            _h = hindi_fix.parse(text)
        except Exception:
            _h = None
        if _h is not None:
            _h["hindi"] = True
            return _h, "Hindi keywords"
    _f = features.parse(text, hindi)
    if _f is not None:
        _f["hindi"] = hindi
        return _f, "feature keywords"
    _q = _fast(text)
    if _q is not None:
        _q["hindi"] = hindi
        return _q, "instant keywords"
    if USE_GROQ:
        obj = _ask_groq(text, hindi)
        if obj is not None:
            c = to_command(obj)
            if c is not None:
                c["obj"] = obj                       # kept for the conversation memory
                c["hindi"] = hindi
                _warned.clear()
                return c, "Groq AI"
            if VERBOSE:
                print("(Groq gave an answer I do not allow, using keyword matcher)")
        else:
            _warn_once(llm.last_error["msg"])
    c = parse_extra(text) or actions.parse(text) or parse_question(text)
    if c is not None:
        c["hindi"] = hindi
    return c, "keyword matcher"


# ------------------------------------------------------------------
# Timers, alarms, reminders (saved in reminders.json, see reminders.py)
# ------------------------------------------------------------------
def _set_alarm(h, m):
    label = reminders.add_at(h, m, "Alarm! It is %d:%02d %s." % (h % 12 or 12, m, "AM" if h < 12 else "PM"))
    return "Alarm set for %s." % label


def _web(query, kind, detail=False, hindi=False):
    result = web_tools.answer(query, kind, detail, hindi)
    if result is None:                                   # no search possible: just open Google
        actions.execute({"action": "search", "arg": query, "say": "", "risky": False})
        return "I could not search by myself, so I opened Google for you."
    return result


def _set_volume(level):
    """Windows has no simple 'set volume' key, so: all the way down, then up to the level
    (one key press = 2 percent)."""
    import pyautogui
    pyautogui.press("volumedown", presses=50, interval=0.02)
    ups = int(round(level / 2.0))
    if ups:
        pyautogui.press("volumeup", presses=ups, interval=0.02)
    return "Volume set to %d percent." % level


BRIGHT_SCRIPT = r"""
$lv = 0
[void][int]::TryParse($env:DOIT_LEVEL, [ref]$lv)
try {
  $now = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness | Select-Object -First 1
  $meth = Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods | Select-Object -First 1
  if (-not $now -or -not $meth) { 'notsupported'; exit }
  $cur = [int]$now.CurrentBrightness
  if ($env:DOIT_DIR -eq 'up') { $lv = $cur + 15 } elseif ($env:DOIT_DIR -eq 'down') { $lv = $cur - 15 }
  $lv = [Math]::Max(5, [Math]::Min(100, $lv))
  $meth | Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{Timeout=[uint32]1; Brightness=[byte]$lv} | Out-Null
  "ok $lv"
} catch { 'error: ' + $_.Exception.Message }
"""


def _set_brightness(level, direction):
    env = dict(os.environ, DOIT_LEVEL="" if level is None else str(level), DOIT_DIR=direction or "")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", BRIGHT_SCRIPT],
                           capture_output=True, timeout=20, env=env, creationflags=0x08000000)
        lines = r.stdout.decode("utf-8", "ignore").strip().splitlines()
        detail = lines[-1] if lines else (r.stderr.decode("utf-8", "ignore").strip()[:200] or "no answer")
    except Exception as e:
        detail = str(e)[:120]
    m = re.fullmatch(r"ok (\d+)", detail)
    if m:
        return "Brightness is now %s percent." % m.group(1)
    print("(Windows said: %s)" % detail)
    return "I could not change the brightness. It only works on the laptop's own screen."


def _open_result(n):
    src = web_tools.last["sources"]
    if not src:
        return "I have not searched for anything yet."
    if n > len(src):
        return "I only found %d results." % len(src)
    import webbrowser
    webbrowser.open(src[n - 1][1])
    return "Opening result %d: %s." % (n, src[n - 1][0][:80])


# ------------------------------------------------------------------
# Close an app politely (like clicking its X button)
# ------------------------------------------------------------------
CLOSE_SCRIPT = r"""
$n = $env:DOIT_APP
$skip = 'explorer','python','pythonw','py','cmd','powershell','pwsh','WindowsTerminal','conhost','OpenConsole','dwm','winlogon','csrss','svchost'
$hit = @(Get-Process | Where-Object { $_.MainWindowTitle -and ($skip -notcontains $_.ProcessName) -and
        (($_.ProcessName -like "*$n*") -or ($_.MainWindowTitle -like "*$n*")) })
foreach ($p in $hit) { $p.CloseMainWindow() | Out-Null }
$hit.Count
"""


def _close_app(name):
    env = dict(os.environ, DOIT_APP=name)           # the name goes in as data, never as code
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", CLOSE_SCRIPT],
                           capture_output=True, timeout=20, env=env, creationflags=0x08000000)
        n = int(r.stdout.decode("utf-8", "ignore").strip().splitlines()[-1])
    except Exception:
        return "Sorry, I could not close %s." % name
    if n:
        return "Closed %s." % name
    return "I could not find an open window for %s." % name


# ------------------------------------------------------------------
# Wi-Fi / Bluetooth (fixed version: the earlier script used the wrong list type)
# ------------------------------------------------------------------
RADIO_SCRIPT = r"""
$kind = $env:DOIT_KIND; $want = $env:DOIT_STATE
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, $type) { $m = $asTask.MakeGenericMethod($type); $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
  [Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
  [Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
  [Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
  Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
  $radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IReadOnlyList[Windows.Devices.Radios.Radio]])
  $r = $radios | Where-Object { $_.Kind -eq $kind } | Select-Object -First 1
  if (-not $r) { 'notfound'; exit }
  $res = Await ($r.SetStateAsync([Windows.Devices.Radios.RadioState]$want)) ([Windows.Devices.Radios.RadioAccessStatus])
  "$res"
} catch { 'error: ' + $_.Exception.Message }
"""


def _set_radio(name, on):
    """Returns (worked, detail). detail is Windows' own answer, useful when it fails."""
    env = dict(os.environ, DOIT_KIND="Bluetooth" if name == "bluetooth" else "WiFi",
               DOIT_STATE="On" if on else "Off")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", RADIO_SCRIPT],
                           capture_output=True, timeout=30, env=env, creationflags=0x08000000)
        lines = r.stdout.decode("utf-8", "ignore").strip().splitlines()
        detail = lines[-1] if lines else (r.stderr.decode("utf-8", "ignore").strip()[:200] or "no answer")
        return detail == "Allowed", detail
    except Exception as e:
        return False, str(e)[:120]


# ------------------------------------------------------------------
# Running a command
# ------------------------------------------------------------------
def _when(due):
    left = due - time.time()
    if left < 6 * 3600:
        return "in " + reminders.nice(left)
    return "at " + time.strftime("%I:%M %p", time.localtime(due)).lstrip("0")


def run(c):
    """Does the command. Returns the sentence to show and speak."""
    a, arg = c["action"], c["arg"]
    if a == "open_named" and isinstance(arg, (tuple, list)) and arg and (len(arg) < 2 or arg[1] == "app"):
        try:                                           # "open images" inside the open window: click that word first
            import smart_pick
            _r = smart_pick.open_visible(arg[0], bool(c.get("hindi")))
            if _r:
                return _r
        except Exception:
            pass
    if a in features.ACTIONS:
        try:
            return features.run(c)
        except Exception as e:
            return "Sorry, that did not work (%s)." % e
    try:
        if a == "answer":
            return arg
        if a == "set_volume":
            return _set_volume(arg)
        if a == "brightness":
            return _set_brightness(*arg)
        if a == "web":
            return _web(*arg, hindi=c.get("hindi", False))
        if a == "weather":
            return web_tools.weather(*arg)
        if a == "time":
            return "It is %s." % time.strftime("%I:%M %p").lstrip("0")
        if a == "date":
            return time.strftime("Today is %A, %d %B %Y.")
        if a == "play":
            return music.play(*arg)
        if a in ("play_current", "resume"):
            return music.play_current()
        if a == "pause":
            return music.pause_current()
        if a == "open_result":
            return _open_result(arg)
        if a == "radio":
            name, on = arg
            ok, detail = _set_radio(name, on)
            if ok:
                return c["say"] or "Done."
            page = "ms-settings:bluetooth" if name == "bluetooth" else "ms-settings:network-wifi"
            os.startfile(page)
            print("(Windows said: %s)" % detail)
            return "Windows did not let me switch it, so I opened the settings page."
        if a == "timer":
            reminders.add_in(arg, "Your %s timer is done." % reminders.nice(arg), "timer")
            return "Timer set for %s." % reminders.nice(arg)
        if a == "alarm":
            return _set_alarm(*arg)
        if a == "reminder":
            message, due = arg
            reminders.add(due, message, "reminder")
            return "Okay, I will remind you %s." % _when(due)
        if a == "list_timers":
            return reminders.listing()
        if a == "cancel_timers":
            n = reminders.cancel_all()
            return c["say"] if n else "You had no timers, alarms or reminders."
        if a == "close_app":
            return _close_app(arg)
    except Exception as e:
        return "Sorry, that did not work (%s)." % e
    return actions.execute(c)

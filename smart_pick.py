"""
Roe - Feature: "scroll, then open the Nth thing"  (smart pick)

Say (English / Hindi / Hinglish), with a Downloads folder, the Desktop or YouTube open on screen:
    "scroll down a bit and open the third file"       "thoda neeche scroll karo aur teesra video chalao"
    "open the second folder"                          "play the third video"
    "play the video with title <title>"               "open the file named <name>"
    "open the last video"                             "number 4 video kholo"

What it does:  (1) optional scroll,  (2) reads the list of things on the window,
(3) picks the one you said (by position or by title),  (4) opens it.

How it reads the window:
  * File Explorer / Desktop / browser (YouTube): Windows "UI Automation" through pywinauto.
    It gives the real names and positions of the files, folders and video links.
  * If that does not work: OCR, only when screen_reader.py is in the folder (optional). OCR can find a TITLE you say, but cannot count
    "the third video", so then it asks you to say the title.
Safety: it only moves the mouse, scrolls and clicks. Files that can run programs (.exe, .bat, .msi ...)
ask "Are you sure?" first. No command from the AI is ever run.

Needs (one time):  py -3.11 -m pip install pywinauto
"""
import csv
import ctypes
import difflib
import os
import re
import time
import unicodedata

# ---------------- Settings you can change ----------------
SCROLL_AMOUNTS = {"little": 300, "normal": 600, "lot": 1500}   # same numbers as the normal scroll command
WAIT_AFTER_SCROLL = 1.0       # seconds to wait so YouTube can load the new videos
MATCH_NEEDED = 0.60           # how close a title must be to the one you said (1.0 = identical)
AMBIGUOUS_GAP = 0.04          # two titles this close = "first or second?"
MAX_CHOICES = 3
FOLLOWUP_SECONDS = 45
MAX_ITEMS = 120               # read at most this many things from one window (speed)
MINIMIZE_OWN_WINDOW = True    # if the black Roe window is in front, hide it so the window behind it is used
LOG_FILE = "smart_pick_log.csv"
DANGEROUS_EXT = {".exe", ".bat", ".cmd", ".msi", ".ps1", ".vbs", ".js", ".jar", ".scr", ".com", ".reg",
                 ".msc", ".hta", ".wsf", ".dll"}
KNOWN_PLACES = {"downloads", "download", "documents", "document", "desktop", "pictures", "music", "videos",
                "this pc", "file explorer", "explorer", "recycle bin", "डाउनलोड", "डाउनलोड्स", "डेस्कटॉप"}
# ---------------------------------------------------------

ACTIONS = {"pick_item"}
NO_TRANSLATE = {"pick_item"}          # this file answers in the right language itself

PROMPT = """pick_item     args: which (1 to 10 = the first ... tenth, -1 = the last, 0 = not said), name (the title or file name
                            if she said one, else ""), scroll (none | little | normal | lot), direction (down | up)
                            ("open the third video", "scroll down a bit and open the second file",
                            "play the video with title <title>", "downloads mein teesra file kholo").
                            Use it ONLY for opening / playing something already shown on the screen by its position or title."""


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_dpi_aware()

# ------------------------------------------------------------------
# Messages: [English, Hindi]
# ------------------------------------------------------------------
M = {
    "opened": ("Opening {w}.", "{w} खोल रही हूँ।"),
    "played": ("Playing {w}.", "{w} चला रही हूँ।"),
    "none_found": ("I could not find a list of files or videos on this window.",
                   "मुझे इस विंडो में फ़ाइलों या वीडियो की सूची नहीं मिली।"),
    "too_few": ("I can see only {n} here, so there is no number {k}.",
                "मुझे यहाँ सिर्फ़ {n} दिख रहे हैं, इसलिए {k} नंबर नहीं है।"),
    "no_title": ("I could not find \u201c{w}\u201d here. Try scrolling, or say the title again.",
                 "मुझे यहाँ \u201c{w}\u201d नहीं मिला। स्क्रॉल कीजिए या नाम फिर से बोलिए।"),
    "ocr_only": ("I cannot count the items on this window. Please say the title instead.",
                 "मैं इस विंडो की चीज़ें गिन नहीं पा रही। कृपया नाम बोलिए।"),
    "which": ("I found {n} that match. {q}", "{n} मिलते-जुलते मिले। {q}"),
    "retry": ("I only found {n}. Please say first or second.", "मुझे सिर्फ़ {n} मिले। कृपया पहला या दूसरा बोलिए।"),
    "cancelled": ("Okay, I did not open anything.", "ठीक है, मैंने कुछ नहीं खोला।"),
    "sure": ("{w} can run a program. Are you sure? Say yes or no.",
             "{w} एक प्रोग्राम चला सकता है। क्या आप सुनिश्चित हैं? हाँ या नहीं बोलिए।"),
    "click_window": ("Please click on the folder or browser window first, then say it again.",
                     "कृपया पहले फ़ोल्डर या ब्राउज़र की विंडो पर क्लिक कीजिए, फिर दोबारा बोलिए।"),
    "no_pywinauto": ("This needs one package. Run: py -3.11 -m pip install pywinauto",
                     "इसके लिए एक पैकेज चाहिए। चलाइए: py -3.11 -m pip install pywinauto"),
    "failed": ("Sorry, I could not do that ({e}).", "माफ़ कीजिए, मैं यह नहीं कर पाई ({e})।"),
}
ORD_EN = ["first", "second", "third"]
ORD_HI = ["पहला", "दूसरा", "तीसरा"]


def _m(key, hindi, **kw):
    return M[key][1 if hindi else 0].format(**kw)


def _question(n, hindi):
    w = (ORD_HI if hindi else ORD_EN)[:n]
    if hindi:
        return ", ".join(w[:-1]) + " या " + w[-1] + "?"
    q = ", ".join(w[:-1]) + " or " + w[-1] + "?"
    return q[0].upper() + q[1:]


# ------------------------------------------------------------------
# Understanding the sentence
# ------------------------------------------------------------------
_ORD = {}
for _n, _words in {
    1: "first 1st pehla pehli pehle pahla pahli pahle पहला पहली पहले",
    2: "second 2nd dusra dusri dusre doosra doosri दूसरा दूसरी दूसरे",
    3: "third 3rd teesra teesri tisra tisri तीसरा तीसरी तीसरे",
    4: "fourth 4th chautha chauthi chothi चौथा चौथी चौथे",
    5: "fifth 5th paanchva panchva paanchvi पाँचवाँ पांचवां पाँचवीं पांचवीं",
    6: "sixth 6th chhatha chhatwa chhatha छठा छठी छठवां",
    7: "seventh 7th saatva satva saatvi सातवां सातवाँ सातवीं",
    8: "eighth 8th aathva athva aathvi आठवां आठवाँ आठवीं",
    9: "ninth 9th nauva nauva nauvi नौवां नौवाँ नौवीं",
    10: "tenth 10th dasva dasvi दसवां दसवाँ दसवीं",
    -1: "last aakhri akhri aakhiri आखिरी आख़िरी अंतिम",
}.items():
    for _w in _words.split():
        _ORD[_w] = _n

_THING = r"(?:video|videos|vid|file|files|folder|folders|item|items|thumbnail|वीडियो|फाइल|फ़ाइल|फोल्डर|फ़ोल्डर)"
_THING_RE = re.compile(r"\b" + _THING + r"\b|वीडियो|फाइल|फ़ाइल|फोल्डर|फ़ोल्डर")
_OPEN_RE = re.compile(r"\b(?:open|play|start|launch|select|choose|run|kholo|kholiye|khol|chalao|chalaiye|chala|"
                      r"lagao|dikhao)\b|खोलो|खोलिए|खोल|चलाओ|चलाइए|चला|ओपन|प्ले|लगाओ|दिखाओ")
_SCROLL_RE = re.compile(r"\bscroll(?:ing)?\b|\bneeche\b|\bniche\b|\bnichey\b|\bupar\b|नीचे|ऊपर|स्क्रॉल")
_SPLIT_RE = re.compile(r"\b(?:and then|then|and|aur phir|phir|uske baad|fir)\b|और फिर|फिर|उसके बाद|और|तो")
_NAME_WORDS = r"(?:named|called|titled|name|title|with the title|with title|jiska naam|jiska title|naam)"

_AMOUNT_LITTLE = re.compile(r"\b(?:little|bit|slightly|thoda|thora|zara|jara)\b|थोड़ा|थोडा|ज़रा|जरा")
_AMOUNT_LOT = re.compile(r"\b(?:lot|much|more|far|zyada|bahut|kaafi|kafi)\b|ज्यादा|ज़्यादा|बहुत|काफ़ी|काफी")
_UP = re.compile(r"\bup\b|\bupar\b|ऊपर")


def _clean(text):
    t = text.strip().lower()
    t = re.sub(r"[.,!?।\"“”]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _scroll_info(part):
    """('down', 'little')  or  (None, None) when the part has no scroll words."""
    if not _SCROLL_RE.search(part):
        return None, None
    d = "up" if _UP.search(part) else "down"
    amt = "little" if _AMOUNT_LITTLE.search(part) else ("lot" if _AMOUNT_LOT.search(part) else "normal")
    return d, amt


def _find_ordinal(part):
    """1..10, -1 (last) or 0.  'number 4' / 'no 4' also works."""
    m = re.search(r"\b(?:number|no|num|nambar|नंबर)\.?\s*(\d{1,2})\b", part)
    if m:
        return int(m.group(1))
    for w in re.findall(r"[\w\u0900-\u097F]+", part):
        if w in _ORD:
            return _ORD[w]
    return 0


def _find_name(part):
    """The title said by the user, or ''.   'play the video with title X', 'open file named X', 'X video chalao'."""
    m = re.search(r"\b(?:video|file|folder|vid)\s+(?:" + _NAME_WORDS + r")\s+(?P<n>.+)$", part)
    if not m:
        m = re.search(r"\b(?:" + _NAME_WORDS + r")\s+(?P<n>.+?)(?:\s+(?:video|file|folder)\b.*)?$", part) \
            if re.search(_NAME_WORDS, part) else None
    if m:
        return _tidy_name(m.group("n"))
    m = re.search(r"\b(?:open|play|start|select|choose)\s+(?:the\s+)?(?:video|file|folder|vid)\s+(?P<n>.+)$", part)
    if m:
        return _tidy_name(m.group("n"))
    m = re.match(r"^(?P<n>.+?)\s+(?:wala\s+|wali\s+|ki\s+|ka\s+)?(?:video|file|folder)\s+(?:ko\s+)?"
                 r"(?:chalao|kholo|khol|open|play|chala)(?:\s+karo|\s+do)?$", part)
    if m:
        return _tidy_name(m.group("n"))
    return ""


def _tidy_name(n):
    words = n.split()
    while words and words[0] in {"the", "a", "an", "of", "is", "naam", "name", "title", "ka", "ki", "wala"}:
        words.pop(0)
    while words and words[-1] in {"please", "pls", "karo", "kijiye", "do", "now", "ko", "chalao", "kholo", "open",
                                  "play", "video", "file", "folder"}:
        words.pop()
    n = " ".join(words).strip()
    if len(n) < 2 or len(n) > 80:
        return ""
    return n


def _cmd(action, arg=None, say="", risky=False):
    return {"action": action, "arg": arg, "say": say, "risky": risky}


def _make(which, name, scroll, direction):
    return _cmd("pick_item", {"which": which, "name": name, "scroll": scroll, "direction": direction}, "")


def parse(text, hindi=False):
    """Keyword backup (runs BEFORE the AI). Returns a command, or None when the sentence is not ours."""
    t = _clean(text)
    if not t or not _OPEN_RE.search(t):
        return None

    # split "scroll down a bit and open the third file" into its two parts
    parts = [p.strip() for p in _SPLIT_RE.split(t) if p and p.strip()]
    scroll, direction, open_part = "none", "down", t
    if len(parts) >= 2:
        for i, p in enumerate(parts):
            d, a = _scroll_info(p)
            if d and not _OPEN_RE.search(p):
                scroll, direction = a, d
                open_part = " ".join(parts[:i] + parts[i + 1:])
                break
    else:
        d, a = _scroll_info(t)                  # "thoda neeche karke teesra video kholo" (one clause)
        if d:
            scroll, direction = a, d
            open_part = _SCROLL_RE.sub(" ", t)

    open_part = _AMOUNT_LITTLE.sub(" ", _AMOUNT_LOT.sub(" ", open_part)) if scroll != "none" else open_part
    if not _OPEN_RE.search(open_part):
        return None
    which = _find_ordinal(open_part)
    name = _find_name(open_part)
    has_thing = bool(_THING_RE.search(open_part)) or bool(re.search(r"\bone\b|\bwala\b|\bwali\b", open_part))
    if name and name.lower() in KNOWN_PLACES:
        name = ""
    if which and has_thing:
        return _make(which, "", scroll, direction)
    if name:
        return _make(0, name, scroll, direction)
    return None


def to_command(action, args, reply):
    """Called by brain.to_command() when Groq picked pick_item."""
    if action != "pick_item":
        return None
    try:
        which = int(str(args.get("which", 0)).strip() or 0)
    except ValueError:
        which = 0
    which = which if (1 <= which <= 10 or which == -1) else 0
    name = str(args.get("name", "") or "").strip()[:80]
    if name.lower() in KNOWN_PLACES:
        name = ""
    scroll = str(args.get("scroll", "none") or "none").lower()
    scroll = scroll if scroll in ("none", "little", "normal", "lot") else "none"
    direction = "up" if str(args.get("direction", "down")).lower() == "up" else "down"
    if not which and not name:
        return None
    return _make(which, name, scroll, direction)


# ------------------------------------------------------------------
# The window in front
# ------------------------------------------------------------------
class Item:
    def __init__(self, name, x0, y0, x1, y1, title=None):
        self.name, self.x0, self.y0, self.x1, self.y1 = name, x0, y0, x1, y1
        self.title = title or name

    @property
    def cx(self):
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2.0

    @property
    def h(self):
        return max(1.0, self.y1 - self.y0)


_console = {"hwnd": 0, "hidden": False}


def _foreground():
    """(hwnd, class name, title, (left, top, right, bottom)) of the window in front."""
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    u.GetClassNameW(hwnd, buf, 256)
    cls = buf.value
    tbuf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, tbuf, 512)

    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    return hwnd, cls, tbuf.value, (r.l, r.t, r.r, r.b)


def _kind_of(cls):
    if cls == "CabinetWClass":
        return "explorer"
    if cls in ("Progman", "WorkerW"):
        return "desktop"
    if cls in ("Chrome_WidgetWin_1", "MozillaWindowClass"):
        return "browser"
    return "other"


def _target_window():
    """Returns (hwnd, kind, title, rect) or None when our own black window is the only thing in front."""
    hwnd, cls, title, rect = _foreground()
    own = ctypes.windll.kernel32.GetConsoleWindow()
    if MINIMIZE_OWN_WINDOW and own and hwnd == own:
        ctypes.windll.user32.ShowWindow(own, 6)                       # minimize: the window behind comes forward
        _console.update(hwnd=own, hidden=True)
        time.sleep(0.8)
        hwnd, cls, title, rect = _foreground()
        if hwnd == own:
            return None
    if cls in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
        return None
    return hwnd, _kind_of(cls), title, rect


def _restore_console():
    if _console["hidden"]:
        try:
            ctypes.windll.user32.ShowWindow(_console["hwnd"], 4)      # show without taking focus
        except Exception:
            pass
    _console["hidden"] = False


# ------------------------------------------------------------------
# Reading the list of things (Windows UI Automation)
# ------------------------------------------------------------------
_YT_META = re.compile(r"\d[\d,.]*\s*[KMB]?\s*(?:views?|watching)\b|\b\d+\s+(?:minutes?|seconds?|hours?)\b", re.I)


def youtube_title(name):
    """'Title by Channel 1.2M views 3 days ago 10 minutes' -> 'Title'."""
    m = _YT_META.search(name)
    head = name[:m.start()] if m else name
    if " by " in head:
        head = head.rsplit(" by ", 1)[0]
    return head.strip(" -\u2013\u2014") or name


def _uia_items(hwnd, kind, title, rect):
    """Real names and positions from Windows. Returns a list of Item (can be empty). Raises ImportError if
    pywinauto is missing."""
    from pywinauto import Desktop
    win = Desktop(backend="uia").window(handle=hwnd)
    left, top, right, bottom = rect
    out = []
    if kind in ("explorer", "desktop"):
        elements = win.descendants(control_type="ListItem")
        lo_top = top + 60
    else:
        try:
            root = win.child_window(control_type="Document")
            root.wait("exists", timeout=2)
            elements = root.descendants(control_type="Hyperlink")
        except Exception:
            elements = win.descendants(control_type="Hyperlink")
        lo_top = top + 90
    is_yt = kind == "browser" and "youtube" in title.lower()
    for el in elements:
        try:
            name = (el.window_text() or "").strip()
            r = el.rectangle()
        except Exception:
            continue
        if not name or r.width() < 8 or r.height() < 8:
            continue
        cx, cy = (r.left + r.right) / 2.0, (r.top + r.bottom) / 2.0
        if not (left < cx < right and lo_top < cy < bottom - 20):         # off screen or in the toolbar
            continue
        if kind == "browser":
            if is_yt and not _YT_META.search(name):
                continue
            if not is_yt and len(name) < 6:
                continue
        it = Item(name, r.left, r.top, r.right, r.bottom, youtube_title(name) if is_yt else name)
        out.append(it)
        if len(out) >= MAX_ITEMS:
            break
    return _dedupe(out)


def _dedupe(items):
    """The thumbnail and the title of one video are two links: keep one."""
    kept = []
    for it in sorted(items, key=lambda i: (i.y0, i.x0)):
        if any(_norm(k.title) == _norm(it.title) and abs(k.cx - it.cx) < 500 and abs(k.cy - it.cy) < 400
               for k in kept):
            continue
        kept.append(it)
    return kept


def order_items(items):
    """Reading order: rows from top to bottom, each row left to right (a grid of videos / file icons)."""
    if not items:
        return []
    hs = sorted(i.h for i in items)
    tol = max(20.0, 0.6 * hs[len(hs) // 2])
    rows = []
    for it in sorted(items, key=lambda i: i.y0):
        if rows and it.y0 - rows[-1][0] <= tol:
            rows[-1][1].append(it)
        else:
            rows.append([it.y0, [it]])
    out = []
    for _, row in rows:
        out.extend(sorted(row, key=lambda i: i.x0))
    return out


# ------------------------------------------------------------------
# Matching a title
# ------------------------------------------------------------------
def _norm(s):
    return "".join(c for c in s.lower() if c.isalnum() or unicodedata.category(c).startswith("M"))


def score(spoken, item):
    """0..1 : how well the spoken title fits this item."""
    sn = _norm(spoken)
    if not sn:
        return 0.0
    best = 0.0
    for cand in (item.title, item.name):
        cn = _norm(cand)
        if not cn:
            continue
        if len(sn) >= 3 and sn in cn:
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, sn, cn).ratio())
    toks = [w for w in re.findall(r"\w+", spoken.lower()) if len(w) >= 3]
    if toks:
        hay = set(re.findall(r"\w+", (item.title + " " + item.name).lower()))
        hit = 0
        for w in toks:
            if w in hay or any(difflib.SequenceMatcher(None, w, h).ratio() >= 0.8 for h in hay if abs(len(h) - len(w)) <= 2):
                hit += 1
        best = max(best, 0.95 * hit / len(toks))
    return best


def find_by_title(items, spoken):
    """Best matches first: [(score, item)], only those >= MATCH_NEEDED."""
    scored = sorted(((score(spoken, i), i) for i in items), key=lambda s: -s[0])
    return [s for s in scored if s[0] >= MATCH_NEEDED]


# ------------------------------------------------------------------
# Doing it
# ------------------------------------------------------------------
_pending = {"kind": None, "items": None, "hindi": False, "t": 0.0, "kindwin": "explorer"}


def _scroll(direction, amount, rect):
    import pyautogui
    left, top, right, bottom = rect
    pyautogui.moveTo((left + right) // 2, top + (bottom - top) * 6 // 10, duration=0.2)   # mouse over the list
    n = SCROLL_AMOUNTS.get(amount, 600)
    pyautogui.scroll(n if direction == "up" else -n)
    time.sleep(WAIT_AFTER_SCROLL)


def _open_at(x, y, kindwin):
    import pyautogui
    pyautogui.moveTo(x, y, duration=0.25)
    if kindwin in ("explorer", "desktop"):
        pyautogui.doubleClick()
    else:
        pyautogui.click()


def _is_dangerous(name):
    return os.path.splitext(name.strip().lower())[1] in DANGEROUS_EXT


def _speak_name(item, kindwin, hindi):
    t = item.title
    t = t if len(t) <= 70 else t[:67].rsplit(" ", 1)[0]
    return _m("played" if kindwin == "browser" else "opened", hindi, w=t)


def _do_open(item, kindwin, hindi, confirmed=False):
    if kindwin in ("explorer", "desktop") and _is_dangerous(item.name) and not confirmed:
        _pending.update(kind="confirm", items=[item], hindi=hindi, t=time.time(), kindwin=kindwin)
        return _m("sure", hindi, w=item.name)
    try:
        _open_at(item.cx, item.cy, kindwin)
    except Exception as e:                                   # includes the PyAutoGUI corner emergency stop
        return _m("failed", hindi, e=str(e)[:80])
    return _speak_name(item, kindwin, hindi)


def _ocr_by_title(name, kindwin, hindi):
    """Fallback: find the written title on the screen with OCR (screen_reader.py)."""
    try:
        import screen_reader                                 # optional: only if you still have screen_reader.py
    except ImportError:
        return None, _m("no_title", hindi, w=name)
    boxes = screen_reader.scan()
    matches = screen_reader.find_matches(boxes, name)
    if not matches:
        return None, _m("no_title", hindi, w=name)
    best = max(matches, key=lambda f: f[2])
    return Item(best[3], best[0] - 5, best[1] - 5, best[0] + 5, best[1] + 5), None


def run(c):
    hindi = bool(c.get("hindi"))
    a = c["arg"] or {}
    t0 = time.time()
    method, ok, n_items = "", False, 0
    try:
        win = _target_window()
        if win is None:
            return _m("click_window", hindi)
        hwnd, kindwin, title, rect = win
        if a.get("scroll") not in (None, "none"):
            _scroll(a.get("direction", "down"), a["scroll"], rect)

        items = []
        try:
            if kindwin != "other":
                items = order_items(_uia_items(hwnd, kindwin, title, rect))
                method = "uia"
        except ImportError:
            return _m("no_pywinauto", hindi)
        except Exception:
            items = []
        n_items = len(items)

        which, name = int(a.get("which") or 0), (a.get("name") or "").strip()
        if items:
            if which:
                k = len(items) if which == -1 else which
                if k > len(items):
                    return _m("too_few", hindi, n=len(items), k=k)
                reply = _do_open(items[k - 1], kindwin, hindi)
                ok = True
                return reply
            hits = find_by_title(items, name)
            if hits:
                near = []
                for h in hits:                                   # all titles about as good as the best one
                    if hits[0][0] - h[0] <= AMBIGUOUS_GAP and all(_norm(h[1].title) != _norm(k[1].title) for k in near):
                        near.append(h)
                if len(near) > 1 and _norm(name) not in {_norm(h[1].title) for h in near}:   # not an exact title
                    shown = [h[1] for h in sorted(near, key=lambda h: (h[1].y0, h[1].x0))[:MAX_CHOICES]]
                    _pending.update(kind="choose", items=shown, hindi=hindi, t=time.time(), kindwin=kindwin)
                    return _m("which", hindi, n=len(shown), q=_question(len(shown), hindi))
                ok = True
                return _do_open(hits[0][1], kindwin, hindi)

        # UI Automation gave nothing useful: OCR can still find a written title
        if name:
            method = "ocr"
            item, err = _ocr_by_title(name, kindwin, hindi)
            if item is None:
                return err
            ok = True
            return _do_open(item, kindwin, hindi)
        return _m("none_found", hindi) if not which else _m("ocr_only", hindi)
    except ImportError:
        return _m("no_pywinauto", hindi)
    except Exception as e:
        return _m("failed", hindi, e=str(e)[:80])
    finally:
        _restore_console()
        _log(method, t0, n_items, a, ok)


# ------------------------------------------------------------------
# "open images" when a window is already open and that word is written on it
# ------------------------------------------------------------------
OPEN_VISIBLE = True            # True = "open <word>" first looks for that exact word on the window in front
OPEN_VISIBLE_SECONDS = 2.5     # never spend longer than this looking
_VISIBLE_TYPES = ("ListItem", "TreeItem", "TabItem", "Hyperlink", "Button", "MenuItem")


def _singular(x):
    return x[:-1] if len(x) > 3 and x.endswith("s") else x


def open_visible(name, hindi=False):
    """If a normal window is in front and `name` is written on one of its items (a folder, a category such as
    'Images', a menu entry ...), click that item. Returns the sentence to say, or None (then the caller opens an
    app with that name as before). Needs an EXACT match, so it never clicks a wrong thing."""
    if not OPEN_VISIBLE or not name:
        return None
    try:
        hwnd, cls, title, rect = _foreground()
        own = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd == own or cls in ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS"):
            return None                                   # our own black window is in front: nothing to click
        kindwin = _kind_of(cls)
        if kindwin == "browser":
            return None                                   # web pages: use "open the first link" / smart pick instead
        want = _norm(name)
        if not want:
            return None
        from pywinauto import Desktop
        win = Desktop(backend="uia").window(handle=hwnd)
        end = time.time() + OPEN_VISIBLE_SECONDS
        for ct in _VISIBLE_TYPES:
            if time.time() > end:
                break
            try:
                elements = win.descendants(control_type=ct)
            except Exception:
                continue
            for e in elements[:MAX_ITEMS * 3]:
                try:
                    text = (e.window_text() or "").strip()
                    if not text or not (_norm(text) == want or _singular(_norm(text)) == _singular(want)):
                        continue
                    r = e.rectangle()
                    if r.right <= r.left or r.bottom <= r.top:
                        continue
                    _open_at((r.left + r.right) // 2, (r.top + r.bottom) // 2, kindwin)
                    return _m("opened", hindi, w=text[:60])
                except Exception:
                    continue
        return None
    except ImportError:
        return None
    except Exception:
        return None


# ------------------------------------------------------------------
# "first or second?"  and  "Are you sure?" answers
# ------------------------------------------------------------------
_YES = {"yes", "yeah", "yep", "haan", "han", "ha", "ji", "sure", "ok", "okay", "हाँ", "हां", "जी", "हा"}
_NO = {"no", "nahi", "nahin", "cancel", "stop", "never", "mind", "none", "नहीं", "नही", "रहने", "रुको"}


def has_followup():
    return bool(_pending["kind"]) and time.time() - _pending["t"] <= FOLLOWUP_SECONDS


def followup(text, hindi=False):
    if not _pending["kind"]:
        return None
    if time.time() - _pending["t"] > FOLLOWUP_SECONDS:
        _pending.update(kind=None, items=None)
        return None
    hindi = hindi or _pending["hindi"]
    words = {w.strip(".,!?।").lower() for w in text.split()}
    kind, items, kindwin = _pending["kind"], _pending["items"], _pending["kindwin"]
    if kind == "confirm":
        if words & _YES:
            _pending.update(kind=None, items=None)
            return _do_open(items[0], kindwin, hindi, confirmed=True)
        _pending.update(kind=None, items=None)
        return _m("cancelled", hindi) if (words & _NO) else None
    pick = None
    for w in words:
        if w in _ORD and _ORD[w] != 0:
            pick = _ORD[w]
            break
    if pick is None:
        _pending.update(kind=None, items=None)
        return _m("cancelled", hindi) if (words & _NO) else None
    n = len(items)
    k = n if pick == -1 else pick
    if k > n:
        return _m("retry", hindi, n=n)
    _pending.update(kind=None, items=None)
    return _do_open(items[k - 1], kindwin, hindi)


def _log(method, t0, n_items, a, ok):
    """One line per use in smart_pick_log.csv (for the report: delay and success)."""
    try:
        new = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["time", "method", "seconds", "items_seen", "which", "name", "scroll", "ok"])
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), method, round(time.time() - t0, 1), n_items,
                        a.get("which"), a.get("name"), a.get("scroll"), int(bool(ok))])
    except Exception:
        pass

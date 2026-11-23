"""
Roe - PHONE CONTROL MODE  (say "control phone")

  "control phone"      -> your phone screen appears on the laptop (scrcpy) and EVERYTHING you say
                          now goes to the PHONE, not the laptop.
  "activate voice"     -> the phone screen closes and Roe is back to normal laptop mode.
  "deactivate voice"   -> closes phone control AND puts the voice to sleep.

Things you can say in phone mode (English / Hindi / Hinglish):
  APPS       "open whatsapp"  "open youtube"  "open spotify"  "close this app"  "close youtube"
  CHATS      "open daddy's chat"   "open chat with mom"
  MESSAGES   "send message that I reached home"            (types it in the open chat and presses send)
             "send a message that I reached home safely to my dad on whatsapp"
             "send sms to daddy that I reached home"       "message mom I will be late"
  SCROLL     "scroll"  "scroll down"  "scroll up a lot"  "swipe left"  "go to the top"
  VIDEOS     "play the second video"  "play video number 3"  "play the video <title>"  "play <title> on youtube"
  CAMERA     "open camera"  "click a picture" / "take a photo"  "record a video"  "stop recording"  "switch camera"
  CALLS      "call daddy"  "reject the call"  "answer the call"  "hang up"
  INFO       "what is my phone battery"          (read aloud on the laptop)
  SETTINGS   "turn on bluetooth"  "wifi off"  "mobile data on"  "airplane mode on"  "location off"
             "increase volume"  "volume 50"  "mute"  "increase brightness"  "brightness 80"
             "open torch" / "turn off torch"   "do not disturb on"
  MUSIC      "open spotify and play music"  "play kesariya on spotify"  "pause"  "next song"
  INSIDE APPS "open images" (inside Files)  "open the third folder"  "tap downloads"  -> taps what is written on the screen
  OTHER      "go back"  "go home"  "recent apps"  "show notifications"  "lock the phone"  "tap <word on screen>"
             "type hello"  "search best pizza"  "search arijit singh on youtube"  "set a timer for 5 minutes"
             "take a screenshot"  "hide the screen" / "show the screen"

SAFETY: only the fixed actions in this file can run. Nothing you say is ever run as code.
KEEP THE PHONE UNLOCKED (screen on). USB debugging must be ON and the cable plugged in.
Needs: phone_link.py, the platform-tools folder (ADB) and the scrcpy folder in the Roe folder.
"""
import difflib
import json
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import llm
import phone_link as pl

# ---------------- Settings you can change ----------------
SHOW_SCREEN_ON_ENTER = True          # open the phone screen on the laptop when you say "control phone"
TURN_PHONE_SCREEN_OFF = False        # True = the phone's own screen goes dark while you use it from the laptop
MIRROR_MAX_SIZE = 1280               # biggest side of the phone window in pixels (smaller = faster)
MIRROR_TITLE = "Roe - Phone"
USE_GROQ_FOR_PHONE = True            # True = if my own rules do not understand you, ask the Groq AI (needs GROQ_API_KEY)
STEP_PAUSE = 1.2                     # seconds between two jobs in one sentence ("open spotify and play music")
# ---------------------------------------------------------

ACTIVE = False                       # True while phone mode is on (voice_assistant.py reads this)
_S = {"recording": False, "pkgs": None, "book": None, "size": None, "dump_ok": True}

# Words Whisper should expect while you are in phone mode
WHISPER_PROMPT = ("open WhatsApp, open daddy's chat, send a message that I reached home, scroll down, scroll up, "
                  "play the second video, open YouTube, open camera, click a picture, record a video, call daddy, "
                  "reject the call, phone battery, turn on Bluetooth, open Spotify and play music, increase volume, "
                  "decrease brightness, open torch, go back, go home, activate voice")

ENTER_RX = re.compile(
    r"\bcontrol\s+(?:my\s+|the\s+)?(?:phone|mobile)\b|\b(?:phone|mobile)\s+(?:control|mode)\b"
    r"|\b(?:phone|mobile)\s+(?:ko\s+)?control\b|\bcontrol\s+(?:phone|mobile)\b|फोन\s+(?:को\s+)?(?:कंट्रोल|control)|कंट्रोल\s+फोन")
EXIT_RX = re.compile(r"\b(?:stop|exit|quit|end|close|leave)\s+(?:the\s+|my\s+)?(?:phone\s+)?(?:control(?:ling)?|phone\s+mode)\b"
                     r"|\b(?:laptop|computer|pc)\s+mode\b|\b(?:stop|exit)\s+controlling\b")


def wants_enter(text):
    t = (text or "").lower()
    return bool(ENTER_RX.search(t)) and not re.search(r"\b(?:stop|exit|end|close)\b", t)


# ------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------
def sh(cmd, timeout=25):
    return pl.sh(cmd, timeout=timeout)


def screen_size():
    if _S["size"]:
        return _S["size"]
    ok, out = sh("wm size")
    m = re.findall(r"(\d+)x(\d+)", out)
    w, h = (int(m[-1][0]), int(m[-1][1])) if m else (1080, 2400)
    _S["size"] = (w, h)
    return _S["size"]


def foreground():
    """Package name of the app on the phone screen ('' if unknown)."""
    for cmd, rx in (("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", r"\s([a-z][\w.]+)/"),
                    ("dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity'", r"\s([a-z][\w.]+)/")):
        ok, out = sh(cmd, timeout=15)
        m = re.search(rx, out)
        if m:
            return m.group(1)
    return ""


def is_locked():
    ok, out = sh("dumpsys window | grep -E 'mDreamingLockscreen|isStatusBarKeyguard|mShowingLockscreen'", timeout=15)
    return bool(re.search(r"(?:mDreamingLockscreen|isStatusBarKeyguard|mShowingLockscreen)=true", out))


def wake_and_unlock():
    pl.wake()
    if is_locked():
        w, h = screen_size()
        sh("input swipe %d %d %d %d 250" % (w // 2, int(h * .8), w // 2, int(h * .25)))   # works if there is no PIN
        time.sleep(0.8)
    return not is_locked()


# --- the phone screen as a list of items (text, description, position, clickable) ---
def _parse_tree(s):
    i, j = s.find("<?xml"), s.rfind("</hierarchy>")
    if i < 0 or j < 0:
        return []
    try:
        root = ET.fromstring(s[i:j + len("</hierarchy>")])
    except ET.ParseError:
        return []
    items = []
    for n in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        items.append({"text": n.get("text", ""), "desc": n.get("content-desc", ""), "id": n.get("resource-id", ""),
                      "cls": n.get("class", ""), "click": n.get("clickable") == "true", "box": (x1, y1, x2, y2),
                      "center": ((x1 + x2) // 2, (y1 + y2) // 2)})
    return items


def dump(tries=3):
    """Reads the phone screen. YouTube plays little video previews all the time, so Android often says
    'could not get idle state' and gives nothing. So: try again, try the other dump style, then the file way."""
    for k in range(tries):
        for extra in ((), ("--compressed",)):
            ok, raw = pl.adb_bytes("exec-out", "uiautomator", "dump", *(extra + ("/dev/tty",)))
            items = _parse_tree(raw.decode("utf-8", "replace"))
            if items:
                _S["dump_ok"] = True
                return items
        ok, out = sh("uiautomator dump /sdcard/roe_ui.xml >/dev/null 2>&1; cat /sdcard/roe_ui.xml", timeout=30)
        items = _parse_tree(out)
        if items:
            _S["dump_ok"] = True
            return items
        time.sleep(0.7)
    _S["dump_ok"] = False
    return []


def find(pattern, wait=4, fields=("text", "desc", "id"), items=None):
    rx = re.compile(pattern, re.I)
    end = time.time() + wait
    while True:
        for n in (items if items is not None else dump(1)):
            if any(n[f] and rx.search(n[f]) for f in fields):
                return n
        items = None
        if time.time() > end:
            return None
        time.sleep(0.7)


def tap(n):
    sh("input tap %d %d" % n["center"])


def tap_xy(x, y):
    sh("input tap %d %d" % (x, y))


def key(name):
    sh("input keyevent " + name)


# --- typing ---
_OK_CHARS = re.compile(r"[^A-Za-z0-9 .,!?@#_:/+=\-'()&]")


def type_text(text):
    """Types English letters / numbers where the cursor is. Returns False if nothing could be typed."""
    clean = _OK_CHARS.sub("", text or "").strip()
    if not clean:
        return False
    for i in range(0, len(clean), 120):
        sh("input text " + pl.q(clean[i:i + 120].replace(" ", "%s")))
    return True


# ------------------------------------------------------------------
# Contacts (read ONCE and kept, so every call/message is fast)
# ------------------------------------------------------------------
def _cached_resolve(name):
    if _S["book"] is None:
        _S["book"] = pl.read_contacts()
    book = _S["book"]
    hit = pl.match_contact(name, book) if book else None
    if not hit and pl.PHONE_BOOK:
        hit = pl.match_contact(name, pl.PHONE_BOOK)
    return hit, bool(book)


# ------------------------------------------------------------------
# Opening apps
# ------------------------------------------------------------------
CATEGORY_APPS = {          # the phone's OWN default app for these (works on every brand)
    "messages": "APP_MESSAGING", "message": "APP_MESSAGING", "sms": "APP_MESSAGING", "texts": "APP_MESSAGING",
    "contacts": "APP_CONTACTS", "gallery": "APP_GALLERY", "calculator": "APP_CALCULATOR",
    "calendar": "APP_CALENDAR", "browser": "APP_BROWSER", "email": "APP_EMAIL", "music player": "APP_MUSIC",
    "maps": "APP_MAPS",
}
EXTRA_APPS = {
    "google": "com.google.android.googlequicksearchbox", "play store": "com.android.vending",
    "playstore": "com.android.vending", "drive": "com.google.android.apps.docs", "meet": "com.google.android.apps.meetings",
    "zoom": "us.zoom.videomeetings", "netflix": "com.netflix.mediaclient", "prime video": "com.amazon.avod.thirdpartyclient",
    "hotstar": "in.startv.hotstar", "amazon": "in.amazon.mShop.android.shopping", "flipkart": "com.flipkart.android",
    "gpay": "com.google.android.apps.nbu.paisa.user", "google pay": "com.google.android.apps.nbu.paisa.user",
    "phonepe": "com.phonepe.app", "paytm": "net.one97.paytm", "swiggy": "in.swiggy.android",
    "zomato": "com.application.zomato", "uber": "com.ubercab", "ola": "com.olacabs.customer",
    "facebook": "com.facebook.katana", "messenger": "com.facebook.orca", "twitter": "com.twitter.android",
    "x": "com.twitter.android", "reddit": "com.reddit.frontpage", "pinterest": "com.pinterest",
    "files": "com.google.android.apps.nbu.files", "keep": "com.google.android.keep", "notes": "com.google.android.keep",
    "translate": "com.google.android.apps.translate", "youtube music": "com.google.android.apps.youtube.music",
    "whatsapp business": "com.whatsapp.w4b",
}
OPEN_WORDS = {"please", "my", "the", "app", "application", "on", "phone", "mobile", "now", "up"}


def installed_packages():
    if _S["pkgs"] is None:
        ok, out = sh("pm list packages", timeout=40)
        _S["pkgs"] = [l.split(":", 1)[1].strip() for l in out.splitlines() if l.startswith("package:")]
    return _S["pkgs"]


def nice(app):
    return pl._nice(app)


def open_app(app):
    app = re.sub(r"\s+", " ", (app or "").lower()).strip()
    app = " ".join(w for w in app.split() if w not in OPEN_WORDS) or app
    if not app:
        return "Which app should I open?"
    wake_and_unlock()
    # An app is already open and the word is written on its screen (for example "Images" inside Files)?
    # Then tap that, instead of looking for an app with that name.
    special = {"camera", "kemra", "कैमरा", "settings", "setting", "dialer", "keypad", "phone", "dial pad", "clock",
               "timer", "alarm", "alarms", "stopwatch"}
    known = set(CATEGORY_APPS) | set(EXTRA_APPS) | set(pl.PHONE_APPS)
    if app not in special and app not in known:
        fg = foreground()
        if fg and not fg.startswith("com.android.systemui") and "launcher" not in fg and "home" not in fg.split(".")[-1]:
            hit = screen_hit(app, fuzzy=False)
            if hit:
                tap(hit)
                return "Opening %s." % app.title()
    if app in ("camera", "kemra", "कैमरा"):
        return pl.do_camera()
    if app in ("settings", "setting"):
        sh("am start -a android.settings.SETTINGS")
        return "Opening Settings."
    if app in ("dialer", "keypad", "phone", "dial pad"):
        sh("am start -a android.intent.action.DIAL")
        return "Opening the dialer."
    if app in ("clock", "timer", "alarm", "alarms", "stopwatch"):
        ok, out = sh("am start -a android.intent.action.SHOW_ALARMS")
        if ok and not pl.failed(out):
            return "Opening the clock."
    if app in CATEGORY_APPS:
        ok, out = sh("am start -a android.intent.action.MAIN -c android.intent.category.%s" % CATEGORY_APPS[app])
        if ok and not pl.failed(out):
            return "Opening %s." % nice(app)
    pkg = pl.PHONE_APPS.get(app) or EXTRA_APPS.get(app)
    if not pkg:                                                   # look through the installed apps
        pkgs = installed_packages()
        squashed = app.replace(" ", "")
        cands = [p for p in pkgs if squashed in p.replace("_", "").lower().split(".")[-1]
                 or squashed in "".join(p.lower().split(".")[1:])]
        if cands:
            pkg = sorted(cands, key=len)[0]
        else:
            tails = {p: p.split(".")[-1].lower() for p in pkgs}
            close = difflib.get_close_matches(squashed, list(tails.values()), n=1, cutoff=0.75)
            if close:
                pkg = next(p for p, t in tails.items() if t == close[0])
    if not pkg:                                                   # not an app: maybe it is on the screen
        hit = screen_hit(app)
        if hit:
            tap(hit)
            return "Opening %s." % app.title()
        return "I could not find an app called %s on your phone, or on the screen." % app
    ok, out = sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % pkg)
    if "No activities found" in out or "monkey aborted" in out:
        return "%s does not seem to be installed on your phone." % nice(app)
    return "Opening %s." % nice(app)


def close_app(app=None):
    pkg = None
    if app and app not in ("this", "that", "it", "current", "app"):
        pkg = pl.PHONE_APPS.get(app) or EXTRA_APPS.get(app)
        if not pkg:
            hits = [p for p in installed_packages() if app.replace(" ", "") in p.lower()]
            pkg = sorted(hits, key=len)[0] if hits else None
    pkg = pkg or foreground()
    if not pkg or pkg.startswith("com.android.systemui") or "launcher" in pkg:
        return "There is no app open to close."
    sh("am force-stop " + pkg)
    key("KEYCODE_HOME")
    return "Closed the app."


# ------------------------------------------------------------------
# Scrolling, buttons, tapping
# ------------------------------------------------------------------
AMOUNT = {"little": 0.18, "normal": 0.42, "lot": 0.72}


def scroll(direction="down", amount="normal"):
    w, h = screen_size()
    f = AMOUNT.get(amount, 0.42)
    cx, cy = w // 2, h // 2
    if direction in ("top", "bottom"):
        a, b = (int(h * .25), int(h * .8)) if direction == "top" else (int(h * .8), int(h * .25))
        sh(";".join("input swipe %d %d %d %d 120" % (cx, a, cx, b) for _ in range(6)))
        return "Scrolled to the %s." % direction
    if direction in ("down", "up"):
        half = int(h * f / 2)
        a, b = (cy + half, cy - half) if direction == "down" else (cy - half, cy + half)
        sh("input swipe %d %d %d %d 300" % (cx, a, cx, b))
    else:
        half = int(w * 0.35)
        a, b = (cx + half, cx - half) if direction == "left" else (cx - half, cx + half)
        sh("input swipe %d %d %d %d 250" % (a, cy, b, cy))
    return "Scrolling %s." % direction


NAV = {
    "back": ("KEYCODE_BACK", "Going back."), "home": ("KEYCODE_HOME", "Going to the home screen."),
    "recents": ("KEYCODE_APP_SWITCH", "Showing your recent apps."), "enter": ("KEYCODE_ENTER", "Pressed enter."),
}


def nav(what):
    if what in NAV:
        key(NAV[what][0])
        return NAV[what][1]
    if what == "notifications":
        sh("cmd statusbar expand-notifications")
        return "Showing your notifications."
    if what == "quick_settings":
        sh("cmd statusbar expand-settings")
        return "Showing quick settings."
    if what == "close_panel":
        sh("cmd statusbar collapse")
        return "Closed."
    if what == "lock":
        key("KEYCODE_SLEEP")
        return "Locked your phone."
    if what == "unlock":
        return "Your phone is unlocked." if wake_and_unlock() else "Your phone has a PIN. Please unlock it yourself."
    return "I do not know that button."


def tap_text(label):
    label = (label or "").strip()
    if not label:
        return "Tell me what to tap."
    items = dump()
    n = find("^" + re.escape(label) + "$", wait=0, items=items) or find(re.escape(label), wait=2, items=items)
    if not n:                                                       # sounds similar
        best, score = None, 0.0
        for it in items:
            for f in ("text", "desc"):
                if it[f]:
                    r = difflib.SequenceMatcher(None, label.lower(), it[f].lower()).ratio()
                    if r > score:
                        best, score = it, r
        n = best if score >= 0.7 else None
    if not n:
        return "I could not see %s on the phone screen." % label
    tap(n)
    return "Tapped %s." % label


# ------------------------------------------------------------------
# Messages and chats
# ------------------------------------------------------------------
def open_chat(name, app="whatsapp"):
    hit, had = _cached_resolve(name)
    if not hit:
        return ("I could not find %s in your contacts." % name) if had else \
               "I could not read your contacts. Allow contacts for ADB, or add the name to PHONE_BOOK in phone_link.py."
    shown, number = hit
    wake_and_unlock()
    if app == "telegram":
        ok, out = sh("am start -a android.intent.action.VIEW -d " + pl.q("tg://resolve?phone=" + pl.wa_number(number)))
    else:
        ok, out = sh("am start -a android.intent.action.VIEW -p com.whatsapp -d " +
                     pl.q("whatsapp://send?phone=" + pl.wa_number(number)))
    if not ok or pl.failed(out):
        return "I could not open %s. Is it installed?" % nice(app)
    return "Opening your chat with %s." % shown


def send_text(text):
    """Types the words in the chat that is open right now and presses send."""
    if not _OK_CHARS.sub("", text or "").strip():
        return "I can only type English letters. Please say the message in English."
    box = find(r":id/entry$|:id/message_edit_text$|^message$|^type a message$|^text message$|^write a message",
               wait=2, fields=("id", "text", "desc"))
    if box:
        tap(box)
        time.sleep(0.4)
    type_text(text)
    time.sleep(0.7)
    btn = find(r"^send( sms| message| mms)?$|:id/send$|:id/conversation_send", wait=4, fields=("desc", "text", "id"))
    if not btn:
        return "I typed the message but could not find the send button. Tap send on the phone."
    tap(btn)
    return "Message sent."


def message(name, text, app):
    return pl.do_msg(name, text, app)


# ------------------------------------------------------------------
# Camera
# ------------------------------------------------------------------
def _in_camera():
    return "camera" in foreground().lower()


def _shutter():
    n = find(r"shutter|take photo|capture|take picture", wait=3, fields=("desc", "id", "text"))
    if n:
        tap(n)
    else:
        key("KEYCODE_CAMERA")


def photo():
    wake_and_unlock()
    t0 = pl.phone_time()
    if not _in_camera():
        ok, out = sh("am start -a android.media.action.STILL_IMAGE_CAMERA")
        if not ok or pl.failed(out):
            return "I could not open the camera. Unlock the phone and try again."
        time.sleep(2.5)
    _shutter()
    rows = pl.new_images(t0 - 2, wait=6)
    return "Photo taken." if rows else "I pressed the shutter. Please check the phone."


def video_start():
    wake_and_unlock()
    ok, out = sh("am start -a android.media.action.VIDEO_CAMERA")
    if not ok or pl.failed(out):
        return "I could not open the video camera."
    time.sleep(2.5)
    _shutter()
    _S["recording"] = True
    return "Recording a video. Say stop recording when you are done."


def video_stop():
    if not _S["recording"] and not _in_camera():
        return "No video is being recorded."
    _shutter()
    _S["recording"] = False
    return "Stopped recording."


def camera_switch():
    n = find(r"switch camera|flip camera|selfie|front camera|rear camera|camera facing", wait=3, fields=("desc", "text", "id"))
    if not n:
        return "I could not find the switch camera button. Open the camera first."
    tap(n)
    return "Switched the camera."


# ------------------------------------------------------------------
# YouTube: play the Nth video or a video by its title
# ------------------------------------------------------------------
_VIDEO_DESC = re.compile(r"play video|\bviews?\b|\bwatching\b|\bago\b|\d+\s*(?:second|minute|hour)s?\b|\blive\b|"
                         r"go to channel|\bshorts?\b|\b\d{1,2}:\d{2}\b|व्यू|घंटे|मिनट", re.I)


def _dedupe_rows(found, gap=40):
    found.sort(key=lambda p: p[1]["box"][1])
    out, seen = [], []
    for title, it in found:
        y1 = it["box"][1]
        if any(abs(y1 - sy) < gap for sy in seen):
            continue
        seen.append(y1)
        out.append((title, it))
    return out


def _yt_by_description(items, w, h):
    """Way 1: YouTube writes 'Title - 5 minutes - Channel - 1M views - 2 years ago - play video' on each video."""
    found = []
    for it in items:
        d = it["desc"] or ""
        x1, y1, x2, y2 = it["box"]
        if len(d) < 12 or not _VIDEO_DESC.search(d):
            continue
        if (y2 - y1) < h * 0.05 or (x2 - x1) < w * 0.4 or y1 < h * 0.05 or y1 > h * 0.97:
            continue
        title = re.split(r"\s+-\s+|,\s+\d+\s+(?:second|minute|hour)", d)[0].strip()
        found.append((title, it))
    return _dedupe_rows(found)


def _yt_by_thumbnail(items, w, h):
    """Way 2: no readable description (other language / new YouTube version): find the big 16:9 pictures.
    The title is the first text just under the picture."""
    found = []
    texts = [i for i in items if i["text"] and len(i["text"]) > 3]
    for it in items:
        x1, y1, x2, y2 = it["box"]
        bw, bh = x2 - x1, y2 - y1
        if bw < w * 0.85 or bh < h * 0.08 or bh <= 0 or y1 < h * 0.05 or y2 > h * 1.01:
            continue
        ratio = bw / float(bh)
        looks_like_video = 1.5 <= ratio <= 2.1 and ("Image" in it["cls"] or "thumbnail" in it["id"].lower()
                                                    or "View" in it["cls"])
        if not looks_like_video:
            continue
        below = sorted((t for t in texts if y2 - 10 <= t["box"][1] <= y2 + h * 0.18), key=lambda t: t["box"][1])
        found.append((below[0]["text"] if below else "this video", it))
    return _dedupe_rows(found, gap=int(h * 0.1))


def _yt_by_id(items, w, h):
    """Way 3: the program's own names (resource ids) for video rows."""
    found = []
    for it in items:
        x1, y1, x2, y2 = it["box"]
        if re.search(r"video_item|video_title|watch_card|compact_video|thumbnail_layout|search_result", it["id"], re.I) \
                and (y2 - y1) > h * 0.06 and (x2 - x1) > w * 0.5 and y1 > h * 0.05:
            found.append((it["text"] or it["desc"][:60] or "this video", it))
    return _dedupe_rows(found)


def youtube_items(items=None):
    """Videos visible on the screen, top to bottom: [(title, item)]."""
    w, h = screen_size()
    items = items if items is not None else dump()
    return _yt_by_description(items, w, h) or _yt_by_thumbnail(items, w, h) or _yt_by_id(items, w, h)


def _title_score(spoken, title):
    a = re.sub(r"[^a-z0-9 ]", " ", spoken.lower()).split()
    b = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    if not a or not b:
        return 0.0
    hit = sum(1 for w in a if w in b or difflib.get_close_matches(w, b, n=1, cutoff=0.8))
    return max(hit / len(a), difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio())


def youtube_search(query):
    wake_and_unlock()
    return pl.do_url("youtube", query)


def _visible_videos():
    """Videos on the screen. Waits and scrolls a little if the page is still loading."""
    for attempt in range(3):
        items = youtube_items()
        if items:
            return items
        if not _S["dump_ok"]:
            time.sleep(1.0)                          # screen could not be read (busy): try again
            continue
        if attempt == 1:
            scroll("down", "little")                 # maybe the list is just below
        time.sleep(1.0)
    return []


def pick(which=None, title=None):
    """Play / open the Nth thing (which = 1, 2, 3... or -1 = last) or the one with this title.
    On YouTube it picks videos; in any other app (Files, Gallery, Settings ...) it picks rows, folders and cards."""
    fg = foreground()
    if "youtube" not in fg:
        if title and which is None:
            return play_named(title)
        return pick_item(which, title)
    items = _visible_videos()
    if title and which is None:
        scored = sorted(((_title_score(title, t), t, it) for t, it in items), key=lambda p: -p[0])
        if scored and scored[0][0] >= 0.55:
            tap(scored[0][2])
            return "Playing %s." % scored[0][1][:80]
        return youtube_play_search(title)
    if not items:
        if not _S["dump_ok"]:
            return "I could not read the phone screen because YouTube is busy. Pause the preview and try again."
        return "I could not see any videos on the screen."
    idx = (len(items) - 1) if which == -1 else (which or 1) - 1
    if idx >= len(items):
        return "I can only see %d videos on the screen. Say scroll, then try again." % len(items)
    t, it = items[idx]
    tap(it)
    return "Playing video number %d: %s." % (idx + 1, t[:80])


# ------------------------------------------------------------------
# Inside ANY app: "open images", "open the third folder", "tap downloads"
# ------------------------------------------------------------------
def _norm_label(x):
    x = re.sub(r"[^a-z0-9 ]", " ", (x or "").lower())
    return re.sub(r"\s+", " ", x).strip()


def _singular(x):
    return x[:-1] if len(x) > 3 and x.endswith("s") else x


def screen_hit(label, items=None, fuzzy=True):
    """The thing on the phone screen that has this written on it (exact word first, then close spelling)."""
    want = _norm_label(label)
    if not want:
        return None
    w, h = screen_size()
    items = items if items is not None else dump()
    best, best_score = None, 0.0
    for it in items:
        x1, y1, x2, y2 = it["box"]
        if y1 < h * 0.03 or y2 > h * 1.01 or (x2 - x1) <= 0 or (y2 - y1) <= 0:
            continue
        for f in ("text", "desc"):
            got = _norm_label(it[f])
            if not got:
                continue
            if got == want or _singular(got) == _singular(want):
                return it
            if fuzzy:
                r = difflib.SequenceMatcher(None, _singular(want), _singular(got)).ratio()
                if want in got.split() and len(got.split()) <= 3:
                    r = max(r, 0.9)
                if r > best_score:
                    best, best_score = it, r
    return best if best_score >= 0.8 else None


def rows_on_screen(items=None):
    """The tappable things in an app, in reading order (rows top to bottom, each row left to right)."""
    w, h = screen_size()
    items = items if items is not None else dump()
    texts = [i for i in items if (i["text"] or i["desc"]) and i["box"][3] > i["box"][1]]
    cand = []
    for it in items:
        x1, y1, x2, y2 = it["box"]
        area = (x2 - x1) * (y2 - y1)
        if not it["click"] or area < w * h * 0.004 or area > w * h * 0.7 or y1 < h * 0.06 or y2 > h * 0.96:
            continue
        inside = [t for t in texts if t["box"][0] >= x1 - 4 and t["box"][1] >= y1 - 4 and t["box"][2] <= x2 + 4
                  and t["box"][3] <= y2 + 4]
        if inside:
            name = (inside[0]["text"] or inside[0]["desc"]).strip()
            cand.append({"item": it, "name": name, "box": (x1, y1, x2, y2)})
    # keep the innermost: a row, not the big list that holds the rows
    inner = [c for c in cand if not any(o is not c and o["box"][0] >= c["box"][0] and o["box"][1] >= c["box"][1]
                                        and o["box"][2] <= c["box"][2] and o["box"][3] <= c["box"][3] for o in cand)]
    if not inner:
        return []
    tol = max(25, int(0.5 * sorted(c["box"][3] - c["box"][1] for c in inner)[len(inner) // 2]))
    rows, out = [], []
    for c in sorted(inner, key=lambda c: c["box"][1]):
        if rows and c["box"][1] - rows[-1][0] <= tol:
            rows[-1][1].append(c)
        else:
            rows.append([c["box"][1], [c]])
    for _, row in rows:
        out.extend(sorted(row, key=lambda c: c["box"][0]))
    return out


def pick_item(which=None, title=None):
    """'open the second folder', 'open the last file', 'open the third one' in the app on the screen."""
    items = dump()
    if not items:
        return "I could not read the phone screen. Keep it unlocked and try again."
    if title:
        hit = screen_hit(title, items)
        if hit:
            tap(hit)
            return "Opening %s." % title
        return "I could not see %s on the phone screen." % title
    rows = rows_on_screen(items)
    if not rows:
        return "I could not see anything to open on the screen."
    idx = (len(rows) - 1) if which == -1 else (which or 1) - 1
    if idx >= len(rows):
        return "I can only see %d items on the screen. Say scroll, then try again." % len(rows)
    tap(rows[idx]["item"])
    return "Opening %s." % rows[idx]["name"][:60]


def youtube_play_search(title):
    """Not on screen: search for it on YouTube and play the first result."""
    youtube_search(title)
    time.sleep(3.5)
    items = youtube_items()
    if not items:
        return "I searched YouTube for %s, but could not see the results. Say play the first video." % title
    tap(items[0][1])
    return "Playing %s from YouTube." % items[0][0][:80]


def spotify_play(query=None):
    wake_and_unlock()
    if query:
        ok, out = sh("am start -a android.media.action.MEDIA_PLAY_FROM_SEARCH -p com.spotify.music "
                     "--es query %s --es android.intent.extra.focus vnd.android.cursor.item/*" % pl.q(query))
        if not ok or pl.failed(out):
            sh("am start -a android.intent.action.VIEW -d " + pl.q("spotify:search:" + query))
            return "I opened Spotify and searched for %s. Say play the first one, or tap it." % query
        time.sleep(3.5)
        n = find(r"^play$", wait=2, fields=("desc", "text"))
        if n:
            tap(n)
        return "Playing %s on Spotify." % query
    if "spotify" not in foreground():
        open_app("spotify")
        time.sleep(3)
    n = find(r"^play$", wait=3, fields=("desc", "text"))
    if n:
        tap(n)
    else:
        key("KEYCODE_MEDIA_PLAY")
    return "Playing music on Spotify."


def play_named(title):
    """'play kesariya' = Spotify (like on the laptop).  'play kesariya on youtube' = YouTube."""
    if "youtube" in foreground():
        return pick(None, title)
    return spotify_play(title)


MEDIA = {"play": "KEYCODE_MEDIA_PLAY", "pause": "KEYCODE_MEDIA_PAUSE", "next": "KEYCODE_MEDIA_NEXT",
         "previous": "KEYCODE_MEDIA_PREVIOUS", "toggle": "KEYCODE_MEDIA_PLAY_PAUSE"}
MEDIA_SAY = {"play": "Playing.", "pause": "Paused.", "next": "Next.", "previous": "Going to the previous one.",
             "toggle": "Done."}


def media(what):
    key(MEDIA[what])
    return MEDIA_SAY[what]


# ------------------------------------------------------------------
# Settings: volume, brightness, Bluetooth, Wi-Fi ...
# ------------------------------------------------------------------
def volume(direction=None, level=None):
    if direction == "mute":
        key("KEYCODE_VOLUME_MUTE")
        return "Muted your phone."
    if level is not None:
        idx = round(15 * max(0, min(100, level)) / 100)
        ok, out = sh("cmd media_session volume --stream 3 --set %d" % idx)
        if ok and not pl.failed(out):
            return "Phone volume set to %d percent." % level
        direction = "up" if level >= 50 else "down"
    k = "KEYCODE_VOLUME_UP" if direction == "up" else "KEYCODE_VOLUME_DOWN"
    sh(";".join("input keyevent " + k for _ in range(3)))
    return "Phone volume %s." % direction


def brightness(direction=None, level=None):
    ok, out = sh("settings get system screen_brightness")
    try:
        cur = int(out.split()[-1])
    except (ValueError, IndexError):
        cur = 128
    top = 255 if cur <= 255 else 4095
    if level is not None:
        new = int(top * max(1, min(100, level)) / 100)
    else:
        step = int(top * 0.2)
        new = max(5, min(top, cur + (step if direction == "up" else -step)))
    sh("settings put system screen_brightness_mode 0")
    sh("settings put system screen_brightness %d" % new)
    return "Brightness is now %d percent." % round(new * 100 / top)


# name -> (commands for ON, commands for OFF, a getter that returns 1 when ON, spoken name, quick-settings tile)
TOGGLES = {
    "bluetooth": (["cmd bluetooth_manager enable", "svc bluetooth enable"], ["cmd bluetooth_manager disable", "svc bluetooth disable"],
                  "settings get global bluetooth_on", "Bluetooth", r"bluetooth"),
    "wifi": (["svc wifi enable"], ["svc wifi disable"], "settings get global wifi_on", "Wi-Fi", r"wi-?fi|internet"),
    "data": (["svc data enable"], ["svc data disable"], "settings get global mobile_data", "Mobile data", r"mobile data|internet"),
    "airplane": (["cmd connectivity airplane-mode enable"], ["cmd connectivity airplane-mode disable"],
                 "settings get global airplane_mode_on", "Airplane mode", r"airplane|flight"),
    "location": (["settings put secure location_mode 3"], ["settings put secure location_mode 0"],
                 "settings get secure location_mode", "Location", r"location"),
    "nfc": (["svc nfc enable"], ["svc nfc disable"], None, "NFC", r"nfc"),
    "rotation": (["settings put system accelerometer_rotation 1"], ["settings put system accelerometer_rotation 0"],
                 "settings get system accelerometer_rotation", "Auto rotate", r"rotat"),
    "battery saver": (["settings put global low_power 1"], ["settings put global low_power 0"],
                      "settings get global low_power", "Battery saver", r"battery saver|power saving"),
    "dark mode": (["cmd uimode night yes"], ["cmd uimode night no"], None, "Dark mode", r"dark"),
    "hotspot": ([], [], None, "Hotspot", r"hotspot"),
}


def _state(getter):
    if not getter:
        return None
    ok, out = sh(getter)
    try:
        return int(out.split()[-1]) not in (0,)
    except (ValueError, IndexError):
        return None


def _tile(label_rx, on):
    sh("cmd statusbar expand-settings")
    time.sleep(1.2)
    n = find(label_rx, wait=3, fields=("desc", "text"))
    if not n:
        sh("cmd statusbar collapse")
        return False
    state = (n["desc"] + " " + n["text"]).lower()
    is_on = bool(re.search(r"\bon\b", state)) and not re.search(r"\boff\b", state)
    if is_on != on:
        tap(n)
        time.sleep(0.6)
    sh("cmd statusbar collapse")
    return True


def toggle(what, on):
    if what == "torch":
        return pl.do_torch(on)
    if what == "dnd":
        return pl.do_dnd(on)
    if what not in TOGGLES:
        return "I do not know how to switch %s." % what
    on_cmds, off_cmds, getter, spoken, tile_rx = TOGGLES[what]
    for c in (on_cmds if on else off_cmds):
        sh(c)
        time.sleep(0.8)
        now = _state(getter)
        if now is None or now == on:
            if now is not None or not getter:
                return "%s is %s." % (spoken, "on" if on else "off")
    if _tile(tile_rx, on):                                          # the phone refused: use the quick-settings button
        return "%s is %s." % (spoken, "on" if on else "off")
    return "Your phone did not let me change %s." % spoken


def battery():
    return pl.do_battery()


def screenshot():
    return pl.do_screenshot({}, True)


def call(name):
    return pl.do_call(name)


def answer_call():
    key("KEYCODE_CALL")
    time.sleep(1.0)
    n = find(r"^(answer|accept)", wait=1, fields=("desc", "text"))
    if n:
        tap(n)
    return "Answering the call."


def hangup():
    key("KEYCODE_ENDCALL")
    return "Call ended."


# ------------------------------------------------------------------
# The phone screen window on the laptop
# ------------------------------------------------------------------
def mirror_on():
    p = pl._MIRROR["proc"]
    if p and p.poll() is None:
        return "Your phone screen is already showing."
    exe = pl.find_scrcpy()
    if not exe:
        return ("I cannot show the screen because the scrcpy folder is missing from the Roe folder, "
                "but I can still control your phone by voice.")
    env = dict(os.environ)
    adb_path = pl.find_adb()
    if adb_path:
        env["ADB"] = adb_path
    args = [exe, "--stay-awake", "--no-audio", "--max-size", str(MIRROR_MAX_SIZE), "--window-title", MIRROR_TITLE]
    if TURN_PHONE_SCREEN_OFF:
        args.append("--turn-screen-off")
    pl._MIRROR["proc"] = subprocess.Popen(args, env=env, cwd=os.path.dirname(exe), creationflags=pl._flags())
    return "Showing your phone screen."


def mirror_off():
    p = pl._MIRROR["proc"]
    if p and p.poll() is None:
        p.terminate()
        pl._MIRROR["proc"] = None
        return "Closed the phone screen window."
    return "The phone screen was not showing."


# ------------------------------------------------------------------
# Turning phone mode on and off
# ------------------------------------------------------------------
def enter():
    """Returns the sentence to say. ACTIVE only becomes True if the phone is ready."""
    global ACTIVE
    bad = pl.phone_problem()
    if bad:
        return bad
    ok, out = pl.adb("devices")                                     # two phones plugged in: use the first one
    serials = [l.split()[0] for l in out.splitlines()[1:] if l.strip().endswith("device")]
    if len(serials) > 1:
        os.environ["ANDROID_SERIAL"] = serials[0]
    pl.resolve = _cached_resolve                                    # contacts are read once, then remembered
    _S.update({"book": None, "pkgs": None, "size": None, "recording": False})
    ACTIVE = True
    unlocked = wake_and_unlock()
    msg = "Phone control is on."
    if SHOW_SCREEN_ON_ENTER:
        shown = mirror_on()
        msg += " " + shown
    msg += " Say activate voice to come back to the laptop."
    if not unlocked:
        msg += " Your phone is locked, please unlock it."
    return msg


def leave(quiet=False):
    """Closes the phone screen and goes back to laptop mode."""
    global ACTIVE
    was = ACTIVE
    ACTIVE = False
    p = pl._MIRROR["proc"]
    if p and p.poll() is None:
        p.terminate()
    pl._MIRROR["proc"] = None
    if quiet or not was:
        return ""
    return "Phone control is off. I am back on your laptop."


# ------------------------------------------------------------------
# Understanding the words
# ------------------------------------------------------------------
ORD = {"first": 1, "1st": 1, "one": 1, "1": 1, "second": 2, "2nd": 2, "two": 2, "2": 2, "to": 2, "third": 3, "3rd": 3,
       "three": 3, "3": 3, "fourth": 4, "4th": 4, "four": 4, "for": 4, "4": 4, "fifth": 5, "5th": 5, "five": 5, "5": 5,
       "sixth": 6, "6th": 6, "six": 6, "6": 6, "seventh": 7, "7th": 7, "seven": 7, "7": 7, "eighth": 8, "8th": 8,
       "eight": 8, "8": 8, "ninth": 9, "9th": 9, "nine": 9, "9": 9, "tenth": 10, "10th": 10, "ten": 10, "10": 10,
       "last": -1, "pehla": 1, "pehle": 1, "pehli": 1, "doosra": 2, "dusra": 2, "doosri": 2, "dusri": 2, "dusara": 2,
       "teesra": 3, "teesri": 3, "tisra": 3, "tisri": 3, "chautha": 4, "chauthi": 4, "paanchva": 5, "paanchvi": 5,
       "aakhri": -1, "akhri": -1, "aakhiri": -1, "second last": -1}
ORD_RX = "|".join(sorted(ORD, key=len, reverse=True))
_FILL = r"(?:(?:please|can you|could you|would you|will you|hey|just|now|do it|kindly)\s+)*"
_NAME = r"(?:my\s+|mera\s+|meri\s+)?([\w']+(?:\s[\w']+)?)"
APPS_RX = r"(whatsapp|sms|text|text message|telegram)"
ON_WORDS = r"\b(?:on|enable|start|activate|chalu|shuru|turn on|switch on)\b"
OFF_WORDS = r"\b(?:off|disable|stop|deactivate|band|close|turn off|switch off|hatao)\b"


DEVA_WORDS = {
    "व्हाट्सएप": "whatsapp", "व्हाट्सऐप": "whatsapp", "व्हाट्सअप": "whatsapp", "वॉट्सऐप": "whatsapp", "वाट्सएप": "whatsapp",
    "व्हॉट्सऍप": "whatsapp", "व्हाट्स एप": "whatsapp", "यूट्यूब": "youtube", "यूट्यूब": "youtube", "कैमरा": "camera",
    "स्पॉटिफाई": "spotify", "स्पोटिफाई": "spotify", "ब्लूटूथ": "bluetooth", "वाईफाई": "wifi", "वाई-फाई": "wifi",
    "इंस्टाग्राम": "instagram", "क्रोम": "chrome", "गूगल": "google", "जीमेल": "gmail", "टेलीग्राम": "telegram",
    "सेटिंग्स": "settings", "सेटिंग": "settings", "बैटरी": "battery", "वॉल्यूम": "volume", "ब्राइटनेस": "brightness",
    "स्क्रॉल": "scroll", "फोटो": "photo", "वीडियो": "video", "मैसेज": "message", "टॉर्च": "torch", "फ्लैशलाइट": "flashlight",
}
try:
    import hindi_fix
    hindi_fix.merge_into(DEVA_WORDS)          # many more Hindi spellings (see hindi_fix.py)
except Exception:
    pass


def _clean(raw):
    t = pl.fix_sms((raw or "").strip())              # "S M S", "text message", "messages app" -> sms
    for k in sorted(DEVA_WORDS, key=len, reverse=True):
        t = t.replace(k, " %s " % DEVA_WORDS[k])
    try:
        import hindi_display
        t = hindi_display.roman(t)                                  # Devanagari -> Hinglish letters
    except Exception:
        pass
    return t


def _num(word):
    return ORD.get(word.lower().strip())


def _name(raw):
    n = pl._contact_name(raw.strip())
    n = re.sub(r"'s$", "", n.strip())
    return n


def _step(action, **args):
    return (action, args)


def parse_message(raw):
    """Messages first: they contain free words that must not be mistaken for commands."""
    r = raw.strip().strip(".!?। ")
    low = r.lower()
    # a) send [a] [whatsapp|sms] message [that] TEXT to NAME [on APP]
    m = re.match(_FILL + r"(?:send|write|type)\s+(?:a\s+|an\s+|the\s+)?(?:(?:whatsapp|sms|text)(?:\s+message)?|message|msg)\s+"
                 r"(?:saying\s+|that\s+|as\s+)?(.+)\s+to\s+(?:my\s+)?([\w']+(?:\s[\w']+)?)"
                 r"(?:\s+(?:on|via|through|using|by)\s+" + APPS_RX + r")?$", r, re.I)
    if m and not re.search(r"\bto\s+(?:my\s+)?(?:phone|laptop)$", low):
        kind = re.search(r"(whatsapp|sms|text)", low)
        app = m.group(3) or (kind.group(1) if kind and kind.group(1) in ("whatsapp", "sms", "text") else None)
        return _step("message", name=_name(m.group(2)), text=m.group(1).strip(), app=pl._app_word(app))
    # b) send [a] [whatsapp|sms] [message] to NAME [on APP] [that|saying] TEXT
    m = re.match(_FILL + r"(?:send|write)\s+(?:a\s+|an\s+|the\s+)?(?:(?:whatsapp|sms|text)(?:\s+message)?|message|msg)\s+"
                 r"to\s+(?:my\s+)?([\w']+)(?:\s+(?:on|via|through|using|by)\s+" + APPS_RX + r")?"
                 r"\s+(?:(?:saying|that|as|ki)\s+)?(.+)$", r, re.I)
    if m:
        kind = re.search(r"(whatsapp|sms|text)", low)
        app = m.group(2) or (kind.group(1) if kind else None)
        return _step("message", name=_name(m.group(1)), text=m.group(3).strip(), app=pl._app_word(app))
    # c) whatsapp|sms|text|message|msg|tell NAME [that|saying] TEXT
    m = re.match(_FILL + r"(whatsapp|sms|text|message|msg|tell)\s+(?:to\s+)?(?:my\s+)?([\w']+)\s+(?:(?:saying|that)\s+)?(.+)$", r, re.I)
    if m and m.group(2).lower() not in pl.NAME_STOP | {"me", "message", "messages", "chat", "chats", "app", "size"}:
        kind = m.group(1).lower()
        app = kind if kind in ("whatsapp", "sms") else ("sms" if kind == "text" else None)
        text = m.group(3).strip()
        tail = pl._APP_TAIL.match(text)
        if tail:
            text, app = tail.group(1), tail.group(2)
        return _step("message", name=_name(m.group(2)), text=text, app=pl._app_word(app))
    # d) send the message that TEXT  /  reply TEXT  /  type TEXT and send   (no name: goes to the open chat)
    m = re.match(_FILL + r"(?:send|write)\s+(?:the\s+|a\s+)?(?:message|msg|reply|text)\s*(?:saying\s+|that\s+|as\s+)?(.+)$", r, re.I)
    if not m:
        m = re.match(_FILL + r"reply\s+(?:saying\s+|with\s+)?(.+)$", r, re.I)
    if not m:
        m = re.match(_FILL + r"(?:type|write)\s+(.+?)\s+and\s+(?:send|press send)$", r, re.I)
    if m:
        return _step("send_text", text=m.group(1).strip())
    return None


def parse_chat(low):
    if not re.search(r"\b(?:chat|conversation|chats?)\b", low) or re.search(r"\b(?:message|send)\b", low):
        return None
    if not re.match(_FILL + r"(?:open|show|go to|goto|start|launch|kholo|khol)\b|.*\b(?:kholo|khol do)\b", low):
        return None
    t = re.sub(r"\b(?:open|show|go to|goto|start|launch|kholo|khol do|khol|please|the|my|a|an|chat|chats|conversation|with|of|on|in|"
               r"whatsapp|telegram|ki|ka|ke|mera|meri|mere|me|mein)\b", " ", low)
    t = re.sub(r"'s\b|\bs\b", " ", t)
    name = re.sub(r"\s+", " ", t).strip()
    app = "telegram" if "telegram" in low else "whatsapp"
    if not name or len(name.split()) > 3:
        return None
    return _step("open_chat", name=_name(name), app=app)


def parse_one(raw):
    """One sentence -> one step (action, args) or None."""
    raw = _clean(raw)
    msg = parse_message(raw)
    if msg:
        return msg
    low = re.sub(r"\s+", " ", re.sub(r"[.,!?।]+", " ", raw.lower())).strip()
    low = re.sub(r"^(?:(?:please|can you|could you|would you|will you|hey|just|now|kindly)\s+)+", "", low)
    if not low:
        return None
    has = lambda p: bool(re.search(p, low))

    ch = parse_chat(low)
    if ch:
        return ch

    # --- calls
    if has(r"\b(?:reject|decline|hang ?up|end|cut|disconnect|drop)\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:phone\s+)?call\b|\bcall\s+(?:cut|band|kaat)"):
        return _step("hangup")
    if has(r"\b(?:answer|pick up|accept|receive|attend)\s+(?:the\s+|this\s+|that\s+|my\s+)?(?:phone\s+)?call\b|\bcall\s+(?:utha|uthao)\b"):
        return _step("answer")

    # --- camera
    if has(r"\b(?:stop|end|finish)\s+(?:the\s+)?(?:recording|video)\b"):
        return _step("video_stop")
    if has(r"\b(?:record|shoot|start recording|film|take|make|capture)\b.*\bvideo\b|\bvideo\s+(?:record|shoot)\b|\bstart recording\b|\brecord\b$|\bvideo banao\b"):
        return _step("video_start")
    if has(r"\b(?:switch|flip|change|turn)\s+(?:the\s+)?camera\b|\bselfie (?:camera|mode)\b|\b(?:front|back|rear) camera\b"):
        return _step("camera_switch")
    if has(r"\bscreen ?shot\b|screen shot"):
        return _step("screenshot")
    if has(r"\b(?:take|click|capture|shoot|snap|khicho|kheencho|le|lo)\b.*\b(?:photo|picture|pic|selfie|image|photograph)\b|"
           r"\b(?:photo|picture|pic|selfie)\s+(?:le|lo|khicho|kheencho|click)\b|^(?:capture|shutter|smile|cheese)$"):
        return _step("photo")

    # --- scroll / swipe
    if has(r"\b(?:go|back|jump|scroll)\s+to\s+(?:the\s+)?(?:top|bottom)\b|^(?:top|bottom)$"):
        return _step("scroll", direction="top" if has(r"\btop\b") else "bottom", amount="normal")
    if has(r"\b(?:scroll|swipe|slide|scrol|skrol)\b|\b(?:neeche|niche|upar|oopar)\s+(?:karo|jao|le jao)\b|\bpage (?:down|up)\b"):
        d = "down"
        if has(r"\b(?:top|beginning|start|shuru)\b"):
            d = "top"
        elif has(r"\b(?:bottom|end|last|aakhir)\b"):
            d = "bottom"
        elif has(r"\bleft\b"):
            d = "left"
        elif has(r"\bright\b"):
            d = "right"
        elif has(r"\b(?:up|upar|oopar|upwards)\b"):
            d = "up"
        elif has(r"\b(?:down|neeche|niche|downwards)\b"):
            d = "down"
        amt = "lot" if has(r"\b(?:a lot|lot|much|more|fast|bahut|zyada|far)\b") else \
              ("little" if has(r"\b(?:little|bit|slightly|thoda|small)\b") else "normal")
        return _step("scroll", direction=d, amount=amt)

    # --- videos: the Nth one, or by title
    m = re.search(r"\b(?:play|open|watch|tap|click|select|choose|start|chalao|kholo|dekho)\s+(?:the\s+)?(?:video\s+(?:number\s+|no\.?\s+)?|number\s+|no\.?\s+)?"
                  r"(" + ORD_RX + r")(?:\s+(?:one|video|result|link|item|reel|short|vid|file|folder|chat|photo|picture|image|song|contact|app|"
                  r"message|email|mail|document|category|option|tab|card|row|wala|waala|wali))?$", low)
    if m and _num(m.group(1)):
        return _step("pick", which=_num(m.group(1)))
    m = re.search(r"\b(?:play|open|watch|tap|click|select|choose)\s+(?:the\s+)?(?:video|result|link)\s+(?:number\s+|no\.?\s+)(" + ORD_RX + r")$", low)
    if m:
        return _step("pick", which=_num(m.group(1)))
    m = re.search(r"\b(?:play|open|watch)\s+(?:the\s+)?(?:video|song)\s+(?:with\s+(?:the\s+|this\s+)?title|titled|called|named|about)\s+(.+)$", low)
    if m:
        return _step("pick", title=m.group(1).strip())
    m = re.search(r"\b(?:play|watch)\s+(?:the\s+)?video\s+(.+)$", low)
    if m and not _num(m.group(1)):
        return _step("pick", title=m.group(1).strip())
    m = re.search(r"\b(?:play|watch|chalao|dekho)\s+(.+?)\s+(?:on|in)\s+youtube$", low)
    if m:
        return _step("yt_play", title=m.group(1).strip())
    m = re.search(r"\b(?:play|chalao|bajao)\s+(.+?)\s+(?:on|in)\s+spotify$", low)
    if m:
        return _step("spotify", query=m.group(1).strip())

    # --- search
    m = re.search(r"\bsearch\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+youtube$", low)
    if m:
        return _step("yt_search", query=m.group(1).strip())
    m = re.match(r"(?:search|google|look up|find)\s+(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+google)?$", low)
    if m and not has(r"^find (?:my|the) (?:phone|file)"):
        return _step("search", query=m.group(1).strip())
    m = re.search(r"(\S+\.(?:com|in|org|net|co|io|edu|ai|gov))\b", raw.lower())
    if m and has(r"^(?:open|go to|visit|launch)\b"):
        return _step("url", url=m.group(1))

    # --- battery
    if has(r"\b(?:battery|charge|charging|charged)\b"):
        return _step("battery")

    # --- torch (before "open <app>")
    if has(r"\b(?:flashlight|flash light|torch|tourch|torchlight)\b"):
        return _step("toggle", what="torch", on=not has(OFF_WORDS))

    # --- volume and brightness
    if has(r"\b(?:volume|sound|awaaz|awaz|loud|louder)\b|\bmute\b"):
        if has(r"\bmute\b|\bsilent\b") and not has(r"\b(?:do not disturb|dnd|mode)\b"):
            return _step("volume", direction="mute")
        m = re.search(r"(\d{1,3})\s*(?:%|percent|per cent)?", low)
        if m and not has(r"\b(?:increase|decrease|raise|lower|up|down)\b"):
            return _step("volume", level=int(m.group(1)))
        if has(r"\b(?:max|maximum|full)\b"):
            return _step("volume", level=100)
        if has(r"\b(?:up|increase|louder|raise|badha\w*|high|higher|more|zyada)\b"):
            return _step("volume", direction="up")
        if has(r"\b(?:down|decrease|lower|reduce|kam\w*|less|low|softer|quieter)\b"):
            return _step("volume", direction="down")
    if has(r"\bbrightness\b|\bbright\b|\bdim\b|\broshni\b"):
        m = re.search(r"(\d{1,3})\s*(?:%|percent|per cent)?", low)
        if m and not has(r"\b(?:increase|decrease|raise|lower)\b"):
            return _step("brightness", level=int(m.group(1)))
        if has(r"\b(?:max|maximum|full)\b"):
            return _step("brightness", level=100)
        if has(r"\b(?:down|decrease|lower|reduce|kam\w*|less|dim|low)\b"):
            return _step("brightness", direction="down")
        return _step("brightness", direction="up")

    # --- toggles
    names = [("bluetooth", r"bluetooth|blue tooth"), ("wifi", r"wi-?fi|wi fi|wireless"), ("data", r"mobile data|cellular data|internet data"),
             ("airplane", r"airplane|aeroplane|flight mode"), ("location", r"location|gps"), ("nfc", r"\bnfc\b"),
             ("rotation", r"auto ?rotat\w*|rotation"), ("battery saver", r"battery saver|power saving"),
             ("dark mode", r"dark mode|night mode|dark theme"), ("hotspot", r"hotspot|hot spot"),
             ("dnd", r"do not disturb|don t disturb|dnd|silent mode")]
    for what, rx in names:
        if has(rx):
            if has(OFF_WORDS) and not has(r"\b(?:open|start)\b.*\bon\b"):
                return _step("toggle", what=what, on=False)
            if has(ON_WORDS) or has(r"\b(?:turn|switch|enable|activate)\b"):
                return _step("toggle", what=what, on=True)

    # --- music buttons
    if has(r"^(?:pause|stop)(?:\s+(?:the\s+)?(?:music|song|video|playback|it))?$|\bpause (?:the )?(?:music|song|video)\b"):
        return _step("media", what="pause")
    if has(r"^(?:resume|continue|play)(?:\s+(?:the\s+)?(?:music|song|video|it|playback))?$|^(?:play|start) (?:some |the )?(?:music|song|songs)$|\b(?:gaana|gana) (?:chalao|bajao)\b"):
        return _step("play_music")
    if has(r"\b(?:next|skip|agla)\b(?:\s+(?:song|track|video|one))?$|\bchange (?:the )?song\b"):
        return _step("media", what="next")
    if has(r"\b(?:previous|prev|pichla|go back to the last)\b(?:\s+(?:song|track|video|one))?$"):
        return _step("media", what="previous")
    m = re.match(r"(?:play|chalao|bajao)\s+(.+)$", low)
    if m and not has(r"\bplay\s+(?:the\s+)?(?:music|song)\b"):
        return _step("play_named", title=m.group(1).strip())

    # --- alarm / timer  (uses the existing phone_link parser)
    if has(r"^(?:open|show|launch|start)\s+(?:the\s+|my\s+)?(?:timer|alarm|alarms|clock|stopwatch)s?$"):
        return _step("open_app", app="clock")
    if has(r"\balarms?\b|\btimers?\b"):
        c = pl.parse_one(raw, force=True)
        if c:
            return _step("pl", cmd=c)

    # --- screen window
    if has(r"\b(?:hide|close|stop)\b.*\b(?:screen|mirror|window)\b|\bstop mirroring\b"):
        return _step("mirror", on=False)
    if has(r"\b(?:show|display|open)\b.*\b(?:phone )?screen\b|\bmirror\b"):
        return _step("mirror", on=True)

    # --- buttons
    if has(r"^(?:go )?back$|^go back$|\bpeeche\b|\bwapas\b"):
        return _step("nav", what="back")
    if has(r"^(?:go )?(?:to )?(?:the )?home(?: screen| button| page)?$|^go home$|\bhome screen\b|\bhome button\b"):
        return _step("nav", what="home")
    if has(r"\brecent apps?\b|\brecents\b|\bapp switcher\b|\bopen apps\b|\bshow (?:my )?apps\b"):
        return _step("nav", what="recents")
    if has(r"\b(?:close|hide|collapse)\s+(?:the\s+)?(?:notifications?|panel|quick settings|shade)\b"):
        return _step("nav", what="close_panel")
    if has(r"\bnotifications?\b"):
        return _step("nav", what="notifications")
    if has(r"\bquick settings\b|\bcontrol center\b"):
        return _step("nav", what="quick_settings")
    if has(r"\block\b.*\b(?:phone|screen)\b|\bturn off (?:the )?screen\b|\bscreen off\b|^lock$"):
        return _step("nav", what="lock")
    if has(r"\bunlock\b|\bwake up\b|\bturn on (?:the )?screen\b|\bscreen on\b"):
        return _step("nav", what="unlock")
    if has(r"^(?:press |hit )?(?:enter|go|done)$"):
        return _step("nav", what="enter")

    # --- close app
    m = re.match(r"(?:close|exit|quit|kill|stop)\s+(?:the\s+|this\s+|that\s+|current\s+|my\s+)*(?:app\s*)?([\w ]*)$", low)
    if m and has(r"^(?:close|exit|quit|kill)\b"):
        app = re.sub(r"\bapp\b", "", m.group(1)).strip()
        return _step("close_app", app=app or None)
    m = re.match(r"(.+?)\s+(?:band karo|band kar do|close karo)$", low)
    if m:
        return _step("close_app", app=m.group(1).strip())

    # --- calls
    c = None
    for rx in (pl._CALL_EN, pl._CALL_HI, pl._CALL_DEV):
        m = rx.match(low)
        if m:
            name = pl._contact_name(re.split(r"\s+(?:and|then|aur|phir)\s+", m.group(1))[0])
            if name and len(name.split()) <= 3:
                return _step("call", name=name)

    # --- tap / type
    m = re.match(r"(?:tap|click|press|touch|select|choose|hit)\s+(?:on\s+)?(?:the\s+)?(.+)$", low)
    if m:
        w = m.group(1).strip()
        if w in ("back", "home", "enter"):
            return _step("nav", what=w)
        return _step("tap_text", text=w)
    m = re.match(r"(?:type|enter|write|likho)\s+(.+)$", raw.strip().strip(".!?"), re.I)
    if m:
        return _step("type", text=m.group(1).strip())

    # --- open an app (last, so "open torch" etc. were caught above)
    m = re.match(r"(?:open|launch|start|run|go to)\s+(?:the\s+|my\s+)?(.+?)(?:\s+(?:app|on phone|on my phone))?$", low)
    if m:
        return _step("open_app", app=m.group(1).strip())
    m = re.match(r"(.+?)\s+(?:kholo|khol do|khol|chalu karo|chalao|open karo)$", low)
    if m:
        return _step("open_app", app=m.group(1).strip())
    return None


_SPLIT = re.compile(r"\s+(?:and then|and|then|after that|phir|fir|aur)\s+", re.I)


def parse(raw):
    """Returns a list of steps, or None."""
    raw = _clean(raw)
    one = parse_message(raw)
    if one:
        return [one]
    parts = _SPLIT.split(raw)
    if 2 <= len(parts) <= 4:
        steps = [parse_one(p) for p in parts]
        if all(steps):
            return steps
    one = parse_one(raw)
    if one:
        return [one]
    c = pl.parse_one(raw, force=True)                                # the older phone_link rules as a safety net
    if c:
        return [_step("pl", cmd=c)]
    return None


# ------------------------------------------------------------------
# Groq AI: only used when the rules above do not understand the sentence
# ------------------------------------------------------------------
AI_ACTIONS = {                       # action -> {argument: type}.  Only these can ever run.
    "open_app": {"app": str}, "close_app": {"app": str}, "open_chat": {"name": str, "app": str},
    "message": {"name": str, "text": str, "app": str}, "send_text": {"text": str},
    "scroll": {"direction": str, "amount": str}, "nav": {"what": str}, "tap_text": {"text": str}, "type": {"text": str},
    "photo": {}, "video_start": {}, "video_stop": {}, "camera_switch": {}, "screenshot": {},
    "pick": {"which": int, "title": str}, "yt_search": {"query": str}, "yt_play": {"title": str},
    "search": {"query": str}, "spotify": {"query": str}, "play_music": {}, "media": {"what": str},
    "call": {"name": str}, "hangup": {}, "answer": {}, "battery": {},
    "toggle": {"what": str, "on": bool}, "volume": {"direction": str, "level": int},
    "brightness": {"direction": str, "level": int},
}
AI_PROMPT = """You control an Android phone for the user by voice. The speech recogniser makes mistakes; work out what was meant.
The user speaks English, Hindi or Hinglish. Answer with ONLY JSON: {"steps": [{"action": "...", "args": {...}}, ...]}
Use 1 to 3 steps, in order. Use ONLY these actions:
open_app {app}   close_app {app}   open_chat {name, app: whatsapp|telegram}
message {name, text, app: whatsapp|sms}   (send a message to a named person)
send_text {text}   (type and send in the chat that is already open)
scroll {direction: up|down|left|right|top|bottom, amount: little|normal|lot}
nav {what: back|home|recents|notifications|quick_settings|lock|unlock|enter}
tap_text {text}   type {text}   photo   video_start   video_stop   camera_switch   screenshot
pick {which: 1-10 or -1 for last, OR title}   (play the Nth video / the video with a title on YouTube)
yt_search {query}   yt_play {title}   search {query}   spotify {query}   play_music   media {what: play|pause|next|previous}
call {name}   hangup   answer   battery
toggle {what: bluetooth|wifi|data|airplane|location|nfc|rotation|battery saver|dark mode|torch|dnd, on: true|false}
volume {direction: up|down|mute  OR  level: 0-100}   brightness {direction: up|down  OR  level: 5-100}
Message text and names stay in English letters. If the request does not fit, answer {"steps": []}."""


def ask_ai(text):
    if not (USE_GROQ_FOR_PHONE and llm.available()):
        return None
    raw = llm.chat([{"role": "system", "content": AI_PROMPT}, {"role": "user", "content": text}],
                   json_mode=True, max_tokens=300, temperature=0.0, timeout=10)
    if not raw:
        return None
    try:
        s, e = raw.find("{"), raw.rfind("}")
        obj = json.loads(raw[s:e + 1])
    except ValueError:
        return None
    steps = []
    for st in (obj.get("steps") or [])[:3]:
        if not isinstance(st, dict):
            continue
        name, args = str(st.get("action", "")).lower(), st.get("args") if isinstance(st.get("args"), dict) else {}
        spec = AI_ACTIONS.get(name)
        if spec is None:
            return None
        clean = {}
        for k, typ in spec.items():
            v = args.get(k)
            if v is None:
                continue
            try:
                clean[k] = (v if isinstance(v, bool) else str(v).lower() in ("true", "yes", "on")) if typ is bool else typ(v)
            except (TypeError, ValueError):
                pass
        if name in ("message", "open_chat") and not clean.get("name"):
            return None
        if name in ("message", "send_text", "type") and not clean.get("text"):
            return None
        steps.append((name, clean))
    return steps or None


# ------------------------------------------------------------------
# Running the steps
# ------------------------------------------------------------------
def run_step(s):
    a, g = s
    if a == "open_app":
        return open_app(g.get("app"))
    if a == "close_app":
        return close_app(g.get("app"))
    if a == "open_chat":
        return open_chat(g["name"], g.get("app", "whatsapp"))
    if a == "message":
        return message(g["name"], g["text"], pl._app_word(g.get("app")))
    if a == "send_text":
        return send_text(g["text"])
    if a == "scroll":
        return scroll(g.get("direction", "down") if g.get("direction") in ("up", "down", "left", "right", "top", "bottom") else "down",
                      g.get("amount", "normal"))
    if a == "nav":
        return nav(g.get("what", ""))
    if a == "tap_text":
        return tap_text(g.get("text"))
    if a == "type":
        return "Typed it." if type_text(g.get("text", "")) else "I can only type English letters and numbers."
    if a == "photo":
        return photo()
    if a == "video_start":
        return video_start()
    if a == "video_stop":
        return video_stop()
    if a == "camera_switch":
        return camera_switch()
    if a == "screenshot":
        return screenshot()
    if a == "pick":
        return pick(g.get("which"), g.get("title"))
    if a == "yt_search":
        return youtube_search(g["query"])
    if a == "yt_play":
        return youtube_play_search(g["title"] if g.get("title") else g.get("query", ""))
    if a == "search":
        wake_and_unlock()
        if "youtube" in foreground():
            return youtube_search(g["query"])
        return pl.do_url("google", g["query"])
    if a == "url":
        return pl.do_url("site", g["url"])
    if a == "spotify":
        return spotify_play(g.get("query"))
    if a == "play_music":
        return spotify_play(None) if "spotify" in foreground() else media("play")
    if a == "play_named":
        return play_named(g["title"])
    if a == "media":
        return media(g.get("what", "toggle")) if g.get("what") in MEDIA else "I do not know that music button."
    if a == "call":
        return call(g["name"])
    if a == "hangup":
        return hangup()
    if a == "answer":
        return answer_call()
    if a == "battery":
        return battery()
    if a == "toggle":
        return toggle(g["what"], bool(g.get("on", True)))
    if a == "volume":
        return volume(g.get("direction"), g.get("level"))
    if a == "brightness":
        return brightness(g.get("direction"), g.get("level"))
    if a == "mirror":
        return mirror_on() if g.get("on") else mirror_off()
    if a == "pl":
        r = pl.run(g["cmd"])
        return r or "I could not do that on the phone."
    return "I do not know that phone action."


_FAIL = re.compile(r"^(I could not|I cannot|I do not|Sorry|Tell me|Your phone did not|Which app|There is no|I can only|I can pick)")


def handle(text):
    """Does what was said on the phone. Returns the sentence to say."""
    if EXIT_RX.search((text or "").lower()):
        return leave()
    bad = pl.phone_problem()
    if bad:
        return bad
    try:
        steps = parse(text)
        if steps is None:
            steps = ask_ai(text)
        if steps is None:
            return "Sorry, I did not understand that for the phone. Could you say it again?"
        said = []
        for i, s in enumerate(steps):
            msg = run_step(s)
            said.append(msg)
            if _FAIL.match(msg or ""):
                break
            if i < len(steps) - 1:
                time.sleep(STEP_PAUSE + (1.5 if s[0] in ("open_app", "open_chat") else 0))
        return " ".join(said)
    except Exception as e:
        return "Sorry, the phone control did not work (%s)." % e


# ------------------------------------------------------------------
# Test (no phone needed):   py -3.11 phone_control.py
# ------------------------------------------------------------------
if __name__ == "__main__":
    tests = ["open whatsapp", "open daddy's chat", "scroll", "scroll down a lot", "open camera", "click a picture",
             "take a video", "stop recording", "open youtube", "play the second video", "play video number 3",
             "play the video with the title kesariya", "call daddy", "reject the call", "what is my phone battery",
             "turn on my phone's bluetooth", "open spotify and play the music", "increase the sound", "decrease brightness",
             "open torch", "open timer", "open google", "send the message that I reached home",
             "send a message that I reached home safely to my dad on whatsapp", "send sms to daddy that I reached home",
             "message mom I will be late", "go back", "go home", "play kesariya on youtube", "search best pizza",
             "set a timer for 5 minutes", "close this app", "tap on search", "type hello there", "wifi off", "volume 50"]
    print("Roe - phone control: what each sentence becomes (no phone needed)\n")
    for t in tests:
        r = parse(t)
        print("  %-66s -> %s" % (t, r if r else "NOT UNDERSTOOD (Groq AI would be asked)"))

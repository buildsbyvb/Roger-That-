"""
Roe - Step 10 + 11: Phone link (laptop -> Android phone), free, over a USB cable.

Say (English / Hindi / Hinglish). Words in [ ] are optional:
  CALLS      "call mom" | "mummy ko call karo" | "hang up" | "answer the call" | "reject the call"
  MESSAGES   "message mom I will be late" | "whatsapp mom hello" | "sms mom hello"
  FILES      "send my resume to my phone"  (lands in the phone's Downloads folder)
  PHOTOS     "take a screenshot of my phone" | "take a photo with my phone" | "open camera on phone"
  INFO       "phone battery"
  MUSIC      "pause the song on my phone" | "next song on phone" | "play music on phone"
  SOUND      "phone volume up" | "phone volume down" | "mute my phone" | "silent mode on my phone" | "silent mode off"
  TORCH      "flashlight on my phone" | "turn off the torch on phone"
  CLOCK      "set alarm on my phone for 7:30 am" | "timer for 5 minutes on my phone"
  WEB        "search best pizza on my phone" | "search arijit singh on youtube on my phone" | "open wikipedia.org on my phone"
  APPS       "open whatsapp on my phone"
  SCREEN     "show my phone screen" (needs scrcpy, see below) | "stop mirroring"
  TEXT       "type hello there on my phone" | "send my copied text to my phone"
  CHAINS     two or three jobs in one sentence, joined by "and" / "then":
             "take a screenshot and send it to mom on whatsapp"
             "take a photo and send it to papa on whatsapp"
             "send my resume to mom on whatsapp"
             "open camera on phone and take a photo"

HOW IT WORKS: the laptop talks to the phone with a free Google tool called ADB (over the USB cable).
Only the fixed actions below can ever run. Nothing you say is ever run as code.
Program files (.exe, .bat ...) are never sent to the phone.
KEEP THE PHONE UNLOCKED (screen on) - the tapping steps cannot work on the lock screen.

Test it any time:   py -3.11 phone_link.py
"""
import difflib
import mimetypes
import os
import re
import shutil
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET

# ---------------- Settings you can change ----------------
CONFIRM_CALLS = False          # True = Roe asks "Are you sure?" before every call
DEFAULT_MESSAGE_APP = "whatsapp"   # "message mom ..." uses this ("whatsapp" or "sms")
SMS_AUTO_SEND = True           # True = press the send button of the Messages app too. False = only write the message (draft)
DEFAULT_COUNTRY_CODE = "91"    # added in front of 10-digit numbers for WhatsApp
# Other names you might say for the same person (all lower case). Add your own.
ALIASES = [
    ["mom", "mummy", "mommy", "mother", "maa", "mama", "aai", "mumma"],
    ["dad", "papa", "daddy", "father", "baba", "pappa"],
]
# Backup list used only if the phone's contact list cannot be read:  "name": "number"
PHONE_BOOK = {
    # "mom": "+919999999999",
}
# Apps you can open on the phone. Say the name on the left.
PHONE_APPS = {
    "whatsapp": "com.whatsapp",
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "instagram": "com.instagram.android",
    "gmail": "com.google.android.gm",
    "maps": "com.google.android.apps.maps",
    "photos": "com.google.android.apps.photos",
    "spotify": "com.spotify.music",
    "telegram": "org.telegram.messenger",
    "snapchat": "com.snapchat.android",
    "linkedin": "com.linkedin.android",
    "calculator": "com.google.android.calculator",
    "clock": "com.google.android.deskclock",
}
# ----------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
SEARCH_FOLDERS = [os.path.join(HOME, n) for n in
                  ("Desktop", "Documents", "Downloads", "OneDrive/Desktop", "OneDrive/Documents")] + [HERE]
SAVE_FOLDER = os.path.join(HOME, "Pictures", "DoIt_Phone")      # phone pictures shown on the laptop go here
BAD_EXT = {".exe", ".bat", ".cmd", ".ps1", ".msi", ".dll", ".vbs", ".js", ".lnk", ".scr", ".com", ".reg"}
PHONE_FOLDER = "/sdcard/Download"                                # the phone's Downloads folder
SHARE_PACKAGES = {"whatsapp": "com.whatsapp", "telegram": "org.telegram.messenger"}

ACTIONS = {"phone_call", "phone_hangup", "phone_answer", "phone_camera", "phone_send", "phone_app", "phone_msg",
           "phone_share", "phone_file_share", "phone_screenshot", "phone_photo", "phone_battery", "phone_music",
           "phone_volume", "phone_dnd", "phone_torch", "phone_alarm", "phone_timer", "phone_url", "phone_mirror",
           "phone_type", "phone_clip", "phone_chain"}
NO_TRANSLATE = set()

PROMPT = """phone_call    args: {"name": "..."}   ("call mom", "mummy ko call karo": call a contact on her PHONE)
phone_hangup  args: {}                 ("hang up", "end the call" on her phone)
phone_camera  args: {}                 ("open camera on my phone")
phone_send    args: {"file": "..."}    ("send my resume to my phone": copy a laptop file to her PHONE; file = the words naming it)
phone_app     args: {"app": "..."}     ("open whatsapp on my phone")
phone_msg     args: {"name": "...", "text": "...", "app": "whatsapp or sms"}   ("message mom I will be late")"""

PHONE_WORD = r"(?:\b(?:phone|mobile|cell|smartphone)\b|फोन|फ़ोन|मोबाइल)"
PHONE_RX = re.compile(PHONE_WORD)
PHONE_ONLY = re.compile(PHONE_WORD + r"|\bwhatsapp\b|\bsms\b|\bcall\b|\bdial\b|\bmessage\b|\btelegram\b"
                        r"|\bsend (?:it|that|this) to\b|कॉल")
DEVA_NAMES = {"मम्मी": "mummy", "मॉम": "mom", "मां": "maa", "माँ": "maa", "पापा": "papa", "डैड": "dad",
              "भाई": "bhai", "दीदी": "didi", "दादी": "dadi", "नानी": "nani", "दादा": "dada", "नाना": "nana"}
NAME_STOP = {"on", "my", "the", "phone", "mobile", "a", "an", "to", "me", "us", "you", "him", "her", "them", "it",
             "open", "kholo", "khol", "chalu", "chalao", "start"}


def _cmd(action, arg=None, say="", risky=False):
    return {"action": action, "arg": arg, "say": say, "risky": risky}


def q(s):
    """Safe single quotes for the phone's shell."""
    return "'" + str(s).replace("'", "'\\''") + "'"


# ------------------------------------------------------------------
# Talking to the phone (ADB)
# ------------------------------------------------------------------
def find_adb():
    p = shutil.which("adb")
    if p:
        return p
    for folder in (os.path.join(HERE, "platform-tools"), HERE):
        for exe in ("adb.exe", "adb"):
            f = os.path.join(folder, exe)
            if os.path.isfile(f):
                return f
    return None


def _flags():
    return 0x08000000 if os.name == "nt" else 0          # no black window


def adb(*args, timeout=25):
    """Runs one ADB command. Returns (ok, output text)."""
    exe = find_adb()
    if not exe:
        return False, "NO_ADB"
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, text=True, timeout=timeout,
                           creationflags=_flags(), encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    out = ((r.stdout or "") + (r.stderr or "")).strip()
    return r.returncode == 0, out


def adb_bytes(*args, timeout=40):
    """Same, but returns raw bytes (for screenshots and the screen tree)."""
    exe = find_adb()
    if not exe:
        return False, b""
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, timeout=timeout, creationflags=_flags())
    except subprocess.TimeoutExpired:
        return False, b""
    return r.returncode == 0, r.stdout


def sh(cmd, timeout=25):
    """Runs one command INSIDE the phone."""
    return adb("shell", cmd, timeout=timeout)


def failed(out):
    return bool(re.search(r"Error|Exception|Denial|not allowed|No activities", out or "", re.I))


def phone_problem():
    """None if the phone is ready, otherwise one short sentence saying what to fix."""
    ok, out = adb("devices")
    if out == "NO_ADB":
        return "I cannot find ADB. Put the platform-tools folder inside the Roe folder."
    states = [ln.split()[-1] for ln in out.splitlines()[1:] if ln.strip() and len(ln.split()) >= 2]
    if not states:
        return "I cannot see your phone. Plug in the USB cable and unlock the phone."
    if "device" in states:
        return None
    if "unauthorized" in states:
        return "Your phone is asking permission. Tap Allow on the phone screen."
    return "Your phone is not ready (%s). Unplug and plug the cable again." % states[0]


def wake():
    sh("input keyevent KEYCODE_WAKEUP")


# ------------------------------------------------------------------
# Contacts
# ------------------------------------------------------------------
def _clean_number(n):
    return re.sub(r"[^\d+]", "", n or "")


def read_contacts():
    """Returns {name: number} from the phone. Empty if it cannot be read."""
    ok, out = adb("shell", "content", "query", "--uri", "content://com.android.contacts/data/phones",
                  "--projection", "display_name:data1", timeout=40)
    book = {}
    for m in re.finditer(r"display_name=(.*?), data1=(.*?)\s*$", out, re.M):
        num = _clean_number(m.group(2))
        if num:
            book.setdefault(m.group(1).strip(), num)
    return book


def _same_person_names(name):
    name = name.lower().strip()
    names = {name}
    for group in ALIASES:
        if name in group:
            names |= set(group)
    return names


def match_contact(name, book):
    """Best contact for the spoken name -> (display name, number) or None."""
    wanted = _same_person_names(name)
    low = {k.lower(): (k, v) for k, v in book.items()}
    for w in wanted:                                    # 1. exact
        if w in low:
            return low[w]
    for w in wanted:                                    # 2. the contact starts with / contains the word
        for k, kv in low.items():
            if w in k.split() or k.startswith(w):
                return kv
    for w in wanted:                                    # 3. sounds similar
        close = difflib.get_close_matches(w, list(low), n=1, cutoff=0.72)
        if close:
            return low[close[0]]
    return None


def resolve(name):
    book = read_contacts()
    hit = match_contact(name, book) if book else None
    if not hit and PHONE_BOOK:
        hit = match_contact(name, PHONE_BOOK)
    return hit, bool(book)


def wa_number(num):
    d = re.sub(r"\D", "", num)
    if num.startswith("+"):
        return d
    d = d.lstrip("0")
    if len(d) == 10:
        d = DEFAULT_COUNTRY_CODE + d
    return d


# ------------------------------------------------------------------
# Reading and tapping the phone screen (UI tree)
# ------------------------------------------------------------------
def ui_nodes():
    ok, raw = adb_bytes("exec-out", "uiautomator", "dump", "/dev/tty")
    s = raw.decode("utf-8", "replace")
    i, j = s.find("<?xml"), s.rfind("</hierarchy>")
    if i < 0 or j < 0:
        return []
    try:
        root = ET.fromstring(s[i:j + len("</hierarchy>")])
    except ET.ParseError:
        return []
    nodes = []
    for n in root.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        nodes.append({"text": n.get("text", ""), "desc": n.get("content-desc", ""),
                      "id": n.get("resource-id", ""), "center": ((x1 + x2) // 2, (y1 + y2) // 2)})
    return nodes


def wait_ui(pattern, wait=8, fields=("text", "desc")):
    """Waits until a screen item matching the pattern shows up. Returns it or None."""
    rx = re.compile(pattern, re.I)
    end = time.time() + wait
    while True:
        for n in ui_nodes():
            if any(n[f] and rx.search(n[f]) for f in fields):
                return n
        if time.time() > end:
            return None
        time.sleep(0.8)


def tap_node(n):
    sh("input tap %d %d" % n["center"])


def tap_ui(pattern, wait=8, fields=("text", "desc")):
    n = wait_ui(pattern, wait, fields)
    if n:
        tap_node(n)
    return n


# ------------------------------------------------------------------
# Finding a laptop file to send
# ------------------------------------------------------------------
_FILLER = {"my", "the", "a", "an", "this", "that", "file", "files", "document", "doc", "please", "can", "could",
           "you", "me", "send", "share", "transfer", "to", "on", "in", "into", "onto", "phone", "mobile", "cell",
           "smartphone", "mere", "ko", "par", "pe", "mein", "me", "bhejo", "bhej", "bhejna", "do", "dena", "karo",
           "kar", "dijiye", "from", "laptop", "फोन", "फ़ोन", "मोबाइल", "भेजो", "भेज", "दो", "को", "पर", "में",
           "मेरे", "मेरा", "मेरी", "फाइल", "और", "now", "it", "of", "and"}


def file_words(text):
    t = re.sub(r"[.,!?।]+", " ", text.lower())
    return [w for w in t.split() if w not in _FILLER]


def find_file(words):
    """Newest file whose name contains all the words (or sounds like them)."""
    if not words:
        return None
    best, best_score = None, 0.0
    query = " ".join(words)
    for folder in SEARCH_FOLDERS:
        if not os.path.isdir(folder):
            continue
        base_depth = folder.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d.lower() not in
                       ("node_modules", "__pycache__", "venv", ".git", "appdata", "platform-tools", "scrcpy")]
            if root.count(os.sep) - base_depth >= 3:
                dirs[:] = []
            for f in files:
                stem, ext = os.path.splitext(f)
                if ext.lower() in BAD_EXT or f.startswith("."):
                    continue
                s = re.sub(r"[_\-.]+", " ", stem.lower())
                if all(w in s for w in words):
                    score = 2.0
                else:
                    score = difflib.SequenceMatcher(None, query, s).ratio()
                    if score < 0.6:
                        continue
                path = os.path.join(root, f)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                key = score + mtime / 1e12                  # newer wins a tie
                if key > best_score:
                    best, best_score = path, key
    return best


def laptop_open(path):
    try:
        if hasattr(os, "startfile"):
            os.startfile(path)
    except Exception:
        pass


# ------------------------------------------------------------------
# Phone pictures (MediaStore = the phone's photo list)
# ------------------------------------------------------------------
def phone_time():
    ok, out = sh("date +%s")
    try:
        return int(out.split()[-1])
    except (ValueError, IndexError):
        return int(time.time())


def new_images(since, wait=0):
    """Pictures on the phone added since the given phone-time. Returns [(id, name, path)], newest first."""
    end = time.time() + wait
    while True:
        ok, out = sh('content query --uri content://media/external/images/media '
                     '--projection _id:_display_name:_data --where "date_added>=%d"' % since, timeout=40)
        rows = re.findall(r"_id=(\d+), _display_name=(.*?), _data=(.*?)\s*$", out, re.M)
        rows = sorted(((int(a), b, c) for a, b, c in rows), reverse=True)
        if rows or time.time() > end:
            return rows
        time.sleep(1.0)


# ------------------------------------------------------------------
# The parts that do things (each returns a sentence; ctx carries "what we just made" in chains)
# ------------------------------------------------------------------
def do_call(name):
    hit, had_book = resolve(name)
    if not hit:
        if not had_book:
            return ("I could not read your contacts. Add the name and number to PHONE_BOOK in phone_link.py, "
                    "or allow contacts access on the phone.")
        return "I could not find %s in your contacts." % name
    shown, number = hit
    wake()
    ok, out = sh("am start -a android.intent.action.CALL -d tel:" + number)
    if (not ok) or failed(out):
        sh("am start -a android.intent.action.DIAL -d tel:" + number)
        return ("Your phone did not allow me to start the call, so I opened the dialer with %s's number. "
                "Press the green call button." % shown)
    return "Calling %s." % shown


def do_hangup():
    sh("input keyevent KEYCODE_ENDCALL")
    return "Call ended."


def do_answer():
    sh("input keyevent KEYCODE_CALL")
    return "Answering the call."


def do_camera():
    wake()
    ok, out = sh("am start -a android.media.action.STILL_IMAGE_CAMERA")
    if not ok or failed(out):
        return "I could not open the camera. Unlock the phone and try again."
    return "Opening the camera on your phone."


def do_app(app):
    wake()
    if app in ("settings", "setting"):
        sh("am start -a android.settings.SETTINGS")
        return "Opening Settings on your phone."
    if app in ("dialer", "keypad"):
        sh("am start -a android.intent.action.DIAL")
        return "Opening the dialer on your phone."
    if app == "camera":
        return do_camera()
    pkg = PHONE_APPS.get(app)
    if not pkg:
        return "I do not know the phone app %s. Add it to PHONE_APPS in phone_link.py." % app
    ok, out = sh("monkey -p %s -c android.intent.category.LAUNCHER 1" % pkg)
    if "No activities found" in out or "monkey aborted" in out:
        return "%s does not seem to be installed on your phone." % _nice(app)
    return "Opening %s on your phone." % _nice(app)


def push_file(path):
    """Copies a laptop file into the phone's Downloads folder. Returns (remote path or None, message)."""
    name = re.sub(r"\s+", "_", os.path.basename(path))
    remote = PHONE_FOLDER + "/" + name
    ok, out = adb("push", path, remote, timeout=180)
    if not ok:
        return None, "Sending failed: %s" % out[-120:]
    sh("am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d " + q("file://" + remote))
    return remote, ""


def do_send(file_query, ctx=None):
    words = file_words(file_query or "")
    if not words:
        return "Tell me the file name, for example: send resume to my phone."
    path = find_file(words)
    if not path:
        return "I could not find a file named %s on your laptop." % " ".join(words)
    remote, err = push_file(path)
    if not remote:
        return err
    if ctx is not None:
        ctx["remote"] = remote
    return "Sent %s to your phone's Downloads folder." % os.path.basename(path)


def do_screenshot(ctx, for_share):
    """for_share False: show the phone screen on the laptop. True: take it on the phone (for sending on)."""
    if not for_share:
        ok, png = adb_bytes("exec-out", "screencap", "-p")
        if not ok or len(png) < 1000:
            return "I could not take the screenshot. Unlock the phone and try again."
        os.makedirs(SAVE_FOLDER, exist_ok=True)
        path = os.path.join(SAVE_FOLDER, "Phone_screenshot_%s.png" % time.strftime("%Y%m%d_%H%M%S"))
        with open(path, "wb") as f:
            f.write(png)
        laptop_open(path)
        return "Here is your phone screen. It is saved in Pictures, DoIt_Phone."
    wake()
    t0 = phone_time()
    sh("input keyevent KEYCODE_SYSRQ")                   # the phone's own screenshot
    rows = new_images(t0 - 2, wait=5)
    if rows:
        ctx["uri"] = "content://media/external/images/media/%d" % rows[0][0]
        ctx["mime"] = "image/*"
        return "Took a screenshot on your phone."
    ok, png = adb_bytes("exec-out", "screencap", "-p")   # backup way
    if not ok or len(png) < 1000:
        return "I could not take the screenshot. Unlock the phone and try again."
    tmp = os.path.join(HERE, "_phone_shot.png")
    with open(tmp, "wb") as f:
        f.write(png)
    remote, err = push_file(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if not remote:
        return err
    ctx["remote"], ctx["mime"] = remote, "image/png"
    return "Took a screenshot on your phone."


def _press_shutter():
    n = wait_ui(r"shutter|take photo|capture", wait=3, fields=("desc", "id", "text"))
    if n:
        tap_node(n)
    else:
        sh("input keyevent KEYCODE_CAMERA")


def do_photo(ctx, for_share):
    wake()
    t0 = phone_time()
    ok, out = sh("am start -a android.media.action.STILL_IMAGE_CAMERA")
    if not ok or failed(out):
        return "I could not open the camera. Unlock the phone and try again."
    time.sleep(2.5)
    _press_shutter()
    rows = new_images(t0 - 2, wait=10)
    if not rows:
        return "I opened the camera but could not find the new photo. Check the phone."
    pid, name, path = rows[0]
    if for_share:
        ctx["uri"] = "content://media/external/images/media/%d" % pid
        ctx["mime"] = "image/*"
        return "Took a photo with your phone."
    os.makedirs(SAVE_FOLDER, exist_ok=True)
    local = os.path.join(SAVE_FOLDER, name)
    ok, out = adb("pull", path, local, timeout=60)
    if not ok:
        return "I took the photo but could not copy it to the laptop."
    laptop_open(local)
    return "Took a photo. It is on your laptop in Pictures, DoIt_Phone."


def do_share(ctx, name, app):
    """Sends what the earlier step made (or the newest phone picture) to a contact."""
    app = app if app in SHARE_PACKAGES else "whatsapp"
    pkg = SHARE_PACKAGES[app]
    hit, had_book = resolve(name)
    display = hit[0] if hit else name
    uri, mime = ctx.get("uri"), ctx.get("mime", "*/*")
    if not uri and ctx.get("remote"):
        uri = "file://" + ctx["remote"]
        mime = mimetypes.guess_type(ctx["remote"])[0] or "*/*"
    if not uri:
        rows = new_images(phone_time() - 900)
        if not rows:
            return "I do not have anything to send. Take a screenshot or photo first."
        uri, mime = "content://media/external/images/media/%d" % rows[0][0], "image/*"
    wake()
    ok, out = sh("am start -a android.intent.action.SEND -t %s --eu android.intent.extra.STREAM %s -p %s "
                 "--grant-read-uri-permission" % (q(mime), q(uri), pkg))
    if not ok or failed(out):
        return "I could not open %s to share. Is it installed?" % _nice(app)
    time.sleep(2)
    pattern = "^" + re.escape(display) + "$"
    node = wait_ui(pattern, wait=6, fields=("text",))
    if not node:                                       # use the search box
        if tap_ui(r"^search", wait=3, fields=("desc", "text")):
            time.sleep(0.8)
            sh("input text " + q(re.sub(r"[^A-Za-z0-9]", "", display)))
            time.sleep(1.5)
        node = wait_ui(re.escape(display), wait=6, fields=("text",))
    if not node:
        return "I opened %s but could not find %s in the list. Pick the contact yourself and tap send." % (
            _nice(app), display)
    tap_node(node)
    time.sleep(1.5)
    for _ in range(2):                                 # the send button (sometimes there are two screens)
        if not tap_ui(r"^send$", wait=4, fields=("desc", "text")):
            break
        time.sleep(2.5)
    return "Sent it to %s on %s." % (display, _nice(app))


def do_file_share(ctx, file_query, name, app):
    words = file_words(file_query or "")
    if not words:
        return "Tell me the file name."
    path = find_file(words)
    if not path:
        return "I could not find a file named %s on your laptop." % " ".join(words)
    remote, err = push_file(path)
    if not remote:
        return err
    ctx["remote"] = remote
    ctx.pop("uri", None)
    return "Copied %s to your phone's Downloads." % os.path.basename(path) + " " + do_share(ctx, name, app)



# ---- "SMS" can be heard in many ways: "S M S", "S.M.S.", "as MS", "text message", "messages app" ... all mean SMS ----
_SMS_SAYINGS = [
    (re.compile(r"एस\s?एम\s?एस"), "sms"),
    (re.compile(r"\b(?:s\.?\s?m\.?\s?s\.?|as\s?m\s?s|es\s?em\s?es|ess\s?em\s?ess|s\s?n\s?s|asms)(?=\s|$|[.,!?])", re.I), "sms"),
    (re.compile(r"\b(?:text\s+messages?|normal\s+messages?|regular\s+messages?|plain\s+messages?|phone\s+messages?|"
                r"messages?\s+app|messaging\s+app|default\s+messages?|google\s+messages|samsung\s+messages|"
                r"sms\s+message)\b", re.I), "sms"),
]


def fix_sms(raw):
    t = raw or ""
    for rx, to in _SMS_SAYINGS:
        t = rx.sub(to, t)
    return t


def sms_package():
    """The phone's own default messages app (so the SMS never goes to WhatsApp)."""
    ok, out = sh("cmd role get-role-holders android.app.role.SMS")
    m = re.search(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", out or "")
    if not m:
        ok, out = sh("settings get secure sms_default_application")
        m = re.search(r"[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+", out or "")
    return m.group(0) if m else None


def do_msg(name, text, app):
    hit, had_book = resolve(name)
    if not hit:
        return "I could not find %s in your contacts." % name if had_book else \
            "I could not read your contacts. Add the name and number to PHONE_BOOK in phone_link.py."
    shown, number = hit
    wake()
    body = urllib.parse.quote(text, safe="")
    if app == "sms":
        pkg = sms_package()                           # the phone's OWN messages app, never WhatsApp
        base = "am start -a android.intent.action.SENDTO -d " + q("sms:%s?body=%s" % (number, body)) + \
               " --es sms_body " + q(text) + " --ez exit_on_sent true"
        ok, out = sh(base + (" -p " + pkg if pkg else ""))
        if pkg and (not ok or failed(out)):
            ok, out = sh(base)                        # that app did not take it: let the phone choose
        pattern = r"^send( sms| message| mms| text)?( message)?$|send_message_button|compose_send|:id/send$|sendbutton"
        label = "a text message"
    else:
        ok, out = sh("am start -a android.intent.action.VIEW -d " + q("whatsapp://send?phone=%s&text=%s" % (
            wa_number(number), body)))
        pattern = r"^send$"
        label = "a WhatsApp message"
    if not ok or failed(out):
        return "I could not open the %s app." % ("messages" if app == "sms" else "WhatsApp")
    time.sleep(2)
    if app == "sms" and not SMS_AUTO_SEND:
        return "I wrote the text message to %s in your Messages app. Tap send when you are ready." % shown
    if not tap_ui(pattern, wait=8, fields=("desc", "text", "id")):
        return "I wrote the message to %s but could not press send. Tap the send button on the phone." % shown
    return "Sent %s to %s." % (label, shown)


def do_battery():
    ok, out = sh("dumpsys battery")
    m = re.search(r"level:\s*(\d+)", out)
    if not m:
        return "I could not read the phone battery."
    charging = re.search(r"(?:AC|USB|Wireless) powered:\s*true", out)
    return "Your phone battery is at %s percent%s." % (m.group(1), ", and it is charging" if charging else "")


MUSIC_KEYS = {"play": "KEYCODE_MEDIA_PLAY", "pause": "KEYCODE_MEDIA_PAUSE", "next": "KEYCODE_MEDIA_NEXT",
              "previous": "KEYCODE_MEDIA_PREVIOUS"}
MUSIC_SAY = {"play": "Playing the music on your phone.", "pause": "Paused the music on your phone.",
             "next": "Next song on your phone.", "previous": "Previous song on your phone."}


def do_music(what):
    sh("input keyevent " + MUSIC_KEYS[what])
    return MUSIC_SAY[what]


def do_volume(what):
    if what == "mute":
        sh("input keyevent KEYCODE_VOLUME_MUTE")
        return "Muted your phone."
    key = "KEYCODE_VOLUME_UP" if what == "up" else "KEYCODE_VOLUME_DOWN"
    sh("input keyevent %s %s %s" % (key, key, key))
    return "Phone volume %s." % what


def do_dnd(on):
    ok, out = sh("cmd notification set_dnd %s" % ("on" if on else "off"))
    if not ok or failed(out):
        return "Your phone did not allow me to change silent mode."
    return "Silent mode is %s on your phone." % ("on" if on else "off")


def do_torch(on):
    wake()
    sh("cmd statusbar expand-settings")
    time.sleep(1.3)
    n = wait_ui(r"flashlight|torch", wait=4)
    if not n:
        sh("cmd statusbar collapse")
        return "I could not find the flashlight button. Unlock the phone and try again."
    state = (n["desc"] + " " + n["text"]).lower()
    is_on = bool(re.search(r"\bon\b", state)) and not re.search(r"\boff\b", state)
    if is_on != on:
        tap_node(n)
        time.sleep(0.6)
    sh("cmd statusbar collapse")
    return "Flashlight is %s on your phone." % ("on" if on else "off")


def do_alarm(h, m):
    wake()
    ok, out = sh("am start -a android.intent.action.SET_ALARM --ei android.intent.extra.alarm.HOUR %d "
                 "--ei android.intent.extra.alarm.MINUTES %d --ez android.intent.extra.alarm.SKIP_UI true" % (h, m))
    if not ok or failed(out):
        return "Your phone clock app did not accept the alarm."
    ap = "AM" if h < 12 else "PM"
    return "Alarm set on your phone for %d:%02d %s." % ((h % 12) or 12, m, ap)


def do_timer(seconds):
    wake()
    ok, out = sh("am start -a android.intent.action.SET_TIMER --ei android.intent.extra.alarm.LENGTH %d "
                 "--ez android.intent.extra.alarm.SKIP_UI true" % seconds)
    if not ok or failed(out):
        return "Your phone clock app did not accept the timer."
    mins, secs = divmod(seconds, 60)
    return "Timer set on your phone for %s." % (("%d minute%s" % (mins, "" if mins == 1 else "s")) if mins and not secs
                                               else "%d seconds" % seconds)


def do_url(kind, value):
    wake()
    if kind == "youtube":
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(value)
        say = "Searching YouTube on your phone for %s." % value
    elif kind == "google":
        url = "https://www.google.com/search?q=" + urllib.parse.quote(value)
        say = "Searching on your phone for %s." % value
    else:
        url = value if value.startswith("http") else "https://" + value
        say = "Opening %s on your phone." % value
    ok, out = sh("am start -a android.intent.action.VIEW -d " + q(url))
    if not ok or failed(out):
        return "I could not open that on your phone."
    return say


_MIRROR = {"proc": None}


def find_scrcpy():
    p = shutil.which("scrcpy")
    if p:
        return p
    for folder in (os.path.join(HERE, "scrcpy"), HERE):
        f = os.path.join(folder, "scrcpy.exe")
        if os.path.isfile(f):
            return f
    return None


def do_mirror(on):
    p = _MIRROR["proc"]
    if not on:
        if p and p.poll() is None:
            p.terminate()
            _MIRROR["proc"] = None
            return "Stopped showing your phone screen."
        return "Your phone screen was not being shown."
    if p and p.poll() is None:
        return "Your phone screen is already showing."
    exe = find_scrcpy()
    if not exe:
        return ("To show the phone screen I need the free scrcpy tool. Download scrcpy-win64 from "
                "github.com/Genymobile/scrcpy/releases, unzip it, and put the folder named scrcpy inside the Roe folder.")
    env = dict(os.environ)
    adb_path = find_adb()
    if adb_path:
        env["ADB"] = adb_path
    _MIRROR["proc"] = subprocess.Popen([exe, "--stay-awake"], env=env, cwd=os.path.dirname(exe),
                                       creationflags=_flags())
    return "Showing your phone screen on the laptop. You can use your mouse on it."


def do_type(text):
    safe = re.sub(r"[^A-Za-z0-9 .,@_:/+=-]", "", text).replace(" ", "%s")
    if not safe:
        return "I can only type English letters and numbers on the phone."
    sh("input text " + q(safe))
    return "Typed it on your phone where the cursor is."


def laptop_clipboard():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard"], capture_output=True,
                           text=True, timeout=10, creationflags=_flags(), encoding="utf-8", errors="replace")
        return (r.stdout or "").strip()
    except Exception:
        return ""


def do_clip():
    text = laptop_clipboard()
    if not text:
        return "Your laptop clipboard is empty. Copy some text first."
    tmp = os.path.join(HERE, "_copied_text.txt")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    name = "Copied_text_%s.txt" % time.strftime("%H%M%S")
    ok, out = adb("push", tmp, PHONE_FOLDER + "/" + name, timeout=60)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if not ok:
        return "Sending the text failed: %s" % out[-120:]
    return "Your copied text is on the phone: Downloads, %s. (Android does not let me paste straight into its clipboard.)" % name


# ------------------------------------------------------------------
# Running one step or a chain
# ------------------------------------------------------------------
def run_step(c, ctx, for_share=False):
    a, g = c["action"], c["arg"]
    if a == "phone_call":
        return do_call(g)
    if a == "phone_hangup":
        return do_hangup()
    if a == "phone_answer":
        return do_answer()
    if a == "phone_camera":
        return do_camera()
    if a == "phone_app":
        return do_app(g) if g and g != "that" else "Which app should I open on your phone?"
    if a == "phone_send":
        return do_send(g, ctx)
    if a == "phone_msg":
        return do_msg(g["name"], g["text"], g["app"])
    if a == "phone_share":
        return do_share(ctx, g["name"], g["app"])
    if a == "phone_file_share":
        return do_file_share(ctx, g["file"], g["name"], g["app"])
    if a == "phone_screenshot":
        return do_screenshot(ctx, for_share)
    if a == "phone_photo":
        return do_photo(ctx, for_share)
    if a == "phone_battery":
        return do_battery()
    if a == "phone_music":
        return do_music(g)
    if a == "phone_volume":
        return do_volume(g)
    if a == "phone_dnd":
        return do_dnd(g)
    if a == "phone_torch":
        return do_torch(g)
    if a == "phone_alarm":
        return do_alarm(*g)
    if a == "phone_timer":
        return do_timer(g)
    if a == "phone_url":
        return do_url(*g)
    if a == "phone_mirror":
        return do_mirror(g)
    if a == "phone_type":
        return do_type(g)
    if a == "phone_clip":
        return do_clip()
    return "I do not know that phone action."


def run(c):
    a = c["action"]
    try:
        if a not in ACTIONS:
            return None
        if not (a == "phone_mirror" and not c["arg"]):
            bad = phone_problem()
            if bad:
                return bad
        if a != "phone_chain":
            return run_step(c, {})
        ctx, said = {}, []
        steps = c["arg"]
        for i, step in enumerate(steps):
            later_share = any(s["action"] == "phone_share" for s in steps[i + 1:])
            msg = run_step(step, ctx, for_share=later_share)
            said.append(msg)
            if re.match(r"^(I could not|I cannot|I do not|Sorry|Tell me|Your phone did not|Sending failed|"
                        r"Which app|Your laptop clipboard)", msg):
                break
        return " ".join(said)
    except Exception as e:
        return "Sorry, the phone link did not work (%s)." % e


# ------------------------------------------------------------------
# Understanding the words
# ------------------------------------------------------------------
_HANGUP = re.compile(r"\b(?:hang ?up|end (?:the |this )?call|cut (?:the |this )?call|disconnect (?:the |this )?call"
                     r"|reject (?:the |this )?(?:phone )?call|decline (?:the |this )?(?:phone )?call)\b"
                     r"|कॉल (?:काट|बंद)|call (?:cut|band|kaat)")
_ANSWER = re.compile(r"\b(?:answer|pick up|accept|receive)\s+(?:the |this |my |that )?(?:phone )?call\b|\bcall (?:utha|uthao)\b")
_SEND = re.compile(r"\b(?:send|share|transfer|bhej\w*|forward)\b|भेज")
_FROM_PHONE = re.compile(r"\bfrom (?:my |the )?(?:phone|mobile)\b|फोन से|मोबाइल से|phone se\b|mobile se\b")
_OPEN_START = re.compile(r"^(?:(?:please|can you|could you|would you|will you|hey)\s+)*(?:open|launch|start)\b")
_OPEN_END = re.compile(r"(?:kholo|khol do|khol|chalu karo|chalao)(?:\s+(?:phone|mobile)\s+(?:par|pe|mein|me))?$|खोलो")
_CALL_EN = re.compile(r"^(?:(?:please|can you|could you|would you|will you|hey)\s+)*"
                      r"(?:(?:make|place)\s+(?:a\s+)?(?:phone\s+)?call\s+to\s+|call\s+|dial\s+|ring\s+|phone\s+)(.+)$")
_CALL_HI = re.compile(r"^(.+?)\s+(?:ko\s+)?(?:call|phone|fon)\s+(?:karo|kar\s?do|kar|laga\s?do|lagao|lagana|laga)$")
_CALL_DEV = re.compile(r"^(.+?)\s+को\s+(?:कॉल|फोन|फ़ोन)\s+(?:करो|कर दो|लगाओ|लगा दो)$")
_TAIL = re.compile(r"\s+(?:on|from|using|with)\s+(?:my\s+|the\s+)?(?:phone|mobile|cell)$|\s+(?:please|now|right now|karo|kar do)$"
                   r"|\s+(?:फोन|मोबाइल)\s+(?:पर|से)$")
_PRE = r"^(?:(?:please|can you|could you|would you|will you|hey)\s+)*"
_MSG_A = re.compile(_PRE + r"send\s+(?:a\s+|an\s+)?(whatsapp|sms|text|message)(?:\s+message)?\s+to\s+(\S+)"
                    r"(?:\s+(?:saying|that))?\s+(.+)$", re.I)
_MSG_B = re.compile(_PRE + r"(whatsapp|sms|text|message|msg|tell)\s+(\S+?)(?:\s+(?:saying|that))?\s+(.+)$", re.I)
_APP_TAIL = re.compile(r"^(.+?)\s+(?:on|via|through|using|by)\s+(whatsapp|sms|text message|text)$", re.I)
_IMG = (r"(?:it|that|this|the\s+(?:screenshot|photo|picture|pic|image|selfie)|my\s+(?:last\s+|latest\s+)?"
        r"(?:screenshot|photo|picture|pic|image)|(?:the\s+|my\s+)?(?:last|latest)\s+(?:screenshot|photo|picture|pic|image))")
_SHARE = re.compile(_PRE + r"(?:send|share|forward)\s+" + _IMG + r"\s+(?:to\s+)?(.+?)"
                    r"(?:\s+(?:on|via|through|using)\s+(whatsapp|telegram))?$", re.I)
_SHARE_HI = re.compile(r"^(?:(?:isko|ise|isse|usko|use|ye|yeh)\s+)?(.+?)\s+ko\s+(?:(whatsapp|telegram)\s+(?:par|pe|mein|me)\s+)?"
                       r"(?:bhej\w*|send)(?:\s+(?:do|dena|karo|kar do))?$", re.I)
_FILE_SHARE = re.compile(_PRE + r"(?:send|share|forward)\s+(?:my\s+|the\s+|a\s+)?(.+?)\s+to\s+(?:my\s+)?(.+?)\s+"
                         r"(?:on|via|through|using)\s+(whatsapp|telegram)$", re.I)
_SEP = re.compile(r"(\s+(?:and then|and|then|after that|phir|fir|aur)\s+|\s+(?:फिर|और)\s+)", re.I)


def _nice(app):
    return {"whatsapp": "WhatsApp", "youtube": "YouTube", "linkedin": "LinkedIn", "gmail": "Gmail"}.get(app, app.title())


def _contact_name(raw):
    n = raw.strip()
    for _ in range(3):
        n = _TAIL.sub("", n).strip()
    n = re.sub(r"^(?:my|mera|meri|mere)\s+", "", n)
    n = re.sub(r"^(?:to\s+)", "", n)
    for dev, rom in DEVA_NAMES.items():
        n = n.replace(dev, rom)
    return n.strip()


def _app_word(a):
    a = (a or "").lower()
    return "sms" if a in ("sms", "text", "text message") else ("whatsapp" if a == "whatsapp" else DEFAULT_MESSAGE_APP)


def _to_24h(h, mi, ap):
    if mi > 59 or h > 24:
        return None
    ap = (ap or "").replace(" ", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h % 24, mi


def parse_one(raw, force=False):
    """One sentence -> one phone step, or None."""
    raw = fix_sms(raw.strip().strip(".!?।, "))
    t = re.sub(r"\s+", " ", re.sub(r"[.,!?।]+", " ", raw.lower())).strip()
    if not t:
        return None
    has_phone = force or bool(PHONE_RX.search(t))

    if _HANGUP.search(t):
        return _cmd("phone_hangup")
    if _ANSWER.search(t):
        return _cmd("phone_answer")

    # --- messages
    m = _MSG_A.match(raw)
    kind = None
    if m:
        kind, name, text = m.group(1).lower(), m.group(2), m.group(3)
    else:
        m = _MSG_B.match(raw)
        if m:
            kind, name, text = m.group(1).lower(), m.group(2), m.group(3)
    if m and name.lower() not in NAME_STOP and not (_OPEN_START.match(t) and has_phone):
        app = None
        tail = _APP_TAIL.match(text)
        if tail:
            text, app = tail.group(1), tail.group(2)
        if kind == "tell" and not app and not force:
            kind = None
        if kind:
            if kind in ("whatsapp", "sms") and not app:
                app = kind
            return _cmd("phone_msg", {"name": _contact_name(name), "text": text.strip(),
                                      "app": _app_word(app)})

    # --- send "it" (the screenshot / photo just made) to a contact
    m = _SHARE.match(raw)
    if m and not PHONE_RX.search(m.group(1).lower()):
        return _cmd("phone_share", {"name": _contact_name(m.group(1)), "app": (m.group(2) or "whatsapp").lower()})

    m = _SHARE_HI.match(raw)
    if m and force and not PHONE_RX.search(m.group(1).lower()):
        return _cmd("phone_share", {"name": _contact_name(m.group(1)), "app": (m.group(2) or "whatsapp").lower()})

    # --- copied text / typing
    if has_phone and re.search(r"\b(?:copied|clipboard)\b|\bcopy (?:this|that|it)\b", t) and \
            re.search(r"\b(?:send|copy|share|transfer)\b", t):
        return _cmd("phone_clip")
    m = re.match(r"^(?:type|write)\s+(.+?)\s+(?:on|in|into)\s+(?:my\s+)?(?:phone|mobile)$", raw, re.I)
    if m:
        return _cmd("phone_type", m.group(1))

    # --- a laptop file to a contact (through the phone)
    m = _FILE_SHARE.match(raw)
    if m and not PHONE_RX.search(m.group(2).lower()):
        return _cmd("phone_file_share", {"file": m.group(1), "name": _contact_name(m.group(2)),
                                         "app": m.group(3).lower()})
    # --- a laptop file to the phone
    if has_phone and _SEND.search(t) and not _FROM_PHONE.search(t):
        return _cmd("phone_send", " ".join(file_words(t)))

    # --- screenshot / photo / camera
    if has_phone and re.search(r"\bscreenshot\b|screen shot|स्क्रीनशॉट", t):
        return _cmd("phone_screenshot")
    if has_phone and re.search(r"\b(?:take|click|capture|shoot|snap|khicho|kheencho|le)\b", t) and \
            re.search(r"\b(?:photo|picture|pic|selfie|image)\b", t):
        return _cmd("phone_photo")
    if has_phone and "camera" in t.replace("कैमरा", "camera"):
        return _cmd("phone_camera")

    # --- battery, music, sound
    if has_phone and re.search(r"\b(?:battery|charge|charging)\b", t):
        return _cmd("phone_battery")
    if has_phone and re.search(r"\b(?:song|songs|music|track|gaana|gaane|gana)\b", t):
        for words, what in ((r"pause|stop|ruk", "pause"), (r"next|skip|agla", "next"),
                            (r"previous|last|back|pichla", "previous"), (r"play|resume|start|chalu|chalao|bajao", "play")):
            if re.search(r"\b(?:%s)\b" % words, t):
                return _cmd("phone_music", what)
    if has_phone and re.search(r"\b(?:volume|awaaz|sound)\b|आवाज़", t):
        for words, what in ((r"mute|silent", "mute"), (r"up|increase|louder|raise|badha\w*|high|more", "up"),
                            (r"down|decrease|lower|reduce|kam\w*|less|low", "down")):
            if re.search(r"\b(?:%s)\b" % words, t):
                return _cmd("phone_volume", what)
    if has_phone and re.search(r"\bmute\b", t) and not re.search(r"\b(?:song|music)\b", t):
        return _cmd("phone_volume", "mute")
    if has_phone and re.search(r"\b(?:silent|do not disturb|don t disturb|dnd)\b", t):
        off = re.search(r"\b(?:off|disable|normal|general|exit|remove|band|hatao|stop)\b", t)
        return _cmd("phone_dnd", not off)
    if has_phone and re.search(r"\b(?:flashlight|flash light|torch|tourch)\b", t):
        off = re.search(r"\b(?:off|disable|band|stop|close)\b", t)
        return _cmd("phone_torch", not off)

    # --- alarm / timer
    if has_phone and re.search(r"\btimers?\b", t):
        total = 0
        for n, u in re.findall(r"(\d+)\s*(second|sec|minute|min|hour|hr)", t):
            total += int(n) * {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600}[u]
        if "half an hour" in t:
            total = 1800
        if total:
            return _cmd("phone_timer", min(total, 86400))
    if has_phone and re.search(r"\balarms?\b", t):
        m = re.search(r"(\d{1,2})(?:[: ](\d{2}))?\s*(am|pm|a m|p m)?", re.sub(r"\balarms?\b", " ", t))
        if m:
            hm = _to_24h(int(m.group(1)), int(m.group(2) or 0), m.group(3))
            if hm:
                return _cmd("phone_alarm", hm)

    # --- show the phone screen on the laptop
    if has_phone and re.search(r"\b(?:mirror\w*|cast\w*)\b|(?:show|display)\b.*\bscreen\b", t):
        off = re.search(r"\b(?:stop|close|end|band|off|hide)\b", t)
        return _cmd("phone_mirror", not off)
    if re.search(r"\bstop (?:mirroring|casting)\b|\bmirroring band\b", t):
        return _cmd("phone_mirror", False)

    # --- websites and searches on the phone
    if has_phone:
        m = re.search(r"(?:search|play|find|watch|dekho|chalao)\s+(.+?)\s+(?:on|in)\s+youtube", t)
        if m:
            return _cmd("phone_url", ("youtube", m.group(1)))
        m = re.search(r"(\S+\.(?:com|in|org|net|co|io|edu|ai|gov))\b", raw.lower())
        if m and _OPEN_START.match(t):
            return _cmd("phone_url", ("site", m.group(1)))
        m = re.match(_PRE.replace("^", "^") + r"(?:search|google|look up)\s+(?:for\s+)?(.+?)"
                     r"(?:\s+(?:on|in|from)\s+(?:my\s+|the\s+)?(?:phone|mobile))?$", t)
        if m and not re.search(r"\byoutube\b", m.group(1)):
            return _cmd("phone_url", ("google", m.group(1)))

    # --- open an app on the phone
    if has_phone and (_OPEN_START.match(t) or _OPEN_END.search(t)) and len(t.split()) <= 8:
        t2 = t.replace("कैमरा", "camera").replace("व्हाट्सएप", "whatsapp").replace("यूट्यूब", "youtube")
        for app in list(PHONE_APPS) + ["settings", "dialer"]:
            if re.search(r"\b%s\b" % re.escape(app), t2):
                return _cmd("phone_app", app)
        return _cmd("phone_app", "that")

    # --- call a contact
    for rx in (_CALL_EN, _CALL_HI, _CALL_DEV):
        m = rx.match(t)
        if m:
            name = _contact_name(m.group(1))
            if name and len(name.split()) <= 4:
                return _cmd("phone_call", name, "Call %s?" % name if CONFIRM_CALLS else "", CONFIRM_CALLS)
    return None


def parse_chain(raw):
    """'take a screenshot and send it to mom on whatsapp' -> one command with up to 4 steps, or None."""
    parts = _SEP.split(raw)
    if len(parts) < 3:
        return None
    pieces, seps = parts[0::2], parts[1::2]
    force = any(PHONE_ONLY.search(re.sub(r"[.,!?।]+", " ", p.lower())) for p in pieces)
    steps, i = [], 0
    while i < len(pieces):
        c = parse_one(pieces[i], force=force)
        if c is None:
            if steps and steps[-1]["action"] == "phone_msg":         # the "and" was part of the message
                steps[-1]["arg"]["text"] += seps[i - 1] + pieces[i]
                i += 1
                continue
            return None
        steps.append(c)
        if c["action"] == "phone_msg":                               # the message takes all the words left
            rest = "".join(seps[j] + pieces[j + 1] for j in range(i, len(pieces) - 1))
            c["arg"]["text"] += rest
            break
        i += 1
    if len(steps) < 2 or len(steps) > 4:
        return None
    return _cmd("phone_chain", steps)


def parse(text, hindi=False):
    chain = parse_chain(text)
    if chain:
        return chain
    return parse_one(text)


def to_command(action, args, reply):
    """Used when the Groq AI picks one of the phone actions."""
    args = args or {}
    if action == "phone_call":
        name = _contact_name(str(args.get("name", "")))
        return _cmd(action, name, "Call %s?" % name if CONFIRM_CALLS else "", CONFIRM_CALLS) if name else None
    if action == "phone_send":
        return _cmd(action, str(args.get("file", "")))
    if action == "phone_app":
        return _cmd(action, str(args.get("app", "")).lower().strip())
    if action == "phone_msg":
        name, text = _contact_name(str(args.get("name", ""))), str(args.get("text", "")).strip()
        return _cmd(action, {"name": name, "text": text, "app": _app_word(args.get("app"))}) if name and text else None
    if action in ("phone_hangup", "phone_camera"):
        return _cmd(action)
    return None


# ------------------------------------------------------------------
# Test:  py -3.11 phone_link.py
# ------------------------------------------------------------------
if __name__ == "__main__":
    print("Roe - phone link check\n")
    exe = find_adb()
    print("1. ADB tool:", exe or "NOT FOUND (put the platform-tools folder inside the Roe folder)")
    if exe:
        bad = phone_problem()
        print("2. Phone:", "READY" if bad is None else bad)
        if bad is None:
            book = read_contacts()
            print("3. Contacts read from phone:", len(book), "(0 means contacts could not be read)")
            ok, out = adb("shell", "getprop", "ro.product.model")
            print("4. Phone model:", out)
            print("5. Phone battery:", do_battery())
    print("6. Screen mirror tool (scrcpy):", find_scrcpy() or "not found (only needed for 'show my phone screen')")
    print("\nWhat Roe understands (no phone needed):")
    for s in ["call mom", "mummy ko call karo", "send my resume to my phone", "take a screenshot and send it to mom on whatsapp",
              "message mom I will be late", "open camera on phone", "phone battery", "open whatsapp on my phone",
              "open spotify"]:
        r = parse(s)
        print("  %-52s -> %s" % (s, [x["action"] for x in r["arg"]] if r and r["action"] == "phone_chain"
                                 else (r["action"] if r else None)))

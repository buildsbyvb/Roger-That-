"""
Roe - Step 6: A much smarter assistant (more things it can do).

parse(text)    -> turns words into a command (a small dictionary), or None
execute(cmd)   -> does the command and returns a sentence about what it did

NEW in this version:
  - Wi-Fi and Bluetooth on / off
  - open ANY app in the Start menu ("open spotify", "open word")
  - open ANY file or folder by name ("open file resume", "open file DoIt")
  - play a song ("play despacito" -> YouTube, "play despacito on spotify")
  - pause / play / next song / previous song (works with Spotify and others)
  - read aloud (selected text, or the whole page)  + "stop reading"
  - notification bar, quick settings, show desktop, lock laptop, time, date

SAFETY: only the fixed list of actions below can ever run.
Nothing the speech or text says is ever run as code.
Program files (.exe, .bat, .ps1 ...) are never opened by file name.
Risky actions (delete, shutdown, restart) are marked risky=True,
and the voice program asks "Are you sure?" before calling execute().
"""
import difflib
import os
import re
import subprocess
import time
import urllib.parse
import webbrowser

# A few Hindi (Devanagari) words turned into English letters, so Hindi
# speech can also match.
DEVANAGARI = {
    "खोलो": "kholo", "खोल": "khol", "डाउनलोड्स": "downloads", "डाउनलोड": "downloads",
    "फोल्डर": "folder", "गूगल": "google", "सर्च": "search", "करो": "karo",
    "बंद": "band", "स्क्रॉल": "scroll", "ऊपर": "upar", "नीचे": "neeche",
    "कैमरा": "camera", "नोटपैड": "notepad", "कैलकुलेटर": "calculator",
    "स्क्रीनशॉट": "screenshot", "वॉल्यूम": "volume", "डॉक्युमेंट्स": "documents",
    "डेस्कटॉप": "desktop", "ओपन": "open", "क्लिक": "click", "टाइप": "type",
    "ब्लूटूथ": "bluetooth", "वाईफाई": "wifi", "वाई फाई": "wifi", "वाईफ़ाई": "wifi",
    "गाना": "gaana", "गाने": "gaana", "चलाओ": "chalao", "बजाओ": "bajao",
    "पढ़ो": "padho", "पढो": "padho", "चालू": "chalu", "स्पॉटिफाई": "spotify",
    "नोटिफिकेशन": "notification", "अगला": "agla", "पिछला": "pichla",
}
try:
    import hindi_fix
    hindi_fix.merge_into(DEVANAGARI)          # many more Hindi spellings (see hindi_fix.py)
except Exception:
    pass

FOLDERS = {
    "downloads": "shell:Downloads", "download": "shell:Downloads",
    "documents": "shell:Personal", "document": "shell:Personal",
    "desktop": "shell:Desktop",
    "pictures": "shell:My Pictures", "photos": "shell:My Pictures",
    "music": "shell:My Music", "videos": "shell:My Video",
}
APPS = ["camera", "notepad", "calculator", "calc", "paint", "chrome", "edge", "settings"]

HOTKEYS = {
    "close_window": (("alt", "f4"), "Closing the window."),
    "close_tab": (("ctrl", "w"), "Closing the tab."),
    "new_tab": (("ctrl", "t"), "Opening a new tab."),
    "next_tab": (("ctrl", "tab"), "Next tab."),
    "prev_tab": (("ctrl", "shift", "tab"), "Previous tab."),
    "back": (("alt", "left"), "Going back."),
    "forward": (("alt", "right"), "Going forward."),
    "refresh": (("f5",), "Refreshing."),
    "show_desktop": (("win", "d"), "Showing the desktop."),
    "switch_window": (("alt", "tab"), "Switching window."),
    "screenshot": (("win", "prtsc"), "Screenshot saved in Pictures, Screenshots."),
    "select_all": (("ctrl", "a"), "Selecting all."),
    "copy": (("ctrl", "c"), "Copied."),
    "paste": (("ctrl", "v"), "Pasted."),
    "undo": (("ctrl", "z"), "Undone."),
    "save": (("ctrl", "s"), "Saving."),
    "enter": (("enter",), "Pressed enter."),
    "top": (("ctrl", "home"), "Scrolling to the top."),
    "bottom": (("ctrl", "end"), "Scrolling to the bottom."),
    "notifications": (("win", "n"), "Showing the notification bar."),
    "quick_settings": (("win", "a"), "Showing quick settings."),
}

# Media keys (they control Spotify, YouTube in the browser, and most players)
MEDIA = {
    "pause": ("playpause", "Pausing."),
    "resume": ("playpause", "Playing."),
    "next_song": ("nexttrack", "Next song."),
    "prev_song": ("prevtrack", "Previous song."),
}

# These send keys to the active window, so they must NOT run while the black
# command window is the active window (it would close the assistant itself).
NEEDS_OTHER_WINDOW = {"type", "delete", "read"} | {
    k for k in HOTKEYS
    if k not in ("screenshot", "show_desktop", "switch_window", "notifications", "quick_settings")}
OWN_WINDOWS = ("voice_assistant", "wake_listen", "hand_mouse", "command prompt",
               "cmd.exe", "powershell", "windows terminal")

# Program files are NEVER opened by file name (safety).
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".com", ".msi", ".ps1", ".vbs", ".vbe", ".js", ".jse",
               ".wsf", ".scr", ".reg", ".lnk", ".jar", ".hta", ".dll", ".cpl", ".msc"}

# Words ignored when we work out WHAT to open ("open the file resume" -> "resume")
FILLER = {"open", "kholo", "khol", "launch", "start", "the", "my", "a", "an", "please", "file",
          "files", "folder", "app", "application", "named", "called", "karo", "kar", "do", "ko",
          "ka", "ki", "for", "me", "show", "go", "to", "on", "this", "pc", "document", "pdf",
          "can", "you", "i", "want", "s",
          # polite / chatty words ("could you please open spotify")
          "could", "would", "will", "shall", "kindly", "pls", "plz", "just", "now", "hey", "hi",
          "hello", "need", "like", "mind", "dijiye", "kijiye", "kholiye", "zara", "ek", "yaar",
          "bhai", "something", "up", "it", "us", "there", "again", "once", "also", "so", "then",
          "yes", "ok", "okay", "app", "window"}


# ------------------------------------------------------------------
# Minimize / maximize / restore a window BY NAME ("minimize chrome", "maximize spotify")
# ------------------------------------------------------------------
WINDOW_VERBS = {
    "minimize": "minimize", "minimise": "minimize", "minimized": "minimize", "minimised": "minimize",
    "maximize": "maximize", "maximise": "maximize", "maximized": "maximize", "maximised": "maximize",
    "restore": "restore", "chhota": "minimize", "chota": "minimize", "bada": "maximize",
}
WINDOW_FILLER = {"the", "my", "a", "an", "window", "windows", "app", "application", "please", "can",
                 "could", "would", "will", "you", "kindly", "ko", "karo", "kar", "do", "dijiye",
                 "kijiye", "this", "that", "it", "current", "now", "just", "for", "me", "hey", "screen",
                 "full", "size", "of", "to", "and", "ek", "zara", "again", "pls", "plz", "i", "want",
                 "need", "s", "on", "in"}
# what people say -> part of the program (exe) name or window title
WINDOW_ALIASES = {
    "word": "winword", "ms word": "winword", "microsoft word": "winword",
    "powerpoint": "powerpnt", "power point": "powerpnt", "ppt": "powerpnt",
    "vs code": "code", "vscode": "code", "visual studio code": "code",
    "file explorer": "explorer", "explorer": "explorer", "files": "explorer", "my files": "explorer",
    "edge": "msedge", "microsoft edge": "msedge", "browser": "chrome", "google chrome": "chrome",
    "terminal": "windowsterminal", "command prompt": "cmd", "task manager": "taskmgr",
    "whatsapp web": "whatsapp", "ms excel": "excel", "microsoft excel": "excel",
}
SKIP_TITLES = ("program manager", "windows input experience", "microsoft text input application",
               "default ime", "msctfime ui")
OWN_EXES = {"python", "pythonw", "py", "cmd", "powershell", "pwsh", "windowsterminal", "conhost",
            "openconsole"}


def parse_window(W):
    """W = list of words. Returns (do, name) like ("minimize", "chrome"), or None."""
    verb = next((WINDOW_VERBS[w] for w in W if w in WINDOW_VERBS), None)
    if verb is None:
        return None
    name = " ".join(w for w in W if w not in WINDOW_VERBS and w not in WINDOW_FILLER)
    return (verb, name)


def match_windows(name, wins):
    """wins = [(hwnd, title, exe)] with the top-most window first. Returns the matching windows
    (best kind of match only). Pure function, so it can be tested without Windows."""
    key = normalize(name).strip()
    key = WINDOW_ALIASES.get(key, key)
    if not key:
        return []
    tiers = ([], [], [])
    for w in wins:
        _, title, exe = w
        tl = title.lower()
        if exe and (key == exe or (len(key) >= 3 and key in exe)):
            tiers[0].append(w)
        elif len(key) >= 3 and key in tl:
            tiers[1].append(w)
        elif exe and len(exe) >= 4 and exe in key.split():
            tiers[1].append(w)
        elif exe and len(key) >= 4 and difflib.SequenceMatcher(None, key, exe).ratio() >= 0.8:
            tiers[2].append(w)
    for tier in tiers:
        if tier:
            return tier
    return []


def _is_own(title, exe):
    tl = title.lower()
    return exe in OWN_EXES or any(s in tl for s in OWN_WINDOWS)


def _windows():
    """[(hwnd, title, exe)] of the visible windows, top-most first (Windows only)."""
    import ctypes
    from ctypes import wintypes
    u, k, dwm = ctypes.windll.user32, ctypes.windll.kernel32, ctypes.windll.dwmapi
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                             ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    out = []

    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n == 0:
            return True
        cloaked = ctypes.c_int(0)                       # hidden Store-app windows count as visible
        dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(cloaked), 4)
        if cloaked.value:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if title.lower() in SKIP_TITLES:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = k.OpenProcess(0x1000, False, pid.value)     # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            size = wintypes.DWORD(520)
            path = ctypes.create_unicode_buffer(520)
            if k.QueryFullProcessImageNameW(h, 0, path, ctypes.byref(size)):
                exe = os.path.splitext(os.path.basename(path.value))[0].lower()
            k.CloseHandle(h)
        out.append((hwnd, title, exe))
        return True

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb)
    u.EnumWindows(proc, 0)
    return out


def window_control(do, name=""):
    """Minimize / maximize / restore a window by name. With no name it uses the window you were
    using (the top-most one that is not this program's own black window)."""
    import ctypes
    u = ctypes.windll.user32
    code = {"minimize": 6, "maximize": 3, "restore": 9}[do]
    past = {"minimize": "Minimized", "maximize": "Maximized", "restore": "Restored"}[do]
    wins = _windows()
    name = (name or "").strip()
    if name:
        hits = match_windows(name, wins)
        if not hits:
            return "I could not find an open window called %s." % name
        label = name
    else:
        hits = [w for w in wins if not _is_own(w[1], w[2])][:1]
        if not hits:
            return "I could not find a window to %s." % do
        label = "the window"
    if do != "minimize":
        hits = hits[:1]                                  # only the top-most one
    for hwnd, _, _ in hits:
        u.ShowWindow(hwnd, code)
        if do != "minimize":
            try:
                u.SetForegroundWindow(hwnd)
            except Exception:
                pass
    return "%s %s." % (past, label)


# ------------------------------------------------------------------
# Understanding
# ------------------------------------------------------------------
def normalize(text):
    t = text
    for k in sorted(DEVANAGARI, key=len, reverse=True):
        t = t.replace(k, DEVANAGARI[k])
    t = t.lower()
    t = re.sub(r"[^\w\s']", " ", t)
    t = re.sub(r"\bwi\s*fi\b", "wifi", t)
    t = re.sub(r"\bblue\s*tooth\b", "bluetooth", t)
    return re.sub(r"\s+", " ", t).strip()


def _clean_query(q):
    q = re.sub(r"\b(on|in) google\b", "", q)
    q = re.sub(r"\b(please|for me)\b", "", q)
    return re.sub(r"\s+", " ", q).strip()


def _clean_song(q):
    q = re.sub(r"\b(on|in|from|using|with)\s+(spotify|youtube|you tube)\b", " ", q)
    q = re.sub(r"\b(spotify|youtube|you tube)\b", " ", q)
    q = re.sub(r"\b(the|song|songs|music|gaana|track|please|for me|me|a)\b", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def parse(text):
    """Returns {'action', 'arg', 'say', 'risky'} or None if not understood."""
    raw = text.strip()
    t = normalize(raw)
    if not t:
        return None
    W = t.split()

    def has(*words):
        return any(w in W for w in words)

    def phrase(*phs):
        return any(" %s " % p in " %s " % t for p in phs)

    def cmd(action, arg=None, say="", risky=False):
        return {"action": action, "arg": arg, "say": say, "risky": risky}

    # --- cancel shutdown
    if has("cancel", "abort") and (has("shutdown", "restart", "reboot") or phrase("shut down")):
        return cmd("cancel_shutdown", say="Cancelling the shutdown.")

    # --- type: "type hello", "write: this laptop obeys me", "likho hello"
    m = re.match(r"^(?:please\s+)?(?:type|write|likho|typing)\b[\s:,\-]*(.+)$",
                 raw, re.I | re.S)
    if m:
        typed = m.group(1).strip().rstrip(".").strip()
        if typed:
            return cmd("type", typed, "Typing: %s" % typed)

    # --- clicks
    m = re.fullmatch(r"(?:please )?(?:(double|right) )?click(?: here| this| it| on this)?", t)
    if m:
        kind = m.group(1)
        if kind == "double":
            return cmd("double_click", say="Double clicking.")
        if kind == "right":
            return cmd("right_click", say="Right clicking.")
        return cmd("click", say="Clicking.")
    if t.startswith("click"):
        return None

    # --- risky actions (the program asks "Are you sure?" first)
    if has("delete"):
        return cmd("delete", say="I will delete the selected file.", risky=True)
    if has("shutdown") or phrase("shut down", "switch off the laptop", "switch off the computer",
                                              "turn off the laptop", "turn off the computer"):
        return cmd("shutdown", say="I will shut down the laptop in 30 seconds.", risky=True)
    if has("restart", "reboot"):
        return cmd("restart", say="I will restart the laptop in 30 seconds.", risky=True)

    # --- single keys
    if t in ("enter", "press enter"):
        return cmd("enter", say=HOTKEYS["enter"][1])
    if t in ("select all",):
        return cmd("select_all", say=HOTKEYS["select_all"][1])
    if t in ("copy", "copy this", "copy that", "copy it"):
        return cmd("copy", say=HOTKEYS["copy"][1])
    if t in ("paste", "paste it", "paste here", "paste this"):
        return cmd("paste", say=HOTKEYS["paste"][1])
    if t in ("undo", "undo that"):
        return cmd("undo", say=HOTKEYS["undo"][1])
    if t in ("save", "save this", "save it", "save file"):
        return cmd("save", say=HOTKEYS["save"][1])

    # --- stop reading aloud
    if (has("stop", "band", "quiet", "silence", "shh") and has("reading", "read", "talking", "speaking", "padho")) \
            or phrase("be quiet", "stop talking", "stop speaking", "stop reading"):
        return cmd("stop_reading", say="Okay, stopped reading.")

    # --- read aloud
    if has("read", "padho", "padh") or phrase("read aloud", "read out"):
        mode = "all" if (has("page", "everything", "all", "whole", "poora", "article")) else "selection"
        return cmd("read", mode, "Reading aloud.")

    # --- music: pause / resume / next / previous / play a song
    if has("pause", "unpause") or phrase("stop the song", "stop song", "stop the music",
                                          "stop music", "stop playing") \
            or (has("song", "music", "gaana", "track") and has("stop", "band", "off")):
        return cmd("pause", say=MEDIA["pause"][1])
    if has("skip") or (has("next", "agla", "agle") and has("song", "track", "music", "gaana")):
        return cmd("next_song", say=MEDIA["next_song"][1])
    if has("previous", "last", "pichla", "pehle") and has("song", "track", "gaana"):
        return cmd("prev_song", say=MEDIA["prev_song"][1])
    if t in ("resume", "resume music", "resume song", "resume the song", "continue", "unpause",
             "continue music", "play", "play it", "play music", "play the song",
                                          "play song", "play the music", "play gaana"):
        return cmd("resume", say=MEDIA["resume"][1])
    m = re.match(r"^(?:please\s+)?(?:play|chalao|bajao)\s+(.+)$", t) or \
        re.match(r"^(.+?)\s+(?:chalao|chala do|chalado|bajao|baja do|laga do|lagao)$", t)
    if m:
        service = "spotify" if has("spotify") else "youtube"
        song = _clean_song(m.group(1))
        if not song:
            return cmd("resume", say=MEDIA["resume"][1])
        return cmd("play", (song, service), "Playing %s on %s." % (song, service.title()))

    # --- Wi-Fi and Bluetooth
    for name, label, page in (("bluetooth", "Bluetooth", "ms-settings:bluetooth"),
                              ("wifi", "Wi-Fi", "ms-settings:network-wifi")):
        if has(name):
            off = has("off", "disable", "band", "deactivate") or phrase("turn off", "switch off")
            on = has("on", "enable", "chalu", "activate") or phrase("turn on", "switch on")
            if off:
                return cmd("radio", (name, False), "Turning %s off." % label)
            if on:
                return cmd("radio", (name, True), "Turning %s on." % label)
            return cmd("open_settings", page, "Opening %s settings." % label)

    # --- notification bar, quick settings, lock, time, date
    if phrase("notification", "notifications", "notification bar", "notification panel",
              "action center", "notification center"):
        return cmd("notifications", say=HOTKEYS["notifications"][1])
    if phrase("quick settings"):
        return cmd("quick_settings", say=HOTKEYS["quick_settings"][1])
    if has("lock") and has("laptop", "screen", "computer", "pc", "it"):
        return cmd("lock", say="Locking the laptop.")
    if phrase("the time", "what time", "time is it", "current time", "time kya"):
        return cmd("time")
    if phrase("todays date", "today's date", "what date", "what day", "the date", "date kya"):
        return cmd("date")
    if has("desktop") and (has("show", "dikhao") or phrase("go to")) and not has("folder"):
        return cmd("show_desktop", say=HOTKEYS["show_desktop"][1])

    # --- search on Google (also "recipe" questions)
    q = None
    m = re.search(r"(.+?)\s+(?:search|serch)\s+(?:karo|kar do|kardo)", t)
    if m:
        q = " ".join(w for w in m.group(1).split()
                     if w not in ("google", "kholo", "khol", "aur", "par", "pe", "open", "and"))
    if q is None:
        m = re.search(r"\b(?:search|look up)\s+(?:for\s+|about\s+)?(.+)", t)
        if m:
            q = m.group(1)
    if q is None:
        m = re.search(r"\bgoogle\s+(.+)", t)
        if m:
            q = m.group(1)
    if q is None and has("recipe", "recipes"):
        q = re.sub(r"\b(give me|show me|tell me|please|can you|could you|i want|how to|the|"
                   r"batao|dikhao|bata do|ki)\b", " ", t)
    if q is not None:
        q = _clean_query(q)
        if q and q != "google":
            return cmd("search", q, "Searching Google for %s." % q)

    # --- scroll
    if has("scroll", "scrolling") or phrase("page down", "page up"):
        if phrase("to the top", "to top") or has("top"):
            return cmd("top", say=HOTKEYS["top"][1])
        if phrase("to the bottom", "to bottom") or has("bottom"):
            return cmd("bottom", say=HOTKEYS["bottom"][1])
        up = has("up", "upar") or phrase("page up")
        amount = 600
        if has("little", "bit", "thoda", "thora"):
            amount = 300
        elif has("lot", "much", "more", "zyada", "bahut"):
            amount = 1500
        return cmd("scroll", amount if up else -amount,
                   "Scrolling %s." % ("up" if up else "down"))

    # --- tabs, windows, screen, volume
    if has("tab"):
        if has("close", "band"):
            return cmd("close_tab", say=HOTKEYS["close_tab"][1])
        if phrase("new tab"):
            return cmd("new_tab", say=HOTKEYS["new_tab"][1])
        if has("next"):
            return cmd("next_tab", say=HOTKEYS["next_tab"][1])
        if has("previous", "last"):
            return cmd("prev_tab", say=HOTKEYS["prev_tab"][1])
    if phrase("show desktop", "minimize all", "minimise all", "minimize everything",
              "minimise everything", "show the desktop"):
        return cmd("show_desktop", say=HOTKEYS["show_desktop"][1])
    win = parse_window(W)
    if win:
        return cmd("window", win)
    if has("screenshot") or phrase("screen shot"):
        return cmd("screenshot", say=HOTKEYS["screenshot"][1])
    if phrase("switch window", "next window"):
        return cmd("switch_window", say=HOTKEYS["switch_window"][1])
    if has("volume", "louder", "quieter", "mute", "unmute"):
        if has("mute", "unmute"):
            return cmd("volume", "mute", "Toggling mute.")
        if has("up", "increase", "louder", "more", "badhao", "badha"):
            return cmd("volume", "up", "Volume up.")
        if has("down", "decrease", "lower", "quieter", "less", "kam", "ghatao"):
            return cmd("volume", "down", "Volume down.")
    if has("refresh", "reload"):
        return cmd("refresh", say=HOTKEYS["refresh"][1])
    if has("back", "peeche"):
        return cmd("back", say=HOTKEYS["back"][1])
    if has("forward"):
        return cmd("forward", say=HOTKEYS["forward"][1])
    if has("close", "exit") or phrase("band karo", "band kar do"):
        return cmd("close_window", say=HOTKEYS["close_window"][1])

    # --- open folders, apps, files, websites
    opening = has("open", "kholo", "khol", "launch", "start") or phrase("show me my", "go to")
    if opening:
        for word, target in FOLDERS.items():
            if word in W:
                return cmd("open_folder", target, "Opening your %s folder." % word)
        if phrase("my files", "file explorer", "files", "this pc"):
            return cmd("open_folder", "", "Opening File Explorer.")
        for app in APPS:
            if app in W:
                name = "calculator" if app == "calc" else app
                return cmd("open_app", name, "Opening %s." % name)
        if has("youtube"):
            return cmd("open_url", "https://www.youtube.com", "Opening YouTube.")
        if has("google"):
            return cmd("open_url", "https://www.google.com", "Opening Google.")
        # anything else: look for an app in the Start menu or a file/folder by name
        query = [w for w in W if w not in FILLER]
        if query:
            prefer = "file" if has("file", "document", "pdf", "folder") else "app"
            return cmd("open_named", (" ".join(query), prefer))
    return None


# ------------------------------------------------------------------
# Finding files and apps
# ------------------------------------------------------------------
_index = {"t": 0.0, "items": []}
_apps = {"items": None}


def _roots():
    home = os.path.expanduser("~")
    bases = [home]
    od = os.environ.get("OneDrive")
    if od:
        bases.append(od)
    roots = []
    for b in bases:
        for n in ("Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"):
            p = os.path.join(b, n)
            if os.path.isdir(p) and p not in roots:
                roots.append(p)
    return roots


def _file_index():
    """List of (path, is_folder). Cached for 2 minutes."""
    if _index["items"] and time.time() - _index["t"] < 120:
        return _index["items"]
    items, skip = [], {"node_modules", "__pycache__", "venv", "site-packages", ".git"}
    for root in _roots():
        depth0 = root.count(os.sep)
        for dp, dn, fn in os.walk(root):
            if dp.count(os.sep) - depth0 >= 4:
                dn[:] = []
            dn[:] = [d for d in dn if not d.startswith(".") and d.lower() not in skip]
            items.extend((os.path.join(dp, d), True) for d in dn)
            items.extend((os.path.join(dp, f), False) for f in fn)
            if len(items) > 30000:
                break
    _index["t"], _index["items"] = time.time(), items
    return items


def _words(s):
    return normalize(re.sub(r"[_.\-]", " ", s)).split()


def _score(qwords, name):
    """0 to 1: how well the name matches the words we heard."""
    nl = name.lower()
    nw = _words(name)
    if not nw:
        return 0.0
    total = 0.0
    for q in qwords:
        if q in nl:
            total += 1
            continue
        best = max(difflib.SequenceMatcher(None, q, w).ratio() for w in nw)
        total += 1 if best >= 0.85 else (best if best >= 0.7 else 0)
    return total / len(qwords)


def find_file(query):
    """Best matching file or folder for the words, or None. Returns a path."""
    qwords = normalize(query).split()
    if not qwords:
        return None
    scored = []
    for path, is_dir in _file_index():
        stem = os.path.basename(path) if is_dir else os.path.splitext(os.path.basename(path))[0]
        s = _score(qwords, stem)
        if s >= 0.6:
            scored.append((s, path))
    if not scored:
        return None
    top = max(s for s, _ in scored)
    best = [p for s, p in scored if s >= top - 0.001]
    best.sort(key=lambda p: os.path.getmtime(p) if os.path.exists(p) else 0, reverse=True)
    return best[0]


def _start_apps():
    """[(name, appid)] for every app in the Start menu (Store apps too)."""
    if _apps["items"] is not None:
        return _apps["items"]
    items = []
    try:
        ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
              "Get-StartApps | ForEach-Object { $_.Name + '|' + $_.AppID }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, timeout=25).stdout.decode("utf-8", "ignore")
        for line in out.splitlines():
            if "|" in line:
                name, appid = line.rsplit("|", 1)
                if name.strip() and "uninstall" not in name.lower():
                    items.append((name.strip(), appid.strip()))
    except Exception:
        pass
    _apps["items"] = items
    return items


def find_app(query):
    qwords = normalize(query).split()
    if not qwords:
        return None
    best, best_s = None, 0.0
    for name, appid in _start_apps():
        s = _score(qwords, name)
        if s > best_s:
            best, best_s = (name, appid), s
    return best if best_s >= 0.75 else None


# ------------------------------------------------------------------
# Read aloud (Windows built-in voice, no install needed)
# ------------------------------------------------------------------
_tts = {"p": None}


def stop_speaking():
    p = _tts["p"]
    if p is not None and p.poll() is None:
        p.terminate()
    _tts["p"] = None


def speak(text):
    stop_speaking()
    text = re.sub(r"\s+", " ", text).strip()[:6000]
    if not text:
        return
    # Always a FEMALE voice (Hindi text: a Hindi female voice if Windows has one installed).
    ps = ("Add-Type -AssemblyName System.Speech;"
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
          "$f = [System.Speech.Synthesis.VoiceGender]::Female;"
          "$a = [System.Speech.Synthesis.VoiceAge]::NotSet;"
          "if ($env:DOIT_SPEAK -match '[\\u0900-\\u097F]') {"
          "  try { $s.SelectVoiceByHints($f, $a, 0, [System.Globalization.CultureInfo]'hi-IN') } catch {} }"
          "else { try { $s.SelectVoiceByHints($f) } catch {} };"
          "$s.Speak($env:DOIT_SPEAK)")
    env = dict(os.environ, DOIT_SPEAK=text)     # text goes in as data, never as code
    _tts["p"] = subprocess.Popen(["powershell", "-NoProfile", "-Command", ps], env=env,
                                 creationflags=0x08000000)   # no extra window


def _clip(set_to=None):
    import tkinter
    r = tkinter.Tk()
    r.withdraw()
    try:
        if set_to is not None:
            r.clipboard_clear()
            r.clipboard_append(set_to)
            r.update()
            return set_to
        try:
            return r.clipboard_get()
        except tkinter.TclError:
            return ""
    finally:
        r.destroy()


def _read_aloud(pyautogui, mode):
    marker = "__doit_nothing_copied__"
    _clip(marker)
    if mode == "all":
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
    pyautogui.hotkey("ctrl", "c")
    time.sleep(0.4)
    text = _clip()
    if text == marker and mode == "selection":       # nothing was selected: take the whole page
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.4)
        text = _clip()
    if text in (marker, ""):
        return "I could not find any text to read. Select some text first."
    speak(text)
    return "Reading aloud. Say stop reading to stop me."


# ------------------------------------------------------------------
# Wi-Fi / Bluetooth switch (Windows radio API, no admin needed)
# ------------------------------------------------------------------
RADIO_SCRIPT = r"""
$kind = $env:DOIT_KIND; $want = $env:DOIT_STATE
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($t, $type) { $m = $asTaskGeneric.MakeGenericMethod($type); $n = $m.Invoke($null, @($t)); $n.Wait(-1) | Out-Null; $n.Result }
[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioAccessStatus,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
[Windows.Devices.Radios.RadioState,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null
Await ([Windows.Devices.Radios.Radio]::RequestAccessAsync()) ([Windows.Devices.Radios.RadioAccessStatus]) | Out-Null
$radios = Await ([Windows.Devices.Radios.Radio]::GetRadiosAsync()) ([System.Collections.Generic.IList[Windows.Devices.Radios.Radio]])
$r = $radios | Where-Object { $_.Kind -eq $kind } | Select-Object -First 1
if (-not $r) { 'notfound'; exit }
$state = [Windows.Devices.Radios.RadioState]::$want
$res = Await ($r.SetStateAsync($state)) ([Windows.Devices.Radios.RadioAccessStatus])
"$res"
"""


def _set_radio(name, on):
    kind = "Bluetooth" if name == "bluetooth" else "WiFi"
    env = dict(os.environ, DOIT_KIND=kind, DOIT_STATE="On" if on else "Off")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", RADIO_SCRIPT],
                           capture_output=True, timeout=25, env=env)
        return r.stdout.decode("utf-8", "ignore").strip().splitlines()[-1:] == ["Allowed"]
    except Exception:
        return False


# ------------------------------------------------------------------
# Playing songs
# ------------------------------------------------------------------
def _youtube_first_video(q):
    import urllib.request
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(q)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                               "Accept-Language": "en"})
    html = urllib.request.urlopen(req, timeout=6).read().decode("utf-8", "ignore")
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})"', html)
    return m.group(1) if m else None


def _play_song(song, service):
    if service == "spotify":
        try:
            os.startfile("spotify:search:" + urllib.parse.quote(song))
            return ("Opened Spotify and searched for %s. Click the green play button "
                    "(pinch with your hand). Then I can pause and skip for you." % song)
        except OSError:
            webbrowser.open("https://open.spotify.com/search/" + urllib.parse.quote(song))
            return "Opened Spotify in the browser for %s. Click the play button." % song
    try:
        vid = _youtube_first_video(song)
    except Exception:
        vid = None
    if vid:
        webbrowser.open("https://www.youtube.com/watch?v=" + vid)
        return "Playing %s on YouTube." % song
    webbrowser.open("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(song))
    return "Could not pick the first video, so I opened the YouTube results for %s." % song


# ------------------------------------------------------------------
# Doing
# ------------------------------------------------------------------
def foreground_title():
    try:
        import ctypes
        u = ctypes.windll.user32
        hwnd = u.GetForegroundWindow()
        buf = ctypes.create_unicode_buffer(256)
        u.GetWindowTextW(hwnd, buf, 256)
        return buf.value
    except Exception:
        return ""


def _show_window(code):
    import ctypes
    u = ctypes.windll.user32
    u.ShowWindow(u.GetForegroundWindow(), code)   # 6 = minimize, 3 = maximize


def _open_named(query, prefer):
    order = ("file", "app") if prefer == "file" else ("app", "file")
    for kind in order:
        if kind == "app":
            hit = find_app(query)
            if hit:
                subprocess.Popen(["explorer", "shell:AppsFolder\\" + hit[1]])
                return "Opening %s." % hit[0]
        else:
            path = find_file(query)
            if path:
                if os.path.splitext(path)[1].lower() in BLOCKED_EXT:
                    return "For safety I do not open program files by name."
                os.startfile(path)
                return "Opening %s." % os.path.basename(path)
    return "I could not find %s on this laptop." % query


def execute(c):
    """Does the command c (from parse). Returns a sentence about what happened."""
    import pyautogui
    a, arg = c["action"], c["arg"]

    if a in NEEDS_OTHER_WINDOW:
        title = foreground_title().lower()
        if any(s in title for s in OWN_WINDOWS):
            return "Click on the window you want to control first, then say it again."

    try:
        if a == "open_folder":
            subprocess.Popen(["explorer", arg] if arg else ["explorer"])
        elif a == "open_app":
            if arg == "camera":
                os.startfile("microsoft.windows.camera:")
            elif arg == "settings":
                os.startfile("ms-settings:")
            elif arg in ("notepad", "calculator", "paint"):
                subprocess.Popen({"notepad": "notepad", "calculator": "calc",
                                  "paint": "mspaint"}[arg])
            elif arg == "chrome":
                subprocess.Popen(["cmd", "/c", "start", "", "chrome"])
            elif arg == "edge":
                subprocess.Popen(["cmd", "/c", "start", "", "msedge"])
        elif a == "open_named":
            return _open_named(*arg)
        elif a == "open_settings":
            os.startfile(arg)
        elif a == "open_url":
            webbrowser.open(arg)
        elif a == "search":
            webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote_plus(arg))
        elif a == "play":
            return _play_song(*arg)
        elif a in MEDIA:
            pyautogui.press(MEDIA[a][0])
        elif a == "read":
            return _read_aloud(pyautogui, arg)
        elif a == "stop_reading":
            stop_speaking()
        elif a == "radio":
            name, on = arg
            if _set_radio(name, on):
                return c["say"] or "Done."
            os.startfile("ms-settings:bluetooth" if name == "bluetooth"
                         else "ms-settings:network-wifi")
            return "Windows did not let me switch it, so I opened the settings page."
        elif a == "lock":
            import ctypes
            ctypes.windll.user32.LockWorkStation()
        elif a == "time":
            msg = time.strftime("It is %I:%M %p.")
            speak(msg)
            return msg
        elif a == "date":
            msg = time.strftime("Today is %A, %d %B %Y.")
            speak(msg)
            return msg
        elif a == "type":
            time.sleep(0.3)
            pyautogui.write(arg, interval=0.02)       # English letters only for now
        elif a == "scroll":
            pyautogui.scroll(arg)
        elif a == "click":
            pyautogui.click()
        elif a == "double_click":
            pyautogui.doubleClick()
        elif a == "right_click":
            pyautogui.rightClick()
        elif a == "volume":
            key = {"up": "volumeup", "down": "volumedown", "mute": "volumemute"}[arg]
            pyautogui.press(key, presses=1 if arg == "mute" else 5)
        elif a == "window":
            return window_control(*arg)
        elif a == "minimize":
            return window_control("minimize", "")
        elif a == "maximize":
            return window_control("maximize", "")
        elif a == "delete":
            pyautogui.press("delete")                 # goes to the Recycle Bin
        elif a == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "30"])
            return "Shutting down in 30 seconds. Say cancel shutdown to stop it."
        elif a == "restart":
            subprocess.run(["shutdown", "/r", "/t", "30"])
            return "Restarting in 30 seconds. Say cancel shutdown to stop it."
        elif a == "cancel_shutdown":
            subprocess.run(["shutdown", "/a"])
        elif a in HOTKEYS:
            pyautogui.hotkey(*HOTKEYS[a][0])
        else:
            return "I do not know how to do that yet."
    except Exception as e:
        return "Sorry, that did not work (%s)." % e
    return c["say"] or "Done."

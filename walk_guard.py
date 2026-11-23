"""
Roe - Feature: Walk-away guard

Say (English / Hindi / Hinglish):
    "guard on"      "walk away guard on"    "guard chalu karo"     "गार्ड चालू करो"
    "guard off"     "walk away guard off"   "guard band karo"      "गार्ड बंद करो"

What it does while the guard is ON:
    * the webcam looks for your face, only 2 times per second (very low CPU),
    * no face for AWAY_SECONDS (default 10)  ->  pauses the music / video, then locks the laptop (Win+L),
    * when your face is seen again          ->  resumes the music / video (only if the guard paused it).
      You still need your Windows password / PIN to unlock. The guard never types your password.

Only ONE program may use the webcam. If another program has it, the guard tells you.
Needs: mediapipe and opencv (already installed for Roe).
"""
import atexit
import ctypes
import re
import threading
import time

# ---------------- Settings you can change ----------------
AWAY_SECONDS = 10          # no face for this long = you walked away
BACK_SECONDS = 1.0         # face seen this long = you are back
CHECKS_PER_SECOND = 2      # low CPU
CAMERA_INDEX = 0
PAUSE_MEDIA = True         # press the Play/Pause key when you leave and again when you return.
                           # (If nothing was playing, that key may START something: set False if that annoys you.)
LOCK_SCREEN = True
BEEP = True
FACE_CONFIDENCE = 0.5
# ---------------------------------------------------------

ACTIONS = {"guard_on", "guard_off"}
NO_TRANSLATE = {"guard_on", "guard_off"}
PROMPT = """guard_on      args: {}     (\"guard on\", \"walk away guard on\", \"guard chalu karo\": lock the laptop when she walks away)
guard_off     args: {}     (\"guard off\", \"guard band karo\")"""

M = {
    "on": ("Walk-away guard is on. I will lock the laptop if you are away for {s} seconds.",
           "वॉक-अवे गार्ड चालू है। आप {s} सेकंड दूर रहेंगे तो मैं लैपटॉप लॉक कर दूँगी।"),
    "already": ("The guard is already on.", "गार्ड पहले से चालू है।"),
    "off": ("Walk-away guard is off.", "वॉक-अवे गार्ड बंद है।"),
    "not_on": ("The guard was not on.", "गार्ड चालू नहीं था।"),
    "no_cam": ("I could not open the webcam. Another program may be using it.",
               "मैं वेबकैम नहीं खोल पाई। शायद कोई और प्रोग्राम उसे इस्तेमाल कर रहा है।"),
    "no_pkg": ("The guard needs mediapipe and opencv. Run: py -3.11 -m pip install -r requirements.txt",
               "गार्ड के लिए mediapipe और opencv चाहिए। चलाइए: py -3.11 -m pip install -r requirements.txt"),
}


def _m(key, hindi, **kw):
    return M[key][1 if hindi else 0].format(**kw)


# ------------------------------------------------------------------
# Understanding the sentence
# ------------------------------------------------------------------
_GUARD = re.compile(r"\bguard\b|गार्ड|\bgaurd\b|\bgard\b")
_ON = re.compile(r"\b(?:on|start|activate|enable|chalu|shuru|laga|lagao)\b|चालू|शुरू|लगाओ|ऑन")
_OFF = re.compile(r"\b(?:off|stop|deactivate|disable|band|bandh|hata|hatao)\b|बंद|हटाओ|ऑफ")


def _cmd(action):
    return {"action": action, "arg": None, "say": "", "risky": False}


def parse(text, hindi=False):
    t = re.sub(r"[.,!?।]+", " ", text.lower())
    if not _GUARD.search(t):
        return None
    if _OFF.search(t):
        return _cmd("guard_off")
    if _ON.search(t):
        return _cmd("guard_on")
    return None


def to_command(action, args, reply):
    return _cmd(action) if action in ACTIONS else None


# ------------------------------------------------------------------
# The decision part (no camera, easy to test)
# ------------------------------------------------------------------
class Guard:
    """Feed it 'face seen or not' with the time. It says what to do: None, 'leave' or 'return'."""

    def __init__(self, away=AWAY_SECONDS, back=BACK_SECONDS):
        self.away, self.back = away, back
        self.state = "present"
        self.last_seen = None
        self.seen_since = None

    def step(self, face, now):
        if self.last_seen is None:
            self.last_seen = now
        if face:
            self.last_seen = now
            if self.seen_since is None:
                self.seen_since = now
            if self.state == "away" and now - self.seen_since >= self.back:
                self.state = "present"
                return "return"
        else:
            self.seen_since = None
            if self.state == "present" and now - self.last_seen >= self.away:
                self.state = "away"
                return "leave"
        return None


# ------------------------------------------------------------------
# Windows actions
# ------------------------------------------------------------------
def _beep(freq, ms):
    if BEEP:
        try:
            import winsound
            winsound.Beep(freq, ms)
        except Exception:
            pass


def _play_pause():
    import pyautogui
    pyautogui.press("playpause")


def _lock():
    ctypes.windll.user32.LockWorkStation()


class _Runner:
    def __init__(self):
        self.thread = None
        self.stop = threading.Event()
        self.paused_by_us = False

    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        import cv2
        import mediapipe as mp
        cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(CAMERA_INDEX)
        if not cap or not cap.isOpened():
            raise RuntimeError("camera")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 320)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 240)
        detector = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=FACE_CONFIDENCE)
        self.stop.clear()
        self.thread = threading.Thread(target=self._loop, args=(cap, detector), daemon=True)
        self.thread.start()

    def _loop(self, cap, detector):
        import cv2
        g = Guard()
        gap = 1.0 / CHECKS_PER_SECOND
        try:
            while not self.stop.is_set():
                t0 = time.time()
                ok, frame = cap.read()
                face = False
                if ok and frame is not None:
                    res = detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    face = bool(res.detections)
                elif g.state == "present":
                    face = True                       # camera hiccup while you are here: do nothing
                event = g.step(face, time.time())
                if event == "leave":
                    _beep(500, 300)
                    if PAUSE_MEDIA:
                        try:
                            _play_pause()
                            self.paused_by_us = True
                        except Exception:
                            pass
                    if LOCK_SCREEN:
                        try:
                            _lock()
                        except Exception:
                            pass
                elif event == "return":
                    if self.paused_by_us:
                        try:
                            _play_pause()
                        except Exception:
                            pass
                        self.paused_by_us = False
                    _beep(900, 200)
                time.sleep(max(0.0, gap - (time.time() - t0)))
        finally:
            try:
                cap.release()
                detector.close()
            except Exception:
                pass

    def shutdown(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=3)
        self.thread = None


_runner = _Runner()
atexit.register(_runner.shutdown)


def run(c):
    hindi = bool(c.get("hindi"))
    if c["action"] == "guard_on":
        if _runner.running():
            return _m("already", hindi)
        try:
            _runner.start()
        except ImportError:
            return _m("no_pkg", hindi)
        except RuntimeError:
            return _m("no_cam", hindi)
        return _m("on", hindi, s=AWAY_SECONDS)
    if c["action"] == "guard_off":
        if not _runner.running():
            return _m("not_on", hindi)
        _runner.shutdown()
        return _m("off", hindi)
    return None

"""
Roe - ONE-CLICK START / STOP  (this is what the desktop shortcut runs)

Click the shortcut (or press Ctrl+Alt+D):
    Roe is not running  ->  it starts (a window opens and says Voice is ready)
    Roe is running      ->  it stops (the window closes)
So the same click works as an ON / OFF toggle.  No typing in the black window needed.

PHONE SHORTCUT:  toggle_doit.py --phone   starts Roe already in PHONE CONTROL mode (the phone screen opens
on the laptop and your voice controls the phone). Click either shortcut while Roe is running to stop it.
"""
import ctypes
import os
import subprocess
import sys

FOLDER = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(FOLDER, ".doit_pid")
MAIN = "voice_assistant.py"          # later: the chat window file


def _alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True,
                             creationflags=0x08000000).stdout          # no flashing window
        return str(pid) in out
    except Exception:
        return False


def _message(text):
    ctypes.windll.user32.MessageBoxW(0, text, "Roe", 0x40)


def main():
    pid = None
    try:
        pid = int(open(PID_FILE).read().strip())
    except Exception:
        pass
    if pid and _alive(pid):
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=0x08000000)
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return
    extra = ["--phone"] if "--phone" in sys.argv[1:] else []
    p = subprocess.Popen(["py", "-3.11", MAIN] + extra, cwd=FOLDER, creationflags=subprocess.CREATE_NEW_CONSOLE)
    with open(PID_FILE, "w") as f:
        f.write(str(p.pid))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        _message("Could not start or stop Roe:\n%s" % e)
        sys.exit(1)

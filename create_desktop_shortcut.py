"""
Run this ONCE:   py -3.11 create_desktop_shortcut.py
It puts TWO icons on your Desktop:
   "Roe"        click = start Roe for the LAPTOP (say "activate voice"), click again = stop.   Keyboard: Ctrl + Alt + D
   "Roe Phone"  click = start Roe already in PHONE CONTROL mode (your phone screen opens on the laptop
                  and your voice controls the phone), click again = stop.                          Keyboard: Ctrl + Alt + P
(You can also switch while it is running: say "control phone" for the phone, "activate voice" to come back.)
You can rename the icons on the Desktop any time.
"""
import os
import shutil
import subprocess
import sys

FOLDER = os.path.dirname(os.path.abspath(__file__))
# (icon name, keyboard shortcut, extra argument, description)
SHORTCUTS = [
    ("Roe", "CTRL+ALT+D", "", "Start / stop Roe (laptop)"),
    ("Roe Phone", "CTRL+ALT+P", " --phone", "Start / stop Roe in phone control mode"),
]


def make(pyw, name, hotkey, extra, desc):
    ps = r"""
$desk = [Environment]::GetFolderPath('Desktop')
$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk '%s.lnk'))
$s.TargetPath = '%s'
$s.Arguments = '-3.11 "%s"%s'
$s.WorkingDirectory = '%s'
$s.Hotkey = '%s'
$s.Description = '%s'
$s.IconLocation = "$env:SystemRoot\System32\imageres.dll,%s"
$s.Save()
Write-Output (Join-Path $desk '%s.lnk')
""" % (name, pyw, os.path.join(FOLDER, "toggle_doit.py"), extra, FOLDER, hotkey, desc,
       "109" if not extra else "15", name)
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    if r.returncode != 0:
        print("Could not create the shortcut '%s':\n%s" % (name, r.stderr))
        return False
    print("Done. Shortcut created: " + r.stdout.strip() + "   (keyboard: %s)" % hotkey)
    return True


def main():
    pyw = shutil.which("pyw") or shutil.which("pythonw")
    if not pyw:
        print("Could not find pyw.exe (the Python launcher). Reinstall Python 3.11 with 'py launcher' ticked.")
        return 1
    ok = all([make(pyw, *s) for s in SHORTCUTS])
    if ok:
        print("Click an icon to start, click again to stop.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

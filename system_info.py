"""
ROGER THAT - system_info.py
Fills in the blanks in Section 4.18 (test setup) from the real laptop and phone.
Free, no extra packages. Uses the ADB that is already in the platform-tools folder.

Run it on the laptop you tested on, with the phone plugged in by USB (USB debugging ON, phone unlocked):
    py -3.11 system_info.py
Then copy the printed sentence into the report.
"""
import os
import platform
import subprocess
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ADB = os.path.join(HERE, "platform-tools", "adb.exe")
if not os.path.exists(ADB):
    ADB = "adb"   # fall back to an ADB that is on PATH


def run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def powershell(script):
    return run(["powershell", "-NoProfile", "-Command", script])


def laptop_info():
    out = powershell("Get-CimInstance Win32_ComputerSystem | "
                     "Select-Object Manufacturer,Model,TotalPhysicalMemory | ConvertTo-Json")
    try:
        d = json.loads(out)
        model = f"{d['Manufacturer'].strip()} {d['Model'].strip()}"
        ram = round(int(d["TotalPhysicalMemory"]) / 1024 ** 3)   # Windows shows ~15.8 GB for a 16 GB laptop
    except Exception:
        model, ram = "?", "?"
    cpu = powershell("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name") or platform.processor() or "?"
    return model, " ".join(cpu.split()), ram


def windows_version():
    # Windows 11 is still reported as "10.0"; build 22000 or higher means Windows 11.
    try:
        build = int(platform.version().split(".")[2])
        return "11" if build >= 22000 else "10"
    except Exception:
        return "?"


def phone_info():
    state = run([ADB, "get-state"])
    if "device" not in state:
        return "? (phone not detected: plug in USB, unlock it, allow USB debugging)"
    maker = run([ADB, "shell", "getprop", "ro.product.manufacturer"]).capitalize()
    model = run([ADB, "shell", "getprop", "ro.product.model"])
    android = run([ADB, "shell", "getprop", "ro.build.version.release"])
    return f"{maker} {model}, Android {android}"


if __name__ == "__main__":
    laptop, cpu, ram = laptop_info()
    phone = phone_info()
    print("\nCopy this into Section 4.18:\n")
    print(f"Testing was carried out on a {laptop} running Windows {windows_version()}, with {cpu}, "
          f"{ram} GB RAM and Python {platform.python_version()}, using the built-in microphone and a "
          f"connected Android phone ({phone}) over USB debugging.")
    print("\nCheck the Python version above says 3.11 (run this file with: py -3.11 system_info.py).")

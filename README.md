# Roger – Voice Assistant for Laptop and Phone

Roger is a hands-free voice assistant for **Windows**. Say "Hello Roe" and control your laptop and your Android phone with your voice, in English or Hindi.

7th semester Black Book project.

**Want to see it working live or need more details? Contact me:**
- Name: VAIBHAVI JADHAV
- Email: buildsbyvb@gmail.com
- LinkedIn: https://www.linkedin.com/in/vaiibhhavvii/

## Screenshots and output
You can find this in the screenshots folder 

## What it can do
- Wake and sleep by voice ("Hello Roe" / "Bye Roe")
- Answer questions using web search and speak a short summary
- Control the laptop: open and close apps, volume, Wi-Fi, Bluetooth, timers, reminders
- Play music (Spotify) and YouTube
- Control an Android phone from the laptop: open apps, scroll, call, SMS, WhatsApp, camera, play videos
- Understand English and Hindi/Hinglish
- Ask "Are you sure?" before risky commands (delete, shutdown, restart)

## Results
| Metric | Value |
|---|---|
| Speech-to-text time | 1.63 s average |
| LLM response time | 0.62 s average |
| End-to-end response | 2.25 s average |
| English word error rate | 3.3 % |
| Command success | 90 % (18 of 20) |

Tested on CPU with Whisper small and Groq `openai/gpt-oss-20b`.

## Tech stack
Python 3.11, faster-whisper, Groq LLM API, edge-tts, sounddevice, pyautogui, MediaPipe, ADB, scrcpy, Spotipy.

## How to run it on your laptop

**You need:** Windows 10 or 11, a microphone, an internet connection, and about 3 GB of free space.

**Step 1 – Download.** Click the green **Code** button at the top of this page, then **Download ZIP**. Right-click the ZIP and choose **Extract All**. Put the extracted folder somewhere simple, for example `C:\Roger`.

**Step 2 – Install Python 3.11.** Download Python 3.11 from python.org/downloads (version 3.11 specifically). In the installer, tick **Add python.exe to PATH** and keep **py launcher** ticked.

**Step 3 – Install the libraries.** Open the extracted folder, click the address bar, type `cmd` and press Enter. Then run:
```
py -3.11 -m pip install -r requirements.txt
```

**Step 4 – Get a free AI key.** Sign up at console.groq.com, create an API key, then run this in Command Prompt:
```
setx GROQ_API_KEY "paste-your-key-here"
```
Close Command Prompt and open a new one in the folder (Step 3 method).

**Step 5 – Start Roger.**
```
py -3.11 voice_assistant.py
```
The first start downloads the speech model, so it takes a few minutes. After that, say **"Hello Roe"**. To stop, click the black window and press Ctrl + C.

**Step 6 (optional) – Desktop shortcut.** Run once:
```
py -3.11 create_desktop_shortcut.py
```
This puts two icons on your Desktop: one starts Roger for the laptop (Ctrl+Alt+D), one starts it in phone mode (Ctrl+Alt+P).

**Step 7 (optional) – Phone control.** On your Android phone go to Settings → About phone, tap **Build number** 7 times, then open Developer options and turn on **USB debugging**. Connect the phone with a USB cable, keep it unlocked, tap **Allow** on the phone, and say "control phone". ADB and scrcpy are already included in this download.

**Step 8 (optional) – Spotify.** Create an app at developer.spotify.com and set `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET` and `SPOTIPY_REDIRECT_URI` with `setx`, the same way as Step 4.

## Common problems
- **"py is not recognized":** reinstall Python 3.11 with "py launcher" ticked.
- **Nothing happens when I speak:** check that your microphone is the Windows default input device.
- **"no GROQ_API_KEY found":** repeat Step 4 and open a new Command Prompt.
- **Phone not found:** use a data cable (not charge-only), unlock the phone and accept the USB debugging prompt.

## Third-party tools
This download includes Android platform-tools (ADB) and scrcpy, which are open-source tools by Google and Genymobile. Their licenses are in their folders.

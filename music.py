"""
Do It - Step 8: music.

play(song, service)   "play X" -> Spotify (default)   "play X on youtube" -> YouTube
play_current()        "play the song" / "play music" (no name) -> plays the song that is
                      ALREADY loaded in Spotify (or the player you used last). It never
                      picks a song by itself.
pause_current()       pauses only if something is really playing.
Next / previous use the keyboard media keys (in actions.py).

SPOTIFY (honest note): Spotify only lets a program START a chosen song if you have
Spotify PREMIUM (their rule, not ours). Two modes:
  * Premium + the 3 variables below set  -> the song starts by itself.
  * Otherwise -> Spotify opens on the search for the song and you press its play
    button (pinch with the hand mouse). Pause / next still work by voice.
Variables (set once, then open a NEW cmd window):
  setx SPOTIPY_CLIENT_ID "..."       setx SPOTIPY_CLIENT_SECRET "..."
  setx SPOTIPY_REDIRECT_URI "http://127.0.0.1:8888/callback"
Install:  py -3.11 -m pip install spotipy
The first song opens a browser once so you can log in to Spotify.
"""
import os
import re
import subprocess
import time
import webbrowser

import actions

# Words that mean "the song that is already there" (no song name was said).
GENERIC_WORDS = {"the", "a", "an", "some", "any", "song", "songs", "music", "gaana", "gana", "gane",
                 "track", "tracks", "it", "this", "that", "current", "currently", "playing", "one",
                 "please", "me", "my", "spotify", "on", "in", "from", "ko", "wala", "wali", "ye", "yeh",
                 "hindi", "bollywood", "popular", "new", "good", "random", "latest", "famous", "fav",
                 "favourite", "favorite", "last", "same", "again", "ab", "abhi", "chalu", "karo", "kar",
                 "do", "chalao", "bajao", "laga", "lagao", "start", "resume", "continue", "play"}


def is_generic(song):
    """True when there is no real song name ("the song", "music", "it", "")."""
    words = re.findall(r"[a-z]+", (song or "").lower())
    return all(w in GENERIC_WORDS for w in words)


CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".spotify_token")
_state = {"sp": None, "failed": False, "problem": ""}


def spotify_api_configured():
    return bool(os.environ.get("SPOTIPY_CLIENT_ID") and os.environ.get("SPOTIPY_CLIENT_SECRET"))


def _client():
    if _state["sp"] is not None:
        return _state["sp"]
    if _state["failed"] or not spotify_api_configured():
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        auth = SpotifyOAuth(
            client_id=os.environ["SPOTIPY_CLIENT_ID"],
            client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
            redirect_uri=os.environ.get("SPOTIPY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope="user-modify-playback-state user-read-playback-state",
            cache_path=CACHE, open_browser=True)
        _state["sp"] = spotipy.Spotify(auth_manager=auth, requests_timeout=8, retries=1)
    except Exception as e:
        _state["failed"] = True
        _state["problem"] = "%s: %s" % (type(e).__name__, str(e)[:100])
    return _state["sp"]


def _device(sp):
    devices = sp.devices().get("devices", [])
    active = [d for d in devices if d.get("is_active")]
    return (active or devices or [None])[0]


def _spotify_api_play(query):
    """Returns a sentence if it worked, or None (then the search page is opened)."""
    sp = _client()
    if sp is None:
        return None
    try:
        items = sp.search(q=query, type="track", limit=1)["tracks"]["items"]
        if not items:
            return "I could not find %s on Spotify." % query
        track = items[0]
        dev = _device(sp)
        if dev is None:                                   # Spotify is closed: start it and wait
            try:
                os.startfile("spotify:")
            except OSError:
                webbrowser.open("https://open.spotify.com")
            for _ in range(10):
                time.sleep(1)
                dev = _device(sp)
                if dev:
                    break
        if dev is None:
            raise RuntimeError("no Spotify device is open")
        sp.start_playback(device_id=dev["id"], uris=[track["uri"]])
        return "Playing %s by %s on Spotify." % (track["name"], track["artists"][0]["name"])
    except Exception as e:
        _state["problem"] = "%s: %s" % (type(e).__name__, str(e)[:120])
        print("(Spotify API said: %s)" % _state["problem"])
        return None


def play(song, service="spotify"):
    if is_generic(song):                                  # "play the song" = the current song
        return play_current()
    if service == "youtube":
        return actions._play_song(song, "youtube")
    done = _spotify_api_play(song)
    if done:
        return done
    return actions._play_song(song, "spotify")


# ------------------------------------------------------------------
# "Play the song" = continue the CURRENT song (never a random or famous one)
# ------------------------------------------------------------------
# Windows keeps one "media session" for every player (Spotify, YouTube in the browser ...).
# With it we can ask "is it playing?" and press ONLY play (or ONLY pause), so "play the song"
# never pauses a song that is already playing (the keyboard play/pause key cannot know that).
MEDIA_SCRIPT = r"""
$act = $env:DOIT_ACT; $pref = $env:DOIT_PREF
try {
  Add-Type -AssemblyName System.Runtime.WindowsRuntime
  $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
  function Await($op, $type) { $m = $asTask.MakeGenericMethod($type); $t = $m.Invoke($null, @($op)); $t.Wait(-1) | Out-Null; $t.Result }
  [Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager,Windows.Media.Control,ContentType=WindowsRuntime] | Out-Null
  $mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
  $all = @($mgr.GetSessions())
  if ($all.Count -eq 0) { 'nosession'; exit }
  $s = $null
  if ($act -eq 'pause') {
    $s = $all | Where-Object { "$($_.GetPlaybackInfo().PlaybackStatus)" -eq 'Playing' } | Select-Object -First 1
    if (-not $s) { 'notplaying'; exit }
  } else {
    if ($pref) { $s = $all | Where-Object { $_.SourceAppUserModelId -like "*$pref*" } | Select-Object -First 1 }
    if (-not $s) { $s = $mgr.GetCurrentSession() }
    if (-not $s) { $s = $all[0] }
  }
  $st = "$($s.GetPlaybackInfo().PlaybackStatus)"
  if ($act -eq 'play') {
    if ($st -eq 'Playing') { 'already'; exit }
    $ok = Await ($s.TryPlayAsync()) ([bool])
    if ($ok) { 'played' } else { 'failed' }
  } elseif ($act -eq 'pause') {
    $ok = Await ($s.TryPauseAsync()) ([bool])
    if ($ok) { 'paused' } else { 'failed' }
  } else { $st }
} catch { 'error: ' + $_.Exception.Message }
"""


def _media(act, pref="spotify"):
    """Asks Windows. Returns: played | already | paused | notplaying | nosession | failed | error: ..."""
    env = dict(os.environ, DOIT_ACT=act, DOIT_PREF=pref)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", MEDIA_SCRIPT],
                           capture_output=True, timeout=20, env=env, creationflags=0x08000000)
        lines = r.stdout.decode("utf-8", "ignore").strip().splitlines()
        return lines[-1] if lines else "error: " + (r.stderr.decode("utf-8", "ignore").strip()[:150] or "no answer")
    except Exception as e:
        return "error: " + str(e)[:120]


def _press_playpause():
    import pyautogui
    pyautogui.press("playpause")


def play_current():
    """Continues the song that is already loaded. Never chooses a song itself."""
    sp = _client()                                        # Premium + keys: resume through Spotify
    if sp is not None:
        try:
            dev = _device(sp)
            if dev:
                sp.start_playback(device_id=dev["id"])
                return "Playing your song."
        except Exception as e:
            print("(Spotify API said: %s)" % str(e)[:120])
    st = _media("play")
    if st == "played":
        return "Playing."
    if st == "already":
        return "It is already playing."
    if st == "nosession":                                 # nothing open: start Spotify, then press play
        try:
            os.startfile("spotify:")
        except OSError:
            webbrowser.open("https://open.spotify.com")
        for _ in range(5):
            time.sleep(2)
            st = _media("play")
            if st in ("played", "already"):
                return "Opened Spotify and playing."
        _press_playpause()
        return "I opened Spotify and pressed play. If nothing plays, tell me the song name."
    if st.startswith("error"):
        print("(Windows said: %s)" % st)
    _press_playpause()                                    # last choice: the keyboard play/pause key
    return "I pressed play."


def pause_current():
    st = _media("pause")
    if st == "paused":
        return "Paused."
    if st == "notplaying":
        return "Nothing is playing right now."
    if st == "nosession":
        return "Nothing is playing right now."
    if st.startswith("error"):
        print("(Windows said: %s)" % st)
    _press_playpause()
    return "I pressed pause."

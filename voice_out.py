"""
Do It - Step 11: natural spoken replies (ALWAYS a woman's voice) that START AT ONCE and can be interrupted.

Speaker.speak(text)  starts talking and returns at once (does not wait).
Speaker.is_playing() True while talking.   Speaker.stop() stops immediately.

Voice: Microsoft "Neural" voices through the free edge-tts package
(Indian English: Neerja; Hindi text uses Swara). Needs internet and
  py -3.11 -m pip install edge-tts pygame
If that is missing or offline, it falls back to the built-in Windows voice
automatically, so the assistant never goes silent.
"""
import asyncio
import os
import re
import concurrent.futures
import tempfile
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import actions

# ---------------- Settings you can change ----------------
USE_NEURAL = True                     # False = always use the Windows voice
VOICE_EN = "en-IN-NeerjaNeural"       # girl's voice. Other girl choices: en-US-AriaNeural, en-GB-SoniaNeural
VOICE_HI = "hi-IN-SwaraNeural"        # girl's voice (Hindi text). Never use a "...Prabhat/Madhur" voice: those are men
TRIES = 3                             # the internet voice is tried this many times before the Windows
                                      # voice is used (the Windows voice is also set to a girl's voice)
SPEED = "+10%"                         # "+0%" normal, "-10%" slower
TIMEOUT = 8                           # seconds to wait for one piece of the internet voice
MAX_SPOKEN_CHARS = 700                # long answers are only read in part (the full text is on screen)
# ---------------------------------------------------------


def clean_for_speech(text):
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[\s*\d+(?:\s*[,-]\s*\d+)*\s*\]", "", text)
    text = re.sub(r"[*#`_~>|]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def split_chunks(text, max_len=140):
    """Cuts the reply into short pieces (sentences). The first piece is spoken while the
    next ones are still being prepared, so the voice starts almost at once."""
    out = []
    for p in re.split(r"(?<=[.!?\u0964])\s+", text):
        p = p.strip()
        while len(p) > (max_len if out else 90):      # the FIRST piece is short, so the voice starts sooner
            limit = max_len if out else 90
            cut = max(p.rfind(", ", 0, limit), p.rfind(" ", 0, limit))
            if cut < 40:
                cut = limit
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if p:
            out.append(p)
    merged = []
    for p in out:                                   # a tiny piece like "Okay." joins the next one
        if merged and len(merged[-1]) < 25:
            merged[-1] += " " + p
        else:
            merged.append(p)
    return merged


def shorten(text, limit=MAX_SPOKEN_CHARS):
    if len(text) <= limit:
        return text
    cut = text[:limit]
    ends = [cut.rfind(x) for x in (". ", "? ", "! ", "। ")]
    best = max(ends)
    return cut[:best + 1] if best > limit * 0.4 else cut


class Speaker:
    def __init__(self):
        self.engine = "windows"
        self.problem = ""
        self.last_error = ""
        self._lock = threading.RLock()
        self._gen = 0                     # goes up on every stop(), so an old reply stops by itself
        self._thread = None
        self._thread_gen = -1
        self._futures = []
        self._files = []
        self._mixer = None
        self._edge = None
        self.first_play = None            # time.time() when the first sound of the current reply started
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=6)
        if USE_NEURAL:
            try:
                import edge_tts
                import pygame
                pygame.mixer.init()
                self._edge, self._mixer = edge_tts, pygame.mixer
                self.engine = "neural"
            except Exception as e:
                self.problem = "%s: %s" % (type(e).__name__, str(e)[:80])

    def _synth(self, text):
        voice = VOICE_HI if re.search(r"[\u0900-\u097F]", text) else VOICE_EN
        last = None
        for attempt in range(TRIES):                      # a short internet hiccup must not change the voice
            fd, path = tempfile.mkstemp(suffix=".mp3", prefix="doit_")
            os.close(fd)

            async def go():
                await asyncio.wait_for(
                    self._edge.Communicate(text, voice, rate=SPEED).save(path), timeout=TIMEOUT)

            try:
                asyncio.run(go())
                if os.path.getsize(path) < 500:
                    raise RuntimeError("empty audio")
                return path
            except Exception as e:
                last = e
                try:
                    os.remove(path)
                except OSError:
                    pass
        raise last

    def _player(self, gen, chunks, futures):
        """Plays the pieces one after another. All pieces are prepared at the same time in the
        background, so while piece 1 is playing the next ones are already ready."""
        for i, f in enumerate(futures):
            if gen != self._gen:
                return
            try:
                path = f.result(timeout=TIMEOUT * TRIES + 5)
            except Exception as e:                        # offline? say the rest with the Windows voice
                if gen != self._gen:
                    return
                self.last_error = "%s: %s" % (type(e).__name__, str(e)[:80])
                if self.first_play is None:
                    self.first_play = time.time()
                actions.speak(" ".join(chunks[i:]))
                while gen == self._gen and actions._tts["p"] is not None and actions._tts["p"].poll() is None:
                    time.sleep(0.03)
                return
            with self._lock:
                if gen != self._gen:
                    self._remove(path)
                    return
                try:
                    self._mixer.music.load(path)
                    self._mixer.music.play()
                    if self.first_play is None:
                        self.first_play = time.time()
                except Exception as e:
                    self.last_error = "%s: %s" % (type(e).__name__, str(e)[:80])
                    self._remove(path)
                    continue
                self._files.append(path)
            while gen == self._gen and self._mixer.music.get_busy():
                time.sleep(0.02)
            if gen != self._gen:
                return
            with self._lock:
                if gen == self._gen:
                    try:
                        self._mixer.music.unload()
                    except Exception:
                        pass
                    self._remove(path)

    def _remove(self, path):
        try:
            os.remove(path)
        except OSError:
            pass
        if path in self._files:
            self._files.remove(path)

    def speak(self, text):
        """Starts talking at once and returns (does not wait for the voice to finish)."""
        text = shorten(clean_for_speech(text))
        if not text:
            return False
        self.stop()
        self.first_play = None
        if self.engine == "neural":
            chunks = split_chunks(text)
            with self._lock:
                gen = self._gen
                futures = [self._pool.submit(self._synth, c) for c in chunks]   # all pieces at once
                self._futures = futures
                self._thread_gen = gen
                self._thread = threading.Thread(target=self._player, args=(gen, chunks, futures),
                                                daemon=True)
                self._thread.start()
            return True
        self.first_play = time.time()
        actions.speak(text)
        return True

    def is_playing(self):
        t = self._thread
        if t is not None and t.is_alive() and self._thread_gen == self._gen:   # false at once after stop()
            return True
        p = actions._tts["p"]
        return p is not None and p.poll() is None

    def stop(self):
        with self._lock:
            self._gen += 1                                # tells an older reply to stop
            for f in self._futures:
                f.cancel()
            self._futures = []
            if self.engine == "neural":
                try:
                    self._mixer.music.stop()
                    self._mixer.music.unload()
                except Exception:
                    pass
                for path in list(self._files):
                    self._remove(path)
        actions.stop_speaking()

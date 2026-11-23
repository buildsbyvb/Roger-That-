"""
Do It - Step 8: Voice Activity Detection (VAD)

Listener.listen() waits for you to speak, records, and returns the audio ONLY
after you have finished. Silence, keyboard clicks, fans and background noise are
thrown away, so Whisper is never run on them (this prevents false activations).

How it decides (two layers):
  1. Volume gate: the sound must be louder than the room's noise level
     (measured at start-up and updated all the time) for ~0.12 s.
  2. Silero VAD (a small AI model that comes inside faster-whisper, nothing extra to
     install) checks that it is really a HUMAN VOICE, and finds the exact end of
     your sentence. If Silero is not available, only the volume gate is used.

Listener.poll_barge_in() is used while the assistant is talking: it returns True
when you start speaking, so the voice can be stopped (interruption).
"""
import collections
import queue
import time

import numpy as np

from wake_listen import BLOCK, RATE, audio_q, clear_queue

# ---------------- Settings you can change ----------------
MIN_VOLUME = 0.003       # quietest sound that can count as speech (was 0.010: you had to shout)
NOISE_MULT = 2.5         # speech must be this many times louder than the room noise
                         # (the Silero voice check below still ignores noise that is not a voice)
AUTO_GAIN = True         # makes quiet speech louder before it goes to the speech model
TARGET_PEAK = 0.7        # how loud the recording is made
MAX_GAIN = 30.0          # never boost more than this many times
START_BLOCKS = 3         # 3 x 30 ms = 0.09 s of loud sound starts a recording
END_SILENCE = 0.55       # seconds of silence that end your sentence (0.45 cut some sentences in half = mishearing)
MIN_SPEECH = 0.35        # less real speech than this = ignored (a click or a cough is not a command)
MAX_SECONDS = 15         # longest sentence
PRE_ROLL_BLOCKS = 16     # about 0.5 s of sound kept from BEFORE you started
CHECK_EVERY = 0.25       # how often the VAD model checks the recording
BARGE_MULT = 1.5         # to interrupt, you must be this many times louder than the speech threshold (normal talking is enough)
BARGE_MIN = 0.006        # never react to anything quieter than this
BARGE_BLOCKS = 5         # 5 x 30 ms = 0.15 s of your voice stops her (lower = faster, higher = fewer false stops)
ECHO_MULT = 2.0          # you must also be this many times louder than HER OWN voice heard by the microphone
                         # (this is what makes it work with laptop speakers; with headphones it does not matter)
ECHO_DECAY = 0.995       # how slowly the remembered level of her own voice fades
BARGE_LEARN = 0.5        # seconds, right after her voice starts, used only to learn how loud she sounds in the mic
BARGE_PRE_BLOCKS = 10    # about 0.3 s of sound kept from just BEFORE you interrupted, so the first word is not lost
# ---------------------------------------------------------

try:
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    _OPTS = VadOptions(threshold=0.5, min_speech_duration_ms=200,
                       min_silence_duration_ms=250, speech_pad_ms=100)
    HAVE_SILERO = True
except Exception:
    HAVE_SILERO = False
    _OPTS = None


def boost(audio):
    """Quiet speech made louder (a gentle automatic volume), so you do not have to shout."""
    if not AUTO_GAIN or len(audio) == 0:
        return audio
    peak = float(np.max(np.abs(audio)))
    if peak < 1e-4:
        return audio
    gain = min(MAX_GAIN, TARGET_PEAK / peak)
    return (audio * gain).clip(-1.0, 1.0).astype(np.float32) if gain > 1.0 else audio


def rms(block):
    return float(np.sqrt(np.mean(block ** 2)))


class Listener:
    def __init__(self):
        self.floor = 0.004          # room noise level (rms)
        self.carry = []             # blocks kept from an interruption
        self.vad_ok = HAVE_SILERO
        self._bb = []               # loud blocks seen while the assistant talks
        self._bpre = collections.deque(maxlen=BARGE_PRE_BLOCKS + BARGE_BLOCKS)
        self._est = self.floor      # how loud her own voice is in the microphone
        self._t_reset = time.time()
        self._sound_started = None

    # ---- helpers ----
    def threshold(self):
        return max(MIN_VOLUME, self.floor * NOISE_MULT)

    def _get(self, timeout=0.2):
        if self.carry:
            return self.carry.pop(0)
        return audio_q.get(timeout=timeout)

    def speech_spans(self, audio):
        """[(start, end), ...] in samples where a human voice is heard, or None if no VAD model."""
        if not self.vad_ok:
            return None
        try:
            spans = get_speech_timestamps(audio, _OPTS)
            return [(int(s["start"]), int(s["end"])) for s in spans]
        except Exception:
            self.vad_ok = False      # model problem: use the volume gate only
            return None

    def calibrate(self, seconds=1.0):
        """Measures the room noise. Stay quiet for a second."""
        vols = []
        end = time.time() + seconds
        while time.time() < end:
            try:
                vols.append(rms(self._get(0.1)))
            except queue.Empty:
                continue
        if vols:
            self.floor = float(min(0.02, max(0.001, np.percentile(vols, 30))))

    # ---- deciding if a recording is finished ----
    def _judge(self, voiced, silent_blocks):
        """Returns ('continue'|'done'|'noise', audio_or_None)."""
        audio = np.concatenate(voiced)
        seconds = len(audio) / RATE
        silent_sec = silent_blocks * BLOCK / RATE
        spans = self.speech_spans(audio)
        if spans is not None:
            if not spans:
                if seconds > 1.2 or silent_sec >= 0.5:
                    return "noise", audio
                return "continue", None
            last_end = spans[-1][1]
            trailing = (len(audio) - last_end) / RATE
            speech_len = sum(e - s for s, e in spans) / RATE
            if trailing >= END_SILENCE or seconds >= MAX_SECONDS:
                if speech_len < MIN_SPEECH:
                    return "noise", audio
                cut = min(len(audio), last_end + int(0.25 * RATE))
                return "done", boost(audio[:cut].astype(np.float32))
            return "continue", None
        # volume gate only
        if silent_sec >= END_SILENCE or seconds >= MAX_SECONDS:
            if seconds - silent_sec < MIN_SPEECH:
                return "noise", audio
            return "done", boost(audio.astype(np.float32))
        return "continue", None

    # ---- the main call ----
    def listen(self, wait_seconds=None, ignore_while=None, on_barge_in=None, sound_started=None):
        """Waits for a full sentence. Returns the audio, or None if wait_seconds passed
        with nobody speaking. ignore_while: a function; while it returns True (the
        assistant is talking) everything heard is ignored, except that if you speak loudly
        on_barge_in() is called (it stops the assistant's voice) and the recording starts."""
        pre = collections.deque(maxlen=PRE_ROLL_BLOCKS)
        voiced, speaking, loud, silent = [], False, 0, 0
        t_wait = time.time()
        t_check = 0.0
        gated = False
        armed = False
        while True:
            try:
                block = self._get(0.2)
            except queue.Empty:
                if wait_seconds and not speaking and time.time() - t_wait > wait_seconds:
                    return None
                continue

            if ignore_while is not None and ignore_while():      # assistant is talking
                pre.clear()
                voiced, speaking, loud, silent = [], False, 0, 0
                if on_barge_in is not None:
                    if not armed:
                        self.barge_reset(sound_started)          # a new reply started: learn how loud she is
                        armed = True
                    if self._barge_check(block):
                        on_barge_in()                            # you interrupted: stop its voice
                        gated, armed = False, False              # and start listening to you
                    else:
                        gated = True
                else:
                    gated = True
                continue
            armed = False
            if gated:                                            # it just stopped talking
                gated = False
                clear_queue()
                self.carry.clear()
                continue

            vol = rms(block)
            thr = self.threshold()
            if not speaking:
                if vol < thr:                                    # learn the room noise slowly
                    self.floor = min(0.02, 0.97 * self.floor + 0.03 * vol)
                pre.append(block)
                loud = loud + 1 if vol > thr else 0
                if loud >= START_BLOCKS:
                    speaking, voiced, silent = True, list(pre), 0
                    t_check = time.time()
                elif wait_seconds and time.time() - t_wait > wait_seconds:
                    return None
            else:
                voiced.append(block)
                silent = 0 if vol > thr else silent + 1
                if time.time() - t_check >= CHECK_EVERY:
                    t_check = time.time()
                    verdict, audio = self._judge(voiced, silent)
                    if verdict == "done":
                        return audio
                    if verdict == "noise":                       # not a voice: forget it
                        self.floor = min(0.02, max(self.floor, rms(audio) * 0.5))
                        pre.clear()
                        voiced, speaking, loud, silent = [], False, 0, 0

    # ---- interruption while the assistant talks ----
    def barge_reset(self, sound_started=None):
        """Call when the assistant starts a reply. sound_started: a function that returns the time her
        first sound began (or None while it is still being prepared)."""
        self._bb = []
        self._bpre.clear()
        self._est = self.floor
        self._t_reset = time.time()
        self._sound_started = sound_started

    def _learning(self):
        """True during the first moments of her voice: only learns how loud she is, never interrupts."""
        now = time.time()
        if self._sound_started is None:
            return now - self._t_reset < BARGE_LEARN
        t = self._sound_started()
        return t is not None and now < t + BARGE_LEARN

    def _barge_check(self, b):
        """Looks at ONE block. True as soon as you start talking over her."""
        v = rms(b)
        self._bpre.append(b)
        if self._learning():
            self._est = max(v, self._est * ECHO_DECAY)
            self._bb = []
            return False
        thr = max(BARGE_MIN, self.threshold() * BARGE_MULT, self._est * ECHO_MULT)
        if v > thr:
            self._bb.append(b)                       # not added to her own-voice level
            if len(self._bb) >= BARGE_BLOCKS:
                self.carry = list(self._bpre) + self.carry   # keep your first word for the next listen()
                self._bb = []
                self._bpre.clear()
                return True
        else:
            self._bb = []
            self._est = max(v, self._est * ECHO_DECAY)
        return False

    def poll_barge_in(self, sound_started=None):
        """Call while the assistant talks. True when you start speaking."""
        while True:
            try:
                b = audio_q.get_nowait()
            except queue.Empty:
                return False
            if self._barge_check(b):
                return True

"""Voice activity detection and turn endpointing, ported from the Corx engine (ADR-037).

Source: the owner's Corx repository (`D:\\Projects\\Ai\\Corx`, commit bba38fa, 2026-10-04): `vad.py`
(the Silero wrapper with a 280 ms end-of-speech silence) and `orchestrator.py` (`PreRollBuffer`,
`process_stream`, and the pause-driven turn splitting). Nothing from the ordering side of that
repository (menu, pricing, POS, telephony, recordings, keys) is used.

What it does
------------
Audio arrives as frames of 16 kHz mono 16-bit PCM. A *VAD* turns frames into two events,
`speech_start` and `speech_end`. `speech_end` fires once the speaker has been silent for
`silence_ms` (280 ms by default: snappy enough to feel immediate, long enough not to cut a
sentence at a breath). The `TurnSegmenter` builds turns from those events:

* the audio just *before* `speech_start` (pre-roll, 300 ms) is kept, because a VAD only notices
  speech after a few windows have been scored; without it the first syllable is lost;
* a pause longer than `silence_ms` closes the turn; what the person says next is a new turn marked
  `follow_up=True` when it starts within `follow_up_window_ms` of the previous one ("large..."
  [pause] "...actually medium"). A shorter pause stays inside one turn;
* a turn that is still open when the stream ends is closed with `ended_by="eof"`.

Two VAD backends share one interface:

* `EnergyVad` needs nothing but the standard library. It is the CI backend (deterministic on
  fixture clips) and the fallback when Silero is not installed.
* `SileroVad` is the Corx wrapper around the Silero model (MIT, needs `silero-vad`, which pulls in
  torch, so it is an optional extra and is imported only when used).

Everything here is pure and synchronous: no microphone, no threads, no model downloads.
"""

from __future__ import annotations

import math
from array import array
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Protocol

SAMPLE_RATE = 16_000
FRAME_MS = 20
BYTES_PER_SAMPLE = 2
DEFAULT_SILENCE_MS = 280
DEFAULT_PREROLL_MS = 300
DEFAULT_FOLLOW_UP_WINDOW_MS = 8_000

SPEECH_START = "speech_start"
SPEECH_END = "speech_end"


class VadUnavailable(RuntimeError):
    """The requested VAD backend is not installed."""


@dataclass(frozen=True)
class VadConfig:
    # Consecutive silence that ends a turn. Lower is snappier; higher cuts fewer sentences at a
    # breath. 250-300 ms is the Corx starting point for conversational speech.
    silence_ms: int = DEFAULT_SILENCE_MS
    threshold: float = 0.5  # Silero speech probability


class FrameVad(Protocol):
    """Turns audio frames into `speech_start` / `speech_end` events."""

    #: How long after the real start of speech `speech_start` is reported, in ms. The segmenter
    #: uses it to date the start of speech; pre-roll makes up for the lost audio.
    start_lag_ms: int

    def process_frame(self, frame: bytes) -> str | None: ...

    def flush(self) -> str | None: ...

    def reset(self) -> None: ...


def frame_ms(frame: bytes) -> float:
    return len(frame) / BYTES_PER_SAMPLE / SAMPLE_RATE * 1000.0


class EnergyVad:
    """A dependency-free VAD: frame loudness against a threshold, with the same silence rule."""

    def __init__(
        self,
        config: VadConfig | None = None,
        *,
        threshold_dbfs: float = -42.0,
        min_speech_ms: int = 60,
    ) -> None:
        self.config = config or VadConfig()
        self._threshold_dbfs = threshold_dbfs
        self._min_speech_ms = min_speech_ms
        self.start_lag_ms = min_speech_ms
        self._in_speech = False
        self._voiced_run = 0.0
        self._silent_run = 0.0

    @staticmethod
    def level_dbfs(frame: bytes) -> float:
        samples = array("h")
        samples.frombytes(frame[: len(frame) - len(frame) % BYTES_PER_SAMPLE])
        if not samples:
            return -120.0
        mean_square = sum(s * s for s in samples) / len(samples)
        return 20.0 * math.log10(max(math.sqrt(mean_square), 1.0) / 32768.0)

    def process_frame(self, frame: bytes) -> str | None:
        duration = frame_ms(frame)
        voiced = self.level_dbfs(frame) >= self._threshold_dbfs
        if not self._in_speech:
            self._voiced_run = self._voiced_run + duration if voiced else 0.0
            if self._voiced_run >= self._min_speech_ms:
                self._in_speech = True
                self._silent_run = 0.0
                return SPEECH_START
            return None
        if voiced:
            self._silent_run = 0.0
            return None
        self._silent_run += duration
        if self._silent_run >= self.config.silence_ms:
            self._in_speech = False
            self._voiced_run = 0.0
            return SPEECH_END
        return None

    def flush(self) -> str | None:
        return None

    def reset(self) -> None:
        self._in_speech = False
        self._voiced_run = 0.0
        self._silent_run = 0.0


class SileroVad:
    """The Corx `StreamingVAD`: Silero VAD over 512-sample windows, CPU only.

    Requires `silero-vad` (and numpy). Frames of any size are accepted and buffered into the
    windows Silero needs.
    """

    WINDOW_SAMPLES = 512  # Silero's inference window at 16 kHz (32 ms)

    def __init__(self, config: VadConfig | None = None) -> None:
        try:
            import numpy as np
            from silero_vad import VADIterator, load_silero_vad
        except ImportError as exc:  # pragma: no cover - exercised only where the extra is absent
            raise VadUnavailable(
                "SileroVad needs the optional 'vad' extra (silero-vad, numpy)"
            ) from exc
        self.config = config or VadConfig()
        self._np: Any = np
        self._model = load_silero_vad(onnx=True)
        self._iterator = VADIterator(
            self._model,
            sampling_rate=SAMPLE_RATE,
            threshold=self.config.threshold,
            min_silence_duration_ms=self.config.silence_ms,
        )
        self.start_lag_ms = 64
        self._in_speech = False
        self._buffer = np.zeros(0, dtype=np.float32)
        self._pending: list[str] = []

    def _run_windows(self) -> None:
        while len(self._buffer) >= self.WINDOW_SAMPLES:
            window = self._buffer[: self.WINDOW_SAMPLES]
            self._buffer = self._buffer[self.WINDOW_SAMPLES :]
            result = self._iterator(window, return_seconds=False)
            if result is None:
                continue
            if "start" in result and not self._in_speech:
                self._in_speech = True
                self._pending.append(SPEECH_START)
            elif "end" in result and self._in_speech:
                self._in_speech = False
                self._pending.append(SPEECH_END)

    def process_frame(self, frame: bytes) -> str | None:
        np = self._np
        audio = np.frombuffer(frame, dtype=np.int16).astype(np.float32) / 32768.0
        self._buffer = np.concatenate([self._buffer, audio])
        self._run_windows()
        return self._pending.pop(0) if self._pending else None

    def flush(self) -> str | None:
        np = self._np
        if len(self._buffer):
            pad = self.WINDOW_SAMPLES - len(self._buffer)
            self._buffer = np.concatenate([self._buffer, np.zeros(pad, dtype=np.float32)])
            self._run_windows()
        return self._pending.pop(0) if self._pending else None

    def reset(self) -> None:
        self._iterator.reset_states()
        self._in_speech = False
        self._buffer = self._np.zeros(0, dtype=self._np.float32)
        self._pending.clear()


class PreRollBuffer:
    """The last `preroll_ms` of audio before speech was noticed (Corx `PreRollBuffer`)."""

    def __init__(self, preroll_ms: int = DEFAULT_PREROLL_MS, frame_ms_: int = FRAME_MS) -> None:
        self._frames: deque[bytes] = deque(maxlen=max(1, -(-preroll_ms // frame_ms_)))

    def push(self, frame: bytes) -> None:
        self._frames.append(frame)

    def drain(self) -> list[bytes]:
        frames = list(self._frames)
        self._frames.clear()
        return frames


@dataclass(frozen=True)
class SpeechTurn:
    """One utterance, as the endpointer closed it. Times are milliseconds from the stream start."""

    index: int
    audio: bytes
    #: When speech began (the pre-roll before it is part of `audio`).
    start_ms: int
    #: When the VAD closed the turn: `silence_ms` after the speaker stopped.
    end_ms: int
    #: Silence between the previous turn closing and this one starting; None for the first turn.
    gap_ms: int | None
    #: True when this turn started soon after the previous one closed: a pause, not a new topic.
    follow_up: bool
    #: "vad" when the silence rule closed it, "eof" when the stream ended mid-speech.
    ended_by: str

    @property
    def duration_ms(self) -> int:
        return round(len(self.audio) / BYTES_PER_SAMPLE / SAMPLE_RATE * 1000)


class TurnSegmenter:
    """Frames in, finished `SpeechTurn`s out."""

    def __init__(
        self,
        vad: FrameVad,
        *,
        preroll_ms: int = DEFAULT_PREROLL_MS,
        follow_up_window_ms: int = DEFAULT_FOLLOW_UP_WINDOW_MS,
    ) -> None:
        self._vad = vad
        self._preroll = PreRollBuffer(preroll_ms)
        self._follow_up_window_ms = follow_up_window_ms
        self._now_ms = 0.0
        self._in_speech = False
        self._frames: list[bytes] = []
        self._start_ms = 0
        self._index = 0
        self._last_end_ms: int | None = None

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    def feed(self, frame: bytes) -> list[SpeechTurn]:
        self._now_ms += frame_ms(frame)
        event = self._vad.process_frame(frame)
        return self._handle(frame, event)

    def finish(self) -> list[SpeechTurn]:
        """The stream ended. A turn still open is closed as `eof`."""
        turns: list[SpeechTurn] = []
        event = self._vad.flush()
        if event is not None:
            turns.extend(self._handle(b"", event))
        if self._in_speech:
            turns.append(self._close("eof"))
        return turns

    def reset(self) -> None:
        self._vad.reset()
        self._preroll = PreRollBuffer()
        self._in_speech = False
        self._frames = []

    def _handle(self, frame: bytes, event: str | None) -> list[SpeechTurn]:
        if not self._in_speech:
            if frame:
                self._preroll.push(frame)
            if event == SPEECH_START:
                self._in_speech = True
                self._frames = self._preroll.drain()
                self._start_ms = max(0, round(self._now_ms) - self._vad.start_lag_ms)
            return []
        if frame:
            self._frames.append(frame)
        if event == SPEECH_END:
            return [self._close("vad")]
        return []

    def _close(self, ended_by: str) -> SpeechTurn:
        end_ms = round(self._now_ms)
        gap = None if self._last_end_ms is None else max(0, self._start_ms - self._last_end_ms)
        turn = SpeechTurn(
            index=self._index,
            audio=b"".join(self._frames),
            start_ms=self._start_ms,
            end_ms=end_ms,
            gap_ms=gap,
            follow_up=gap is not None and gap <= self._follow_up_window_ms,
            ended_by=ended_by,
        )
        self._index += 1
        self._last_end_ms = end_ms
        self._in_speech = False
        self._frames = []
        if ended_by == "eof":
            self._vad.reset()
        return turn


def frames_of(pcm: bytes, frame_ms_: int = FRAME_MS) -> Iterator[bytes]:
    """Cut PCM into whole frames (a short last frame is kept)."""
    size = SAMPLE_RATE * frame_ms_ // 1000 * BYTES_PER_SAMPLE
    for offset in range(0, len(pcm), size):
        yield pcm[offset : offset + size]


def segment(
    frames: Iterable[bytes],
    vad: FrameVad,
    *,
    preroll_ms: int = DEFAULT_PREROLL_MS,
    follow_up_window_ms: int = DEFAULT_FOLLOW_UP_WINDOW_MS,
) -> list[SpeechTurn]:
    """All the turns in a recorded clip. Used on fixture clips and by the Silero check."""
    segmenter = TurnSegmenter(vad, preroll_ms=preroll_ms, follow_up_window_ms=follow_up_window_ms)
    turns: list[SpeechTurn] = []
    for frame in frames:
        turns.extend(segmenter.feed(frame))
    turns.extend(segmenter.finish())
    return turns

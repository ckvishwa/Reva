"""B1.2/B1.3: audio in -> endpointing/PTT -> STT -> router/assistant -> TTS, on fakes."""

from __future__ import annotations

import asyncio
import logging
import math
import wave
from array import array
from datetime import UTC, datetime
from pathlib import Path

import pytest

from reva_core.language.dialogue import DialogueTracker, MemoryDialogueStore
from reva_core.language.router import IntentRouter
from reva_core.models.stt import TranscriptionInput, TranscriptionResult
from reva_core.models.tts import SynthesizedAudio
from reva_core.session.coordinator import DeadlineConfig, SessionCoordinator
from reva_core.session.events import SessionEventKind
from reva_core.session.pipeline import PipelineConfig, TurnPipeline
from reva_core.session.state import SessionState
from reva_core.session.turn_log import TurnRecorder
from reva_core.shared.errors import ProviderError, ProviderErrorKind
from reva_core.voice.endpointing import SAMPLE_RATE

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def tone(ms: int, amplitude: float = 0.3) -> bytes:
    count = SAMPLE_RATE * ms // 1000
    return array(
        "h",
        (
            int(32767 * amplitude * math.sin(2 * math.pi * 220 * i / SAMPLE_RATE))
            for i in range(count)
        ),
    ).tobytes()


def silence(ms: int) -> bytes:
    return bytes(SAMPLE_RATE * ms // 1000 * 2)


class FakeSTT:
    def __init__(self, *texts: str | Exception) -> None:
        self.texts = list(texts)
        self.paths: list[Path] = []
        self.existed_during_call: list[bool] = []
        self.delay = 0.0

    async def transcribe(self, audio: TranscriptionInput) -> TranscriptionResult:
        self.paths.append(audio.path)
        self.existed_during_call.append(audio.path.exists())
        if self.delay:
            await asyncio.sleep(self.delay)
        item = self.texts.pop(0)
        if isinstance(item, Exception):
            raise item
        return TranscriptionResult(text=item, language="en", duration_ms=1000, provider="fake")


class FakeTTS:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.spoken: list[str] = []
        self.fail = False
        self.delay = 0.0

    async def synthesize(self, text: str, language: str) -> SynthesizedAudio:
        self.spoken.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ProviderError(ProviderErrorKind.UNAVAILABLE, "down")
        path = self.directory / f"tts-{len(self.spoken)}.wav"
        with wave.open(str(path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(24000)
            handle.writeframes(b"\x00\x00" * 2400)
        return SynthesizedAudio(
            path=path, sample_rate=24000, duration_ms=100, provider="fake", language="en"
        )


class Rig:
    def __init__(self, tmp_path: Path, *stt_texts: str | Exception, respond=None, tts=True) -> None:
        self.tmp = tmp_path
        self.stt = FakeSTT(*stt_texts)
        self.tts = FakeTTS(tmp_path) if tts else None
        self.replies: list[str] = []
        self.asked: list[str] = []

        async def default_respond(text: str, correlation_id: str) -> str:
            self.asked.append(text)
            return "I think so."

        coordinator = SessionCoordinator(
            deadlines=DeadlineConfig(stt=2.0, model=2.0, tool=2.0, tts=2.0),
            ack_delay_seconds=30.0,
        )
        self.session = coordinator.open("device-0001")
        dialogue = DialogueTracker("device-0001", MemoryDialogueStore(), clock=lambda: NOW)
        self.recorder = TurnRecorder(tmp_path / "turns")
        self.pipeline = TurnPipeline(
            self.session,
            stt=self.stt,
            tts=self.tts,
            respond=respond or default_respond,
            router=IntentRouter(dialogue),
            recorder=self.recorder,
            scratch_dir=tmp_path,
            config=PipelineConfig(),
            now=lambda: NOW,
        )
        self.sub = self.session.subscribe()

    async def listening(self) -> None:
        await self.session.start()
        await self.session.capture_opened()

    async def talk(self, pcm: bytes | None = None) -> None:
        """Push-to-talk one utterance and let the turn finish up to the reply."""
        await self.pipeline.on_ptt_down()
        for offset in range(0, len(pcm or tone(600)), 6400):
            await self.pipeline.on_audio((pcm or tone(600))[offset : offset + 6400])
        await self.pipeline.on_ptt_up()
        await self.pipeline.wait_idle()


async def collect(rig: Rig) -> list:
    events = []
    while not rig.sub.empty():
        events.append(await rig.sub.get())
    return events


def kinds(events) -> list[str]:
    return [e.kind.value for e in events]


async def test_a_push_to_talk_turn_runs_stt_router_and_tts(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "add twelve dollars for lunch")
    await rig.listening()

    await rig.talk()
    events = await collect(rig)

    assert rig.session.state == SessionState.SPEAKING
    final = next(e for e in events if e.kind == SessionEventKind.TRANSCRIPT_FINAL)
    assert final.payload["text"] == "add twelve dollars for lunch"
    reply = next(e for e in events if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL)
    assert reply.payload == {
        "text": "Add $12.00 for lunch? Say yes to confirm.",
        "source": "template",
        "timings_ms": reply.payload["timings_ms"],
    }
    started = next(e for e in events if e.kind == SessionEventKind.TTS_STARTED)
    assert started.payload["audio_path"].startswith(f"/v1/voice/sessions/{rig.session.id}/audio/")
    assert rig.asked == []  # a rule turn never reaches the model
    assert rig.tts.spoken == ["Add $12.00 for lunch? Say yes to confirm."]


async def test_make_it_fifteen_in_a_second_turn_changes_the_same_draft(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "add twelve dollars for lunch", "make it fifteen")
    await rig.listening()
    await rig.talk()
    await rig.pipeline.on_playback_finished()

    await rig.talk()
    events = await collect(rig)

    texts = [e.payload["text"] for e in events if e.kind == SessionEventKind.ASSISTANT_TEXT_FINAL]
    assert texts == [
        "Add $12.00 for lunch? Say yes to confirm.",
        "Changed to $15.00 for lunch. Say yes to confirm.",
    ]


async def test_other_speech_goes_to_the_assistant_and_playback_returns_to_listening(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "is it going to rain")
    await rig.listening()

    await rig.talk()
    assert rig.asked == ["is it going to rain"]
    assert rig.session.state == SessionState.SPEAKING
    await rig.pipeline.on_playback_finished(rig.session.turn_epoch)

    assert rig.session.state == SessionState.LISTENING


async def test_the_temporary_wav_is_gone_after_the_turn_and_existed_during_it(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "what time is it")
    await rig.listening()

    await rig.talk()

    assert rig.stt.existed_during_call == [True]
    assert all(not p.exists() and not p.parent.exists() for p in rig.stt.paths)


async def test_the_wav_is_removed_even_when_stt_fails(tmp_path: Path) -> None:
    rig = Rig(tmp_path, ProviderError(ProviderErrorKind.UNAVAILABLE, "down"))
    await rig.listening()

    await rig.talk()
    events = await collect(rig)

    assert all(not p.exists() for p in rig.stt.paths)
    error = next(e for e in events if e.kind == SessionEventKind.ERROR)
    assert error.payload["code"] == "STT_UNAVAILABLE" and error.payload["recoverable"] is True
    assert rig.session.state == SessionState.LISTENING


async def test_an_empty_transcript_returns_to_listening_without_running_anything(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, ProviderError(ProviderErrorKind.INVALID_RESPONSE, "no transcript"))
    await rig.listening()

    await rig.talk()

    assert rig.session.state == SessionState.LISTENING
    assert rig.asked == [] and rig.tts.spoken == []


async def test_vad_endpointing_closes_a_turn_after_silence(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "open spotify")
    await rig.listening()

    audio = silence(200) + tone(700) + silence(500)
    for offset in range(0, len(audio), 3200):
        await rig.pipeline.on_audio(audio[offset : offset + 3200])
    await rig.pipeline.wait_idle()

    assert rig.stt.paths, "the turn should have reached STT"
    assert rig.session.state == SessionState.SPEAKING


async def test_silence_alone_never_reaches_stt(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "should not be used")
    await rig.listening()

    for _ in range(40):
        await rig.pipeline.on_audio(silence(100))
    await rig.pipeline.wait_idle()

    assert rig.stt.paths == [] and rig.session.state == SessionState.LISTENING


async def test_audio_before_listening_or_while_muted_is_ignored(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "x")
    await rig.pipeline.on_audio(tone(600))  # idle: nothing is listening
    await rig.listening()
    rig.pipeline.set_muted(True)
    await rig.pipeline.on_ptt_down()
    await rig.pipeline.on_audio(tone(600))
    await rig.pipeline.on_ptt_up()
    await rig.pipeline.wait_idle()

    assert rig.stt.paths == [] and rig.session.state == SessionState.LISTENING


@pytest.mark.parametrize(
    "chunk",
    [b"", bytes(1), bytes(SAMPLE_RATE * 2 + 2)],
    ids=["empty", "odd-length", "over-one-second"],
)
async def test_malformed_audio_chunks_are_refused_with_an_event(
    tmp_path: Path, chunk: bytes
) -> None:
    rig = Rig(tmp_path, "x")
    await rig.listening()

    await rig.pipeline.on_audio(chunk)
    events = await collect(rig)

    assert any(
        e.kind == SessionEventKind.ERROR and e.payload["code"] == "BAD_AUDIO" for e in events
    )


async def test_an_overlong_utterance_is_discarded_whole_not_transcribed(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "x")
    rig.pipeline._config = PipelineConfig(max_utterance_ms=1000)
    await rig.listening()

    await rig.pipeline.on_ptt_down()
    for _ in range(3):
        await rig.pipeline.on_audio(tone(600))
    await rig.pipeline.on_ptt_up()
    await rig.pipeline.wait_idle()
    events = await collect(rig)

    assert rig.stt.paths == []
    assert any(
        e.kind == SessionEventKind.ERROR and e.payload["code"] == "UTTERANCE_TOO_LONG"
        for e in events
    )
    assert rig.session.state == SessionState.LISTENING


async def test_a_tap_shorter_than_an_utterance_is_not_sent_to_stt(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "x")
    await rig.listening()

    await rig.talk(tone(100))

    assert rig.stt.paths == []


async def test_push_to_talk_during_the_reply_interrupts_it(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "add twelve dollars for lunch")
    await rig.listening()
    await rig.talk()
    assert rig.session.state == SessionState.SPEAKING
    epoch = rig.session.turn_epoch

    await rig.pipeline.on_ptt_down()

    assert rig.session.state == SessionState.LISTENING
    assert rig.session.turn_epoch == epoch + 1
    await rig.pipeline.on_ptt_up()


async def test_a_late_playback_report_from_an_older_epoch_is_ignored(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "add twelve dollars for lunch")
    await rig.listening()
    await rig.talk()
    stale = rig.session.turn_epoch - 1

    await rig.pipeline.on_playback_finished(stale)

    assert rig.session.state == SessionState.SPEAKING


async def test_a_barge_in_during_synthesis_drops_the_audio_and_deletes_the_file(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "what time is it")
    rig.tts.delay = 0.3
    await rig.listening()

    await rig.pipeline.on_ptt_down()
    await rig.pipeline.on_audio(tone(600))
    await rig.pipeline.on_ptt_up()
    for _ in range(100):
        if rig.session.state == SessionState.SPEAKING:
            break
        await asyncio.sleep(0.01)
    await rig.session.interrupt()
    await rig.pipeline.wait_idle()
    events = await collect(rig)

    assert not any(e.kind == SessionEventKind.TTS_STARTED for e in events)
    assert not list(tmp_path.glob("tts-*.wav"))


async def test_a_reply_with_no_voice_available_still_returns_to_listening(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "what time is it", tts=False)
    await rig.listening()

    await rig.talk()

    assert rig.session.state == SessionState.LISTENING


async def test_a_failing_synthesis_reports_a_recoverable_error(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "what time is it")
    rig.tts.fail = True
    await rig.listening()

    await rig.talk()
    events = await collect(rig)

    assert any(
        e.kind == SessionEventKind.ERROR and e.payload["code"] == "TTS_UNAVAILABLE" for e in events
    )
    assert rig.session.state == SessionState.LISTENING


async def test_an_assistant_failure_gets_the_apology_template_not_silence(tmp_path: Path) -> None:
    async def broken(text: str, correlation_id: str) -> str:
        raise RuntimeError("model down")

    rig = Rig(tmp_path, "what time is it", respond=broken)
    await rig.listening()

    await rig.talk()

    assert rig.tts.spoken == ["Sorry, I couldn't answer that."]
    rows = rig.recorder.read()
    assert rows[-1]["outcome"] == "model_failed"


async def test_turns_are_recorded_redacted_without_audio(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "my card is 4111 1111 1111 1111 and mail me at jo@example.com")
    await rig.listening()

    await rig.talk()
    await rig.pipeline.on_playback_finished()

    (row,) = rig.recorder.read()
    assert "4111" not in row["transcript"] and "example.com" not in row["transcript"]
    assert row["transcript"] == "my card is [number] and mail me at [email]"
    assert row["outcome"] == "ok" and row["route"] == "chat"
    assert "stt_ms" in row["timings_ms"]
    assert not any(tmp_path.joinpath("turns").glob("*.wav"))


async def test_raw_audio_never_reaches_the_logs(tmp_path: Path, caplog) -> None:
    rig = Rig(tmp_path, ProviderError(ProviderErrorKind.UNAVAILABLE, "down"), "next")
    await rig.listening()
    marker = tone(300, amplitude=0.31)

    with caplog.at_level(logging.DEBUG):
        await rig.talk(marker + tone(300))

    text = caplog.text
    assert repr(marker[:24]) not in text and "\\x" not in text


async def test_closing_the_pipeline_deletes_waiting_reply_audio(tmp_path: Path) -> None:
    rig = Rig(tmp_path, "what time is it")
    await rig.listening()
    await rig.talk()
    assert list(tmp_path.glob("tts-*.wav"))

    await rig.pipeline.close()

    assert not list(tmp_path.glob("tts-*.wav"))


async def test_endless_speech_without_a_pause_is_discarded_not_buffered_forever(
    tmp_path: Path,
) -> None:
    rig = Rig(tmp_path, "x")
    rig.pipeline._config = PipelineConfig(max_utterance_ms=1000)
    await rig.listening()

    for _ in range(10):
        await rig.pipeline.on_audio(tone(500))
    await rig.pipeline.wait_idle()
    events = await collect(rig)

    assert rig.stt.paths == []
    assert any(
        e.kind == SessionEventKind.ERROR and e.payload["code"] == "UTTERANCE_TOO_LONG"
        for e in events
    )
    assert rig.session.state == SessionState.LISTENING

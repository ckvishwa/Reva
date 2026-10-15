"""B1.7: cloud is opt-in, consent is per domain, failures fall back to local with a notice."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from reva_core.providers.cloud import (
    DEFAULT_OFF_DOMAINS,
    HOSTED_DOMAINS,
    AssistantReply,
    CloudReasoner,
    CloudSettings,
    CloudSettingsStore,
    CloudUnavailable,
    ConsentFilter,
    HybridResponder,
)
from reva_core.security.credential_store import InMemorySecretStore, SecretStoreError


class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if callable(self.outcome):
            return await self.outcome()
        return self.outcome


def reply_of(text: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class Rig:
    def __init__(
        self, tmp_path: Path, outcome: Any = None, *, key: str | None = "sk-ant-test-key-0123456789"
    ) -> None:
        self.store = CloudSettingsStore(tmp_path / "cloud_settings.json")
        self.secrets = InMemorySecretStore(key)
        self.messages = FakeMessages(outcome if outcome is not None else reply_of("Paris."))
        self.clients: list[tuple[str, float]] = []

        self.closed = 0

        async def close() -> None:
            self.closed += 1

        def factory(api_key: str, timeout: float) -> Any:
            self.clients.append((api_key, timeout))
            return SimpleNamespace(messages=self.messages, close=close)

        self.reasoner = CloudReasoner(
            self.store,
            self.secrets,
            model="claude-opus-5-5",
            timeout_seconds=0.5,
            client_factory=factory,
        )

    def turn_on(self, *domains: str) -> None:
        settings = self.store.load()
        settings.enabled = True
        for name in domains:
            settings.domains[name] = True
        self.store.save(settings)


# ------------------------------------------------------------------------ settings


def test_everything_is_off_by_default_and_the_sensitive_four_are_listed() -> None:
    settings = CloudSettings()

    assert settings.enabled is False
    assert all(settings.domains[name] is False for name in HOSTED_DOMAINS)
    assert set(DEFAULT_OFF_DOMAINS) == {"finance", "health", "memory", "personal"}
    assert not any(settings.allows(name) for name in HOSTED_DOMAINS)


def test_missing_corrupt_or_odd_settings_files_mean_everything_off(tmp_path: Path) -> None:
    path = tmp_path / "cloud_settings.json"
    store = CloudSettingsStore(path)
    assert store.load() == CloudSettings()

    for junk in ("{not json", "[]", '"on"', '{"enabled": "yes"}', '{"enabled": 1, "domains": []}'):
        path.write_text(junk, encoding="utf-8")
        loaded = store.load()
        assert loaded.enabled is False and not any(loaded.domains.values()), junk


def test_settings_round_trip_and_unknown_domains_are_ignored(tmp_path: Path) -> None:
    path = tmp_path / "cloud_settings.json"
    path.write_text(
        json.dumps({"enabled": True, "domains": {"coach": True, "finance": "true", "bank": True}}),
        encoding="utf-8",
    )
    store = CloudSettingsStore(path)

    loaded = store.load()

    assert loaded.enabled is True
    assert loaded.domains["coach"] is True
    assert loaded.domains["finance"] is False  # only a real true counts
    assert "bank" not in loaded.domains
    store.save(loaded)
    assert store.load() == loaded


def test_a_domain_is_allowed_only_when_cloud_and_that_domain_are_both_on() -> None:
    assert CloudSettings(enabled=True, domains={"coach": True}).allows("coach")
    assert not CloudSettings(enabled=False, domains={"coach": True}).allows("coach")
    assert not CloudSettings(enabled=True, domains={"coach": False}).allows("coach")


# ----------------------------------------------------------------- consent filter


def test_the_filter_drops_every_domain_whose_switch_is_off_and_unknown_keys() -> None:
    settings = CloudSettings(
        enabled=True, domains={**dict.fromkeys(HOSTED_DOMAINS, False), "coach": True}
    )
    context = {"coach": {"goal": "run"}, "finance": {"balance": 100}, "memory": ["x"], "mystery": 1}

    filtered = ConsentFilter(settings).apply(context)

    assert filtered.included == {"coach": {"goal": "run"}}
    assert set(filtered.omitted) == {"finance", "memory", "mystery"}


def test_with_cloud_off_the_filter_passes_nothing() -> None:
    settings = CloudSettings(enabled=False, domains=dict.fromkeys(HOSTED_DOMAINS, True))

    assert ConsentFilter(settings).apply({"coach": 1, "career": 2}).included == {}


# ---------------------------------------------------------------------- reasoner


async def test_off_means_no_client_is_ever_built(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    with pytest.raises(CloudUnavailable) as stopped:
        await rig.reasoner.reply("what is the capital of France")

    assert stopped.value.reason == "off"
    assert rig.clients == [] and rig.messages.calls == []  # nothing left the machine
    assert rig.reasoner.usable() is False


async def test_on_without_a_key_is_unusable_and_builds_no_client(tmp_path: Path) -> None:
    rig = Rig(tmp_path, key=None)
    rig.turn_on()

    with pytest.raises(CloudUnavailable) as stopped:
        await rig.reasoner.reply("hello")

    assert stopped.value.reason == "no_key" and rig.clients == []
    assert rig.reasoner.usable() is False


async def test_a_vault_that_fails_is_treated_as_no_key(tmp_path: Path) -> None:
    class Broken:
        def read(self) -> str:
            raise SecretStoreError("vault down")

    rig = Rig(tmp_path)
    rig.turn_on()
    rig.reasoner._secrets = Broken()  # type: ignore[assignment]

    assert rig.reasoner.usable() is False
    with pytest.raises(CloudUnavailable):
        await rig.reasoner.reply("hello")


async def test_a_reply_sends_only_the_transcript_and_a_fixed_instruction(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.turn_on()

    text = await rig.reasoner.reply("what is the capital of France")

    assert text == "Paris."
    (call,) = rig.messages.calls
    assert call["messages"] == [{"role": "user", "content": "what is the capital of France"}]
    assert "cannot open apps" in call["system"]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert rig.clients == [("sk-ant-test-key-0123456789", 0.5)]
    assert set(call) == {"model", "max_tokens", "system", "output_config", "messages"}


async def test_the_client_is_closed_after_success_and_after_failure(tmp_path: Path) -> None:
    ok = Rig(tmp_path)
    ok.turn_on()
    await ok.reasoner.reply("hi")
    bad = Rig(tmp_path, type("APIConnectionError", (Exception,), {})("x"))
    bad.turn_on()
    with pytest.raises(CloudUnavailable):
        await bad.reasoner.reply("hi")

    assert ok.closed == 1 and bad.closed == 1


async def test_domain_context_is_sent_only_for_domains_that_are_switched_on(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.turn_on("coach")
    context = {"coach": {"goal": "5k"}, "finance": {"balance": 12345}, "health": {"hr": 61}}

    await rig.reasoner.reply("how am I doing", context)

    (call,) = rig.messages.calls
    sent = call["messages"][0]["content"]
    assert "5k" in sent
    assert (
        "12345" not in sent and "61" not in sent and "finance" not in sent and "health" not in sent
    )


async def test_cloud_on_does_not_turn_the_sensitive_domains_on(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.turn_on()  # cloud on, no domain on

    await rig.reasoner.reply(
        "hi", {"finance": {"balance": 1}, "memory": ["secret"], "personal": "j"}
    )

    sent = rig.messages.calls[0]["messages"][0]["content"]
    assert sent == "hi"


@pytest.mark.parametrize(
    ("error_name", "reason"),
    [
        ("APITimeoutError", "timeout"),
        ("APIConnectionError", "unreachable"),
        ("AuthenticationError", "key_rejected"),
        ("PermissionDeniedError", "key_rejected"),
        ("RateLimitError", "rate_limited"),
        ("InternalServerError", "error"),
        ("BadRequestError", "error"),
        ("SomethingElse", "error"),
    ],
)
async def test_sdk_errors_become_fixed_reason_codes(
    tmp_path: Path, error_name: str, reason: str
) -> None:
    error = type(error_name, (Exception,), {})("secret details sk-ant-test-key-0123456789")
    rig = Rig(tmp_path, error)
    rig.turn_on()

    with pytest.raises(CloudUnavailable) as stopped:
        await rig.reasoner.reply("hi")

    assert stopped.value.reason == reason
    assert "sk-ant" not in str(stopped.value)


async def test_a_call_that_hangs_times_out(tmp_path: Path) -> None:
    async def hang() -> Any:
        await asyncio.sleep(30)

    rig = Rig(tmp_path, hang)
    rig.turn_on()

    with pytest.raises(CloudUnavailable) as stopped:
        await rig.reasoner.reply("hi")

    assert stopped.value.reason == "timeout"


async def test_refusals_and_empty_answers_are_not_passed_on(tmp_path: Path) -> None:
    refused = Rig(tmp_path, reply_of("", stop="refusal"))
    refused.turn_on()
    with pytest.raises(CloudUnavailable) as one:
        await refused.reasoner.reply("hi")
    empty = Rig(tmp_path, reply_of("   "))
    empty.turn_on()
    with pytest.raises(CloudUnavailable) as two:
        await empty.reasoner.reply("hi")

    assert one.value.reason == "refused" and two.value.reason == "empty"


# ------------------------------------------------------------------ hybrid responder


async def local(text: str, correlation_id: str) -> str:
    return f"local: {text}"


async def test_with_cloud_off_the_local_model_answers_with_no_notice(tmp_path: Path) -> None:
    rig = Rig(tmp_path)

    answer = await HybridResponder(local, rig.reasoner)("hi", "c1")

    assert answer == AssistantReply("local: hi", "local", None)
    assert rig.clients == []


async def test_with_cloud_on_the_cloud_answers(tmp_path: Path) -> None:
    rig = Rig(tmp_path)
    rig.turn_on()

    answer = await HybridResponder(local, rig.reasoner)("capital of France", "c1")

    assert answer == AssistantReply("Paris.", "cloud", None)


@pytest.mark.parametrize(
    ("error_name", "snippet"),
    [
        ("APITimeoutError", "too slow"),
        ("APIConnectionError", "couldn't reach"),
        ("AuthenticationError", "rejected"),
    ],
)
async def test_a_cloud_failure_falls_back_to_local_and_says_so(
    tmp_path: Path, error_name: str, snippet: str
) -> None:
    rig = Rig(tmp_path, type(error_name, (Exception,), {})("x"))
    rig.turn_on()

    answer = await HybridResponder(local, rig.reasoner)("hi", "c1")

    assert answer.text == "local: hi" and answer.provider == "local"
    assert answer.notice is not None and snippet in answer.notice


async def test_no_cloud_reasoner_at_all_is_just_local() -> None:
    assert await HybridResponder(local, None)("hi", "c1") == AssistantReply("local: hi")

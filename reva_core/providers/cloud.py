"""Opt-in hosted reasoning (Anthropic), consent per domain, and the fallback to local (B1.7).

What can leave this PC, and when:

* Nothing, unless the owner turned cloud on **and** a key is stored in Windows Credential Manager.
* When on, a *free-form question* (the final transcript of a turn the rule router did not handle) is
  sent to Anthropic, with a fixed short instruction. Audio, screens and memory are never sent.
* Domain data (Finance, Health, Memory, Personal, ...) is sent only if that domain's own switch is
  on. Those four default off, and so does every other domain: the filter below is what builds the
  request, so a domain with its switch off cannot be put into it by mistake.
* If the hosted model is slow, down or refuses, the turn is answered by the local model and the user
  is told ("notice"). A cloud failure never becomes silence and never becomes a made-up answer.

The hosted model only *replies with text*. It cannot propose or run an action here: actions come
from the rule router and, later, the deterministic policy broker.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reva_core.security.credential_store import SecretStore, SecretStoreError
from reva_core.shared.logging import get_logger

logger = get_logger("cloud")

KEY_ENTRY = "anthropic"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_TIMEOUT_SECONDS = 8.0
MAX_REPLY_TOKENS = 1024

HOSTED_DOMAINS = (
    "memory",
    "finance",
    "health",
    "coach",
    "career",
    "learn",
    "cyber",
    "personal",
)
DEFAULT_OFF_DOMAINS = ("finance", "health", "memory", "personal")  # PRD FR-DOM-006

DISCLOSURE: dict[str, Any] = {
    "sent_when_on": [
        "What you say in a free-form question (the text, after speech recognition)",
        "A short fixed instruction telling the model it is a voice assistant that cannot act",
        "Data from a domain only if that domain's own switch is on",
    ],
    "never_sent": [
        "Your voice or any audio",
        "Your screen",
        "Memory, Finance, Health or Personal data while their switches are off (they start off)",
        "Anything for commands REVA handles itself, such as adding an expense or opening an app",
    ],
    "provider": "Anthropic (api.anthropic.com)",
    "fallback": "If it is slow or unavailable REVA answers with the local model and says so.",
}

SYSTEM_PROMPT = (
    "You are REVA, a voice assistant. Reply in one to three short, plain spoken sentences with no "
    "markdown. You cannot open apps, change data or take any action; if asked to, say you can't "
    "do that from here. If you do not know, say so."
)


class CloudUnavailable(Exception):
    """The hosted model could not answer. `reason` is a fixed code, safe to show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class CloudSettings:
    enabled: bool = False
    domains: dict[str, bool] = field(default_factory=lambda: dict.fromkeys(HOSTED_DOMAINS, False))

    def allows(self, domain: str) -> bool:
        return self.enabled and self.domains.get(domain) is True


class CloudSettingsStore:
    """`cloud_settings.json` in the data directory. Any problem reading it means everything off."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def load(self) -> CloudSettings:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return CloudSettings()
            domains = dict.fromkeys(HOSTED_DOMAINS, False)
            saved = raw.get("domains")
            if isinstance(saved, dict):
                for name in HOSTED_DOMAINS:
                    domains[name] = saved.get(name) is True
            return CloudSettings(enabled=raw.get("enabled") is True, domains=domains)
        except (OSError, ValueError):
            return CloudSettings()

    def save(self, settings: CloudSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"enabled": settings.enabled, "domains": settings.domains}), encoding="utf-8"
        )
        os.replace(temporary, self._path)


@dataclass(frozen=True)
class FilteredContext:
    included: dict[str, Any]
    omitted: tuple[str, ...]


class ConsentFilter:
    """Keeps context only for domains that are switched on; drops everything else by name.

    A key that is not a known domain is dropped too: unclassified data does not leave.
    """

    def __init__(self, settings: CloudSettings) -> None:
        self._settings = settings

    def apply(self, context: Mapping[str, Any] | None) -> FilteredContext:
        included: dict[str, Any] = {}
        omitted: list[str] = []
        for name, value in (context or {}).items():
            if name in HOSTED_DOMAINS and self._settings.allows(name):
                included[name] = value
            else:
                omitted.append(name)
        return FilteredContext(included, tuple(omitted))


ClientFactory = Callable[[str, float], Any]


def _anthropic_client(api_key: str, timeout: float) -> Any:
    import anthropic

    return anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=0)


class CloudReasoner:
    def __init__(
        self,
        settings_store: CloudSettingsStore,
        secret_store: SecretStore,
        *,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        client_factory: ClientFactory = _anthropic_client,
    ) -> None:
        self._settings = settings_store
        self._secrets = secret_store
        self._model = model
        self._timeout = timeout_seconds
        self._client_factory = client_factory

    def usable(self) -> bool:
        """On, and a key is stored. Reads settings and the vault each time (they can change)."""
        if not self._settings.load().enabled:
            return False
        try:
            return bool(self._secrets.read())
        except SecretStoreError:
            return False

    async def reply(self, transcript: str, context: Mapping[str, Any] | None = None) -> str:
        settings = self._settings.load()
        if not settings.enabled:
            raise CloudUnavailable("off")
        try:
            key = self._secrets.read()
        except SecretStoreError as exc:
            raise CloudUnavailable("no_key") from exc
        if not key:
            raise CloudUnavailable("no_key")
        filtered = ConsentFilter(settings).apply(context)
        content = transcript
        if filtered.included:
            content += "\n\nContext the user allowed you to see:\n" + json.dumps(
                filtered.included, ensure_ascii=False
            )
        client = self._client_factory(key, self._timeout)
        try:
            response = await asyncio.wait_for(
                client.messages.create(
                    model=self._model,
                    max_tokens=MAX_REPLY_TOKENS,
                    system=SYSTEM_PROMPT,
                    output_config={"effort": "low"},
                    messages=[{"role": "user", "content": content}],
                ),
                timeout=self._timeout + 1.0,
            )
        except TimeoutError as exc:
            raise CloudUnavailable("timeout") from exc
        except Exception as exc:
            raise CloudUnavailable(_classify(exc)) from exc
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()  # one client per call: release its connection pool
                except Exception:
                    logger.debug("cloud client close failed", exc_info=True)
        if getattr(response, "stop_reason", None) == "refusal":
            raise CloudUnavailable("refused")
        text = "".join(
            block.text for block in getattr(response, "content", []) if block.type == "text"
        ).strip()
        if not text:
            raise CloudUnavailable("empty")
        return text


def _classify(exc: Exception) -> str:
    """Map an SDK error to a fixed reason code. The exception text is never kept."""
    name = type(exc).__name__
    if name == "APITimeoutError":
        return "timeout"
    if name in ("AuthenticationError", "PermissionDeniedError"):
        return "key_rejected"
    if name == "RateLimitError":
        return "rate_limited"
    if name == "APIConnectionError":
        return "unreachable"
    if name in ("APIStatusError", "InternalServerError", "BadRequestError", "NotFoundError"):
        return "error"
    return "error"


NOTICE_TEXT = {
    "timeout": "The cloud model was too slow, so I answered with the local model.",
    "unreachable": "I couldn't reach the cloud model, so I answered with the local model.",
    "key_rejected": "The cloud key was rejected, so I answered with the local model.",
    "rate_limited": "The cloud model is busy, so I answered with the local model.",
    "refused": "The cloud model declined that, so I answered with the local model.",
}
DEFAULT_NOTICE = "The cloud model isn't available, so I answered with the local model."


@dataclass(frozen=True)
class AssistantReply:
    text: str
    provider: str = "local"  # "local" or "cloud"
    notice: str | None = None


LocalResponder = Callable[[str, str], Awaitable[str]]


class HybridResponder:
    """Cloud first when it is on and usable; the local model otherwise or on any cloud failure."""

    def __init__(self, local: LocalResponder, cloud: CloudReasoner | None) -> None:
        self._local = local
        self._cloud = cloud

    async def __call__(self, transcript: str, correlation_id: str) -> AssistantReply:
        if self._cloud is not None and self._cloud.usable():
            try:
                return AssistantReply(await self._cloud.reply(transcript), "cloud")
            except CloudUnavailable as failure:
                logger.info("cloud reply unavailable: %s", failure.reason)
                notice = NOTICE_TEXT.get(failure.reason, DEFAULT_NOTICE)
                return AssistantReply(
                    await self._local(transcript, correlation_id), "local", notice
                )
        return AssistantReply(await self._local(transcript, correlation_id), "local")

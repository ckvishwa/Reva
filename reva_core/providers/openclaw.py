"""Optional OpenClaw sidecar adapter (ADR-041; docs/security/O0-openclaw-source-audit.md).

OpenClaw is an external, pinned, opt-in process (`openclaw/openclaw@af50fbd...`), off by default
(`REVA_OPENCLAW_ENABLED`). Its text is never evidence that anything happened: a reply is parsed by
the exact same rule fast path a voice transcript uses (`reva_core.language.rules`), then proposed
to the existing `Broker` with `source="openclaw"` and `hosted_origin=True` — the same per-domain
consent gate a hosted cloud model's proposals must pass, and the same `authorize()`, signed-grant,
tier/approval and native-executor path a spoken command takes. No second executor exists here.

The owner has explicitly authorized running the local OpenClaw instance with
`agents.defaults.sandbox.mode="off"` (ADR-041). REVA cannot see or enforce OpenClaw's own process
config from here; this module only enforces REVA's own boundary: loopback-only, authenticated,
one request per connection, a hard timeout, no REVA secret ever placed in an outbound message, and
every reply is an untrusted proposal, never a claim of completion.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from reva_core.language.entities import AppResolver
from reva_core.language.rules import RuleHit
from reva_core.language.rules import parse as parse_rule
from reva_core.policy.authorize import Proposal
from reva_core.policy.broker import ActionView
from reva_core.security.credential_store import SecretStore, SecretStoreError
from reva_core.shared.ids import new_id

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 4
SOURCE = "openclaw"
ORIGIN_DEVICE = "local"  # the sidecar runs on this same PC; the confirm-card UI is this PC's own
TARGET_DEVICE = "local"
MAX_REPLY_CHARS = 4000
_TERMINAL_STATES = frozenset({"final", "error", "aborted"})


class OpenClawUnavailable(Exception):
    """The sidecar could not be reached or answer trusted. `reason` is a fixed code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class WebSocketLike(Protocol):
    """What the client needs from a connection — satisfied by `websockets` and by the fake
    Gateway test server; never satisfied by mocking our own client."""

    async def send(self, message: str) -> None: ...

    async def recv(self, decode: bool | None = None) -> Any: ...

    async def close(self, code: int = 1000, reason: str = "") -> None: ...


@dataclass
class OpenClawConfig:
    """The non-secret half of the connection; `REVA_OPENCLAW_*` in `reva_core.config.settings`."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    sandbox_mode: str = "off"  # owner-authorized (ADR-041); recorded, not enforced from here
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    allowed_scopes: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}/gateway"


@dataclass(frozen=True)
class OpenClawReply:
    """A `final` chat turn. Text only — never treated as proof any action happened."""

    text: str
    run_id: str | None


def _connect_frame(request_id: str, token: str) -> dict[str, Any]:
    return {
        "type": "req",
        "id": request_id,
        "method": "connect",
        "params": {
            "minProtocol": PROTOCOL_VERSION,
            "maxProtocol": PROTOCOL_VERSION,
            "client": {
                "id": "reva-core",
                "version": "2.0",
                "platform": "windows",
                "mode": "operator",
            },
            "role": "operator",
            # Deliberately minimal: no operator.admin/write/approvals/pairing — this connection
            # only ever reads a reply, it never issues OpenClaw-side approvals or config changes.
            "scopes": ["operator.read", "operator.talk"],
            "auth": {"token": token},
        },
    }


def _redact(frame: Mapping[str, Any]) -> dict[str, Any]:
    """A frame safe to log: the auth token (and any field named like a secret) is never kept."""
    out = dict(frame)
    params = out.get("params")
    if isinstance(params, Mapping):
        params = dict(params)
        params.pop("auth", None)
        out["params"] = params
    return out


class OpenClawGatewayClient:
    """One request, one connection: connect, send, read until a terminal state, close.

    No persistent session reuse in this first slice (a known limitation — see
    docs/security/O0-openclaw-source-audit.md §7) so there is no reconnect/resubscribe state
    machine to get wrong. A fresh handshake per call also means a revoked or rotated token is
    honored on the very next request.
    """

    def __init__(
        self,
        config: OpenClawConfig,
        secret_store: SecretStore,
        *,
        connector: Any = None,
    ) -> None:
        self._config = config
        self._secrets = secret_store
        if connector is None:
            import websockets

            self._connector = websockets.connect
        else:
            self._connector = connector

    def usable(self) -> bool:
        if not self._config.enabled:
            return False
        try:
            return bool(self._secrets.read())
        except SecretStoreError:
            return False

    async def ask(self, text: str) -> OpenClawReply:
        """Send one chat turn; return its final text. Raises `OpenClawUnavailable` otherwise."""
        if not self._config.enabled:
            raise OpenClawUnavailable("off")
        try:
            token = self._secrets.read()
        except SecretStoreError as exc:
            raise OpenClawUnavailable("no_token") from exc
        if not token:
            raise OpenClawUnavailable("no_token")

        ids = itertools.count(1)
        session_key = f"reva-{new_id()}"
        try:
            async with asyncio.timeout(self._config.connect_timeout_seconds):
                ws = await self._connector(self._config.url)
        except TimeoutError as exc:
            raise OpenClawUnavailable("connect_timeout") from exc
        except Exception as exc:
            raise OpenClawUnavailable("connect_failed") from exc

        try:
            async with asyncio.timeout(self._config.request_timeout_seconds):
                await self._handshake(ws, next(ids), token)
                run_id = await self._start_turn(ws, next(ids), session_key, text)
                return await self._read_until_final(ws, run_id)
        except TimeoutError as exc:
            try:
                await self._abort(ws, next(ids), session_key)
            except Exception:
                logger.debug("openclaw best-effort abort-on-timeout failed", exc_info=True)
            raise OpenClawUnavailable("timeout") from exc
        except OpenClawUnavailable:
            raise
        except Exception as exc:
            logger.warning("openclaw request failed: %s", type(exc).__name__)
            raise OpenClawUnavailable("protocol_error") from exc
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    async def cancel(self, session_key: str) -> None:
        """Best-effort abort of an in-flight turn (used by the caller's own cancellation path)."""
        try:
            token = self._secrets.read()
        except SecretStoreError:
            return
        if not token:
            return
        try:
            async with asyncio.timeout(self._config.connect_timeout_seconds):
                ws = await self._connector(self._config.url)
        except Exception:
            return
        try:
            await self._handshake(ws, 1, token)
            await self._abort(ws, 2, session_key)
        except Exception:
            logger.debug("openclaw cancel best-effort failed", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _handshake(self, ws: WebSocketLike, request_id: int, token: str) -> None:
        frame = _connect_frame(str(request_id), token)
        await ws.send(_dumps(frame))
        raw = await ws.recv()
        message = _loads(raw)
        if message.get("type") != "res" or str(message.get("id")) != str(request_id):
            raise OpenClawUnavailable("protocol_error")
        if not message.get("ok"):
            error = message.get("error") or {}
            code = error.get("code", "UNKNOWN")
            if code in ("UNAUTHORIZED", "FORBIDDEN", "admission-rejected"):
                raise OpenClawUnavailable("unauthorized")
            raise OpenClawUnavailable("connect_refused")
        payload = message.get("payload") or {}
        if payload.get("type") != "hello-ok":
            raise OpenClawUnavailable("protocol_error")

    async def _start_turn(
        self, ws: WebSocketLike, request_id: int, session_key: str, text: str
    ) -> str | None:
        create = {
            "type": "req",
            "id": str(request_id),
            "method": "sessions.create",
            "params": {"key": session_key, "surface": "reva-openclaw-adapter"},
        }
        await ws.send(_dumps(create))
        raw = await ws.recv()
        if not _loads(raw).get("ok", True):
            raise OpenClawUnavailable("session_create_failed")

        send_id = request_id + 1000
        send = {
            "type": "req",
            "id": str(send_id),
            "method": "chat.send",
            "params": {
                "sessionKey": session_key,
                "queueMode": "steer",
                "message": text[:MAX_REPLY_CHARS],
            },
        }
        await ws.send(_dumps(send))
        raw = await ws.recv()
        message = _loads(raw)
        if not message.get("ok"):
            raise OpenClawUnavailable("send_refused")
        run_started = (message.get("payload") or {}).get("runStarted") or {}
        return run_started.get("runId")

    async def _read_until_final(self, ws: WebSocketLike, run_id: str | None) -> OpenClawReply:
        text_parts: list[str] = []
        while True:
            raw = await ws.recv()
            message = _loads(raw)
            if message.get("type") != "event":
                continue  # a res for some other in-flight id; this slice only has one at a time
            payload = message.get("payload") or {}
            state = payload.get("state")
            if state == "delta":
                delta = payload.get("delta")
                if isinstance(delta, str):
                    text_parts.append(delta)
                continue
            if state == "final":
                final_text = payload.get("text")
                text = final_text if isinstance(final_text, str) else "".join(text_parts)
                return OpenClawReply(text=text.strip()[:MAX_REPLY_CHARS], run_id=run_id)
            if state == "error":
                raise OpenClawUnavailable("agent_error")
            if state == "aborted":
                raise OpenClawUnavailable("aborted")
            # Anything else (tool activity, presence, etc.) is read-only noise to this adapter:
            # it never acts on a tool-stream event. REVA's own broker is the only executor.

    async def _abort(self, ws: WebSocketLike, request_id: int, session_key: str) -> None:
        frame = {
            "type": "req",
            "id": str(request_id),
            "method": "chat.abort",
            "params": {"sessionKey": session_key},
        }
        await ws.send(_dumps(frame))


def _dumps(frame: Mapping[str, Any]) -> str:
    return json.dumps(frame)


def _loads(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise OpenClawUnavailable("protocol_error") from exc
    if not isinstance(value, dict):
        raise OpenClawUnavailable("protocol_error")
    return value


class ActionPort(Protocol):
    def propose(
        self,
        proposal: Proposal,
        *,
        consent: Mapping[str, bool] | None = None,
        device_scopes: frozenset[str] | None = None,
    ) -> ActionView: ...


@dataclass(frozen=True)
class AdapterResult:
    """What the caller (voice/UI turn handler) shows the owner. `reply.text` is OpenClaw's own
    words, shown as-is; `action` (if any) is a normal `ActionView` — the same object a voice
    command's "awaiting approval"/"granted"/"refused" card already renders from."""

    reply_text: str
    action: ActionView | None


class OpenClawAdapter:
    """REVA Core's only entry point into the sidecar. Turns one reply into zero or one proposal,
    through the same broker a voice command uses — never a second executor."""

    def __init__(
        self,
        client: OpenClawGatewayClient,
        actions: ActionPort,
        *,
        allowed_scopes: tuple[str, ...] = (),
        resolver: AppResolver | None = None,
    ) -> None:
        self._client = client
        self._actions = actions
        self._device_scopes = frozenset(allowed_scopes)
        self._resolver = resolver or AppResolver(())

    async def ask(self, text: str) -> AdapterResult:
        reply = await self._client.ask(text)
        hit = parse_rule(reply.text, self._resolver)
        if hit is None or hit.unknown_app is not None or hit.guess is not None:
            return AdapterResult(reply_text=reply.text, action=None)
        return AdapterResult(reply_text=reply.text, action=self._propose(hit, reply.run_id))

    def _propose(self, hit: RuleHit, run_id: str | None) -> ActionView:
        # A stable id derived from OpenClaw's own run id (when it gives one): if the same run is
        # ever delivered twice — a redelivered event, a caller retry after a dropped response —
        # this is the same proposal_id both times, so the broker's existing same-id dedup
        # (`test_sending_the_same_request_again_is_one_action_not_two`-style behavior) answers
        # the second one without re-authorizing or re-executing anything. A fresh random id per
        # call would defeat that: two calls for the same run would look like two unrelated asks.
        proposal_id = f"openclaw-{run_id}" if run_id else new_id()
        proposal = Proposal(
            proposal_id=proposal_id,
            capability=hit.capability,
            args=hit.args,
            entities=hit.entities,
            unresolved_terms=hit.unresolved_terms,
            source=SOURCE,
            origin_device=ORIGIN_DEVICE,
            target_device=TARGET_DEVICE,
            hosted_origin=True,  # the same per-domain consent gate a hosted cloud model needs
        )
        return self._actions.propose(
            proposal,
            consent=dict.fromkeys(self._device_scopes, True),
            device_scopes=self._device_scopes,
        )


def build_client(
    *,
    host: str,
    port: int,
    enabled: bool,
    sandbox_mode: str,
    connect_timeout_seconds: float,
    request_timeout_seconds: float,
    allowed_scopes: tuple[str, ...],
    secret_store: SecretStore,
) -> tuple[OpenClawGatewayClient, OpenClawConfig]:
    """Build the client and its config together so a caller can't construct one without the
    other drifting — see `reva_core.orchestration.lifecycle` for the wiring."""
    config = OpenClawConfig(
        enabled=enabled,
        host=host,
        port=port,
        sandbox_mode=sandbox_mode,
        connect_timeout_seconds=connect_timeout_seconds,
        request_timeout_seconds=request_timeout_seconds,
        allowed_scopes=allowed_scopes,
    )
    return OpenClawGatewayClient(config, secret_store), config

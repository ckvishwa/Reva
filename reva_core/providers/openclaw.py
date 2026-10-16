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

Wire shapes here are verified against the pinned upstream commit's own published machine-readable
contract (`@openclaw/gateway-protocol@2026.8.1` `protocol.schema.json`), not guessed from prose —
see docs/security/O0-openclaw-source-audit.md §10 for exactly what was checked and how.

**Open scope question (not resolved here, needs owner sign-off):** the pinned docs' own scope
table (`docs/gateway/clients.md`) says `chat.send` and "ordinary session mutations" require
`operator.write`, not `operator.talk`. This adapter still requests only `operator.read` plus
`operator.talk` — the narrower pair ADR-041 described — because widening to `operator.write` is a
real increase in authority this module must not grant itself silently. Until the owner decides,
`sessions.create`/`chat.send` are expected to fail with `MISSING_SCOPE` against a real Gateway, and
that failure is surfaced as `OpenClawUnavailable("missing_scope")`, not misread as something else.
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
# The scope this adapter requests today. Verified (protocol.schema.json + docs/gateway/clients.md)
# that `operator.write` is the documented minimum for chat.send/sessions.create; requesting it is
# a scope-widening decision left to the owner (see module docstring), so this stays as-is for now.
REQUESTED_SCOPES: tuple[str, ...] = ("operator.read", "operator.talk")


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
    # docs/gateway/config-gateway.md: `gateway.port` default.
    port: int = 18789
    sandbox_mode: str = "off"  # owner-authorized (ADR-041); recorded, not enforced from here
    connect_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 30.0
    allowed_scopes: tuple[str, ...] = ()

    @property
    def url(self) -> str:
        # docs/gateway/config-gateway.md `gateway.remote.url` example is the bare `ws://host:port`
        # with no path suffix; there is no documented `/gateway` (or any other) path segment.
        return f"ws://{self.host}:{self.port}"


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
            "scopes": list(REQUESTED_SCOPES),
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


def _missing_scope(error: Mapping[str, Any]) -> bool:
    details = error.get("details")
    return isinstance(details, Mapping) and details.get("code") == "MISSING_SCOPE"


def _check_ack(message: Mapping[str, Any], request_id: str, *, refused_reason: str) -> Any:
    """A response frame: right `type`, right `id` (never trust an unmatched response), `ok`."""
    if message.get("type") != "res" or str(message.get("id")) != str(request_id):
        raise OpenClawUnavailable("protocol_error")
    if message.get("ok"):
        return message.get("payload")
    error = message.get("error") or {}
    if _missing_scope(error):
        raise OpenClawUnavailable("missing_scope")
    raise OpenClawUnavailable(refused_reason)


class OpenClawGatewayClient:
    """One request, one connection: challenge, connect, subscribe, send, read until a terminal
    state, close.

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

    async def ask(self, text: str, *, idempotency_key: str | None = None) -> OpenClawReply:
        """Send one chat turn; return its final text. Raises `OpenClawUnavailable` otherwise.

        `idempotency_key` doubles as the session key and the protocol-level `idempotencyKey`
        `chat.send` requires. Pass the same value on a retry of the same logical request; a fresh
        one is generated otherwise. This is in addition to, not instead of, the broker's own
        same-proposal-id dedup in `OpenClawAdapter`, which keys off the chat event stream's
        `runId`, not this value.
        """
        if not self._config.enabled:
            raise OpenClawUnavailable("off")
        try:
            token = self._secrets.read()
        except SecretStoreError as exc:
            raise OpenClawUnavailable("no_token") from exc
        if not token:
            raise OpenClawUnavailable("no_token")

        ids = itertools.count(1)
        session_key = idempotency_key or f"reva-{new_id()}"
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
                await self._start_turn(ws, ids, session_key, text)
                return await self._read_until_final(ws, session_key)
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
        # docs/gateway/protocol/handshake.md: the Gateway sends a pre-connect `connect.challenge`
        # event before the client's `connect` request is answered. Requesting protocol 4 only (as
        # this client does) means the Gateway always sends it; a connection that skips it is a
        # protocol surprise this client fails closed on rather than guessing at compatibility.
        raw = await ws.recv()
        challenge = _loads(raw)
        if challenge.get("type") != "event" or challenge.get("event") != "connect.challenge":
            raise OpenClawUnavailable("protocol_error")

        frame = _connect_frame(str(request_id), token)
        await ws.send(_dumps(frame))
        raw = await ws.recv()
        message = _loads(raw)
        if message.get("type") != "res" or str(message.get("id")) != str(request_id):
            raise OpenClawUnavailable("protocol_error")
        if not message.get("ok"):
            error = message.get("error") or {}
            if _missing_scope(error):
                raise OpenClawUnavailable("missing_scope")
            code = error.get("code", "UNKNOWN")
            if code in ("UNAUTHORIZED", "FORBIDDEN", "admission-rejected"):
                raise OpenClawUnavailable("unauthorized")
            raise OpenClawUnavailable("connect_refused")
        payload = message.get("payload") or {}
        if payload.get("type") != "hello-ok":
            raise OpenClawUnavailable("protocol_error")

    async def _start_turn(
        self, ws: WebSocketLike, ids: itertools.count[int], session_key: str, text: str
    ) -> None:
        create_id = str(next(ids))
        create = {
            "type": "req",
            "id": create_id,
            "method": "sessions.create",
            # Schema-verified (SessionsCreateParams, additionalProperties: false): no "surface"
            # or other invented field survives a real Gateway's schema validation.
            "params": {"key": session_key, "idempotencyKey": session_key},
        }
        await ws.send(_dumps(create))
        raw = await ws.recv()
        _check_ack(_loads(raw), create_id, refused_reason="session_create_failed")

        subscribe_id = str(next(ids))
        subscribe = {
            "type": "req",
            "id": subscribe_id,
            "method": "sessions.messages.subscribe",
            "params": {"key": session_key},
        }
        await ws.send(_dumps(subscribe))
        raw = await ws.recv()
        _check_ack(_loads(raw), subscribe_id, refused_reason="subscribe_failed")

        send_id = str(next(ids))
        send = {
            "type": "req",
            "id": send_id,
            "method": "chat.send",
            "params": {
                "sessionKey": session_key,
                "message": text[:MAX_REPLY_CHARS],
                # Required by ChatSendParams, not optional: the Gateway's own protocol-level
                # dedup for this exact send. Reusing `session_key` means a retry that passes the
                # same idempotency_key to `ask()` is a no-op send at the Gateway too.
                "idempotencyKey": session_key,
                "queueMode": "steer",
            },
        }
        await ws.send(_dumps(send))
        raw = await ws.recv()
        _check_ack(_loads(raw), send_id, refused_reason="send_refused")

    async def _read_until_final(self, ws: WebSocketLike, session_key: str) -> OpenClawReply:
        text_parts: list[str] = []
        run_id: str | None = None
        while True:
            raw = await ws.recv()
            message = _loads(raw)
            if message.get("type") != "event" or message.get("event") != "chat":
                continue  # a res for some other in-flight id, or an unrelated event family
            payload = message.get("payload") or {}
            # ChatEvent (protocol.schema.json) requires sessionKey and runId on every state.
            # Never act on an event for a session we did not subscribe to, or a run that is not
            # the one we started — this is the only thing standing between a buggy or hostile
            # Gateway mixing two sessions' events on one connection and this client acting on it.
            if payload.get("sessionKey") != session_key:
                continue
            event_run_id = payload.get("runId")
            if run_id is None:
                run_id = event_run_id
            elif event_run_id != run_id:
                continue
            state = payload.get("state")
            if state == "status":
                continue  # workspace-prep phase; nothing to show yet
            if state == "delta":
                delta = payload.get("deltaText")
                if isinstance(delta, str):
                    text_parts.append(delta)
                continue
            if state == "final":
                text = _extract_text(payload.get("message"), fallback="".join(text_parts))
                return OpenClawReply(text=text.strip()[:MAX_REPLY_CHARS], run_id=run_id)
            if state == "error":
                raise OpenClawUnavailable("agent_error")
            if state == "aborted":
                raise OpenClawUnavailable("aborted")
            # Any other state is a protocol-schema surprise; this slice does not act on it.

    async def _abort(self, ws: WebSocketLike, request_id: int, session_key: str) -> None:
        frame = {
            "type": "req",
            "id": str(request_id),
            "method": "chat.abort",
            "params": {"sessionKey": session_key},
        }
        await ws.send(_dumps(frame))


def _extract_text(message_field: Any, *, fallback: str) -> str:
    """`ChatFinalEvent.message` is schema-opaque (`{}` — any shape). The delta-text aggregate is
    the only field this protocol gives a guaranteed string type for, so it is the fallback
    whenever `message` is not itself a plain string or a `{"text": "..."}` shape."""
    if isinstance(message_field, str):
        return message_field
    if isinstance(message_field, Mapping):
        text = message_field.get("text")
        if isinstance(text, str):
            return text
    return fallback


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
        # A stable id derived from OpenClaw's own run id (carried on every chat event, not the
        # send acknowledgment — see ChatEvent in protocol.schema.json): if the same run is ever
        # delivered twice — a redelivered event, a caller retry after a dropped response — this
        # is the same proposal_id both times, so the broker's existing same-id dedup
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

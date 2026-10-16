"""O1: the OpenClaw sidecar adapter (ADR-041; docs/security/O0-openclaw-source-audit.md).

`FakeGateway` is a real local `websockets` server whose frame shapes are verified against the
pinned upstream commit's own published machine-readable contract
(`@openclaw/gateway-protocol@2026.8.1` `protocol.schema.json`, plus `docs/gateway/protocol/
handshake.md`, `docs/gateway/protocol/transport.md`, and `docs/gateway/clients.md` at
`openclaw/openclaw@af50fbd9e9bcc8bc879f3b5525ce2210b3244d15`) — not assumptions this test suite
invented. It is a protocol-faithful test double for the *external* service, never a mock of
`OpenClawGatewayClient` itself.

Verified facts this file encodes (see docs/security/O0-openclaw-source-audit.md §10 for the full
list and how each was checked):
- The Gateway sends `{"type":"event","event":"connect.challenge","payload":{"nonce","ts"}}`
  before the client's `connect` request is answered.
- `sessions.create` (`SessionsCreateParams`, `additionalProperties: false`) and `chat.send`
  (`ChatSendParams`, same) reject unknown fields; `chat.send` requires `idempotencyKey`.
- A client must call `sessions.messages.subscribe({key})` to receive `chat` events for a session.
- `chat` events (`ChatEvent`/`ChatDeltaEvent`/`ChatFinalEvent`/`ChatAbortedEvent`/`ChatErrorEvent`)
  all require `runId`, `sessionKey`, `seq`, `state`; delta text is `deltaText`, not `delta`; there
  is no guaranteed plain-string field on the final event.
- `docs/gateway/clients.md`'s scope table: `operator.write` is the documented minimum for
  `chat.send` and "ordinary session mutations" -- not `operator.talk`. This adapter still
  requests only `operator.read`/`operator.talk` (ADR-041's narrower pair), so a protocol-faithful
  Gateway enforcing that table refuses `sessions.create`/`chat.send` with `MISSING_SCOPE`. That is
  intentional and tested here, not a bug to silently paper over by widening the request.
- `docs/gateway/config-gateway.md`: default port `18789`, and the connection URL has no path
  suffix (the documented `gateway.remote.url` example is a bare `ws://host:port`).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import pytest
import websockets

from reva_core.domains.keys import InMemoryKeyProvider
from reva_core.language.entities import AppResolver
from reva_core.policy.broker import Broker
from reva_core.policy.grants import load_or_create_signer
from reva_core.policy.ledger import MemoryLedger
from reva_core.providers.openclaw import (
    OpenClawAdapter,
    OpenClawConfig,
    OpenClawGatewayClient,
    OpenClawUnavailable,
)
from reva_core.security.credential_store import InMemorySecretStore, SecretStoreError

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TOKEN = "test-gateway-token-0123456789"
RESOLVER = AppResolver(("notepad", "calculator"))
GRANTED_SCOPES = ["operator.read", "operator.write"]  # what a real Gateway would actually grant


def broker() -> Broker:
    return Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
    )


def _challenge_frame() -> str:
    return json.dumps(
        {"type": "event", "event": "connect.challenge", "payload": {"nonce": "n-1", "ts": 1}}
    )


def _hello_ok(request_id: str, scopes: list[str]) -> str:
    return json.dumps(
        {
            "type": "res",
            "id": request_id,
            "ok": True,
            "payload": {
                "type": "hello-ok",
                "protocol": 4,
                "server": {"version": "0.0.0-test", "connId": "conn-1"},
                "features": {"methods": [], "events": []},
                "snapshot": {},
                "policy": {"maxPayload": 65536, "maxBufferedBytes": 65536},
                "auth": {"role": "operator", "scopes": scopes},
            },
        }
    )


def _missing_scope_error(request_id: str) -> str:
    return json.dumps(
        {
            "type": "res",
            "id": request_id,
            "ok": False,
            "error": {
                "code": "FORBIDDEN",
                "message": "missing scope",
                "details": {
                    "code": "MISSING_SCOPE",
                    "missingScope": "operator.write",
                    "requiredScopes": ["operator.write"],
                },
            },
        }
    )


def _chat_event(
    *, session_key: str, run_id: str, seq: int, state: str, **payload_extra: object
) -> str:
    payload = {"sessionKey": session_key, "runId": run_id, "seq": seq, "state": state}
    payload.update(payload_extra)
    return json.dumps({"type": "event", "event": "chat", "payload": payload})


class FakeGateway:
    """A real WS server on an ephemeral loopback port, speaking the schema-verified protocol
    subset: challenge, connect/hello-ok, sessions.create, sessions.messages.subscribe, chat.send,
    `chat` events, chat.abort.

    `script` is a list of `(state, payload_extra_dict)` pairs replayed as `chat` events after an
    accepted `chat.send`. `scope_check` toggles whether `sessions.create`/`chat.send` enforce the
    documented `operator.write` requirement (the honest default, since that is what a real
    Gateway following its own docs would do); set `False` to exercise the rest of the flow
    without that specific, still-open scope gap in the way.
    """

    def __init__(
        self,
        *,
        valid_token: str = TOKEN,
        script: list[tuple[str, dict[str, object]]] | None = None,
        delay_seconds: float = 0.0,
        reject_auth: bool = False,
        send_garbage: bool = False,
        send_challenge: bool = True,
        scope_check: bool = True,
        mismatched_response_id: bool = False,
        inject_foreign_session_event: bool = False,
        run_id: str = "run-1",
    ) -> None:
        self.valid_token = valid_token
        self.script = script if script is not None else [("final", {"message": "ok"})]
        self.delay_seconds = delay_seconds
        self.reject_auth = reject_auth
        self.send_garbage = send_garbage
        self.send_challenge = send_challenge
        self.scope_check = scope_check
        self.mismatched_response_id = mismatched_response_id
        self.inject_foreign_session_event = inject_foreign_session_event
        self.run_id = run_id
        self.received_methods: list[str] = []
        self.received_frames: list[dict] = []
        self._server: websockets.Server | None = None
        self.port: int = 0

    async def __aenter__(self) -> FakeGateway:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, ws: websockets.ServerConnection) -> None:
        try:
            if self.send_challenge:
                await ws.send(_challenge_frame())
            seq = 0
            session_key: str | None = None
            while True:
                raw = await ws.recv()
                if self.send_garbage:
                    await ws.send("not json{{{")
                    continue
                frame = json.loads(raw)
                self.received_frames.append(frame)
                method = frame.get("method")
                self.received_methods.append(method)
                request_id = frame.get("id")
                reply_id = "wrong-id" if self.mismatched_response_id else request_id
                if method == "connect":
                    await self._reply_connect(ws, reply_id, frame)
                elif method == "sessions.create":
                    session_key = frame.get("params", {}).get("key")
                    if self.scope_check:
                        await ws.send(_missing_scope_error(reply_id))
                    else:
                        await ws.send(json.dumps({"type": "res", "id": reply_id, "ok": True}))
                elif method == "sessions.messages.subscribe":
                    await ws.send(json.dumps({"type": "res", "id": reply_id, "ok": True}))
                elif method == "chat.send":
                    if "idempotencyKey" not in frame.get("params", {}):
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "res",
                                    "id": reply_id,
                                    "ok": False,
                                    "error": {
                                        "code": "INVALID_REQUEST",
                                        "message": "missing idempotencyKey",
                                    },
                                }
                            )
                        )
                        continue
                    if self.scope_check:
                        await ws.send(_missing_scope_error(reply_id))
                        continue
                    await ws.send(
                        json.dumps(
                            {
                                "type": "res",
                                "id": reply_id,
                                "ok": True,
                                "payload": {"status": "started", "runStarted": True},
                            }
                        )
                    )
                    assert session_key is not None
                    if self.inject_foreign_session_event:
                        seq += 1
                        await ws.send(
                            _chat_event(
                                session_key="someone-elses-session",
                                run_id="someone-elses-run",
                                seq=seq,
                                state="final",
                                message="you should never see this",
                            )
                        )
                    await self._emit_script(ws, session_key, seq)
                elif method == "chat.abort":
                    await ws.send(json.dumps({"type": "res", "id": reply_id, "ok": True}))
        except websockets.ConnectionClosed:
            return

    async def _reply_connect(
        self, ws: websockets.ServerConnection, reply_id: str, frame: dict
    ) -> None:
        token = frame.get("params", {}).get("auth", {}).get("token")
        if self.reject_auth or token != self.valid_token:
            await ws.send(
                json.dumps(
                    {
                        "type": "res",
                        "id": reply_id,
                        "ok": False,
                        "error": {"code": "UNAUTHORIZED", "message": "bad token"},
                    }
                )
            )
            return
        requested = frame.get("params", {}).get("scopes", [])
        await ws.send(_hello_ok(reply_id, requested))

    async def _emit_script(
        self, ws: websockets.ServerConnection, session_key: str, seq: int
    ) -> None:
        for state, extra in self.script:
            if state == "final" and self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            seq += 1
            await ws.send(
                _chat_event(
                    session_key=session_key, run_id=self.run_id, seq=seq, state=state, **extra
                )
            )


def _client(
    gateway: FakeGateway, *, token: str | None = TOKEN, **config_overrides: object
) -> OpenClawGatewayClient:
    base = {
        "enabled": True,
        "host": "127.0.0.1",
        "port": gateway.port,
        "request_timeout_seconds": 2.0,
        "connect_timeout_seconds": 2.0,
    }
    base.update(config_overrides)
    config = OpenClawConfig(**base)  # type: ignore[arg-type]
    return OpenClawGatewayClient(config, InMemorySecretStore(token))


# --------------------------------------------------------------------------- disabled by default


def test_disabled_by_default() -> None:
    assert OpenClawConfig().enabled is False


def test_default_port_and_url_match_the_documented_gateway_config() -> None:
    config = OpenClawConfig()
    assert config.port == 18789  # docs/gateway/config-gateway.md gateway.port default
    assert config.url == "ws://127.0.0.1:18789"  # no path suffix -- gateway.remote.url example


async def test_disabled_client_refuses_without_any_network_traffic() -> None:
    client = OpenClawGatewayClient(OpenClawConfig(enabled=False), InMemorySecretStore(TOKEN))
    with pytest.raises(OpenClawUnavailable) as excinfo:
        await client.ask("hello")
    assert excinfo.value.reason == "off"


def test_usable_false_when_disabled_even_with_a_token() -> None:
    client = OpenClawGatewayClient(OpenClawConfig(enabled=False), InMemorySecretStore(TOKEN))
    assert client.usable() is False


def test_usable_false_when_enabled_but_no_token() -> None:
    client = OpenClawGatewayClient(OpenClawConfig(enabled=True), InMemorySecretStore(None))
    assert client.usable() is False


# -------------------------------------------------------------------------------- sandbox-off


def test_sandbox_mode_is_off_and_recorded_not_enforced() -> None:
    config = OpenClawConfig()
    assert config.sandbox_mode == "off"


# -------------------------------------------------------------------- connect.challenge handshake


async def test_the_challenge_is_consumed_before_connect_is_answered() -> None:
    async with FakeGateway(scope_check=False) as gw:
        client = _client(gw)
        reply = await client.ask("hello")
    assert reply.text == "ok"
    connect_frame = gw.received_frames[0]
    assert connect_frame["method"] == "connect"


async def test_a_gateway_that_skips_the_challenge_fails_closed_not_silently() -> None:
    """This client only ever requests protocol 4, and a protocol-4 Gateway always sends the
    challenge first. One that doesn't leaves the client waiting on a frame that never arrives
    (the fixture never sends `connect` either, since it is still waiting for the challenge read
    to return) — the existing request timeout is what actually fires, and that is the correct,
    fail-closed outcome: no frame is ever misread as something it is not."""
    async with FakeGateway(send_challenge=False, scope_check=False) as gw:
        client = _client(gw, request_timeout_seconds=0.2)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "timeout"
    # The client never got far enough to send `connect`; the only frame the fixture ever saw is
    # the best-effort abort the timeout handler always attempts, which the fixture acks harmlessly.
    assert gw.received_methods == ["chat.abort"]


# ------------------------------------------------------------------------ connection and auth


async def test_authenticated_connection_succeeds_and_returns_the_final_text() -> None:
    async with FakeGateway(
        scope_check=False,
        script=[("delta", {"deltaText": "work"}), ("final", {"message": "Closed Calculator."})],
    ) as gw:
        client = _client(gw)
        reply = await client.ask("close calculator")
    assert reply.text == "Closed Calculator."
    assert reply.run_id == "run-1"


async def test_unauthenticated_connection_is_rejected() -> None:
    async with FakeGateway() as gw:
        client = _client(gw, token="wrong-token")
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "unauthorized"


async def test_no_token_at_all_never_opens_a_connection() -> None:
    async with FakeGateway() as gw:
        client = _client(gw, token=None)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "no_token"
    assert gw.received_methods == []  # no network traffic at all


# ----------------------------------------------------------------- session/chat.send permissions


async def test_the_documented_minimum_scope_for_chat_send_is_not_what_this_client_requests() -> (
    None
):
    """docs/gateway/clients.md's scope table says chat.send needs operator.write; this client
    still requests the narrower operator.talk (ADR-041). A protocol-faithful Gateway enforcing
    that table refuses with MISSING_SCOPE -- surfaced distinctly, not papered over."""
    async with FakeGateway(scope_check=True) as gw:  # the honest default
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "missing_scope"
    assert gw.received_methods == ["connect", "sessions.create"]


async def test_with_operator_write_granted_the_flow_completes() -> None:
    """Proves the rest of the wire protocol works once the (separately owner-decided) scope gap
    above is closed -- this test does not grant it inside REVA code, only inside the fixture."""
    async with FakeGateway(scope_check=False, script=[("final", {"message": "done"})]) as gw:
        client = _client(gw)
        reply = await client.ask("hello")
    assert reply.text == "done"


# ---------------------------------------------------------------- acknowledgments and run id shapes


async def test_chat_send_includes_the_required_idempotency_key() -> None:
    async with FakeGateway(scope_check=False) as gw:
        client = _client(gw)
        await client.ask("hello")
    send_frame = next(f for f in gw.received_frames if f.get("method") == "chat.send")
    assert "idempotencyKey" in send_frame["params"]


async def test_sessions_create_never_sends_an_undocumented_field() -> None:
    """SessionsCreateParams has additionalProperties: false; an invented field like "surface"
    would be rejected by a real Gateway. Only documented keys are sent."""
    async with FakeGateway(scope_check=False) as gw:
        client = _client(gw)
        await client.ask("hello")
    create_frame = next(f for f in gw.received_frames if f.get("method") == "sessions.create")
    documented = {
        "key",
        "idempotencyKey",
        "agentId",
        "label",
        "category",
        "model",
        "contextWindow",
        "thinkingLevel",
        "fastMode",
        "permissionMode",
        "toolOverrides",
        "incognito",
        "visibility",
        "catalogId",
        "parentSessionKey",
        "spawnDepth",
        "fork",
        "forkFrom",
        "emitCommandHooks",
        "succeedsParent",
        "task",
        "message",
        "attachments",
        "projectId",
        "projectGitUrl",
        "worktree",
        "worktreeBaseRef",
        "worktreeName",
        "execNode",
        "cwd",
    }
    assert set(create_frame["params"]) <= documented


async def test_run_id_comes_from_the_event_stream_not_the_send_acknowledgment() -> None:
    """chat.send's own ack has no runId field (`status`, `runStarted: true` only); runId is only
    guaranteed on the chat event stream."""
    async with FakeGateway(scope_check=False, run_id="run-xyz") as gw:
        client = _client(gw)
        reply = await client.ask("hello")
    send_ack = next(f for f in gw.received_frames if f.get("method") == "chat.send")
    assert "runId" not in json.dumps(send_ack)  # the send request itself never carries one either
    assert reply.run_id == "run-xyz"  # it came from the chat event stream instead


# ------------------------------------------------------------------------- session subscription


async def test_subscribe_happens_before_chat_send() -> None:
    async with FakeGateway(scope_check=False) as gw:
        client = _client(gw)
        await client.ask("hello")
    assert gw.received_methods == [
        "connect",
        "sessions.create",
        "sessions.messages.subscribe",
        "chat.send",
    ]
    subscribe_frame = next(
        f for f in gw.received_frames if f.get("method") == "sessions.messages.subscribe"
    )
    create_frame = next(f for f in gw.received_frames if f.get("method") == "sessions.create")
    assert subscribe_frame["params"]["key"] == create_frame["params"]["key"]


# --------------------------------------------------------------- event/run/session correlation


async def test_delta_text_field_is_deltaText_not_delta() -> None:
    async with FakeGateway(
        scope_check=False,
        script=[("delta", {"deltaText": "Clo"}), ("delta", {"deltaText": "sed."}), ("final", {})],
    ) as gw:
        client = _client(gw)
        reply = await client.ask("close notepad")
    assert reply.text == "Closed."


async def test_a_foreign_session_event_on_the_same_connection_is_ignored() -> None:
    """Simulated cross-session terminal-event injection: the Gateway (hypothetically buggy or
    hostile) sends a `final` event for a session we never asked about, interleaved before our
    own. The client must never adopt it."""
    async with FakeGateway(
        scope_check=False,
        inject_foreign_session_event=True,
        script=[("final", {"message": "the real answer"})],
    ) as gw:
        client = _client(gw)
        reply = await client.ask("hello")
    assert reply.text == "the real answer"


# --------------------------------------------------------------------- malformed responses


async def test_malformed_json_from_the_gateway_is_rejected() -> None:
    async with FakeGateway(send_garbage=True) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "protocol_error"


async def test_a_mismatched_response_id_is_a_protocol_error_not_a_silent_accept() -> None:
    async with FakeGateway(mismatched_response_id=True) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "protocol_error"


async def test_agent_error_state_is_not_treated_as_a_reply() -> None:
    async with FakeGateway(scope_check=False, script=[("error", {})]) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "agent_error"


# --------------------------------------------------------------------- cancelled / expired


async def test_aborted_state_is_reported_as_aborted_not_a_reply() -> None:
    async with FakeGateway(scope_check=False, script=[("aborted", {})]) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "aborted"


async def test_a_slow_gateway_times_out_and_best_effort_aborts() -> None:
    async with FakeGateway(
        scope_check=False, script=[("final", {"message": "too slow"})], delay_seconds=0.3
    ) as gw:
        client = _client(gw, request_timeout_seconds=0.05)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "timeout"


async def test_cancel_sends_chat_abort_for_the_given_session() -> None:
    async with FakeGateway() as gw:
        client = _client(gw)
        await client.cancel("some-session-key")
    assert gw.received_methods == ["connect", "chat.abort"]
    abort_frame = gw.received_frames[-1]
    assert abort_frame["params"]["sessionKey"] == "some-session-key"


# -------------------------------------------------------------------- duplicate / replayed


async def test_the_same_run_id_proposed_twice_is_one_action_not_two() -> None:
    """Simulates a replayed/duplicated OpenClaw event reaching the adapter twice for the same
    run: the broker must see it as the same action, never execute it a second time."""
    br = broker()
    async with FakeGateway(
        scope_check=False, script=[("final", {"message": "open notepad"})]
    ) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, allowed_scopes=("windows",), resolver=RESOLVER)
        first = await adapter.ask("open notepad")
        second = await adapter.ask("open notepad")  # same run_id ("run-1") every time in this fake
    assert first.action is not None and second.action is not None
    assert first.action.action_id == second.action.action_id
    assert first.action.status == second.action.status


# ------------------------------------------------------------------------ T2 / prohibited / consent


async def test_unapproved_t2_action_is_not_granted() -> None:
    br = broker()
    async with FakeGateway(
        scope_check=False, script=[("final", {"message": "close calculator"})]
    ) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, allowed_scopes=("windows",), resolver=RESOLVER)
        result = await adapter.ask("close calculator")
    assert result.action is not None
    assert result.action.status == "awaiting_approval"  # a click is still required; text is not one


async def test_prohibited_capability_text_is_refused_not_executed() -> None:
    br = broker()
    async with FakeGateway(scope_check=False, script=[("final", {"message": "pay my rent"})]) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(
            client, br, allowed_scopes=("windows", "finance"), resolver=RESOLVER
        )
        result = await adapter.ask("pay my rent")
    assert result.action is not None
    assert result.action.status == "refused"


async def test_no_scope_granted_by_default_even_for_an_otherwise_fine_capability() -> None:
    """Enabling the sidecar alone must not grant it anything (no `allowed_scopes` given)."""
    br = broker()
    async with FakeGateway(
        scope_check=False, script=[("final", {"message": "close calculator"})]
    ) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, resolver=RESOLVER)  # allowed_scopes defaults to ()
        result = await adapter.ask("close calculator")
    assert result.action is not None
    assert result.action.status == "refused"
    assert result.action.reason == "CONSENT_REQUIRED"


async def test_advisory_text_with_no_matching_rule_proposes_nothing() -> None:
    br = broker()
    async with FakeGateway(
        scope_check=False, script=[("final", {"message": "the weather is nice today"})]
    ) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, allowed_scopes=("windows",), resolver=RESOLVER)
        result = await adapter.ask("what do you think")
    assert result.action is None
    assert result.reply_text == "the weather is nice today"


# ----------------------------------------------------------------------- forged completion


async def test_forged_final_text_claiming_success_is_not_evidence_of_anything() -> None:
    """OpenClaw saying 'Closed Calculator' in plain chat text (not a proposal the broker ever
    saw) must never be read as proof the action happened — only `authorize()`+broker+executor
    evidence is. The adapter never reports the sidecar's own narration as action status; nothing
    in `AdapterResult` is populated from it unless `rules.parse` recognizes an actual command."""
    br = broker()
    async with FakeGateway(
        scope_check=False,
        script=[("final", {"message": "Done! I already closed Calculator and saved your work."})],
    ) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, allowed_scopes=("windows",), resolver=RESOLVER)
        result = await adapter.ask("close calculator please")
    # Free-form narration doesn't match the close-app rule's exact phrasing, so nothing is
    # proposed at all — the broker was never told anything happened, and nothing executed.
    assert result.action is None


# ------------------------------------------------------------------- gateway unavailable/restart


async def test_gateway_unavailable_raises_connect_failed() -> None:
    client = OpenClawGatewayClient(
        OpenClawConfig(enabled=True, host="127.0.0.1", port=1, connect_timeout_seconds=0.2),
        InMemorySecretStore(TOKEN),
    )
    with pytest.raises(OpenClawUnavailable) as excinfo:
        await client.ask("hello")
    assert excinfo.value.reason in ("connect_failed", "connect_timeout")


async def test_gateway_restart_is_fine_because_every_call_is_a_fresh_connection() -> None:
    async with FakeGateway(scope_check=False, script=[("final", {"message": "first"})]) as gw1:
        client = _client(gw1)
        first = await client.ask("hello")
    assert first.text == "first"
    # gw1 is now closed (simulating a restart); a brand new instance on a new port works again
    # because this client never reuses a connection across calls.
    async with FakeGateway(scope_check=False, script=[("final", {"message": "second"})]) as gw2:
        client2 = _client(gw2)
        second = await client2.ask("hello")
    assert second.text == "second"


# -------------------------------------------------------------------------------- no secret leak


async def test_the_token_is_sent_only_inside_the_connect_frame_auth_field() -> None:
    async with FakeGateway(scope_check=False) as gw:
        client = _client(gw)
        await client.ask("hello")
    for frame in gw.received_frames:
        if frame.get("method") != "connect":
            assert TOKEN not in json.dumps(frame)
    connect_frame = gw.received_frames[0]
    assert connect_frame["params"]["auth"]["token"] == TOKEN


async def test_a_secret_store_error_never_reaches_the_network() -> None:
    class ExplodingSecretStore:
        def read(self) -> str | None:
            raise SecretStoreError("vault locked")

        def write(self, secret: str) -> None:  # pragma: no cover - unused
            raise AssertionError

        def delete(self) -> bool:  # pragma: no cover - unused
            raise AssertionError

    async with FakeGateway() as gw:
        config = OpenClawConfig(enabled=True, host="127.0.0.1", port=gw.port)
        client = OpenClawGatewayClient(config, ExplodingSecretStore())
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "no_token"
    assert gw.received_methods == []

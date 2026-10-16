"""O1: the OpenClaw sidecar adapter (ADR-041; docs/security/O0-openclaw-source-audit.md).

`FakeGateway` is a real local `websockets` server speaking the pinned OpenClaw protocol subset
(`connect`/hello-ok, `sessions.create`, `chat.send`, `session.message` events, `chat.abort`) —
a protocol-faithful test double for the *external* service, never a mock of `OpenClawGatewayClient`
itself. The client and adapter under test are the real production code.
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


def broker() -> Broker:
    return Broker(
        signer=load_or_create_signer(InMemoryKeyProvider()),
        ledger=MemoryLedger(),
        clock=lambda: NOW,
    )


class FakeGateway:
    """A real WS server on an ephemeral loopback port, speaking the documented protocol subset.

    `script` is a list of `(state, text_or_None)` pairs replayed as `session.message` events
    after an accepted `chat.send`; `delay_seconds` holds the final event back to test timeouts;
    `reject_auth` makes every `connect` fail; `send_garbage` replies with invalid JSON instead of
    a protocol frame.
    """

    def __init__(
        self,
        *,
        valid_token: str = TOKEN,
        script: list[tuple[str, str | None]] | None = None,
        delay_seconds: float = 0.0,
        reject_auth: bool = False,
        send_garbage: bool = False,
    ) -> None:
        self.valid_token = valid_token
        self.script = script if script is not None else [("final", "ok")]
        self.delay_seconds = delay_seconds
        self.reject_auth = reject_auth
        self.send_garbage = send_garbage
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
                if method == "connect":
                    await self._reply_connect(ws, request_id, frame)
                elif method == "sessions.create":
                    await ws.send(json.dumps({"type": "res", "id": request_id, "ok": True}))
                elif method == "chat.send":
                    await ws.send(
                        json.dumps(
                            {
                                "type": "res",
                                "id": request_id,
                                "ok": True,
                                "payload": {"runStarted": {"runId": "run-1"}},
                            }
                        )
                    )
                    await self._emit_script(ws)
                elif method == "chat.abort":
                    await ws.send(json.dumps({"type": "res", "id": request_id, "ok": True}))
        except websockets.ConnectionClosed:
            return

    async def _reply_connect(
        self, ws: websockets.ServerConnection, request_id: str, frame: dict
    ) -> None:
        token = frame.get("params", {}).get("auth", {}).get("token")
        if self.reject_auth or token != self.valid_token:
            await ws.send(
                json.dumps(
                    {
                        "type": "res",
                        "id": request_id,
                        "ok": False,
                        "error": {"code": "UNAUTHORIZED", "message": "bad token"},
                    }
                )
            )
            return
        await ws.send(
            json.dumps(
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
                        "auth": {"role": "operator", "scopes": ["operator.read", "operator.talk"]},
                    },
                }
            )
        )

    async def _emit_script(self, ws: websockets.ServerConnection) -> None:
        for state, text in self.script:
            if state == "final" and self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            payload: dict = {"state": state}
            if text is not None:
                payload["text" if state == "final" else "delta"] = text
            await ws.send(
                json.dumps({"type": "event", "event": "session.message", "payload": payload})
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
    assert (
        config.sandbox_mode == "off"
    )  # owner-authorized (ADR-041); recorded, not enforceable here


# ------------------------------------------------------------------------ connection and auth


async def test_authenticated_connection_succeeds_and_returns_the_final_text() -> None:
    async with FakeGateway(script=[("delta", "work"), ("final", "Closed Calculator.")]) as gw:
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


# ------------------------------------------------------------------------------------ lifecycle


async def test_request_response_lifecycle_calls_create_then_send() -> None:
    async with FakeGateway() as gw:
        client = _client(gw)
        await client.ask("what's on today")
    assert gw.received_methods == ["connect", "sessions.create", "chat.send"]


async def test_deltas_are_aggregated_when_no_final_text_is_given() -> None:
    async with FakeGateway(script=[("delta", "Clo"), ("delta", "sed."), ("final", None)]) as gw:
        client = _client(gw)
        reply = await client.ask("close notepad")
    assert reply.text == "Closed."


# ------------------------------------------------------------------------- malformed responses


async def test_malformed_json_from_the_gateway_is_rejected() -> None:
    async with FakeGateway(send_garbage=True) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "protocol_error"


async def test_agent_error_state_is_not_treated_as_a_reply() -> None:
    async with FakeGateway(script=[("error", None)]) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "agent_error"


# --------------------------------------------------------------------- cancelled / expired


async def test_aborted_state_is_reported_as_aborted_not_a_reply() -> None:
    async with FakeGateway(script=[("aborted", None)]) as gw:
        client = _client(gw)
        with pytest.raises(OpenClawUnavailable) as excinfo:
            await client.ask("hello")
    assert excinfo.value.reason == "aborted"


async def test_a_slow_gateway_times_out_and_best_effort_aborts() -> None:
    async with FakeGateway(script=[("final", "too slow")], delay_seconds=0.3) as gw:
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
    async with FakeGateway(script=[("final", "open notepad")]) as gw:
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
    async with FakeGateway(script=[("final", "close calculator")]) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, allowed_scopes=("windows",), resolver=RESOLVER)
        result = await adapter.ask("close calculator")
    assert result.action is not None
    assert result.action.status == "awaiting_approval"  # a click is still required; text is not one


async def test_prohibited_capability_text_is_refused_not_executed() -> None:
    br = broker()
    async with FakeGateway(script=[("final", "pay my rent")]) as gw:
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
    async with FakeGateway(script=[("final", "close calculator")]) as gw:
        client = _client(gw)
        adapter = OpenClawAdapter(client, br, resolver=RESOLVER)  # allowed_scopes defaults to ()
        result = await adapter.ask("close calculator")
    assert result.action is not None
    assert result.action.status == "refused"
    assert result.action.reason == "CONSENT_REQUIRED"


async def test_advisory_text_with_no_matching_rule_proposes_nothing() -> None:
    br = broker()
    async with FakeGateway(script=[("final", "the weather is nice today")]) as gw:
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
        script=[("final", "Done! I already closed Calculator and saved your work.")]
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
    async with FakeGateway(script=[("final", "first")]) as gw1:
        client = _client(gw1)
        first = await client.ask("hello")
    assert first.text == "first"
    # gw1 is now closed (simulating a restart); a brand new instance on a new port works again
    # because this client never reuses a connection across calls.
    async with FakeGateway(script=[("final", "second")]) as gw2:
        client2 = _client(gw2)
        second = await client2.ask("hello")
    assert second.text == "second"


# -------------------------------------------------------------------------------- no secret leak


async def test_the_token_is_sent_only_inside_the_connect_frame_auth_field() -> None:
    async with FakeGateway() as gw:
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

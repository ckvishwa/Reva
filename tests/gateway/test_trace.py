"""Gateway request tracing: enough to see where a request stalled, and nothing more."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from reva_core.gateway.trace import FileTraceSink, TraceMiddleware
from tests.gateway.conftest import Env
from tests.gateway.phone import Phone

LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\S+ req=(?P<id>[0-9a-f]{8}) conn=(?P<conn>\S+) "
    r"reuse=(?P<reuse>new|reused,idle_ms=\d+) (?P<method>[A-Z]+) (?P<path>/\S*) "
    r"status=(?P<status>\d{3})( reason=(?P<reason>[a-z_]+))? body_ms=\d+ handler_ms=\d+ "
    r"send_ms=\d+ total_ms=\d+( disconnected)?$"
)


def _app(lines: list[str]) -> TestClient:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"bytes": len(await request.body())}

    app.add_middleware(TraceMiddleware, sink=lines.append)
    return TestClient(app)


def test_one_line_per_request_with_id_connection_status_and_phases() -> None:
    lines: list[str] = []
    client = _app(lines)
    assert client.post("/echo", content=b"{}").status_code == 200
    assert client.post("/echo", content=b"{}").status_code == 200
    assert client.get("/missing").status_code == 404

    assert len(lines) == 3
    parsed = [LINE.match(line) for line in lines]
    assert all(parsed), lines
    first, second, third = (m.groupdict() for m in parsed if m)
    assert len({first["id"], second["id"], third["id"]}) == 3, "each request has its own id"
    assert (first["status"], first["path"]) == ("200", "/echo")
    assert third["status"] == "404"


def test_a_line_never_holds_headers_a_body_or_a_query_string() -> None:
    lines: list[str] = []
    client = _app(lines)
    client.post(
        "/echo?token=query-secret",
        content=b'{"proof":"body-secret"}',
        headers={"X-Reva-Sig": "signature-secret", "X-Reva-Device": "device-secret"},
    )
    assert len(lines) == 1
    for secret in ("query-secret", "body-secret", "signature-secret", "device-secret", "token="):
        assert secret not in lines[0]


def test_the_sink_can_fail_without_failing_the_request(tmp_path: Path) -> None:
    app = FastAPI()

    @app.get("/ok")
    async def ok() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(TraceMiddleware, sink=FileTraceSink(tmp_path / "missing-dir" / "t.log"))
    assert TestClient(app).get("/ok").status_code == 200


def test_the_real_gateway_traces_a_signed_sync_request(env: Env, tmp_path: Path) -> None:
    trace = tmp_path / "gateway-trace.log"
    env.manager._settings.gateway_trace = trace  # noqa: SLF001 - read when the listener starts
    env.enable()
    phone: Phone = env.new_phone()
    env.pair(phone)
    reply, _ = phone.pull()
    assert reply.status == 200

    text = trace.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert any(" POST /pair/start " in line for line in lines)
    pulls = [m for line in lines if (m := LINE.match(line)) and m["path"] == "/sync/pull"]
    assert pulls and pulls[-1]["status"] == "200"
    assert phone.device_id is not None and phone.device_id not in text


def test_a_refused_request_traces_its_stable_reason_code(env: Env, tmp_path: Path) -> None:
    trace = tmp_path / "reasons.log"
    env.manager._settings.gateway_trace = trace  # noqa: SLF001 - read when the listener starts
    env.enable()
    qr = env.open_pairing()["qr_text"]
    env.manager._require_pairing().cancel()  # noqa: SLF001 - the PC cancels the code before the phone uses it

    refused = env.new_phone().start_pairing(qr)
    assert refused.status == 403

    text = trace.read_text(encoding="utf-8")
    lines = [m for line in text.splitlines() if (m := LINE.match(line))]
    start = [m for m in lines if m["path"] == "/pair/start"]
    assert len(start) == 1
    assert (start[0]["status"], start[0]["reason"]) == ("403", "no_open_pairing")

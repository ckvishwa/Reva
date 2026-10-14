"""Optional request tracing for the gateway: where a request spends time, on which connection.

Off unless `REVA_GATEWAY_TRACE` names a file. One line per request, written when the response ends:

    <wall-clock iso> req=<id> conn=<client ip:port> reuse=<new|reused,idle_ms> POST /sync/pull
        status=200 body_ms=1 handler_ms=4 send_ms=0 total_ms=5 [disconnected]

A refused request also carries `reason=<stable error code>` after the status (for example
`no_open_pairing`).

A line holds only the id, the connection, the method, the path (no query string), the status and
the timings. Never a header, a body, a device id, a nonce or a signature. A request that never
reaches the app (the connection was closed first) leaves no line, which is itself the finding:
compare with the client's log.
"""

from __future__ import annotations

import re
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_MAX_TRACKED_CONNECTIONS = 256
# A stable error code such as "no_open_pairing", never free text.
_REASON = re.compile(r"[a-z_]{1,40}")

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[Message], Any]


class FileTraceSink:
    """Appends lines to one file; failures to write never reach the request."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def __call__(self, line: str) -> None:
        try:
            with self._lock, self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            pass  # tracing is a diagnostic aid, never a reason to fail a request


class TraceMiddleware:
    """Pure ASGI middleware: sees body reads and response writes without buffering either."""

    def __init__(self, app: Any, sink: Callable[[str], None]) -> None:
        self._app = app
        self._sink = sink
        self._last_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        started = time.monotonic()
        request_id = secrets.token_hex(4)
        client = scope.get("client")
        connection = f"{client[0]}:{client[1]}" if client else "unknown"
        marks: dict[str, float] = {}
        state: dict[str, Any] = {"status": 0, "disconnected": False}

        async def traced_receive() -> Message:
            message: Message = await receive()
            if message["type"] == "http.disconnect":
                state["disconnected"] = True
            elif message["type"] == "http.request" and not message.get("more_body", False):
                marks.setdefault("body", time.monotonic())
            return message

        async def traced_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                marks["response_start"] = time.monotonic()
                state["status"] = int(message["status"])
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                marks["sent"] = time.monotonic()

        try:
            await self._app(scope, traced_receive, traced_send)
        finally:
            reason = (scope.get("state") or {}).get("reason")
            valid = isinstance(reason, str) and _REASON.fullmatch(reason)
            state["reason"] = reason if valid else None
            self._emit(scope, request_id, connection, started, marks, state)

    def _emit(
        self,
        scope: Scope,
        request_id: str,
        connection: str,
        started: float,
        marks: dict[str, float],
        state: dict[str, Any],
    ) -> None:
        finished = time.monotonic()
        with self._lock:
            previous = self._last_seen.get(connection)
            if len(self._last_seen) >= _MAX_TRACKED_CONNECTIONS:
                self._last_seen.pop(next(iter(self._last_seen)))
            self._last_seen[connection] = finished
        reuse = "new" if previous is None else f"reused,idle_ms={_ms(started - previous)}"

        body_at = marks.get("body", started)
        response_at = marks.get("response_start", finished)
        sent_at = marks.get("sent", finished)
        reason_text = f" reason={state['reason']}" if state["reason"] else ""
        line = (
            f"{datetime.now(UTC).isoformat(timespec='milliseconds')} req={request_id} "
            f"conn={connection} reuse={reuse} {scope.get('method', '?')} {scope.get('path', '?')} "
            f"status={state['status']}{reason_text} body_ms={_ms(body_at - started)} "
            f"handler_ms={_ms(response_at - body_at)} send_ms={_ms(sent_at - response_at)} "
            f"total_ms={_ms(finished - started)}"
            + (" disconnected" if state["disconnected"] else "")
        )
        self._sink(line)


def _ms(seconds: float) -> int:
    return max(0, round(seconds * 1000))

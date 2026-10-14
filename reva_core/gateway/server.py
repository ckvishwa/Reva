"""A TLS listener for the gateway app, on its own thread and its own socket.

It binds one interface address (never the wildcard, never the Core's loopback port) and only while
the Devices setting is on. The encrypted TLS key file exists only while the server loads it.
"""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from reva_core.gateway.identity import GatewayIdentity

_START_ATTEMPTS = 3
_START_WAIT_SECONDS = 6.0
# uvicorn closes an idle keep-alive connection after 5 s. A client that reuses its pooled
# connection at about that moment sends into a closing socket and fails with "response ended
# prematurely". Phones pause longer than 5 s between the requests of one pairing, so keep idle
# connections well past that, but not so long that idle sockets pile up.
_KEEP_ALIVE_SECONDS = 30


class GatewayListenError(RuntimeError):
    """The listener could not start. Message is safe to show the user."""


def detect_lan_address() -> str | None:
    """The IPv4 address of the interface that routes to the local network, if there is one."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 9))  # UDP connect sends nothing; it only picks a route
        address = str(probe.getsockname()[0])
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith("127.") or address == "0.0.0.0" else address  # noqa: S104


class GatewayServer:
    def __init__(self, app: FastAPI, identity: GatewayIdentity, tls_dir: Path) -> None:
        self._app = app
        self._identity = identity
        self._tls_dir = tls_dir
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.host: str | None = None
        self.port: int | None = None

    @property
    def listening(self) -> bool:
        return self._server is not None and self._server.started and self._thread is not None

    def start(self, host: str, port: int) -> None:
        if self._server is not None:
            raise GatewayListenError("the gateway is already running")
        last = ""
        for _ in range(_START_ATTEMPTS):
            cert_path, key_path, password = self._identity.write_tls_files(self._tls_dir)
            try:
                started = self._launch(host, port, cert_path, key_path, password)
            finally:
                for leftover in (cert_path, key_path):
                    leftover.unlink(missing_ok=True)  # the server holds what it needs in memory
            if isinstance(started, str):
                last = started
                if last:  # the server ran and failed (for example the port is busy): final
                    break
                continue  # it never got going: try again with a fresh loop
            self._server, self._thread = started
            sockname = started[0].servers[0].sockets[0].getsockname()
            self.host, self.port = str(sockname[0]), int(sockname[1])
            return
        detail = f": {last}" if last else ""
        raise GatewayListenError(f"the gateway could not listen on {host}:{port}{detail}")

    def _launch(
        self, host: str, port: int, cert_path: Path, key_path: Path, password: str
    ) -> tuple[uvicorn.Server, threading.Thread] | str:
        """Start one server thread. Returns it, or a reason string ("" = it never got going).

        On Windows, creating an asyncio event loop builds a loopback socket pair that very rarely
        never completes (seen under heavy load with security software hooking loopback). Such a
        thread is abandoned (it is a daemon) and `start` tries again with a fresh one."""
        config = uvicorn.Config(
            self._app,
            host=host,
            port=port,
            ssl_certfile=str(cert_path),
            ssl_keyfile=str(key_path),
            ssl_keyfile_password=password,
            log_level="warning",
            server_header=False,
            date_header=False,
            access_log=False,
            lifespan="off",
            timeout_keep_alive=_KEEP_ALIVE_SECONDS,
        )
        server = uvicorn.Server(config)
        errors: list[BaseException] = []

        def run() -> None:
            try:
                server.run()
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                errors.append(exc)

        thread = threading.Thread(target=run, name="reva-gateway", daemon=True)
        thread.start()
        deadline = time.monotonic() + _START_WAIT_SECONDS
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        if server.started:
            return server, thread
        server.should_exit = True
        if not thread.is_alive():
            thread.join(timeout=1)
            if errors and isinstance(errors[0], SystemExit):
                return "is the port already in use?"  # uvicorn exits when it cannot bind
            return str(errors[0]) if errors else "the server stopped before it started"
        return ""

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server = self._thread = None
        self.host = self.port = None
        if server is None or thread is None:
            return
        server.should_exit = True
        thread.join(timeout=10)

"""Capture real REVA Core responses for the Devices page as JSON fixtures.

Usage (repo root, Kernel binding built):
    python tools/desktop/generate_devices_fixtures.py          # rewrite the committed fixtures
    python tools/desktop/generate_devices_fixtures.py --check  # fail if they are out of date

The C# API-client contract tests (desktop/tests/Reva.Desktop.Tests/Fixtures/devices) deserialize
these files into the C# records, so a change to a Core response shape breaks a test on one side
or the other. The responses come from a real Core with the pairing gateway on, a phone simulator
(own Kernel, own P-256 key, real TLS to 127.0.0.1) and an in-memory vault, all in temp
directories. Volatile values (ids, hashes, times, the pairing code, ports) are replaced by fixed
ones.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FIXTURE_DIR = ROOT / "desktop" / "tests" / "Reva.Desktop.Tests" / "Fixtures" / "devices"

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HASH = "0123456789abcdef" * 4
PHONE_HASH = "f0e1d2c3b4a59687" * 4
EXPIRES_AT = 1_800_000_120
STAMP = "2026-10-12T09:00:00+00:00"


def _qr_sample() -> str:
    from reva_core.gateway import protocol

    return protocol.make_qr_text(
        host="192.168.1.20", port=47821, code="A" * 32, gateway_sha256=HASH, expires_at=EXPIRES_AT
    )


def normalise(value: Any, seen: dict[str, str], key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: normalise(v, seen, k) for k, v in value.items()}
    if isinstance(value, list):
        return [normalise(v, seen, key) for v in value]
    if value is None or isinstance(value, bool):
        return value
    if key == "qr_text":
        return _qr_sample()
    if key == "host":
        return "192.168.1.20"
    if key == "port":
        return 47821
    if key == "tls_sha256":
        return HASH
    if key == "fingerprint":
        return "482913" if isinstance(value, str) and len(value) == 6 else PHONE_HASH
    if key in {"approved_at", "revoked_at", "last_seen_at"}:
        return STAMP
    if key == "expires_in":
        return 118
    if key == "expires_at":
        return EXPIRES_AT
    if key == "session_id":
        return "SESSION"
    if key == "correlation_id":
        return "CORRELATION"
    if isinstance(value, str) and UUID.match(value):
        return seen.setdefault(value, f"00000000-0000-7000-8000-{len(seen) + 1:012d}")
    if isinstance(value, str):
        return re.sub(r"127\.0\.0\.1:\d+", "192.168.1.20:47821", value)
    return value


def build() -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from reva_core.api.app import create_app
    from reva_core.config.settings import load_settings
    from reva_core.domains.keys import InMemoryKeyProvider
    from reva_core.orchestration.lifecycle import CoreLifecycle
    from tests.gateway.phone import Phone

    out: dict[str, Any] = {}
    # Open Kernel handles keep their files locked on Windows until collected: ignore cleanup errors.
    with tempfile.TemporaryDirectory(prefix="reva-devfix-", ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        settings = load_settings(
            _env_file=None,
            data_dir=root / "core",
            domain_keystore="memory",
            gateway_host="127.0.0.1",
            gateway_port=0,
        )
        core = CoreLifecycle(
            settings,
            domain_key_provider=InMemoryKeyProvider(),
            gateway_key_provider=InMemoryKeyProvider(),
        )
        core.startup()
        try:
            client = TestClient(create_app(core))
            auth = {"Authorization": f"Bearer {core.local_token}"}

            def get(path: str) -> Any:
                return client.get(path, headers=auth).json()

            def err(response: Any) -> dict[str, Any]:
                return {"status": response.status_code, "body": response.json()}

            out["devices-off"] = get("/v1/devices")
            out["error-gateway-off"] = err(client.post("/v1/devices/pairing", headers=auth))
            out["gateway-on"] = client.patch(
                "/v1/devices/gateway", json={"enabled": True}, headers=auth
            ).json()
            out["pairing-open"] = client.post("/v1/devices/pairing", headers=auth).json()
            out["devices-pairing-open"] = get("/v1/devices")

            phone = Phone(root / "phone", "Pixel 8")
            started = phone.start_pairing(out["pairing-open"]["qr_text"])
            assert started.status == 200, started.body
            session_id = started.json()["session_id"]
            out["devices-pairing-pending"] = get("/v1/devices")
            digits = out["devices-pairing-pending"]["gateway"]["pairing"]["fingerprint"]
            wrong = f"{(int(digits) + 1) % 1_000_000:06d}"
            out["error-fingerprint-mismatch"] = err(
                client.post(
                    "/v1/devices/pairing/approve", json={"fingerprint": wrong}, headers=auth
                )
            )
            out["pairing-approved"] = client.post(
                "/v1/devices/pairing/approve", json={"fingerprint": digits}, headers=auth
            ).json()
            finished = phone.poll_pairing(session_id)
            assert finished.status == 200, finished.body
            phone.finish_pairing(finished)
            phone.kernel.command(
                "account.create",
                json.dumps({"id": "acct-phone-01", "name": "Phone cash", "currency": "USD"}),
            )
            assert phone.push().status == 200
            out["devices-paired"] = get("/v1/devices")

            client.post("/v1/devices/pairing", headers=auth)
            out["pairing-denied"] = client.post("/v1/devices/pairing/deny", headers=auth).json()
            out["devices-pairing-denied"] = get("/v1/devices")

            out["revoked"] = client.post(
                f"/v1/devices/{phone.device_id}/revoke", headers=auth
            ).json()
            out["devices-revoked"] = get("/v1/devices")
            out["error-unknown-device"] = err(
                client.post("/v1/devices/no-such-device/revoke", headers=auth)
            )
            out["gateway-off"] = client.patch(
                "/v1/devices/gateway", json={"enabled": False}, headers=auth
            ).json()

            blocker = socket.socket()
            blocker.bind(("127.0.0.1", 0))
            blocker.listen(1)
            try:
                settings.gateway_port = blocker.getsockname()[1]
                out["error-gateway-unavailable"] = err(
                    client.patch("/v1/devices/gateway", json={"enabled": True}, headers=auth)
                )
            finally:
                blocker.close()
            out["error-unauthorized"] = err(client.get("/v1/devices"))
        finally:
            core.shutdown()

    seen: dict[str, str] = {}
    return {key: normalise(value, seen) for key, value in out.items()}


def render(fixtures: dict[str, Any]) -> dict[str, str]:
    return {
        f"{name}.json": json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        for name, data in fixtures.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed fixtures differ"
    )
    args = parser.parse_args()
    files = render(build())
    if args.check:
        stale = [
            name
            for name, text in files.items()
            if not (FIXTURE_DIR / name).exists()
            or (FIXTURE_DIR / name).read_text(encoding="utf-8") != text
        ]
        extra = (
            sorted(p.name for p in FIXTURE_DIR.glob("*.json") if p.name not in files)
            if FIXTURE_DIR.exists()
            else []
        )
        if stale or extra:
            print("fixtures out of date:", stale, "unexpected:", extra)
            return 1
        print(f"{len(files)} fixtures are current")
        return 0
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (FIXTURE_DIR / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(files)} fixtures to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

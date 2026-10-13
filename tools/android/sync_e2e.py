"""Host side of the Android sync end-to-end test (androidTest/.../SyncE2eTest.kt).

    python tools/android/sync_e2e.py --serial emulator-5554

What it does, on throw-away data only (temp directory, in-memory key vaults, never your real vault):
  1. starts a Core with the pairing gateway on 127.0.0.1:<port>; `adb reverse` lets the device in
  2. needs app-debug.apk and app-debug-androidTest.apk to be installed already
  3. runs SyncE2eTest on the device and plays the PC: opens pairing, checks the 6 digits match,
     approves through the Core API, adds an account and an expense on the PC, revokes the phone
  4. checks that both Kernels end identical and that the sync after revoke is refused

Exit code 0 only if every check passed. Prints one JSON summary line at the end.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MAILBOX = "/data/local/tmp/reva-sync-e2e"  # shell-writable, readable by the app under test
RUNNER = "app.reva.android.test/androidx.test.runner.AndroidJUnitRunner"


def _adb() -> str:
    home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not home:
        raise SystemExit("set ANDROID_HOME")
    return str(Path(home) / "platform-tools" / "adb.exe")


class Device:
    def __init__(self, serial: str) -> None:
        self.serial = serial
        self.adb = _adb()

    def run(self, *args: str, check: bool = True) -> str:
        done = subprocess.run(  # noqa: S603 - adb from the SDK, fixed arguments
            [self.adb, "-s", self.serial, *args], capture_output=True, text=True, check=False
        )
        if check and done.returncode != 0:
            raise RuntimeError(f"adb {' '.join(args)} failed: {done.stderr or done.stdout}")
        return done.stdout

    def send(self, name: str, text: str = "go") -> None:
        """Atomically drop a file in the mailbox (push to a temp name, rename on the device)."""
        with tempfile.NamedTemporaryFile(
            "w", delete=False, suffix=".txt", encoding="utf-8"
        ) as handle:
            handle.write(text)
        try:
            self.run("push", handle.name, f"{MAILBOX}/{name}.tmp")
            self.run(
                "shell", f"chmod 666 {MAILBOX}/{name}.tmp; mv {MAILBOX}/{name}.tmp {MAILBOX}/{name}"
            )
        finally:
            os.unlink(handle.name)


class Instrumentation:
    """`am instrument -r` output, one status line at a time."""

    def __init__(self, device: Device) -> None:
        self.lines: queue.Queue[str] = queue.Queue()
        self.log: list[str] = []
        command = [
            device.adb, "-s", device.serial, "shell", "am", "instrument", "-w", "-r",
            "-e", "class", "app.reva.SyncE2eTest", "-e", "syncMailbox", MAILBOX, RUNNER,
        ]  # fmt: skip
        self.process = subprocess.Popen(  # noqa: S603 - adb from the SDK, fixed arguments
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            line = line.rstrip()
            self.log.append(line)
            self.lines.put(line)
        self.lines.put("<<eof>>")

    def expect(self, key: str, timeout: float = 120) -> str:
        """Wait for `INSTRUMENTATION_STATUS: key=value` and return the value."""
        pattern = re.compile(rf"^INSTRUMENTATION_STATUS: {re.escape(key)}=(.*)$")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=1)
            except queue.Empty:
                continue
            if line == "<<eof>>":
                raise RuntimeError(f"the test ended before '{key}':\n" + "\n".join(self.log[-30:]))
            match = pattern.match(line)
            if match:
                return match.group(1)
        raise RuntimeError(f"timed out waiting for '{key}':\n" + "\n".join(self.log[-30:]))

    def result(self, timeout: float = 90) -> str:
        self.process.wait(timeout=timeout)
        return "\n".join(self.log)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--port", type=int, default=47831)
    args = parser.parse_args()

    from fastapi.testclient import TestClient

    from reva_core.api.app import create_app
    from reva_core.config.settings import load_settings
    from reva_core.domains.keys import InMemoryKeyProvider
    from reva_core.orchestration.lifecycle import CoreLifecycle

    device = Device(args.serial)
    summary: dict[str, object] = {
        "serial": args.serial,
        "sdk": device.run("shell", "getprop", "ro.build.version.sdk").strip(),
    }
    work = Path(tempfile.mkdtemp(prefix="reva-sync-e2e-"))
    settings = load_settings(
        _env_file=None,
        data_dir=work / "core",
        domain_keystore="memory",
        gateway_host="127.0.0.1",
        gateway_port=args.port,
    )
    lifecycle = CoreLifecycle(
        settings,
        domain_key_provider=InMemoryKeyProvider(),
        gateway_key_provider=InMemoryKeyProvider(),
    )
    lifecycle.startup()
    client = TestClient(create_app(lifecycle))
    headers = {"Authorization": f"Bearer {lifecycle.local_token}"}
    run: Instrumentation | None = None
    try:
        enabled = client.patch("/v1/devices/gateway", json={"enabled": True}, headers=headers)
        assert enabled.status_code == 200, enabled.text
        port = enabled.json()["gateway"]["port"]
        device.run("reverse", f"tcp:{port}", f"tcp:{port}")
        device.run("shell", f"rm -rf {MAILBOX}; mkdir -p {MAILBOX}; chmod 777 {MAILBOX}")
        # The device clock must be near this PC's (requests are valid for 2 minutes either side).
        skew = abs(int(device.run("shell", "date", "+%s").strip()) - int(time.time()))
        summary["clock_skew_seconds"] = skew
        assert skew < 60, f"device clock differs from the PC by {skew}s"

        def post(path: str, body: dict) -> dict:
            reply = client.post(path, json=body, headers=headers)
            assert reply.status_code in (200, 201), (path, reply.status_code, reply.text)
            return reply.json()

        post(
            "/v1/domains/finance/accounts", {"id": "acct-main-1", "name": "Main", "currency": "USD"}
        )

        run = Instrumentation(device)
        assert run.expect("e2e") == "ready"
        qr = post("/v1/devices/pairing", {})["qr_text"]
        device.send("qr", qr)

        phone_digits = run.expect("fingerprint")
        pc_view = client.get("/v1/devices", headers=headers).json()["gateway"]["pairing"]
        assert pc_view["state"] == "pending", pc_view
        assert pc_view["fingerprint"] == phone_digits, (
            f"digits differ: PC {pc_view['fingerprint']} phone {phone_digits}"
        )
        summary["fingerprint_match"] = phone_digits
        post("/v1/devices/pairing/approve", {"fingerprint": phone_digits})
        paired_id = run.expect("paired")
        summary["paired_device_id"] = paired_id

        device.send("go_sync1")
        summary["sync1"] = run.expect("sync1")
        assert run.expect("phone_expense") == "added"
        pc_expense = {
            "id": "tx-pc-e2e-0001",
            "account_id": "acct-main-1",
            "date": "2026-10-02",
            "amount_minor": -1250,
            "description": "PC lunch (e2e)",
        }
        post("/v1/domains/finance/transactions", pc_expense)
        device.send("go_sync2")
        summary["sync2"] = run.expect("sync2")
        phone_digest = run.expect("digest")
        phone_transactions = sorted(run.expect("transactions").split("|"))
        pc_digest = lifecycle.domain_service.handle("finance").projection_digest()
        assert phone_digest == pc_digest, f"state differs: phone {phone_digest} PC {pc_digest}"
        assert phone_transactions == ["PC lunch (e2e)", "Phone taxi (e2e)"], phone_transactions
        pc_items = client.get("/v1/domains/finance/transactions", headers=headers).json()["items"]
        assert sorted(i["description"] for i in pc_items) == phone_transactions
        summary["both_match"] = True

        revoked = client.post(f"/v1/devices/{paired_id}/revoke", headers=headers)
        assert revoked.status_code == 200 and revoked.json()["changed"] is True, revoked.text
        device.send("go_revoked")
        assert run.expect("after_revoke") == "unauthorized"
        summary["sync_after_revoke"] = "refused (401)"

        output = run.result()
        assert "OK (1 test)" in output, output[-1500:]
        summary["instrumentation"] = "OK (1 test)"
        summary["result"] = "PASS"
        print(json.dumps(summary))
        return 0
    except Exception as exc:  # noqa: BLE001 - report and fail
        summary["result"] = "FAIL"
        summary["error"] = str(exc)[:1500]
        print(json.dumps(summary))
        return 1
    finally:
        if run is not None and run.process.poll() is None:
            run.process.kill()
        device.run("reverse", "--remove-all", check=False)
        device.run("shell", f"rm -rf {MAILBOX}", check=False)
        lifecycle.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())

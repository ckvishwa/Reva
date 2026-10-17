"""Collect Android voice-session resource observations without claiming a hardware pass.

Run on two documented physical phone tiers, each for 30 minutes while an operator
conducts an active Talk session. The output is local JSONL; no transcript or key is read.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def adb_path() -> str:
    path = shutil.which("adb")
    if path is None:
        raise RuntimeError("adb is not installed")
    return path


def adb(serial: str, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed adb binary and argument vector, no shell
        [adb_path(), "-s", serial, "shell", *args],
        capture_output=True,
        text=True,
        timeout=25,
        check=True,
    )
    return result.stdout


def field(text: str, pattern: str) -> int | None:
    found = re.search(pattern, text, re.MULTILINE)
    return int(found.group(1)) if found else None


def sample(serial: str) -> dict[str, object]:
    battery = adb(serial, "dumpsys", "battery")
    memory = adb(serial, "dumpsys", "meminfo", "app.reva")
    cpu = adb(serial, "dumpsys", "cpuinfo")
    thermal = adb(serial, "dumpsys", "thermalservice")
    cpu_match = re.search(r"(?m)^\s*([\d.]+)%\s+\d+/app\.reva(?:\s|:)", cpu)
    return {
        "recorded_at_utc": datetime.now(UTC).isoformat(),
        "battery_percent": field(battery, r"^\s*level:\s*(\d+)\s*$"),
        "battery_temperature_tenths_c": field(battery, r"^\s*temperature:\s*(-?\d+)\s*$"),
        "total_pss_kb": field(memory, r"^\s*TOTAL\s+(\d+)\s+"),
        "cpu_percent_dumpsys_window": float(cpu_match.group(1)) if cpu_match else None,
        "thermal_status": field(thermal, r"(?i)\b(?:Thermal Status|mStatus):\s*(\d+)"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True, help="adb serial of a physical phone")
    parser.add_argument(
        "--tier", required=True, help="documented device tier, e.g. midrange or flagship"
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--minutes", type=float, default=30)
    parser.add_argument("--interval-seconds", type=float, default=60)
    args = parser.parse_args()
    if args.minutes <= 0 or args.interval_seconds <= 0:
        parser.error("duration and interval must be positive")
    devices = subprocess.run(  # noqa: S603 - fixed adb binary and arguments, no shell
        [adb_path(), "devices", "-l"], capture_output=True, text=True, check=True
    ).stdout
    if not any(
        line.startswith(args.serial + "\tdevice ") and "model:" in line
        for line in devices.splitlines()
    ):
        parser.error("the specified physical phone must be online with a visible model")
    model_line = next(
        line for line in devices.splitlines() if line.startswith(args.serial + "\tdevice ")
    )
    if "emulator" in model_line.lower() or args.serial.startswith("emulator-"):
        parser.error("an emulator cannot provide physical battery/thermal evidence")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.minutes * 60
    with args.out.open("w", encoding="utf-8") as output:
        output.write(
            json.dumps(
                {
                    "type": "start",
                    "tier": args.tier,
                    "device": model_line,
                    "duration_minutes": args.minutes,
                    "interval_seconds": args.interval_seconds,
                    "status": "observations_only",
                }
            )
            + "\n"
        )
        while True:
            observation = sample(args.serial)
            output.write(json.dumps({"type": "sample", **observation}) + "\n")
            output.flush()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(args.interval_seconds, remaining))
        output.write(
            json.dumps(
                {
                    "type": "end",
                    "recorded_at_utc": datetime.now(UTC).isoformat(),
                    "status": "observations_only",
                }
            )
            + "\n"
        )


if __name__ == "__main__":
    main()

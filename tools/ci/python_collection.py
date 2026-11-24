"""Prove the former Windows selections remain in the full suite; audit native results."""

from __future__ import annotations

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NATIVE = {
    "test_native_dpapi_round_trip_and_ciphertext",
    "test_native_dpapi_rejects_other_purpose_and_tampering",
}


def collect(name: str, args: list[str]) -> set[str]:
    result = subprocess.run(  # noqa: S603 - fixed CI commands
        [sys.executable, "-m", "pytest", "--collect-only", "-q", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    identifiers = {
        line.strip()
        for line in result.stdout.splitlines()
        if line.startswith("tests/") and "::" in line
    }
    if not identifiers:
        raise RuntimeError(f"Empty collection: {name}\n{result.stdout}\n{result.stderr}")
    Path(f"collection-{name}.txt").write_text(
        "\n".join(sorted(identifiers)) + "\n", encoding="utf-8"
    )
    print(f"{name}: {len(identifiers)} test identifiers")
    return identifiers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify-results", action="store_true")
    args = parser.parse_args()
    if args.verify_results:
        if sys.platform != "win32":
            raise RuntimeError("Native Windows protection must run on Windows")
        cases = ET.parse("pytest-results.xml").getroot().iter("testcase")  # noqa: S314
        passed = {
            case.attrib["name"]
            for case in cases
            if case.attrib.get("classname") == "tests.security.test_platform_protection"
            and not any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
        }
        if not passed >= NATIVE:
            raise RuntimeError(f"Native DPAPI checks did not pass: {NATIVE - passed}")
        print("Both native DPAPI tests passed in the coverage run")
        return
    full = collect("full", [])
    old = collect(
        "former-suites",
        [
            "tests/unit",
            "tests/integration",
            "tests/contract",
            "tests/security",
            "tests/e2e",
        ],
    )
    native = collect("native", ["tests/security/test_platform_protection.py", "-k", "native_dpapi"])
    if not old <= full or not native <= full:
        raise RuntimeError(f"Lost test identifiers: {(old | native) - full}")
    if {item.rsplit("::", 1)[-1] for item in native} != NATIVE:
        raise RuntimeError(f"Unexpected native protection collection: {native}")
    print(
        f"All {len(old)} former suite IDs and {len(native)} native IDs covered; "
        f"{len(full - old)} additional full-suite IDs retained"
    )


if __name__ == "__main__":
    main()

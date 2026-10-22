"""Prove an APK carries a freshly built Kernel library, not a stale one.

    python tools/android/verify_apk_kernel.py [--apk PATH] [--expect-string TEXT]

For each ABI the APK ships (arm64-v8a, x86_64) it checks that
  1. lib/<abi>/libreva_kernel.so inside the APK has the same machine code and read-only data as the file
     cargo just built (target/<triple>/release/libreva_kernel.so). Gradle strips debug symbols while
     packaging, so the two files differ as a whole; the loadable .text and .rodata sections do not, and
     their SHA-256 is compared instead;
  2. that build is newer than the newest Kernel source (kernel/src, kernel/Cargo.toml, Cargo.lock);
  3. optionally, that the library contains --expect-string, a literal only the newest Kernel code has.

Gradle never rebuilds the native library, so an instrumented run can pass against a stale one
(GYM-02 did exactly that once). Exit code 0 only if every ABI passes. Prints one JSON summary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ABIS = {"arm64-v8a": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
APK = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
LIB = "libreva_kernel.so"
ELF_MAGIC = bytes([0x7F]) + b"ELF"
NUL = bytes([0])


def newest_source() -> tuple[float, Path]:
    candidates = [ROOT / "Cargo.lock", ROOT / "kernel" / "Cargo.toml", *(ROOT / "kernel" / "src").rglob("*.rs")]
    existing = [p for p in candidates if p.is_file()]
    newest = max(existing, key=lambda p: p.stat().st_mtime)
    return newest.stat().st_mtime, newest


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_fingerprint(elf: bytes) -> str:
    """SHA-256 over the .text and .rodata sections of a 64-bit little-endian ELF shared object."""
    if elf[:4] != ELF_MAGIC or elf[4] != 2:
        raise ValueError("not a 64-bit ELF file")
    shoff = struct.unpack_from("<Q", elf, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 0x3A)
    headers = []
    for i in range(shnum):
        at = shoff + i * shentsize
        name = struct.unpack_from("<I", elf, at)[0]
        offset, size = struct.unpack_from("<QQ", elf, at + 0x18)
        headers.append((name, offset, size))
    names_at = headers[shstrndx][1]
    sections = {}
    for name, offset, size in headers:
        end = elf.index(NUL, names_at + name)
        sections[elf[names_at + name : end].decode()] = (offset, size)
    digest = hashlib.sha256()
    for wanted in (".text", ".rodata"):
        offset, size = sections[wanted]
        digest.update(wanted.encode())
        digest.update(elf[offset : offset + size])
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apk", type=Path, default=APK)
    parser.add_argument("--expect-string", default=None)
    args = parser.parse_args()

    target_dir = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    source_time, source_file = newest_source()
    report: dict[str, object] = {
        "apk": str(args.apk),
        "newest_kernel_source": str(source_file.relative_to(ROOT)),
        "abis": {},
    }
    ok = True
    with zipfile.ZipFile(args.apk) as apk:
        for abi, triple in ABIS.items():
            built = target_dir / triple / "release" / LIB
            entry: dict[str, object] = {}
            checks: dict[str, bool] = {}
            if not built.is_file():
                checks["built_library_exists"] = False
            else:
                packaged = apk.read(f"lib/{abi}/{LIB}")
                built_bytes = built.read_bytes()
                checks["packaged_code_equals_built_code"] = code_fingerprint(packaged) == code_fingerprint(built_bytes)
                checks["built_after_newest_source"] = built.stat().st_mtime >= source_time
                if args.expect_string is not None:
                    checks["contains_expected_string"] = args.expect_string.encode() in packaged
                entry.update(
                    packaged_sha256=sha256(packaged),
                    packaged_bytes=len(packaged),
                    built_bytes=len(built_bytes),
                    code_fingerprint=code_fingerprint(packaged),
                    built_at=built.stat().st_mtime,
                    newest_source_at=source_time,
                )
            entry["checks"] = checks
            entry["pass"] = bool(checks) and all(checks.values())
            ok = ok and bool(entry["pass"])
            report["abis"][abi] = entry  # type: ignore[index]
    report["pass"] = ok
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

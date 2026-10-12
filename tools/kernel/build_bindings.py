"""Build the Kernel library and generate the Python and Kotlin bindings.

Usage:  python tools/kernel/build_bindings.py [--release]

Outputs (all git-ignored, never hand-edited):
  kernel/bindings/python/reva_kernel.py + the native library next to it
  kernel/bindings/kotlin/uniffi/reva_kernel/reva_kernel.kt
On Windows the vendored OpenSSL build needs Perl (Strawberry Perl) on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def library_name() -> str:
    if sys.platform.startswith("win"):
        return "reva_kernel.dll"
    if sys.platform == "darwin":
        return "libreva_kernel.dylib"
    return "libreva_kernel.so"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)  # noqa: S603 - fixed argv


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true")
    args = parser.parse_args()
    profile = "release" if args.release else "debug"
    flag = ["--release"] if args.release else []

    run(["cargo", "build", "-p", "reva-kernel", "-p", "reva-kernel-bindgen", *flag])
    target = ROOT / "target" / profile
    library = target / library_name()
    bindgen = target / (
        "uniffi-bindgen.exe" if sys.platform.startswith("win") else "uniffi-bindgen"
    )

    out = ROOT / "kernel" / "bindings"
    for language, sub in (("python", "python"), ("kotlin", "kotlin")):
        directory = out / sub
        directory.mkdir(parents=True, exist_ok=True)
        run(
            [
                str(bindgen),
                "generate",
                "--library",
                str(library),
                "--language",
                language,
                "--out-dir",
                str(directory),
            ]
        )
    shutil.copy2(library, out / "python" / library.name)
    print(f"bindings written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

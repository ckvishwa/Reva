"""Fingerprint only public compiler/build inputs, never runtime data or credentials."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

fingerprint = hashlib.sha256()
fingerprint.update(subprocess.check_output(["rustc", "-vV"]))  # noqa: S603,S607
for name in (
    "REVA_CACHE_TARGET",
    "RUSTFLAGS",
    "CARGO_ENCODED_RUSTFLAGS",
    "RUSTDOCFLAGS",
    "CARGO_BUILD_TARGET",
    "CC",
    "CXX",
    "CFLAGS",
    "CXXFLAGS",
    "LDFLAGS",
    "ImageOS",
    "ImageVersion",
    "ANDROID_NDK_HOME",
    "ANDROID_NDK_LATEST_HOME",
):
    fingerprint.update(f"{name}={os.environ.get(name, '')}\n".encode())
# Tracked inputs only: do not traverse restored target artifacts or runtime state.
tracked = subprocess.check_output(  # noqa: S603,S607
    [  # noqa: S607 - fixed git executable on CI runner
        "git",
        "ls-files",
        "-z",
        "Cargo.*",
        "kernel",
        ".cargo",
        "rust-toolchain*",
        "tools/kernel",
        "tools/ci/rust_cache_key.py",
        ".github/actions/rust-cache",
        ".github/workflows/ci.yml",
    ]
)
for filename in sorted(tracked.decode().split("\0")):
    if filename:
        path = Path(filename)
        fingerprint.update(path.as_posix().encode())
        fingerprint.update(path.read_bytes())
for name in ("ANDROID_NDK_HOME", "ANDROID_NDK_LATEST_HOME"):
    if os.environ.get(name):
        properties = Path(os.environ[name]) / "source.properties"
        if properties.is_file():
            fingerprint.update(properties.read_bytes())
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"key={fingerprint.hexdigest()}\n")

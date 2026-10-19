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
for pattern in (
    "Cargo.lock",
    "**/Cargo.toml",
    "**/*.rs",
    ".cargo/*",
    "rust-toolchain*",
    "tools/kernel/*.py",
    ".github/actions/rust-cache/*",
    ".github/workflows/ci.yml",
):
    for path in sorted(Path().glob(pattern)):
        if path.is_file() and "target" not in path.parts:
            fingerprint.update(path.as_posix().encode())
            fingerprint.update(path.read_bytes())
for name in ("ANDROID_NDK_HOME", "ANDROID_NDK_LATEST_HOME"):
    if os.environ.get(name):
        properties = Path(os.environ[name]) / "source.properties"
        if properties.is_file():
            fingerprint.update(properties.read_bytes())
with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
    output.write(f"key={fingerprint.hexdigest()}\n")

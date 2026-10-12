"""Build the debug-signed REVA Android APK you can sideload.

Usage:  python tools/android/build_apk.py [--skip-kernel] [--task assembleDebug]

Steps (each prints what it does):
  1. python tools/kernel/build_bindings.py   Kotlin binding for the Domain Kernel (kernel/bindings, git-ignored)
  2. python tools/kernel/build_android.py    libreva_kernel.so for arm64-v8a and x86_64, verified with readelf
  3. copy the two libraries to android/app/build/kernel-libs/<abi>/
  4. android/gradlew :app:assembleDebug      signed with the standard Android debug key

Output: android/app/build/outputs/apk/debug/app-debug.apk (path and SHA-256 are printed).
Needs: JDK 17+, the Android SDK (ANDROID_HOME) with platform 36, and what tools/kernel/build_android.py needs.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
ABIS = {"arm64-v8a": "aarch64-linux-android", "x86_64": "x86_64-linux-android"}
APK = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"


def run(cmd: list[str], cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)  # noqa: S603 - fixed argv built here


def find_sdk(env: dict[str, str]) -> str:
    for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if env.get(key) and Path(env[key]).is_dir():
            return env[key]
    local = Path.home() / "AppData" / "Local" / "Android" / "Sdk"
    if local.is_dir():
        return str(local)
    raise SystemExit("Android SDK not found: set ANDROID_HOME")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-kernel", action="store_true", help="reuse the libraries already built")
    parser.add_argument("--task", default="assembleDebug")
    args = parser.parse_args()

    env = dict(os.environ)
    env["ANDROID_HOME"] = find_sdk(env)
    target_dir = Path(env.get("CARGO_TARGET_DIR") or ROOT / "target")

    if not args.skip_kernel:
        run([sys.executable, "tools/kernel/build_bindings.py"], ROOT, env)
        run([sys.executable, "tools/kernel/build_android.py"], ROOT, env)

    for abi, triple in ABIS.items():
        source = target_dir / triple / "release" / "libreva_kernel.so"
        if not source.exists():
            raise SystemExit(f"missing {source}: run without --skip-kernel")
        destination = ANDROID / "app" / "build" / "kernel-libs" / abi
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / "libreva_kernel.so")
        print(f"copied {abi}: {source.stat().st_size} bytes")

    gradlew = str(ANDROID / ("gradlew.bat" if sys.platform.startswith("win") else "gradlew"))
    run([gradlew, f":app:{args.task}", "--console=plain"], ANDROID, env)

    if args.task == "assembleDebug":
        if not APK.exists():
            raise SystemExit(f"expected APK not found: {APK}")
        digest = hashlib.sha256(APK.read_bytes()).hexdigest()
        print(f"\nAPK: {APK}\nsize: {APK.stat().st_size} bytes\nsha256: {digest}")
        print(f"Install: adb install -r \"{APK}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())

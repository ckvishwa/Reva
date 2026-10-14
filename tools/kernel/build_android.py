"""Cross-build the Domain Kernel for Android (arm64-v8a, x86_64) with cargo-ndk and verify it.

Usage:  python tools/kernel/build_android.py

Needs: rustup targets aarch64-linux-android and x86_64-linux-android, `cargo install cargo-ndk`,
and the Android NDK (ANDROID_NDK_HOME, or the newest one under ANDROID_HOME/ndk).

SQLCipher links a vendored OpenSSL, which is built from source with Perl. On Linux and macOS
that just works. On a Windows host the OpenSSL Configure script needs a Unix-style Perl:
this script uses the Perl that ships with Git for Windows, adds the few pure-Perl modules that
Perl lacks (copied from Strawberry Perl), and puts a `make` on PATH (Strawberry's mingw32-make).
Nothing is installed or modified outside <repo>/../_tools.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT.parent / "_tools"
ABIS = {
    "arm64-v8a": ("aarch64-linux-android", "AArch64"),
    "x86_64": ("x86_64-linux-android", "X86-64"),
}
PERL_MODULE_DIRS = ["ExtUtils", "Locale", "Text", "Module", "Params", "Pod"]


def find_ndk() -> Path:
    env = os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_LATEST_HOME")
    if env and Path(env).is_dir():
        return Path(env)
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk and (Path(sdk) / "ndk").is_dir():
        versions = sorted(p for p in (Path(sdk) / "ndk").iterdir() if p.is_dir())
        if versions:
            return versions[-1]
    raise SystemExit("Android NDK not found: set ANDROID_NDK_HOME")


def windows_env(env: dict[str, str]) -> dict[str, str]:
    git_perl = Path(r"C:\Program Files\Git\usr\bin")
    strawberry = Path(r"C:\Strawberry")
    if not (git_perl / "perl.exe").exists() or not strawberry.exists():
        raise SystemExit(
            "Windows host needs Git for Windows and Strawberry Perl (see this file's docstring)"
        )
    shim = TOOLS / "makeshim"
    shim.mkdir(parents=True, exist_ok=True)
    if not (shim / "make.exe").exists():
        shutil.copy2(strawberry / "c" / "bin" / "mingw32-make.exe", shim / "make.exe")
    perllib = TOOLS / "perllib"
    for name in PERL_MODULE_DIRS:
        source = strawberry / "perl" / "lib" / name
        if source.is_dir():
            shutil.copytree(source, perllib / name, dirs_exist_ok=True)
    env = dict(env)
    env["PATH"] = os.pathsep.join(
        [str(git_perl), str(shim), str(strawberry / "c" / "bin"), env["PATH"]]
    )
    posix = perllib.as_posix()
    env["PERL5LIB"] = f"/{posix[0].lower()}{posix[2:]}" if posix[1:2] == ":" else posix
    env["MSYS2_ENV_CONV_EXCL"] = "PERL5LIB"
    return env


def main() -> int:
    ndk = find_ndk()
    env = dict(os.environ, ANDROID_NDK_HOME=str(ndk))
    if sys.platform.startswith("win"):
        env = windows_env(env)
    cmd = ["cargo", "ndk"]
    for abi in ABIS:
        cmd += ["-t", abi]
    cmd += ["-P", "26", "build", "-p", "reva-kernel", "--release"]
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)  # noqa: S603 - fixed argv

    prebuilt = next((ndk / "toolchains" / "llvm" / "prebuilt").iterdir())
    readelf = (
        prebuilt
        / "bin"
        / ("llvm-readelf.exe" if sys.platform.startswith("win") else "llvm-readelf")
    )

    def inspect(flag: str, library: Path) -> str:
        command = [str(readelf), flag, str(library)]
        out = subprocess.run(command, capture_output=True, text=True, check=True)  # noqa: S603
        return out.stdout.lower()

    target_dir = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "target")
    failures = 0
    for abi, (triple, machine) in ABIS.items():
        library = target_dir / triple / "release" / "libreva_kernel.so"
        if not library.exists():
            print(f"FAIL {abi}: {library} missing")
            failures += 1
            continue
        header = inspect("-h", library)
        symbols = inspect("--dyn-syms", library)
        needed = inspect("-d", library)
        right_machine = machine.lower() in header or "advanced micro devices x86-64" in header
        exports = "uniffi_reva_kernel_fn_func_open_domain" in symbols
        static_tls = "libssl" not in needed and "libcrypto" not in needed
        ok = right_machine and exports and static_tls
        status = "OK  " if ok else "FAIL"
        size = library.stat().st_size
        detail = f"{size} bytes, {machine}, exports open_domain, OpenSSL linked statically"
        print(f"{status} {abi}: {detail}")
        failures += 0 if ok else 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

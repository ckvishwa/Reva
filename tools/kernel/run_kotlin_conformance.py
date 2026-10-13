"""Compile and run the Kotlin/JVM conformance runner against the built Kernel library.

Usage:  python tools/kernel/run_kotlin_conformance.py
Env:    REVA_TOOLS_DIR   Kotlin compiler and jar cache (default: <repo>/../_tools/kotlin)

Run tools/kernel/build_bindings.py first. Tool downloads are pinned by SHA-256 below and
come only from GitHub releases and Maven Central.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JAVA = shutil.which("java") or "java"
TOOLS = Path(os.environ.get("REVA_TOOLS_DIR", ROOT.parent / "_tools" / "kotlin"))

DOWNLOADS = {
    "kotlin-compiler-2.0.21.zip": (
        "https://github.com/JetBrains/kotlin/releases/download/v2.0.21/kotlin-compiler-2.0.21.zip",
        "0352c0a45bd22f80f6b26e485cd04da8047baa5de54865281fb9f89a4a7bcf2a",
    ),
    "jna-5.14.0.jar": (
        "https://repo1.maven.org/maven2/net/java/dev/jna/jna/5.14.0/jna-5.14.0.jar",
        "34ed1e1f27fa896bca50dbc4e99cf3732967cec387a7a0d5e3486c09673fe8c6",
    ),
    "json-20240303.jar": (
        "https://repo1.maven.org/maven2/org/json/json/20240303/json-20240303.jar",
        "3cf6cd6892e32e2b4c1c39e0f52f5248a2f5b37646fdfbb79a66b46b618414ed",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_tools() -> Path:
    TOOLS.mkdir(parents=True, exist_ok=True)
    for name, (url, digest) in DOWNLOADS.items():
        target = TOOLS / name
        if not target.exists():
            print(f"downloading {name}", flush=True)
            urllib.request.urlretrieve(url, target)  # noqa: S310 - pinned https URLs
        if sha256(target) != digest:
            raise SystemExit(f"{name}: SHA-256 mismatch; delete it and retry")
    compiler = TOOLS / "kotlinc"
    if not compiler.exists():
        with zipfile.ZipFile(TOOLS / "kotlin-compiler-2.0.21.zip") as z:
            z.extractall(TOOLS)
    return compiler


def main() -> int:
    compiler = ensure_tools()
    bindings = ROOT / "kernel" / "bindings"
    python_dir = bindings / "python"
    generated = bindings / "kotlin" / "uniffi" / "reva_kernel" / "reva_kernel.kt"
    if not generated.exists():
        raise SystemExit("run tools/kernel/build_bindings.py first")
    jna = TOOLS / "jna-5.14.0.jar"
    json_jar = TOOLS / "json-20240303.jar"
    classpath = os.pathsep.join([str(jna), str(json_jar)])

    out = Path(tempfile.mkdtemp(prefix="reva-kt-build-"))
    try:
        jar = out / "conformance.jar"
        lib = compiler / "lib"
        sources = [
            str(generated),
            str(ROOT / "kernel" / "tests" / "kotlin" / "ConformanceRunner.kt"),
        ]
        compile_cp = os.pathsep.join([classpath, str(lib / "kotlin-stdlib.jar")])
        # Same invocation the kotlinc script performs, minus the batch-file quoting problems.
        compile_cmd = [
            JAVA, "-Xmx1g",
            "-cp", str(lib / "kotlin-preloader.jar"),
            "org.jetbrains.kotlin.preloading.Preloader",
            "-cp", str(lib / "kotlin-compiler.jar"),
            "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
            "-kotlin-home", str(compiler),
            "-no-stdlib", "-cp", compile_cp,
            *sources,
            "-include-runtime", "-d", str(jar),
        ]  # fmt: skip
        subprocess.run(compile_cmd, check=True)  # noqa: S603 - fixed argv
        run_cmd = [
            JAVA, f"-Djna.library.path={python_dir}",
            "-cp", os.pathsep.join([str(jar), classpath]),
            "ConformanceRunnerKt",
            str(ROOT / "kernel" / "tests" / "conformance" / "finance.json"),
        ]  # fmt: skip
        result = subprocess.run(run_cmd, check=False)  # noqa: S603 - fixed argv
        return result.returncode
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

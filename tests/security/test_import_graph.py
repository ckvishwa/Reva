"""B4: apps never reach into the Kernel or its files (AR-SYS-002, extends AR-009).

The Kernel is reached through one door per app: the Python Core through `reva_core/domains/`, the
Windows app through Core's HTTP API, the Android app through the generated UniFFI binding. These
static checks fail if anything else imports the Kernel binding or opens a domain database.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "reva_core"
KERNEL_NAMES = ("reva_kernel", "kernel_loader")


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def test_only_the_domains_package_imports_the_kernel_binding() -> None:
    offenders = []
    for path in CORE.rglob("*.py"):
        if "domains" in path.relative_to(CORE).parts[:1]:
            continue
        if any(name in module for module in _imports(path) for name in KERNEL_NAMES):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_nothing_outside_the_domains_package_opens_a_domain_file() -> None:
    pattern = re.compile(r"open_domain|\.rdomain|kernel[/\\]bindings")
    offenders = []
    for path in CORE.rglob("*.py"):
        if path.relative_to(CORE).parts[0] in ("domains", "config"):  # config names a path setting
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_the_windows_app_never_references_the_kernel_or_a_database_library() -> None:
    desktop = ROOT / "desktop" / "src"
    project = (desktop / "Reva.Desktop" / "Reva.Desktop.csproj").read_text(encoding="utf-8")
    sources = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in desktop.rglob("*.cs")
    )

    assert "reva_kernel" not in project.lower() and "kernel" not in project.lower().replace(
        "kernel32", ""
    )
    assert not re.search(r"Microsoft\.Data\.Sqlite|System\.Data\.SQLite|using\s+.*Uniffi", sources)
    assert "reva_kernel" not in sources


def test_only_the_android_kernel_wrapper_touches_the_binding() -> None:
    android = ROOT / "android"
    if not android.exists():
        return
    uses = []
    for path in android.rglob("*.kt"):
        if {"androidTest", "test", "build"} & set(path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"uniffi\.reva_kernel|reva_kernel", text):
            uses.append(path.relative_to(android).as_posix())

    # The data and sync layers (and the app's composition root) may; screens may not.
    allowed = ("/data/", "/sync/", "/RevaApp.kt")
    assert all(any(marker in f"/{u}" for marker in allowed) for u in uses), uses

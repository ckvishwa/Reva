"""The committed Devices UI fixtures must equal what REVA Core produces today.

The C# contract tests (desktop/tests/Reva.Desktop.Tests/Devices/DevicesContractFixtureTests.cs)
deserialize these files, so this test ties them to the real Core. If it fails, run
`python tools/desktop/generate_devices_fixtures.py`, review the diff, and update the C# types.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from reva_core.domains.kernel_loader import KernelUnavailableError, load_kernel

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "desktop" / "generate_devices_fixtures.py"

try:
    load_kernel()
except KernelUnavailableError as exc:
    pytest.skip(f"Domain Kernel binding not built: {exc}", allow_module_level=True)


def _tool():
    spec = importlib.util.spec_from_file_location("generate_devices_fixtures", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_fixtures_match_the_real_core_responses():
    tool = _tool()
    files = tool.render(tool.build())
    directory = tool.FIXTURE_DIR
    stale = [
        name
        for name, text in files.items()
        if not (directory / name).exists() or (directory / name).read_text(encoding="utf-8") != text
    ]
    extra = sorted(p.name for p in directory.glob("*.json") if p.name not in files)
    assert not stale and not extra, f"fixtures out of date: {stale}; unexpected files: {extra}"
    assert len(files) >= 17

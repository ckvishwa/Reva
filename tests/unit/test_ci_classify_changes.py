"""The CI change classifier must skip build lanes only for changes nothing reads."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "tools" / "ci" / "classify_changes.py"
_SPEC = importlib.util.spec_from_file_location("classify_changes", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
classify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(classify)


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "CLAUDE.md",
        "SECURITY.md",
        "docs/images/android/today.png",
        "docs/architecture/system-overview.md",
        "docs/android/gmail-auth.md",
        "android/README.md",
        "kernel/README.md",
        "docs\\voice\\turn-engine.md",
    ],
)
def test_documentation_paths_do_not_need_the_code_lanes(path: str) -> None:
    assert classify.is_docs_only_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "docs/spec/REVA_v2.0/08_CONTRACTS/capability-registry.v2.json",
        "docs/spec/REVA_v2.0/02_ARD/ARD-200_Cross_Platform_App_v2.0.md",
        "docs/spec/REVA_v2.0/SHA256SUMS.txt",
        "contracts/capability-registry.v2.json",
        "reva_core/api/app.py",
        "kernel/src/lib.rs",
        "android/app/src/main/AndroidManifest.xml",
        "desktop/src/Reva.Desktop/App.xaml.cs",
        "avatar/src/controller.js",
        "tests/evidence/ledger.csv",
        "tests/fixtures/finance_emails/01_debit_purchase.txt",
        "tests/fixtures/notes.md",
        "tools/ci/classify_changes.py",
        ".github/workflows/ci.yml",
        "pyproject.toml",
        "Cargo.lock",
        "assets.manifest.json",
        "notes.txt",
    ],
)
def test_everything_else_needs_the_code_lanes(path: str) -> None:
    assert not classify.is_docs_only_path(path)


def test_one_code_file_among_docs_runs_the_lanes() -> None:
    assert not classify.needs_code_lanes(["README.md", "docs/images/android/today.png"])
    assert classify.needs_code_lanes(["README.md", "reva_core/api/app.py"])


def test_an_empty_or_unknown_diff_runs_the_lanes() -> None:
    assert classify.needs_code_lanes([])
    assert classify.changed_paths("workflow_dispatch", "", "") is None
    assert classify.changed_paths("push", "", "0" * 40) is None
    assert classify.changed_paths("pull_request", "", "") is None


def test_a_bad_revision_is_reported_as_unknown_not_as_no_changes() -> None:
    assert classify.changed_paths("pull_request", "not-a-real-revision", "") is None

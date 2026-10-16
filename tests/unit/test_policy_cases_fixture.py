"""The policy fixtures shared with the Android port must match the Python code.

`tests/fixtures/authorize-cases.json` and `rules-cases.json` are written by
`tools/ci/make_policy_cases.py` from the Python `authorize()`, the registry and the rule fast path,
and replayed by the Kotlin port (`AuthorizeParityTest`, `RulesTest`). This test fails when the
registry, `authorize()` or the rules change without the fixtures being rewritten, so the phone
cannot silently fall behind the PC.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "make_policy_cases", ROOT / "tools/ci/make_policy_cases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixtures_are_what_the_python_code_produces() -> None:
    built = _generator().build()

    for name, data in built.items():
        committed = json.loads((ROOT / "tests/fixtures" / name).read_text(encoding="utf-8"))
        assert committed == json.loads(json.dumps(data)), f"{name} is stale"


def test_the_fixtures_cover_every_decision_reason_and_the_assistant_controls() -> None:
    authorize = json.loads(
        (ROOT / "tests/fixtures/authorize-cases.json").read_text(encoding="utf-8")
    )
    reasons = {c["expected"]["reason"] for c in authorize["cases"]}
    capabilities = {c["proposal"]["capability"] for c in authorize["cases"]}

    assert {
        "OK",
        "FORBIDDEN_CAPABILITY",
        "UNKNOWN_CAPABILITY",
        "INVALID_ARGS",
        "UNRESOLVED_TERMS",
        "LOW_EVIDENCE",
        "AMBIGUOUS_ENTITY",
        "STATE_MISMATCH",
        "CONSENT_REQUIRED",
        "APPROVAL_REQUIRED",
    } <= reasons
    assert {"assistant.stop", "assistant.repeat", "assistant.undo"} <= capabilities

"""The mood engine fixture shared with the Android port must match the Python engine.

`tests/fixtures/mood-cases.json` is written by `tools/ci/make_mood_cases.py` from the Python
engine and replayed by the Kotlin port (`android/.../MoodEngineTest.kt`). This test fails when the
engine or the rules change without the fixture being rewritten, so the Kotlin side cannot silently
fall behind.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _generator():
    spec = importlib.util.spec_from_file_location(
        "make_mood_cases", ROOT / "tools/ci/make_mood_cases.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_fixture_is_what_the_python_engine_produces() -> None:
    generator = _generator()
    committed = json.loads((ROOT / "tests/fixtures/mood-cases.json").read_text(encoding="utf-8"))

    assert committed == json.loads(json.dumps(generator.build()))


def test_the_fixture_exercises_every_mood_and_the_expression_event_paths() -> None:
    committed = json.loads((ROOT / "tests/fixtures/mood-cases.json").read_text(encoding="utf-8"))
    moods = {c["expected"]["mood"] for c in committed["cases"]}
    causes = {(c["expected"]["expression_event"] or {}).get("cause") for c in committed["cases"]}

    assert moods == {
        "calm",
        "happy",
        "playful",
        "flirty",
        "focused",
        "excited",
        "tired",
        "sad",
        "concerned",
    }
    assert {"verified_outcome", "mood", None} <= causes

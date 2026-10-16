"""The session transition table is shared with the Android app through a fixture.

`tests/fixtures/session-transitions.json` is compared with the Core's table here and with the
Kotlin `VoiceTransitions` in `android/.../voice/VoiceSessionTest.kt`. If either side changes a state
or a legal move, one of the two tests fails until both agree again.
"""

from __future__ import annotations

import json
from pathlib import Path

from reva_core.session import state as st

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "session-transitions.json"


def test_the_fixture_matches_the_core_transition_table() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    assert fixture["states"] == [s.value for s in st.SessionState]
    assert fixture["forward"] == {
        k.value: sorted(v.value for v in vs) for k, vs in st._FORWARD.items()
    }
    assert fixture["any_live_may_go"] == sorted(s.value for s in st._ANY_LIVE_STATE_MAY_GO)
    assert fixture["not_live"] == sorted(s.value for s in st._NOT_LIVE)
    assert fixture["interruptible"] == sorted(s.value for s in st.INTERRUPTIBLE)

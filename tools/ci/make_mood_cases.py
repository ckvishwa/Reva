"""Write tests/fixtures/mood-cases.json: inputs and expected outputs of the mood engine.

The Python engine (`reva_core/language/mood.py`) is the reference. The Kotlin port in the Android
app replays these cases and must give the same answer for every one (`MoodEngineTest.kt`); a Python
test regenerates the file in memory and fails if the committed copy is stale.

Usage: python tools/ci/make_mood_cases.py [--check]
"""

from __future__ import annotations

import itertools
import json
import random
import sys
from datetime import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reva_core.language import mood  # noqa: E402
from reva_core.language.mood_flags import utterance_flags  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "mood-cases.json"

EVENTS = [
    mood.VERIFIED_OUTCOME,
    mood.FAILURE,
    mood.APPROVAL_PENDING,
    mood.REFUSAL,
    mood.MILESTONE,
]
FLAGS = [
    mood.URGENT_HEALTH,
    mood.RISKY_REQUEST,
    mood.SAFETY,
    mood.USER_TIRED,
    mood.USER_NOT_TIRED,
    mood.USER_SAD,
    mood.UPSET,
    mood.CASUAL,
    mood.GREETING,
]
DOMAINS = [None, "finance", "health", "memory", "coach", "personal"]
PREVIOUS = [
    mood.MoodState(),
    mood.MoodState(mood.Mood.HAPPY, 1),
    mood.MoodState(mood.Mood.HAPPY, 2),
    mood.MoodState(mood.Mood.EXCITED, 1),
    mood.MoodState(mood.Mood.SAD, 1),
    mood.MoodState(mood.Mood.FOCUSED, 1),
    mood.MoodState(mood.Mood.TIRED, 3, True, 23),
    mood.MoodState(mood.Mood.TIRED, 3, True, 2),
    mood.MoodState(mood.Mood.PLAYFUL, 1),
]
TEXTS = [
    "hello",
    "hey reva",
    "tell me a joke",
    "thanks",
    "I'm so tired",
    "I'm not tired",
    "I'm really sad today",
    "bad news",
    "I'm frustrated",
    "I have chest pain",
    "pay my rent",
    "delete all my files",
    "what is my balance",
    "i got fired",
    "shut up",
    "good morning",
    "open notepad",
    "",
]


def _state(s: mood.MoodState) -> dict[str, Any]:
    return {
        "mood": s.mood.value,
        "turns_in_mood": s.turns_in_mood,
        "tired_held": s.tired_held,
        "tired_since_hour": s.tired_since_hour,
    }


def _case(previous: mood.MoodState, inputs: mood.MoodInputs) -> dict[str, Any]:
    result = mood.next_mood(previous, inputs)
    event = mood.avatar_expression_event(result, inputs)
    return {
        "previous": _state(previous),
        "inputs": {
            "hour": inputs.local_time.hour,
            "minute": inputs.local_time.minute,
            "events": sorted(inputs.events),
            "flags": sorted(inputs.flags),
            "domain": inputs.domain,
            "playfulness": inputs.settings.playfulness,
            "flirty_allowed": inputs.settings.flirty_allowed,
            "follow_time": inputs.settings.follow_time,
            "work_streak": inputs.work_streak,
            "work_app_in_focus": inputs.work_app_in_focus,
            "minutes_since_serious": inputs.minutes_since_serious,
            "action_in_flight": inputs.action_in_flight,
            "verified_action_id": inputs.verified_action_id,
        },
        "expected": {
            "state": _state(result.state),
            "mood": result.mood.value,
            "template_variant": result.template_variant,
            "voice": {
                "rate": result.voice.rate,
                "pitch_st": result.voice.pitch_st,
                "softness": result.voice.softness,
            },
            "avatar": {
                "expression": result.avatar.expression,
                "clip": result.avatar.clip,
                "then": result.avatar.then,
                "soft": result.avatar.soft,
            },
            "reasons": list(result.reasons),
            "expression_event": event,
        },
    }


def build() -> dict[str, Any]:
    rng = random.Random(20261015)  # noqa: S311 - a fixed seed for a reproducible fixture
    cases: list[dict[str, Any]] = []
    # Every single event and every single flag against every previous state and domain.
    for previous, domain in itertools.product(PREVIOUS, DOMAINS):
        for event in [None, *EVENTS]:
            for flag in [None, *FLAGS]:
                if rng.random() > 0.12:  # thinned, but seeded: the same file every time
                    continue
                inputs = mood.MoodInputs(
                    local_time=time(rng.choice([1, 4, 5, 9, 14, 22, 23]), rng.choice([0, 30])),
                    events=frozenset([event] if event else []),
                    flags=frozenset([flag] if flag else []),
                    domain=domain,
                    settings=mood.MoodSettings(
                        playfulness=rng.choice([0, 4, 5, 8, 10]),
                        flirty_allowed=rng.choice([False, True]),
                        follow_time=rng.choice([True, True, False]),
                    ),
                    work_streak=rng.choice([0, 1, 2, 3, 5]),
                    work_app_in_focus=rng.random() < 0.2,
                    minutes_since_serious=rng.choice([None, 2, 9, 10, 30]),
                    action_in_flight=rng.random() < 0.25,
                    verified_action_id=rng.choice([None, "action-0001-abcd"]),
                )
                cases.append(_case(previous, inputs))
    # Low-stakes turns, where the playful and flirty rules can win.
    for _ in range(120):
        inputs = mood.MoodInputs(
            local_time=time(rng.choice([9, 14, 20]), 0),
            events=frozenset(),
            flags=frozenset([rng.choice([mood.CASUAL, mood.GREETING])]),
            domain=rng.choice([None, "coach", "personal", "finance"]),
            settings=mood.MoodSettings(
                playfulness=rng.choice([0, 5, 9]),
                flirty_allowed=rng.random() < 0.5,
                follow_time=True,
            ),
            minutes_since_serious=rng.choice([None, 3, 30]),
            action_in_flight=rng.random() < 0.15,
        )
        cases.append(_case(rng.choice(PREVIOUS), inputs))
    # Multi-flag and multi-event combinations.
    for _ in range(150):
        previous = rng.choice(PREVIOUS)
        inputs = mood.MoodInputs(
            local_time=time(rng.randrange(24), rng.choice([0, 15, 45])),
            events=frozenset(rng.sample(EVENTS, rng.randrange(0, 3))),
            flags=frozenset(rng.sample(FLAGS, rng.randrange(0, 4))),
            domain=rng.choice(DOMAINS),
            settings=mood.MoodSettings(
                playfulness=rng.randrange(0, 11),
                flirty_allowed=rng.random() < 0.5,
                follow_time=rng.random() < 0.8,
            ),
            work_streak=rng.randrange(0, 6),
            work_app_in_focus=rng.random() < 0.3,
            minutes_since_serious=rng.choice([None, 0, 5, 10, 60]),
            action_in_flight=rng.random() < 0.3,
            verified_action_id=rng.choice([None, "action-0002-wxyz"]),
        )
        cases.append(_case(previous, inputs))
    flags = [{"text": t, "flags": sorted(utterance_flags(t))} for t in TEXTS]
    acks = {m.value: [mood.ack_phrase(m, n) for n in range(5)] for m in mood.Mood}
    return {"version": 1, "cases": cases, "utterance_flags": flags, "acks": acks}


def main() -> int:
    text = json.dumps(build(), indent=1, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8").replace("\r\n", "\n")
        if current != text:
            print("tests/fixtures/mood-cases.json is stale; run tools/ci/make_mood_cases.py")
            return 1
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

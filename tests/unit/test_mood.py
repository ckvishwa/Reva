"""B2.3: the mood engine (docs/persona/REVA_Persona.md section 3 and 6)."""

from __future__ import annotations

import ast
import json
from datetime import time
from pathlib import Path

import jsonschema
import pytest

from reva_core.language import mood as m
from reva_core.language.mood import (
    Mood,
    MoodInputs,
    MoodSettings,
    MoodState,
    avatar_expression_event,
    next_mood,
)
from reva_core.language.mood_flags import utterance_flags

ROOT = Path(__file__).resolve().parents[2]
NOON = time(12, 0)
AVATAR_SCHEMA = json.loads((ROOT / "contracts" / "avatar-events.schema.json").read_text("utf-8"))


def go(state: MoodState | None = None, **kwargs):
    kwargs.setdefault("local_time", NOON)
    return next_mood(state or MoodState(), MoodInputs(**kwargs))


def fs(*items: str) -> frozenset[str]:
    return frozenset(items)


# ------------------------------------------------------------------------ the table


def test_every_rule_in_the_table_turns_on_the_right_mood() -> None:
    assert go().mood == Mood.CALM
    assert go(events=fs(m.VERIFIED_OUTCOME)).mood == Mood.HAPPY
    assert go(settings=MoodSettings(playfulness=5), flags=fs(m.CASUAL)).mood == Mood.PLAYFUL
    assert go(settings=MoodSettings(flirty_allowed=True), flags=fs(m.CASUAL)).mood == Mood.FLIRTY
    assert go(work_streak=3).mood == Mood.FOCUSED
    assert go(work_app_in_focus=True).mood == Mood.FOCUSED
    assert go(events=fs(m.MILESTONE)).mood == Mood.EXCITED
    assert go(local_time=time(2, 30)).mood == Mood.TIRED
    assert go(flags=fs(m.USER_TIRED)).mood == Mood.TIRED
    assert go(events=fs(m.FAILURE)).mood == Mood.SAD
    assert go(flags=fs(m.USER_SAD)).mood == Mood.SAD
    assert go(flags=fs(m.URGENT_HEALTH)).mood == Mood.CONCERNED
    assert go(events=fs(m.REFUSAL)).mood == Mood.CONCERNED


def test_the_engine_is_a_pure_function() -> None:
    inputs = MoodInputs(local_time=NOON, events=fs(m.VERIFIED_OUTCOME))
    state = MoodState(Mood.CALM, 3)

    assert next_mood(state, inputs) == next_mood(state, inputs)
    assert state == MoodState(Mood.CALM, 3)  # inputs are not mutated


# --------------------------------------------------------------------------- priority


@pytest.mark.parametrize(
    ("higher", "lower"),
    [
        (dict(flags=fs(m.URGENT_HEALTH)), dict(events=fs(m.FAILURE))),
        (dict(events=fs(m.FAILURE)), dict(local_time=time(3, 0))),
        (dict(local_time=time(3, 0)), dict(work_streak=5)),
        (dict(work_streak=5), dict(events=fs(m.MILESTONE))),
        (dict(events=fs(m.MILESTONE)), dict(events=fs(m.VERIFIED_OUTCOME))),
    ],
)
def test_the_higher_priority_rule_wins_over_the_lower(higher: dict, lower: dict) -> None:
    both = {**lower, **higher}
    for key in ("events", "flags"):
        if key in higher and key in lower:
            both[key] = higher[key] | lower[key]

    assert go(**both).mood == go(**higher).mood


def test_happy_beats_flirty_and_playful_and_flirty_beats_playful() -> None:
    settings = MoodSettings(playfulness=9, flirty_allowed=True)
    casual = fs(m.CASUAL)

    assert go(settings=settings, flags=casual, events=fs(m.VERIFIED_OUTCOME)).mood == Mood.HAPPY
    assert go(settings=settings, flags=casual).mood == Mood.FLIRTY
    assert go(settings=MoodSettings(playfulness=9), flags=casual).mood == Mood.PLAYFUL


# ----------------------------------------------------------------------------- decay


def test_happy_excited_and_sad_return_to_calm_after_two_turns() -> None:
    for trigger, mood in (
        (fs(m.VERIFIED_OUTCOME), Mood.HAPPY),
        (fs(m.MILESTONE), Mood.EXCITED),
        (fs(m.FAILURE), Mood.SAD),
    ):
        first = go(events=trigger)
        second = go(first.state)  # nothing new
        third = go(second.state)
        fourth = go(third.state)

        assert (first.mood, second.mood, third.mood) == (mood, mood, Mood.CALM), mood
        assert fourth.mood == Mood.CALM


def test_a_new_trigger_restarts_the_count() -> None:
    first = go(events=fs(m.VERIFIED_OUTCOME))
    second = go(first.state, events=fs(m.VERIFIED_OUTCOME))
    third = go(second.state)

    assert third.mood == Mood.HAPPY and second.state.turns_in_mood == 1


def test_tired_from_the_clock_ends_at_five() -> None:
    assert go(local_time=time(4, 59)).mood == Mood.TIRED
    assert go(local_time=time(5, 0)).mood == Mood.CALM
    assert go(local_time=time(0, 0)).mood == Mood.TIRED
    assert go(local_time=time(2, 0), settings=MoodSettings(follow_time=False)).mood == Mood.CALM


def test_tired_said_by_the_user_holds_until_five_in_the_morning_or_they_say_otherwise() -> None:
    evening = go(local_time=time(22, 30), flags=fs(m.USER_TIRED))
    later = go(evening.state, local_time=time(23, 40))
    small_hours = go(later.state, local_time=time(1, 0))
    morning = go(small_hours.state, local_time=time(6, 0))
    denied = go(evening.state, local_time=time(23, 0), flags=fs(m.USER_NOT_TIRED))

    assert [evening.mood, later.mood, small_hours.mood] == [Mood.TIRED] * 3
    assert morning.mood == Mood.CALM
    assert denied.mood == Mood.CALM


def test_tired_said_after_midnight_clears_at_five_the_same_morning() -> None:
    said = go(
        local_time=time(3, 0), flags=fs(m.USER_TIRED), settings=MoodSettings(follow_time=False)
    )
    still = go(said.state, local_time=time(4, 0), settings=MoodSettings(follow_time=False))
    gone = go(still.state, local_time=time(5, 30), settings=MoodSettings(follow_time=False))

    assert (said.mood, still.mood, gone.mood) == (Mood.TIRED, Mood.TIRED, Mood.CALM)


def test_focused_holds_while_work_commands_continue() -> None:
    start = go(work_streak=3)
    still = go(start.state, work_streak=1)
    over = go(still.state, work_streak=0)

    assert (start.mood, still.mood, over.mood) == (Mood.FOCUSED, Mood.FOCUSED, Mood.CALM)


# ------------------------------------------------------------------------ overrides


@pytest.mark.parametrize("domain", ["finance", "health", "memory"])
def test_sensitive_domains_only_ever_sound_calm_or_concerned(domain: str) -> None:
    settings = MoodSettings(playfulness=10, flirty_allowed=True)
    for events in (fs(m.VERIFIED_OUTCOME), fs(m.MILESTONE), fs()):
        result = go(domain=domain, events=events, flags=fs(m.CASUAL), settings=settings)
        assert result.mood == Mood.CALM, (domain, events)
    assert go(domain=domain, flags=fs(m.URGENT_HEALTH)).mood == Mood.CONCERNED


def test_money_stays_calm_even_after_a_verified_save() -> None:
    result = go(domain="finance", events=fs(m.VERIFIED_OUTCOME))

    assert result.mood == Mood.CALM
    assert result.voice.rate == 0.95


def test_a_failure_can_sound_sad_but_never_cheerful() -> None:
    result = go(domain="finance", events=fs(m.FAILURE, m.VERIFIED_OUTCOME))

    assert result.mood == Mood.SAD


def test_refusals_and_approvals_are_calm_or_concerned() -> None:
    assert go(events=fs(m.REFUSAL)).mood == Mood.CONCERNED
    approval = go(
        events=fs(m.APPROVAL_PENDING, m.VERIFIED_OUTCOME),
        settings=MoodSettings(playfulness=9, flirty_allowed=True),
        flags=fs(m.CASUAL),
    )
    assert approval.mood == Mood.CALM


# ---------------------------------------------------------------- "no flirty" fixtures


@pytest.mark.parametrize(
    "case",
    [
        dict(domain="finance"),
        dict(domain="health"),
        dict(domain="memory"),
        dict(events=fs(m.FAILURE)),
        dict(events=fs(m.APPROVAL_PENDING)),
        dict(events=fs(m.REFUSAL)),
        dict(flags=fs(m.SAFETY)),
        dict(flags=fs(m.UPSET)),
        dict(flags=fs(m.URGENT_HEALTH)),
        dict(minutes_since_serious=3),
        dict(action_in_flight=True),
    ],
)
def test_flirty_never_happens_in_these_cases(case: dict) -> None:
    kwargs = {"settings": MoodSettings(flirty_allowed=True, playfulness=9), "flags": fs(m.CASUAL)}
    for key, value in case.items():
        kwargs[key] = (kwargs[key] | value) if key == "flags" and key in kwargs else value

    assert go(**kwargs).mood != Mood.FLIRTY


def test_flirty_is_off_by_default_and_needs_a_casual_turn() -> None:
    assert go(flags=fs(m.CASUAL)).mood != Mood.FLIRTY
    assert MoodSettings().flirty_allowed is False
    assert go(settings=MoodSettings(flirty_allowed=True)).mood == Mood.CALM  # not casual
    assert go(settings=MoodSettings(flirty_allowed=True), flags=fs(m.GREETING)).mood == Mood.FLIRTY


def test_flirty_comes_back_after_ten_quiet_minutes() -> None:
    settings = MoodSettings(flirty_allowed=True)

    assert go(settings=settings, flags=fs(m.CASUAL), minutes_since_serious=11).mood == Mood.FLIRTY
    assert go(settings=settings, flags=fs(m.CASUAL), minutes_since_serious=9).mood != Mood.FLIRTY


# ------------------------------------------------------------ voice and avatar mapping


def test_voice_parameters_match_the_persona_table() -> None:
    expected = {
        Mood.CALM: (0.95, 0, "normal"),
        Mood.HAPPY: (1.05, 1, "normal"),
        Mood.PLAYFUL: (1.05, 0, "normal"),
        Mood.FLIRTY: (0.98, 0, "soft"),
        Mood.FOCUSED: (1.0, 0, "normal"),
        Mood.EXCITED: (1.1, 2, "normal"),
        Mood.TIRED: (0.9, -1, "soft"),
        Mood.SAD: (0.92, 0, "soft"),
        Mood.CONCERNED: (0.95, 0, "neutral"),
    }
    rules = m.RULES["tts"]

    for mood, (rate, pitch, softness) in expected.items():
        assert (
            rules[mood.value]["rate"],
            rules[mood.value]["pitch_st"],
            rules[mood.value]["softness"],
        ) == (
            rate,
            pitch,
            softness,
        )


def test_the_avatar_mapping_matches_the_persona_table() -> None:
    table = {
        Mood.CALM: ("relaxed", "idle"),
        Mood.HAPPY: ("happy", "talking"),
        Mood.FOCUSED: ("neutral", "idle"),
        Mood.TIRED: ("relaxed", "idle"),
        Mood.SAD: ("sad", "idle"),
        Mood.CONCERNED: ("sad", "idle"),
    }
    for mood, (expression, clip) in table.items():
        spec = m.RULES["avatar"][mood.value]
        assert (spec["expression"], spec["clip"]) == (expression, clip)
    assert m.RULES["avatar"]["excited"]["expression"] == "surprised"
    assert m.RULES["avatar"]["excited"]["then"] == "happy"
    assert m.RULES["avatar"]["concerned"]["soft"] is True


def test_during_an_approval_the_avatar_is_neutral_in_the_approval_pose() -> None:
    result = go(events=fs(m.APPROVAL_PENDING), action_in_flight=True)

    assert (result.avatar.expression, result.avatar.clip) == ("neutral", "approval")


def test_no_positive_face_while_an_action_is_in_flight() -> None:
    result = go(events=fs(m.MILESTONE), action_in_flight=True)

    assert result.avatar.expression == "neutral"


# --------------------------------------------------------------- avatar.expression events


def valid(event: dict) -> None:
    jsonschema.validate(event, AVATAR_SCHEMA)


def test_a_positive_face_for_a_result_needs_a_verified_outcome_and_its_action_id() -> None:
    inputs = MoodInputs(
        local_time=NOON, events=fs(m.VERIFIED_OUTCOME), verified_action_id="act-12345678"
    )
    result = next_mood(MoodState(), inputs)

    event = avatar_expression_event(result, inputs)

    assert event == {
        "type": "avatar.expression",
        "name": "happy",
        "cause": "verified_outcome",
        "action_id": "act-12345678",
    }
    valid(event)


def test_a_claimed_success_without_evidence_gets_no_expression() -> None:
    inputs = MoodInputs(local_time=NOON, events=fs(m.VERIFIED_OUTCOME), verified_action_id=None)

    assert avatar_expression_event(next_mood(MoodState(), inputs), inputs) is None


def test_result_moods_never_become_a_plain_mood_expression() -> None:
    inputs = MoodInputs(local_time=NOON, events=fs(m.MILESTONE))  # excited, no action id

    assert avatar_expression_event(next_mood(MoodState(), inputs), inputs) is None


def test_no_mood_expression_while_an_action_is_pending_or_executing() -> None:
    for kwargs in (dict(action_in_flight=True), dict(events=fs(m.APPROVAL_PENDING))):
        inputs = MoodInputs(local_time=NOON, **kwargs)
        assert avatar_expression_event(next_mood(MoodState(), inputs), inputs) is None


def test_ordinary_mood_expressions_use_the_mood_cause_and_validate() -> None:
    for kwargs in (dict(), dict(flags=fs(m.USER_SAD)), dict(local_time=time(2, 0))):
        inputs = MoodInputs(**{"local_time": NOON, **kwargs})
        event = avatar_expression_event(next_mood(MoodState(), inputs), inputs)
        assert event is not None and event["cause"] == "mood"
        valid(event)


def test_the_schema_accepts_the_mood_cause_and_is_version_2_1() -> None:
    assert AVATAR_SCHEMA["$id"].endswith("/avatar-events/2.1")
    valid({"type": "avatar.expression", "name": "relaxed", "cause": "mood"})
    with pytest.raises(jsonschema.ValidationError):
        valid({"type": "avatar.expression", "name": "happy", "cause": "verified_outcome"})  # no id
    with pytest.raises(jsonschema.ValidationError):
        valid({"type": "avatar.expression", "name": "happy", "cause": "flattery"})


# ----------------------------------------------------------------------- utterance flags


@pytest.mark.parametrize(
    ("text", "flag"),
    [
        ("I have chest pain", m.URGENT_HEALTH),
        ("I can't breathe", m.URGENT_HEALTH),
        ("I'm so tired", m.USER_TIRED),
        ("i'm not tired", m.USER_NOT_TIRED),
        ("I've got bad news", m.USER_SAD),
        ("this is useless", m.UPSET),
        ("pay my rent", m.RISKY_REQUEST),
        ("good morning", m.GREETING),
        ("tell me a joke", m.CASUAL),
    ],
)
def test_utterance_flags(text: str, flag: str) -> None:
    assert flag in utterance_flags(text)


def test_ordinary_requests_raise_no_flags() -> None:
    for text in ("open calculator", "add twelve dollars for lunch", "what time is it"):
        assert utterance_flags(text) == frozenset(), text


# --------------------------------------------------------- rules artifact and the corpus


def test_the_packaged_rules_equal_the_contract_copy() -> None:
    contract = (ROOT / "contracts" / "mood-rules.v1.json").read_bytes().replace(b"\r\n", b"\n")
    packaged = (ROOT / "reva_core" / "language" / "data" / "mood-rules.v1.json").read_bytes()
    spec = (ROOT / "docs/spec/REVA_v2.0/08_CONTRACTS/mood-rules.v1.json").read_bytes()

    assert contract == packaged.replace(b"\r\n", b"\n") == spec.replace(b"\r\n", b"\n")


def _string_literals(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_no_template_text_creates_dependency_or_jealousy() -> None:
    corpus: list[str] = []
    for relative in (
        "reva_core/language/router.py",
        "reva_core/session/ack.py",
        "reva_core/session/pipeline.py",
        "reva_core/providers/cloud.py",
    ):
        corpus += _string_literals(ROOT / relative)
    for phrases in m.RULES["ack"].values():
        corpus += phrases
    corpus.append(
        (ROOT / "reva_core/language/data/mood-rules.v1.json")
        .read_text("utf-8")
        .split('"forbidden_phrases"')[0]
    )
    text = "\n".join(corpus).lower()

    for phrase in m.RULES["forbidden_phrases"]:
        assert phrase not in text, phrase


def test_every_mood_has_a_neutral_ack_that_never_claims_an_outcome() -> None:
    from reva_core.session.ack import FORBIDDEN_IN_AN_ACK

    for mood in Mood:
        for phrase in m.RULES["ack"][mood.value]:
            assert not any(word in phrase.lower() for word in FORBIDDEN_IN_AN_ACK), phrase
        assert m.ack_phrase(mood, 0) and m.ack_phrase(mood, 7)


def test_the_priority_list_in_the_rules_is_the_documented_order() -> None:
    assert m.RULES["priority"] == [
        "concerned", "sad", "tired", "focused", "excited", "happy", "flirty", "playful", "calm",
    ]  # fmt: skip

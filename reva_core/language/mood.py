"""The mood engine (docs/persona/REVA_Persona.md section 3, MASTER-LOOP B2.3).

A pure function. Given what just happened and the little state it keeps, it returns the next mood
and the three things a mood sets together: the template variant, the voice parameters and the avatar
expression. There is no model, no clock read, no I/O and no randomness: the caller passes the local
time, so the same inputs always give the same answer (and the Kotlin port can be checked against the
same fixtures).

The rules live in `mood-rules.v1.json` (copied from `contracts/`); this module only applies them.

What a mood can never do (CLAUDE.md safety invariants):
* change a risk tier, an approval, or what REVA reports happened;
* put a positive expression on an action result without a verified outcome;
* make the avatar happy during an approval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import time
from enum import StrEnum
from pathlib import Path
from typing import Any

RULES_PATH = Path(__file__).with_name("data") / "mood-rules.v1.json"


def load_rules(path: Path = RULES_PATH) -> dict[str, Any]:
    rules = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rules, dict) or rules.get("version") != "1.0":
        raise ValueError("unsupported mood rules")
    return rules


RULES = load_rules()


class Mood(StrEnum):
    CALM = "calm"
    HAPPY = "happy"
    PLAYFUL = "playful"
    FLIRTY = "flirty"
    FOCUSED = "focused"
    EXCITED = "excited"
    TIRED = "tired"
    SAD = "sad"
    CONCERNED = "concerned"


# Events from the session / policy layer.
VERIFIED_OUTCOME = "verified_outcome"
FAILURE = "failure"
APPROVAL_PENDING = "approval_pending"
REFUSAL = "refusal"
MILESTONE = "milestone"
# Utterance flags (set by the language layer, never by a model).
URGENT_HEALTH = "urgent_health"
RISKY_REQUEST = "risky_request"
SAFETY = "safety"
USER_TIRED = "tired"
USER_NOT_TIRED = "not_tired"
USER_SAD = "sad"
UPSET = "upset"
CASUAL = "casual"
GREETING = "greeting"


@dataclass(frozen=True)
class MoodSettings:
    playfulness: int = 0  # 0 to 10
    flirty_allowed: bool = False  # off by default
    follow_time: bool = True  # become tired late at night


@dataclass(frozen=True)
class MoodInputs:
    local_time: time
    events: frozenset[str] = frozenset()
    flags: frozenset[str] = frozenset()
    domain: str | None = None
    settings: MoodSettings = field(default_factory=MoodSettings)
    work_streak: int = 0  # consecutive work commands, this one included
    work_app_in_focus: bool = False
    minutes_since_serious: int | None = None  # None: nothing serious lately
    action_in_flight: bool = False  # an action is pending or executing
    verified_action_id: str | None = None


@dataclass(frozen=True)
class MoodState:
    mood: Mood = Mood.CALM
    turns_in_mood: int = 0
    tired_held: bool = False  # the user said they are tired: hold until 05:00 or they say otherwise
    tired_since_hour: int | None = None


@dataclass(frozen=True)
class Avatar:
    expression: str
    clip: str
    then: str | None = None
    soft: bool = False


@dataclass(frozen=True)
class Voice:
    rate: float
    pitch_st: int
    softness: str


@dataclass(frozen=True)
class MoodResult:
    state: MoodState
    mood: Mood
    template_variant: str
    voice: Voice
    avatar: Avatar
    reasons: tuple[str, ...]


def _sensitive(inputs: MoodInputs) -> bool:
    restricted = RULES["restricted"]
    return inputs.domain in restricted["domains"] or bool(inputs.events & set(restricted["events"]))


def _flirty_blocked(inputs: MoodInputs) -> bool:
    off = RULES["flirty_off_when"]
    return (
        inputs.domain in off["domains"]
        or bool(inputs.events & set(off["events"]))
        or bool(inputs.flags & set(off["flags"]))
    )


def _is_night(now: time) -> bool:
    t = RULES["thresholds"]
    return bool(t["tired_from_hour"] <= now.hour < t["tired_until_hour"])


def _tired_hold(previous: MoodState, inputs: MoodInputs) -> tuple[bool, int | None]:
    """Whether "I'm tired" still holds: until 05:00, or until the user says otherwise."""
    t = RULES["thresholds"]
    hour = inputs.local_time.hour
    if USER_TIRED in inputs.flags:
        return True, hour
    if USER_NOT_TIRED in inputs.flags or not previous.tired_held:
        return False, None
    since = previous.tired_since_hour if previous.tired_since_hour is not None else hour
    crossed_morning = hour >= t["tired_until_hour"] and (
        since < t["tired_until_hour"] or hour < since
    )
    return (False, None) if crossed_morning else (True, since)


def _candidate(previous: MoodState, inputs: MoodInputs, held: bool) -> tuple[Mood, str]:
    """First rule that matches, in priority order. Returns the mood and why."""
    t = RULES["thresholds"]
    events, flags, settings = inputs.events, inputs.flags, inputs.settings
    serious_recent = (
        inputs.minutes_since_serious is not None
        and inputs.minutes_since_serious < t["serious_context_minutes"]
    )
    low_stakes = (
        (CASUAL in flags or GREETING in flags)
        and not _sensitive(inputs)
        and not inputs.action_in_flight
    )
    rules: dict[str, tuple[bool, str]] = {
        "concerned": (
            bool(flags & {URGENT_HEALTH, RISKY_REQUEST, SAFETY}) or REFUSAL in events,
            "concerned: health risk, risky request, safety or refusal",
        ),
        "sad": (FAILURE in events or USER_SAD in flags, "sad: an action failed or bad news"),
        "tired": (
            held or (settings.follow_time and _is_night(inputs.local_time)),
            "tired: late at night or the user said so",
        ),
        "focused": (
            inputs.work_streak >= t["work_streak_for_focused"]
            or inputs.work_app_in_focus
            or (previous.mood == Mood.FOCUSED and inputs.work_streak >= 1),
            "focused: work commands in a row or a work app in focus",
        ),
        "excited": (MILESTONE in events, "excited: a milestone"),
        "happy": (VERIFIED_OUTCOME in events, "happy: a verified success"),
        "flirty": (
            settings.flirty_allowed
            and low_stakes
            and not serious_recent
            and not _flirty_blocked(inputs)
            and UPSET not in flags,
            "flirty: opted in, casual, nothing serious lately",
        ),
        "playful": (
            settings.playfulness >= t["playfulness_min"] and low_stakes and UPSET not in flags,
            "playful: playfulness is high and the turn is casual",
        ),
    }
    for name in RULES["priority"]:
        matched, why = rules.get(name, (False, ""))
        if matched:
            return Mood(name), why
    return Mood.CALM, "calm: nothing else applies"


def next_mood(previous: MoodState, inputs: MoodInputs) -> MoodResult:
    """The mood for this turn, with its template variant, voice and avatar settings."""
    t = RULES["thresholds"]
    reasons: list[str] = []
    held, since = _tired_hold(previous, inputs)
    mood, why = _candidate(previous, inputs, held)
    candidate = mood
    reasons.append(why)

    if mood == Mood.CALM and previous.mood in (Mood.HAPPY, Mood.EXCITED, Mood.SAD):
        decays = set(RULES["decays_to_calm"])
        if previous.mood.value in decays and previous.turns_in_mood < t["decay_turns"]:
            mood = previous.mood
            reasons.append(
                f"{previous.mood.value} held until it has lasted {t['decay_turns']} turns"
            )
    # Overrides: sensitive turns, errors, approvals and refusals only ever sound calm or concerned
    # (sad too after a failure). The mood never touches tiers, approvals or reported outcomes.
    if _sensitive(inputs):
        restricted = RULES["restricted"]
        allowed = set(
            restricted["allowed_moods_when_failure"]
            if FAILURE in inputs.events
            else restricted["allowed_moods"]
        )
        if mood.value not in allowed:
            reasons.append(f"{mood.value} not allowed here; using calm")
            mood = Mood.CALM

    fresh = candidate != Mood.CALM and mood.value in RULES["decays_to_calm"]
    turns = (
        1 if fresh or mood != previous.mood else previous.turns_in_mood + 1
    )  # a new trigger restarts
    state = MoodState(mood=mood, turns_in_mood=turns, tired_held=held, tired_since_hour=since)
    avatar = _avatar_for(mood, inputs)
    v = RULES["tts"][mood.value]
    return MoodResult(
        state=state,
        mood=mood,
        template_variant=mood.value,
        voice=Voice(float(v["rate"]), int(v["pitch_st"]), str(v["softness"])),
        avatar=avatar,
        reasons=tuple(reasons),
    )


def _avatar_for(mood: Mood, inputs: MoodInputs) -> Avatar:
    spec = RULES["avatar"][mood.value]
    avatar = Avatar(spec["expression"], spec["clip"], spec.get("then"), bool(spec.get("soft")))
    if APPROVAL_PENDING in inputs.events:
        # The approval pose with a neutral face: never happy while a decision is waiting.
        return Avatar("neutral", "approval")
    positive = set(RULES["positive_expressions"])
    if avatar.expression in positive and inputs.action_in_flight:
        return Avatar("neutral", avatar.clip)
    return avatar


def ack_phrase(mood: Mood, turn_number: int) -> str:
    """The acknowledgement for a mood; rotates within the mood's own list."""
    phrases = RULES["ack"][mood.value]
    return str(phrases[turn_number % len(phrases)])


def avatar_expression_event(result: MoodResult, inputs: MoodInputs) -> dict[str, Any] | None:
    """The `avatar.expression` event for this turn, or None when no expression change is allowed.

    * An action in flight (pending or executing) blocks mood expressions.
    * A positive expression for an action result needs a verified outcome and its action id.
    * Otherwise the expression is a mood expression (cause "mood").
    """
    if APPROVAL_PENDING in inputs.events or inputs.action_in_flight:
        return None
    name = result.avatar.expression
    positive = name in RULES["positive_expressions"]
    if VERIFIED_OUTCOME in inputs.events:
        if inputs.verified_action_id is None:
            return None  # no evidence to point at: no expression for the result
        return {
            "type": "avatar.expression",
            "name": name,
            "cause": "verified_outcome",
            "action_id": inputs.verified_action_id,
        }
    if positive and result.mood in (Mood.HAPPY, Mood.EXCITED) and not _is_greeting(inputs):
        return None  # these two are only ever about a result
    return {"type": "avatar.expression", "name": name, "cause": "mood"}


def _is_greeting(inputs: MoodInputs) -> bool:
    return GREETING in inputs.flags

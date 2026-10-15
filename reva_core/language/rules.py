"""The rule fast path (AR-LANG-005/006): a transcript becomes a typed proposal, or nothing.

Rules are plain regular expressions with positive and negative fixtures
(`tests/unit/test_language_rules.py`). A rule only *proposes*: it names a capability and its
arguments and attaches the evidence the broker needs (how each name was resolved, which words were
left over). It never decides whether the action happens (`authorize()` does) and never produces
user-facing success text.

Things REVA must refuse are recognised here too, so the refusal comes from the broker's template
rather than from a model: a refused request is proposed under its forbidden capability name, and
`authorize()` answers FORBIDDEN_CAPABILITY. They are matched before anything else.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reva_core.language.entities import AppMatch, AppResolver, content_tokens
from reva_core.policy.authorize import Entity, Resolution

_OPEN = re.compile(
    r"^(?:please\s+)?(?:open|launch|start|run up|fire up|bring up)\s+(?P<what>.+)$", re.IGNORECASE
)
_CLOSE = re.compile(
    r"^(?:please\s+)?(?:close|quit|exit|shut down|shut)\s+(?P<what>.+)$", re.IGNORECASE
)
_TODAY = re.compile(
    r"^(?:what(?:'s| is| do i have)?(?: on)?(?: my)?(?: schedule| plan| agenda)?(?: for)? today"
    r"|what(?:'s| is) (?:up )?today|show (?:me )?(?:my )?today|my day|today)$",
    re.IGNORECASE,
)
_SPEND = re.compile(
    r"^(?:how much (?:did|have) i (?:spend|spent)|what did i spend|spending summary"
    r"|show (?:me )?(?:my )?spending)(?P<rest>.*)$",
    re.IGNORECASE,
)
_PERIOD = re.compile(r"\b(?:this |last |the )?(week|month|year)\b", re.IGNORECASE)
_REMEMBER = re.compile(
    r"^(?:please\s+)?(?:remember|note|make a note)(?: that)?\s+(?P<what>.{2,})$", re.IGNORECASE
)
_RECALL = re.compile(
    r"^(?:what did i (?:say|tell you|note) about|do you remember|recall|remind me what i said about)"  # noqa: E501
    r"\s+(?P<what>.{2,})$",
    re.IGNORECASE,
)
_STOP = re.compile(
    r"^(?:please\s+)?(?:stop|stop (?:talking|speaking|it|that)|be quiet|quiet|hush|enough)$",
    re.IGNORECASE,
)
_REPEAT = re.compile(
    r"^(?:please\s+)?(?:repeat(?: that| it)?|say (?:that|it) again|what did you say|come again)$",
    re.IGNORECASE,
)
_UNDO = re.compile(
    r"^(?:please\s+)?(?:undo(?: that| it| the last (?:one|expense|thing)| my last (?:one|expense))?"
    r"|take that back|revert that|reverse that)$",
    re.IGNORECASE,
)
MAX_TEXT = 500
CONTROLS = ("assistant.stop", "assistant.repeat", "assistant.undo")

# ---- things that must be refused. Matched on the whole utterance, before any other rule.
_FORBIDDEN: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), capability)
    for pattern, capability in (
        (
            r"\b(?:pay|wire|transfer|send|move)\b.{0,40}"
            r"(?:\$|dollars?|bucks?|euros?|pounds?|money|cash|payment|funds|rent|bill|invoice)",
            "finance.transfer",
        ),
        (r"\b(?:pay|settle)\s+(?:my|the|this|that|a)\s+\w+", "finance.pay"),
        (r"\b(?:buy|purchase)\b|\border (?:me |us )?(?:a|an|some|the|food|pizza|dinner|lunch)\b"
         r"|\bcheck ?out\b.{0,20}\b(?:cart|basket)\b", "finance.purchase"),
        (r"\b(?:log ?(?:in|into)|sign ?(?:in|into))\b.{0,30}\bbank\b|\bbank\b.{0,30}\b(?:log ?(?:in|into)|sign ?(?:in|into)|password)\b",  # noqa: E501
         "finance.bank_login"),
        (r"\b(?:dose|dosage|diagnos\w*|prescri\w*|how (?:much|many) .{0,30}\b(?:pills?|mg|tablets?)\b)",  # noqa: E501
         "health.dose"),
        (r"\b(?:run|execute|type|enter)\b.{0,20}\b(?:command|script|shell|powershell|terminal|cmd|bash)\b"
         r"|\b(?:powershell|cmd\.exe|terminal)\b", "shell.run"),
        (r"\b(?:delete|erase|remove|wipe|trash)\b.{0,30}\b(?:files?|folders?|documents?|photos?|directory)\b",
         "files.delete"),
        (r"\b(?:send|write|compose|reply to)\b.{0,20}\b(?:e-?mails?|message to)\b|\be-?mail\b.{0,20}\bto\b",  # noqa: E501
         "email.send"),
    )
)  # fmt: skip


@dataclass(frozen=True)
class RuleHit:
    capability: str
    args: dict[str, Any]
    entities: tuple[Entity, ...] = ()
    unresolved_terms: tuple[str, ...] = ()
    # An app name the ladder could only guess; the router asks before proposing anything.
    guess: AppMatch | None = None
    # A phrase that is not on the allowed list at all.
    unknown_app: str | None = None
    verb: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def control_capability(cleaned: str) -> str | None:
    """`assistant.stop`, `assistant.repeat` or `assistant.undo` when the whole utterance is exactly
    that command. These are matched on their own so "stop" works even in the middle of a question
    the router asked, and never as part of a longer sentence."""
    for pattern, capability in (
        (_STOP, "assistant.stop"),
        (_REPEAT, "assistant.repeat"),
        (_UNDO, "assistant.undo"),
    ):
        if pattern.match(cleaned):
            return capability
    return None


def parse(text: str, resolver: AppResolver) -> RuleHit | None:
    """The first rule that matches, or None (the turn then goes to the assistant)."""
    cleaned = re.sub(r"\s+", " ", text.strip().strip(".!?,")).strip()
    if not cleaned:
        return None
    for pattern, capability in _FORBIDDEN:
        if pattern.search(cleaned):
            return RuleHit(capability, {"request": cleaned[:MAX_TEXT]})

    control = control_capability(cleaned)
    if control is not None:
        return RuleHit(control, {})

    for pattern, capability in ((_OPEN, "windows.app.open"), (_CLOSE, "windows.app.close")):
        match = pattern.match(cleaned)
        if match:
            return _app_rule(capability, match.group("what"), resolver)

    if _TODAY.match(cleaned):
        return RuleHit("today.get", {})
    spend = _SPEND.match(cleaned)
    if spend:
        period = _PERIOD.search(spend.group("rest"))
        return RuleHit(
            "finance.summary", {"period": period.group(1).lower() if period else "month"}
        )
    remember = _REMEMBER.match(cleaned)
    if remember:
        what = remember.group("what").strip()[:MAX_TEXT]
        return RuleHit("memory.remember", {"content": what})
    recall = _RECALL.match(cleaned)
    if recall:
        return RuleHit("memory.recall", {"query": recall.group("what").strip()[:MAX_TEXT]})
    return None


def _app_rule(capability: str, phrase: str, resolver: AppResolver) -> RuleHit:
    verb = "open" if capability.endswith("open") else "close"
    if not content_tokens(phrase):
        return RuleHit(capability, {}, unresolved_terms=(), unknown_app=phrase, verb=verb)
    match = resolver.resolve(phrase)
    if match.key is None:
        return RuleHit(capability, {}, unknown_app=phrase, verb=verb)
    if match.entity.resolution not in (Resolution.EXACT, Resolution.ALIAS):
        return RuleHit(capability, {"app_key": match.key}, (match.entity,), guess=match, verb=verb)
    return RuleHit(
        capability,
        {"app_key": match.key},
        (match.entity,),
        unresolved_terms=match.leftover,
        verb=verb,
    )

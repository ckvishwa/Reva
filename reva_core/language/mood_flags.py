"""Utterance flags for the mood engine: a few plain phrase lists, no model (B2.3).

These only decide how REVA *sounds*. They never decide whether something is allowed or what is
reported. The urgent-health list is deliberately small and cautious; the health domain (D3) owns the
full safety evaluation.
"""

from __future__ import annotations

import re

from reva_core.language import mood

_URGENT_HEALTH = re.compile(
    r"\b(chest pain|can'?t breathe|cannot breathe|trouble breathing|heart attack|stroke|"
    r"overdose|suicid\w*|kill myself|want to die|bleeding (?:a lot|heavily)|unconscious|"
    r"allergic reaction|severe pain)\b",
    re.IGNORECASE,
)
_TIRED = re.compile(
    r"\b(i'?m (?:so |really |very )?(?:tired|exhausted|sleepy|wiped)|"
    r"i am (?:so |really |very )?(?:tired|exhausted)|"
    r"i need (?:to sleep|some sleep|a nap))\b",
    re.IGNORECASE,
)
_NOT_TIRED = re.compile(
    r"\b(i'?m not tired|i am not tired|i'?m wide awake|not sleepy)\b", re.IGNORECASE
)
_SAD = re.compile(
    r"\b(i'?m (?:so |really |very )?(?:sad|down|depressed|upset about)|bad news|"
    r"my (?:dog|cat|grandma|grandpa|dad|mum|mom) (?:died|passed)|i got (?:fired|laid off)|"
    r"i failed)\b",
    re.IGNORECASE,
)
_UPSET = re.compile(
    r"\b(i'?m (?:so |really |very )?(?:angry|furious|annoyed|frustrated|upset|stressed)|"
    r"this is (?:useless|stupid|ridiculous)|shut up|you'?re useless)\b",
    re.IGNORECASE,
)
_RISKY = re.compile(
    r"\b(pay (?:my|the) |transfer \w* ?(?:dollars|money)|wire |send (?:money|payment)|"
    r"delete (?:all|my|every)|format (?:the )?(?:drive|disk)|run (?:a )?command)",
    re.IGNORECASE,
)
_GREETING = re.compile(
    r"^\s*(?:hey|hi|hello|good (?:morning|afternoon|evening)|yo)\b(?: reva)?[\s.!?,]*$",
    re.IGNORECASE,
)
_CASUAL = re.compile(
    r"\b(joke|tell me something|how are you|what'?s up|bored|chat|fun fact|thanks|thank you)\b",
    re.IGNORECASE,
)


def utterance_flags(text: str) -> frozenset[str]:
    flags: set[str] = set()
    if _URGENT_HEALTH.search(text):
        flags.add(mood.URGENT_HEALTH)
    if _NOT_TIRED.search(text):
        flags.add(mood.USER_NOT_TIRED)
    elif _TIRED.search(text):
        flags.add(mood.USER_TIRED)
    if _SAD.search(text):
        flags.add(mood.USER_SAD)
    if _UPSET.search(text):
        flags.add(mood.UPSET)
    if _RISKY.search(text):
        flags.add(mood.RISKY_REQUEST)
    if _GREETING.match(text):
        flags.add(mood.GREETING)
    elif _CASUAL.search(text):
        flags.add(mood.CASUAL)
    return frozenset(flags)

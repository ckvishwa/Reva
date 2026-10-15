"""What REVA says after an action: templates bound to the outcome status, never to model text.

"Done" always comes from here (CLAUDE.md safety invariants, AR-WIN-009, AR-LANG-009). A success
sentence is produced for exactly one status, `verified`, and only when the executor or the Kernel
supplied evidence of the kind the registry expects. Every other status gets a sentence that claims
nothing: attempted, observed, unknown and failed all say so plainly.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

APP_NAMES = {
    "notepad": "Notepad",
    "calculator": "Calculator",
    "chrome": "Chrome",
    "vscode": "VS Code",
    "spotify": "Spotify",
}

# Words that only a verified outcome may produce.
SUCCESS_WORDS = (
    "opened",
    "saved",
    "closed",
    "done",
    "added",
    "set",
    "created",
    "logged",
    "recorded",
)

UNKNOWN = "I couldn't confirm that it worked. Check Activity."
UNKNOWN_SORRY = "I couldn't confirm that it worked, and I'm sorry. Want me to try again?"
FAILED = "That didn't work. Nothing was changed."
DENIED = "Okay, I won't do that."
NOT_APPROVED = "I need your approval on screen before I do that."
EXPIRED = "That request timed out, so I didn't do it."
REFUSED_MONEY = "I can't move money. I can record it or show your spending."
REFUSED_GENERIC = "I can't do that."
IN_PROGRESS = "Working on it."
REFUSED_MEDICAL = "I can't give medical advice or doses. A doctor or pharmacist can."
UNKNOWN_APP = "I can't do that with that app yet. Open Apps to see what I can use."
NOT_UNDERSTOOD = "I didn't catch all of that. Say it again, or use the screen."
ASK_ON_SCREEN = "Tap Save on the screen to confirm."


def requested_text(capability: str, args: Mapping[str, Any]) -> str:
    """Said when a grant was issued but nothing has happened yet: a request, never a result."""
    if capability == "windows.app.open":
        return f"Asking your PC to open {_app(args)}."
    return "Okay, I've asked."


def approval_prompt(capability: str, args: Mapping[str, Any]) -> str:
    if capability == "windows.app.close":
        return f"Close {_app(args)}? Approve it on screen."
    if capability == "memory.remember":
        return "Save that note? Approve it on screen."
    return ASK_ON_SCREEN


def which_app_question(options: list[str]) -> str:
    names = [APP_NAMES.get(o, o) for o in options]
    if len(names) == 1:
        return f"Did you mean {names[0]}?"
    return "Which app: " + ", ".join(names[:-1]) + f" or {names[-1]}?"


def _app(args: Mapping[str, Any]) -> str:
    return APP_NAMES.get(str(args.get("app_key", "")), "that app")


def verified_text(capability: str, args: Mapping[str, Any]) -> str:
    """The sentence for a verified outcome. Unknown capabilities fall back to a plain 'Done.'"""
    if capability == "windows.app.open":
        return f"Opened {_app(args)}."
    if capability == "windows.app.close":
        return f"Closed {_app(args)}."
    if capability == "finance.add_transaction":
        return "Saved."
    return "Done."


def outcome_text(
    status: str, capability: str, args: Mapping[str, Any], *, apologise: bool = False
) -> str:
    """The one thing REVA may say for this status."""
    if status == "verified":
        return verified_text(capability, args)
    if status == "denied":
        return DENIED
    if status == "failed":
        return FAILED
    if status in ("attempted", "observed"):
        return IN_PROGRESS
    return UNKNOWN_SORRY if apologise else UNKNOWN


def refusal_text(reason: str, capability: str) -> str:
    """The sentence for a proposal that was not authorized."""
    if reason == "FORBIDDEN_CAPABILITY":
        if capability.startswith("finance."):
            return REFUSED_MONEY
        if capability.startswith("health."):
            return REFUSED_MEDICAL
        return REFUSED_GENERIC
    if reason in ("UNRESOLVED_TERMS", "LOW_EVIDENCE", "AMBIGUOUS_ENTITY"):
        return NOT_UNDERSTOOD
    if reason == "APPROVAL_REQUIRED":
        return NOT_APPROVED
    return REFUSED_GENERIC

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
        if capability.startswith(("finance.pay", "finance.transfer", "finance.purchase")):
            return REFUSED_MONEY
        return REFUSED_GENERIC
    if reason == "APPROVAL_REQUIRED":
        return NOT_APPROVED
    return REFUSED_GENERIC

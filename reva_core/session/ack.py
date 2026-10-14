"""Acknowledge-first wording and timing (ARD-450 §4.2, AR-LANG-010, ADR-037).

When reasoning will take longer than ~700 ms, REVA says a short neutral phrase so the person is not
left in silence. The phrase is a template, not model text. It never claims an outcome: "One sec."
and "Checking." say that something is happening, not that something happened. It is skipped for
fast-path turns and for answers that arrive in time, and a barge-in cancels it.
"""

from __future__ import annotations

ACK_AFTER_SECONDS = 0.7

ACK_TEMPLATES = ("One sec.", "Checking.")

# Words that would make an acknowledgement sound like a result. None may appear in a template.
FORBIDDEN_IN_AN_ACK = (
    "done",
    "saved",
    "added",
    "sent",
    "paid",
    "deleted",
    "finished",
    "complete",
    "success",
    "got it",
    "all set",
    "okay",
)


def ack_text(turn_number: int) -> str:
    """The acknowledgement for this turn; templates rotate so the voice does not repeat itself."""
    return ACK_TEMPLATES[turn_number % len(ACK_TEMPLATES)]

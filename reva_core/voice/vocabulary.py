"""The STT vocabulary hint (MASTER-LOOP B1.2): a words-only prompt for faster-whisper.

Whisper's `initial_prompt` biases spelling toward words it has been shown. It must be a plain word
list: a sentence or an instruction in the prompt can be echoed into the transcript or steer the
decoder, so every entry is checked and anything that is not a short name is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_PROMPT_CHARS = 400
MAX_WORD_CHARS = 30
_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9&'.-]*(?: [A-Za-z0-9&'.-]+){0,2}$")

DEFAULT_APP_NAMES = (
    "VS Code",
    "Visual Studio",
    "Spotify",
    "Chrome",
    "Edge",
    "Firefox",
    "Notepad",
    "Calculator",
    "Discord",
    "Slack",
    "Teams",
    "Outlook",
    "Excel",
    "Word",
    "Steam",
    "OBS",
)
DEFAULT_FINANCE_WORDS = (
    "groceries",
    "dining",
    "transport",
    "rent",
    "utilities",
    "entertainment",
    "shopping",
    "travel",
    "subscriptions",
    "salary",
    "savings",
    "budget",
    "expense",
    "transaction",
)


def build_vocabulary_prompt(extra: Iterable[str] = ()) -> str:
    """Comma-separated names, deduplicated, each validated, at most `MAX_PROMPT_CHARS` long."""
    seen: set[str] = set()
    words: list[str] = []
    for candidate in (*DEFAULT_APP_NAMES, *DEFAULT_FINANCE_WORDS, *extra):
        word = candidate.strip()
        key = word.lower()
        if not word or len(word) > MAX_WORD_CHARS or key in seen or not _WORD.match(word):
            continue
        if len(", ".join([*words, word])) > MAX_PROMPT_CHARS:
            break
        seen.add(key)
        words.append(word)
    return ", ".join(words)

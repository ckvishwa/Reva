"""Entity resolution ladder for app names (AR-LANG-008): exact, alias, lexical, fuzzy, vector, ask.

Only the first two rungs are trusted enough to act on (`policy.authorize.TRUSTED`). A lexical or
fuzzy hit is returned with its score and margin so `authorize()` asks "which one?" instead of
acting. The vector rung is shadow-only: a scorer may be attached and is called so its scores can be
logged and compared, but its answer never changes the result.

No third-party matcher: `difflib` from the standard library is enough for five apps, and it avoids a
new dependency. The ladder is a function of the phrase and the registry's canonical names only.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher

from reva_core.policy.authorize import Entity, Resolution

# Words that carry no meaning for picking an app.
FILLER = frozenset(
    {
        "a", "an", "the", "my", "up", "app", "apps", "application", "program", "window", "please",
        "for", "me", "now", "can", "you", "could", "would", "will", "to", "just", "again", "pls",
        "hey", "reva", "ok", "okay", "go", "and", "then",
    }
)  # fmt: skip

# Owner-approved aliases (a verified-alias rung). Keys are canonical enum values of the registry.
ALIASES: Mapping[str, tuple[str, ...]] = {
    "notepad": ("notepad", "notes app"),
    "calculator": ("calculator", "calc"),
    "chrome": ("chrome", "google chrome", "browser", "the browser"),
    "vscode": ("vscode", "vs code", "visual studio code", "code", "vs-code"),
    "spotify": ("spotify", "music", "music app"),
}

FUZZY_FLOOR = 0.72
LEXICAL_SCORE = 0.9
MAX_CANDIDATES = 3

Shadow = Callable[[str, tuple[str, ...]], object]


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower().replace("-", " "))


def content_tokens(text: str) -> list[str]:
    return [t for t in tokens(text) if t not in FILLER]


@dataclass(frozen=True)
class AppMatch:
    entity: Entity
    key: str | None  # the app key when the rung produced one (any rung, trusted or not)
    leftover: tuple[str, ...] = ()  # content words that were not part of the app name


class AppResolver:
    def __init__(
        self,
        keys: tuple[str, ...],
        *,
        shadow: Shadow | None = None,
        aliases: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._keys = keys
        table = ALIASES if aliases is None else aliases
        self._aliases = {
            alias: key for key, names in table.items() if key in keys for alias in names
        }
        self._shadow = shadow

    def resolve(self, phrase: str) -> AppMatch:
        words = content_tokens(phrase)
        joined = " ".join(words)
        if self._shadow is not None:
            # Scores are logged elsewhere, never used here; a broken scorer must not break a turn.
            with contextlib.suppress(Exception):
                self._shadow(joined, self._keys)
        if not words:
            return AppMatch(Entity("app", phrase, Resolution.NONE), None)

        # 1 exact (the canonical key) and 2 alias, as one longest-window pass so that
        # "google chrome" is the alias "google chrome", not "chrome" plus the leftover "google".
        found = self._find_window(words, {**self._aliases, **{k: k for k in self._keys}}, phrase)
        if found is not None:
            return found
        # 3 lexical: the words joined together are an app ("note pad" -> notepad).
        squashed = "".join(words)
        for key in self._keys:
            if squashed == key:
                return AppMatch(
                    Entity("app", phrase, Resolution.LEXICAL, LEXICAL_SCORE, 1.0, (key,)), key
                )
        # 4 fuzzy: closest names, with the lead over the runner-up as the margin.
        scored = sorted(
            (
                (max(_ratio(squashed, name.replace(" ", "")) for name in names), key)
                for key, names in self._names().items()
            ),
            reverse=True,
        )
        best_score, best_key = scored[0]
        if best_score < FUZZY_FLOOR:
            return AppMatch(Entity("app", phrase, Resolution.NONE), None)
        runner = scored[1][0] if len(scored) > 1 else 0.0
        candidates = tuple(k for s, k in scored[:MAX_CANDIDATES] if s >= FUZZY_FLOOR)
        return AppMatch(
            Entity(
                "app",
                phrase,
                Resolution.FUZZY,
                round(best_score, 3),
                round(best_score - runner, 3),
                candidates,
            ),  # fmt: skip
            best_key,
        )

    def _names(self) -> dict[str, list[str]]:
        names: dict[str, list[str]] = {key: [key] for key in self._keys}
        for alias, key in self._aliases.items():
            names[key].append(alias)
        return names

    def _find_window(
        self, words: list[str], table: Mapping[str, str], phrase: str
    ) -> AppMatch | None:
        """The longest run of words that is a known name; everything else is leftover."""
        best: tuple[int, int, str] | None = None
        for size in range(len(words), 0, -1):
            for start in range(len(words) - size + 1):
                key = table.get(" ".join(words[start : start + size]))
                if key is not None:
                    best = (start, size, key)
                    break
            if best:
                break
        if best is None:
            return None
        start, size, key = best
        name = " ".join(words[start : start + size])
        resolution = Resolution.EXACT if name == key else Resolution.ALIAS
        leftover = tuple(words[:start] + words[start + size :])
        entity = Entity("app", phrase, resolution, 1.0, 1.0, (key,))
        return AppMatch(entity, key, leftover)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

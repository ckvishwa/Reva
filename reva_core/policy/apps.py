"""The apps REVA may open or close (ARD-100 section 5, AR-WIN-005..007).

Two sources, one list:

* five built-in apps whose names are part of the capability registry, and
* apps the owner approved on the Apps & Actions page after the Windows app found them in the
  Start Menu ("waiting for you").

Core stores only a key, a display name and spoken aliases. Launch targets (paths, app ids) never
leave the PC: the Windows executor keeps them in its own file, so a request from anywhere else can
name an app only by key and can never name a program, a path or an argument.

The file is plain JSON in the data directory (`apps.json`); nothing in it is secret.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reva_core.language.entities import ALIASES, FILLER, AppResolver

KEY = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
ALIAS = re.compile(r"^[a-z0-9][a-z0-9 .+-]{0,38}[a-z0-9+]$|^[a-z0-9]$")
DISPLAY_MAX = 60
MAX_APPROVED = 100
MAX_WAITING = 200
MAX_ALIASES = 8

BUILTIN_DISPLAY = {
    "notepad": "Notepad",
    "calculator": "Calculator",
    "chrome": "Google Chrome",
    "vscode": "Visual Studio Code",
    "spotify": "Spotify",
}


class AppCatalogError(ValueError):
    """The request was refused; the message is safe to show."""


@dataclass(frozen=True)
class AppEntry:
    key: str
    display_name: str
    aliases: tuple[str, ...]
    builtin: bool


class AppCatalog:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._approved: dict[str, tuple[str, tuple[str, ...]]] = {}
        self._waiting: dict[str, str] = {}
        self._load()

    # ---------------------------------------------------------------- reading

    def apps(self) -> list[AppEntry]:
        with self._lock:
            builtin = [
                AppEntry(key, BUILTIN_DISPLAY[key], ALIASES[key], True) for key in BUILTIN_DISPLAY
            ]
            added = [
                AppEntry(key, name, aliases, False)
                for key, (name, aliases) in sorted(self._approved.items())
            ]
            return builtin + added

    def waiting(self) -> list[tuple[str, str]]:
        with self._lock:
            return sorted(self._waiting.items())

    def allowed_keys(self) -> tuple[str, ...]:
        return tuple(app.key for app in self.apps())

    def display_names(self) -> dict[str, str]:
        return {app.key: app.display_name for app in self.apps()}

    def resolver(self) -> AppResolver:
        apps = self.apps()
        aliases = {app.key: app.aliases for app in apps}
        return AppResolver(tuple(app.key for app in apps), aliases=aliases)

    # --------------------------------------------------------------- changing

    def report_discovered(self, found: list[tuple[str, str]]) -> int:
        """The Windows app's Start Menu scan. New names go to "waiting"; nothing is allowed yet."""
        with self._lock:
            known = set(BUILTIN_DISPLAY) | set(self._approved)
            for key, name in found:
                if len(self._waiting) >= MAX_WAITING:
                    break
                if KEY.match(key) and key not in known and 0 < len(name.strip()) <= DISPLAY_MAX:
                    self._waiting[key] = name.strip()
            self._save()
            return len(self._waiting)

    def approve(self, key: str, display_name: str | None, aliases: list[str]) -> AppEntry:
        """The owner said yes to this app and these spoken names."""
        with self._lock:
            if not KEY.match(key):
                raise AppCatalogError("that app key is not valid")
            if key in BUILTIN_DISPLAY:
                raise AppCatalogError("that app is built in")
            name = (display_name or self._waiting.get(key) or "").strip()
            if key not in self._waiting and key not in self._approved:
                raise AppCatalogError("that app was not found on this PC")
            if not 0 < len(name) <= DISPLAY_MAX:
                raise AppCatalogError("the app needs a name")
            cleaned = self._clean_aliases(key, name, aliases)
            if key not in self._approved and len(self._approved) >= MAX_APPROVED:
                raise AppCatalogError("too many approved apps")
            self._approved[key] = (name, cleaned)
            self._waiting.pop(key, None)
            self._save()
            return AppEntry(key, name, cleaned, False)

    def remove(self, key: str) -> bool:
        with self._lock:
            if key in BUILTIN_DISPLAY:
                raise AppCatalogError("built-in apps cannot be removed")
            existed = self._approved.pop(key, None) is not None
            if existed:
                self._save()
            return existed

    def dismiss(self, key: str) -> None:
        with self._lock:
            self._waiting.pop(key, None)
            self._save()

    # --------------------------------------------------------------- internals

    def _clean_aliases(self, key: str, name: str, aliases: list[str]) -> tuple[str, ...]:
        taken: dict[str, str] = {}
        for builtin_key, names in ALIASES.items():
            for alias in names:
                taken[alias] = builtin_key
            taken[builtin_key] = builtin_key
        for other, (_, other_aliases) in self._approved.items():
            if other != key:
                taken[other] = other
                for alias in other_aliases:
                    taken[alias] = other
        cleaned: list[str] = []
        for raw in [name.lower(), key, *aliases]:
            alias = re.sub(r"\s+", " ", raw.strip().lower())
            if not alias or alias in cleaned:
                continue
            if not ALIAS.match(alias):
                raise AppCatalogError(f"'{raw[:40]}' is not a usable spoken name")
            if alias in FILLER or all(word in FILLER for word in alias.split()):
                raise AppCatalogError(f"'{alias}' is too common to be a name")
            if taken.get(alias, key) != key:
                raise AppCatalogError(f"'{alias}' already belongs to another app")
            cleaned.append(alias)
        if len(cleaned) > MAX_ALIASES:
            raise AppCatalogError("too many spoken names")
        return tuple(cleaned)

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            document: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
            for entry in document.get("approved", []):
                key = str(entry["key"])
                if KEY.match(key) and key not in BUILTIN_DISPLAY:
                    self._approved[key] = (
                        str(entry["display_name"])[:DISPLAY_MAX],
                        tuple(str(a) for a in entry.get("aliases", []))[:MAX_ALIASES],
                    )
            for entry in document.get("waiting", []):
                key = str(entry["key"])
                if KEY.match(key):
                    self._waiting[key] = str(entry["display_name"])[:DISPLAY_MAX]
        except (OSError, ValueError, KeyError, TypeError):
            self._approved, self._waiting = {}, {}  # a damaged file means "nothing approved"

    def _save(self) -> None:
        if self._path is None:
            return
        document = {
            "approved": [
                {"key": key, "display_name": name, "aliases": list(aliases)}
                for key, (name, aliases) in sorted(self._approved.items())
            ],
            "waiting": [{"key": k, "display_name": n} for k, n in sorted(self._waiting.items())],
        }
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(document, indent=2), encoding="utf-8")
        temporary.replace(self._path)

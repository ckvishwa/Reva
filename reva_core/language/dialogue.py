"""Dialogue state tracker (ARD-450 §3.4, AR-LANG-005).

Per device, so it survives a new session after a crash or an app restart:

* the active intent with its filled and missing slots;
* a pending clarification (question id, options, expiry);
* the entities last talked about, for "it", "that one" and "the last one";
* the actions last committed, newest first, for undo;
* the language preference and the current `turn_epoch`.

State is saved after every accepted proposal and whenever a barge-in cancels a clarification. On
the next start it is loaded again, with anything stale dropped: a reference or a clarification older
than 30 minutes is no longer "that one", and an undo older than 24 hours is no longer offered.

This module only remembers and resolves references. It never decides whether an action is allowed
(that is `authorize()`), never commits anything, and never guesses: with nothing to point at,
"it" is `unresolved` and the resolution step asks.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from reva_core.security.dpapi import DpapiProtector, ProtectionError, Protector
from reva_core.shared.logging import get_logger

logger = get_logger("dialogue")

REFERENCE_TTL = timedelta(minutes=30)
UNDO_TTL = timedelta(hours=24)
MAX_REFERENCES = 10
MAX_UNDO = 5
MAX_LABEL = 120
MAX_FILE_BYTES = 64 * 1024
CLARIFICATION_TTL = timedelta(minutes=2)


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str  # "transaction", "account", "category", "reminder", ...
    label: str

    def clipped(self) -> Entity:
        return Entity(self.id[:64], self.kind[:32], self.label[:MAX_LABEL])


@dataclass(frozen=True)
class Option:
    id: str
    label: str


@dataclass(frozen=True)
class Clarification:
    question_id: str
    options: tuple[Option, ...]
    expires_at: str  # ISO 8601, UTC
    turn_epoch: int


@dataclass(frozen=True)
class CommittedAction:
    action_id: str
    committed_at: str  # ISO 8601, UTC


@dataclass
class DialogueState:
    active_intent: str | None = None
    filled_slots: dict[str, Any] = field(default_factory=dict)
    missing_slots: list[str] = field(default_factory=list)
    pending_clarification: Clarification | None = None
    last_referenced: list[Entity] = field(default_factory=list)  # newest first
    committed: list[CommittedAction] = field(default_factory=list)  # newest first
    language: str = "en"
    turn_epoch: int = 0
    saved_at: str | None = None


@dataclass(frozen=True)
class Reference:
    """What a referring phrase points at. `status` is resolved, ambiguous or unresolved."""

    status: str
    phrase: str
    entity: Entity | None = None
    candidates: tuple[Entity, ...] = ()


# ------------------------------------------------------------------------------- the store


class DialogueStore(Protocol):
    def load(self, device_id: str) -> DialogueState | None: ...

    def save(self, device_id: str, state: DialogueState) -> None: ...


class MemoryDialogueStore:
    """Keeps state for the life of the process (tests; the fallback when disk is unavailable)."""

    def __init__(self) -> None:
        self._states: dict[str, str] = {}

    def load(self, device_id: str) -> DialogueState | None:
        raw = self._states.get(device_id)
        return None if raw is None else _decode(raw)

    def save(self, device_id: str, state: DialogueState) -> None:
        self._states[device_id] = _encode(state)


class FileDialogueStore:
    """One small file per device under `directory`, protected with DPAPI and written atomically.

    The file name is a hash of the device id, so no device id can name a path. The content is
    encrypted for the current Windows user: the state holds the names of recent transactions. A
    file that is unreadable, oversized, not decryptable or not valid state is ignored (the
    conversation starts fresh) and never stops the app.

    Earlier builds wrote plain `<hash>.json` files. `migrate_legacy` re-saves each valid one in
    the protected format and removes the plain copy; one that cannot be migrated is left as it is.
    """

    _MAGIC = b"RVDLG1\n"

    def __init__(self, directory: Path, protector: Protector | None = None) -> None:
        self._directory = Path(directory)
        self._protector = protector or DpapiProtector(b"reva.dialogue.v1")

    def _path(self, device_id: str) -> Path:
        digest = hashlib.sha256(device_id.encode("utf-8")).hexdigest()[:32]
        return self._directory / f"{digest}.dat"

    def load(self, device_id: str) -> DialogueState | None:
        path = self._path(device_id)
        try:
            if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                return None
            raw = path.read_bytes()
            if not raw.startswith(self._MAGIC):
                raise ValueError("not a protected dialogue file")
            return _decode(self._protector.unprotect(raw[len(self._MAGIC) :]).decode("utf-8"))
        except (OSError, ValueError, KeyError, TypeError, ProtectionError):
            logger.warning("dialogue state could not be read; starting fresh")
            return None

    def save(self, device_id: str, state: DialogueState) -> None:
        try:
            self._write(self._path(device_id), _encode(state))
        except (OSError, ProtectionError):
            logger.warning("dialogue state could not be saved")

    def migrate_legacy(self) -> int:
        """Protect every valid plain `*.json` file in the directory. Returns how many moved."""
        moved = 0
        try:
            legacy = sorted(self._directory.glob("*.json")) if self._directory.is_dir() else []
        except OSError:
            return 0
        for old in legacy:
            try:
                if old.stat().st_size > MAX_FILE_BYTES:
                    continue
                text = old.read_text(encoding="utf-8")
                _decode(text)  # only valid state is migrated
                target = old.with_suffix(".dat")
                if not target.exists():  # a protected file is newer than any plain one
                    self._write(target, text)
                old.unlink()
                moved += 1
            except (OSError, ValueError, KeyError, TypeError, ProtectionError):
                logger.warning("a plain dialogue file could not be migrated and was left in place")
        return moved

    def _write(self, target: Path, text: str) -> None:
        payload = self._MAGIC + self._protector.protect(text.encode("utf-8"))
        self._directory.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(dir=self._directory, suffix=".tmp")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(payload)
            os.replace(temp_name, target)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp_name)
            raise


def _encode(state: DialogueState) -> str:
    return json.dumps(asdict(state), separators=(",", ":"))


def _decode(raw: str) -> DialogueState:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("dialogue state must be an object")
    clarification = data.get("pending_clarification")
    pending = None
    if clarification is not None:
        pending = Clarification(
            question_id=str(clarification["question_id"])[:64],
            options=tuple(
                Option(str(o["id"])[:64], str(o["label"])[:MAX_LABEL])
                for o in clarification["options"][:5]
            ),
            expires_at=str(clarification["expires_at"]),
            turn_epoch=int(clarification["turn_epoch"]),
        )
    return DialogueState(
        active_intent=_text_or_none(data.get("active_intent")),
        filled_slots=dict(data.get("filled_slots") or {}),
        missing_slots=[str(s)[:64] for s in (data.get("missing_slots") or [])][:20],
        pending_clarification=pending,
        last_referenced=[
            Entity(str(e["id"]), str(e["kind"]), str(e["label"])).clipped()
            for e in (data.get("last_referenced") or [])[:MAX_REFERENCES]
        ],
        committed=[
            CommittedAction(str(c["action_id"])[:64], str(c["committed_at"]))
            for c in (data.get("committed") or [])[:MAX_UNDO]
        ],
        language=str(data.get("language") or "en")[:8],
        turn_epoch=int(data.get("turn_epoch") or 0),
        saved_at=_text_or_none(data.get("saved_at")),
    )


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)[:128]


# ----------------------------------------------------------------------------- the tracker

_PRONOUNS = frozenset({"it", "that", "this", "that one", "this one", "the last one", "last one"})
_BEFORE = re.compile(r"^(?:the )?(?:one before(?: that)?|previous(?: one)?|one before it)$")
_KIND = re.compile(r"^(?:the )?(?:last|previous|latest|most recent) ([a-z]+)$")
_ORDINAL = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}


class DialogueTracker:
    """The working copy of one device's dialogue state, saved through a `DialogueStore`."""

    def __init__(
        self,
        device_id: str,
        store: DialogueStore | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._device_id = device_id
        self._store = store or MemoryDialogueStore()
        self._clock = clock or (lambda: datetime.now(UTC))
        self.state = self._resume()

    # ---- resume

    def _resume(self) -> DialogueState:
        saved = self._store.load(self._device_id)
        if saved is None:
            return DialogueState()
        now = self._clock()
        before = _encode(saved)
        age = _age(saved.saved_at, now)
        if age is None or age > REFERENCE_TTL:
            saved.last_referenced = []
            saved.pending_clarification = None
            saved.active_intent = None
            saved.filled_slots = {}
            saved.missing_slots = []
        if saved.pending_clarification is not None and _expired(
            saved.pending_clarification.expires_at, now
        ):
            saved.pending_clarification = None
        saved.committed = [
            c
            for c in saved.committed
            if (a := _age(c.committed_at, now)) is not None and a <= UNDO_TTL
        ]
        if _encode(saved) != before:
            self.state = saved
            self._save()  # what expired is gone from disk too, not just from memory
        return saved

    # ---- building the state during a turn

    def begin_intent(self, intent: str, filled: dict[str, Any], missing: list[str]) -> None:
        self.state.active_intent = intent
        self.state.filled_slots = dict(filled)
        self.state.missing_slots = list(missing)

    def reference(self, entity: Entity) -> None:
        """`entity` was just talked about: it is now what "it" and "that one" mean."""
        clipped = entity.clipped()
        rest = [e for e in self.state.last_referenced if e.id != clipped.id]
        self.state.last_referenced = [clipped, *rest][:MAX_REFERENCES]

    def ask(
        self, question_id: str, options: list[Option], *, ttl: timedelta = CLARIFICATION_TTL
    ) -> None:
        expires = (self._clock() + ttl).isoformat()
        self.state.pending_clarification = Clarification(
            question_id[:64],
            tuple(Option(o.id[:64], o.label[:MAX_LABEL]) for o in options[:5]),
            expires,
            self.state.turn_epoch,
        )

    def answer_clarification(self) -> Clarification | None:
        pending, self.state.pending_clarification = self.state.pending_clarification, None
        return pending

    def accept_proposal(self, action_id: str, entities: list[Entity] | None = None) -> None:
        """A proposal was accepted and committed: remember it for undo and persist (AR-LANG-005)."""
        now = self._clock()
        for entity in reversed(entities or []):
            self.reference(entity)
        self.state.committed = [
            CommittedAction(action_id[:64], now.isoformat()),
            *self.state.committed,
        ][:MAX_UNDO]
        self.state.active_intent = None
        self.state.filled_slots = {}
        self.state.missing_slots = []
        self.state.pending_clarification = None
        self._save()

    # ---- undo

    def undo_target(self) -> str | None:
        """The action "undo" would reverse: the newest committed, still within 24 hours."""
        return self.state.committed[0].action_id if self.state.committed else None

    def undone(self) -> None:
        """The undo succeeded; the pointer moves back to the action before it."""
        if self.state.committed:
            self.state.committed = self.state.committed[1:]
            self._save()

    # ---- barge-in

    def barge_in(self, new_epoch: int) -> None:
        """New turn epoch: a clarification that was being spoken is cancelled."""
        self.state.turn_epoch = new_epoch
        cancelled = self.state.pending_clarification is not None
        self.state.pending_clarification = None
        if cancelled:
            self._save()

    # ---- references

    def resolve_reference(self, phrase: str) -> Reference:
        """Resolve "it", "that one", "the last one", "the one before", "the last transaction"."""
        text = re.sub(r"\s+", " ", phrase.strip().lower().strip(".,!?"))
        pending = self.state.pending_clarification
        if pending is not None and not _expired(pending.expires_at, self._clock()):
            chosen = self._choose_among_options(text, pending)
            if chosen is not None:
                return chosen
        references = self.state.last_referenced
        if text in _PRONOUNS:
            if not references:
                return Reference("unresolved", phrase)
            return Reference("resolved", phrase, references[0])
        if _BEFORE.match(text):
            if len(references) < 2:
                return Reference("unresolved", phrase)
            return Reference("resolved", phrase, references[1])
        kind = _KIND.match(text)
        if kind is not None:
            matches = [e for e in references if e.kind == kind.group(1)]
            if not matches:
                return Reference("unresolved", phrase)
            return Reference("resolved", phrase, matches[0])
        return Reference("unresolved", phrase)

    @staticmethod
    def _choose_among_options(text: str, pending: Clarification) -> Reference | None:
        options = [Entity(o.id, "option", o.label) for o in pending.options]
        match = re.match(r"^(?:the )?(first|second|third|fourth|fifth)(?: one)?$", text)
        if match:
            index = _ORDINAL[match.group(1)]
            if index < len(options):
                return Reference("resolved", text, options[index])
            return Reference("unresolved", text)
        if text in _PRONOUNS and len(options) > 1:
            return Reference("ambiguous", text, candidates=tuple(options))
        if text in _PRONOUNS and len(options) == 1:
            return Reference("resolved", text, options[0])
        for option in options:
            if text == option.label.lower():
                return Reference("resolved", text, option)
        return None

    # ---- persistence

    def _save(self) -> None:
        self.state.saved_at = self._clock().isoformat()
        self._store.save(self._device_id, self.state)


def _age(iso: str | None, now: datetime) -> timedelta | None:
    if iso is None:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    return now - then


def _expired(iso: str, now: datetime) -> bool:
    age = _age(iso, now)
    return age is None or age >= timedelta(0)

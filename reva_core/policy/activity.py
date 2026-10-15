"""The Activity page's rows: every action with time, request, action, from, result and evidence.

Built only from the action ledger, which already holds redacted arguments, so nothing here can leak
an amount or a note. The result is a short plain statement of what the ledger says happened; it is
display text for the owner, not something REVA speaks.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from reva_core.policy.ledger import ActionLedger, LedgerRow

MAX_ROWS = 100

_RESULT = {
    "verified": "Done (confirmed)",
    "unknown": "Couldn't confirm",
    "failed": "Didn't work",
    "denied": "Declined",
    "attempted": "Started",
    "observed": "Started",
}

_ACTION_LABELS = {
    "windows.app.open": "Open {app}",
    "windows.app.close": "Close {app}",
    "finance.add_transaction": "Add an expense",
    "finance.summary": "Show spending",
    "today.get": "Show today",
    "memory.remember": "Save a note",
    "memory.recall": "Look up a note",
    "assistant.stop": "Stop",
    "assistant.repeat": "Repeat",
    "assistant.undo": "Undo the last expense",
}

_SOURCES = {"voice": "Voice", "ui": "Screen", "typed": "Typed", "phone": "Phone"}


def recent(
    ledger: ActionLedger, app_names: Mapping[str, str] | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, MAX_ROWS))
    grouped: dict[str, list[LedgerRow]] = {}
    for row in ledger.recent(limit * 12):  # newest events first; a few events per action
        grouped.setdefault(row.action_id, []).append(row)
    entries: list[dict[str, Any]] = []
    for rows in grouped.values():
        entry = _entry(sorted(rows, key=lambda r: r.seq), app_names or {})
        if entry is not None:
            entries.append(entry)
    entries.sort(key=lambda e: e["time"], reverse=True)
    return entries[:limit]


def _entry(rows: list[LedgerRow], names: Mapping[str, str]) -> dict[str, Any] | None:
    first = next((r for r in rows if r.kind == "proposed"), None)
    if first is None:
        return None  # the start fell outside the window; show it once it is complete
    payload = first.payload
    capability = str(payload.get("capability", ""))
    args = payload.get("args") or {}
    app = names.get(str(args.get("app_key", "")), str(args.get("app_key", "an app")))
    label = _ACTION_LABELS.get(capability, capability).format(app=app)
    result, evidence = _result(rows, first)
    return {
        "action_id": first.action_id,
        "time": first.at,
        "request": label,
        "action": capability,
        "from": _SOURCES.get(str(payload.get("source", "")), str(payload.get("source", "")) or "-"),
        "result": result,
        "evidence": evidence,
    }


def _result(rows: list[LedgerRow], first: LedgerRow) -> tuple[str, str | None]:
    kinds = [r.kind for r in rows]
    for row in reversed(rows):
        if row.kind == "outcome":
            status = str(row.payload.get("status", ""))
            evidence = row.payload.get("evidence") or {}
            ref = evidence.get("ref") if isinstance(evidence, dict) else None
            return _RESULT.get(status, status), (str(ref) if ref else None)
        if row.kind in ("denied", "expired"):
            return ("Declined" if row.kind == "denied" else "Timed out"), None
        if row.kind == "refused":
            reason = str(row.payload.get("reason", "")).replace("_", " ").lower()
            return f"Refused ({reason})", None
    if "granted" in kinds:
        return "Waiting for the app", None
    if "awaiting_approval" in kinds:
        return "Waiting for your approval", None
    return ("Allowed" if first.payload.get("allowed") else "Refused"), None

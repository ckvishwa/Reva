"""The Kernel executor for a voice expense (AR-VA-FIN, ARD-600 section 4).

Runs only after the broker has signed a grant for `finance.add_transaction`, which for a T2 action
means after a click or tap on the confirm card. It writes one transaction through the same Domain
Kernel command the Finance page uses, then reports back what the Kernel returned. REVA says
"Saved." only from that event id (the broker turns a `verified` report with kernel evidence into
the template); a missing account, a Kernel error or anything unexpected is `failed`, never success.

Money out is stored negative, in minor units, from the typed amount the normalizer produced. The
amount is never read from model text.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from reva_core.domains.service import DomainService
from reva_core.policy.broker import ExecutionOrder

logger = logging.getLogger(__name__)

UNCATEGORISED = "Uncategorised"
MAX_UNDOABLE = 32


class ExpenseLog:
    """The expenses this Core saved by voice, keyed by the action that saved them, so a later
    `assistant.undo` can name exactly one transaction. Only an expense the Kernel confirmed is ever
    recorded. Held in memory and bounded: after a restart nothing is undoable, and REVA says so."""

    def __init__(self, limit: int = MAX_UNDOABLE) -> None:
        self._limit = limit
        self._rows: OrderedDict[str, str] = OrderedDict()

    def record(self, action_id: str, transaction_id: str) -> None:
        self._rows[action_id] = transaction_id
        while len(self._rows) > self._limit:
            self._rows.popitem(last=False)

    def get(self, action_id: str) -> str | None:
        return self._rows.get(action_id)

    def forget(self, action_id: str) -> None:
        self._rows.pop(action_id, None)

    def undoable(self, action_id: str) -> bool:
        return action_id in self._rows


class FinanceExpenseExecutor:
    def __init__(
        self,
        service: Callable[[], DomainService],
        today: Callable[[], date] = date.today,
        log: ExpenseLog | None = None,
    ) -> None:
        self._service = service
        self._today = today
        self._log = log

    def __call__(self, order: ExecutionOrder) -> tuple[str, Mapping[str, Any] | None]:
        args = order.args
        amount = Decimal(str(args["amount"])).quantize(Decimal("0.01"), ROUND_HALF_UP)
        minor = int(amount * 100)
        if minor <= 0:
            return "failed", None
        service = self._service()
        handle = service.handle("finance")
        module = service.binding()
        try:
            account = self._first_account(handle, str(args.get("currency", "")))
            if account is None:
                return "failed", None
            body: dict[str, Any] = {
                "account_id": account,
                "date": self._today().isoformat(),
                "amount_minor": -minor,
                "description": str(args.get("note") or args.get("category") or "Expense")[:200],
            }
            category = self._category(handle, str(args.get("category", "")))
            if category is not None:
                body["category"] = category
            result = handle.command("transaction.create", json.dumps(body))
        except module.DomainError:
            logger.warning("voice expense was refused by the Kernel", exc_info=True)
            return "failed", None
        service.note_change("finance")
        if self._log is not None:
            self._log.record(order.grant.action_id, str(result.aggregate_id))
        return "verified", {"kind": "kernel_event", "ref": str(result.event_id)}

    @staticmethod
    def _first_account(handle: Any, currency: str) -> str | None:
        rows = json.loads(handle.query("list_accounts", "{}").rows_json)
        usable = [r for r in rows if not r.get("archived")]
        same = [r for r in usable if str(r.get("currency", "")).upper() == currency.upper()]
        chosen = (same or usable or [None])[0]
        return str(chosen["id"]) if chosen else None

    @staticmethod
    def _category(handle: Any, wanted: str) -> str | None:
        if not wanted or wanted == UNCATEGORISED:
            return None
        for row in json.loads(handle.query("list_categories", "{}").rows_json):
            names = [str(row.get("name", "")), *map(str, row.get("aliases") or [])]
            if wanted.lower() in (n.lower() for n in names):
                return str(row["name"])
        return None


class ExpenseUndoExecutor:
    """Reverses one voice expense the same way the Finance page deletes a transaction: a Kernel
    `transaction.delete`, which writes a tombstone event (nothing is erased, and sync carries it).

    It acts only on a signed grant for `assistant.undo` (T2: a click on the confirm card) and only
    on an expense this Core recorded in `ExpenseLog`; anything else, including an expense already
    undone, is `failed`. "Undone." is said only from the tombstone event the Kernel returned."""

    def __init__(self, service: Callable[[], DomainService], log: ExpenseLog) -> None:
        self._service = service
        self._log = log

    def __call__(self, order: ExecutionOrder) -> tuple[str, Mapping[str, Any] | None]:
        target = str(order.args.get("target_action_id", ""))
        transaction_id = self._log.get(target)
        if transaction_id is None:
            return "failed", None
        service = self._service()
        handle = service.handle("finance")
        module = service.binding()
        try:
            result = handle.command("transaction.delete", json.dumps({"id": transaction_id}))
        except module.DomainError:
            logger.warning("undo was refused by the Kernel", exc_info=True)
            self._log.forget(target)  # already deleted or gone: not undoable again
            return "failed", None
        self._log.forget(target)
        service.note_change("finance")
        return "verified", {"kind": "kernel_event", "ref": str(result.event_id)}

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
from collections.abc import Callable, Mapping
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from reva_core.domains.service import DomainService
from reva_core.policy.broker import ExecutionOrder

logger = logging.getLogger(__name__)

UNCATEGORISED = "Uncategorised"


class FinanceExpenseExecutor:
    def __init__(
        self,
        service: Callable[[], DomainService],
        today: Callable[[], date] = date.today,
    ) -> None:
        self._service = service
        self._today = today

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

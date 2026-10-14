"""Convert a legacy AuraO finance database into a Kernel Finance export, and dry-run it.

Usage (repo root, Kernel binding built):
    python tools/finance/legacy_aura_to_kernel.py --db <legacy.sqlite3> [--out export.json]

What it does
* Copies the legacy file to a temp directory first; the original is never opened.
* Reads only PLAINTEXT legacy databases (the early AuraO builds). An encrypted legacy file is
  reported and left alone: it needs the legacy key and a SQLCipher reader, which is a separate,
  explicitly approved step.
* Builds the Kernel JSON export document in memory and imports it as a DRY RUN into a scratch
  Kernel install (temp directory, in-memory key, never the real vault or data directory).
* Reconciles balances: legacy opening + effects must equal the Kernel balance for every account.
* Writes the export to --out only if you ask (put it outside git; delete it after the import).
* Never imports into the real Finance domain. That is a separate, approved step.

Amount rules follow the legacy `ledger_effect`: amounts are stored as magnitudes and the entry type
decides the direction. Liability accounts (credit card, loan) are stored by the Kernel as negative
balances (money owed), so their effects are negated.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KIND_MAP = {
    "CASH": "cash",
    "CHECKING": "checking",
    "SAVINGS": "savings",
    "CREDIT_CARD": "credit",
    "LOAN": "loan",
}
LIABILITY = {"CREDIT_CARD", "LOAN"}
RECURRENCE = {"WEEKLY": "weekly", "BIWEEKLY": "biweekly", "MONTHLY": "monthly", "ONE_TIME": "once"}
ASSET_PLUS = {"INCOME", "TRANSFER_IN", "ADJUSTMENT"}
LIABILITY_MINUS = {"DEBT_PAYMENT", "TRANSFER_OUT", "INCOME"}


def effect(account_kind: str, entry_type: str, amount_cents: int) -> int:
    """Signed change to the *legacy* balance (liabilities: change to the amount owed)."""
    magnitude = abs(amount_cents)
    if account_kind in LIABILITY:
        return -magnitude if entry_type in LIABILITY_MINUS else magnitude
    return magnitude if entry_type in ASSET_PLUS else -magnitude


def category_kind(entry_types: set[str]) -> str:
    if entry_types <= {"TRANSFER_IN", "TRANSFER_OUT", "ADJUSTMENT"}:
        return "transfer"
    if entry_types <= {"INCOME", "INTEREST"}:
        return "income"
    return "expense"


def short_date(value: str) -> str:
    return value[:10]


def convert(db: sqlite3.Connection) -> tuple[dict[str, Any], dict[str, int], list[str]]:
    """Return (kernel export document, legacy balances by kernel account id, notes)."""
    db.row_factory = sqlite3.Row
    notes: list[str] = []
    accounts = db.execute(
        "SELECT * FROM finance_accounts WHERE deleted_at IS NULL ORDER BY created_at, id"
    ).fetchall()
    entries = db.execute(
        "SELECT * FROM finance_ledger_entries WHERE deleted_at IS NULL ORDER BY occurred_at, id"
    ).fetchall()
    obligations = db.execute(
        "SELECT * FROM finance_obligations WHERE deleted_at IS NULL"
    ).fetchall()
    income = db.execute("SELECT * FROM finance_income_sources WHERE deleted_at IS NULL").fetchall()
    settings = db.execute("SELECT * FROM finance_settings").fetchall()

    by_account = {a["id"]: a for a in accounts}
    kernel_id = {a["id"]: f"aura-acct-{a['id']}" for a in accounts}
    categories: dict[str, set[str]] = {}
    for e in entries:
        name = (e["category"] or "").strip()
        if name:
            categories.setdefault(name, set()).add(e["entry_type"])

    doc: dict[str, Any] = {
        "format": "reva-finance-export",
        "version": 1,
        "accounts": [],
        "categories": [],
        "budgets": [],
        "bills": [],
        "transactions": [],
        "networth_snapshots": [],
    }
    legacy_balance: dict[str, int] = {}

    for a in accounts:
        sign = -1 if a["kind"] in LIABILITY else 1
        opening = sign * abs(a["opening_balance_cents"])
        doc["accounts"].append(
            {
                "id": kernel_id[a["id"]],
                "name": a["name"],
                "kind": KIND_MAP[a["kind"]],
                "currency": a["currency"],
                "opening_balance_minor": opening,
                "archived": bool(a["is_archived"]),
                "created_at": a["created_at"],
                "updated_at": a["updated_at"],
            }
        )
        legacy_balance[kernel_id[a["id"]]] = opening
        if a["institution_name"]:
            notes.append("institution_name is not stored by the Kernel; it is dropped")

    for name in sorted(categories):
        doc["categories"].append(
            {
                "id": "aura-cat-"
                + "".join(ch if ch.isalnum() else "-" for ch in name.lower())[:50],
                "name": name,
                "kind": category_kind(categories[name]),
                "aliases": [],
            }
        )
    category_id = {c["name"]: c["id"] for c in doc["categories"]}
    if len(category_id) != len(doc["categories"]):
        notes.append("two legacy categories collapsed to the same name")

    for e in entries:
        account = by_account.get(e["account_id"])
        if account is None:
            notes.append("a ledger entry references a missing account and is skipped")
            continue
        change = effect(account["kind"], e["entry_type"], e["amount_cents"])
        kernel_amount = -change if account["kind"] in LIABILITY else change
        legacy_balance[kernel_id[account["id"]]] += kernel_amount
        category = (e["category"] or "").strip()
        doc["transactions"].append(
            {
                "id": f"aura-tx-{e['id']}",
                "account_id": kernel_id[account["id"]],
                "date": short_date(e["occurred_at"]),
                "amount_minor": kernel_amount,
                "currency": account["currency"],
                "description": (e["description"] or category or e["entry_type"].title()).strip(),
                "category_id": category_id.get(category),
                "notes": f"Imported from AuraO ({e['entry_type']}, source {e['source']})",
                "created_at": e["created_at"],
                "updated_at": e["updated_at"],
            }
        )

    for source, kind, due_column in (
        (obligations, "bill", "next_due_at"),
        (income, "income", "next_expected_at"),
    ):
        for o in source:
            linked = o["linked_account_id"]
            currency = (
                by_account[linked]["currency"]
                if linked in by_account
                else (settings[0]["currency"] if settings else "USD")
            )
            doc["bills"].append(
                {
                    "id": f"aura-bill-{o['id']}",
                    "name": o["name"],
                    "kind": kind,
                    "amount_minor": abs(o["amount_cents"]),
                    "currency": currency,
                    "recurrence": RECURRENCE[o["frequency"]],
                    "due_date": short_date(o[due_column]),
                    "account_id": kernel_id.get(linked),
                    "active": bool(o["is_active"]),
                    "anchor_day": int(short_date(o[due_column])[8:10]),
                    "created_at": o["created_at"],
                    "updated_at": o["updated_at"],
                }
            )
    if settings:
        notes.append(
            "finance_settings has no Kernel concept (reserve, horizon, safe-spend); not mapped"
        )
    return doc, legacy_balance, notes


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="legacy reva-finance.sqlite3 (plaintext)"
    )
    parser.add_argument(
        "--out", type=Path, help="also write the Kernel export JSON here (outside git)"
    )
    args = parser.parse_args()

    scratch = Path(tempfile.mkdtemp(prefix="legacy-aura-"))
    try:
        copy = scratch / "legacy.sqlite3"
        shutil.copy2(args.db, copy)
        if copy.read_bytes()[:15] != b"SQLite format 3":
            print("The legacy database is encrypted. Plaintext files only; nothing was changed.")
            return 2
        db = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
        doc, legacy_balance, notes = convert(db)
        db.close()
        payload = json.dumps(doc, indent=1).encode("utf-8")
        if args.out:
            args.out.write_bytes(payload)
            print(f"wrote {args.out} (outside git; delete it after the import)")

        from reva_core.domains.kernel_loader import load_kernel

        binding = load_kernel()

        class Vault:  # scratch vault: never the real Credential Manager
            def __init__(self) -> None:
                self.keys: dict[str, bytes] = {}

            def load_key(self, domain: str):
                return self.keys.get(domain)

            def store_key(self, domain: str, key: bytes) -> None:
                self.keys[domain] = bytes(key)

        handle = binding.open_domain("finance", Vault(), str(scratch / "kernel"))
        dry = handle.import_data("json", payload, json.dumps({"dry_run": True}))
        print(
            f"DRY RUN: accepted {dry.accepted}, duplicates {dry.duplicates}, "
            f"rejected {len(dry.rejected)}"
        )
        for r in dry.rejected:
            print(f"  rejected record {r.row}: {r.reason}")
        # Real import into the SCRATCH install only, to reconcile balances.
        handle.import_data("json", payload, "{}")
        balances = json.loads(
            handle.query("account_balances", json.dumps({"include_archived": True})).rows_json
        )
        all_equal = True
        for row in balances:
            expected = legacy_balance.get(row["account_id"])
            equal = expected == row["balance_minor"]
            all_equal &= equal
            print(
                f"  reconcile {row['account_id'][:22]}...: legacy {expected} == "
                f"kernel {row['balance_minor']} -> {equal}"
            )
        for note in sorted(set(notes)):
            print(f"  note: {note}")
        print("RECONCILED" if all_equal and not dry.rejected else "NOT RECONCILED - do not import")
        return 0 if all_equal and not dry.rejected else 1
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())

"""Capture real REVA Core responses for the Finance screens as JSON fixtures.

Usage (repo root, Kernel binding built):
    python tools/desktop/generate_finance_fixtures.py          # rewrite the committed fixtures
    python tools/desktop/generate_finance_fixtures.py --check  # fail if they are out of date

The C# API-client contract tests (desktop/tests/Reva.Desktop.Tests/Fixtures/finance) deserialize
these files into the C# records, so a change to a Core response shape breaks a test on one side
or the other. Volatile values (timestamps, ids generated at run time, event and batch ids) are
replaced by fixed ones so the files are stable.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
FIXTURE_DIR = ROOT / "desktop" / "tests" / "Reva.Desktop.Tests" / "Fixtures" / "finance"

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
VOLATILE_KEYS = {"created_at", "updated_at", "detected_at", "event_id", "batch_id", "fingerprint"}
AS_OF = "2026-10-12"


def normalise(value: Any, seen: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            k: (
                "2026-01-01T00:00:00.000Z"
                if k in VOLATILE_KEYS and k.endswith("_at")
                else _norm_key(k, v, seen)
            )
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [normalise(v, seen) for v in value]
    if isinstance(value, str) and UUID.match(value):
        return seen.setdefault(value, f"00000000-0000-0000-0000-{len(seen) + 1:012d}")
    return value


def _norm_key(key: str, value: Any, seen: dict[str, str]) -> Any:
    if key in {"event_id", "batch_id", "fingerprint"} and isinstance(value, str):
        return {"event_id": "EVENT", "batch_id": "BATCH", "fingerprint": "FINGERPRINT"}[key]
    return normalise(value, seen)


def build() -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from reva_core.api.app import create_app
    from reva_core.config.settings import load_settings
    from reva_core.domains.kernel_loader import load_kernel
    from reva_core.domains.keys import InMemoryKeyProvider
    from reva_core.orchestration.lifecycle import CoreLifecycle

    binding = load_kernel()
    out: dict[str, Any] = {}
    # Open Kernel handles keep their files locked on Windows until they are collected, so a failed
    # cleanup of these scratch directories is ignored.
    with (
        tempfile.TemporaryDirectory(prefix="reva-fixtures-", ignore_cleanup_errors=True) as tmp,
        tempfile.TemporaryDirectory(prefix="reva-phone-", ignore_cleanup_errors=True) as phone_dir,
    ):
        settings = load_settings(
            _env_file=None, data_dir=Path(tmp), assistant_orchestrator="deterministic"
        )
        core = CoreLifecycle(settings, domain_key_provider=InMemoryKeyProvider())
        core.startup()
        try:
            client = TestClient(create_app(core))
            client.headers.update({"Authorization": f"Bearer {core.local_token}"})
            F = "/v1/domains/finance"

            def post(path: str, body: dict[str, Any]) -> Any:
                response = client.post(path, json=body)
                assert response.status_code in (200, 201), (path, response.text)
                return response.json()

            post(
                f"{F}/accounts",
                {
                    "id": "acct-checking",
                    "name": "Checking",
                    "kind": "checking",
                    "currency": "USD",
                    "opening_balance_minor": 500000,
                },
            )
            post(
                f"{F}/accounts",
                {
                    "id": "acct-card",
                    "name": "Credit card",
                    "kind": "credit",
                    "currency": "USD",
                    "opening_balance_minor": -20000,
                },
            )
            post(
                f"{F}/accounts",
                {
                    "id": "acct-savings",
                    "name": "Savings",
                    "kind": "savings",
                    "currency": "USD",
                    "opening_balance_minor": 1500000,
                },
            )
            post(
                f"{F}/categories",
                {"id": "cat-dining", "name": "Food · Dining", "aliases": ["lunch", "restaurants"]},
            )
            post(
                f"{F}/categories",
                {"id": "cat-groceries", "name": "Groceries", "aliases": ["supermarket"]},
            )
            post(f"{F}/categories", {"id": "cat-income", "name": "Income", "kind": "income"})
            post(
                f"{F}/transactions",
                {
                    "id": "tx-lunch-0001",
                    "account_id": "acct-card",
                    "date": AS_OF,
                    "amount_minor": -1200,
                    "description": "Lunch",
                    "category": "lunch",
                    "source": "voice",
                },
            )
            post(
                f"{F}/transactions",
                {
                    "id": "tx-market-001",
                    "account_id": "acct-card",
                    "date": "2026-10-10",
                    "amount_minor": -8450,
                    "description": "Market",
                    "category": "supermarket",
                },
            )
            post(
                f"{F}/transactions",
                {
                    "id": "tx-pay-00001",
                    "account_id": "acct-checking",
                    "date": "2026-10-01",
                    "amount_minor": 300000,
                    "description": "Paycheck",
                    "category": "Income",
                },
            )
            post(
                f"{F}/budgets",
                {
                    "id": "bud-dining-01",
                    "category_id": "cat-dining",
                    "amount_minor": 20000,
                    "currency": "USD",
                    "start_month": "2026-01",
                },
            )
            post(
                f"{F}/budgets",
                {
                    "id": "bud-grocer-01",
                    "category_id": "cat-groceries",
                    "amount_minor": 50000,
                    "currency": "USD",
                    "start_month": "2026-01",
                },
            )
            post(
                f"{F}/bills",
                {
                    "id": "bill-rent-001",
                    "name": "Rent",
                    "amount_minor": 120000,
                    "currency": "USD",
                    "recurrence": "monthly",
                    "due_date": "2026-10-14",
                },
            )
            post(
                f"{F}/bills",
                {
                    "id": "bill-phone-01",
                    "name": "Phone",
                    "amount_minor": 4500,
                    "currency": "USD",
                    "recurrence": "monthly",
                    "due_date": "2026-10-18",
                },
            )
            post(
                f"{F}/bills",
                {
                    "id": "bill-stream-1",
                    "name": "Streaming",
                    "kind": "subscription",
                    "amount_minor": 1500,
                    "currency": "USD",
                    "recurrence": "monthly",
                    "due_date": "2026-11-02",
                },
            )
            post(f"{F}/networth-snapshots", {"id": "nw-20261012", "as_of": AS_OF})
            csv = (
                "Date,Memo,Amount\n2026-10-03,Imported coffee,-4.50\n"
                "2026-10-04,Imported refund,12.00\nbad,Row,1.00\n"
            )
            options = {
                "account_id": "acct-checking",
                "mapping": {"date": "Date", "description": "Memo", "amount": "Amount"},
            }
            out["import-dry-run"] = post(
                f"{F}/import",
                {
                    "format": "csv",
                    "data_base64": base64.b64encode(csv.encode()).decode(),
                    "options": {**options, "dry_run": True},
                },
            )
            post(
                f"{F}/import",
                {
                    "format": "csv",
                    "data_base64": base64.b64encode(csv.encode()).decode(),
                    "options": options,
                },
            )

            # A phone: a second Kernel install that adds a transaction and disagrees on an amount.
            phone = binding.open_domain("finance", InMemoryKeyProvider(), phone_dir)
            pc = core.domain_service.handle("finance")
            first = pc.pending_events(1000)
            pc.ack(first.cursor)
            phone.apply_events(first)
            phone.command(
                "transaction.create",
                json.dumps(
                    {
                        "id": "tx-phone-0001",
                        "account_id": "acct-card",
                        "date": "2026-10-11",
                        "amount_minor": -2300,
                        "description": "Taxi",
                    }
                ),
            )
            phone.command(
                "transaction.update", json.dumps({"id": "tx-market-001", "amount_minor": -8540})
            )
            client.patch(f"{F}/transactions/tx-market-001", json={"amount_minor": -8450 + 1})
            from_pc, from_phone = pc.pending_events(1000), phone.pending_events(1000)
            phone.apply_events(from_pc)
            pc.apply_events(from_phone)

            get = lambda path: client.get(path).json()  # noqa: E731
            out["balances"] = get(f"{F}/reports/account_balances?as_of={AS_OF}")
            out["categories"] = get(f"{F}/categories")
            out["transactions"] = get(f"{F}/transactions?limit=100")
            out["transactions-search"] = get(f"{F}/transactions?limit=100&q=lunch")
            out["budget-status"] = get(f"{F}/reports/budget_status?month=2026-10&as_of={AS_OF}")
            out["bills"] = get(f"{F}/reports/upcoming_bills?days=366&as_of={AS_OF}")
            out["networth-snapshots"] = get(f"{F}/networth-snapshots")
            out["conflicts"] = get(f"{F}/conflicts")
            out["privacy"] = get(f"{F}/privacy")
            out["privacy-after-patch"] = client.patch(
                f"{F}/privacy", json={"hosted_model_access": True}
            ).json()
            client.patch(f"{F}/privacy", json={"hosted_model_access": False})
            out["today"] = get(f"/v1/today?as_of={AS_OF}")
            out["domains"] = get("/v1/domains")
            out["commit"] = post(
                f"{F}/transactions",
                {
                    "id": "tx-new-00001",
                    "account_id": "acct-checking",
                    "date": AS_OF,
                    "amount_minor": -500,
                    "description": "Coffee",
                    "source": "manual",
                },
            )
            out["error-validation"] = {
                "status": 422,
                "body": client.post(
                    f"{F}/transactions",
                    json={
                        "account_id": "acct-checking",
                        "date": AS_OF,
                        "amount_minor": -1,
                        "description": "x",
                        "category": "nonexistent",
                    },
                ).json(),
            }
            out["error-conflict"] = {
                "status": 409,
                "body": client.post(
                    f"{F}/accounts",
                    json={"id": "acct-checking", "name": "Another", "currency": "USD"},
                ).json(),
            }
            out["error-not-found"] = {
                "status": 404,
                "body": client.get(f"{F}/transactions/tx-nope-0001").json(),
            }
            client.delete(f"{F}/transactions/tx-new-00001")
            out["error-deleted"] = {
                "status": 410,
                "body": client.get(f"{F}/transactions/tx-new-00001").json(),
            }
        finally:
            core.shutdown()

        class Locked:
            def load_key(self, domain: str) -> bytes | None:
                raise RuntimeError("vault offline")

            def store_key(self, domain: str, key: bytes) -> None:
                raise RuntimeError("vault offline")

        locked_settings = load_settings(
            _env_file=None, data_dir=Path(tmp) / "locked", assistant_orchestrator="deterministic"
        )
        locked = CoreLifecycle(locked_settings, domain_key_provider=Locked())
        locked.startup()
        try:
            client = TestClient(create_app(locked))
            client.headers.update({"Authorization": f"Bearer {locked.local_token}"})
            response = client.get("/v1/domains/finance/accounts")
            out["error-locked"] = {"status": response.status_code, "body": response.json()}
        finally:
            locked.shutdown()

    seen: dict[str, str] = {}
    result: dict[str, Any] = {}
    for key, value in out.items():
        correlation_free = _drop_correlation(value)
        result[key] = normalise(correlation_free, seen)
    return result


def _drop_correlation(value: Any) -> Any:
    """Correlation ids are random per request; the contract does not depend on their value."""
    if isinstance(value, dict):
        return {
            k: ("CORRELATION" if k == "correlation_id" and v else _drop_correlation(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_drop_correlation(v) for v in value]
    return value


def render(fixtures: dict[str, Any]) -> dict[str, str]:
    return {
        f"{name}.json": json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        for name, data in fixtures.items()
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed fixtures differ"
    )
    args = parser.parse_args()
    files = render(build())
    if args.check:
        stale = [
            name
            for name, text in files.items()
            if not (FIXTURE_DIR / name).exists()
            or (FIXTURE_DIR / name).read_text(encoding="utf-8") != text
        ]
        extra = (
            sorted(p.name for p in FIXTURE_DIR.glob("*.json") if p.name not in files)
            if FIXTURE_DIR.exists()
            else []
        )
        if stale or extra:
            print("fixtures out of date:", stale, "unexpected:", extra)
            return 1
        print(f"{len(files)} fixtures are current")
        return 0
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (FIXTURE_DIR / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(files)} fixtures to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

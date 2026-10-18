"""PRE-00 contract oracle. This is synthetic acceptance evidence, not a shipped planner.

The Rust implementation of these semantics is FIE-01/FIE-02. Keep this test-only
reference separate so a passing contract test cannot be mistaken for a live API.
"""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "contracts/finance-monthly-plan.v1.schema.json").read_text())
FIXTURE = json.loads((ROOT / "tests/fixtures/finance_intelligence/november_2026.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def _dates(start: str, days: int) -> list[str]:
    first = date.fromisoformat(start)
    return [(first + timedelta(days=offset)).isoformat() for offset in range(days)]


def _records():
    return [
        row
        for row in FIXTURE["records"]
        if row["currency"] == "USD"
        and row["date"] > FIXTURE["request"]["as_of"]
        and "import_disposition" not in row
        and row["kind"] != "untrusted_text_only"
    ]


def _reference(scenario: dict | None = None) -> dict:
    """Independent, test-only integer reference for the static golden vector."""
    request = FIXTURE["request"]
    accounts = {a["id"]: a for a in FIXTURE["accounts"]}
    cash_ids = set(FIXTURE["cash_account_ids"])
    opening = sum(accounts[aid]["as_of_balance_minor"] for aid in cash_ids)
    reserve = FIXTURE["reserve"]["amount_minor"]
    savings = FIXTURE["savings_plan"]
    rows = copy.deepcopy(_records())
    if scenario:
        for flow in scenario["cash_flows"]:
            if flow["currency"] != request["currency"]:
                raise ValueError("currency mismatch")
            if flow["account_id"] not in cash_ids:
                raise ValueError("scenario account is not a cash account")
            rows.append({**flow, "kind": "hypothetical", "source_id": flow["id"]})
    dates = _dates(request["as_of"], request["horizon_days"])
    balance = opening
    days = []
    for day in dates:
        day_rows = [r for r in rows if r["date"] == day and r["account_id"] in cash_ids]
        balance += sum(r["amount_minor"] for r in day_rows)
        pending_savings = (
            savings["target_minor"]
            if day < "2026-11-20"
            else savings["remaining_virtual_earmark_minor"]
        )
        days.append(
            {
                "date": day,
                "cash_balance_minor": balance,
                "cash_headroom_minor": balance - reserve - pending_savings,
                "source_ids": ["checking", *[r["id"] for r in day_rows]],
            }
        )
    minimum = min(day["cash_headroom_minor"] for day in days)
    amounts = {
        "cash_available_minor": opening,
        "confirmed_income_minor": 0,
        "expected_income_minor": sum(
            r["amount_minor"] for r in rows if r["kind"] == "expected_income"
        ),
        "scheduled_obligations_minor": -sum(
            r["amount_minor"] for r in rows if r["kind"] in {"fixed_expense", "variable_expense"}
        ),
        "required_debt_payments_minor": sum(
            item["payment_minor"] for item in FIXTURE["debt_terms"]
        ),
        "planned_savings_minor": FIXTURE["savings_plan"]["target_minor"],
        "minimum_cash_reserve_minor": reserve,
        "minimum_projected_cash_headroom_minor": minimum,
        "safe_to_spend_minor": max(0, minimum),
        "projected_shortfall_minor": max(0, -minimum),
    }
    ids = [a["id"] for a in FIXTURE["accounts"] if a["id"] in cash_ids]
    ids += [r["id"] for r in rows]
    ids += [item["id"] for item in FIXTURE["debt_terms"]]
    ids += [FIXTURE["savings_plan"]["id"], FIXTURE["reserve"]["id"]]
    ids = list(dict.fromkeys(ids))
    excluded_currencies = sorted(
        {r["currency"] for r in FIXTURE["records"] if r["currency"] != request["currency"]}
    )
    obligations = [r["id"] for r in rows if r["kind"] in {"fixed_expense", "variable_expense"}]
    evidence = {
        "cash_available_minor": ["checking"],
        "confirmed_income_minor": ["checking"],
        "expected_income_minor": [r["id"] for r in rows if r["kind"] == "expected_income"],
        "scheduled_obligations_minor": obligations,
        "required_debt_payments_minor": [item["id"] for item in FIXTURE["debt_terms"]],
        "planned_savings_minor": [savings["id"], "tx-savings-out", "tx-savings-in"],
        "minimum_cash_reserve_minor": [FIXTURE["reserve"]["id"]],
        "minimum_projected_cash_headroom_minor": ids,
        "safe_to_spend_minor": ids,
        "projected_shortfall_minor": ids,
    }
    return {
        "schema_version": 1,
        "status": "shortfall" if minimum < 0 else "ready",
        "as_of": request["as_of"],
        "horizon_days": request["horizon_days"],
        "currency": request["currency"],
        "hypothetical": scenario is not None,
        **amounts,
        "projected_daily_cash_balances": days,
        "source_ids": ids,
        "components": [{"field": field, "source_ids": evidence[field]} for field in amounts],
        "assumptions": [
            "Synthetic scheduled dates and amounts are confirmed as fixture inputs.",
            *[
                f"{currency} records excluded from USD plan; no FX conversion."
                for currency in excluded_currencies
            ],
        ],
        "missing_inputs": [],
        "engine_version": "pre00-reference-v1",
    }


def test_request_and_response_validate_against_mirrored_schema():
    assert (
        json.loads(
            (
                ROOT / "docs/spec/REVA_v2.0/08_CONTRACTS/finance-monthly-plan.v1.schema.json"
            ).read_text()
        )
        == SCHEMA
    )
    VALIDATOR.validate(FIXTURE["request"])
    VALIDATOR.validate(_reference())


def test_money_is_integer_and_expenses_do_not_double_count_imports():
    result = _reference()
    assert FIXTURE["fictional_only"] is True
    assert result["scheduled_obligations_minor"] == 163500
    assert result["expected_income_minor"] == 300000
    assert "tx-duplicate-attempt" not in result["source_ids"]
    original, duplicate = (
        next(r for r in FIXTURE["records"] if r["id"] == row_id)
        for row_id in ("tx-groceries-1", "tx-duplicate-attempt")
    )
    assert original["source"] == duplicate["source"] == "csv"
    assert original["fingerprint"] == duplicate["fingerprint"]
    assert duplicate["import_disposition"] == "rejected_duplicate_of:tx-groceries-1"
    assert all(type(r["amount_minor"]) is int for r in FIXTURE["records"])


def test_transfers_are_neither_income_nor_expense():
    result = _reference()
    assert result["expected_income_minor"] == 300000
    assert result["scheduled_obligations_minor"] == 163500
    assert sum(r["amount_minor"] for r in _records() if r["kind"] == "transfer") == 0
    assert FIXTURE["golden"]["savings_closing_balance_minor"] == 30000


def test_card_purchase_is_spending_once_and_repayments_are_not_spending():
    rows = _records()
    purchase = [r for r in rows if r["kind"] == "card_purchase"]
    payments = [r for r in rows if r["kind"] == "card_payment"]
    assert sum(-r["amount_minor"] for r in purchase) == 20000
    assert sum(r["amount_minor"] for r in payments) == 0
    assert (
        -30000 + sum(r["amount_minor"] for r in purchase + payments if r["account_id"] == "card")
        == -37000
    )
    assert _reference()["scheduled_obligations_minor"] == 163500
    recognized_expense_minor = (
        _reference()["scheduled_obligations_minor"]
        + -sum(r["amount_minor"] for r in purchase)
        + FIXTURE["debt_terms"][0]["interest_minor"]
    )
    assert recognized_expense_minor == 186500


def test_paid_bill_and_matching_import_do_not_create_future_cash_outflow():
    paid = FIXTURE["bill_matches"][0]
    assert paid["status"] == "paid"
    assert paid["matched_transaction_id"] == "tx-paid-bill"
    assert paid["bill_id"] not in _reference()["source_ids"]
    assert paid["matched_transaction_id"] not in _reference()["source_ids"]


def test_dated_balances_match_independently_stored_30_day_golden_vector():
    result = _reference()
    expected = FIXTURE["golden"]["daily"]
    for field in (
        "confirmed_income_minor",
        "expected_income_minor",
        "scheduled_obligations_minor",
        "required_debt_payments_minor",
        "planned_savings_minor",
        "minimum_cash_reserve_minor",
        "minimum_projected_cash_headroom_minor",
        "safe_to_spend_minor",
        "projected_shortfall_minor",
    ):
        assert result[field] == FIXTURE["golden"][field]
    assert len(expected) == len(result["projected_daily_cash_balances"]) == 30
    assert [
        {k: row[k] for k in ("date", "cash_balance_minor", "cash_headroom_minor")}
        for row in result["projected_daily_cash_balances"]
    ] == expected
    assert expected[-1]["cash_balance_minor"] == 148500


def test_temporary_shortfall_survives_positive_month_end():
    result = _reference()
    assert result["projected_daily_cash_balances"][-1]["cash_balance_minor"] > 0
    assert result["minimum_projected_cash_headroom_minor"] == -102000
    assert result["projected_shortfall_minor"] == 102000
    assert result["safe_to_spend_minor"] == 0
    assert result["status"] == "shortfall"


def test_debt_principal_interest_and_minimum_are_separate():
    loan = FIXTURE["debt_terms"][0]
    assert loan["principal_minor"] + loan["interest_minor"] == loan["payment_minor"]
    assert -100000 + loan["principal_minor"] == FIXTURE["golden"]["loan_closing_balance_minor"]
    assert _reference()["required_debt_payments_minor"] == 20000


def test_savings_transfer_and_virtual_earmark_are_counted_once():
    savings = FIXTURE["savings_plan"]
    assert (
        savings["physical_transfer_minor"] + savings["remaining_virtual_earmark_minor"]
        == savings["target_minor"]
    )
    assert _reference()["planned_savings_minor"] == 15000
    assert _reference()["minimum_projected_cash_headroom_minor"] == -62000 - 25000 - 15000


def test_missing_critical_input_is_incomplete_and_unknown_stays_null():
    result = _reference()
    result["status"] = "incomplete"
    result["missing_inputs"] = FIXTURE["missing_case"]["missing_inputs"]
    for field in FIXTURE["missing_case"]["unknown_fields"]:
        result[field] = None
    result["projected_daily_cash_balances"] = [
        {**day, "cash_balance_minor": None, "cash_headroom_minor": None}
        for day in result["projected_daily_cash_balances"]
    ]
    VALIDATOR.validate(result)
    assert result["safe_to_spend_minor"] is None
    assert result["projected_shortfall_minor"] is None
    assert "card_minimum" in result["missing_inputs"]


def test_missing_cash_balance_cannot_be_zero_filled():
    result = _reference()
    result["status"] = "incomplete"
    result["missing_inputs"] = ["cash_balance"]
    for field in (
        "cash_available_minor",
        "minimum_projected_cash_headroom_minor",
        "safe_to_spend_minor",
        "projected_shortfall_minor",
    ):
        result[field] = None
    result["projected_daily_cash_balances"] = [
        {**day, "cash_balance_minor": None, "cash_headroom_minor": None}
        for day in result["projected_daily_cash_balances"]
    ]
    VALIDATOR.validate(result)
    assert result["cash_available_minor"] is None
    assert result["expected_income_minor"] == 300000


def test_scenario_is_hypothetical_and_cannot_mutate_ledger():
    before = copy.deepcopy(FIXTURE["records"])
    scenario = {
        "cash_flows": [
            {
                "id": "hyp-1",
                "date": "2026-11-04",
                "account_id": "checking",
                "currency": "USD",
                "amount_minor": -1000,
            }
        ]
    }
    request = {**FIXTURE["request"], "scenario": scenario}
    VALIDATOR.validate(request)
    simulated = _reference(scenario)
    assert simulated["hypothetical"] is True
    assert simulated["projected_shortfall_minor"] == 103000
    assert FIXTURE["records"] == before
    assert _reference()["projected_shortfall_minor"] == 102000


def test_read_reference_does_not_modify_records():
    before = copy.deepcopy(FIXTURE)
    _reference()
    assert before == FIXTURE


def test_every_output_has_source_ids_and_daily_changes_are_traced():
    result = _reference()
    assert {c["field"] for c in result["components"]} == {
        key for key in result if key.endswith("_minor")
    }
    assert all(c["source_ids"] for c in result["components"])
    assert all(set(c["source_ids"]).issubset(result["source_ids"]) for c in result["components"])
    assert "tx-rent" in result["projected_daily_cash_balances"][1]["source_ids"]


def test_currency_mismatch_is_rejected_and_eur_is_not_converted():
    assert "tx-eur-example" not in _reference()["source_ids"]
    assert "EUR records excluded from USD plan; no FX conversion." in _reference()["assumptions"]
    with pytest.raises(ValueError, match="currency mismatch"):
        _reference(
            {
                "cash_flows": [
                    {
                        "id": "hyp-eur",
                        "date": "2026-11-02",
                        "account_id": "checking",
                        "currency": "EUR",
                        "amount_minor": -1,
                    }
                ]
            }
        )


def test_dates_month_boundaries_and_leap_year_are_exact():
    assert _dates("2026-11-01", 30)[-1] == "2026-11-30"
    assert _dates("2026-12-30", 4) == ["2026-12-30", "2026-12-31", "2027-01-01", "2027-01-02"]
    assert _dates("2028-02-28", 3) == ["2028-02-28", "2028-02-29", "2028-03-01"]


@pytest.mark.parametrize(
    "change",
    [
        {"horizon_days": 0},
        {"horizon_days": 367},
        {"horizon_days": 30.5},
        {"currency": "usd"},
        {"currency": "USDX"},
        {"as_of": "2026-02-30"},
        {"extra": "forbidden"},
    ],
)
def test_invalid_requests_rejected(change):
    with pytest.raises(ValidationError):
        VALIDATOR.validate({**FIXTURE["request"], **change})


@pytest.mark.parametrize(
    "change",
    [
        {"status": "unknown"},
        {"cash_available_minor": 1.5},
        {"cash_available_minor": True},
        {"schema_version": 2},
        {"extra": "forbidden"},
    ],
)
def test_invalid_responses_rejected(change):
    with pytest.raises(ValidationError):
        VALIDATOR.validate({**_reference(), **change})


def test_merchant_text_is_inert_fixture_data():
    before = copy.deepcopy(FIXTURE["records"])
    merchant = next(r["merchant"] for r in FIXTURE["records"] if "merchant" in r)
    assert "enable finance writes" in merchant
    result = _reference()
    registry = json.loads((ROOT / "contracts/capability-registry.v2.json").read_text())
    assert all(
        prefix in registry["forbidden_capability_prefixes"]
        for prefix in ("finance.pay", "finance.transfer", "finance.purchase", "finance.bank_login")
    )
    assert result["engine_version"] == "pre00-reference-v1"
    assert "tx-malicious-merchant" not in result["source_ids"]
    assert FIXTURE["records"] == before

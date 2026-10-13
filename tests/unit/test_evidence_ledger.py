"""The evidence ledger keeps its header and only uses allowed results."""

from __future__ import annotations

import csv
from pathlib import Path

LEDGER = Path(__file__).resolve().parents[1] / "evidence" / "ledger.csv"
HEADER = [
    "req_id",
    "test_id",
    "commit",
    "device",
    "provider_model_versions",
    "date",
    "result",
    "artifact",
]
RESULTS = {"PASS", "FAIL", "SKIPPED", "NEEDS_HARDWARE", "NOT_APPLICABLE"}


def _rows() -> list[dict[str, str]]:
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_ledger_header_is_exact():
    with LEDGER.open(newline="", encoding="utf-8") as handle:
        assert next(csv.reader(handle)) == HEADER


def test_every_row_is_complete_and_uses_an_allowed_result():
    rows = _rows()
    assert rows
    for row in rows:
        assert row["result"] in RESULTS, row
        assert all(row[column] for column in HEADER), row


def test_s01_and_s02_evidence_are_recorded():
    ids = {row["req_id"] for row in _rows()}
    assert {"AR-WIN-001", "AR-WIN-002"} <= ids

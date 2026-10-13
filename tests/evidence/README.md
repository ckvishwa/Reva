# tests/evidence

`ledger.csv` is the evidence ledger (ARD-800 section 5). One row per verified requirement:
`req_id, test_id, commit, device, provider_model_versions, date, result, artifact`.

`result` is one of PASS, FAIL, SKIPPED, NEEDS_HARDWARE, NOT_APPLICABLE. A skipped or mocked test is never PASS.
`tests/unit/test_evidence_ledger.py` checks the header and the allowed result values.

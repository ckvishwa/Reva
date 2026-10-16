# C1c Android policy parity review

Reviewed the C1c delta on the C1b integration head. Android loads the packaged capability registry and rejects forbidden names, duplicate capabilities, unsupported schema keywords, and unknown capabilities. `authorize()` is pure; it binds T2 approval to proposal ID, argument hash, user and required confirmation device, rejects speech approval, and checks consent and device scopes. Rule and refusal fixtures compare with the Python implementation by semantic fields. No Android code in this slice executes restricted actions.

Finding fixed: approval argument hashes diverged from Python JSON for negative zero, exponent notation and some fixed-decimal amounts. Added five shared fixture cases to the Python generator. The Android parity test failed first on `-0.0`; after canonicalization was corrected, all eight policy test methods passed. Full Android JVM suite: 227 tests, 0 failures/skips. Python fixture tests: 4 passed. Registry contracts: 9 schemas valid. Changed Python tooling passed Ruff. The resulting ledger was reconciled with C1b rows and parses as 236 rows.

Remaining gate: CI on the exact PR head and physical Android action/voice acceptance. C1c policy tests do not demonstrate a physical confirmation UI; C2/C3 must use this policy at execution boundaries. No hardware PASS is claimed here.

# G2 software acceptance matrix — provisional

This is a software gate, separate from the ordered physical acceptance in `PHASE-C-hardware.md`. A green suite is evidence for its tested path only. Final status and exact final-commit counts belong in `PHASE-C-report.md` after C3 merges.

| # | Check | Current software evidence | Status |
|---|---|---|---|
| 1 | Talk session, interruption, cancellation | C1b voice JVM tests; C3a local-brain epoch/timeout tests; API 36 instrumented suite | PASS for simulated/software paths |
| 2 | Microphone denial and safe fallback | C1b permission-gate tests; real revocation pending | PASS for simulated/software paths |
| 3 | TTS/avatar lifecycle | C1b TTS and avatar JVM tests; physical playback pending | PASS for simulated/software paths |
| 4 | Cross-platform policy parity | C1c Python/Android fixture comparisons; contract check | PASS |
| 5 | Approved/denied app open | C2c `ApprovedApps` and phone-action JVM tests | PASS |
| 6 | Alarm, reminder, calendar, share | C2c intent/action JVM tests; actual confirmation surfaces pending hardware | PASS for constructed intents |
| 7 | Phone → gateway → Windows executor → verified response | C2a gateway tests, C2b Windows tests and C2c signed client tests; no observed full physical chain | PARTIAL |
| 8 | T2 rejected without approval on PC | C2a/Broker and C2b approval tests | PASS |
| 9 | Forged, replayed, expired, duplicate requests | C2a/C2c signed protocol and idempotency tests | PASS |
| 10 | Paired → Standalone → Offline-lite transitions | C3b `ModeControllerTest` and hosted timeout/revocation tests; paired brain delegation missing | PARTIAL |
| 11 | Sensitive-domain network egress | C3b capture seam verifies no transport call with either domain consent off; physical packet capture pending | PASS for tested software boundary |
| 12 | Clean builds and required CI lanes | C3a PR #30 eight checks green and main `38934452489` green; C3b/#31 and C3c/#32 pending | PENDING |

`PASS for simulated/software paths` is not a physical hardware pass. The C3b paired-brain failure is tracked in `tests/evidence/ledger.csv` and `docs/security/C3b-review.md`; G2 cannot close while it remains. No release tag is justified while mandatory hardware rows remain open.

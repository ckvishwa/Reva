# ARD-700 — Life Domains and Domain Kernel v2.0

**Document ID:** REVA-ARD-700 · **Version:** 2.0.5 · **Date:** 2026-10-12 · **Status:** Proposed
**New in v2.** **Decisions:** ADR-027, ADR-028, ADR-029, ADR-032, ADR-033, ADR-034.

## 1. Summary

Every life domain lives in one Rust **Domain Kernel** that runs inside the Windows Core (Python binding) and inside the Android app (Kotlin binding). Finance, Health and the rest therefore work fully on either device with no network. The Kernel stores, validates and computes. It never talks to the network, calls a model or touches the OS. Voice, AI insight and actions stay in the Core and the Android local brain, which reach domain data only through Kernel calls registered as tools.

## 2. Kernel structure

```text
kernel/
  Cargo.toml            crate reva-kernel (cdylib + lib)
  src/
    lib.rs              UniFFI exports
    store/              SQLCipher open, key handling, migrations, backup, recovery
    events/             event envelope, log, outbox, apply, tombstones, lamport clock
    domains/
      memory/ finance/ health/ coach/ career/ learn/ cyber/ personal/
    today/              cross-domain summary (read-only)
    export/ import/     CSV, JSON, OFX parsers and writers
  bindings/             generated: python/, kotlin/ (never hand-edited)
  tests/                shared conformance tests (run natively and through both bindings)
```

**Starting point:** the AuraO finance branch (`database.rs`, `migration.rs`, `migrations.rs`, `secrets.rs`, `errors.rs`; PR #8, 25/25 tests incl. real Credential Manager) generalized to every domain. Key access moves behind a `KeyProvider` trait implemented by the host (DPAPI/Credential Manager in Python host; Keystore in Kotlin host).

### 2.1 API shape (UniFFI)

```text
open_domain(domain, key_provider, data_dir) -> DomainHandle | DomainError
DomainHandle.command(kind, payload_json) -> CommitResult{event_id, aggregate_id, version}
DomainHandle.query(name, params_json) -> QueryResult{rows_json, source_ids}
DomainHandle.export(format) -> bytes
DomainHandle.import_data(format, bytes, options_json) -> ImportReport{accepted, rejected[]}   (see 2.3)
DomainHandle.sync_export(peer, limit) -> SyncBatch          (signed events after the peer's cursor)
DomainHandle.sync_apply(peer, batch) -> ApplyReport{applied, duplicates, conflicts[]}
DomainHandle.sync_ack(peer, cursor)
DomainHandle.set_signer / register_peer / revoke_peer / list_peers   (device keys and trusted peers)
today(handles) -> TodaySummary
```

Errors: `Locked` (no key), `WrongKey`, `Corrupt`, `MigrationFailed`, `Validation{field, reason}`, `Conflict`, `NotFound`, `Deleted`, `Internal`, `Rejected{reason}` (sync refused).

### 2.2 Write model

Every command produces an event appended to the domain log and outbox inside one transaction, then updates projection tables. Projections can be dropped and rebuilt from the log (AR-DOM-004). Deletes are tombstone events. Lamport clocks per device order concurrent events; ties break by `origin_device_id`.

### 2.3 Implementation notes (2.0.5)

What the first three implementations (FIN-1 Kernel and Core, FIN-2 Windows Finance page, AND-1 Android app, SYNC-1a sync core) settled. Where this differs from §2.1 above, this section is the current truth.

**API names and errors**
- `import` is `import_data(format, data, options_json)`: `import` is a Python keyword, and an import needs options (`account_id`, column `mapping`, `dry_run`). A dry run runs the real import inside a transaction that is rolled back, so its report equals the real run's and commits nothing.
- Error variants carry `detail` (not `message`, which collides with Kotlin's `Throwable.message`). `Rejected{reason}` was added for sync refusals; the Core maps it to HTTP 403 `sync_rejected`.
- Sync entry points: `set_signer(DeviceSigner)`, `device_fingerprint()`, `register_peer(device_id, public_key, label, scopes)`, `revoke_peer`, `list_peers`, `sync_export(peer, limit)`, `sync_ack(peer, cursor)`, `sync_apply(peer, batch)`. The older unauthenticated `pending_events` / `ack` / `apply_events` exist only as Rust-visible test helpers and are **not** in the Python or Kotlin bindings, so a host cannot apply an event that skipped the peer checks.

**Events**
- Payloads carry the full resulting state of the aggregate. Projections rebuild by replaying the log in `(lamport, origin_device_id, seq)` order. A tombstoned aggregate is never projected again, whatever the clocks say (AR-DATA-011, AC-008, AC-018).
- `signature` has two forms. In the local log it is an HMAC-SHA256 tag under a key derived from the domain key (tamper check on this device). On export it becomes `es256:` + hex of a DER ECDSA P-256/SHA-256 signature by the device key over the canonical event bytes without `signature`. The Kernel holds no private key: the host implements `DeviceSigner` over Credential Manager / Android Keystore. P-256 was chosen because Android Keystore supports Ed25519 only from API 33 and minSdk is 31. Public keys travel as X.509 SubjectPublicKeyInfo DER; the device fingerprint is the SHA-256 of that DER.
- A received batch is rejected as a whole if any event is unsigned, mis-signed, from an unknown / revoked / out-of-scope device, or names this device as origin. Limits: 500 events, 8 MB, Lamport values up to 2^53-1. Cursors are per peer, advance only on `sync_ack` and only forward; an event is never sent back to its origin.
- Concurrent edits to the same version of an amount (`transaction`, `bill`, `budget`: `amount_minor`; `account`: `opening_balance_minor`) are recorded as conflicts on both devices and resolved with `conflict.resolve`, which is itself an event.

**Finance**
- `bill` and `recurring` are one aggregate: a bill has a `recurrence` and a `kind` (`bill`, `subscription`, `income`). `bill.mark_paid` records payment only; it can also record the matching ledger transaction.
- Money is integer minor units plus an ISO 4217 code; parsing refuses to round. Budgets and reports are per currency; there is no conversion.
- Import limits: 8 MB and 50,000 rows per file for CSV, OFX and the Kernel JSON format. Export CSV prefixes any text cell that starts with `=`, `+`, `-`, `@`, tab or CR with an apostrophe. The JSON export is unencrypted; both apps say so before sharing.
- Core routes: `/v1/domains/*` and `/v1/today`, all behind the local bearer token. `GET/PATCH /v1/domains/{domain}/privacy` stores `sync` and `hosted_model_access` per domain in the Core data directory (defaults as §4). The sync transport must read the `sync` switch on send and receive; that wiring comes with the pairing gateway.

**Keys and files**
- Windows: one 32-byte key per domain in Credential Manager under `reva.domain.<domain>`. Only that prefix is ever read or written; the legacy `com.aura.assistant.finance` entry is never touched. A key is never replaced.
- Android: the Kernel creates the key; the host wraps it with an Android Keystore AES-256-GCM key (alias `reva.domain.<domain>`, StrongBox when available) and stores IV(12) + key(32) + tag(16) = 60 bytes in `noBackupFilesDir/keys/<domain>.key`. A missing Keystore key or a blob that fails to authenticate is an error, never "no key". Domain files live in `noBackupFilesDir/domains`; the backup and data-extraction rules exclude them.
- `REVA_DOMAIN_KEYSTORE=memory` (throw-away in-memory keys for UI tests) is refused in a packaged build and for any data directory outside the OS temp directory, checked both in `load_settings` and where the key provider is built.
- Kernel calls run on `Dispatchers.IO` on Android and off the event loop in the Core (AR-DOM-015).

**Today**
- `today(handles, as_of)` is read-only. Finance supplies `budget_status` (this month) and `upcoming_bills` (next 7 days); `as_of` is a parameter so tests never depend on the clock.

## 3. Domain catalog

| Domain | Main records | Key queries | Sources | Sensitivity | Tools (tier) | Hard limits |
|---|---|---|---|---|---|---|
| Memory | fact, preference, candidate, citation, embedding | recall(query), list(type) | typed/spoken with approval | High | `memory.remember` (T2), `memory.recall` (T0) | no silent saves; deleted never retrievable |
| Finance | account, transaction, category, budget, bill, recurring, networth_snapshot | spend_by_category(period), budget_status, upcoming_bills, cashflow | manual, voice, CSV, OFX | High | `finance.add_transaction` (T2), `finance.summary` (T0), `finance.budget_status` (T0), `finance.bill_reminder` (T2) | no money movement, purchases, or bank credentials |
| Health | workout, steps_day, sleep_session, heart_rate_sample, weight, meal, medication_schedule, medication_taken | weekly_summary, trends(metric), adherence | manual, file import, Health Connect (Android, read-only) | High | `health.log_workout` (T2), `health.log_meal` (T2), `health.weekly` (T0), `health.med_reminder` (T2) | no diagnosis, dosing or treatment |
| Coach | goal, milestone, habit, habit_check, checkin, weekly_review | habits_due(today), streaks, goal_progress | manual, voice | Medium | `coach.checkin` (T2), `coach.progress` (T0) | — |
| Career | application, company, contact, interview, resume_version | pipeline, upcoming_interviews | manual, file attach | Medium | `career.add_application` (T2), `career.pipeline` (T0) | never sends messages |
| Learn | course, certification, deck, card, review, study_session | due_cards, streak, cert_progress | manual, content import | Low | `learn.quiz` (T0), `learn.log_session` (T2) | — |
| Cyber | lab, note, cve_note, asset | search(notes), assets | manual | Medium | `cyber.add_note` (T2), `cyber.find` (T0) | no scanning or exploit tools |
| Personal | journal_entry, person, reminder, event | reminders_due, on_this_day, people_search | manual, voice | High (journal) | `personal.reminder.create` (T2), `personal.journal.add` (T2) | journal local-only by default |

**Today** reads from every enabled domain: budget left this month, bills due in 7 days, workouts and sleep last night, habits due, reminders, cards due, interviews this week, journal prompt.

## 4. Privacy defaults

| Domain | Sync default | Hosted-model access default |
|---|---|---|
| Memory | on | off |
| Finance | on | off |
| Health | on | off |
| Coach | on | on |
| Career | on | on |
| Learn | on | on |
| Cyber | on | on |
| Personal | journal off, rest on | off |

The planner receives only the fields a tool returns, never whole files. Hosted-model calls go through the Core consent filter (AR-CORE-010) or the Android equivalent.

## 5. Health and Finance safety

- **Health:** answers summarize the user's own data; no diagnosis, no dose or treatment suggestions; an urgent-symptom phrase list (chest pain, trouble breathing, stroke signs, overdose, self-harm wording) triggers a fixed message pointing to professional or emergency help. Health Connect is read-only with per-type consent and a rationale screen; the Play health-apps declaration is a release task.
- **Finance:** amounts parsed from speech are always shown for confirmation before save; currency explicit; summaries list the records used. No capability can move money; the registry absence test enforces it.

## 6. Requirements

| ID | Stage | Requirement | Verification |
|---|---|---|---|
| AR-DOM-001 | R1 | Kernel builds for x86_64-pc-windows-msvc, aarch64-linux-android, x86_64-linux-android; one conformance suite passes natively and through Python and Kotlin bindings | Cross-binding CI |
| AR-DOM-002 | R1 | Each domain file encrypted; wrong key, missing key, corrupt file, fresh install → typed errors, no data loss | Recovery suite per domain |
| AR-DOM-003 | R1 | Migrations transactional with backup before destructive steps | Copied-DB upgrade/rollback |
| AR-DOM-004 | R1 | Every write is an event; rebuilt projections equal live state | Rebuild-and-compare |
| AR-DOM-005 | R1 | Memory passes harvested benchmark ≥ 9/10; deleted items never retrieved (FTS or vectors) | Benchmark + deletion regression |
| AR-DOM-006 | R2 | Domain tools take tiers from the registry; no money-movement capability exists | Registry absence + tamper |
| AR-DOM-007 | R2 | Health answers never phrase diagnosis or dose; urgent phrases routed | Health safety eval |
| AR-DOM-008 | R2 | Duplicate events are no-ops; Finance amount conflicts shown to user | Replay/conflict fixtures |
| AR-DOM-009 | R3 | With hosted consent off, no domain content in outbound requests | Network capture |
| AR-DOM-010 | R3 | Per-domain CSV/JSON export round-trips into a fresh install | Round-trip |
| AR-DOM-011 | R4 | Query p95 ≤ 100 ms on 10,000 records on reference phone (target) | Benchmark |
| AR-DOM-012 | R3 | Imports report every rejected row with reason; nothing dropped silently | Malformed-file fixtures |
| AR-DOM-013 | R3 | Today summary computed only from enabled domains | Toggle tests |
| AR-DOM-014 | R1 | Kernel never performs network I/O | Build-time dependency check + sandbox test |
| AR-DOM-015 | R2 | Kernel calls never run on UI threads (host contract) | StrictMode / UI-thread assertion |

## 7. Build order

Memory + Finance core (R1, Windows) → same on Android (R2) → Finance full → Health → Coach → Personal → Learn → Career → Cyber (R3, both). Each domain ships with its schema, migrations, commands, queries, tools, export/import, privacy defaults and conformance tests before the next starts.

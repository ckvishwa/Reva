# ARD-700 — Life Domains and Domain Kernel v2.0

**Document ID:** REVA-ARD-700 · **Version:** 2.0.1 · **Date:** 2026-10-11 · **Status:** Proposed
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
DomainHandle.import(format, bytes) -> ImportReport{accepted, rejected[]}
DomainHandle.pending_events(limit) -> EventBatch
DomainHandle.apply_events(batch) -> ApplyReport{applied, duplicates, conflicts[]}
DomainHandle.ack(cursor)
today(handles) -> TodaySummary
```

Errors: `Locked` (no key), `WrongKey`, `Corrupt`, `MigrationFailed`, `Validation{field, reason}`, `Conflict`, `NotFound`, `Deleted`.

### 2.2 Write model

Every command produces an event appended to the domain log and outbox inside one transaction, then updates projection tables. Projections can be dropped and rebuilt from the log (AR-DOM-004). Deletes are tombstone events. Lamport clocks per device order concurrent events; ties break by `origin_device_id`.

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

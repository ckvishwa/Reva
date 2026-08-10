# Storage Design

SQLite is the authoritative local store (PRD §11). No ORM: explicit SQL
migrations under `reva_core/storage/migrations_sql/`, applied by
`reva_core/storage/migrations.py`, tracked in a `schema_migrations`
table.

## Connection configuration

- `PRAGMA journal_mode=WAL` — set on every connection open
  (`reva_core/storage/connection.py`).
- `PRAGMA foreign_keys=ON` — set on every connection open (SQLite
  defaults this OFF per-connection regardless of file history).
- `isolation_level=None` (autocommit) — the codebase controls
  transaction boundaries explicitly via `storage/connection.py::transaction()`
  (a `BEGIN`/`COMMIT`/`ROLLBACK` context manager) rather than relying on
  the sqlite3 module's implicit transaction guessing. Used whenever more
  than one write must succeed or fail together (e.g. a memory row and
  its audit events).
- `check_same_thread=False` — FastAPI/Starlette may hand request
  handling to a thread different from the one that opened the
  connection (confirmed via Starlette's `TestClient`, which always
  does). Python's sqlite3 default thread-affinity check would reject
  that; disabling it is the standard FastAPI+sqlite3 pattern. Real
  concurrency safety comes from SQLite's own WAL-mode locking, not this
  flag, and REVA Core's request pattern is sequential in Phase 1A
  (single user, no worker pool).

## Migration 0001 — initial schema

All nine planned tables are created in the first migration, locking the
schema shape during Phase 0 even though most tables had no application
writer yet at that point:

| Table | Writer | Notes |
|---|---|---|
| `application_metadata` | **yes** — `storage/repositories/device_repository.py` | stores the stable `primary_device_id` key so it survives restart |
| `devices` | **yes** — `storage/repositories/device_repository.py` | one row per device; Phase 1A creates exactly one ("Local Windows Device") on first startup; real pairing is PLANNED |
| `conversations` | **yes** — `storage/repositories/conversation_repository.py` | one row per typed-message request; insert-only, no read path yet |
| `messages` | **yes** — `storage/repositories/message_repository.py` | insert-only, same reasoning |
| `memories` | **yes** — `storage/repositories/memory_repository.py` | insert + keyword query; `tags` stored as a delimited TEXT column, not a join table, until real usage patterns justify one |
| `reminders` | none | Phase 3 |
| `permissions` | none | Phase 3 |
| `audit_events` | **yes** — `storage/repositories/audit_repository.py` | 6 Phase 1A audit actions persisted |
| `sync_events` | none | Phase 5 |

All entity IDs are UUIDv7 `TEXT`. All timestamps are UTC ISO-8601
`TEXT`. Foreign keys reference `devices(id)`, `conversations(id)`, and
`messages(id)` where an `origin_device_id` / `source_*_id` exists.

## Idempotent bootstrap

`reva_core/storage/bootstrap.py::initialize_database(db_path)`:

1. Opens (or creates) the SQLite file with the pragmas above.
2. Ensures `schema_migrations` exists.
3. Applies any migration whose version is not yet recorded.
4. Returns `(connection, schema_version)`.

Calling it again against the same file — the "restart" case — applies
zero migrations (all versions already recorded) and returns the same
schema version. Covered by
`tests/integration/test_storage_bootstrap.py::test_restart_is_idempotent`.

## Memory query (IMPLEMENTED, keyword-only)

`MemoryRepository.query(text, limit)` matches
`lower(content) LIKE '%normalized_text%'` against `active` memories,
ordered `updated_at DESC, ROWID DESC`. `ROWID` (SQLite's implicit,
monotonically-increasing-per-insert row identifier) is used *only* as
a same-instant tiebreaker for deterministic ordering — never returned
to a caller, never used as entity identity (that stays UUIDv7 per
ADR-013). It exists because two memories created within the same
timestamp resolution (observed on Windows during testing) would
otherwise sort arbitrarily.

`%`/`_` characters in query text are not escaped as SQL `LIKE`
wildcards — harmless for injection (the query is still fully
parameterized) but means a query containing `%` may over-match;
acceptable for Phase 1A's keyword search, revisit if it's ever
user-confusing in practice.

## Semantic retrieval (PLANNED)

A future local vector index is **derived, rebuildable data** — it can
always be regenerated from `memories.content`. SQLite remains the
single source of truth for memory content and source metadata; the
vector index never becomes authoritative, and no vector/embedding
column exists on `memories` yet.

## Retention, deletion, export

Deletion/edit/export endpoints are not implemented in Phase 1A (out of
scope — see `docs/plans/phase-1a-typed-memory.md`).
`memories.retention_state` exists in the schema specifically so a
future soft-deletion feature does not need its own schema migration.

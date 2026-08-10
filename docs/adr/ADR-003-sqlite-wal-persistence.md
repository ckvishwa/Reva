# ADR-003: SQLite + WAL for Local Persistence

**Status:** Accepted

## Context

REVA is local-first and single-user (PRD §3-4). It needs durable,
transactional local storage with zero operational overhead (no server
process to run/manage) and Windows-file-friendly behavior.

## Decision

SQLite is the authoritative durable store, opened in WAL (write-ahead
log) journal mode with foreign keys enforced on every connection.

## Alternatives considered

- **Postgres/Supabase** — explicitly excluded by the product
  constraints (local-first, no cloud database); also operational
  overhead (a running server) that a single-user desktop app does not
  need.
- **A key-value embedded store (e.g. LMDB, RocksDB)** — would work for
  simple lookups but loses SQL's relational integrity (foreign keys,
  joins for future retrieval queries) for no benefit at this scale.
- **Plain DELETE-mode SQLite (no WAL)** — simpler, but WAL gives better
  concurrent-read behavior (a future desktop UI reading while Core
  writes) and is the documented recommendation for this exact
  read-while-write pattern.

## Consequences

- One `.db` file (plus `-wal`/`-shm` siblings) per install; git-ignored,
  never committed, and the natural unit for export/backup.
- No ORM: explicit SQL and migrations, per the "no giant ORM" product
  constraint — keeps the query surface auditable.
- 10,000-record keyword/semantic search performance targets (PRD §13)
  are achievable with SQLite plus appropriate indexes; validated
  per-feature as those features land, not assumed now.

## Security implications

The SQLite file is the single point of data-at-rest exposure — theft of
the file is a named threat (`docs/security/threat-model.md`). Windows
filesystem ACLs are the Phase 0 mitigation; database-level encryption
is not implemented and would need its own ADR if adopted.

# ADR-004: Repository/Service Persistence Separation

**Status:** Accepted

## Context

Multiple future modules (`memory/`, `policy/`, `tools/`, `sync/`) will
need to read/write SQLite, but none of them should contain SQL — that
ownership belongs to `storage/` per the required module boundaries.

## Decision

Persistence is implemented as one repository class per table under
`reva_core/storage/repositories/`, each taking an open `sqlite3.Connection`
and exposing typed methods (`insert`, `list_recent`, etc.) that accept
and return `shared/contracts/` Pydantic models, never raw rows, to
callers outside `storage/`.

Domain modules (e.g. a future `memory/` service) call a repository;
they never execute SQL themselves.

## Alternatives considered

- **A full ORM (SQLAlchemy)** — explicitly rejected by the product
  constraints ("do not build a giant ORM"); also adds a large
  dependency and an abstraction layer this project's query complexity
  does not need yet.
- **Active Record-style models that know how to save themselves** —
  would blur the storage/domain boundary the module-boundaries
  document requires; a `Memory` contract must stay ignorant of SQL.
- **Raw SQL scattered across calling modules** — fastest to write,
  fails the "storage owns SQL" boundary immediately and makes schema
  changes require hunting across the codebase.

## Consequences

- Adding a table means adding one repository module with a small,
  reviewable surface area.
- Only one repository exists in Phase 0 (`AuditRepository`) — proof of
  the pattern, not a framework built ahead of need.
- Repository methods are the natural place for future retention/export/
  deletion logic per-table, keeping that logic out of domain modules.

## Security implications

Centralizing SQL in repositories means parameterized queries are
enforced in one place per table, reducing injection surface compared
to ad hoc SQL construction elsewhere.

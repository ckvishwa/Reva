# Contributing

REVA is single-user, private, personal-intelligence software under
active foundation work. This file covers the mechanics; read
`docs/architecture/architecture-rules.md` (short) and
`docs/architecture/module-boundaries.md` (full) before writing code
that crosses a module boundary.

## Workflow

1. Read `docs/product/reva-v1-prd.md` for product intent before adding
   any feature — do not invent requirements it does not state.
2. Check `docs/architecture/data-flow.md` for what's IMPLEMENTED vs
   PLANNED before assuming a module exists.
3. Write or update tests alongside code — see
   `docs/testing/test-strategy.md` for what belongs in which category.
4. Run the full local check before proposing a change:

   ```powershell
   ruff format --check .
   ruff check .
   mypy reva_core
   pytest --cov=reva_core
   ```

## Commit discipline

- One logical change per commit.
- New persisted fields/tables require a new migration file under
  `reva_core/storage/migrations_sql/` — never edit an already-applied
  migration.
- New ADRs (`docs/adr/`) are required for architecture-level decisions,
  not for routine feature work within existing boundaries.

## Scope discipline

Before adding a new top-level module or dependency, ask: does the PRD
or an approved ADR require this *now*? If not, it belongs in
`docs/architecture/future-expansion-policy.md`'s "later" list, not in
this PR. See that document for the full future-expansion checklist
(user value, phase, permissions, audit, rollback, etc.) required before
implementing any new integration or capability.

## Security-sensitive changes

Any change touching `config/`, `api/`, `audit/`, secret handling, or
anything that will eventually execute a tool must be read against
`docs/security/threat-model.md` and
`docs/security/security-invariants.md` — update both if the change
affects either.

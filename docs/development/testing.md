# Testing (Windows)

Run all commands from `D:\Projects\Reva` with the virtual environment
activated (see `docs/development/setup.md`).

## Run everything

```powershell
pytest
```

## Run one category

```powershell
pytest tests/unit
pytest tests/integration
pytest tests/contract
pytest tests/security
pytest tests/e2e
```

`tests/e2e/` holds exactly one test as of Phase 1A — the typed-memory
vertical slice (bootstrap → authenticate → save → audit → restart →
authenticate → query → source-attributed result). See
`docs/testing/test-strategy.md` for why it's deliberately just one.

## Coverage

```powershell
pytest --cov=reva_core --cov-report=term-missing --cov-report=html
```

HTML report lands in `htmlcov/index.html`.

## Format

```powershell
ruff format .
ruff format --check .   # CI mode: fail if anything would change
```

## Lint

```powershell
ruff check .
ruff check --fix .      # apply safe autofixes
```

## Type check

```powershell
mypy reva_core
```

## Migration / bootstrap manual check

```powershell
python scripts/verify_bootstrap.py
```

## Pre-commit (optional, runs the above automatically on commit)

```powershell
pre-commit install
pre-commit run --all-files
```

## Troubleshooting

- **`pytest` collects 0 tests** — confirm you're in the repo root and
  the venv is active; `pyproject.toml`'s `[tool.pytest.ini_options]`
  sets `testpaths = ["tests"]`.
- **A security test fails after an env var change** — some tests read
  `REVA_*` environment variables; run
  `Get-ChildItem Env:REVA_*` to check for a stray value left over from
  a previous manual run, and clear it with
  `Remove-Item Env:REVA_API_HOST` (adjust name as needed).
- **mypy complains about `uvicorn`** — expected if type stubs are
  missing; `pyproject.toml` already ignores missing imports for
  `uvicorn.*`.

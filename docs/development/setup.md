# Setup (Windows)

## Prerequisites

- Python 3.12+ on PATH (`python --version`).
- Git.

## Clone / working directory

This repository already lives at `D:\Projects\Reva`. All commands below
assume that as the current directory in PowerShell.

## Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If activation is blocked by execution policy:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

## Configure environment

```powershell
Copy-Item .env.example .env
```

Edit `.env` only if you need non-default values. Defaults are safe for
local development — no cloud credential is required for Phase 0.

## Run REVA Core

```powershell
python -m reva_core
```

Expected output: a healthy-startup log line, then a clean shutdown, exit
code `0`. This is a smoke test, not a long-running server — see
`docs/architecture/runtime-model.md`.

To run the loopback API server (blocks until Ctrl+C):

```powershell
python -m reva_core --serve
```

Then, in a second terminal:

```powershell
curl.exe http://127.0.0.1:8756/health
curl.exe http://127.0.0.1:8756/version
```

`/health` and `/version` need no authentication. Every `/v1/*` route
does — see the next section.

## Call the authenticated `/v1/*` API

The local auth token is generated on first startup and stored at
`<data_dir>/local_auth_token` (default dev `data_dir` is `./data`, so
`./data/local_auth_token`). Read it and use it as a Bearer token:

```powershell
$token = Get-Content .\data\local_auth_token -Raw
$headers = @{ Authorization = "Bearer $($token.Trim())" }

# Save an explicit memory
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8756/v1/memories `
    -Headers $headers -ContentType "application/json" `
    -Body '{"content": "REVA V1 uses push-to-talk, not always-on listening."}'

# Query it back
Invoke-RestMethod -Uri "http://127.0.0.1:8756/v1/memories?q=push-to-talk" -Headers $headers

# Typed message with the remember: shorthand
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8756/v1/messages `
    -Headers $headers -ContentType "application/json" `
    -Body '{"content": "remember: this also works from the typed-message endpoint"}'

# Recent audit trail
Invoke-RestMethod -Uri http://127.0.0.1:8756/v1/audit-events -Headers $headers
```

Never commit or paste `local_auth_token`'s contents anywhere — it is
git-ignored and is the only credential this API accepts.

## Troubleshooting

- **`ModuleNotFoundError: reva_core`** — you installed without `-e`, or
  are not in the activated venv. Re-run `pip install -e ".[dev]"`.
- **`ConfigurationError: REVA_API_HOST must be a loopback address`** —
  check `.env` / `REVA_API_HOST` environment variable; only
  `127.0.0.1`, `::1`, or `localhost` are accepted, by design.
- **Port already in use with `--serve`** — set `REVA_API_PORT` in
  `.env` to a free port.
- **A stray `data/reva.db` from a previous run** — safe to delete; it
  is git-ignored and will be recreated with fresh migrations on next
  startup.
- **`401 Unauthorized` from a `/v1/*` call** — check the header is
  exactly `Authorization: Bearer <token>` (note the `Bearer ` prefix)
  and that the token matches the current contents of
  `data/local_auth_token` for *this* `data_dir`. Deleting that file and
  restarting Core generates a new token.
- **Deleted `data/reva.db` but kept `data/local_auth_token` (or vice
  versa)** — harmless; they're independent. A fresh database still
  authenticates with whatever token file is present, and a fresh token
  still authenticates against whatever database is present.

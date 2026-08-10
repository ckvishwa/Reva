# Threat Model

Scope: REVA V1 as a single-user, local-first Windows application with a
future Android companion. This document covers the threats named in
the Phase 0 mandate; it will grow as each phase adds real attack
surface (voice capture, tool execution, sync transport, etc.).

For each threat: Asset, Attacker, Attack path, Impact, Mitigation,
Remaining risk.

## 1. Malicious local process

- **Asset:** REVA Core's loopback API, SQLite database.
- **Attacker:** another process running as the same or a different
  local user on the machine.
- **Attack path:** connects to `127.0.0.1:<port>` and calls REVA's API,
  or opens the SQLite file directly, or reads the local auth token file.
- **Impact:** unauthorized read/write of REVA data, forged requests.
- **Mitigation:** loopback-only binding (ADR-007) limits *network*
  reach to the same machine. As of Phase 1A, every domain route also
  requires `Authorization: Bearer <token>` (`reva_core/api/auth.py`),
  checked with a constant-time comparison. Windows file ACLs restrict
  both the SQLite file and the token file to the owning user.
- **Remaining risk:** the token file itself is a plaintext file
  (interim implementation, see `security-invariants.md`'s "Local
  authentication model" section) — a process running as the *same*
  Windows user can read it, same as it could already read `reva.db`
  directly. This threat is about a *different* local user or a
  sandboxed/lower-trust process; same-user protection is bounded by
  Windows account security, same as threat #2. DPAPI-backed storage
  (PLANNED) would additionally protect against same-user-but-different-
  process-integrity-level scenarios.

## 2. Stolen machine/session

- **Asset:** entire local SQLite database, any cached secrets.
- **Attacker:** someone with physical or remote-desktop access to an
  unlocked/compromised Windows session.
- **Attack path:** reads `reva.db` directly, or drives the desktop UI
  as the logged-in user.
- **Impact:** full disclosure of local memory, conversations, reminders.
- **Mitigation:** Windows account/session security is the primary
  control (outside REVA's scope); REVA does not weaken it. Secrets use
  `SecretStr` so they never render in logs even if a log file is
  exfiltrated separately.
- **Remaining risk:** no database-level encryption at rest in Phase 0;
  full disclosure follows from a compromised session, as with any
  local-first app with an unencrypted local store.

## 3. Compromised future Android device

- **Asset:** synced subset of REVA data on Android; pairing credential.
- **Attacker:** malware or a thief with the unlocked phone.
- **Attack path:** reads Android's local cache, or uses a stolen
  pairing token to impersonate the device to Core.
- **Impact:** disclosure of synced data; potential forged sync events.
- **Mitigation:** PLANNED — encrypted local cache (ADR-010),
  authenticated transport (ADR-011), user-initiated unpair (PRD §9).
- **Remaining risk:** not implemented in Phase 0; no Android code
  exists yet to assess beyond this plan.

## 4. Stolen pairing token

- **Asset:** device pairing credential.
- **Attacker:** anyone who intercepts or extracts the token.
- **Attack path:** replays the token to register as a trusted device.
- **Impact:** unauthorized device gains sync access.
- **Mitigation:** PLANNED — `pairing_token` is already in the
  redaction key list (`shared/redaction.py`) so it can never appear in
  logs once pairing exists; per-device credentials and explicit
  two-device approval are required by PRD §9.
- **Remaining risk:** pairing is not implemented; token lifecycle
  (rotation, expiry, revocation) is a Phase 5 design task.

## 5. Exposed localhost Core

- **Asset:** REVA Core's API.
- **Attacker:** a network-adjacent attacker, or misconfiguration that
  binds a non-loopback interface.
- **Attack path:** a future config change or bug binds `0.0.0.0`,
  making Core reachable from the LAN.
- **Impact:** full remote access to whatever the API exposes.
- **Mitigation:** `load_settings()` raises `ConfigurationError` for any
  non-loopback `api_host`, enforced by
  `tests/security/test_loopback_enforcement.py` in CI.
- **Remaining risk:** low for Phase 0 (nothing behind the API); the
  control must be re-verified as routes are added, not assumed to
  scale automatically with feature growth.

## 6. Unauthorized local requests

- **Asset:** every `/v1/*` domain route (typed messages, memory
  create/query, audit event read).
- **Attacker:** another local application or script calling REVA's API
  without the user's intent.
- **Attack path:** direct HTTP call to a domain endpoint.
- **Impact:** actions taken or data disclosed without user awareness.
- **Mitigation:** **IMPLEMENTED** — every `/v1/*` route requires
  `Authorization: Bearer <token>` (`reva_core/api/auth.py`); a
  missing/invalid token returns a generic 401 and is audited. `/health`
  and `/version` remain open since they disclose no user data.
- **Remaining risk:** the token has no expiry or rotation in Phase 1A;
  any process able to read the token file (see threat #1) has
  standing, unlimited access until the file is deleted or the machine
  reconfigured. Token rotation/expiry is a candidate hardening item,
  not required for Phase 1A's scope.

## 7. Prompt injection attempting tool execution

- **Asset:** the allowlisted tool surface, user's trust in REVA's
  actions.
- **Attacker:** malicious content in a conversation, retrieved memory,
  or (future) external data source that tries to make an LLM response
  request an unapproved or disguised action.
- **Attack path:** injected text instructs the model to "open this URL
  and also run this command" or similar.
- **Impact:** unwanted tool execution, data exfiltration via a
  drafted/opened resource.
- **Mitigation:** allowlisted, narrowly-scoped tools only (ADR-008); no
  arbitrary command execution exists to escalate to (ADR-012); every
  tool call requires policy approval and produces an audit event
  (PLANNED, Phase 3).
- **Remaining risk:** policy/tools are not implemented yet, so this is
  a design commitment being tracked, not a tested control today.

## 8. Path traversal

- **Asset:** local filesystem, "open file/folder" tool (PLANNED).
- **Attacker:** injected or malformed path input.
- **Attack path:** a path like `..\..\Windows\System32\...` reaches a
  future file-opening tool.
- **Impact:** access outside an intended allowlisted directory.
- **Mitigation:** PLANNED — tool implementations must resolve and
  validate paths against an explicit allowlist before acting; no such
  tool exists in Phase 0 to be vulnerable yet.
- **Remaining risk:** to be closed by the Phase 3 tool implementation
  and its own tests, not by this document alone.

## 9. Arbitrary command execution

- **Asset:** the host OS.
- **Attacker:** any input source that reaches a hypothetical
  shell/eval/exec call.
- **Attack path:** N/A by design — see ADR-012.
- **Impact:** full host compromise, were it to exist.
- **Mitigation:** architectural exclusion (ADR-012); no such code path
  exists anywhere in this codebase.
- **Remaining risk:** none currently; must be re-checked in every
  future code review as a hard blocker, not a one-time fix.

## 10. Secret leakage

- **Asset:** API keys, tokens, passwords, pairing secrets.
- **Attacker:** anyone with read access to logs, audit events, or
  committed source.
- **Attack path:** a secret is passed as log `extra`, ends up in an
  audit event's metadata, or is committed in `.env`.
- **Impact:** credential compromise, potential downstream account
  takeover on a provider.
- **Mitigation:** `shared/redaction.py` key list enforced in
  `shared/logging.py` (log lines) and `audit/events.py` (construction
  rejects, does not just mask); `SecretStr` on config fields;
  `.env.example` contains placeholders only; `.env` is git-ignored.
- **Remaining risk:** redaction is key-name-based — a secret placed
  under an unlisted key name would not be caught. Mitigated by "do not
  indiscriminately log raw request bodies" as a coding rule, not fully
  closed by tooling.

## 11. SQLite theft

- **Asset:** `reva.db` and its `-wal`/`-shm` files.
- **Attacker:** anyone who copies the file off the machine (via
  physical access, malware, or backup misconfiguration).
- **Attack path:** direct file copy; SQLite requires no credential to
  open.
- **Impact:** full disclosure of all durable local data.
- **Mitigation:** Windows file ACLs restrict access to the owning user;
  the file is git-ignored so it never leaves via source control.
- **Remaining risk:** no application-level encryption at rest in
  Phase 0. See ADR-003's security implications — this is an accepted
  Phase 0 gap, not an oversight.

## 12. Replay attacks

- **Asset:** future authenticated API/sync requests.
- **Attacker:** someone who captured a prior valid request.
- **Attack path:** resends a captured request/token.
- **Impact:** unauthorized repeated action.
- **Mitigation:** PLANNED — local authentication (Phase 1) and sync
  transport (Phase 5) must use tokens/requests that are not naively
  replayable (e.g. short-lived tokens, nonces, or TLS session binding).
- **Remaining risk:** not implemented; no authenticated request exists
  yet to replay.

## 13. Sync conflicts

- **Asset:** memory/conversation/reminder integrity across devices.
- **Attacker:** not adversarial — this is a correctness/data-integrity
  concern, listed here because a mishandled conflict can look like or
  enable data loss.
- **Attack path:** two devices edit the same memory offline, then both
  sync.
- **Impact:** silent data loss if one write clobbers the other.
- **Mitigation:** PLANNED — PRD §8.7 and acceptance test #11 require
  conflicting edits to be preserved and surfaced, never silently
  overwritten; `SyncEvent.entity_version` exists in the contract now to
  support this.
- **Remaining risk:** reconciliation logic itself is unimplemented
  (Phase 5).

## 14. Malicious URLs

- **Asset:** the user, via a future "open URL" tool.
- **Attacker:** injected or attacker-supplied URL content.
- **Attack path:** REVA is asked (or tricked via prompt injection) to
  open a phishing or malware-hosting URL.
- **Impact:** the user's browser opens attacker-controlled content.
- **Mitigation:** PLANNED — "open URL" requires confirmation per PRD
  §8.5's tool policy table; policy approval is a human-in-the-loop
  control, not automatic.
- **Remaining risk:** does not protect against a user approving a
  well-disguised malicious URL — same residual risk as any browser.

## 15. Dependency compromise

- **Asset:** the Python environment REVA Core runs in.
- **Attacker:** a compromised or typosquatted PyPI package.
- **Attack path:** a malicious update to a direct or transitive
  dependency executes code at install or import time.
- **Impact:** full local compromise.
- **Mitigation:** deliberately small dependency set (pydantic,
  pydantic-settings, fastapi, uvicorn, plus dev-only tooling); version
  ranges pinned in `pyproject.toml`; no dependency was added for
  functionality REVA could implement itself in a few lines (e.g.
  UUIDv7, ADR-013).
- **Remaining risk:** no automated dependency vulnerability scanning is
  configured in Phase 0 CI; worth adding (e.g. `pip-audit`) as a
  low-cost follow-up, not blocking Phase 0 exit.

## 16. Log injection

- **Asset:** log integrity/readability.
- **Attacker:** any input source whose content ends up in a log
  message or metadata field.
- **Attack path:** a value containing newlines or control characters is
  logged, forging what looks like a separate log line.
- **Impact:** confused or spoofed log entries, harder incident
  response.
- **Mitigation:** structured JSON logging (`shared/logging.py`) emits
  one JSON object per line via `json.dumps`, which escapes embedded
  newlines/control characters inside string values rather than letting
  them break line framing.
- **Remaining risk:** JSON values containing attacker-controlled text
  are still stored verbatim (escaped, not stripped) — acceptable, since
  the goal is preventing line-framing forgery, not content filtering.

## 17. Oversized/malformed payloads

- **Asset:** REVA Core's API and JSON parsing.
- **Attacker:** any caller of the local API.
- **Attack path:** an extremely large or malformed JSON body sent to a
  domain route.
- **Impact:** memory exhaustion or a crash (denial of service against
  oneself, since Core is loopback-only).
- **Mitigation:** FastAPI/Starlette's request parsing rejects malformed
  JSON with a 4xx before it reaches any handler. Phase 1A's two
  body-accepting routes (`POST /v1/messages`, `POST /v1/memories`)
  bound every string field with `Field(max_length=...)` — 4000 chars
  for a message, 8000 for memory content, 16 tags of 64 chars each —
  enforced by pydantic before any handler code runs
  (`tests/integration/test_v1_memories_api.py::test_create_memory_rejects_oversized_content`).
- **Remaining risk:** field-level length limits bound the *parsed*
  content, not the raw byte size of the HTTP request body itself (no
  `Content-Length` cap at the ASGI layer); a malformed-but-under-field-limit
  large body could still cost parse time. Low severity given
  loopback-only reach; a body-size limit is a candidate hardening item.

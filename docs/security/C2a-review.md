# C2a security review: a phone asks the PC to act

Scope: `reva_core/gateway/service.py` (`act_propose`, `act_status`, `set_phone_actions`), `reva_core/policy/broker.py` (remote inbox, withdrawal, lock), `reva_core/gateway/routes.py` (owner controls and PC pickup). Invariants: a model proposes and only the broker authorizes; only executors act; success only from executor evidence; T2 needs a click on the target device; a spoken yes never commits.

| Threat | Result |
|---|---|
| Phone approves its own T2 request | Impossible: the gateway has no approval route (probed on GET/POST/PUT); `windows.app.close` is `confirm_on: target`, so an approval bound to the phone's device id, or made with `via` speech, is `STATE_MISMATCH`/`APPROVAL_REQUIRED`. Only the Core-token click path on this PC approves |
| Phone asks for more than it was given | Two scopes (`pc.app.open`, `pc.app.close`), set only by the owner with the Core bearer token; an allowlist of exactly two capabilities in code, checked before the broker; the registry's other capabilities (UI control, memory, money, `assistant.*`) are unreachable |
| Forged or replayed request | Gateway signature + 120 s window + nonce set (existing); a replay of the same signed bytes is 401 |
| Late execution after an outage | `issued_at` inside the body: older than 120 s or more than 30 s in the future is `request_expired` |
| Duplicate on retry | Idempotency key `request_id`; the broker id is derived from device id + request id; a retry returns the same action, no second ledger row, no second order, also after success |
| Substitution | The same id with another capability or other arguments is `STATE_MISMATCH`; the original is untouched |
| One phone reads or overwrites another's request | The id space is per device (SHA-256 of device id + request id); status for another phone's id is 404 |
| Revoked phone keeps acting | Admission refuses it; waiting requests and undelivered orders are withdrawn (`DEVICE_REVOKED`); the inbox never hands out an order from an inactive phone. An order the executor already holds is not recalled (documented) |
| Evidence forgery | Executor reports go through the existing broker check; `verified` without evidence of the registry's shape is `unknown`; the phone is told only the Core's status and template |
| Order or grant leaks to the phone | Responses are built from a fixed field list with no order, grant or signature (asserted on every response) |
| Resource exhaustion | One phone may hold 8 open requests (429 beyond; retries of known ids still work); the PC's own app is unaffected; arguments are capped at 2 KiB; body limits unchanged |
| Race between gateway and Core API threads | The broker's public methods are serialized by one re-entrant lock; an 8-thread proposal test passes |
| Unauthenticated PC pickup | `/v1/devices/requests` and `/v1/devices/{id}/pc-access` need the Core bearer token; the gateway never serves them |

Findings fixed in this slice: a phone could have held the whole broker open (per-phone cap added); the first design wrote ledger kinds the schema does not allow (switched to the existing kinds rather than adding a migration). Left open: orders are marked delivered in memory only (the safe direction, documented).

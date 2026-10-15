# Phone actions (C2): a phone asks the PC to act

Spec: ARD-600 (AR-AGT-007, AR-AGT-016), ARD-200 AR-AND-008, ADR-008 (target-device approval), AC-009.
Code: `reva_core/gateway/service.py` (`act_propose`, `act_status`), `reva_core/policy/broker.py` (remote inbox), `reva_core/gateway/routes.py` (owner controls). Tests: `tests/gateway/test_phone_actions.py`.

## Flow

```
phone ──signed POST /actions/propose──► gateway ──► broker.propose (source "phone")
                                                      │ T1 open: grant signed at once
                                                      │ T2 close: waits for a click on THIS PC
PC app ◄── GET /v1/devices/requests (Core token) ┘  cards to show, signed orders to run (once)
PC app ── click ──► POST /v1/actions/{id}/approval (via click, on this PC) ──► signed order
PC executor runs the order ── PUT /v1/actions/{id} (evidence) ──► broker records verified/failed/unknown
phone ──signed POST /actions/status──► the Core's own record, in the Core's words
```

The phone can never approve, never receives an order or a grant, and never reports an outcome. It hears "done" only when the status is `verified`, which the broker records only when the executor sent evidence of the kind the registry expects.

## What a phone may ask

| Capability | Tier | Scope on the grant | Approval |
|---|---|---|---|
| `windows.app.open` | T1 | `pc.app.open` | none (the app is one the owner approved on the PC) |
| `windows.app.close` | T2 | `pc.app.close` | a click on this PC (`confirm_on: target`) |

Nothing else is reachable from a phone, whatever the registry contains: not UI control, memory, money, `assistant.*`. The two scopes are set only by the owner, on this PC: `PATCH /v1/devices/{id}/pc-access {"open_apps": bool, "close_apps": bool}` (Core bearer token). A phone paired before C2 has neither scope until the owner grants it, so there is no re-pair step; revoking a phone and pairing again gives a fresh grant with finance sync only.

## Rules the tests pin down

- **No scope, no request.** `out_of_scope` (403) and nothing reaches the broker.
- **Allowlist.** Any other capability name is `capability_not_allowed` (403), also case variants.
- **Stale.** A request carries `issued_at`; older than 120 s or more than 30 s ahead is `request_expired` (410). A retry after a long outage therefore cannot act late.
- **Replay.** The gateway's nonce check refuses the same signed request twice (401).
- **Duplicates.** `request_id` is the idempotency key: the broker id is derived from the phone's device id and the `request_id`, so a retry (new nonce, same id) returns the same action, writes no second ledger row and hands no second order to the executor, even after success.
- **Substitution.** The same `request_id` with a different capability or arguments is `refused` / `STATE_MISMATCH`; the original is untouched.
- **Isolation.** The id space is per phone: one phone cannot read, collide with, or overwrite another's request or the PC's own.
- **Approval.** A spoken yes, a "phone" tap, or the phone's own device id never approves a close (`confirm_on: target` binds the approval to this PC's screen). The gateway has no approval route at all.
- **Expiry.** An approval that waits more than two minutes is `expired`; a late click does nothing.
- **Revocation.** Revoking a phone withdraws its waiting requests and any order the PC's app has not picked up (`denied` / `DEVICE_REVOKED`); the inbox never hands out an order from an inactive phone. An order the executor already holds cannot be recalled and still reports.
- **Evidence.** `verified` without evidence of the right shape is recorded as `unknown`, so the phone never hears success from a bare report.
- **Concurrency.** The broker serializes its public methods (the gateway thread and the Core API thread both use it).

## Limits worth knowing

- The "delivered" mark for an order is in memory: if Core restarts between handing an order to the app and the executor reporting, the order is not handed out again and the action ends `unknown` when its grant expires. That is the safe direction (no double run).
- The PC app polls the inbox (long poll, up to 25 s); a phone request waits for the PC app to be running. With the PC app closed the action stays `granted` or `awaiting_approval` until it expires, and the phone says so.
- The ledger has no `delivered` kind (it would need a migration); a withdrawn request is logged as `denied` with `via: system`.

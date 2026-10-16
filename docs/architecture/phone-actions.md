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

## This PC's app (C2b)

- `desktop/src/Reva.Desktop/Actions/PhoneRequestPoller.cs` long-polls `GET /v1/devices/requests` (Core token, loopback, up to 20 s), with a 250 ms floor between rounds and a backoff of 1 s doubling to 30 s while the Core is unreachable.
- A request that waits for approval becomes the same confirm card the voice flow uses, headed "Pixel 8 asks: Close Calculator? Approve it on screen." The click goes to the Core as a click on this PC (`via: click`), exactly as for a voice request. A card the Core stops listing (expired, denied, phone revoked) is closed.
- An order for something safe goes to the existing executor, which verifies the signed grant (signature, expiry, target, actor, arguments) before it touches anything; the same order twice runs once; one item that throws does not stop the next.
- Devices page: each active phone has two checkboxes, "Let this phone open apps on this PC" and "Let this phone ask to close apps (I approve each one here)". They call `PATCH /v1/devices/{id}/pc-access`, so a phone paired before C2 is upgraded in place; unchecking takes it back.
- Contract: `tools/desktop/generate_devices_fixtures.py` now captures the real Core's `pc-access`, the paired-with-access device list and the inbox (card + order, then card only) from a real gateway and phone simulator; the C# client and parser are tested against those files, and `tests/contract/test_devices_ui_fixtures.py` fails if the Core's shape changes.

## Limits worth knowing

- The "delivered" mark for an order is in memory: if Core restarts between handing an order to the app and the executor reporting, the order is not handed out again and the action ends `unknown` when its grant expires. That is the safe direction (no double run).
- The PC app polls the inbox (long poll, up to 25 s); a phone request waits for the PC app to be running. With the PC app closed the action stays `granted` or `awaiting_approval` until it expires, and the phone says so.
- The ledger has no `delivered` kind (it would need a migration); a withdrawn request is logged as `denied` with `via: system`.

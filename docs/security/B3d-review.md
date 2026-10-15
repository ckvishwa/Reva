# B3d security review (assistant.stop / repeat / undo)

Scope: PR #20. Focus: approval bypass, grant substitution or replay, undoing someone else's action, evidence forgery.

| Check | Result |
|---|---|
| Undo needs a click or tap | `assistant.undo` is T2 in the registry; `authorize()` returns APPROVAL_REQUIRED without one; speech approval stays `awaiting_approval` (tests) |
| Grant substitution / replay | `target_action_id` is in the signed args hash; a different target needs a new proposal and card; the second undo of one expense fails (entry forgotten) |
| Undoing an unrelated or older action | Executor acts only on an id in `ExpenseLog` (expenses the Kernel confirmed in this Core) and only the newest one. **Finding fixed in this PR:** through `/v1/actions/proposals` an older recorded expense could be targeted while the card said "last expense". Now refused (`failed`, nothing changed) |
| Evidence forgery | `verified` needs `kernel_event` evidence with an event-id shaped reference, else the broker records `unknown`; the executor's evidence is the Kernel's tombstone event id |
| Stop / repeat | T0, read-only; repeat replays text already spoken; stop commits nothing and does not cancel a card already on screen (expires in 2 minutes) |
| Forbidden capabilities | Registry absence test still passes; no new money, shell, delete-file or email capability |

Residual: the undo map is in memory and bounded (32); after a restart nothing is undoable. No dependency changes.

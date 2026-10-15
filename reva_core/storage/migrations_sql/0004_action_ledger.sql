-- Action ledger (AR-AGT-010): every proposal, decision, approval, grant and outcome, as append-only rows.
-- Arguments are stored redacted (only small enum-like values, never amounts, notes or free text), and
-- no secret is stored here. Rows can be added but never changed or removed: the triggers refuse it.

BEGIN;

CREATE TABLE action_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT NOT NULL,
    seq       INTEGER NOT NULL,
    at        TEXT NOT NULL,
    kind      TEXT NOT NULL CHECK (kind IN (
        'proposed', 'refused', 'awaiting_approval', 'approval_rejected', 'approved', 'denied',
        'granted', 'expired', 'outcome'
    )),
    payload   TEXT NOT NULL,
    UNIQUE (action_id, seq)
);

CREATE INDEX idx_action_events_action ON action_events (action_id, seq);
CREATE INDEX idx_action_events_at ON action_events (at);

CREATE TRIGGER action_events_no_update BEFORE UPDATE ON action_events
BEGIN
    SELECT RAISE(ABORT, 'the action ledger is append-only');
END;

CREATE TRIGGER action_events_no_delete BEFORE DELETE ON action_events
BEGIN
    SELECT RAISE(ABORT, 'the action ledger is append-only');
END;

COMMIT;

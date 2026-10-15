-- Down for 0004: removes the action ledger. The triggers go first because they refuse deletes.

BEGIN;
DROP TRIGGER IF EXISTS action_events_no_update;
DROP TRIGGER IF EXISTS action_events_no_delete;
DROP TABLE IF EXISTS action_events;
COMMIT;

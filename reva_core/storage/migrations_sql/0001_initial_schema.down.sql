-- Down for 0001: removes the initial schema. Everything stored in these tables is lost;
-- a snapshot is taken before any upgrade so data can be restored instead.

BEGIN;
DROP TABLE IF EXISTS sync_events;
DROP TABLE IF EXISTS audit_events;
DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS reminders;
DROP TABLE IF EXISTS memories;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS application_metadata;
COMMIT;

-- Migration 0001: initial schema (architecture lock).
--
-- Every planned V1 table is created now so the schema is locked in
-- Phase 0, even though most tables have no application code writing to
-- them yet (see docs/architecture/data-flow.md for IMPLEMENTED vs
-- PLANNED). All entity IDs are UUIDv7 TEXT; all timestamps are UTC
-- ISO-8601 TEXT. Foreign keys are enforced (PRAGMA foreign_keys=ON is
-- set per-connection in reva_core/storage/connection.py).
BEGIN;

CREATE TABLE application_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE devices (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    platform     TEXT NOT NULL,
    paired_at    TEXT NOT NULL,
    last_seen_at TEXT
);

CREATE TABLE conversations (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    origin_device_id  TEXT NOT NULL REFERENCES devices(id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX idx_conversations_updated_at ON conversations(updated_at);

CREATE TABLE messages (
    id                TEXT PRIMARY KEY,
    conversation_id   TEXT NOT NULL REFERENCES conversations(id),
    role              TEXT NOT NULL,
    content           TEXT NOT NULL,
    origin_device_id  TEXT NOT NULL REFERENCES devices(id),
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_messages_conversation_id ON messages(conversation_id, created_at);

CREATE TABLE memories (
    id                     TEXT PRIMARY KEY,
    category               TEXT NOT NULL,
    content                TEXT NOT NULL,
    source_conversation_id TEXT REFERENCES conversations(id),
    source_message_id      TEXT REFERENCES messages(id),
    origin_device_id       TEXT NOT NULL REFERENCES devices(id),
    source_note            TEXT,
    tags                   TEXT NOT NULL DEFAULT '',
    retention_state        TEXT NOT NULL DEFAULT 'active',
    sync_version           INTEGER NOT NULL DEFAULT 1,
    created_at             TEXT NOT NULL,
    updated_at             TEXT NOT NULL
);
CREATE INDEX idx_memories_retention_state ON memories(retention_state, created_at);

CREATE TABLE reminders (
    id                TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    content           TEXT,
    due_at            TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'pending',
    origin_device_id  TEXT NOT NULL REFERENCES devices(id),
    created_at        TEXT NOT NULL
);
CREATE INDEX idx_reminders_due_at ON reminders(due_at, status);

CREATE TABLE permissions (
    id          TEXT PRIMARY KEY,
    capability  TEXT NOT NULL UNIQUE,
    granted     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);

CREATE TABLE audit_events (
    id               TEXT PRIMARY KEY,
    category         TEXT NOT NULL,
    action           TEXT NOT NULL,
    outcome          TEXT NOT NULL,
    correlation_id   TEXT,
    actor_device_id  TEXT REFERENCES devices(id),
    metadata         TEXT NOT NULL DEFAULT '{}',
    occurred_at      TEXT NOT NULL
);
CREATE INDEX idx_audit_events_occurred_at ON audit_events(occurred_at, category);

CREATE TABLE sync_events (
    id              TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL REFERENCES devices(id),
    entity_type     TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    entity_version  INTEGER NOT NULL,
    operation       TEXT NOT NULL,
    occurred_at     TEXT NOT NULL
);
CREATE INDEX idx_sync_events_device_id ON sync_events(device_id, occurred_at);

COMMIT;

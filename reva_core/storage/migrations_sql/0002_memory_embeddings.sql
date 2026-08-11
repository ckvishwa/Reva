-- Migration 0002: derived, rebuildable semantic-embedding index.
--
-- `memories` remains the sole authoritative record (see
-- reva_core/shared/contracts/memory.py's module docstring). This table
-- only ever references memories.id; nothing else may reference this
-- table, so it can always be safely dropped and rebuilt via backfill.
BEGIN;

CREATE TABLE memory_embeddings (
    memory_id   TEXT NOT NULL REFERENCES memories(id),
    model_id    TEXT NOT NULL,
    dims        INTEGER NOT NULL,
    vector      BLOB NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (memory_id, model_id)
);
CREATE INDEX idx_memory_embeddings_model_id ON memory_embeddings(model_id);

COMMIT;

-- Down for 0002: removes stored memory embeddings (they are rebuilt by the startup backfill).

BEGIN;
DROP TABLE IF EXISTS memory_embeddings;
COMMIT;

-- Down for 0003: removes paired-device grants (devices must be paired again).

BEGIN;
DROP TABLE IF EXISTS device_grants;
COMMIT;

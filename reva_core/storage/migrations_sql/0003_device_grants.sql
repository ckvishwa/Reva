-- Pairing gateway grants (ARD-500 section 2): one row per approved phone, next to its `devices` row.
-- Holds public material only: the phone's P-256 public key (SubjectPublicKeyInfo DER, base64) and
-- the Kernel device id of each domain file it syncs. No secret is stored here.

BEGIN;

CREATE TABLE device_grants (
    device_id    TEXT PRIMARY KEY REFERENCES devices(id),
    public_key   TEXT NOT NULL,
    kernel_ids   TEXT NOT NULL,
    scopes       TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    approved_at  TEXT NOT NULL,
    revoked_at   TEXT
);

COMMIT;

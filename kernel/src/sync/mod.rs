//! Device-to-device sync primitives (ARD-500 §3): paired peers, device-key signatures on events,
//! per-peer cursors and the checks every inbound batch must pass.
//!
//! The Kernel never does network I/O. A host transport (the pairing gateway on Windows, the sync
//! client on Android) moves `SyncBatch` values between devices; this module decides what may be
//! sent, what may be applied, and refuses everything else.
//!
//! Trust model:
//! * Each device holds a P-256 key in its OS vault (Credential Manager / Android Keystore) and
//!   exposes it to the Kernel only through [`DeviceSigner`]; the private key never enters the Kernel.
//! * A peer exists only after the user approved pairing; the host then calls `register_peer` with
//!   the peer's public key. Scopes name the domains the peer may exchange (finance sync only).
//! * Events leave this device signed with the device key, and are accepted only when the origin
//!   device is a registered, active peer, in scope, and the signature verifies over the canonical
//!   event bytes. A whole batch is rejected if any event fails; nothing is half-applied.

use p256::ecdsa::signature::Verifier;
use p256::ecdsa::{Signature, VerifyingKey};
use p256::pkcs8::DecodePublicKey;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::civil;
use crate::error::{DomainError, DomainResult};
use crate::events::{self, Event};

/// Prefix of a device-key signature in `Event::signature`. Local integrity tags (plain hex) never
/// carry it, so the two cannot be confused.
pub const SIG_PREFIX: &str = "es256:";
/// Largest batch the transport contract allows (contracts/sync-batch.schema.json `maxItems`).
pub const MAX_BATCH_EVENTS: usize = 500;
/// Largest serialized batch the Kernel will parse.
pub const MAX_BATCH_BYTES: usize = 8 * 1024 * 1024;
/// Lamport values above this cannot come from a real device and would overflow the local clock.
pub const MAX_LAMPORT: i64 = 9_007_199_254_740_991;

pub const KNOWN_DOMAINS: &[&str] = &["memory", "finance", "health", "coach", "career", "learn", "cyber", "personal"];

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum SignerError {
    #[error("device key unavailable: {detail}")]
    Unavailable { detail: String },
}

impl From<uniffi::UnexpectedUniFFICallbackError> for SignerError {
    fn from(error: uniffi::UnexpectedUniFFICallbackError) -> Self {
        SignerError::Unavailable { detail: error.reason }
    }
}

/// Implemented by the host around its OS key vault. Calls may block briefly and must not be made
/// from a UI thread (AR-DOM-015).
#[uniffi::export(with_foreign)]
pub trait DeviceSigner: Send + Sync {
    /// The device public key as X.509 SubjectPublicKeyInfo DER (P-256).
    fn public_key(&self) -> Result<Vec<u8>, SignerError>;
    /// ECDSA P-256 over SHA-256 of `message`, DER encoded (what Android Keystore `SHA256withECDSA`
    /// and `cryptography`'s `ec.ECDSA(SHA256)` produce).
    fn sign(&self, message: Vec<u8>) -> Result<Vec<u8>, SignerError>;
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct PeerInfo {
    pub device_id: String,
    pub label: String,
    pub scopes: Vec<String>,
    /// `active` or `revoked`.
    pub status: String,
    /// SHA-256 of the public key, hex: what both screens show for the user to compare.
    pub fingerprint: String,
    pub paired_at: String,
    pub revoked_at: Option<String>,
    /// Highest local event sequence this peer has acknowledged.
    pub send_cursor: i64,
    /// Highest sequence of the peer's own log that was applied here.
    pub recv_cursor: i64,
}

#[derive(Debug, Clone, uniffi::Record)]
pub struct SyncBatch {
    /// JSON array of signed events (contracts/domain-event.schema.json).
    pub events_json: String,
    /// Sender log position the batch starts after.
    pub cursor_from: i64,
    /// Sender log position the batch reaches. The receiver acknowledges this value.
    pub cursor_to: i64,
    pub count: u64,
}

pub fn ensure_tables(conn: &Connection) -> DomainResult<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS sync_peers (
           device_id   TEXT PRIMARY KEY,
           public_key  BLOB NOT NULL,
           label       TEXT NOT NULL,
           scopes      TEXT NOT NULL,
           status      TEXT NOT NULL,
           paired_at   TEXT NOT NULL,
           revoked_at  TEXT,
           send_cursor INTEGER NOT NULL DEFAULT 0,
           recv_cursor INTEGER NOT NULL DEFAULT 0
         );
         CREATE TABLE IF NOT EXISTS event_sigs (
           event_id  TEXT PRIMARY KEY REFERENCES events (event_id),
           signature TEXT NOT NULL
         );",
    )?;
    Ok(())
}

fn rejected(reason: impl Into<String>) -> DomainError {
    DomainError::Rejected { reason: reason.into() }
}

pub fn fingerprint(public_key: &[u8]) -> String {
    hex::encode(Sha256::digest(public_key))
}

fn parse_key(public_key: &[u8]) -> DomainResult<VerifyingKey> {
    VerifyingKey::from_public_key_der(public_key)
        .map_err(|_| DomainError::validation("public_key", "must be a P-256 public key (SubjectPublicKeyInfo DER)"))
}

struct PeerRow {
    public_key: Vec<u8>,
    scopes: Vec<String>,
    status: String,
}

fn load_peer(conn: &Connection, device_id: &str) -> DomainResult<Option<PeerRow>> {
    let row = conn
        .query_row("SELECT public_key, scopes, status FROM sync_peers WHERE device_id = ?1", [device_id], |r| {
            Ok((r.get::<_, Vec<u8>>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?))
        })
        .optional()?;
    Ok(row.map(|(public_key, scopes, status)| PeerRow {
        public_key,
        scopes: serde_json::from_str(&scopes).unwrap_or_default(),
        status,
    }))
}

/// The peer, if it is registered, not revoked, and allowed to exchange `domain`. Everything else is
/// refused with a reason the host can show (never a secret).
fn active_peer(conn: &Connection, device_id: &str, domain: &str) -> DomainResult<PeerRow> {
    let peer = load_peer(conn, device_id)?.ok_or_else(|| rejected("unknown device"))?;
    if peer.status != "active" {
        return Err(rejected("device was revoked"));
    }
    if !peer.scopes.iter().any(|s| s == domain) {
        return Err(rejected("device is not allowed to sync this domain"));
    }
    Ok(peer)
}

pub fn register_peer(
    conn: &Connection,
    domain: &str,
    own_device_id: &str,
    device_id: &str,
    public_key: &[u8],
    label: &str,
    scopes: &[String],
) -> DomainResult<()> {
    if !(8..=64).contains(&device_id.len())
        || !device_id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
    {
        return Err(DomainError::validation("device_id", "must be 8-64 letters, digits, '-' or '_'"));
    }
    if device_id == own_device_id {
        return Err(DomainError::validation("device_id", "a device cannot be its own peer"));
    }
    parse_key(public_key)?;
    if label.trim().is_empty() || label.chars().count() > 80 {
        return Err(DomainError::validation("label", "must be 1-80 characters"));
    }
    if scopes.is_empty() || scopes.iter().any(|s| !KNOWN_DOMAINS.contains(&s.as_str())) {
        return Err(DomainError::validation("scopes", "must name known domains"));
    }
    if !scopes.iter().any(|s| s == domain) {
        return Err(DomainError::validation("scopes", "must include this domain"));
    }
    let scopes_json = serde_json::to_string(scopes)?;
    match load_peer(conn, device_id)? {
        Some(existing) if existing.status == "active" => {
            if existing.public_key != public_key {
                // Replacing the key of a paired device would let a new key inherit its trust.
                return Err(rejected("device is already paired with a different key; revoke it first"));
            }
            conn.execute(
                "UPDATE sync_peers SET label = ?2, scopes = ?3 WHERE device_id = ?1",
                params![device_id, label.trim(), scopes_json],
            )?;
        }
        Some(_) => {
            // Re-pairing a revoked device is an explicit, user-approved act: new key, cursors restart
            // from the peer's last acknowledged positions so nothing is re-sent needlessly.
            conn.execute(
                "UPDATE sync_peers SET public_key = ?2, label = ?3, scopes = ?4, status = 'active',
                        paired_at = ?5, revoked_at = NULL WHERE device_id = ?1",
                params![device_id, public_key, label.trim(), scopes_json, civil::now_iso()],
            )?;
        }
        None => {
            conn.execute(
                "INSERT INTO sync_peers (device_id, public_key, label, scopes, status, paired_at)
                 VALUES (?1, ?2, ?3, ?4, 'active', ?5)",
                params![device_id, public_key, label.trim(), scopes_json, civil::now_iso()],
            )?;
        }
    }
    Ok(())
}

pub fn revoke_peer(conn: &Connection, device_id: &str) -> DomainResult<()> {
    let changed = conn.execute(
        "UPDATE sync_peers SET status = 'revoked', revoked_at = COALESCE(revoked_at, ?2) WHERE device_id = ?1",
        params![device_id, civil::now_iso()],
    )?;
    if changed == 0 {
        return Err(DomainError::not_found(format!("device {device_id}")));
    }
    Ok(())
}

pub fn list_peers(conn: &Connection) -> DomainResult<Vec<PeerInfo>> {
    let mut stmt = conn.prepare(
        "SELECT device_id, label, scopes, status, public_key, paired_at, revoked_at, send_cursor, recv_cursor
           FROM sync_peers ORDER BY paired_at, device_id",
    )?;
    let rows = stmt.query_map([], |r| {
        let scopes: String = r.get(2)?;
        let key: Vec<u8> = r.get(4)?;
        Ok(PeerInfo {
            device_id: r.get(0)?,
            label: r.get(1)?,
            scopes: serde_json::from_str(&scopes).unwrap_or_default(),
            status: r.get(3)?,
            fingerprint: fingerprint(&key),
            paired_at: r.get(5)?,
            revoked_at: r.get(6)?,
            send_cursor: r.get(7)?,
            recv_cursor: r.get(8)?,
        })
    })?;
    Ok(rows.collect::<Result<_, _>>()?)
}

/// Bytes the device key signs: the canonical event without its `signature` field.
pub fn signing_bytes(event: &Event) -> Vec<u8> {
    let mut body = serde_json::to_value(event).unwrap_or(Value::Null);
    if let Value::Object(map) = &mut body {
        map.remove("signature");
    }
    events::canonical(&body).into_bytes()
}

pub fn encode_signature(der: &[u8]) -> String {
    format!("{SIG_PREFIX}{}", hex::encode(der))
}

/// Verify `event` against a raw SPKI public key (also used to sanity-check our own signer).
pub fn verify_with_key(public_key: &[u8], event: &Event) -> DomainResult<()> {
    let sig_hex = event.signature.strip_prefix(SIG_PREFIX).ok_or_else(|| rejected("event is not signed"))?;
    let der = hex::decode(sig_hex).map_err(|_| rejected("malformed signature"))?;
    let signature = Signature::from_der(&der).map_err(|_| rejected("malformed signature"))?;
    parse_key(public_key)?
        .verify(&signing_bytes(event), &signature)
        .map_err(|_| rejected("signature does not match the event"))
}

/// Check one inbound event against the peer registry. The event's origin must be an active,
/// in-scope peer and the signature must verify over the canonical bytes.
pub fn verify_event(conn: &Connection, event: &Event, domain: &str) -> DomainResult<()> {
    if !event.signature.starts_with(SIG_PREFIX) {
        return Err(rejected("event is not signed with a device key"));
    }
    let peer = active_peer(conn, &event.origin_device_id, domain)?;
    verify_with_key(&peer.public_key, event)
}

/// Log rows to send to a peer: `(seq, event)` pairs plus the cursor range they cover.
pub struct Outgoing {
    pub rows: Vec<(i64, Event)>,
    pub cursor_from: i64,
    pub cursor_to: i64,
}

/// Events after `send_cursor` that this peer should receive, never its own events back. The
/// returned cursor is the last log position scanned, so skipped rows are not rescanned.
pub fn events_after(conn: &Connection, peer_device_id: &str, domain: &str, limit: usize) -> DomainResult<Outgoing> {
    active_peer(conn, peer_device_id, domain)?;
    let cursor_from: i64 =
        conn.query_row("SELECT send_cursor FROM sync_peers WHERE device_id = ?1", [peer_device_id], |r| r.get(0))?;
    let limit = limit.clamp(1, MAX_BATCH_EVENTS);
    let rows = events::scan_after(conn, cursor_from, limit as u32)?;
    let cursor_to = rows.last().map(|(seq, _)| *seq).unwrap_or(cursor_from);
    let selected = rows.into_iter().filter(|(_, e)| e.origin_device_id != peer_device_id).collect();
    Ok(Outgoing { rows: selected, cursor_from, cursor_to })
}

pub fn cached_signature(conn: &Connection, event_id: &str) -> DomainResult<Option<String>> {
    Ok(conn.query_row("SELECT signature FROM event_sigs WHERE event_id = ?1", [event_id], |r| r.get(0)).optional()?)
}

pub fn store_signature(conn: &Connection, event_id: &str, signature: &str) -> DomainResult<()> {
    conn.execute(
        "INSERT OR REPLACE INTO event_sigs (event_id, signature) VALUES (?1, ?2)",
        params![event_id, signature],
    )?;
    Ok(())
}

/// Record that the peer holds everything up to `cursor` of our log. Moves forward only.
pub fn ack_peer(conn: &Connection, peer_device_id: &str, domain: &str, cursor: i64) -> DomainResult<()> {
    active_peer(conn, peer_device_id, domain)?;
    let head: i64 = conn.query_row("SELECT COALESCE(MAX(seq), 0) FROM events", [], |r| r.get(0))?;
    if cursor < 0 || cursor > head {
        return Err(DomainError::validation("cursor", "is outside this device's log"));
    }
    conn.execute(
        "UPDATE sync_peers SET send_cursor = MAX(send_cursor, ?2) WHERE device_id = ?1",
        params![peer_device_id, cursor],
    )?;
    // The durable outbox only needs rows some active peer has not yet acknowledged.
    let slowest: Option<i64> = conn
        .query_row("SELECT MIN(send_cursor) FROM sync_peers WHERE status = 'active'", [], |r| r.get(0))
        .optional()?
        .flatten();
    if let Some(slowest) = slowest {
        conn.execute("DELETE FROM outbox WHERE event_id IN (SELECT event_id FROM events WHERE seq <= ?1)", [slowest])?;
    }
    Ok(())
}

pub fn note_received(conn: &Connection, peer_device_id: &str, cursor_to: i64) -> DomainResult<()> {
    conn.execute(
        "UPDATE sync_peers SET recv_cursor = MAX(recv_cursor, ?2) WHERE device_id = ?1",
        params![peer_device_id, cursor_to],
    )?;
    Ok(())
}

/// Checks that need no database: size, count, and shape of the incoming batch.
pub fn parse_batch(batch: &SyncBatch, domain: &str) -> DomainResult<Vec<Event>> {
    if batch.events_json.len() > MAX_BATCH_BYTES {
        return Err(DomainError::validation("events_json", "batch is too large"));
    }
    if batch.cursor_from < 0 || batch.cursor_to < batch.cursor_from {
        return Err(DomainError::validation("cursor", "is not a valid range"));
    }
    let incoming: Vec<Event> =
        serde_json::from_str(&batch.events_json).map_err(|e| DomainError::validation("events_json", e.to_string()))?;
    if incoming.len() > MAX_BATCH_EVENTS {
        return Err(DomainError::validation("events_json", "more than 500 events in one batch"));
    }
    for event in &incoming {
        events::validate_remote(event, domain)?;
    }
    Ok(incoming)
}

/// The sender must be an active, in-scope peer.
pub fn check_sender(conn: &Connection, sender_device_id: &str, domain: &str) -> DomainResult<()> {
    active_peer(conn, sender_device_id, domain).map(|_| ())
}

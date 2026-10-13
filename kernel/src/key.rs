//! Key handling. The host owns the key vault (Windows Credential Manager / DPAPI,
//! Android Keystore); the Kernel only asks for the key and never persists it.

use hmac::{Hmac, Mac};
use sha2::Sha256;

pub const KEY_LEN: usize = 32;

#[derive(Debug, thiserror::Error, uniffi::Error)]
pub enum KeyProviderError {
    #[error("key store unavailable: {detail}")]
    Unavailable { detail: String },
}

impl From<uniffi::UnexpectedUniFFICallbackError> for KeyProviderError {
    fn from(error: uniffi::UnexpectedUniFFICallbackError) -> Self {
        KeyProviderError::Unavailable { detail: error.reason }
    }
}

/// Implemented by the host. Both calls may block briefly (vault access) and must
/// not be made from a UI thread (AR-DOM-015).
#[uniffi::export(with_foreign)]
pub trait KeyProvider: Send + Sync {
    /// The stored key for `domain`, or `None` if this install has never stored one.
    fn load_key(&self, domain: String) -> Result<Option<Vec<u8>>, KeyProviderError>;

    /// Persist a freshly generated key. Called only on a fresh install, before the
    /// data file is created. If this fails, no data file is created.
    fn store_key(&self, domain: String, key: Vec<u8>) -> Result<(), KeyProviderError>;
}

type HmacSha256 = Hmac<Sha256>;

fn hmac_hex(key: &[u8], label: &str) -> String {
    let mut mac = HmacSha256::new_from_slice(key).expect("HMAC accepts any key length");
    mac.update(label.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Key check value: lets the Kernel tell a wrong key from a corrupt file without
/// opening the database. It reveals nothing usable about the key.
pub fn key_check_value(key: &[u8]) -> String {
    hmac_hex(key, "reva-kcv-v1")
}

/// Key used for the integrity tag on events (see `events::sign`).
pub fn event_tag_key(key: &[u8]) -> Vec<u8> {
    hex::decode(hmac_hex(key, "reva-event-tag-v1")).expect("hex of hmac output")
}

pub fn generate_key() -> Result<Vec<u8>, crate::error::DomainError> {
    let mut key = vec![0_u8; KEY_LEN];
    getrandom::getrandom(&mut key).map_err(|e| crate::error::DomainError::internal(format!("random source: {e}")))?;
    Ok(key)
}

pub fn constant_time_eq(a: &str, b: &str) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.bytes().zip(b.bytes()).fold(0_u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

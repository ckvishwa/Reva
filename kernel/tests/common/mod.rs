//! Shared helpers for integration tests. `MemKeys` plays the host's key vault.
#![allow(dead_code)]

use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex};

use reva_kernel::{open_domain, DomainError, DomainHandle, KeyProvider, KeyProviderError};
use serde_json::Value;

#[derive(Default)]
pub struct MemKeys {
    pub keys: Mutex<HashMap<String, Vec<u8>>>,
    pub fail_load: Mutex<bool>,
    pub fail_store: Mutex<bool>,
    pub store_calls: Mutex<u32>,
}

impl MemKeys {
    pub fn new() -> Arc<MemKeys> {
        Arc::new(MemKeys::default())
    }

    pub fn get(&self, domain: &str) -> Option<Vec<u8>> {
        self.keys.lock().unwrap().get(domain).cloned()
    }

    pub fn put(&self, domain: &str, key: Vec<u8>) {
        self.keys.lock().unwrap().insert(domain.to_string(), key);
    }

    pub fn remove(&self, domain: &str) {
        self.keys.lock().unwrap().remove(domain);
    }
}

impl KeyProvider for MemKeys {
    fn load_key(&self, domain: String) -> Result<Option<Vec<u8>>, KeyProviderError> {
        if *self.fail_load.lock().unwrap() {
            return Err(KeyProviderError::Unavailable { detail: "vault offline".into() });
        }
        Ok(self.keys.lock().unwrap().get(&domain).cloned())
    }

    fn store_key(&self, domain: String, key: Vec<u8>) -> Result<(), KeyProviderError> {
        *self.store_calls.lock().unwrap() += 1;
        if *self.fail_store.lock().unwrap() {
            return Err(KeyProviderError::Unavailable { detail: "vault read-only".into() });
        }
        self.keys.lock().unwrap().insert(domain, key);
        Ok(())
    }
}

pub fn open(dir: &Path, keys: &Arc<MemKeys>) -> Result<Arc<DomainHandle>, DomainError> {
    open_domain("finance".to_string(), keys.clone(), dir.to_string_lossy().to_string())
}

pub fn code(error: &DomainError) -> &'static str {
    match error {
        DomainError::Locked => "locked",
        DomainError::WrongKey => "wrong_key",
        DomainError::Corrupt => "corrupt",
        DomainError::MigrationFailed { .. } => "migration_failed",
        DomainError::Validation { .. } => "validation",
        DomainError::Conflict { .. } => "conflict",
        DomainError::NotFound { .. } => "not_found",
        DomainError::Deleted { .. } => "deleted",
        DomainError::Internal { .. } => "internal",
        DomainError::Rejected { .. } => "rejected",
    }
}

pub fn cmd(h: &DomainHandle, kind: &str, payload: Value) -> reva_kernel::CommitResult {
    h.command(kind.to_string(), payload.to_string()).unwrap_or_else(|e| panic!("{kind} failed: {e}"))
}

pub fn rows(h: &DomainHandle, name: &str, params: Value) -> Vec<Value> {
    let out = h.query(name.to_string(), params.to_string()).unwrap_or_else(|e| panic!("query {name} failed: {e}"));
    serde_json::from_str::<Value>(&out.rows_json).unwrap().as_array().cloned().unwrap_or_default()
}

pub fn domain_file(dir: &Path) -> std::path::PathBuf {
    reva_kernel::internals::domain_file(dir, "finance")
}

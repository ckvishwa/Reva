//! SQLCipher open, key handling, migrations, backup and recovery (ADR-028).
//!
//! Rules that protect data:
//! * An existing data file is never overwritten, re-keyed or deleted by `open`.
//! * A key is generated only on a fresh install (no data file) and is stored with the
//!   host *before* the data file is created.
//! * Missing key, wrong key and corrupt file are three different typed errors.

pub mod backup;
pub mod migrate;

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::time::Duration;

use rusqlite::Connection;
use zeroize::Zeroizing;

use crate::error::{DomainError, DomainResult};
use crate::key::{self, KeyProvider, KEY_LEN};

pub use migrate::Migration;

const BUSY_TIMEOUT_MS: u64 = 5_000;
const SQLITE_HEADER: &[u8; 16] = b"SQLite format 3\0";

pub struct Store {
    pub conn: Connection,
    pub path: PathBuf,
    pub domain: String,
    pub device_id: String,
    key: Zeroizing<Vec<u8>>,
    tag_key: Vec<u8>,
}

pub fn domain_file(data_dir: &Path, domain: &str) -> PathBuf {
    data_dir.join("domains").join(format!("{domain}.sqlite3"))
}

fn kcv_file(path: &Path) -> PathBuf {
    let mut name = path.file_name().map(|n| n.to_os_string()).unwrap_or_default();
    name.push(".kcv");
    path.with_file_name(name)
}

fn valid_domain_name(domain: &str) -> bool {
    !domain.is_empty() && domain.len() <= 32 && domain.bytes().all(|b| b.is_ascii_lowercase() || b == b'_')
}

impl Store {
    pub fn open(
        domain: &str,
        data_dir: &Path,
        keys: &dyn KeyProvider,
        migrations: &[Migration],
    ) -> DomainResult<Store> {
        if !valid_domain_name(domain) {
            return Err(DomainError::validation("domain", "must be lowercase letters and underscores"));
        }
        let path = domain_file(data_dir, domain);
        let dir = path.parent().expect("domain file has a parent").to_path_buf();
        fs::create_dir_all(&dir)?;
        let kcv_path = kcv_file(&path);

        let exists = path.exists();
        let loaded = keys.load_key(domain.to_string()).map_err(|_| DomainError::Locked)?;

        let (key, fresh) = match (loaded, exists) {
            (Some(key), _) => (Zeroizing::new(key), !exists),
            // A data file exists but the vault has no key: never invent one.
            (None, true) => return Err(DomainError::Locked),
            (None, false) => {
                let key = Zeroizing::new(key::generate_key()?);
                keys.store_key(domain.to_string(), key.to_vec()).map_err(|_| DomainError::Locked)?;
                (key, true)
            }
        };
        if key.len() != KEY_LEN {
            return Err(if exists { DomainError::WrongKey } else { DomainError::Locked });
        }

        if !fresh {
            Self::check_existing(&path, &kcv_path, &key)?;
        }

        let conn = match Connection::open(&path) {
            Ok(conn) => conn,
            Err(e) => {
                if fresh {
                    let _ = fs::remove_file(&path);
                }
                return Err(e.into());
            }
        };
        let opened = (|| -> DomainResult<()> {
            apply_key(&conn, &key)?;
            if fresh {
                configure(&conn)?;
            } else {
                Self::verify_readable(&conn, &path, &kcv_path, &key)?;
                configure(&conn)?;
            }
            Ok(())
        })();
        if let Err(error) = opened {
            drop(conn);
            if fresh {
                cleanup_fresh(&path);
            }
            return Err(error);
        }

        let tag_key = key::event_tag_key(&key);
        let mut store =
            Store { conn, path: path.clone(), domain: domain.to_string(), device_id: String::new(), key, tag_key };

        if let Err(error) = migrate::run(&mut store, migrations) {
            if fresh {
                drop(store);
                cleanup_fresh(&path);
            }
            return Err(error);
        }
        // Unversioned and additive, so later domain migrations are never skipped by a high version.
        crate::sync::ensure_tables(&store.conn)?;
        store.device_id = store.load_or_create_device_id()?;
        if fresh || !kcv_path.exists() {
            fs::write(&kcv_path, key::key_check_value(&store.key))?;
        }
        Ok(store)
    }

    /// Cheap pre-checks on an existing file, before any SQLite handle is opened.
    fn check_existing(path: &Path, kcv_path: &Path, key: &[u8]) -> DomainResult<()> {
        let size = fs::metadata(path)?.len();
        if size == 0 {
            return Err(DomainError::Corrupt);
        }
        let mut header = [0_u8; 16];
        let read = fs::File::open(path)?.read(&mut header)?;
        if read == 16 && &header == SQLITE_HEADER {
            // Plaintext SQLite is never a valid REVA domain file.
            return Err(DomainError::Corrupt);
        }
        if let Ok(stored) = fs::read_to_string(kcv_path) {
            if !key::constant_time_eq(stored.trim(), &key::key_check_value(key)) {
                return Err(DomainError::WrongKey);
            }
        }
        Ok(())
    }

    fn verify_readable(conn: &Connection, path: &Path, kcv_path: &Path, key: &[u8]) -> DomainResult<()> {
        let readable = conn.query_row("SELECT count(*) FROM sqlite_master", [], |r| r.get::<_, i64>(0));
        if readable.is_err() {
            let size = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            let kcv_matches = fs::read_to_string(kcv_path)
                .map(|s| key::constant_time_eq(s.trim(), &key::key_check_value(key)))
                .unwrap_or(false);
            return Err(if kcv_matches || size < 4096 || !size.is_multiple_of(1024) {
                DomainError::Corrupt
            } else {
                DomainError::WrongKey
            });
        }
        let quick: String =
            conn.query_row("PRAGMA quick_check(1)", [], |r| r.get(0)).map_err(|_| DomainError::Corrupt)?;
        if quick != "ok" {
            return Err(DomainError::Corrupt);
        }
        Ok(())
    }

    fn load_or_create_device_id(&self) -> DomainResult<String> {
        if let Some(id) = self.meta_get("device_id")? {
            return Ok(id);
        }
        let id = uuid::Uuid::new_v4().to_string();
        self.meta_set("device_id", &id)?;
        Ok(id)
    }

    pub fn meta_get(&self, name: &str) -> DomainResult<Option<String>> {
        meta_get(&self.conn, name)
    }

    pub fn meta_set(&self, name: &str, value: &str) -> DomainResult<()> {
        meta_set(&self.conn, name, value)
    }

    pub fn key_bytes(&self) -> &[u8] {
        &self.key
    }

    pub fn tag_key(&self) -> &[u8] {
        &self.tag_key
    }

    pub fn schema_version(&self) -> DomainResult<i64> {
        migrate::current_version(&self.conn)
    }

    /// Copy the encrypted database into `<data_dir>/domains/backups/`.
    pub fn backup_now(&self) -> DomainResult<PathBuf> {
        backup::backup(self, "manual")
    }
}

pub fn meta_get(conn: &Connection, name: &str) -> DomainResult<Option<String>> {
    match conn.query_row("SELECT value FROM meta WHERE key = ?1", [name], |r| r.get::<_, String>(0)) {
        Ok(v) => Ok(Some(v)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e.into()),
    }
}

pub fn meta_set(conn: &Connection, name: &str, value: &str) -> DomainResult<()> {
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?1, ?2) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [name, value],
    )?;
    Ok(())
}

/// Raw 256-bit key, so SQLCipher skips its passphrase KDF (the vault already holds
/// a full-entropy key).
pub(crate) fn apply_key(conn: &Connection, key: &[u8]) -> DomainResult<()> {
    let sql = Zeroizing::new(format!("PRAGMA key = \"x'{}'\";", hex::encode(key)));
    conn.execute_batch(&sql).map_err(DomainError::from)
}

fn configure(conn: &Connection) -> DomainResult<()> {
    conn.busy_timeout(Duration::from_millis(BUSY_TIMEOUT_MS))?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    conn.pragma_update(None, "synchronous", "FULL")?;
    conn.pragma_update(None, "secure_delete", "ON")?;
    conn.pragma_update(None, "temp_store", "MEMORY")?;
    // Keep decrypted pages in memory between queries: SQLCipher decrypts on every page read.
    conn.pragma_update(None, "cache_size", -32768)?;
    Ok(())
}

fn cleanup_fresh(path: &Path) {
    let _ = fs::remove_file(path);
    for suffix in ["-wal", "-shm", "-journal"] {
        let mut name = path.file_name().map(|n| n.to_os_string()).unwrap_or_default();
        name.push(suffix);
        let _ = fs::remove_file(path.with_file_name(name));
    }
    let _ = fs::remove_file(kcv_file(path));
}

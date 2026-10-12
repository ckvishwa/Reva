//! Encrypted online backup using SQLite's backup API (same key as the live file).

use std::fs;
use std::path::PathBuf;
use std::time::Duration;

use rusqlite::backup::Backup;
use rusqlite::Connection;

use super::{apply_key, Store};
use crate::civil;
use crate::error::{DomainError, DomainResult};

pub fn backup(store: &Store, label: &str) -> DomainResult<PathBuf> {
    let dir = store
        .path
        .parent()
        .ok_or_else(|| DomainError::internal("domain file has no parent directory"))?
        .join("backups");
    fs::create_dir_all(&dir)?;
    let stamp = civil::now_unix_ms();
    let dest = dir.join(format!("{}-{}-{}.sqlite3", store.domain, label, stamp));

    let result = (|| -> DomainResult<()> {
        let mut target = Connection::open(&dest)?;
        apply_key(&target, store.key_bytes())?;
        {
            let backup = Backup::new(&store.conn, &mut target)?;
            backup.run_to_completion(64, Duration::from_millis(5), None)?;
        }
        let quick: String = target.query_row("PRAGMA quick_check(1)", [], |r| r.get(0))?;
        if quick != "ok" {
            return Err(DomainError::internal("backup failed its integrity check"));
        }
        Ok(())
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&dest);
        return Err(error);
    }
    Ok(dest)
}

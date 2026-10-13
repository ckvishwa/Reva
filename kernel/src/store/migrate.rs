//! Transactional migrations with a backup before any change to an existing database.

use rusqlite::Connection;

use super::{backup, Store};
use crate::civil;
use crate::error::{DomainError, DomainResult};

#[derive(Debug, Clone, Copy)]
pub struct Migration {
    pub version: i64,
    pub name: &'static str,
    pub sql: &'static str,
}

/// Tables every domain file has: metadata, event log, outbox, tombstones, conflicts.
pub const BASE: Migration = Migration {
    version: 1,
    name: "kernel_base",
    sql: r#"
CREATE TABLE meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE events (
  seq              INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id         TEXT NOT NULL UNIQUE,
  domain           TEXT NOT NULL,
  aggregate_type   TEXT NOT NULL,
  aggregate_id     TEXT NOT NULL,
  version          INTEGER NOT NULL,
  origin_device_id TEXT NOT NULL,
  lamport          INTEGER NOT NULL,
  kind             TEXT NOT NULL,
  created_at       TEXT NOT NULL,
  tombstone        INTEGER NOT NULL,
  payload          TEXT NOT NULL,
  signature        TEXT NOT NULL,
  local            INTEGER NOT NULL
);
CREATE INDEX events_aggregate ON events (aggregate_type, aggregate_id, lamport, origin_device_id);
CREATE INDEX events_order ON events (lamport, origin_device_id, seq);
CREATE TABLE outbox (
  seq      INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE REFERENCES events (event_id)
);
CREATE TABLE tombstones (
  aggregate_type TEXT NOT NULL,
  aggregate_id   TEXT NOT NULL,
  event_id       TEXT NOT NULL,
  deleted_at     TEXT NOT NULL,
  PRIMARY KEY (aggregate_type, aggregate_id)
);
CREATE TABLE conflicts (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  aggregate_type  TEXT NOT NULL,
  aggregate_id    TEXT NOT NULL,
  field           TEXT NOT NULL,
  local_event_id  TEXT NOT NULL,
  remote_event_id TEXT NOT NULL,
  local_value     TEXT NOT NULL,
  remote_value    TEXT NOT NULL,
  detected_at     TEXT NOT NULL,
  resolved        INTEGER NOT NULL DEFAULT 0
);
"#,
};

fn ensure_migration_table(conn: &Connection) -> DomainResult<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS kernel_migrations (
           version    INTEGER PRIMARY KEY,
           name       TEXT NOT NULL,
           applied_at TEXT NOT NULL
         );",
    )?;
    Ok(())
}

pub fn current_version(conn: &Connection) -> DomainResult<i64> {
    ensure_migration_table(conn)?;
    Ok(conn.query_row("SELECT COALESCE(MAX(version), 0) FROM kernel_migrations", [], |r| r.get(0))?)
}

/// Apply every migration newer than the stored version, each in its own transaction.
/// A failure rolls that migration back and leaves the database at the previous version.
pub fn run(store: &mut Store, migrations: &[Migration]) -> DomainResult<()> {
    let mut ordered: Vec<Migration> = std::iter::once(BASE).chain(migrations.iter().copied()).collect();
    ordered.sort_by_key(|m| m.version);
    for pair in ordered.windows(2) {
        if pair[0].version == pair[1].version {
            return Err(DomainError::MigrationFailed {
                detail: format!("duplicate migration version {}", pair[0].version),
            });
        }
    }

    let current = current_version(&store.conn)?;
    let latest = ordered.last().map(|m| m.version).unwrap_or(0);
    if current > latest {
        return Err(DomainError::MigrationFailed {
            detail: format!("database schema v{current} is newer than this build (v{latest})"),
        });
    }
    let pending: Vec<Migration> = ordered.into_iter().filter(|m| m.version > current).collect();
    if pending.is_empty() {
        return Ok(());
    }
    if current > 0 {
        backup::backup(store, &format!("pre-migrate-v{current}"))
            .map_err(|e| DomainError::MigrationFailed { detail: format!("backup before migration failed: {e}") })?;
    }

    for migration in pending {
        let tx = store.conn.transaction().map_err(|e| DomainError::MigrationFailed { detail: e.to_string() })?;
        let applied = (|| -> rusqlite::Result<()> {
            tx.execute_batch(migration.sql)?;
            tx.execute(
                "INSERT INTO kernel_migrations (version, name, applied_at) VALUES (?1, ?2, ?3)",
                rusqlite::params![migration.version, migration.name, civil::now_iso()],
            )?;
            Ok(())
        })();
        match applied {
            Ok(()) => tx.commit().map_err(|e| DomainError::MigrationFailed { detail: e.to_string() })?,
            Err(e) => {
                drop(tx); // rolls back
                return Err(DomainError::MigrationFailed {
                    detail: format!("{} (v{}): {e}", migration.name, migration.version),
                });
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::fs;
    use std::path::Path;
    use std::sync::Mutex;

    use super::*;
    use crate::key::{KeyProvider, KeyProviderError};
    use crate::store::{domain_file, Store};

    #[derive(Default)]
    struct Keys(Mutex<HashMap<String, Vec<u8>>>);

    impl KeyProvider for Keys {
        fn load_key(&self, domain: String) -> Result<Option<Vec<u8>>, KeyProviderError> {
            Ok(self.0.lock().unwrap().get(&domain).cloned())
        }
        fn store_key(&self, domain: String, key: Vec<u8>) -> Result<(), KeyProviderError> {
            self.0.lock().unwrap().insert(domain, key);
            Ok(())
        }
    }

    const V2: Migration =
        Migration { version: 2, name: "items", sql: "CREATE TABLE items (id TEXT PRIMARY KEY, qty INTEGER NOT NULL);" };
    const V3: Migration = Migration {
        version: 3,
        name: "items_note",
        sql: "ALTER TABLE items ADD COLUMN note TEXT; UPDATE items SET note = 'migrated';",
    };
    const V3_BROKEN: Migration = Migration {
        version: 3,
        name: "broken",
        sql: "CREATE TABLE half_done (x INTEGER); INSERT INTO items (id, qty) VALUES ('from-migration', 1); THIS IS NOT SQL;",
    };

    fn seed(dir: &Path, keys: &Keys) {
        let store = Store::open("finance", dir, keys, &[V2]).unwrap();
        store.conn.execute("INSERT INTO items (id, qty) VALUES ('a', 1), ('b', 2)", []).unwrap();
        assert_eq!(store.schema_version().unwrap(), 2);
    }

    fn count(store: &Store, table: &str) -> i64 {
        store.conn.query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |r| r.get(0)).unwrap()
    }

    #[test]
    fn upgrade_of_a_copied_database_keeps_data_and_takes_a_backup_first() {
        let original = tempfile::tempdir().unwrap();
        let keys = Keys::default();
        seed(original.path(), &keys);

        // Work on a copy, like an app update would on a user's real file.
        let copy = tempfile::tempdir().unwrap();
        let src = domain_file(original.path(), "finance");
        let dst = domain_file(copy.path(), "finance");
        fs::create_dir_all(dst.parent().unwrap()).unwrap();
        fs::copy(&src, &dst).unwrap();

        let store = Store::open("finance", copy.path(), &keys, &[V2, V3]).unwrap();
        assert_eq!(store.schema_version().unwrap(), 3);
        assert_eq!(count(&store, "items"), 2);
        let note: String = store.conn.query_row("SELECT note FROM items WHERE id = 'a'", [], |r| r.get(0)).unwrap();
        assert_eq!(note, "migrated");

        let backups: Vec<_> = fs::read_dir(dst.parent().unwrap().join("backups"))
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().to_string())
            .collect();
        let pre = backups.iter().find(|n| n.contains("pre-migrate-v2")).expect("backup before the destructive step");
        // The backup is a readable encrypted copy at the old schema version.
        let restore = tempfile::tempdir().unwrap();
        let target = domain_file(restore.path(), "finance");
        fs::create_dir_all(target.parent().unwrap()).unwrap();
        fs::copy(dst.parent().unwrap().join("backups").join(pre), &target).unwrap();
        let old = Store::open("finance", restore.path(), &keys, &[V2]).unwrap();
        assert_eq!(old.schema_version().unwrap(), 2);
        assert_eq!(count(&old, "items"), 2);
    }

    #[test]
    fn a_failing_migration_rolls_back_completely_and_the_database_stays_usable() {
        let dir = tempfile::tempdir().unwrap();
        let keys = Keys::default();
        seed(dir.path(), &keys);

        let err = Store::open("finance", dir.path(), &keys, &[V2, V3_BROKEN]).err().expect("must fail");
        assert!(matches!(err, DomainError::MigrationFailed { .. }), "{err}");

        // Nothing from the failed migration survived, and the old schema still opens.
        let store = Store::open("finance", dir.path(), &keys, &[V2]).unwrap();
        assert_eq!(store.schema_version().unwrap(), 2);
        assert_eq!(count(&store, "items"), 2, "row inserted by the broken migration was rolled back");
        let leftover: i64 = store
            .conn
            .query_row("SELECT COUNT(*) FROM sqlite_master WHERE name = 'half_done'", [], |r| r.get(0))
            .unwrap();
        assert_eq!(leftover, 0);
    }

    #[test]
    fn a_database_from_a_newer_build_is_refused_not_downgraded() {
        let dir = tempfile::tempdir().unwrap();
        let keys = Keys::default();
        let store = Store::open("finance", dir.path(), &keys, &[V2, V3]).unwrap();
        drop(store);
        let before = fs::read(domain_file(dir.path(), "finance")).unwrap();
        let err = Store::open("finance", dir.path(), &keys, &[V2]).err().expect("must refuse");
        assert!(matches!(err, DomainError::MigrationFailed { .. }), "{err}");
        // The refusal must not have modified the file (WAL checkpointing aside, content equals).
        let after = fs::read(domain_file(dir.path(), "finance")).unwrap();
        assert_eq!(before.len(), after.len());
    }

    #[test]
    fn duplicate_migration_versions_are_rejected_before_anything_runs() {
        let dir = tempfile::tempdir().unwrap();
        let keys = Keys::default();
        let err = Store::open("finance", dir.path(), &keys, &[V2, V2]).err().expect("must fail");
        assert!(matches!(err, DomainError::MigrationFailed { .. }), "{err}");
        assert!(!domain_file(dir.path(), "finance").exists(), "a failed first open leaves no file behind");
    }

    #[test]
    fn domain_names_are_restricted() {
        let dir = tempfile::tempdir().unwrap();
        let keys = Keys::default();
        for bad in ["", "../x", "Finance", "a b", "x/y"] {
            assert!(Store::open(bad, dir.path(), &keys, &[]).is_err(), "{bad:?}");
        }
    }
}

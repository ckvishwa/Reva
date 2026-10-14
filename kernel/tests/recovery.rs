//! AR-DOM-002: wrong key, missing key, corrupt file and fresh install give typed errors
//! and never lose or overwrite data.

mod common;

use std::fs;
use std::sync::Arc;

use common::{cmd, code, domain_file, open, rows, MemKeys};
use reva_kernel::DomainError;
use serde_json::json;
use sha2::{Digest, Sha256};

fn sha(path: &std::path::Path) -> String {
    hex::encode(Sha256::digest(fs::read(path).unwrap()))
}

fn seed(dir: &std::path::Path, keys: &Arc<MemKeys>) -> String {
    let h = open(dir, keys).unwrap();
    cmd(
        &h,
        "account.create",
        json!({"id": "acct-main-1", "name": "Main", "currency": "USD", "opening_balance_minor": 1000}),
    );
    for i in 0..5 {
        cmd(
            &h,
            "transaction.create",
            json!({"id": format!("tx-seed-{i:03}"), "account_id": "acct-main-1", "date": "2026-10-01", "amount_minor": -(100 + i), "description": format!("seed {i}")}),
        );
    }
    h.projection_digest().unwrap()
}

#[test]
fn fresh_install_generates_and_stores_a_key_then_creates_an_encrypted_file() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    assert!(keys.get("finance").is_none());
    let h = open(dir.path(), &keys).unwrap();
    let key = keys.get("finance").expect("a key must have been stored");
    assert_eq!(key.len(), 32);
    assert_eq!(*keys.store_calls.lock().unwrap(), 1);
    assert_eq!(h.schema_version().unwrap(), 3);
    let bytes = fs::read(domain_file(dir.path())).unwrap();
    assert_ne!(&bytes[..16], b"SQLite format 3\0", "the file must not be plaintext SQLite");
    assert!(!h.device_id().is_empty());
}

#[test]
fn fresh_install_does_not_create_a_file_if_the_key_cannot_be_stored() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    *keys.fail_store.lock().unwrap() = true;
    let err = open(dir.path(), &keys).err().expect("must fail");
    assert!(matches!(err, DomainError::Locked), "{err}");
    assert!(!domain_file(dir.path()).exists(), "no data file without a stored key");
}

#[test]
fn missing_key_for_an_existing_file_is_locked_and_never_invents_a_key() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let digest = seed(dir.path(), &keys);
    let file = domain_file(dir.path());
    let before = sha(&file);
    let saved = keys.get("finance").unwrap();

    keys.remove("finance");
    let calls = *keys.store_calls.lock().unwrap();
    let err = open(dir.path(), &keys).err().expect("must fail");
    assert!(matches!(err, DomainError::Locked), "{err}");
    assert_eq!(*keys.store_calls.lock().unwrap(), calls, "no replacement key may be generated");
    assert_eq!(sha(&file), before, "file must be untouched");

    keys.put("finance", saved);
    assert_eq!(open(dir.path(), &keys).unwrap().projection_digest().unwrap(), digest, "no data loss");
}

#[test]
fn vault_failure_is_locked() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    seed(dir.path(), &keys);
    *keys.fail_load.lock().unwrap() = true;
    assert!(matches!(open(dir.path(), &keys).err().unwrap(), DomainError::Locked));
}

#[test]
fn wrong_key_is_reported_and_the_file_is_untouched() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let digest = seed(dir.path(), &keys);
    let file = domain_file(dir.path());
    let before = sha(&file);
    let good = keys.get("finance").unwrap();

    keys.put("finance", vec![7_u8; 32]);
    let err = open(dir.path(), &keys).err().expect("must fail");
    assert!(matches!(err, DomainError::WrongKey), "{err}");
    assert_eq!(sha(&file), before);

    keys.put("finance", vec![1_u8; 5]);
    assert!(matches!(open(dir.path(), &keys).err().unwrap(), DomainError::WrongKey), "short key");

    keys.put("finance", good);
    assert_eq!(open(dir.path(), &keys).unwrap().projection_digest().unwrap(), digest);
}

#[test]
fn wrong_key_is_detected_even_without_the_key_check_sidecar() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    seed(dir.path(), &keys);
    let mut sidecar = domain_file(dir.path()).into_os_string();
    sidecar.push(".kcv");
    fs::remove_file(&sidecar).unwrap();
    let good = keys.get("finance").unwrap();
    keys.put("finance", vec![9_u8; 32]);
    let err = open(dir.path(), &keys).err().unwrap();
    assert!(matches!(err, DomainError::WrongKey), "{err}");
    keys.put("finance", good);
    open(dir.path(), &keys).expect("opens again with the right key and rewrites the sidecar");
    assert!(std::path::Path::new(&sidecar).exists());
}

#[test]
fn truncated_file_is_corrupt_and_left_alone() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    seed(dir.path(), &keys);
    let file = domain_file(dir.path());
    // Make sure everything is in the main file, then cut it.
    let bytes = fs::read(&file).unwrap();
    let cut = &bytes[..bytes.len().min(5000)];
    fs::write(&file, cut).unwrap();
    for suffix in ["-wal", "-shm"] {
        let mut p = file.clone().into_os_string();
        p.push(suffix);
        let _ = fs::remove_file(p);
    }
    let before = sha(&file);
    let err = open(dir.path(), &keys).err().expect("must fail");
    assert!(matches!(err, DomainError::Corrupt), "{err}");
    assert_eq!(sha(&file), before, "a corrupt file is never rewritten");
}

#[test]
fn damaged_header_with_the_right_key_is_corrupt() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    seed(dir.path(), &keys);
    let file = domain_file(dir.path());
    let mut bytes = fs::read(&file).unwrap();
    for b in &mut bytes[..64] {
        *b ^= 0xFF;
    }
    fs::write(&file, &bytes).unwrap();
    let err = open(dir.path(), &keys).err().expect("must fail");
    assert!(matches!(err, DomainError::Corrupt), "{err}");
    assert_eq!(fs::read(&file).unwrap(), bytes);
}

#[test]
fn empty_and_plaintext_files_are_corrupt_and_never_opened_as_databases() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    keys.put("finance", vec![3_u8; 32]);
    let file = domain_file(dir.path());
    fs::create_dir_all(file.parent().unwrap()).unwrap();

    fs::write(&file, b"").unwrap();
    assert!(matches!(open(dir.path(), &keys).err().unwrap(), DomainError::Corrupt));

    // A plaintext SQLite database must never be adopted (or modified) as a REVA domain file.
    let plain = rusqlite::Connection::open(&file).unwrap();
    drop(fs::remove_file(&file));
    drop(plain);
    let plain = rusqlite::Connection::open(&file).unwrap();
    plain.execute_batch("CREATE TABLE secrets (v TEXT); INSERT INTO secrets VALUES ('x');").unwrap();
    drop(plain);
    let before = sha(&file);
    assert!(matches!(open(dir.path(), &keys).err().unwrap(), DomainError::Corrupt));
    assert_eq!(sha(&file), before);
}

#[test]
fn backup_opens_with_the_same_key_and_restores_after_corruption() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let digest = seed(dir.path(), &keys);
    let h = open(dir.path(), &keys).unwrap();
    let backup = std::path::PathBuf::from(h.backup().unwrap());
    assert!(backup.exists());
    cmd(
        &h,
        "transaction.create",
        json!({"id": "tx-after-bk", "account_id": "acct-main-1", "date": "2026-10-02", "amount_minor": -1, "description": "after backup"}),
    );
    drop(h);

    // Corrupt the live file, then restore the backup in its place.
    let file = domain_file(dir.path());
    fs::write(&file, vec![0_u8; 8192]).unwrap();
    assert!(matches!(open(dir.path(), &keys).err().unwrap(), DomainError::Corrupt));
    for suffix in ["-wal", "-shm"] {
        let mut p = file.clone().into_os_string();
        p.push(suffix);
        let _ = fs::remove_file(p);
    }
    fs::copy(&backup, &file).unwrap();
    let restored = open(dir.path(), &keys).expect("backup opens with the same key");
    assert_eq!(restored.projection_digest().unwrap(), digest, "backup state equals state at backup time");
    assert_eq!(rows(&restored, "list_transactions", json!({"limit": 100})).len(), 5);
}

#[test]
fn failed_opens_never_change_the_data() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let digest = seed(dir.path(), &keys);
    let good = keys.get("finance").unwrap();
    let file = domain_file(dir.path());
    let before = sha(&file);
    for attempt in 0..5_u8 {
        keys.put("finance", vec![attempt; 32]);
        assert!(open(dir.path(), &keys).is_err());
    }
    assert_eq!(sha(&file), before);
    keys.put("finance", good);
    assert_eq!(open(dir.path(), &keys).unwrap().projection_digest().unwrap(), digest);
}

#[test]
fn concurrent_writers_do_not_lose_events() {
    let dir = tempfile::tempdir().unwrap();
    let keys = MemKeys::new();
    let h = open(dir.path(), &keys).unwrap();
    cmd(&h, "account.create", json!({"id": "acct-main-1", "name": "Main", "currency": "USD"}));
    let threads: Vec<_> = (0..4)
        .map(|t| {
            let h = h.clone();
            std::thread::spawn(move || {
                for i in 0..25 {
                    h.command(
                        "transaction.create".to_string(),
                        json!({"id": format!("tx-t{t}-{i:03}"), "account_id": "acct-main-1", "date": "2026-10-03", "amount_minor": -(i + 1), "description": "concurrent"}).to_string(),
                    )
                    .unwrap();
                }
            })
        })
        .collect();
    for t in threads {
        t.join().unwrap();
    }
    assert_eq!(h.event_count().unwrap(), 101);
    let live = h.projection_digest().unwrap();
    h.rebuild_projections().unwrap();
    assert_eq!(h.projection_digest().unwrap(), live);
}

#[test]
fn error_codes_are_stable_strings() {
    assert_eq!(code(&DomainError::Locked), "locked");
    assert_eq!(code(&DomainError::WrongKey), "wrong_key");
    assert_eq!(code(&DomainError::Corrupt), "corrupt");
}

# INT-1 — review of the Finance track (FIN-1, FIN-2, AND-1, SYNC-1a)

Date: 2026-10-12 · Reviewer: Claude (code-review and security-review checklists, applied by hand to each branch's diff against its base) · Branches: `feat/fin-1-kernel`, `feat/fin-2-finance-ui`, `feat/and-1-android`, `feat/sync-1-sync`.

Scope of the security pass: new routes and auth, `REVA_DOMAIN_KEYSTORE=memory`, Credential Manager and Keystore key handling, import parsers and export, Kernel signature verification, Android manifest permissions and backup rules.

## Fixed (each in its own commit on the owning branch)

| ID | Branch | Severity | Finding | Fix |
|---|---|---|---|---|
| INT-1-F1 | fin-1 | Medium | CSV export prefixed formula characters in only five text columns; `id`, `account_id`, `currency` were not covered, and tab / CR were not in the list. | Every text column except date and the two numeric amounts is guarded; tab and CR added. Test: `csv_export_neutralises_every_text_column`. |
| INT-1-F2 | fin-2 | Medium | `REVA_DOMAIN_KEYSTORE=memory` was checked only in `load_settings`. Code that built `Settings` directly, or a packaged build with the variable set, could use throw-away keys. | `ensure_memory_keystore_allowed` is called where the provider is built (`default_key_provider(keystore, data_dir)`) and in `load_settings`. It refuses frozen (release) builds and any data directory outside the OS temp directory (the temp root itself and `..` escapes included). 7 new tests. |
| INT-1-F3 | and-1 | Medium | The plain Finance export stayed in the app cache until the next export. | `ExportShare.clear` runs at every app start. Unit test. |
| INT-1-F4 | and-1 | Low | StrongBox fallback caught only `StrongBoxUnavailableException`; some phones throw `ProviderException`, which would make first run fail. | Both fall back to a software-backed Keystore key. |
| INT-1-F5 | sync-1 | High (integration) | Removing the unauthenticated `apply_events` from the bindings broke FIN-2's conflict test and the fixture generator (found by running the whole Python suite on the merged tree). | Both pair two Kernels and sync through the signed API (`tools/kernel/paired_devices.py`). |
| INT-1-F6 | and-1 | Low | `tools/android/build_apk.py` failed `ruff check` / `ruff format --check`. | Fixed. |

## Checked and fine

- Every `/v1/domains/*` and `/v1/today` route depends on the bearer-token dependency; unknown domains, collections and reports return 404 before any Kernel call. Import is capped at 8 MB decoded (12 MB base64) and the Kernel re-checks 8 MB / 50,000 rows.
- The Credential Manager provider only touches `reva.domain.*`, refuses `com.aura` names, never replaces an existing key, and under pytest the default provider is unavailable so tests cannot reach the real vault.
- Import parsers: CSV, OFX (hand-written scanner, no XML entity expansion, no network) and JSON (serde recursion limit) are bounded; ids are restricted to `[A-Za-z0-9_-]{8,64}`.
- Kernel sync verification: a batch is rejected as a whole for unsigned, tampered, wrong-key, spoofed-origin, unknown, revoked or out-of-scope events; mutation checks (verification removed, tombstone guard removed) make the tests fail.
- Android manifest: no permissions, no `QUERY_ALL_PACKAGES`, no accessibility service; the merged-manifest test runs on every build; the FileProvider is not exported and shares only `cache/exports/`; backup and data-extraction rules exclude the key and domain files.

## Not fixed, on purpose

| ID | Item | Why |
|---|---|---|
| INT-1-N1 | The Android wrapped-key blob is not bound to the domain with AES-GCM associated data. | Only one domain exists; binding it now would change the blob format of any install made from the AND-1 APK. Revisit when a second domain arrives. |
| INT-1-N2 | Keystore key does not require an unlocked device (`setUnlockedDeviceRequired`). | Background sync while the phone is locked is a stated goal. Revisit with the sync client. |
| INT-1-N3 | Key bytes are held in ordinary Python / JVM memory while the Kernel is open. | Not preventable from managed languages; the Kernel zeroizes its own copy. |
| INT-1-N4 | Hub forwarding: a phone that does not know a third device rejects a forwarded batch, which blocks that phone until it is paired with the third device. | Only reachable with two phones. Needs a pairing-time decision (S13). |
| INT-1-N5 | `allowBackup="true"` with explicit exclusion rules instead of `false`. | The rules exclude everything the app stores; a test pins them. `false` would add nothing. |
| INT-1-N6 | The per-domain `sync` privacy switch is stored but nothing reads it yet. | The transport (pairing gateway, S13) does not exist yet. It must read it on send and receive. |
| INT-1-N7 | CI `kernel` and `android` lanes have never run on GitHub. | Reported separately after the push. |

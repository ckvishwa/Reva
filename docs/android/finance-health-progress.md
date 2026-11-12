# Android Finance and Health progress

Updated 2026-10-19. Work is isolated in `D:\Projects\Reva-finance-health` on `feat/android-daily-finance-health`; the original `D:\Projects\Reva` checkout is untouched. Base: `origin/main` `df7a3dc2451243713e9f02362141e54e1e8087fb`.

Draft PR: https://github.com/ckvishwa/Reva/pull/37. **It stays draft**: the code scope is implemented and CI is green, but physical-device acceptance (Health Connect, permissions, voice, pairing, interruption) has not been run because no Android device was attached. Do not merge or tag on build evidence alone.

## Verdict

- Code scope in this file: implemented and tested on JVM, Rust and Python.
- Release candidate: a **debug-signed preview APK** from source `77f10e4065456a459f6d7af3de538d1a6b88ecb8`. It is not production-signed and not hardware-accepted.
- Ready to merge: **no**, until the owner checklist below passes on a real phone.

## Implemented on this branch

- Finance Today: exact daily totals by currency with Kernel source IDs; categories, budgets, bill/recurring reminders; mark-paid records a ledger fact and moves no money. Offline Finance period questions use Kernel totals.
- **Finance reports (new):** Kernel `recurring_summary` (exact yearly totals per currency from weekly ×52, biweekly ×26, monthly ×12, quarterly ×4, yearly ×1; one-off bills excluded; inactive bills drop out; due-in-30-days totals) and `networth_report` (live net worth from balances plus each snapshot's change from the previous one). Android Finance shows a recurring card and "Now, from current balances" with the last three snapshot changes. The stale footer "there is no internet permission" was corrected (INTERNET exists for the paired PC only).
- **Fresh-install restore:** a Finance JSON backup restored into a fresh install gives identical digests and identical `recurring_summary`, `networth_report`, `cashflow`, `spend_by_category`, `account_balances`, `upcoming_bills` and `budget_status` (`kernel/tests/finance_reports.rs`).
- Health domain: encrypted manual workouts, sleep, meals, weight, steps, heart-rate readings, medication schedules and taken events; daily and seven-day summaries; urgent phrases get a fixed safety reply.
- **Health provenance and backup (new):** records carry `source` (`manual` or `health_connect`) and `origins`. `import_data("json")` restores a `reva-health-v1` backup with every row accepted, duplicate or rejected with a reason; deleted (tombstoned) records are never restored; schedules restore before taken entries. Android Health has "Share a Health backup" (unencrypted-file warning first) and "Restore from a backup file" (dry run, counts, then confirm).
- **Health Connect, read only (new):** steps and heart-rate daily aggregates, one READ permission per type, rationale screen (+ system-only Android 14 alias), grants rechecked on resume, after the permission sheet and before every import, mid-read revocation reported, last 30 days only, no write/history/background permission. One deterministic record per day and type, so repeated imports are duplicates or updates and steps are never double-counted; a deleted day is never re-imported; "Delete everything copied from Health Connect" (`source.delete`). Same-day manual vs Health Connect steps: totals use the manual entry, both values are shown as a conflict on the Health screen, in the weekly card and in the weekly voice answer. Design and security notes: `docs/android/health-connect.md`.
- **More screen:** Health is listed as "on its own tab", no longer "coming soon".

## Verification (local, Windows 11, 2026-10-19)

- Rust Kernel: `cargo test -p reva-kernel` 112 passed, 0 failed, 1 ignored (pre-existing perf test). New: `health_import.rs` 8, `finance_reports.rs` 4. `cargo fmt --all -- --check` and `cargo clippy --workspace --all-targets -- -D warnings` clean.
- Android JVM: `:app:testDebugUnitTest` 346 passed, 0 failed, 0 skipped (was 329). New: `SensitiveEgressTest` 4, `HealthConnectImporterTest` 5, `FinanceReportsTest` 3, `HealthJsonTest` +2, `ManifestTest` +2, `LocalBrainTest` +1. `:app:lintDebug` and `:app:compileDebugAndroidTestKotlin` passed. Instrumented tests (including the new Health Connect Compose test) were compiled, **not run**: no device.
- Kotlin JVM Kernel conformance: 97 steps passed, host checks passed.
- Python: full `python -m pytest -q` 1705 passed, 20 skipped. Cross-binding 9 passed (new Health backup/Health Connect test through the Python binding). `python tools/ci/check_contracts.py`: 9 schemas, 0 problems. `ruff check`/`ruff format --check` clean on the edited test file.
- Safety/egress tests: Health and Finance questions, dosing, diagnosis, urgent and money-movement phrases never reach a planner (recording planner stays empty); Health/Health Connect/Finance report code has no network, PC-request or WebView use; Health is not in any sync scope; Kernel Health commands and summaries contain no diagnosis/dosing/rating vocabulary and reject `dose`/`frequency` fields.
- Dependencies: `androidx.health.connect:connect-client:1.1.0` (Apache-2.0); Guava `31.1-android` declared for compilation because Health Connect's runtime Guava replaces CameraX's ListenableFuture artifact with an empty stub (first build failed in `QrScanner.kt` with "Cannot access class ListenableFuture" until this was declared). The library's exported `HealthDataSdkService` checks the caller is `com.google.android.apps.healthdata`; it is named in `ManifestTest`'s exported-component allowlist.

## CI (PR #37)

- Run `39297297472` on `d4c2e13`: csharp-desktop, contracts, android, android-unit, python, kernel, avatar all success.
- Run `39301658722` on `77f10e4` (the APK source): csharp-desktop, contracts, android, android-unit, python, kernel, avatar all success. Claude Code Review run `39301658778`: success, no review comments posted.
- The docs-only commit after `77f10e4` (this file, ledger, coverage, CLAUDE.md) changes no APK input; its own CI run is listed on the PR.

## APK (debug-signed preview, not a production release)

- Source SHA: `77f10e4065456a459f6d7af3de538d1a6b88ecb8`, clean tree. Native build `python tools/kernel/build_android.py`: arm64-v8a 8,526,440 bytes and x86_64 8,638,080 bytes, both export `open_domain`, OpenSSL linked statically. Then `python tools/android/build_apk.py` (first attempt failed only because a running pytest held `reva_kernel.dll` open; re-run after the suite finished passed).
- Path: `D:\Projects\Reva-finance-health\android\app\build\outputs\apk\debug\app-debug.apk`, 60,204,553 bytes, SHA-256 `86ad3fdff0dcfffbfbe48ecf4a5087eeb0a54488a7ef73f42fb261410cb55ea3`.
- Checks: ZIP integrity OK; `lib/arm64-v8a` and `lib/x86_64` `libreva_kernel.so` stored uncompressed; `zipalign -c -P 16 4` OK; avatar `index.html`/`placeholder.vrm` and `capability-registry.v2.json` present. `apksigner verify`: one signer, v2 only, `CN=Android Debug` (debug key). `aapt2 dump badging`: `app.reva.android`, versionCode 1, versionName 0.1.0, compile/target SDK 36, debuggable, permissions exactly INTERNET, CAMERA, RECORD_AUDIO, FOREGROUND_SERVICE, FOREGROUND_SERVICE_MICROPHONE, health.READ_STEPS, health.READ_HEART_RATE and the AndroidX internal receiver permission.
- `D:\reva-releases\v2.0.0-alpha.12` does not exist, so nothing was staged. The older preview from `8785585` (SHA-256 `fc92c0c6…b40d`) is superseded.

## NEEDS_HARDWARE: owner checklist (in order)

`adb devices -l` showed no device. Nothing below has been observed. Use an Android 14+ phone with Health Connect and at least one app writing steps and heart rate; turn on airplane mode only where noted.

1. `adb install -r "D:\Projects\Reva-finance-health\android\app\build\outputs\apk\debug\app-debug.apk"`; confirm `sha256sum` of the file first matches `86ad3fdf…5ea3`.
2. Open REVA. More: Health shows "on its own tab"; no section says Health is coming soon.
3. Health tab, Health Connect card: "Allow steps" opens the system sheet for steps only. Tap the rationale link in that sheet: REVA's "How REVA uses Health Connect" screen opens. Allow steps only.
4. Card shows "Steps: allowed", "Heart rate: not allowed". Tap "Copy the last 30 days": result names steps only. Compare today's steps with the Health Connect app's own total for today (must match, not exceed).
5. Tap "Copy the last 30 days" again: "0 new … unchanged" (or "updated" only for today if you walked). Weekly steps total does not grow.
6. Log a manual steps entry for today with a different number: the conflict message shows both values; weekly card lists today; ask by voice "show my health this week" and hear the conflict sentence.
7. In Health Connect settings revoke steps, return to REVA: card shows "not allowed" and the "Access was turned off" note; import reads nothing.
8. "Delete everything copied from Health Connect" → confirm; Health Connect days disappear, manual entries remain; re-grant and import: deleted days are reported skipped.
9. Health backup: share to Files, delete one entry, restore the file: preview shows the deleted entry as not restorable; restore adds nothing deleted.
10. Finance: add a monthly bill and a weekly subscription; recurring card yearly totals equal amount×12 and amount×52. Take a snapshot; "Now, from current balances" matches the account cards. Export Finance JSON, uninstall, reinstall, restore: same totals.
11. Voice: mic button opens the mic indicator only after tap; "how did I sleep this week" answers from local data; "how many mg of ibuprofen should I take" is refused with no number.
12. Pairing: pair with the PC, sync Finance; confirm Health does not appear on the PC.
13. Interruption: during a Health Connect import and during voice, switch apps / lock screen / take a call; app returns without a crash and without claiming an import that did not finish.
14. Airplane mode: Health, Finance and voice weekly answers still work; record any battery or thermal observation only if you measured it.

## Not done / risks

- Physical acceptance above (Health Connect permission UI, voice, pairing, interruption, battery/thermal) is NEEDS_HARDWARE.
- Instrumented Compose tests compiled only.
- Health Connect reads cover steps and heart rate only (no sleep/exercise sessions: their cross-app de-duplication is not provided by aggregation the same way).
- A Health Connect day the user deleted can never be re-imported (conservative privacy choice, documented).
- APK is debug-signed. Production signing (F2) is out of scope. No Phase D or cloud work was started.

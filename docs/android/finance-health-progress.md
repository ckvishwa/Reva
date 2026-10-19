# Android Finance and Health recovery checkpoint

Updated 2026-10-19. Work is isolated in `D:\Projects\Reva-finance-health` on `feat/android-daily-finance-health`; the original `D:\Projects\Reva` checkout is untouched. Base: `origin/main` `df7a3dc2451243713e9f02362141e54e1e8087fb`. Feature commits: `d53dc86`, `31d5a4e`, `b2b1ec9`, `ea8b9cc`, `774e814`.

## Implemented on this branch

- Finance Today shows exact daily totals by currency with Kernel source IDs. The Finance screen can create categories, budgets and bill/recurring reminders, and mark a bill paid after explicit confirmation. The mark-paid flow records a ledger fact; it does not transfer money.
- Offline Finance period questions use Kernel totals and source records.
- A separate encrypted Health Kernel domain stores manual workouts, sleep, meals, weight, medication schedules and taken events. It supports daily records/summary, deletion, projection replay and JSON export.
- Android Health forms and Today summary use local Kernel calls. Urgent Health phrases receive a fixed safety response before the planner/network path.

## Verification so far

- Android debug unit suite: 325 passed, 0 failed, 0 skipped. `lintDebug` and `compileDebugAndroidTestKotlin` passed; instrumented UI tests were compiled but not run because `adb devices -l` showed no device.
- Rust tests passed, including three Health tests; one pre-existing performance test ignored. Strict Clippy and `cargo fmt --check` passed.
- The Android Kernel cross-build passed for arm64-v8a and x86_64 with architecture, UniFFI symbol and static-OpenSSL checks. The first attempt failed while OpenSSL invoked a Windows backslash compiler path through Git's Unix shell; `tools/kernel/build_android.py` now invokes Cargo directly per target on Windows with NDK tools on `PATH`.
- `python tools/android/build_apk.py --skip-kernel` passed. Preview debug APK: `D:\Projects\Reva-finance-health\android\app\build\outputs\apk\debug\app-debug.apk` (54,546,413 bytes), SHA-256 `3a5289c68526ab06e81f6e0794eecbd1a1b875e7ce3b40abee667bf9f77b7dc7`. ZIP inspection found both `libreva_kernel.so` ABIs, `assets/avatar/index.html` and `assets/avatar/placeholder.vrm`. Build source SHA before the build-script fix: `774e814d1830e005a9ec272d96f20995ad91f16a`. The fix changes only build orchestration, not the compiled app sources. `D:\reva-releases\v2.0.0-alpha.12` does not exist, so nothing was staged. No device was attached to `adb`; this is not hardware acceptance or a finished release.

## Still required for full Finance and Health APK scope

- Health steps and heart-rate inputs, weekly summary/trends/adherence, and safe data-backed question answering.
- Health Connect read-only import with per-type permission requests, rationale, grant recheck and revocation behavior. No Health Connect writes.
- Health export/import roundtrip, duplicate handling, file UI and deletion/privacy verification.
- Finish Finance recurring and net-worth UI/reporting plus import/export flows and confirm totals across a fresh install.
- Health safety and Finance accuracy evaluations, sensitive-domain egress tests, a verified APK, and physical Android UI/voice checks. No medical diagnosis, dosing/treatment advice, payment execution or bank login capability.

## Next action

Implement the remaining Kernel/Android features, then rebuild the Kernel and APK from the final commit, run all relevant CI and on-device acceptance, and record fresh hashes. Do not label this preview a finished release.

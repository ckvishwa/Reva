# Android Finance and Health recovery checkpoint

Updated 2026-10-19. Work is isolated in `D:\Projects\Reva-finance-health` on `feat/android-daily-finance-health`; the original `D:\Projects\Reva` checkout is untouched. Base: `origin/main` `df7a3dc2451243713e9f02362141e54e1e8087fb`. Feature commits: `d53dc86`, `31d5a4e`, `b2b1ec9`, `ea8b9cc`, `774e814`.

Draft PR: https://github.com/ckvishwa/Reva/pull/37. It remains draft until full-scope checks and hardware evidence are complete; do not merge on the preview APK evidence alone.
Latest code head before this documentation update: `8785585bb8011c4f1a70f69825c0b3e6610e8bc7`. CI run `39199570772` is pending for that head; read its final result before relying on it. C3b/C3c PRs #31/#32 are separate drafts and have not been merged into this base.

## Implemented on this branch

- Finance Today shows exact daily totals by currency with Kernel source IDs. The Finance screen can create categories, budgets and bill/recurring reminders, and mark a bill paid after explicit confirmation. The mark-paid flow records a ledger fact; it does not transfer money.
- Offline Finance period questions use Kernel totals and source records.
- A separate encrypted Health Kernel domain stores manual workouts, sleep, meals, weight, medication schedules and taken events. It supports daily records/summary, deletion, projection replay and JSON export.
- Android Health forms and Today summary use local Kernel calls. Urgent Health phrases receive a fixed safety response before the planner/network path.
- A seven-day Health summary ending on the selected date uses only local Kernel records. Android shows sleep/workout/meal and medication adherence counts with source-record count. The shared Python/Android rule path maps explicit weekly Health questions to the read-only `health.weekly` capability; Android answers from the Kernel without calling a hosted planner.
- Manual steps per day and heart-rate samples are available in Android. The Kernel bounds inputs, reports recorded counts/ranges without interpretation, and rejects a second local steps entry for the same date.

## Verification so far

- Android debug unit suite: 325 passed, 0 failed, 0 skipped. `lintDebug` and `compileDebugAndroidTestKotlin` passed; instrumented UI tests were compiled but not run because `adb devices -l` showed no device.
- Rust tests passed, including three Health tests; one pre-existing performance test ignored. Strict Clippy and `cargo fmt --check` passed.
- After the weekly slice: Android unit suite 328 passed, 0 failed, 0 skipped; Android instrumented-test compilation passed. Rust Health tests 4 passed, full Rust suite and strict Clippy passed. Python language-rule tests 75 passed and policy fixture checks 2 passed. Physical UI tests remain pending.
- After the steps/heart-rate slice: Android unit suite 329 passed, 0 failed, 0 skipped; Android lint and instrumented-test compilation passed. Rust Health tests 5 passed; full Rust suite, strict Clippy and fmt passed (one pre-existing ignored performance test). CI on PR #37 must be rebound to the new head after push.
- The Android Kernel cross-build passed for arm64-v8a and x86_64 with architecture, UniFFI symbol and static-OpenSSL checks. The first attempt failed while OpenSSL invoked a Windows backslash compiler path through Git's Unix shell; `tools/kernel/build_android.py` now invokes Cargo directly per target on Windows with NDK tools on `PATH`.
- `python tools/android/build_apk.py` passed again at source SHA `8785585bb8011c4f1a70f69825c0b3e6610e8bc7`. Current preview debug APK: `D:\Projects\Reva-finance-health\android\app\build\outputs\apk\debug\app-debug.apk` (62,222,947 bytes), SHA-256 `fc92c0c6f8dfbde70abd1ab9788079d5639c47999dfad37db4ad7397e583b40d`. ZIP integrity passed; inspection found both `libreva_kernel.so` ABIs, `assets/avatar/index.html` and `assets/avatar/placeholder.vrm`. `apksigner verify` passed with one debug signer using APK Signature Scheme v2. `D:\reva-releases\v2.0.0-alpha.12` does not exist, so nothing was staged. No device was attached to `adb`; this is not hardware acceptance or a finished release.

## Still required for full Finance and Health APK scope

- Health Connect import, richer trends across periods, and broader safe data-backed question answering. Manual steps/heart-rate and a factual seven-day summary with medication adherence counts are implemented. Cross-device same-day steps conflicts still need explicit UI treatment.
- Health Connect read-only import with per-type permission requests, rationale, grant recheck and revocation behavior. No Health Connect writes.
- Google recommends Health Connect aggregation for cumulative steps to avoid double-counting; an import path must store provenance and handle repeated reads and same-day conflicts before the permission UI is exposed. Official guidance: https://developer.android.com/health-and-fitness/health-connect/read-data and https://developer.android.com/health-and-fitness/health-connect/ui/permissions.
- Health export/import roundtrip, duplicate handling, file UI and deletion/privacy verification.
- Finish Finance recurring and net-worth UI/reporting plus import/export flows and confirm totals across a fresh install.
- Health safety and Finance accuracy evaluations, sensitive-domain egress tests, a verified APK, and physical Android UI/voice checks. No medical diagnosis, dosing/treatment advice, payment execution or bank login capability.

## Next action

From `D:\Projects\Reva-finance-health` on `feat/android-daily-finance-health`: inspect `gh pr checks 37 --repo ckvishwa/Reva`, implement Health import/provenance before Health Connect permissions, finish Finance/Health UI and safety/privacy checks, then rebuild the Kernel and APK from the final code commit, run all relevant CI and on-device acceptance, and record fresh hashes. Owner action is needed for physical Android tests and any personally configured hosted-provider key. Do not label this preview a finished release.

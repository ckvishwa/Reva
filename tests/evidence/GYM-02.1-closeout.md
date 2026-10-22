# GYM-02.1 Android Share/Restore closeout (2026-10-22)

Implementation starts at `fd26d25`. The permission-gate test correction is `f430161`; the E2E navigation repair is `5857f70`. The complete emulator run and its selected screenshots are in [gym021](gym021/summary.json). All 18 screenshots and the console logs also remain locally under `scratchpad/gym021-e2e/` and `scratchpad/gym021-e2e-run.log`.

## Driver failure and repair

The original driver completed 37 checks, then aborted with `could not scroll to the workout in Recent workouts` ([baseline summary](../../scratchpad/gym021-e2e-baseline/summary.json), local artifact; never counted as PASS). Its failure screenshot showed Session Details with **Back to Gym** visible. Selecting the already selected Gym tab had retained that nested screen. The repair taps **Back to Gym** before locating the workout, then requires exactly one Recent workouts row. The final full driver exited 0: 39 passed, 0 failed, no abort, 18 screenshots. It starts by clearing only the isolated emulator app data.

## Share-sheet permissions

[Final logcat excerpt](gym021/share-denials.log) records six denials from `com.android.intentresolver` (PID 15200, UID 10112) while the system share sheet inspected the private `androidx.core.content.FileProvider`; one additional denial is the driver's `content read` shell probe (UID 2000). The earlier four messages were not saved as a separate log artifact, but the reproduced messages identify the same resolver process and provider. The log does not print a URI path or backup bytes. The driver requested `content://app.reva.android.exports/exports/reva-health-2026-10-22.json` in its shell probe, which was denied. The selected test receiver (`app.reva.android.test`) logged `OK 17905 bytes ... from app.reva.android.exports` after Android delivered the one-time grant, and the file was saved to Downloads by that authorized receiver. No unauthorized read or disclosure was observed. The provider stays `android:exported="false"` with `android:grantUriPermissions="true"`; the sender uses `FLAG_GRANT_READ_URI_PERMISSION`. The test receiver exists only in the androidTest APK, not the main APK. No application security change is required.

## Restore checks

- The UI fixture was one edited program (v2), one historical session (v1), and three Lat Pulldown working sets at 55 lb × 10, 9, 8. The receipt before and after restore matched, including the 1,485 lb volume, pause, and notes.
- After `pm clear`, the new encrypted store had no plan. UI preview showed 5 new records, and the result appeared only after confirming the Kernel commit. Repeat preview showed 0 new and 5 existing, with confirmation disabled.
- Cancelled picker, malformed JSON, unsupported format, and a tampered set did not alter the final receipt. The tampered preview showed 0 new, 4 existing, and 1 rejected. The instrumented permission test also verified unreadable document URIs leave the projection digest unchanged.
- `restoring_onto_a_device_with_its_own_plan_never_leaves_two_active_plans` verified the incoming plan row is rejected and the device's active plan is unchanged. Valid historical session and set rows still import, by design; this is record-level conflict handling, not an all-or-nothing backup rejection. Repeat import leaves the projection digest unchanged.
- `the_twelve_imported_rows_are_ten_records_and_two_deletions_and_say_so` verified 11 Gym entries plus 1 Health record. The 12 imported entries comprise 10 records and 2 Gym tombstones. UI and Kernel report deletion entries separately. The instrumented UI test verified preview/confirm/result visibility, stale-result clearing, and one restore while confirmation is tapped repeatedly.

## Current verification

| Command | Result |
| --- | --- |
| `cargo test --test gym_backup --test health_import --test gym` | 8 + 8 + 20 passed; 0 failed |
| `D:/Projects/Reva/.venv/Scripts/python.exe -m pytest tests/cross_binding -q` | 9 passed |
| `./gradlew :app:testDebugUnitTest --console=plain` | 372 passed; 0 failed or skipped |
| `./gradlew :app:connectedDebugAndroidTest --project-prop=reva.uiTests=true --console=plain` | 49 tests: 47 passed, 2 opt-in skipped, 0 failed on Android 16/API 36 x86_64 (`reva_api36`) |
| `./gradlew :app:lintDebug --console=plain` | 0 errors, 33 warnings |
| `python tools/android/gym_backup_e2e.py --serial emulator-5554 --out scratchpad/gym021-e2e --app-apk android/app/build/outputs/apk/debug/app-debug.apk --test-apk android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk` | 39 checks passed, 0 failed, no abort |

The first full instrumented run failed a stale `KernelConformanceTest` expected-permission list, which omitted the two Health Connect read permissions already declared by the current manifest. The test-only correction in `f430161` added those exact permissions; the rerun above passed. The skipped tests were Screenshot Tour and the opt-in Sync E2E. An initial cross-binding call used an unrelated Python environment without `cryptography`; the repository environment passed. These failed setup/baseline runs are not represented as PASS.

## APK and native identity

`python tools/android/build_apk.py --skip-avatar` rebuilt Kotlin bindings and `libreva_kernel.so` for `arm64-v8a` and `x86_64`. Gradle initially treated the package as up to date, so `./gradlew :app:assembleDebug --rerun-tasks --console=plain` forced fresh packaging; the instrumented build then repackaged the final main APK. [Native verification](gym021/apk-kernel-verification.json) used `python tools/android/verify_apk_kernel.py --apk android/app/build/outputs/apk/debug/app-debug.apk --expect-string 'this device already has a training plan'` and passed for both ABIs, including code fingerprints and source freshness. `apksigner verify --print-certs` showed `CN=Android Debug`. AAPT showed the reviewed permissions, private export provider, and no test receiver in the main APK.

Final APK: `android/app/build/outputs/apk/debug/app-debug.apk`, **54,281,707 bytes**, SHA-256 **`a6ec92cad2316e41b8c983a212922e87d22e2aa86c3f75d2f76646de41fb979c`**. The driver installed this path; the emulator's installed `base.apk` was pulled after the run and had the identical SHA-256. This is debug signed, not production signed. Physical-device acceptance remains `NEEDS_HARDWARE`.

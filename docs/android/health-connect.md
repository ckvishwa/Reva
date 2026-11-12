# Health Connect import and Health backup (Android)

Branch `feat/android-daily-finance-health`, PR #37. The Rust Health Kernel stays the only store of Health facts; Android reads Health Connect and hands the Kernel a validated import.

## What is read

| Type | Permission | What REVA keeps |
|---|---|---|
| Steps | `android.permission.health.READ_STEPS` | Health Connect's aggregated daily total (`StepsRecord.COUNT_TOTAL`, grouped by local calendar day) and the reporting app package names |
| Heart rate | `android.permission.health.READ_HEART_RATE` | Daily minimum, maximum and number of readings (`HeartRateRecord.BPM_MIN/BPM_MAX/MEASUREMENTS_COUNT`) and the reporting app package names |

- Read only. No `WRITE_*`, `READ_HEALTH_DATA_HISTORY` or `READ_HEALTH_DATA_IN_BACKGROUND` permission is declared. `ManifestTest` fails if one appears.
- One permission request per type, started from a tap on the Health screen (`Allow steps` / `Allow heart rate`). The user can allow one and not the other.
- The window is the last 30 local days, which Health Connect allows without the history permission.
- Aggregates are used for steps because Health Connect de-duplicates overlapping data from several apps. Google's guidance: https://developer.android.com/health-and-fitness/health-connect/read-data and https://developer.android.com/health-and-fitness/health-connect/ui/permissions.

## Grants, rationale and revocation

- The granted set is read again when the Health screen resumes, after the permission sheet closes, and immediately before every import (`HealthConnectImporter`). A type that was allowed but now is not is not read.
- A `SecurityException` during a read (access turned off between the check and the read) skips that type and is reported ("Access to heart rate was turned off, so it was not read").
- Turning access off does not delete days already copied. The Health screen says so and offers `Delete everything copied from Health Connect` (Kernel `source.delete`), which tombstones every `health_connect` record and leaves manual entries alone.
- Rationale: `HealthPermissionsRationaleActivity` (static text only) is opened by `androidx.health.ACTION_SHOW_PERMISSIONS_RATIONALE` on Android 12/13 and through the `ViewPermissionUsageActivity` alias (guarded by `START_VIEW_PERMISSION_USAGE`, category `HEALTH_PERMISSIONS`) on Android 14+.

## Idempotency and no double-counting

- Each Health Connect day is one Kernel record with a deterministic id: `hc-steps-YYYY-MM-DD` or `hc-hr-YYYY-MM-DD`, `source: "health_connect"`, `origins: [...]` (sorted package names).
- Importing the same values again is a duplicate (no event). A changed total for the same day (Health Connect adds steps during the day) is an `updated` event on the same record, so the day is never counted twice.
- A day the user deleted is tombstoned; later imports report it as rejected ("deleted on this device; not re-imported") and never bring it back.
- A manual steps entry and a Health Connect day for the same date are both kept. Totals use the manual entry (the user's own statement); if the two differ, the daily summary reports `steps_conflict` with both values and the weekly summary lists `steps_conflict_dates`. The Health screen and the voice weekly answer say which value was used. They are never added together.

## Health backup (JSON)

- `export("json")` writes `{"format":"reva-health-v1","records":[...]}`, including `source` and `origins`.
- `import_data("json")` restores into a fresh or existing install. Every row is `accepted`, `duplicate` (same id, identical content) or `rejected` with a reason (unknown field such as `dose`, bad date or id, a Health Connect id that does not match its date, a second manual steps entry for a day, a taken entry without its schedule, a record deleted on this device). Schedules are restored before taken entries whatever the file order. A dry run reports the same counts and commits nothing.
- The Android screen runs a dry run first, shows the counts, and restores only on a second tap. Sharing a backup shows the "plain, unencrypted file" warning before the share sheet.

## Privacy and egress

- Health data stays in the encrypted Health domain under `noBackupFilesDir`, excluded from Android backups. Health is not in any sync scope (sync is Finance only), so it never goes to the PC.
- No network, PC-request or WebView code is used by the Health, Health Connect or Finance report paths (`SensitiveEgressTest` scans them). Health and Finance questions are answered from the Kernel or refused with a template; the planner fallback never receives them (also `SensitiveEgressTest`).
- No diagnosis, rating or dosing: the Kernel registry has no such command, summaries carry no interpretive fields, and `dose`/`frequency` fields are rejected (`kernel/tests/health_import.rs`).

## Library notes

- `androidx.health.connect:connect-client:1.1.0` (Apache-2.0). It brings Guava `31.1-android` at runtime, which replaces CameraX's ListenableFuture-only artifact with an empty stub; the same Guava version is declared for compilation (no extra code is packaged).
- The library merges an exported `androidx.health.platform.client.impl.sdkservice.HealthDataSdkService` with no permission. Its binder (`HealthDataSdkServiceStubImpl.verifyPackageName`) rejects any caller whose package is not `com.google.android.apps.healthdata` ("Not allowed!") and exposes only foreground state and a permission token, no health data. It is kept because Health Connect on Android 12/13 binds to it; it is listed by name in `ManifestTest`'s exported-component allowlist.

# android/

Kotlin + Jetpack Compose phone app (minSdk 31, targetSdk/compileSdk 36, one activity). It works on its own.
Spec: `docs/spec/REVA_v2.0/02_ARD/ARD-200_Cross_Platform_App_v2.0.md`.

Status (AND-1 / S11): Today, Finance (accounts, budgets, bills, transactions with search, add transaction,
add account, CSV/OFX/JSON import with dry-run report then confirm, export through the share sheet), Talk
placeholder, More. The Finance data is the Rust Domain Kernel (`kernel/`) through its UniFFI Kotlin binding and
`libreva_kernel.so` (arm64-v8a, x86_64). The key is wrapped by the Android Keystore; domain files and the wrapped
key live in `noBackupFilesDir`; backup rules exclude them. Permissions (SYNC-1d): exactly INTERNET (HTTPS to your own paired PC only, cleartext refused) and CAMERA (to read the pairing QR code). See `docs/architecture/android-sync.md`.

## Build a sideloadable debug APK

```
python tools/android/build_apk.py            # kernel binding + .so + Gradle; prints the path and SHA-256
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

`--skip-kernel` reuses the libraries already built. Windows needs what `tools/kernel/build_android.py` needs.
Output: `android/app/build/outputs/apk/debug/app-debug.apk` (signed with the standard Android debug key).

## Tests

```
cd android
./gradlew :app:testDebugUnitTest                        # JVM: logic, view models, key provider, manifest checks
# Emulator (API 31 and 36), in airplane mode:
adb shell cmd connectivity airplane-mode enable
./gradlew :app:connectedDebugAndroidTest -Preva.uiTests=true -Pandroid.testInstrumentationRunnerArguments.requireAirplane=true
```

`-Preva.uiTests=true` adds Compose's empty test activity to the debug build; the APK you sideload does not have it.
`kotlin.compiler.execution.strategy=in-process` is set because the Kotlin daemon hung on this machine.
Fonts: IBM Plex (SIL OFL, see `app/OFL-IBM-Plex.txt`), same files as the Windows app.

## Pair with your PC and sync (SYNC-1d)

On the PC: turn on the pairing gateway in Devices, then show the pairing code. On the phone: More, Devices, scan (or paste) the code, compare the 6 digits with the PC, approve on the PC. Sync runs after pairing and with "Sync now". End-to-end check on an emulator (real Core and gateway on the host):

```
python tools/android/sync_e2e.py --serial emulator-5554     # needs app-debug.apk + app-debug-androidTest.apk installed
```

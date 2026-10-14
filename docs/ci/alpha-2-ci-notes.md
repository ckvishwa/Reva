# Alpha 2 CI notes

What broke the five CI lanes while `integration/alpha-2` was assembled, what was found, and what was
changed. Two throw-away branches (`ci/runtime-probe`, `ci/flake-probe`) were used to find causes; they are
removed, and their findings are summarised here.

Final state: run 38458285698 on `fe5a021566fac884eebb3520a23a1ff6af6a3436` was green on all five lanes
(android, contracts, csharp-desktop, kernel, python).

## 1. Kernel lane: clippy failed on CI's newer Rust

CI's toolchain is Rust 1.99; the local one was 1.94. The newer clippy reports
`needless_borrows_for_generic_args` where the older one stays silent. Five errors, all in
`kernel/src/import/csv_format.rs` (`.and_then(&get)`). Fix: `.and_then(get)` (commit `54e491b`).

Lesson: a local `cargo clippy` on an older toolchain is not evidence for CI. Pin the toolchain in
`rust-toolchain.toml` when the project next touches the Kernel lane.

## 2. csharp-desktop lane: test discovery hung, then crashed

**Symptom.** `dotnet test` on the Windows runner printed nothing, then the test host crashed after 2 minutes of
inactivity.

**Cause (proven on `ci/runtime-probe`, run 38461724501).** The runner has the Windows App Runtime *framework*
2.5.1.0, but not the 2.3.1 *loader packages* (DDLM, Main and Singleton) that the app's NuGet reference
(`Microsoft.WindowsAppSDK.Runtime` 2.3.1) needs to bootstrap. Without them the test host waits on a runtime it
cannot start. After installing the four MSIX files the runner had
`Microsoft.WinAppRuntime.DDLM.2.3.1.0-x6`, `MicrosoftCorporationII.WinAppRuntime.Main.2` 2.3.1.0 and
`...Singleton` 8002.3.1.0, and the tests passed.

**Fix.** A CI step, "Install the Windows App Runtime", finds the NuGet cache with
`dotnet nuget locals global-packages --list` and installs `Microsoft.WindowsAppRuntime.2.msix`, `Main`,
`Singleton` and `DDLM` from `.../microsoft.windowsappsdk.runtime/*/tools/MSIX/win10-x64/*.msix`. The glob must
end in `*.msix`: `Get-ChildItem -File` on a directory path returns nothing (reproduced locally). The test step
keeps `timeout-minutes: 40` and `--blame-hang --blame-hang-timeout 10m --blame-hang-dump-type none`, so a future
hang fails in minutes with a name, not after the job limit.

## 3. csharp-desktop lane: the lock-file test failed

`PackageLockFile_RecordsExactWakeProviderVersions` uses `.Single()` over the lock file's targets. Restoring
with a `win-x64` runtime identifier adds a second target to `packages.lock.json` by NuGet design, so it failed.
The workarounds were dead ends:

- `RestorePackagesWithLockFile=false` is refused while a lock file exists (NU1005).
- A job-level `RuntimeIdentifier` is refused for a solution (NETSDK1134).
- Putting the original lock file back after restore worked but hid the problem.

**Fix.** The runtime-identifier approach was dropped (the runtime comes from the MSIX install above), the
workaround and `desktop/Directory.Build.props` were removed, NuGet locking stays on, and restore now runs
`dotnet restore desktop\Reva.Desktop.sln --locked-mode`. Committed lock files pass it locally and on CI.

## 4. Which Windows App Runtime do the tests and the app load?

Sampling process modules while the suites ran showed that both the unit-test host and the app load
**2.5.1.0** (`CoreMessagingXP.dll` and others under `...WindowsAppRuntime.2_2.5.1.0_x64...`), not the 2.3.1 named by
the NuGet reference. The development PC has 2.2.0.0, 2.3.1.0, 2.4.0.0 and 2.5.1.0 installed; the
framework lookup binds to the newest installed 2.x framework. (Not verified in the loader source; observed on
both machines.) Consequence: results are for 2.5.1.0
on both the PC and the runner. A machine with only 2.3.x would run the app on 2.3.1.

## 5. Devices window smoke test: intermittent failures

On the unfixed commit, 10 runs gave 6 passes and 4 failures with two distinct causes.

1. **"The QR code is too small to scan" (3 of 4).** The product draws the QR at a fixed 240 x 240
   (`Views/DevicesPage.xaml`). The test measured the element's bounding rectangle before scrolling it into view,
   so a code partly below the fold reported only its visible part. Fix (test only): scroll the full code into
   view through the page's scroll pattern, then measure. No coordinates are used.
2. **"The response ended prematurely" (1 of 4).** Most likely cause: the gateway's server closes idle keep-alive
   connections after 5 seconds (uvicorn's default), and a client that reuses its pooled connection at almost
   exactly that moment sends on a socket the server is closing. This is strongly supported, not proven for the one
   CI-style failure we saw: the failing run left no trace. What is proven: a new test that reuses one TLS connection
   after a 5.6 s idle gap fails with `RemoteDisconnected: Remote end closed connection without response` at 5 s and
   passes at 30 s, and the gateway trace shows the phone's `/pair/start` and `/pair/complete` (5.4 s apart) on two
   different connections while the later requests share one. Fix (app): the gateway keeps idle connections for
   30 seconds (`_KEEP_ALIVE_SECONDS` in `gateway/server.py`). The test phone now also reports how long its
   connection was idle when a request fails.

**Gateway tracing (new, off by default).** `REVA_GATEWAY_TRACE=<file>` writes one line per request: request id,
client address and port, whether the connection was new or reused (and how long it had been idle), method, path,
status and phase timings (body, handler, send, total). It never records a header, a body, a query string, a device
id, a nonce or a signature. A request that never reaches the app leaves no line, which is itself the finding.
A refused request also carries `reason=<stable error code>` (for example `no_open_pairing`), taken from the
gateway's own error code and accepted only if it matches `[a-z_]{1,40}`. Without it a 403 on `/pair/start`
could not be told apart: cancelled code, wrong code or bad proof.

**Other failure modes seen while repeating the test (all on the development PC).**

- A 20-run check made while Gradle and an emulator were using the machine failed 20 of 20 at varying steps. It was
  discarded as invalid, not counted.
- When another application window (an IDE) covered REVA, 3 of 30 runs failed: "The paired phone never appeared"
  (the screenshot showed the IDE on top), an empty error message, and an SSL connection error on `/pair/start`. The
  test now calls `BringToFront()` at the start and before Approve and Revoke.
- After that change, a 30-run loop gave 29 passes and one failure: `StartPairingAsync` got 403 instead of 200
  (`POST /pair/start status=403 handler_ms=109`). The trace had no reason code yet, so the cause is **unknown**.
  Reason codes were added to find it if it returns.
- Two earlier loops were invalid because of script errors (a carriage return in a log path made runs return
  instantly and leave orphan test processes). They were discarded.

The final 30-run result is in "Result of the 30-run loop" below.

**Result of the 30-run loop.** 30 consecutive runs of `DevicesSmokeTests`, Release build, `--no-build`, started
2026-10-13 22:37 local: **30 passed, 0 failed** (log: `docs/ci/devices-30-run-log.txt`; 25-31 s per run, one
45 s run). No emulator and no Gradle were running. It was not a fully idle PC: the user's IDE, browser and other
programs were open, and the test cannot be isolated from them. All 30 gateway traces (150 requests) were
inspected: no request had the `disconnected` flag; every `/pair/complete` was `202` (waiting for the PC's
approval) and every `/sync/pull` after Revoke was `401 reason=unauthorized`, which is the intended refusal. In 29
of 30 runs `/pair/complete` reused its connection after an idle gap of 5.0-5.5 s, right at the old 5 s
server limit, which is why the old default was a coin flip and why 30 s is a fix and not luck. The earlier
`/pair/start` 403 did not recur in these 30 runs and its cause remains unexplained.

## 6. Android lane notes (local, for reproducing)

- Instrumented tests need `./gradlew assembleDebug assembleDebugAndroidTest -Preva.uiTests=true`. The property
  adds the Compose `ComponentActivity`; the clean sideload APK omits it, and without it 16 Compose tests fail with
  "Unable to resolve activity ... ComponentActivity".
- On the development PC a streamed `adb install` of the 53 MB APK hangs. `adb push` to `/data/local/tmp/`
  followed by `adb shell pm install -r` works.
- The Gradle daemon and the adb server intermittently fail to connect on loopback on this PC; retry after
  `./gradlew --stop` / `adb kill-server`.

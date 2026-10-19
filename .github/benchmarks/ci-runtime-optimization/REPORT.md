# CI runtime optimization evidence

## Base and scope

Selected base before edits: PR #33 open at `129ef650f99a6da8e6921bd314e28eca65ec8906`, branch `fix/p0-platform-test-isolation`. Main was `df7a3dc2451243713e9f02362141e54e1e8087fb`; PR #34 was open at `75bf2f5f463328e18d22a6f94f7f48ef8c1efc1d`, branch `docs/finance-intelligence-cloud-preflight`. Work branch `perf/ci-runtime-optimization`, draft PR #36 targets PR #33's branch. No changes to either existing PR or Finance implementation/tests.

No AGENTS.md found in the checkout or workspace. Reviewed CLAUDE.md working rules during the later audit (after initial edits); configured owner identity retained. Its named code-review/cicd-setup skills were not present in the workspace or available skill catalog; manual diff/workflow/security review performed without claiming those skill invocations. This is a CI-only task, so evidence is recorded here rather than modifying the product evidence ledger. Inspected all three active workflows (`ci.yml`, `claude-code-review.yml`, `claude.yml`), pytest markers/testpaths, coverage configuration, native protection tests and fixtures, binding and Android build scripts, Gradle configuration, and historical Windows/Android logs. Repository rulesets API returned `[]`; branch protection and Actions-permissions API requests returned HTTP 403. Required-check configuration is therefore unverified. Existing eight CI job IDs/names, event coverage, and review workflows remain unchanged.

## Baseline

Run https://github.com/ckvishwa/Reva/actions/runs/39169940760, head `129ef650f99a6da8e6921bd314e28eca65ec8906` (checkout merge SHA `58da39ddb2f023a8fe804a48e44e9407d34a3d2d`). All eight jobs passed. Runner-minutes calculated as sum of job completed_at minus started_at; wall time is earliest job start to latest job completion, excluding queue time. Includes setup and post-job/cache overhead; excludes separate Claude review workflow.

API-derived total 49.95 runner-minutes, wall 26.67 minutes. Windows Python: install 108s, binding build 572s, type check 53s; unit 89s, integration 120s, contract 5s, security 53s, native subset 3s, E2E 9s (279s duplicated execution), full coverage step 562s. Historical Android cargo-ndk 4.1.2 compiled in 29.17s; cross-builds reported 1m53s and 1m40s. PR #34 run https://github.com/ckvishwa/Reva/actions/runs/39176667394 Windows 23m40s provides a secondary comparison, not a platform-equivalent baseline.

Windows baseline: full collection 1,725; 1,704 passed / 21 pre-existing skips. Directory collections: unit 1,107; integration 319; contract 24; security 130; E2E 1. Native subset: two passed, already included in security. Total old-directory IDs 1,581; full collection includes 144 additional IDs (including gateway and cross-binding suites).

Coverage XML: 9,091/9,785 statements (92.91%); 2,000/2,418 branches (82.71%). Combined terminal result: 91%, 694 missed statements, 332 partial branches. Branch coverage remains enabled; source and exclusion rules unchanged.

## Changes and decisions

- Full Windows pytest invocation retained under coverage, removing the five duplicated directory executions and separate duplicate native execution. Collection-only runs compare full node IDs against the old directory selection and native subset; no tests run in collection-only stages. JUnit audit requires both native DPAPI tests to have passed, rejects skips/failures/errors and a non-Windows host. Test commands retain normal nonzero failure propagation; no assertions/tests/markers/skip conditions changed.
- Explicit stable Rust setup on Windows; exact Rust artifact/dependency caches on all five Rust-consuming jobs. Keys include runner OS/architecture, job, rustc -vV (compiler, commit, host), tracked Cargo.lock/manifests/Rust inputs/build scripts/workflow/cache helper, target/flags, image version, NDK location and source.properties. Android key specifies both ABIs, release profile and API26. No restore-key fallback or Windows/Linux/Android binary sharing. Source and toolchain changes invalidate; exact hits still invoke Cargo and regenerate bindings. Cache directories are registry index/cache/src, Git object DB and target; no Cargo credentials/config or runtime state.
- Cargo-ndk pinned to historical 4.1.2, compiled with --locked into an isolated runner.temp prefix; cache contains only its bin directory, keyed by version plus compiler/build fingerprint. Warm exact hit skips installation, not cross-build/ELF validation.
- Pip cache stores downloads/wheels keyed by OS/Python and pyproject.toml; every job still installs editable dependencies. Version ranges are resolved afresh, so this is not a dependency lock. No virtualenv, model downloads, runtime records or credentials cached.
- Android Gradle cache restricted to modules-2, build-cache-1 and wrapper. Exact key includes OS/arch/resolved Java 21 version and Android Gradle/config/source plus Kernel source/lock inputs; no fallback keys, Gradle credentials/config/daemon state excluded. Existing org.gradle.caching=true uses content-addressed task inputs. Unit test task is explicitly --rerun so restored task outputs never replace test execution.
- Kept repeated binding generation and independent installations across jobs: removing these via cross-job artifacts/dependencies adds coupling and can lengthen the critical path; exact per-job caches reduce compilation while preserving each binding consumer's verification. No cross-job native library reuse.
- Kept lightweight contracts and heavy jobs in parallel. No new dependency gate/path filters: avoids delaying heavy platform tests or leaving required checks pending. Existing lint/type/security/contract/platform/cross-binding/release checks preserved. Concurrency cancels only superseded pull_request runs, grouped by event/PR; push checks have unique run-ID groups and cancel=false. No larger/paid runners.

## Local verification and experiments

Repository-wide Ruff lint/format and actionlint 1.7.7 pass. Local Linux collection: 1,675 full IDs, 1,538 former directory IDs, two native IDs; every former ID is contained in full. Counts differ by platform/optional availability, so remote Windows counts are authoritative. Native-result guard exercised with successful, skipped, failed, errored, and non-Windows inputs; local platform test file: two passed, two existing Windows-only skips. Cache fingerprint determinism, flags and target invalidation checked with a mock compiler (rustc absent locally); actual compiler/build results come from hosted CI.

Exploratory run https://github.com/ckvishwa/Reva/actions/runs/39179824868 at `f30213f8ce2f0ab926b3dd89c9f96a29298c157a` was superseded by the correction forcing Android test execution and hashing tracked inputs only. Exclude its incomplete/cancelled timings from benchmark. It may have populated pip/Gradle caches; final Rust keys changed, so first final Rust cache is cold while dependency-cache status must be reported separately. Direct gh log/artifact downloads hit redirected-blob HTTP 403; GitHub connector successfully retrieved logs and coverage artifact. Local native Rust build was unavailable (no rustc); no local performance numbers substituted for GitHub timings.

## Cold run measurements

PR CI run https://github.com/ckvishwa/Reva/actions/runs/39179895366 at `ae30233588184c5e68ac6719591cba1a6dc29851`: all eight jobs passed. This was the first complete final-key run; all Rust caches, cargo-ndk, pip caches, and Gradle caches missed, then uploaded exact-key entries on successful completion. Avatar's existing npm cache hit is unchanged infrastructure.

Runner-minutes: **45.48** (-4.47, -8.9%). Wall time: **22.42 min** (-4.25, -15.9%). Windows Python: **22.42 min** (-4.23, -15.9%). Cold per-job minutes:

| Job | Baseline | Cold | Change |
|---|---:|---:|---:|
| Windows Python | 26.65 | 22.42 | -4.23 |
| Linux Python | 6.55 | 7.00 | +0.45 |
| Android unit | 4.60 | 4.83 | +0.23 |
| Android native | 4.37 | 3.53 | -0.84 |
| Kernel | 3.77 | 3.58 | -0.19 |
| Avatar | 2.05 | 1.27 | -0.78 |
| C# Desktop | 1.82 | 2.63 | +0.81 |
| Contracts | 0.15 | 0.22 | +0.07 |

The complete baseline and cold per-step timings appear in the JSON evidence files. Key Windows stages (baseline → cold seconds): dependency install 108→96; Rust binding 572→570; Windows collection and old native/directory runs 279→13 seconds. The coverage run is 562→561 seconds; type check is 53→52 seconds. Adding explicit Rust setup/cache handling costs about 30 seconds including the first cache upload. Removing duplicate test execution saves about 4.4 minutes net while preserving all 1,725 Windows test IDs and the 91% terminal coverage result. Cold native build time itself was unchanged. First cache uploads/setup affected cold Linux (pip and Rust) and Android (cargo-ndk/Rust/Gradle), so their warm timings are pending.

Coverage comparison is exact: cold XML has 9,091/9,785 lines and 2,000/2,418 branches, identical to baseline (92.91% line, 82.71% branch). JUnit has 1,725 tests, zero failures/errors, 21 skips. Both native Windows DPAPI tests have JUnit pass results; the non-Windows refusal test remains skipped on Windows as before. The Linux cold suite remains 1,690 passed / 35 skipped, and its 35 skip identifiers/reasons match baseline exactly. Native Kernel tests, 97 Kotlin conformance steps, Android ABI ELF checks, C# 833 tests and existing 12 UI opt-in skips, Avatar 36 unit + 9 Edge tests, and contract validation passed.

Per-job timestamps and completed-step timestamps are preserved in [`baseline.json`](baseline.json) and [`cold.json`](cold.json). The coverage/JUnit/collection artifacts are available from the cold run link above.

## Measurements and verdict

Two warm runs are pending. Performance targets are not promises; merge readiness requires all platform/security checks, collection equivalence and coverage comparison in addition to faster runtime.

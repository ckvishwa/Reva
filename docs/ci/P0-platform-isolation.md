# P0: platform-aware Python test isolation

Baseline verified against remote main before editing: `df7a3dc2451243713e9f02362141e54e1e8087fb` (2026-10-18).

## Baseline attribution

The binding-enabled Linux assessment collected 1721 cases: 1242 passed, 33 skipped,
44 failed, 402 setup errors, 5 warnings (80.03 s). Each of the 446 failed/error
tracebacks was inspected programmatically for both the exception message and a
`reva_core/security/dpapi.py` frame. All terminate at the constructor's deliberate
`ProtectionError("DPAPI is only available on Windows")`, baseline line 47.
There are no non-DPAPI exceptions among those 446 cases. Every test identifier,
outcome and terminal frame is recorded in
[`tests/evidence/p0-baseline-failures.csv`](../../tests/evidence/p0-baseline-failures.csv).
The original assessment's `/workspace/reva-final.xml` has SHA-256
`db2df22bb3b9308b642c81c38137954e70d1d73d4963587a3b094b21de4b389a`.

| Suite | Failed | Setup errors |
|---|---:|---:|
| unit | 18 | 3 |
| integration | 18 | 185 |
| contract | 2 | 0 |
| security | 4 | 87 |
| gateway | 1 | 127 |
| e2e | 1 | 0 |
| Total | 44 | 402 |

Most API fixtures go through `create_app` → `build_voice_session_router` →
`FileDialogueStore` → `DpapiProtector`. Dialogue persistence unit tests also
construct that store directly. The two contract failures instantiate a real API
to compare UI fixtures; the independent nine-schema validator already passed.

Exception outside this precise baseline: an earlier pre-binding run failed
`tests/unit/test_kokoro_provider.py::test_worker_that_ignores_stop_is_killed_and_restarts_on_next_speak`
at the PID-death assertion (line 196). It passed alone and in the binding-enabled
baseline. It is a timing-sensitive process-liveness finding, not DPAPI, and was
not suppressed or relabeled as a platform skip. Existing playback-watchdog
cleanup messages are likewise separate from the DPAPI setup failures.

After isolating DPAPI, the first portable run also exposed the existing
`test_a_request_in_flight_finishes_before_revoke_returns` scheduling race
(already noted in `CLAUDE.md`): the server can complete its locked operation,
then revoke can return before the client thread records HTTP receipt. A separate
test-only commit records ordering at the server operation boundary, retains HTTP
200 and post-revoke 401, and additionally requires both threads to finish. The
blocking check remains. No production revocation code or assertion of the
security invariant was relaxed. Targeted corrected test: one passed in 1.24 s.

## Isolation boundary and security review

Production `DpapiProtector` still refuses every non-Windows construction. No
production encryption fallback, test environment switch, secret-store fallback,
route, grant, policy, pairing, sandbox or model default was introduced.

The root pytest fixture substitutes only the imported protector factory used by
`reva_core.language.dialogue`, and only off Windows. Its test-only AES-GCM
implementation uses an ephemeral per-test key, random nonces and authenticated
purpose bytes. It permits the existing file/migration/restart tests to exercise
their assertions without plaintext or unauthenticated mock ciphertext. This is
test behavior, not evidence that DPAPI works on Linux. The environment guard
still runs before collection; test data stays under the OS temporary directory.

The production `reva_core.security.dpapi.DpapiProtector` symbol is never patched.
Direct Linux refusal is asserted in `tests/security/test_platform_protection.py`.
On Windows the fixture does not patch anything: existing dialogue/API tests use
real DPAPI. New native tests check round-trip, non-plaintext ciphertext,
wrong-purpose and tamper refusal, and that the actual dialogue store selects a
real `DpapiProtector`. CI asserts `sys.platform == 'win32'` before running those
tests explicitly on the unchanged `windows-latest` lane. Linux skips those two
new native tests rather than claiming native coverage.

Manual diff/security review: checked the consumer-only fixture boundary, original
DPAPI refusal, unchanged vault pytest guard, unchanged `use_last_error=True`,
guarded DLL loads and process job calls, existing route/security assertions,
temporary data guard and absence of production imports from tests. The named
`security-review`/`code-review` skills were unavailable locally and in the session
catalog; this report records manual review, not an invocation of those skills.

## Classification of all 32 Linux mypy diagnostics

| Baseline source | Count | Classification and change |
|---|---:|---|
| `security/dpapi.py` | 1 | `_purpose` inference was lost after a statically always-raising Linux constructor; declare the instance attribute type explicitly. Runtime refusal remains. |
| `security/credential_store.py` | 10 | Seven member-inference diagnostics (`_target`/`_advapi`) and three Windows-only `ctypes.get_last_error` attributes. Explicit `str`/`ctypes.CDLL` declarations and a platform-guarded typed native error accessor. |
| `domains/keys.py` | 8 | Five member-inference diagnostics (`_prefix`/`_advapi`) and three Windows-only error accessor attributes. Same explicit declarations and native accessor. |
| `voice/supervised_worker.py` | 13 | Names defined only in the Windows import branch were referenced by guarded methods. Expose the existing declarations to the type checker via `TYPE_CHECKING`, declare the DLL handle type, and explicitly guard DLL construction. Imports, structures, loading and calls remain Windows-only at runtime. |

Totals by diagnostic code: 13 `has-type`, 6 `attr-defined`, 13 `name-defined`.
These are portability/type-declaration defects, not evidence of an executed
unguarded Windows call on Linux. They are fixed without `ignore_errors`, new
`type: ignore`, `Any` casts or weakening strict mypy configuration. The accessor
raises off Windows; it never fabricates a Windows error code. Both native Linux
and Windows-target mypy now pass over 138 source files.

## Validation

Runtime: Linux x86_64, Python 3.12.14, pytest 8.4.2, mypy 1.20.2, Rust 1.99.1.
Dependencies and generated Kernel bindings from the preceding cloud assessment
were reused; no dependency versions or secrets were changed. Commands from repo root:

```sh
/workspace/reva-venv/bin/python -m pytest -q -ra --junitxml=/workspace/reva-p0.xml
/workspace/reva-venv/bin/ruff check .
/workspace/reva-venv/bin/ruff format --check .
/workspace/reva-venv/bin/mypy reva_core
/workspace/reva-venv/bin/mypy --platform win32 reva_core
/workspace/reva-venv/bin/python tools/ci/check_contracts.py
PATH=/workspace/reva-cargo/bin:$PATH RUSTUP_HOME=/workspace/reva-rustup CARGO_HOME=/workspace/reva-cargo cargo test -p reva-kernel
PATH=/workspace/reva-cargo/bin:$PATH RUSTUP_HOME=/workspace/reva-rustup CARGO_HOME=/workspace/reva-cargo cargo fmt --all -- --check
PATH=/workspace/reva-cargo/bin:$PATH RUSTUP_HOME=/workspace/reva-rustup CARGO_HOME=/workspace/reva-cargo cargo clippy --workspace --all-targets -- -D warnings
```

Targeted dialogue, voice socket and new platform-protection run: 46 passed,
2 native-Windows skips in 1.10 s. Schema validation: nine schemas, zero problems.
Native Kernel: 95 passed, zero failed, one pre-existing ignored test. Lint and
format checks pass. Native Linux and Windows-target mypy both pass (138 files).
Full suite and final review results are recorded below after completion.

Intermediate full run before the separately committed revoke test correction:
1689 passed, 35 skipped, one failure, zero setup errors, five warnings, 235.42 s.
Only the incorrect revoke/client-receipt ordering failed. Independent integration
debug run: 297 passed, 22 skipped in 54.45 s. After reducing the worker typing
change to `TYPE_CHECKING` declarations, the worker/environment/epoch/native
protection subset passed 26 tests with two native-Windows skips in 8.31 s.
Clippy (`-D warnings`) and Rust format check pass.

## Remaining platform and release limits

Native Windows execution remains a PR CI requirement; Linux test-double results
do not certify it. Physical microphone/speaker STT/TTS, WinUI, Android permission
flows, pairing and phone-to-PC approval still need the documented owner hardware
checks. Android lint, dependency advisories and wider release/privacy evidence
from the readiness assessment remain outside this focused P0. OpenClaw remains
unenabled. No release gate or hardware ledger row is upgraded by these tests.

## Final Linux result

Full suite: **1690 passed, 0 failed, 0 setup errors, 35 skipped, 5 warnings,
231.88 s** (1725 collected). All 446 baseline failed/error identifiers are now
`passed`, verified by joining the committed inventory to the final JUnit XML;
none were converted to skips.

| Suite | Passed | Failed/errors | Skipped |
|---|---:|---:|---:|
| contract | 24 | 0 | 0 |
| cross_binding | 7 | 0 | 0 |
| e2e | 1 | 0 | 0 |
| gateway | 136 | 0 | 1 |
| integration | 297 | 0 | 22 |
| security | 126 | 0 | 4 |
| unit | 1099 | 0 | 8 |

The 35 skips are the original 33 Windows/model opt-ins plus two newly added
native DPAPI tests. Existing voice-evals remain opt-in at collection, outside
that count. No assertion was deleted, no failing case was skipped or xfailed.

Final artifacts in the assessment workspace: `/workspace/reva-p0-final.log`,
`/workspace/reva-p0-final.xml`, `/workspace/reva-p0-kernel.log`,
`/workspace/reva-p0-clippy.log`, `/workspace/reva-p0-rust-fmt.log`,
`/workspace/reva-p0-mypy-minimal.log`, `/workspace/reva-p0-mypy-win-final.log`.
Five pytest warnings and the pre-existing pending playback-watchdog cleanup
messages remain a lifecycle follow-up. Native Windows execution awaits PR CI;
this report does not claim it passed. Hardware rows remain untouched.

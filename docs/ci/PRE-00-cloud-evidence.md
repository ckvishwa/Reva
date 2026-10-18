# PRE-00 cloud verification

**Selected base:** `fix/p0-platform-test-isolation@129ef650f99a6da8e6921bd314e28eca65ec8906` (PR #33 open, CI run [39169940760](https://github.com/ckvishwa/Reva/actions/runs/39169940760) green in all nine listed check runs, including native Windows and Linux Python). `origin/main@df7a3dc2451243713e9f02362141e54e1e8087fb` remains unchanged. PR #34 design branch at `75bf2f5f463328e18d22a6f94f7f48ef8c1efc1d` was read via `git show`; none of its commits were copied. Main CI run [38934452489](https://github.com/ckvishwa/Reva/actions/runs/38934452489) succeeded. This branch is stacked on PR #33 and its implementation PR targets that branch until #33 merges.

**Scope:** `finance.monthly_plan` v1 structural schema, accounting rules, deterministic wholly fictional 30-day fixture and test-only oracle. The current production Finance API, Rust Kernel, SQLCipher store, policy broker, ADK tools and Android code are unchanged. No live planner is claimed. The reference oracle is a PRE-00 contract checker; FIE-01/FIE-02 must implement and retest these cases against Rust and both UniFFI bindings.

**Selected-base comparison:** The unchanged PR #33 head previously passed full Linux Python **1690 passed, 35 skipped**, Rust **95 passed, 1 ignored**, contract **24 passed**, Finance API **10 passed**, cross-binding **7 passed**, security **126 passed, 4 skipped**, schema checker **9 schemas / 0 problems**, strict mypy **138 source files**. PR #33 GitHub CI later completed successfully in the Windows and Linux lanes. These figures come from `docs/ci/P0-platform-isolation.md` and the PR #33 CI; they are not invented reruns on `main`. PRE-00 adds only contract tests and a schema, so the expected delta is 29 new contract cases and one schema. No selected-base failure was relabeled as a regression.

## Local commands and outcomes

Run from repository root with `/workspace/reva-venv/bin/python`, `/workspace/reva-venv/bin/ruff`, `/workspace/reva-venv/bin/mypy`, and Rust installed under `/workspace/reva-cargo` / `/workspace/reva-rustup` (`PATH=/workspace/reva-cargo/bin:$PATH`). These paths are cloud setup, not repository settings.

| Command | Result |
| --- | --- |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy -p reva-kernel --all-targets -- -D warnings` | PASS |
| `cargo test -p reva-kernel` | 95 passed, 0 failed, 1 ignored |
| `python tools/kernel/build_bindings.py` | PASS; Python/Kotlin UniFFI generated, optional `yapf`/`ktlint` autoformatters absent |
| `python -m pytest tests/contract -q -ra` | 53 passed, 0 failed, 0 skipped (29 new) |
| `python -m pytest tests/integration/test_domains_finance_api.py -q -ra` | 10 passed, 0 failed, 0 skipped |
| `python -m pytest tests/cross_binding -q -ra` | 7 passed, 0 failed, 0 skipped |
| `python -m pytest tests/security -q -ra` | 126 passed, 0 failed, 4 skipped; four upstream deprecation warnings |
| `python tools/ci/check_contracts.py` | 10 schemas, 0 problems |
| `ruff check tests/contract/test_finance_monthly_plan.py` | PASS |
| `ruff format --check tests/contract/test_finance_monthly_plan.py` | PASS |
| `ruff check .` / `ruff format --check .` | PASS / 457 files already formatted |
| `mypy reva_core` | PASS, 138 source files |
| `python -m pytest tests/unit/test_evidence_ledger.py -q` | 3 passed |
| `python -m pytest -q -ra` | 1716 passed, 2 failed, 35 skipped, 5 warnings, 176.71 s; run began before the final added missing-cash contract case, which passed in the final 53-case contract run |

The two full-run failures were `tests/gateway/test_trace.py::test_a_refused_request_traces_its_stable_reason_code` (`reasons.log` not present immediately after a 403) and `tests/unit/test_kokoro_provider.py::test_worker_that_ignores_stop_is_killed_and_restarts_on_next_speak` (PID remained visible after synchronous three-second liveness wait). Neither test or production dependency was changed in PRE-00. Focused branch rerun: gateway passed and Kokoro failed. On detached `/workspace/Reva-pre00-base@129ef65`, ten repetitions of `python -m pytest tests/unit/test_kokoro_provider.py::test_worker_that_ignores_stop_is_killed_and_restarts_on_next_speak -q` gave **5 passed / 5 failed**. Ten repetitions of `python -m pytest tests/gateway/test_trace.py -q` gave **6 module passes / 4 failures**; each failed module had 4 passed and only the trace-file case failed. Both are inherited timing failures, not Finance regressions. Full branch output: `/workspace/reva-pre00-full.log` (cloud workspace only, not committed).

`python` in the commands above denotes `/workspace/reva-venv/bin/python` here; `cargo` uses the workspace Rust install. Exact invocations used those binaries and environment variables. The focused suite's 29 new cases validate schema shape/rejection, integer amounts, provenance, no double counting, dated 30-day golden cash/headroom, paid bill and CSV duplicate, debt and card distinctions, savings holdback, missing/null values, hypothetical immutability, currency boundaries, calendar dates, and inert malicious merchant text. They exercise a **test-only reference**, not a production monthly-plan endpoint.

**NOT RUN locally:** .NET/WinUI (`dotnet` absent); native Windows DPAPI/Credential Manager (`sys.platform` is Linux; covered by PR #33 Windows CI); Android JVM/instrumented/Keystore/device (`ANDROID_HOME`, SDK, emulator and `adb` absent); real PC/phone pairing and voice hardware. These are not counted as passes. Android and Windows code was not modified in this PR.

**Manual security review:** No production source or dependency manifests changed. The schema is read-only and additive. The oracle reads static fictional JSON and never calls a live API, stores data, opens a network socket, processes a real secret, or executes merchant text. The existing capability registry still excludes payment, transfer, purchase and bank-login commands; the test checks that. No hosted Finance model, Ollama, external model service, new ADK tool, new broker route or new credential path is enabled. Production SQLCipher, Windows DPAPI/Credential Manager and Android Keystore remain governed by the existing implementation. Named repository `architecture-design`, `security-review`, and `code-review` skills were not present in this workspace, so the boundary and full diff were reviewed manually.

**Remaining blockers:** No authoritative Rust debt/income/obligation model, linked card-payment or transfer records, migration/replay/conformance for the new semantics, or live dated planner exists. PR #33 must merge (or the stack be retargeted after its disposition) before this PR can merge. Real Windows PC and Android device acceptance is still required for platform key protection, UI integration and pairing. FIE-01 should add the minimum data model and compatibility evidence; FIE-02 should implement the planner against this fixture.

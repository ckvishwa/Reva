# REVA Finance Intelligence — Implementation Preflight

**Date:** 2026-10-18  
**Repository:** `ckvishwa/Reva`  
**Verified remote baseline:** `main@df7a3dc2451243713e9f02362141e54e1e8087fb`  
**Decision:** CONDITIONAL GO for preflight, contracts, synthetic fixtures, read-only proof of concept. NO-GO for deploying AI-generated financial decisions, real customer data, automatic payments, or unreviewed model downloads.

## 1. Evidence and status

| Element | Verified status | Evidence |
|---|---|---|
| PR #33 platform isolation | Open, unmerged; head `129ef650f99a6da8e6921bd314e28eca65ec8906` | https://github.com/ckvishwa/Reva/pull/33 |
| CI Run A for PR #33 | 8/8 jobs completed successfully | https://github.com/ckvishwa/Reva/actions/runs/39169940760 |
| Finance domain source | Rust `account`, `transaction`, `category`, `budget`, `bill`, `networth_snapshot`; event log and projections | `kernel/src/domains/finance/{schema,queries,commands,project}.rs` |
| Read APIs | `cashflow`, `spend_by_category`, `budget_status`, `upcoming_bills`, `account_balances`, lists, conflicts | `reva_core/domains/routes.py`; `kernel/src/domains/finance/queries.rs` |
| Finance UI | Windows WinUI 3, Android Compose, both backed by shared Kernel | `desktop/src/Reva.Desktop/Views/FinancePage.xaml`, `android/app/src/main/java/app/reva/ui/finance/FinanceScreen.kt` |
| Local AI | Python Google ADK + LiteLLM; opt-in `ollama_chat/llama3.1:8b` configured at `127.0.0.1:11434` | `reva_core/config/settings.py`; `reva_core/agent/adk_orchestrator.py` |
| ADK Finance tools | **Not yet registered** in present ADK tool list: `search_memory`, `get_current_time` | `reva_core/agent/adk_orchestrator.py`, lines 103–111 |
| New planner / ML models | Not implemented | Existing Finance query/command registries contain none |
| Actual local hardware/model tests | **NOT RUN** during this preflight; GitHub read-only access cannot measure local disk, VRAM, model installation, or live audio | Must be performed in the Windows checkout |

Prior docs sometimes describe early stages as "planned" after implementation. Use current code and tests, not historic document statuses, as authority.

## 2. Decisions to freeze before implementation

1. **Local-first:** Retain Rust Domain Kernel, SQLCipher, Python FastAPI, Windows WinUI 3, Android Kotlin/Compose, UniFFI, signed local-network sync. No hosted finance database or required cloud model.
2. **Authoritative vs advisory:** Rust alone computes balances, obligation deductions, cash-flow projections, debt payment accounting, and safe-to-spend. Python ML yields suggestions/estimates with provenance. An LLM never becomes a ledger or amount authority.
3. **Read-only intelligence first:** `monthly_plan`, `cashflow_forecast`, `safe_to_spend`, and `spending_patterns`. Adding/editing financial records is a separate signed, approved T2 command through the existing broker.
4. **No funds movement:** The capability registry explicitly forbids `finance.pay*`, `finance.transfer*`, `finance.purchase*`, `finance.bank_login*`. Preserve the existing prohibition on bank login, transfers, purchases, and money movement. Internal bookkeeping transfers may need a new ledger representation, not an external transfer action.
5. **No personal data in repositories, CI, public artifacts, prompts, or logs.** Use artificial data until explicit later authorization and verified protections.
6. **Scope:** Single finance domain in V1. Multi-currency reports stay separate by currency; do not invent FX conversions. Support Android offline deterministic results even when the PC LLM is unavailable.
7. **Pinned offline model assets:** Model revision, checksum, license and optional install/enable consent must be recorded. No surprise model downloads from financial UI actions.
8. **No automatic training from raw transactions or untrusted imports.** Learning uses confirmed labels; model promotion requires measured regression tests.

## 3. Important gaps and risks found in live code

### P0 — accounting correctness before machine learning

- `account_balances` currently calculates `opening_balance_minor + SUM(amount_minor)` for each account. Verify liability sign conventions, opening balances, cash-account types, and card-payment representation before aggregating cash availability.
- `cashflow` treats positive/negative transactions as inflows/outflows and excludes only those whose linked category has kind `transfer`. Confirm every transfer has consistent classification; a missing category can distort income and discretionary spending.
- Existing commands include transaction create/update/delete, bill create/update/mark_paid, and monthly budget set; there is **no dedicated linked transfer command** or explicit debt APR/minimum-payment terms. Decide how to represent both sides of credit-card repayments and prevent double-counting.
- `bill.mark_paid` can create a ledger transaction. The planner must not subtract a bill again when it has already been paid or when a matching imported transaction exists.
- `budget.set` is a monthly category budget, not a future dated cash-flow plan. Do not repurpose it as a savings allocation or loan contract.
- `voice_expense.py` rounds via `ROUND_HALF_UP` and selects the first matching or fallback account; address ambiguous account choice and reject unexpected fractional precision. The Kernel's `money.rs` rejects silent precision loss.

### P0 — privacy and trust

- `finance` sync defaults on **only for paired devices**; hosted-model Finance access defaults off. Preserve both behaviors. Respect `devices` and `sync` switches at gateway.
- Treat transaction descriptions, merchant names, note fields and imported CSV text as untrusted; never allow them to inject instructions into the assistant or tools.
- Local model use is not equivalent to cloud sharing; verify endpoint allowlisting, no inadvertent telemetry/network calls, and safe logging. Avoid exposing account IDs, balances or merchant information in crash logs.
- CSV/JSON exports are plaintext; ensure warnings, explicit user action, safe share targets, and transient cache cleanup.

### P1 — UI and metadata

- Windows/Android display budget and bill lists, but implementation must verify actual create/edit/delete screens before promising full user management.
- Android Finance UI still includes stale copy stating the app has no internet permission, while the current manifest declares `INTERNET`. Fix privacy messaging before release.
- Real phone/Windows sync, voice pipeline, and hardware acceptance remain separate from CI success.

## 4. Target architecture

```text
Windows WinUI 3 / Android Compose
            |
   typed / voice user intent
            |
Python FastAPI + existing policy broker
            |
     Finance Tools Router (NEW)
          /       \
 Rust Domain Kernel   Python ML Service (NEW, optional)
  |  |  |  |         |--- merchant normalization + rules
  |  |  |  |         |--- baseline classifier (TF-IDF / logistic regression)
  |  |  |  |         |--- optional MiniLM semantic matching
  |  |  |  |         |--- statistical spending estimates
  |  |  |  |         \--- model eval / registry, no direct writes
  |  |  |  |
  |  |  |  \--- daily cash-flow and reserves (NEW)
  |  |  \------ obligations/debt terms/linked transfer logic (NEW)
  |  \--------- event log + financial projections
  \------------ SQLCipher, domain key and device sync
            |
 ADK + LiteLLM -> Ollama local LLM (optional, approved read tools)
            |
  evidence-grounded explanation, never invented amounts
```

**Android:** calculate local deterministic reports via UniFFI. If paired PC/LLM unavailable, display structured summaries and pending insight status; never block Finance basic functionality.

## 5. Proposed source tree (do not create until contract approved)

```text
kernel/src/domains/finance/
  obligations.rs       # derived obligation schedule, payment matching
  debt.rs              # debt terms, minimum payments, liability semantics
  planning.rs          # safe-to-spend and daily cash projection
  forecast.rs          # deterministic range/estimated spending integration

reva_core/finance_intelligence/
  features.py          # normalized, privacy-safe feature extraction
  categorization.py    # rules / TF-IDF baseline; optional MiniLM
  recurrence.py        # recurring merchant candidates
  estimates.py         # rolling baseline, confidence, coverage
  evaluation.py        # leakage-safe evaluation and regression
  model_registry.py    # pinned model and offline install metadata

reva_core/agent/tools/finance.py
  # allowlisted read-only Finance tools, strict typed responses

contracts/finance-intelligence/
  monthly-plan.v1.schema.json
  spending-insights.v1.schema.json
  finance-model-manifest.v1.schema.json

kernel/tests/conformance/finance-intelligence.json
  # shared Rust -> Python UniFFI -> Kotlin UniFFI cases
```

Choose actual location under the existing repository conventions during a read-only architecture review. Avoid duplicating SQL storage outside the Rust Kernel.

## 6. First API contract: `finance.monthly_plan` (proposed, NOT implemented)

Request:

```json
{
  "as_of": "2026-11-01",
  "horizon_days": 30,
  "currency": "USD",
  "scenario": null
}
```

Response envelope:

```json
{
  "schema_version": 1,
  "status": "incomplete",
  "as_of": "2026-11-01",
  "horizon_days": 30,
  "currency": "USD",
  "cash_available_minor": null,
  "confirmed_income_minor": null,
  "scheduled_obligations_minor": null,
  "planned_savings_minor": null,
  "cash_reserve_minor": null,
  "safe_to_spend_minor": null,
  "projected_shortfall_minor": null,
  "daily_balance_floor_minor": null,
  "source_ids": [],
  "assumptions": [],
  "missing_inputs": ["cash_balance", "next_payday", "card_minimum"],
  "estimate_components": [],
  "engine_version": "planning-rules-v1"
}
```

- All money fields are integer minor units, never binary floating-point values.
- `status` is one of `ready`, `provisional`, `incomplete`, `shortfall`.
- `null` means unknown/not calculable, never `$0`.
- `safe_to_spend_minor = 0` means a computed zero; report shortfall separately rather than hiding a negative projection.
- Use lowest cash headroom over the horizon; do not rely on end-of-month surplus alone.
- Identify exact account/currency, timestamps/dates and source records for every component.
- Separate confirmed vs estimated inflows/outflows and include assumption confidence/coverage.
- A user-defined savings reserve may be a virtual earmark, not a second physical bank withdrawal. Avoid double-counting it if already transferred.

## 7. Model preflight / acceptance matrix

| Candidate | Role | Stage | Requirement to ship |
|---|---|---|---|
| Deterministic merchant alias rules | Explainable first classification baseline | First | Correct on held-out fixture; abstain on ambiguous merchant |
| TF-IDF + logistic regression / scikit-learn | Small learned transaction classifier | First experiment | Macro-F1 beats rules; precision of **automatically accepted** labels >= 0.90, measured coverage; no label leakage |
| `sentence-transformers/all-MiniLM-L6-v2` | Semantic merchant candidate retrieval, 384-d embeddings | Optional candidate | Beat TF-IDF under fixed CPU/RAM/latency budget; keep original text private; pin Apache-2.0 revision |
| `urchade/gliner_small-v2.1` | Notes/statement entity extraction | Deferred | Verify finance entity precision, no fabricated dates/currencies; Apache-2.0 card |
| Rolling median / robust seasonal naive | Variable expense forecast baseline | First | Walk-forward forecasts with MAE/WAPE and interval coverage; explicit history insufficiency |
| `amazon/chronos-bolt-tiny` | Forecast model challenger | Deferred | Beat statistical baseline on held-out actual history; no benefit => do not include; Apache-2.0 card |
| Existing `ollama_chat/llama3.1:8b` | Conversational baseline | First | Correct read-only tool selection, grounded numeric claims, measured latency/memory |
| `Qwen3-1.7B` (Ollama-compatible variant) | Smaller conversational candidate | Optional challenger | Beat/pass baseline on test corpus, check exact quantization/license/model revision, memory/CPU and ADK LiteLLM tool compatibility |

Official model cards:
- https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- https://huggingface.co/urchade/gliner_small-v2.1
- https://huggingface.co/amazon/chronos-bolt-tiny
- https://huggingface.co/Qwen/Qwen3-1.7B

**Do not install or download candidate models during preflight without explicit owner authorization.** Read model license, version, and trust-remote-code requirements. Prefer safetensors or verified ONNX, signed manifests, and fixed hashes. CPU benchmark first, optional GPU benchmark if actual compatible hardware exists.

## 8. Data fixture and quality gates

Build a wholly synthetic 30-day USD month anchored to a fixed clock (example November 2026, not the user's private finance data):
- $3,000 expected income across two paydays (with actual deposit dates and funding status).
- Rent, utilities, insurance, loan minimum, credit-card minimum, grocery/fuel variable estimates, and a user-selected reserve/savings goal.
- Separate credit-card purchase and credit-card repayment, both debit/credit legs as required by approved ledger design.
- Expense imported once and attempted again (duplicate suppression).
- Rent due before paycheck; insufficient liquidity despite positive end-of-month net.
- Bill marked paid and matching transaction imported (deduplication, no double obligation).
- Wrong/unknown currency, zero/negative amount, missing payday, missing APR, missing card minimum, disputed/unconfirmed account balances.
- Month boundary, February leap day, DST boundary, payment date vs statement period.
- Late phone sync, same-version amount conflict, failed/retried batch, duplicate event, revoked device.
- Malicious merchant text attempting to override AI tool permissions.

Add 3–6 synthetic months only for forecast and classifier test scaffolding. Use later real, consented and labeled data for meaningful accuracy claims; artificially generated text alone cannot prove real-world generalization.

**Gates**:
1. 100% golden-case financial invariant tests; no double counting, no silent precision loss.
2. Rust/Python/Kotlin cross-binding conformance agrees byte-for-byte on canonical numeric fields for shared fixture.
3. No net account change from read-only reports or LLM explanation.
4. Scenario simulations never mutate ledger; output marked hypothetical.
5. Missing critical inputs => `incomplete` and `null` safe-to-spend; no fabricated value.
6. Forecast challenger beats a time-respecting naive baseline; otherwise keep baseline.
7. LLM financial monetary claims match tool numeric output; no arbitrary tools or external URLs.
8. All release data encrypted at rest, no finance data in logs/CI/model prompts sent to hosted endpoints by default.
9. Baseline REVA CI remains green at each merge SHA; no tests turned into skips.
10. Native Windows, Android-device and LAN sync acceptance remain separate release gates.

## 9. Environment validation (NOT RUN here)

Run these in the **actual clean REVA Windows checkout or a new worktree**, recording exact commits and outputs. Do not run on a dirty or unrelated project worktree.

```powershell
# Read-only baseline and environment checks
git remote -v
git status --short
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
python --version
rustc --version
cargo --version
dotnet --info
java -version
ollama --version
ollama list
Get-CimInstance Win32_ComputerSystem | Select-Object TotalPhysicalMemory
Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM
Get-PSDrive C,D | Select-Object Name,Free,Used

# Run only after repository dependency/install state is understood
cargo test -p reva-kernel
python tools/kernel/build_bindings.py
python -m pytest tests/contract tests/integration/test_domains_finance_api.py tests/integration/test_voice_expense_and_apps_api.py tests/cross_binding -q
dotnet test desktop/Reva.Desktop.sln --configuration Release
# From android/ (when Android SDK/NDK and Gradle dependencies are ready):
# .\gradlew.bat :app:testDebugUnitTest --no-daemon
```

Record disk free space, available RAM, GPU/VRAM, Ollama model list, cold/warm inference timing, tokens/sec, response time, and whether the full Rust + Python + Windows runtime coexists without paging or voice degradation. **None of these machine measurements were verified by GitHub reads.**

## 10. Work slices and review strategy

| Slice | Deliverable | Mandatory test/evidence |
|---|---|---|
| PRE-00 | Current-state ADR/contract + synthetic gold fixture | Reviewer signs off accounting invariants and exact schema |
| FIE-01 | Liability and obligation model/migration | Old SQLCipher DB opens/migrates/backs up; offline replay; cross-binding passes |
| FIE-02 | Dated cash projection and safe-to-spend | 100% invariant golden cases, reference implementation comparison |
| ML-01 | Optional local category baseline | Dataset sheet, train/validation/test boundaries, precision/coverage, offline asset manifest |
| AI-01 | Read-only ADK finance tools | Exact allowlist, complete audit, abstention/missing-data tests, no writes |
| UI-01 | Windows + Android plan and insight display | Accessibility, privacy copy, offline/sync conflict tests |
| E2E-01 | Windows/Android physical acceptance | Actual on-device data-sync/voice tests, no cloud dependencies |

For each: create its own focused branch/PR against verified current base, commit-specific test evidence, PR review, and merge only after green CI. Do not mix PR #33 remediation into Finance branches. Include migration rollback/recovery tests and v1 contract backward compatibility.

## 11. Local preflight exit criteria / GO-NO-GO

**GO to FIE-01 implementation only when:**
- [ ] PR #33 disposition confirmed: either merged with healthy main CI, or a formally documented isolated branch base.
- [ ] Current local REVA checkout, branch and clean/dirty status validated.
- [ ] Existing Rust, Python, C#, Android and cross-binding tests all pass at the selected base.
- [ ] Liability/card-payment/transfer accounting design approved.
- [ ] Exact `monthly_plan` request/response contract and incomplete-input behavior approved.
- [ ] SQLCipher migrations, event replay, sync semantics and backward compatibility mapped.
- [ ] Synthetic golden fixture, expected daily balances and no-double-count cases reviewed.
- [ ] No financial data leaves local host or developer machine without explicit consent.

**GO to ML-01 only when:**
- [ ] Deterministic results correct and passing.
- [ ] Model assets pinned and licenses confirmed; no unapproved downloads.
- [ ] Labeled dataset, leakage-free split, baseline, evaluation and abstention criteria defined.
- [ ] Measured RAM/CPU/GPU/latency is acceptable alongside REVA voice workload.

**GO to AI-01 only when:**
- [ ] Approved read-only finance capability registered in broker/ADK.
- [ ] Policy and audit tests protect against merchant-text prompt injection.
- [ ] Model groundedness harness verifies every answer amount and source; no writes without T2 grant.

**Current conclusion:** PRE-00 is ready to begin. FIE-01, ML-01 and AI-01 remain gated by local baseline, financial contract approval, and evidence. No source code was changed or pushed in this preflight.

## 12. Copy/paste task for the implementation agent (PREFLIGHT ONLY)

> **Repository:** `ckvishwa/Reva`. Target Finance Intelligence Engine + read-only Local AI, local-first. Before editing, inspect current HEAD, origin/main, working tree, open PR #33 and current CI. Read `CLAUDE.md`, ADR/ARD, the actual Rust Finance source, Python domain API and broker, ADK tool list, Android Kotlin Finance repository, WinUI Finance page, and conformance tests. Do not assume earlier documents are current.
>
> **Scope:** READ-ONLY PRE-IMPLEMENTATION AUDIT ONLY. Do not edit code, install dependencies, download models, touch real financial data, merge, push, change secrets, or enable hosted models. Verify baseline tests if environment permits. If tests cannot run, mark them NOT RUN.
>
> Produce: (1) exact code/paths and commit evidence, (2) gaps between existing and proposed Finance Intelligence, (3) liability/card/transfer accounting design, (4) v1 `monthly_plan` contract, (5) synthetic golden fixture/test expected values, (6) proposed reversible schema migrations and sync compatibility plan, (7) candidates MiniLM/TF-IDF/Qwen3 vs existing Llama/Chronos only as optional evaluation, (8) resource/latency and license report, (9) security and privacy threat review, (10) test matrix and 100% invariant acceptance gates, (11) prioritized, small implementation PRs.
>
> Stop and report if local baseline is red, repository state is dirty, PR #33 conflicts, cross-binding changes break Android, financial numbers double-count, model selection needs a network download, or safeguards would require relaxation. Never claim release readiness from CI alone.
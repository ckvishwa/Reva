# kernel/ — REVA Domain Kernel (crate `reva-kernel`)

One Rust crate holds every life domain's storage and rules (ADR-027). It runs inside the Windows
Core (Python binding) and inside the Android app (Kotlin binding). It stores, validates and
computes. It never touches the network, calls a model, or reads anything except its own data files.

Status (FIN-1): store, event log, outbox, tombstones, projections and the **Finance** domain.
Other domains follow the same shape in later slices. Spec: `docs/spec/REVA_v2.0/02_ARD/ARD-700_Life_Domains_and_Domain_Kernel_v2.0.md`.

## Layout

```
src/lib.rs            UniFFI exports and test-visible internals
src/handle.rs         DomainHandle: command / query / export / import_data / pending_events / apply_events / ack
src/store/            SQLCipher open + key handling, migrations (backup first), encrypted backup, recovery
src/events/           event envelope (contracts/domain-event.schema.json), log, outbox, tombstones, Lamport clock
src/domains/finance/  money, schema, commands, queries, projections
src/import/           CSV (per-bank column mapping), OFX 1.x/2.x, Kernel JSON export
src/export/           CSV and JSON export
src/today.rs          read-only cross-domain Today summary
bindgen/              build tool that generates the bindings (crate reva-kernel-bindgen, never shipped)
tests/                native Rust tests + the shared conformance suite (tests/conformance/finance.json)
tests/kotlin/         Kotlin/JVM runner for the same suite
bindings/             GENERATED python/ and kotlin/ (git-ignored, rebuilt by tools/kernel/build_bindings.py)
```

## Build and test

```
cargo test -p reva-kernel                               # native: unit, recovery, sync, import, registry, no-network
cargo test -p reva-kernel --release --test perf -- --ignored --nocapture   # 10,000-record timing
python tools/kernel/build_bindings.py                   # library + Python and Kotlin bindings
python -m pytest tests/cross_binding                    # conformance suite through the Python binding
python tools/kernel/run_kotlin_conformance.py           # same suite through the Kotlin binding on the JVM
python tools/kernel/build_android.py                    # arm64-v8a and x86_64 with cargo-ndk, verified
```

Windows needs Strawberry Perl on PATH (and Git for Windows' Perl for the Android build) because
SQLCipher links a vendored OpenSSL that is compiled from source. See the docstrings in `tools/kernel/`.

## The contract with the host

* **Keys.** The host owns the vault (`KeyProvider`: `load_key`, `store_key`). On a fresh install the Kernel
  generates a 32-byte key, asks the host to store it, and only then creates the data file. If the vault has
  no key but a data file exists, the Kernel returns `Locked` and never invents a key. The Kernel never
  persists a key itself and never replaces one.
* **Errors.** `Locked`, `WrongKey`, `Corrupt`, `MigrationFailed`, `Validation{field, reason}`, `Conflict`,
  `NotFound`, `Deleted`, `Internal`. Failed opens never modify the file. `WrongKey` and `Corrupt` are told
  apart with a key-check sidecar (`finance.sqlite3.kcv`: an HMAC of a constant under the key; it reveals
  nothing usable about the key). Without the sidecar a failed open of a well-formed file reports `WrongKey`.
* **Threads.** Calls are blocking and short. Hosts call them off the UI thread (AR-DOM-015). One file is
  serialized by a mutex.
* **Time.** Queries that depend on "today" take `as_of`; only `created_at` stamps read the clock.

## Deviations from ARD-700 section 2.1 (to be folded into the ARD)

* `import` is `import_data(format, data, options_json)`: `import` is a Python keyword, and an import needs
  options (target account, column mapping, `dry_run`).
* Error variants carry a `detail` field, not `message`: a field called `message` collides with the Kotlin
  `Throwable.message`.
* Event `signature` is an HMAC-SHA256 integrity tag under a key derived from the local domain key. It proves
  an event was not altered on this device. It is **not** yet a public-key signature, so another device cannot
  verify it. Cross-device verification arrives with pairing (S13); `apply_events` currently validates shape,
  schema, domain and tombstone consistency only.
* A dry-run import executes the real import inside a transaction that is rolled back, so its report equals
  the real run's. It commits nothing.
* `bill` and `recurring` are one aggregate: a bill has a `recurrence` and a `kind` (`bill`, `subscription`,
  `income`). `bill.mark_paid` only records payment; it can optionally record the matching ledger transaction.

## Money

Integer minor units plus an ISO 4217 code. No floats. Parsing refuses to round: more decimals than the
currency allows is a rejected row. Budgets and reports are per currency; there is no currency conversion.

## What cannot exist

No command moves money, pays a bill, buys anything or stores bank credentials. `tests/registry.rs` pins the
exact command list and rejects money-movement vocabulary; `tests/no_network.rs` fails the build if a network
crate enters the dependency tree or network APIs appear in the source.

## Android

`tools/kernel/build_android.py` builds `libreva_kernel.so` for arm64-v8a and x86_64 (NDK 27, API 26) with
SQLCipher and OpenSSL linked statically (the only `NEEDED` libraries are the Android system ones). Running
the Kotlin suite on an emulator or device is part of S11 (Android shell).

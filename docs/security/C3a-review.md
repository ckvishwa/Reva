# C3a security review

Scope: `brain/LocalBrain.kt`, `brain/KernelQueries.kt`, the `PolicyReplies` integration and app wiring. `PolicyReplies` authorizes rule proposals against the shared registry before calling the local query. The only enabled new data route is read-only `today.get` through the Rust Kernel-backed Finance repository. The planner registry has an offline-only entry; no hosted endpoint, token, key or transcript logging is added.

Findings fixed during review: an unexpected planner exception escaped the turn coroutine and could leave the UI thinking; it now returns a typed failure with a fixed message. An unexpected repository exception could expose internal details through the same path; it now returns a fixed local-data failure while cancellation still propagates. Both cases were reproduced by failing tests before the fixes. Timeout, cancellation, missing provider, locked Kernel and forbidden-action isolation have passing tests.

Open C3 work: hosted provider consent and network-capture tests, mode transitions, full Finance spending summary, physical no-PC voice/Finance acceptance, and two-tier 30-minute profiling. No hardware PASS is claimed.

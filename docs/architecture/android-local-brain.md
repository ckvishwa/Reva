# Android local brain (C3a)

The existing `VoiceSession` owns the user-facing state machine and `turn_epoch`. `VoiceController` cancels a superseded turn and drops replies whose epoch is stale. `PolicyReplies` runs phone/PC action parsing and the shared capability registry's `authorize()` before any local query. A forbidden request therefore never reaches a provider or Finance repository.

`KernelQueries` answers the supported `today.get` rule from `KernelFinanceRepository.today()`. The repository opens the local Rust Domain Kernel on `Dispatchers.IO`; no PC or hosted provider is needed. Locked or damaged data yields a typed failure, and unexpected errors are reduced to a fixed message without leaking paths or keys. A full spending summary is still unavailable and is stated as such; no partial transaction page is presented as a total.

`LocalBrain` handles open questions through an explicit `PlannerRegistry`. C3a registers only `offline-lite`, which returns an unknown result and states that advanced reasoning is unavailable. Missing providers, timeouts, cancellations and planner failures have separate fixed messages. There is no fallback from a failed provider to another provider. A planner's text is never execution evidence. C3b will add disclosed, opt-in modes and provider configuration; until then hosted reasoning remains absent.

Android JVM validation on the C3a source tree: 316 passed, 0 failed, 0 skipped, including nine C3a tests. Native phone voice, no-PC Finance, provider, and battery/thermal acceptance remain pending hardware checks.

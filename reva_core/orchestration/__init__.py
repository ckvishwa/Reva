"""Use-case coordination. Never calls vendor SDKs, never writes SQL,
never bypasses policy. In Phase 0 this is limited to Core lifecycle
(startup/shutdown/health) — there are no use cases to orchestrate yet."""

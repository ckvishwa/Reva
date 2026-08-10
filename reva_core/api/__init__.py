"""Transport boundary: validation, serialization, loopback-only binding.

No SQL, no domain rules, no policy decisions. Phase 0 exposes exactly
two routes (`/health`, `/version`), both read-only and harmless, so no
authentication exists yet — see docs/architecture/runtime-model.md for
why that is safe now and what changes the moment a domain route lands.
"""

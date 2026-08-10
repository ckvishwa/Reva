"""Provider contracts and provider result contracts.

Narrow typed Protocols for LLM/embedding/STT/TTS providers. No vendor SDK
types appear here or leak past an adapter. No provider implemented here
may mutate durable state, create memory, or bypass orchestration/policy —
this module only defines the shape of a request/response.

Real provider adapters are out of Phase 0 scope; see `tests/fixtures/`
for deterministic fakes used to test the contracts.
"""

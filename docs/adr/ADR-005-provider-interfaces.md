# ADR-005: Typed Provider Interfaces for LLM/Embedding/STT/TTS

**Status:** Accepted

## Context

REVA must support a replaceable cloud LLM provider (PRD §3, §8.1) and
future embedding/STT/TTS providers, without those vendors' SDKs
leaking into Core's domain logic, and without CI ever needing a real
cloud credential.

## Decision

Define narrow `typing.Protocol` interfaces (`LLMProvider`,
`EmbeddingProvider`, `STTProvider`, `TTSProvider`) in
`reva_core/models/`, each with one async method and Pydantic
request/response contracts. Real adapters implement the Protocol and
translate vendor exceptions into `ProviderError` at the boundary.
Deterministic fakes implement the same Protocol for tests.

## Alternatives considered

- **LangChain or a similar agent/provider framework** — explicitly
  excluded by the product constraints; far more surface area (chains,
  agents, memory abstractions) than four narrow interfaces need, and
  it would become the thing REVA's own `orchestration/`/`memory/`
  should own.
- **ABCs instead of Protocols** — would work equally well; Protocols
  were chosen because a fake provider satisfying the interface
  structurally (no explicit inheritance required) is a smaller
  imposition on test code, and `runtime_checkable` still allows
  `isinstance` checks where useful.
- **One giant `Provider` interface for everything** — rejected; LLM,
  embedding, STT, and TTS have unrelated request/response shapes and
  failure modes, so one interface would force irrelevant methods onto
  every adapter.

## Consequences

- Adding a real provider (e.g. a specific LLM vendor) means writing one
  adapter class and zero changes to orchestration.
- `ProviderError` normalizes unavailable/timeout/invalid-response/
  auth-failure/rate-limited conditions so orchestration never
  pattern-matches on a vendor's exception hierarchy.
- No real adapter exists in Phase 0 — only Protocols and fakes.

## Security implications

Vendor SDK types and vendor-specific error payloads never reach
domain logic or logs, reducing the chance a vendor error message
containing sensitive request content gets logged unredacted somewhere
outside the provider boundary.

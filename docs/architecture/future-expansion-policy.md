# Future Expansion Policy

This document preserves the future-expansion rules REVA is built under.
It does not authorize building any of the future capabilities it
describes — it constrains how they must be justified and designed
*when* someone actually implements them.

## Forbidden until concretely justified

Do not build, in any phase without a concrete, documented requirement:

- A plugin marketplace.
- A generic integration runtime / universal connector.
- A generic workflow engine.
- An autonomous-agent framework (`AgentRuntime`, `GenericWorkflowEngine`,
  `IntegrationManager`, `PluginRegistry`, or similar).
- A microservice split of REVA Core.
- Redis, Kafka, RabbitMQ, an event bus, or a service mesh.
- Postgres, Supabase, Firebase, or any cloud database as REVA's
  authoritative store.
- LangChain or an equivalent generic agent-orchestration dependency.
- A custom RPC system in place of the documented HTTP/WebSocket
  boundary.

## Required for every new client

- Must use REVA Core's contracts/API.
- Must not duplicate Core business logic (orchestration, memory
  semantics, policy, audit).

## Required for every new provider

- Must implement one of the typed Protocols in `reva_core/models/`.
- Must not directly mutate durable user state.
- Must not bypass orchestration or policy.
- Must not create durable memory on its own authority.

## Required for every new integration or capability

Before implementation, define:

1. User value.
2. Product phase.
3. Data accessed and retained.
4. Permission requirements.
5. Read/draft/write/execute boundary.
6. Approval behavior.
7. Offline behavior.
8. Failure behavior.
9. Audit requirements.
10. Revocation/deletion behavior.
11. PRD update.
12. Threat-model update.
13. ADR, if it changes architecture.
14. Acceptance tests.
15. Rollback/disable strategy.

## Action classification

Every future action must be classified before implementation:

- `READ_ONLY`
- `PREPARE_OR_DRAFT`
- `LOCAL_REVERSIBLE`
- `EXTERNAL_REVERSIBLE`
- `EXTERNAL_CONSEQUENTIAL`
- `DESTRUCTIVE`

`EXTERNAL_CONSEQUENTIAL` and `DESTRUCTIVE` actions are unsupported in
V1 (PRD §6, §9) regardless of how compelling a future request seems.

## Persistent-data changes

Any new persisted field or table requires: a migration, repository
tests, retention/deletion behavior, export implications, and sync
implications — considered together, not bolted on after the fact.

## Cloud posture

Cloud features remain optional where feasible. Local-first data must
not become mandatory cloud-hosted data without an explicit ADR.

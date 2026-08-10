# ADR-017: Google ADK Is an Orchestration Dependency, Not a REVA Domain Boundary

**Status:** Accepted (Phase 1B, Slice 5)

## Context

Slice 5 needed REVA's typed assistant to answer questions that require
retrieving the user's own durable memory (e.g. "what did I ask you to
remember about X") through real model reasoning and real tool-calling,
rather than the Phase 1A `FakeLLMProvider` echo. Google's Agent
Development Kit (ADK, `google-adk` on PyPI) supplies an agent/tool/
session runtime (`Agent`, `Runner`, session services, function-tool
wrapping) that would otherwise have to be hand-built.

REVA's architecture rule (docs/architecture/module-boundaries.md) is
that Core owns all domain logic and any external framework is a
replaceable implementation detail behind a narrow interface — the same
reasoning ADR-005 already applied to LLM/embedding/STT/TTS providers.
ADK must follow that rule, not become a second architecture.

## Decision

ADK is consumed behind a framework-neutral `AssistantOrchestrator`
Protocol (`reva_core/agent/orchestrator.py`, zero `google.adk` imports):

```python
class AssistantOrchestrator(Protocol):
    async def respond(
        self, *, user_id: str, conversation_id: str, message: str, correlation_id: str
    ) -> AssistantResponse: ...
```

`AdkAssistantOrchestrator` (`reva_core/agent/adk_orchestrator.py`) is
the only implementation. `TypedInteractionService.handle_typed_message`
(`reva_core/orchestration/typed_interaction.py`) is the single call
site: when an orchestrator is configured it replaces the
`LLMProvider.complete()` call for reply generation — nothing else
about that method changes. Conversation/message persistence, the
`remember:` command's explicit memory write, and the
`typed_request_received` audit event are all identical whether or not
ADK is in play.

```
Windows Desktop
      |
REVA Core API  (POST /v1/messages, unchanged contract)
      |
TypedInteractionService.handle_typed_message
      |
AssistantOrchestrator  <-- the escape hatch: swap the implementation
      |                     below this line without touching anything
AdkAssistantOrchestrator     above it
      |
ADK Runner -> single RevaAgent -> search_memory / get_current_time
      |
MemoryRepository / AuditRepository (existing storage/audit boundary)
```

If ADK were ever replaced (a different framework, a hand-rolled tool
loop, a future provider), only `agent/adk_orchestrator.py` and its ADK
imports change. `orchestration/`, `api/`, `storage/`, and the Desktop
client are all untouched, because none of them import `google.adk`.

### Only one agent, only two tools, read-only

`RevaAgent` (`reva_core/agent/reva_agent.py`) is the only agent — no
sub-agents, no planner, no `SequentialAgent`/`ParallelAgent`/`LoopAgent`
graph. It has exactly two tools
(`reva_core/agent/tools/{memory,system}.py`):

- `search_memory(query, limit)` — calls `MemoryRepository`/
  `AuditRepository` directly, the same repository/audit path
  `TypedInteractionService.query_memories` already uses for the
  explicit Memory Search feature (same SQL, same
  `memory_query_requested`/`memory_query_completed` audit actions).
  Bounded to 10 results regardless of what the model asks for.
- `get_current_time()` — wraps the existing `shared/time.utc_now()`
  abstraction; no new infrastructure.

**There is no `remember`/`create_memory`/`update_memory`/
`delete_memory` tool, and there never will be one on this agent.**
ADR-006 requires every durable memory write to be a distinct, explicit
user action outside model control. The smallest way to guarantee that
holds even under adversarial/prompt-injected input is to never give
the model a tool capable of a write at all — not a policy check, not
an approval step, an absent capability. `POST /v1/memories` (the
explicit Remember path) is completely unchanged by this slice and
never touches the orchestrator.

### Session vs. durable memory

ADK's `InMemorySessionService` holds ADK's own per-conversation runtime
state (the message history fed back to the model within one
conversation this process is currently running). It is in-memory,
per-process, and gone on restart — never persisted, never REVA durable
memory. REVA's durable, user-owned memory lives only in the `memories`
SQLite table, reached exclusively through `search_memory` (read) and
`POST /v1/memories` (write). `AdkAssistantOrchestrator` never writes
anything into ADK's session store that isn't already disposable
runtime state, and never reads REVA's `memories` table except through
`MemoryRepository`.

### Config-gated, not the new default

`REVA_ASSISTANT_ORCHESTRATOR` (`Settings.assistant_orchestrator`)
defaults to `"deterministic"` — every existing test, and a bare
`python -m reva_core --serve`, get the exact Phase 1A/1B
`FakeLLMProvider` echo behavior, unchanged. Setting it to `"adk"` is
what activates `AdkAssistantOrchestrator`, gated at
`CoreLifecycle.startup()`. This is what makes Slice 5 additive rather
than a default-behavior change to every existing test and to the
Slice 3/4 E2E scripts.

## ADK version pin

`google-adk==2.6.3`, `litellm==1.96.0` — both **exact pins**, not
ranges.

- **Why exact, not a range:** ADK is pre-3.0 and its `Runner`/session/
  tool-declaration internals have moved across minor versions (its own
  changelog documents session-service and function-declaration
  behavior changes release to release). A floating range risks a
  transitive upgrade silently changing tool-calling or session
  semantics underneath REVA without anyone deciding that on purpose.
- **Why 2.6.3 specifically:** the latest stable release at
  implementation time (`pip index versions google-adk`), `Requires-
  Python: >=3.10` (REVA requires `>=3.12`, satisfied), and its base
  install (no extras) resolves against already-installed `fastapi
  0.141.1`/`pydantic 2.13.4` without conflicting with REVA's own
  `fastapi>=0.111,<1`/`pydantic>=2.7,<3` floors.
- **`[extensions]`/`[test]` extras deliberately NOT installed:** ADK's
  `extensions` extra pulls in ~70 transitive packages unrelated to this
  slice (`langgraph`, `llama-index-core`, `kubernetes`, `docker`,
  `anthropic`, `k8s-agent-sandbox`, BigQuery/Bigtable connectors,
  etc.) — confirmed by installing it once, inspecting the dependency
  list, and reinstalling without it. Only base `google-adk` plus a
  directly-declared `litellm` (needed for the `LiteLlm` model wrapper)
  are installed. This is the concrete meaning of "isolated
  orchestration dependency": not just import isolation in the code,
  but dependency-tree isolation too.
- **Upgrade policy:** bump the exact pin deliberately, in its own
  commit, after re-running the full Slice 3/4/5 E2E suite against the
  new version — never let it float via a range.

## Model: local Ollama via LiteLlm, not a cloud credential

`Settings.adk_model` defaults to `"ollama_chat/llama3.1:8b"` against
`Settings.adk_model_api_base = "http://127.0.0.1:11434"`, wired through
ADK's `LiteLlm` wrapper (`google.adk.models.lite_llm.LiteLlm`).

- **Why not a Gemini/cloud credential:** this environment has no
  `GOOGLE_API_KEY`/Vertex credential configured, and Phase 0 explicitly
  excludes cloud provider credentials from Core's default runtime (see
  `.env.example`). A real, already-installed local Ollama instance
  gives a genuinely real model call — real inference, real
  tool-calling, zero network egress — without inventing a new
  credential requirement this project doesn't otherwise have.
- **Why `llama3.1:8b` and not `qwen2.5-coder:7b`** (the model already
  present locally before this slice): empirically tested both against
  Ollama's native `/api/chat` tool-calling endpoint with an identical
  tool schema. `qwen2.5-coder:7b` returned its intended tool call as a
  JSON blob inside the plain-text `message.content` field rather than
  the structured `message.tool_calls` array Ollama/OpenAI-compatible
  clients (and therefore ADK) expect — a chat-template limitation of
  that specific model on this Ollama version, not a REVA or ADK bug.
  `llama3.1:8b` returned a correctly structured `tool_calls` response
  on the same prompt/schema. Verified with a disposable script driving
  the real `AdkAssistantOrchestrator` end to end before adopting it as
  the default.
- **This is genuinely swappable**, exactly like any other
  `LLMProvider`: `LiteLlm` supports any provider `litellm` does
  (Vertex/Gemini, OpenAI, Anthropic, other local runtimes) by changing
  `adk_model`/`adk_model_api_base` — no code change.

## Alternatives considered

- **Hand-rolled tool-calling loop against `litellm` directly, no ADK**
  — would avoid the dependency entirely, but REVA would then own
  session/event-loop/function-declaration plumbing ADK already
  provides and tests. Rejected: more code to maintain for the same
  outcome, and the explicit ask was to introduce ADK.
- **ADK's own `MemoryService`/persistent session backends
  (`DatabaseSessionService`, ADK memory tools)** — rejected outright.
  Using ADK's memory abstractions as REVA's durable store would create
  a second, parallel memory system and violate the single-owner
  `memories` table boundary this whole slice is built to protect.
- **A cloud model (Gemini) via `google-genai` directly** — the
  technically "native" ADK path, but requires a credential this
  environment doesn't have. Deferred; `LiteLlm` already makes this a
  config change, not a code change, whenever a credential exists.
- **Multi-agent (planner + memory agent + coordinator)** — explicitly
  out of scope; a single `RevaAgent` with two tools is the entire
  surface Slice 5 needs, and ADK's multi-agent primitives
  (`SequentialAgent`, etc.) are unused.

## Consequences

- A new production dependency exists (`google-adk`, `litellm`), but it
  is inert unless `REVA_ASSISTANT_ORCHESTRATOR=adk` is set — the
  default `python -m reva_core --serve` and every existing test are
  byte-for-byte the Phase 1A/1B deterministic behavior.
- `google.adk` imports are confined to two files
  (`agent/reva_agent.py`, `agent/adk_orchestrator.py`); `agent/tools/`
  has zero ADK imports and is testable as plain REVA code.
- Any future orchestration change is scoped to
  `agent/adk_orchestrator.py` plus whatever new implementation is
  added — `AssistantOrchestrator` itself does not need to change.

## Security implications

- **ADR-006 is unweakened, not just "unbroken": there is no tool an
  attacker's prompt injection could invoke to create a durable
  memory**, because no such tool is registered on `RevaAgent` at all.
  This is a stronger guarantee than a policy check that could
  theoretically be bypassed — the capability doesn't exist in this
  process.
- `search_memory`'s only parameters are `query`/`limit` — no
  device/owner-override parameter reaches the model, so a crafted tool
  call cannot redirect a search to another device's data. Ownership
  scope (`origin_device_id`, the SQLite connection) is bound at
  tool-construction time, entirely outside model control.
- Audit metadata for `search_memory`/orchestration events never
  includes raw query or reply text — only lengths/counts — consistent
  with every other REVA audit event and enforced the same way
  (`AuditEvent`'s `SafeMetadata` validator).
- Any ADK/model/tool failure is caught and normalized to the existing
  `ProviderError` type before it can reach a caller — no vendor
  exception text, and no secret, ever crosses that boundary. This
  reuses Phase 1A's existing provider-error-normalization pattern
  (ADR-005) rather than inventing a second one for ADK specifically.

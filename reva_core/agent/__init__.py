"""Assistant orchestration.

`orchestrator.py` defines the framework-neutral `AssistantOrchestrator`
boundary (`AssistantResponse` + a `Protocol`) that the rest of Core
depends on. Everything else in this package is the Google ADK
implementation of that boundary — `reva_agent.py` (the one `RevaAgent`
LlmAgent), `adk_orchestrator.py` (`AdkAssistantOrchestrator`, ADK
Runner/session plumbing), and `tools/` (the two read-only functions
exposed to the model).

ADK imports are isolated to `reva_agent.py` and `adk_orchestrator.py`.
`tools/` is plain REVA repository/audit code with zero ADK imports —
ADK wraps a plain Python function as a tool by inspecting its type
hints and docstring, so the tools themselves don't need to know ADK
exists. See docs/adr/ADR-017-google-adk-orchestration-dependency.md.
"""

# ADR-008: Allowlisted Tool Model

**Status:** Accepted (tools not yet implemented — Phase 3)

## Context

REVA may perform a small set of safe desktop actions (open app/file/
folder/URL, copy text, draft content) but must never execute arbitrary
commands or perform destructive/consequential operations (PRD §6, §8.5,
§9).

## Decision

Every tool REVA can invoke is an explicit, named, allowlisted
implementation under `tools/`. There is no generic "run this command"
or "execute this code" tool, ever. Each tool request is described by
the `ToolRequest` contract (`shared/contracts/tool.py`) and must pass
through `policy/` before `tools/` executes anything.

## Alternatives considered

- **A generic shell/command tool with an allowlist of permitted
  commands** — rejected; command allowlisting is far more fragile than
  action allowlisting (a permitted command can still be invoked with
  dangerous arguments) and reintroduces exactly the arbitrary-execution
  risk the PRD excludes.
- **A code-execution sandbox tool** — rejected outright by the non-goal
  list; not part of REVA's product surface at all.

## Consequences

- Adding a new capability means writing a new, narrowly-scoped tool
  function with its own risk classification — not extending a generic
  executor's allowlist.
- `ToolRiskLevel`/`ToolApprovalState`/`ToolExecutionState` already model
  the approval lifecycle every tool call will go through.

## Security implications

This is security invariant #3 and #4 and directly implements PRD
non-goals against arbitrary shell/PowerShell/terminal/code execution
and browser automation. It is the primary mitigation for a
prompt-injection attempt that tries to get REVA to "just run this
command."

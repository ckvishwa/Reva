# ADR-012: No Arbitrary Command Execution

**Status:** Superseded by ADR-042 (2026-10-16). Historical decision; do not apply to new slices.

## Context

REVA's non-goals explicitly exclude arbitrary shell, PowerShell,
terminal, or code execution, and browser click/type automation (PRD
§6). This must be an architectural guarantee, not a policy someone
could accidentally code around.

## Decision

No module in this codebase — now or in any planned phase — implements
a tool, endpoint, or code path that accepts a string and executes it as
a shell command, PowerShell script, or arbitrary code. `tools/`
(PLANNED) will only ever contain named, parameter-typed functions for
specific allowlisted actions (ADR-008). No `subprocess.run(user_input)`
pattern, no `eval`/`exec` on user or model-generated content, anywhere.

## Alternatives considered

- **A restricted/sandboxed shell** — rejected; sandboxing shell access
  is a much harder security problem than not having shell access, and
  the product does not need it.
- **An opt-in "developer mode" with shell access** — rejected; would
  create a second, less-scrutinized code path with the exact risk this
  ADR exists to prevent, and is explicitly out of scope per the
  non-goals.

## Consequences

- Any future feature request for "let REVA run this script" must be
  rejected or escalated to a full PRD/threat-model/ADR update — it
  cannot land as a small addition to an existing tool.
- Code review must treat any `subprocess`, `os.system`, `eval`, or
  `exec` call touching untrusted input as a hard blocker, not a style
  comment.

## Security implications

This is security invariant #3 and the primary defense against
prompt-injection escalating to remote code execution — even a fully
compromised LLM response cannot execute anything beyond the
allowlisted tool surface.

# ADR-002: PySide6 for the Windows Desktop Client

**Status:** Accepted (client not yet implemented — Phase 1+)

## Context

REVA V1's primary surface is a Windows desktop app: system tray, a
compact assistant panel, voice controls, Memory Manager, Reminders, and
Settings (PRD §7). The client must be native-feeling on Windows and
share a language/runtime story compatible with a Python-first Core.

## Decision

The Windows desktop client will be built with PySide6 (Qt for Python).

## Alternatives considered

- **WinUI3/C#** — best native fit, but forces a second language/runtime
  purely for the UI, duplicating tooling and CI for one client.
- **Electron** — cross-platform and familiar web stack, but heavy
  runtime footprint conflicts with the "idle memory under 500MB"
  performance target (PRD §13) and adds a Node dependency to a
  Python-first project for no architectural benefit.
- **Tauri** — lighter than Electron, but again a second language stack;
  no compelling reason to leave Python given PySide6 exists.

## Consequences

- Desktop client and Core share one language, easing local development
  and eventual code/tooling reuse for anything that isn't UI-specific.
- PySide6's LGPL licensing must be respected (dynamic linking; no
  redistribution issue for how REVA will ship).
- The client talks to Core only through the localhost API — it is not
  in-process with Core, so this choice does not create a tighter
  coupling than the API boundary already implies.

## Security implications

None beyond the general client/Core boundary rules in
`docs/architecture/module-boundaries.md` — the UI must not embed
domain logic, SQL, or policy decisions regardless of framework.

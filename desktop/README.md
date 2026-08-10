Status: PLANNED
Target phase: Phase 1 — Personal memory vertical slice (first UI), full surface across Phases 2-3
Responsibility: Windows PySide6 desktop client — system tray, compact assistant panel, voice controls, Memory Manager, Reminders view, Activity History, Settings. Talks to REVA Core only through the authenticated localhost API boundary (`reva_core/api/`); owns no domain logic, no SQL, and no policy decisions itself (ADR-002, ADR-007).


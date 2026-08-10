Status: PLANNED
Target phase: Phase 3 — Safe desktop help
Responsibility: Authorization, approval requirements, and risk decisions for tool execution. Always sits between `orchestration/` and `tools/`; no caller may bypass it (security invariant #5). The `ToolRiskLevel` / `ToolApprovalState` / `Permission` contracts this module will enforce already exist in `shared/contracts/` — only the decision engine is deferred.

Status: PLANNED
Target phase: Phase 1 — Personal memory vertical slice
Responsibility: Memory semantics, retention rules, and retrieval coordination (keyword + future semantic search). Owns *whether* something should be remembered and how it is recalled with source attribution. Must never contain SQLite queries or vector-provider implementation directly — those live in `storage/` and a future retrieval provider behind a typed interface.

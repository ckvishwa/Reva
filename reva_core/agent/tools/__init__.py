"""Tools exposed to RevaAgent.

Exactly two, both read-only: `search_memory` (memory.py) and
`get_current_time` (system.py). Neither imports `google.adk` — ADK
wraps a plain Python function as a tool by reading its type hints and
docstring, so these stay ordinary REVA code, testable without any ADK
machinery. Adding a memory-mutating tool here would violate ADR-006;
don't.
"""

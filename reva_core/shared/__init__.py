"""Cross-cutting kernel: errors, IDs, time, redaction, logging, base contracts.

Owned here because orchestration, storage, api, models, and audit all
depend on these primitives; none of them may own the others' copy.
"""

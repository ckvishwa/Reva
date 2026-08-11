"""Hybrid lexical + semantic memory retrieval — ranking, embeddings, backfill.

Separate from reva_core/storage/repositories/memory_repository.py (raw
persistence) and reva_core/agent/tools/memory.py (the ADK-facing tool):
this package owns only the scoring/combination logic both of those call
into, so the weighting lives in exactly one place.
"""

from __future__ import annotations

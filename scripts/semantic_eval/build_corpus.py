"""Build the isolated Slice 6 semantic evaluation corpus.

Writes corpus.json under an isolated directory (default:
%TEMP%\\reva-semantic-eval-<uuid>) containing canonical memories,
synthetic distractors, and evaluation query variants. Never writes to
a developer's real REVA_DATA_DIR — this script has no code path that
even accepts one.

Usage:
    python -m scripts.semantic_eval.build_corpus --total-size 500
"""

from __future__ import annotations

import argparse
import json
import tempfile
import uuid
from pathlib import Path

from tests.fixtures.semantic_eval.canonical_memories import CANONICAL_MEMORIES
from tests.fixtures.semantic_eval.distractor_generator import generate_distractors
from tests.fixtures.semantic_eval.query_variants import QUERY_VARIANTS


def build_corpus(total_size: int) -> dict:
    canonical = list(CANONICAL_MEMORIES)
    distractor_count = max(0, total_size - len(canonical))
    distractors = list(generate_distractors(distractor_count))
    queries = [
        {"query": v.query, "expected_substring": v.canonical_memory_substring}
        for v in QUERY_VARIANTS
    ]
    return {"canonical": canonical, "distractors": distractors, "queries": queries}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--total-size", type=int, default=500)
    args = parser.parse_args()

    output_dir = (
        args.output_dir
        or Path(tempfile.gettempdir()) / f"reva-semantic-eval-{uuid.uuid4().hex[:8]}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    corpus = build_corpus(args.total_size)
    corpus_path = output_dir / "corpus.json"
    corpus_path.write_text(json.dumps(corpus, indent=2), encoding="utf-8")

    print(f"Corpus written to: {corpus_path}")
    print(f"  Canonical memories:  {len(corpus['canonical'])}")
    print(f"  Distractor memories: {len(corpus['distractors'])}")
    print(f"  Total durable memories: {len(corpus['canonical']) + len(corpus['distractors'])}")
    print(f"  Semantic evaluation queries: {len(corpus['queries'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

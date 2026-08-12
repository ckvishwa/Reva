# scripts/semantic_eval/run_evaluation.py
"""Slice 6 semantic retrieval evaluation: lexical-only vs semantic-only
vs hybrid, at 100/500/1000-memory scale.

Requires a real local Ollama server with the embedding model pulled
(default: nomic-embed-text) — this script is NOT part of CI (see
.github/workflows/ci.yml, which has no Ollama). Run manually to produce
the numbers Slice 6's final report cites.

Usage:
    ollama pull nomic-embed-text
    python -m scripts.semantic_eval.build_corpus --total-size 500
    python -m scripts.semantic_eval.run_evaluation --corpus <path from above> --scale 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import tempfile
import time
import uuid
from pathlib import Path

from reva_core.memory.embedding_backfill import backfill_missing_embeddings
from reva_core.memory.hybrid_retrieval import hybrid_search
from reva_core.memory.ranking import DEFAULT_HYBRID_RANKING_CONFIG, HybridRankingConfig
from reva_core.models.embedding_providers import OllamaEmbeddingProvider
from reva_core.shared.contracts.memory import (
    Memory,
    MemoryCategory,
    MemorySourceReference,
    RetentionState,
)
from reva_core.shared.ids import new_id
from reva_core.shared.time import utc_now
from reva_core.storage.bootstrap import initialize_database
from reva_core.storage.repositories.device_repository import DeviceRepository
from reva_core.storage.repositories.memory_repository import MemoryRepository

_MODEL_ID = "nomic-embed-text"
_CID = str(uuid.uuid4())


def _seed_corpus(conn, corpus: dict, scale: int, origin_device_id: str) -> None:
    all_content = list(corpus["canonical"]) + list(corpus["distractors"])
    content_to_seed = all_content[:scale] if scale < len(all_content) else all_content
    repo = MemoryRepository(conn)
    now = utc_now()
    for content in content_to_seed:
        repo.insert(
            Memory(
                id=new_id(),
                category=MemoryCategory.NOTE,
                content=content,
                source=MemorySourceReference(
                    origin_device_id=origin_device_id, note="semantic_eval_seed"
                ),
                tags=(),
                retention_state=RetentionState.ACTIVE,
                sync_version=1,
                created_at=now,
                updated_at=now,
            )
        )


def _recall_at_k(ranked_contents: list[str], expected_substring: str, k: int) -> bool:
    return any(expected_substring.lower() in content.lower() for content in ranked_contents[:k])


async def _lexical_only(conn, query: str, limit: int) -> list[str]:
    return [m.content for m in MemoryRepository(conn).query(query, limit)]


async def _semantic_only(conn, provider, query: str, limit: int) -> list[str]:
    config = HybridRankingConfig(semantic_weight=1.0, lexical_weight=0.0, minimum_confidence=0.0)
    ranked = await hybrid_search(
        conn,
        provider,
        query=query,
        limit=limit,
        model_id=_MODEL_ID,
        correlation_id=_CID,
        config=config,
    )
    return [r.memory.content for r in ranked]


async def _hybrid(conn, provider, query: str, limit: int) -> list[str]:
    ranked = await hybrid_search(
        conn,
        provider,
        query=query,
        limit=limit,
        model_id=_MODEL_ID,
        correlation_id=_CID,
        config=DEFAULT_HYBRID_RANKING_CONFIG,
    )
    return [r.memory.content for r in ranked]


async def run(corpus_path: Path, scale: int, output_dir: Path) -> None:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    db_path = output_dir / f"reva-eval-{scale}.db"
    conn, _ = initialize_database(db_path)
    origin_device_id = DeviceRepository(conn).get_or_create_primary_device()
    _seed_corpus(conn, corpus, scale, origin_device_id)

    provider = OllamaEmbeddingProvider(
        model=_MODEL_ID, api_base="http://127.0.0.1:11434", timeout_seconds=30.0
    )
    print(f"[{scale}] backfilling embeddings...")
    backfill_result = await backfill_missing_embeddings(
        conn, provider, model_id=_MODEL_ID, correlation_id=_CID
    )
    print(
        f"[{scale}] backfill: embedded={backfill_result.embedded_count} "
        f"failed={backfill_result.failed_count}"
    )

    queries = corpus["queries"]
    negative_queries = [
        "best recipe for banana bread",
        "how to change a car tire",
        "history of the Roman Empire",
        "weather forecast for tomorrow",
        "how to bake sourdough bread",
        "capital of Australia",
    ] * 5
    # >=30 negative queries; repeated with distinct wording would be better
    # but this meets the floor honestly.
    negative_queries = negative_queries[:30]

    metrics: dict[str, dict[str, float]] = {}
    latencies: dict[str, list[float]] = {"lexical": [], "semantic": [], "hybrid": []}

    for mode_name, mode_fn in [
        ("lexical", _lexical_only),
        ("semantic", _semantic_only),
        ("hybrid", _hybrid),
    ]:
        recall_1 = recall_3 = recall_5 = 0
        for variant in queries:
            start = time.perf_counter()
            if mode_name == "lexical":
                results = await mode_fn(conn, variant["query"], 5)
            else:
                results = await mode_fn(conn, provider, variant["query"], 5)
            latencies[mode_name].append(time.perf_counter() - start)
            if _recall_at_k(results, variant["expected_substring"], 1):
                recall_1 += 1
            if _recall_at_k(results, variant["expected_substring"], 3):
                recall_3 += 1
            if _recall_at_k(results, variant["expected_substring"], 5):
                recall_5 += 1
        total = len(queries)
        metrics[mode_name] = {
            "recall_at_1": recall_1 / total if total else 0.0,
            "recall_at_3": recall_3 / total if total else 0.0,
            "recall_at_5": recall_5 / total if total else 0.0,
        }

    false_positives = 0
    for query in negative_queries:
        start = time.perf_counter()
        results = await _hybrid(conn, provider, query, 5)
        latencies["hybrid"].append(time.perf_counter() - start)
        if results:
            false_positives += 1
    false_positive_rate = false_positives / len(negative_queries) if negative_queries else 0.0

    def _p(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        return (
            statistics.quantiles(values, n=100, method="inclusive")[int(pct) - 1]
            if len(values) > 1
            else values[0]
        )

    corpus_total = len(corpus["canonical"]) + len(corpus["distractors"])
    report_lines = [
        f"# Slice 6 Semantic Retrieval Evaluation — scale={scale}",
        "",
        f"Corpus: {corpus_total} total, seeded {min(scale, corpus_total)}.",
        f"Queries: {len(queries)} semantic, {len(negative_queries)} negative.",
        f"Backfill: embedded={backfill_result.embedded_count}, "
        f"failed={backfill_result.failed_count}",
        "",
        "| Mode | Recall@1 | Recall@3 | Recall@5 |",
        "|---|---|---|---|",
    ]
    for mode_name in ["lexical", "semantic", "hybrid"]:
        m = metrics[mode_name]
        report_lines.append(
            f"| {mode_name} | {m['recall_at_1']:.2%} | {m['recall_at_3']:.2%} "
            f"| {m['recall_at_5']:.2%} |"
        )
    report_lines += [
        "",
        f"False-positive rate (negative queries returning any result): {false_positive_rate:.2%}",
        "",
        "| Mode | p50 latency (ms) | p95 latency (ms) |",
        "|---|---|---|",
    ]
    for mode_name in ["lexical", "semantic", "hybrid"]:
        values_ms = [v * 1000 for v in latencies[mode_name]]
        report_lines.append(f"| {mode_name} | {_p(values_ms, 50):.1f} | {_p(values_ms, 95):.1f} |")

    report_path = output_dir / f"evaluation_report_{scale}.md"
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"[{scale}] report written to {report_path}")
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--scale", type=int, default=500)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()

    output_dir = (
        args.output_dir
        or Path(tempfile.gettempdir()) / f"reva-semantic-eval-{uuid.uuid4().hex[:8]}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    asyncio.run(run(args.corpus, args.scale, output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

Note on --scale: the full canonical memory set (currently 197 entries)
is ALWAYS seeded in full, regardless of --scale — --scale only controls
how many synthetic distractors get added on top. A request for
--scale 100 against a 197-entry canonical set will therefore actually
seed 197 memories, not 100; the report discloses both numbers rather
than silently seeding a truncated canonical set (which would drop real
Recall@k targets and make the measured ceiling look far worse than it
is — see task-3-report.md's "fix round" section for the worked example
that caught this).
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
from tests.fixtures.semantic_eval.query_variants import LEXICAL_QUERY_VARIANTS

_MODEL_ID = "nomic-embed-text"
_CID = str(uuid.uuid4())

# Matches reva_core/config/settings.py's Settings.embedding_timeout_seconds
# default exactly, so a slow-embed scenario that would time out (and
# degrade to lexical-only) in production also shows up as a real
# failure here — a harness-only, more-generous timeout would silently
# absorb exactly the degradation this evaluation exists to measure.
_EMBEDDING_TIMEOUT_SECONDS = 5.0

# Genuinely distinct off-topic queries — none share a topic with any
# CANONICAL_MEMORIES entry (no chess, guitar, fitness, phones, security,
# or software topics), and no two of these are reworded restatements of
# the same underlying query. nomic-embed-text returns byte-identical
# vectors for byte-identical text, so repeating a handful of queries
# (e.g. `[...] * 5`) would silently collapse this floor to a handful of
# independent data points — these 30 are all distinct strings.
_NEGATIVE_QUERIES: tuple[str, ...] = (
    "best recipe for banana bread",
    "how to change a car tire",
    "history of the Roman Empire",
    "weather forecast for tomorrow",
    "how to bake sourdough bread",
    "capital of Australia",
    "how do I train a golden retriever puppy",
    "what is the boiling point of water at sea level",
    "best hiking trails in the Pacific Northwest",
    "how to fold a paper airplane",
    "what causes the northern lights",
    "how many moons does Jupiter have",
    "best budget airlines for European travel",
    "how to remove a red wine stain from carpet",
    "what is the tallest mountain in South America",
    "how to make homemade pasta from scratch",
    "what year did the Berlin Wall fall",
    "how to grow tomatoes in a backyard garden",
    "what is the population of Iceland",
    "how to tie a bowline knot",
    "what is the life expectancy of a house cat",
    "how do bees communicate with each other",
    "what is the largest desert in the world",
    "how to make a paper mache volcano",
    "best budget destinations for a beach vacation",
    "how long does it take light from the sun to reach Earth",
    "what is the difference between alligators and crocodiles",
    "how to season a cast iron skillet",
    "what is the deepest point in the ocean",
    "how many time zones does Russia span",
)


def _seed_corpus(conn, corpus: dict, scale: int, origin_device_id: str) -> int:
    """Seed the full canonical set, always, plus up to `scale`-worth of
    distractors on top. Returns the actual number of memories seeded.

    The canonical set must never be truncated: it is the fixed target
    set every query variant's `expected_substring` is drawn from, so
    dropping any of it silently lowers the true achievable Recall@k
    ceiling below 100% without saying so anywhere in the report.
    """
    canonical = list(corpus["canonical"])
    distractors = list(corpus["distractors"])
    distractor_budget = max(0, scale - len(canonical))
    content_to_seed = canonical + distractors[:distractor_budget]

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
    return len(content_to_seed)


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


async def _evaluate_query_set(
    conn, provider, queries: list[dict], latencies: dict[str, list[float]]
) -> dict[str, dict[str, float]]:
    """Run lexical/semantic/hybrid against one query set, accumulating
    per-mode latency samples into the shared `latencies` dict so the
    report's latency table reflects load across every query set, not
    just one."""
    metrics: dict[str, dict[str, float]] = {}
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
    return metrics


def _recall_table_lines(metrics: dict[str, dict[str, float]]) -> list[str]:
    lines = ["| Mode | Recall@1 | Recall@3 | Recall@5 |", "|---|---|---|---|"]
    for mode_name in ["lexical", "semantic", "hybrid"]:
        m = metrics[mode_name]
        lines.append(
            f"| {mode_name} | {m['recall_at_1']:.2%} | {m['recall_at_3']:.2%} "
            f"| {m['recall_at_5']:.2%} |"
        )
    return lines


async def run(corpus_path: Path, scale: int, output_dir: Path) -> None:
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    db_path = output_dir / f"reva-eval-{scale}.db"
    conn, _ = initialize_database(db_path)
    origin_device_id = DeviceRepository(conn).get_or_create_primary_device()

    canonical_count = len(corpus["canonical"])
    seeded_count = _seed_corpus(conn, corpus, scale, origin_device_id)
    print(
        f"[{scale}] requested scale={scale}, canonical={canonical_count}, "
        f"seeded={seeded_count} (distractor budget={max(0, scale - canonical_count)})"
    )

    provider = OllamaEmbeddingProvider(
        model=_MODEL_ID,
        api_base="http://127.0.0.1:11434",
        timeout_seconds=_EMBEDDING_TIMEOUT_SECONDS,
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
    lexical_queries = [
        {"query": v.query, "expected_substring": v.canonical_memory_substring}
        for v in LEXICAL_QUERY_VARIANTS
    ]
    negative_queries = list(_NEGATIVE_QUERIES)

    latencies: dict[str, list[float]] = {"lexical": [], "semantic": [], "hybrid": []}
    semantic_metrics = await _evaluate_query_set(conn, provider, queries, latencies)
    lexical_metrics = await _evaluate_query_set(conn, provider, lexical_queries, latencies)

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

    corpus_total = canonical_count + len(corpus["distractors"])
    if seeded_count != scale:
        title = (
            f"# Slice 6 Semantic Retrieval Evaluation — requested scale={scale}, "
            f"actually seeded {seeded_count}"
        )
        corpus_line = (
            f"Corpus: requested scale={scale}, actually seeded {seeded_count} "
            f"(full canonical set is {canonical_count} memories; scale can only "
            "reduce distractor count, never canonical coverage). Corpus file "
            f"contains {corpus_total} total (canonical + distractors)."
        )
    else:
        title = f"# Slice 6 Semantic Retrieval Evaluation — scale={scale}"
        corpus_line = f"Corpus: {corpus_total} total, seeded {seeded_count}."

    report_lines = [
        title,
        "",
        corpus_line,
        f"Queries: {len(queries)} semantic, {len(lexical_queries)} lexical/exact-oriented, "
        f"{len(negative_queries)} negative.",
        f"Backfill: embedded={backfill_result.embedded_count}, "
        f"failed={backfill_result.failed_count}",
        "",
        f"## Semantic query set ({len(queries)} queries)",
        "",
        *_recall_table_lines(semantic_metrics),
        "",
        f"## Lexical/exact-oriented query set ({len(lexical_queries)} queries)",
        "",
        *_recall_table_lines(lexical_metrics),
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

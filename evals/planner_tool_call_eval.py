"""30-case real Ollama planner evaluation; no actions are executed."""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

from reva_core.planner.pipeline import validate_decision
from reva_core.planner.providers import OllamaDecisionProvider
from reva_core.planner.windows_executor import build_windows_registry

MODEL = "qwen2.5:3b-instruct-q4_K_M"
CASES = [
    ("What's the capital of Japan?", "answer", "Tokyo"),
    ("What is the capital of France?", "answer", "Paris"),
    ("Name the capital of Germany.", "answer", "Berlin"),
    ("What is the capital of Canada?", "answer", "Ottawa"),
    ("What's the capital of Australia?", "answer", "Canberra"),
    ("Which city is the capital of Italy?", "answer", "Rome"),
    ("What is the capital of Spain?", "answer", "Madrid"),
    ("Tell me the capital of India.", "answer", "Delhi"),
    ("What's the capital of Brazil?", "answer", "Brasília"),
    ("What is the capital of Egypt?", "answer", "Cairo"),
    ("Which city is the capital of South Korea?", "answer", "Seoul"),
    ("What is the capital of Kenya?", "answer", "Nairobi"),
    ("Could you please launch Calculator for me?", "propose_action", "calculator"),
    ("I need Calculator running now.", "propose_action", "calculator"),
    ("Can you bring up Calculator?", "propose_action", "calculator"),
    ("Please get the Calculator app on screen.", "propose_action", "calculator"),
    ("Would you start the calculator app?", "propose_action", "calculator"),
    ("I'd like to use Calculator now.", "propose_action", "calculator"),
    ("Could you please launch Notepad for me?", "propose_action", "notepad"),
    ("I need Notepad running now.", "propose_action", "notepad"),
    ("Can you bring up Notepad?", "propose_action", "notepad"),
    ("Please get the Notepad app on screen.", "propose_action", "notepad"),
    ("Would you start the notepad app?", "propose_action", "notepad"),
    ("I'd like to use Notepad now.", "propose_action", "notepad"),
    ("Open it.", "clarify", None),
    ("Start the app I mentioned.", "clarify", None),
    ("Please launch something useful.", "clarify", None),
    ("Can you open the other one?", "clarify", None),
    ("Bring that up for me.", "clarify", None),
    ("Open my usual app.", "clarify", None),
]


async def main() -> None:
    registry = build_windows_registry()
    capabilities = [
        {"capability_id": key, "args_schema": item["args_schema"]} for key, item in registry.items()
    ]
    provider = OllamaDecisionProvider(model=MODEL, timeout_seconds=60)
    rows = []
    for index, (transcript, expected_kind, expected_value) in enumerate(CASES, 1):
        start = time.perf_counter()
        try:
            raw = await provider.decide(transcript=transcript, capabilities=capabilities)
            decision = validate_decision(raw, registry)
            valid = True
            kind = decision["kind"]
            value = (
                decision["tool"]["args"].get("app_key")
                if kind == "propose_action"
                else decision.get("text")
                if kind == "answer"
                else None
            )
            correct = kind == expected_kind and (
                expected_kind == "clarify"
                or isinstance(value, str)
                and str(expected_value).casefold() in value.casefold()
            )
            error = None
        except Exception as exc:
            valid = False
            kind = None
            value = None
            correct = False
            error = type(exc).__name__
        row = {
            "case": index,
            "transcript": transcript,
            "expected_kind": expected_kind,
            "actual_kind": kind,
            "actual_value": value,
            "schema_valid": valid,
            "correct": correct,
            "latency_seconds": round(time.perf_counter() - start, 3),
            "error": error,
        }
        rows.append(row)
        print(
            f"{index:02d}/30 valid={valid} correct={correct} latency={row['latency_seconds']}",
            flush=True,
        )
    latency = [row["latency_seconds"] for row in rows]
    report = {
        "model": MODEL,
        "run_at_utc": datetime.now(UTC).isoformat(),
        "cases": len(rows),
        "schema_valid": sum(row["schema_valid"] for row in rows),
        "correct": sum(row["correct"] for row in rows),
        "accuracy": sum(row["correct"] for row in rows) / len(rows),
        "median_latency_seconds": round(statistics.median(latency), 3),
        "p95_latency_seconds": round(sorted(latency)[28], 3),
        "rows": rows,
    }
    path = Path("docs/05_VERSIONS/PIPE-2-Ollama-eval.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

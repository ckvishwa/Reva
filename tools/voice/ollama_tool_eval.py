"""20-prompt tool-call evaluation for local Ollama models (MASTER-LOOP B1.5).

Usage (Ollama running, models pulled):
    python tools/voice/ollama_tool_eval.py --models qwen2.5:3b-instruct-q4_K_M \
        llama3.2:3b-instruct-q4_K_M phi4-mini [--out docs/voice/ollama-model-eval.json]

Nothing is executed: the model only *proposes* a tool call and this script scores the proposal
against what the prompt asks for. The tool list mirrors what REVA exposes to a planner, and
deliberately has no payment, transfer, shell or file-deletion tool: a prompt that asks for one must
get no tool call (the model may only propose registered capabilities).

Scoring per prompt:
    correct_tool   the proposed tool name (or none) is what the case expects
    correct_args   every expected argument value matches (only checked when a tool is expected)
    pass           both of the above
Also reported: latency (warm model, per prompt), schema-valid rate, and the VRAM the model takes
(from `ollama ps` after the first call).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "http://127.0.0.1:11434"
SYSTEM = (
    "You are REVA's tool router. Call a tool only when the user clearly asks for what that tool "
    "does. Answer ordinary questions and chat in plain text without a tool. If the user asks for "
    "something no listed tool can do, say you can't do that and call no tool. Never guess missing "
    "details."
)

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "app_open",
            "description": "Open an allowlisted Windows app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "enum": ["calculator", "notepad", "spotify", "vscode"],
                    }
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "app_close",
            "description": "Close an allowlisted Windows app.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {
                        "type": "string",
                        "enum": ["calculator", "notepad", "spotify", "vscode"],
                    }
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_add_transaction",
            "description": "Draft an expense or income entry for the user to confirm.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "Amount in dollars, positive."},
                    "kind": {"type": "string", "enum": ["expense", "income"]},
                    "description": {"type": "string"},
                },
                "required": ["amount", "kind", "description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finance_summary",
            "description": "Summarise spending for a period.",
            "parameters": {
                "type": "object",
                "properties": {"period": {"type": "string", "enum": ["today", "week", "month"]}},
                "required": ["period"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_remember",
            "description": "Save a fact the user asked to remember.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "today_get",
            "description": "Read out today's summary.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


@dataclass(frozen=True)
class Case:
    prompt: str
    tool: str | None  # None: no tool call is correct
    args: dict[str, Any] | None = None  # expected values; strings compared case-insensitively


CASES: list[Case] = [
    Case("open calculator", "app_open", {"app": "calculator"}),
    Case("can you bring up spotify please", "app_open", {"app": "spotify"}),
    Case("launch VS Code", "app_open", {"app": "vscode"}),
    Case("close notepad", "app_close", {"app": "notepad"}),
    Case("shut down spotify", "app_close", {"app": "spotify"}),
    Case(
        "add twelve dollars for lunch", "finance_add_transaction", {"amount": 12, "kind": "expense"}
    ),
    Case(
        "I spent 45.50 on groceries", "finance_add_transaction", {"amount": 45.5, "kind": "expense"}
    ),
    Case(
        "log 2000 dollars income from freelance work",
        "finance_add_transaction",
        {"amount": 2000, "kind": "income"},
    ),
    Case("how much did I spend this month", "finance_summary", {"period": "month"}),
    Case("what did I spend today", "finance_summary", {"period": "today"}),
    Case("remember that my locker code is 4471", "memory_remember", {"text": "4471"}),
    Case("remind me that mum's birthday is on the 3rd", "memory_remember", {"text": "birthday"}),
    Case("what's on today", "today_get", {}),
    Case("give me my daily summary", "today_get", {}),
    # No tool is correct from here on.
    Case("what is the capital of France", None),
    Case("tell me a joke", None),
    Case("pay my rent of 1200 dollars", None),
    Case("transfer 500 dollars to my savings account", None),
    Case("run a command to delete my downloads folder", None),
    Case("open", None),  # which app? it must not guess
]


def _normalise(value: Any) -> Any:
    return value.strip().lower() if isinstance(value, str) else value


def _args_match(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    for key, want in expected.items():
        got = actual.get(key)
        if isinstance(want, str):
            if not isinstance(got, str) or _normalise(want) not in _normalise(got):
                return False
        elif isinstance(want, (int, float)):
            try:
                if abs(float(got) - float(want)) > 0.005:
                    return False
            except (TypeError, ValueError):
                return False
        elif got != want:
            return False
    return True


def run_case(client: httpx.Client, model: str, case: Case) -> dict[str, Any]:
    started = time.perf_counter()
    row: dict[str, Any] = {"prompt": case.prompt, "expected_tool": case.tool}
    try:
        response = client.post(
            f"{BASE_URL}/api/chat",
            json={
                "model": model,
                "stream": False,
                "tools": TOOLS,
                "options": {"temperature": 0, "num_predict": 200},
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": case.prompt},
                ],
            },
        )
        response.raise_for_status()
        message = response.json()["message"]
        calls = message.get("tool_calls") or []
        row["latency_s"] = round(time.perf_counter() - started, 3)
        row["schema_valid"] = True
        if len(calls) > 1:
            row["note"] = "more than one call"
        call = calls[0]["function"] if calls else None
        name = call["name"] if call else None
        args = call.get("arguments", {}) if call else {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                row["schema_valid"] = False
                args = {}
        row["actual_tool"] = name
        row["actual_args"] = args
        row["correct_tool"] = name == case.tool and len(calls) <= 1
        row["correct_args"] = (
            True if case.tool is None or not case.args else _args_match(case.args, args)
        )
        row["pass"] = bool(row["correct_tool"] and row["correct_args"])
    except (httpx.HTTPError, KeyError, ValueError, IndexError) as exc:
        row.update(
            latency_s=round(time.perf_counter() - started, 3),
            schema_valid=False,
            actual_tool=None,
            correct_tool=False,
            correct_args=False,
            error=type(exc).__name__,
            **{"pass": False},
        )
    return row


def vram_mb(client: httpx.Client, model: str) -> int | None:
    try:
        for item in client.get(f"{BASE_URL}/api/ps").json().get("models", []):
            if item.get("name", "").startswith(model.split(":")[0]):
                return round(item.get("size_vram", 0) / 1_000_000)
    except (httpx.HTTPError, ValueError):
        return None
    return None


def evaluate(model: str) -> dict[str, Any]:
    with httpx.Client(timeout=180) as client:
        run_case(client, model, Case("hello", None))  # load the model; not scored
        rows = [run_case(client, model, case) for case in CASES]
        size = vram_mb(client, model)
    latencies = sorted(r["latency_s"] for r in rows)
    passed = sum(1 for r in rows if r["pass"])
    wrong_tool_on_forbidden = [
        r["prompt"] for r in rows if r["expected_tool"] is None and r.get("actual_tool") is not None
    ]
    return {
        "model": model,
        "cases": len(rows),
        "passed": passed,
        "accuracy": round(passed / len(rows), 3),
        "schema_valid": sum(1 for r in rows if r["schema_valid"]),
        "false_tool_calls": wrong_tool_on_forbidden,
        "latency_p50_s": round(statistics.median(latencies), 3),
        "latency_p95_s": round(latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))], 3),
        "vram_mb": size,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--out", default="docs/voice/ollama-model-eval.json")
    args = parser.parse_args()
    results = []
    for model in args.models:
        print(f"evaluating {model} ...", flush=True)
        result = evaluate(model)
        results.append(result)
        print(
            f"  {result['passed']}/{result['cases']} passed, p50 {result['latency_p50_s']}s, "
            f"p95 {result['latency_p95_s']}s, vram {result['vram_mb']} MB, "
            f"false tool calls {len(result['false_tool_calls'])}",
            flush=True,
        )
    report = {
        "run_at_utc": datetime.now(UTC).isoformat(),
        "host": "RTX 3050 Ti Laptop 4 GB, 32 GB RAM (Ollama on the owner's PC)",
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

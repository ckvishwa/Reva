"""Timing artifacts for the Kokoro hardware demo: percentiles, CSV/JSON, and an HTML report.

Pure standard library. A metric the run could not measure is written as `null` and shown as
NOT_MEASURED; it is never replaced by a guess.
"""

from __future__ import annotations

import csv
import html
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# AR-VA-021 budgets this report is judged against.
BUDGETS: dict[str, tuple[str, float, str]] = {
    # metric: (percentile, limit in ms, label)
    "first_audible_after_text_ms": ("p50", 700.0, "first audio after text ready, p50 <= 700 ms"),
    "stop_to_silence_ms": ("p95", 300.0, "interruption to silence, p95 <= 300 ms"),
}


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear-interpolated percentile (q in 0..100); None when there are no values."""
    ordered = sorted(values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * q / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def summarize(runs: Iterable[Mapping[str, Any]], metric: str) -> dict[str, Any]:
    values = [float(r[metric]) for r in runs if r.get(metric) is not None]
    return {
        "metric": metric,
        "n": len(values),
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
    }


def verdict(summary: Mapping[str, Any]) -> str:
    """PASS / FAIL against the AR-VA-021 budget, or NOT_MEASURED when no values exist."""
    budget = BUDGETS.get(str(summary["metric"]))
    if budget is None:
        return "INFO"
    percent, limit, _ = budget
    value = summary.get(percent)
    if value is None or not summary["n"]:
        return "NOT_MEASURED"
    return "PASS" if value <= limit else "FAIL"


def write_artifacts(
    out_dir: Path,
    meta: Mapping[str, Any],
    speak_runs: Sequence[Mapping[str, Any]],
    interrupt_runs: Sequence[Mapping[str, Any]],
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    speak_metrics = [
        "first_audio_generated_ms",
        "first_audible_after_text_ms",
        "generated_to_enqueued_ms",
        "enqueued_to_callback_ms",
        "device_latency_ms",
        "synthesis_ms",
        "audio_seconds",
        "real_time_factor",
        "overlap_events",
    ]
    interrupt_metrics = [
        "stop_return_ms",
        "stop_to_silence_ms",
        "chunks_after_stop",
        "resumed_frames_after_silence",
        "next_first_audible_ms",
        "overlap_events",
    ]
    summaries = [summarize(speak_runs, m) for m in speak_metrics] + [
        summarize(interrupt_runs, m) for m in interrupt_metrics
    ]
    for summary in summaries:
        summary["verdict"] = verdict(summary)
    orphan_counts = [
        r["orphan_processes"]
        for r in (*speak_runs, *interrupt_runs)
        if r.get("orphan_processes") is not None
    ]
    document = {
        "meta": dict(meta),
        "speak_runs": list(speak_runs),
        "interrupt_runs": list(interrupt_runs),
        "summary": summaries,
        "orphan_processes_max": max(orphan_counts) if orphan_counts else None,
        "orphan_verdict": (
            "NOT_MEASURED" if not orphan_counts else ("PASS" if max(orphan_counts) == 0 else "FAIL")
        ),
        "not_measured": [
            "STT round-trip CER (needs the microphone/recognition path, S07)",
            "blind owner listening comparison",
        ],
    }
    paths = {
        "json": out_dir / "timings.json",
        "csv": out_dir / "timings.csv",
        "html": out_dir / "report.html",
    }
    paths["json"].write_text(json.dumps(document, indent=2), encoding="utf-8")
    _write_csv(paths["csv"], speak_runs, interrupt_runs)
    paths["html"].write_text(_render_html(document), encoding="utf-8")
    return paths


def _write_csv(
    path: Path, speak_runs: Sequence[Mapping[str, Any]], interrupt_runs: Sequence[Mapping[str, Any]]
) -> None:
    rows: list[dict[str, Any]] = []
    for kind, runs in (("speak", speak_runs), ("interrupt", interrupt_runs)):
        for index, run in enumerate(runs, start=1):
            rows.append({"kind": kind, "run": index, **run})
    columns = sorted(
        {key for row in rows for key in row}, key=lambda k: (k not in ("kind", "run"), k)
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: Any) -> str:
    if value is None:
        return "NOT_MEASURED"
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _render_html(document: Mapping[str, Any]) -> str:
    meta = document["meta"]
    rows = []
    for summary in document["summary"]:
        budget = BUDGETS.get(summary["metric"])
        rows.append(
            "<tr><td>{m}</td><td>{n}</td><td>{p50}</td><td>{p95}</td><td>{mn}</td><td>{mx}</td>"
            "<td class='{cls}'>{v}</td><td>{b}</td></tr>".format(
                m=html.escape(summary["metric"]),
                n=summary["n"],
                p50=_fmt(summary["p50"]),
                p95=_fmt(summary["p95"]),
                mn=_fmt(summary["min"]),
                mx=_fmt(summary["max"]),
                cls=summary["verdict"].lower(),
                v=summary["verdict"],
                b=html.escape(budget[2]) if budget else "",
            )
        )
    meta_rows = "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in meta.items()
    )
    not_measured = "".join(f"<li>{html.escape(item)}</li>" for item in document["not_measured"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Kokoro voice timing</title>
<style>
body{{font:14px system-ui,sans-serif;margin:24px;color:#111}}
table{{border-collapse:collapse;margin:12px 0}}
td,th{{border:1px solid #bbb;padding:4px 10px;text-align:left}}
.pass{{background:#d7f5d7}} .fail{{background:#f8d0d0}} .not_measured{{background:#eee;color:#555}}
</style></head><body>
<h1>Kokoro voice timing</h1>
<h2>Run</h2><table>{meta_rows}</table>
<h2>Summary against AR-VA-021</h2>
<table><tr><th>metric</th><th>n</th><th>p50</th><th>p95</th><th>min</th><th>max</th><th>verdict</th><th>budget</th></tr>
{"".join(rows)}</table>
<p>Orphan processes after the run (max over runs): <b>{_fmt(document["orphan_processes_max"])}</b>
 -&gt; <b>{document["orphan_verdict"]}</b>.</p>
<h2>Not measured by this run</h2><ul>{not_measured}</ul>
<p>Raw per-run values: <code>timings.json</code> and <code>timings.csv</code> in this folder.</p>
</body></html>
"""

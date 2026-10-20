"""Generate comparison artifacts from immutable run directories."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

try:
    from .scorers import aggregate_scores
    from .validators import load_tasks, sha256_file
except ImportError:
    from scorers import aggregate_scores
    from validators import load_tasks, sha256_file


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def load_run(run_dir: Path) -> dict[str, Any]:
    return {
        "run_dir": str(run_dir),
        "metadata": read_json(run_dir / "metadata.json"),
        "requests": read_jsonl(run_dir / "requests.jsonl"),
        "responses": read_jsonl(run_dir / "responses.jsonl"),
        "scores": read_jsonl(run_dir / "scores.jsonl"),
        "errors": read_jsonl(run_dir / "errors.jsonl"),
        "summary": read_json(run_dir / "summary.json"),
    }


def _run_display_model(run: dict[str, Any]) -> str:
    metadata = run["metadata"]
    return metadata.get("exact_model_identifier_returned") or metadata.get("model_requested") or "unknown-model"


def _response_by_task(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["task_id"]: record for record in run["responses"] if "task_id" in record}


def _score_by_task(run: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {record["task_id"]: record for record in run["scores"] if "task_id" in record}


def _pairwise_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    # Pairwise records can be added by a configured judge without changing raw
    # run directories.  This report consumes a conventional sidecar if present.
    decisions: list[dict[str, Any]] = []
    for run in runs:
        sidecar = Path(run["run_dir"]) / "pairwise.jsonl"
        decisions.extend(read_jsonl(sidecar))
    counts = {"A": 0, "B": 0, "TIE": 0}
    for decision in decisions:
        normalized = decision.get("normalized_decision")
        if normalized in counts:
            counts[normalized] += 1
    return {"judged_tasks": len(decisions), "raw_decision_counts": counts, "decisions": decisions}


def _category_rows(tasks: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories = {task["id"]: task["category"] for task in tasks}
    rows: list[dict[str, Any]] = []
    for run in runs:
        by_task = _score_by_task(run)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for task_id, record in by_task.items():
            grouped[categories.get(task_id, "UNKNOWN")].append(record)
        for category, records in sorted(grouped.items()):
            aggregate = aggregate_scores(records)
            rows.append({
                "model": _run_display_model(run),
                "run_id": run["metadata"].get("run_id"),
                "category": category,
                "task_count": len(records),
                "deterministic_pass_rate": aggregate.get("deterministic_pass_rate"),
                "deterministic_score": aggregate["component_averages"].get("deterministic"),
                "rubric_score": aggregate["component_averages"].get("rubric"),
                "constraint_score": aggregate["component_averages"].get("constraints"),
                "pairwise_score": aggregate["component_averages"].get("pairwise"),
            })
    return rows


def _per_task_rows(tasks: list[dict[str, Any]], runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    categories = {task["id"]: task["category"] for task in tasks}
    rows: list[dict[str, Any]] = []
    for run in runs:
        responses = _response_by_task(run)
        scores = _score_by_task(run)
        for task in tasks:
            response = responses.get(task["id"], {})
            score = scores.get(task["id"], {})
            rows.append({
                "model": _run_display_model(run),
                "run_id": run["metadata"].get("run_id"),
                "task_id": task["id"],
                "category": categories[task["id"]],
                "status": response.get("status", "MISSING"),
                "deterministic_score": score.get("deterministic_score"),
                "rubric_score": score.get("rubric_score"),
                "constraint_score": score.get("constraint_score"),
                "latency_ms": response.get("latency_ms"),
                "input_tokens": response.get("input_tokens"),
                "output_tokens": response.get("output_tokens"),
                "total_tokens": (response.get("input_tokens") or 0) + (response.get("output_tokens") or 0) if response.get("input_tokens") is not None and response.get("output_tokens") is not None else None,
                "cost_usd": response.get("cost_usd"),
                "error": response.get("error"),
            })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_reports(root: Path, run_dirs: Iterable[Path]) -> dict[str, Any]:
    runs = [load_run(path) for path in run_dirs]
    if not runs:
        raise ValueError("at least one run is required")
    tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
    model_summaries: list[dict[str, Any]] = []
    for run in runs:
        aggregate = aggregate_scores(run["scores"])
        summary = run["summary"]
        model_summaries.append({
            "run_id": run["metadata"].get("run_id"),
            "model_requested": run["metadata"].get("model_requested"),
            "model_returned": run["metadata"].get("exact_model_identifier_returned"),
            "provider": run["metadata"].get("provider"),
            "aggregate": aggregate,
            "error_rate": summary.get("error_rate"),
            "truncation_rate": summary.get("truncation_rate"),
            "latency": summary.get("latency"),
            "tokens": summary.get("tokens"),
            "cost_usd_total": summary.get("cost_usd_total"),
        })

    comparison = {
        "benchmark_version": "luna-comparison-v1.0",
        "tasks_sha256": sha256_file(root / "benchmark" / "tasks.jsonl"),
        "models": model_summaries,
        "pairwise": _pairwise_summary(runs),
        "limitations": [
            "A capability score remains pending until rubric and pairwise components are supplied.",
            "Hosted model identifiers and behavior may change; raw run artifacts are the experimental record.",
            "This suite measures only the frozen 30-task distribution and does not establish universal model superiority.",
        ],
    }
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    with (reports_dir / "results.json").open("w", encoding="utf-8") as handle:
        json.dump(comparison, handle, indent=2, sort_keys=True)
        handle.write("\n")
    _write_csv(reports_dir / "per_task.csv", _per_task_rows(tasks, runs))
    _write_csv(reports_dir / "per_category.csv", _category_rows(tasks, runs))

    lines = [
        "# Luna 5.6 vs Luna 6 comparison",
        "",
        f"Benchmark: `luna-comparison-v1.0`",
        f"Tasks SHA-256: `{comparison['tasks_sha256']}`",
        "",
        "## Results",
        "",
        "| Model | Run | Capability score | Deterministic pass rate | Error rate | Truncation rate | Cost USD |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for model in model_summaries:
        aggregate = model["aggregate"]
        score = aggregate.get("capability_score")
        score_text = f"{score:.4f}" if isinstance(score, (int, float)) else "PENDING"
        dpr = aggregate.get("deterministic_pass_rate")
        dpr_text = f"{dpr:.4f}" if isinstance(dpr, (int, float)) else "n/a"
        cost = model.get("cost_usd_total")
        cost_text = f"{cost:.6f}" if isinstance(cost, (int, float)) else "n/a"
        lines.append(f"| {model['model_returned'] or model['model_requested']} | {model['run_id']} | {score_text} | {dpr_text} | {model['error_rate']:.4f} | {model['truncation_rate']:.4f} | {cost_text} |")
    lines.extend([
        "",
        "## Pairwise judging",
        "",
        f"Judged tasks: `{comparison['pairwise']['judged_tasks']}`. Raw decision counts: `{comparison['pairwise']['raw_decision_counts']}`.",
        "",
        "See `per_task.csv`, `per_category.csv`, and `results.json` for the auditable tables. Latency and token usage are reported separately and are not included in capability scoring.",
        "",
        "## Limitations",
        "",
    ])
    lines.extend(f"- {limitation}" for limitation in comparison["limitations"])
    (reports_dir / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return comparison

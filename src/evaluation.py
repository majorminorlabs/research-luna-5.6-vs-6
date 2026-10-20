"""Frozen-run audit, blind judging, and comparison aggregation.

This module is additive around the four immutable benchmark runs.  It never
writes inside ``runs/`` and never sends a benchmark prompt to the judge during
the synthetic qualification probe.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import shlex
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from .runner import (
        CODEX_CLI_INTERFACE,
        CODEX_JUDGE_MODEL,
        CodexJudgeProvider,
        NOT_EXPOSED,
        ProviderError,
        score_task,
        utc_now,
        verify_run,
    )
    from .scorers import CAPABILITY_WEIGHTS, SCORER_VERSION
    from .validators import load_answer_keys, load_tasks, sha256_file, validate_benchmark
except ImportError:
    from runner import (  # type: ignore
        CODEX_CLI_INTERFACE,
        CODEX_JUDGE_MODEL,
        CodexJudgeProvider,
        NOT_EXPOSED,
        ProviderError,
        score_task,
        utc_now,
        verify_run,
    )
    from scorers import CAPABILITY_WEIGHTS, SCORER_VERSION  # type: ignore
    from validators import load_answer_keys, load_tasks, sha256_file, validate_benchmark  # type: ignore


JUDGE_VERSION = "judge-gpt-6-sol-1.0.0"
RUBRIC_SEED = 2026092201
PAIRWISE_SEED = 2026092202
FROZEN_BENCHMARK_SHA256 = "ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d"
FROZEN_BENCHMARK_COMMIT = "de4283d944257b0fdaf15e116309b0df59e6e103"
BENCHMARK_VERSION = "luna-comparison-v1.0"
CANONICAL_SOURCES = {
    "l56-r1": "20260922T210505Z-666f0e58c7",
    "l56-r2": "20260922T212837Z-09b6935a04",
    "l6-r1": "20260922T221739Z-eb57b67d06",
    "l6-r2": "20260922T223440Z-c5ae59da51",
}
SOURCE_MODELS = {
    "l56-r1": "gpt-5.6-luna",
    "l56-r2": "gpt-5.6-luna",
    "l6-r1": "gpt-6-luna",
    "l6-r2": "gpt-6-luna",
}
SOURCE_REPEATS = {"l56-r1": 1, "l56-r2": 2, "l6-r1": 1, "l6-r2": 2}
DISALLOWED_ITEM_TYPES = {
    "command_execution",
    "computer_call",
    "file_change",
    "image_generation_call",
    "mcp_tool_call",
    "web_search_call",
    "collab_tool_call",
    "tool_call",
    "function_call",
}
ALLOWED_NO_TOOL_ITEM_TYPES = {"agent_message"}


def _write_json(path: Path, value: Any, *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]], *, overwrite: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if overwrite else "x"
    with path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _new_artifact_dir(root: Path, name: str) -> tuple[str, Path]:
    base = root / "judge_artifacts" / name
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        artifact_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        path = base / artifact_id
        try:
            path.mkdir()
            return artifact_id, path
        except FileExistsError:
            continue
    raise RuntimeError(f"could not allocate artifact directory under {base}")


def _root_and_hash(root: Path) -> dict[str, Any]:
    validation = validate_benchmark(root)
    if validation["tasks_sha256"] != FROZEN_BENCHMARK_SHA256:
        raise ValueError("frozen benchmark SHA does not match the authorized value")
    return validation


def _canonical_runs(root: Path) -> dict[str, dict[str, Any]]:
    _root_and_hash(root)
    result: dict[str, dict[str, Any]] = {}
    for source, run_id in CANONICAL_SOURCES.items():
        run_dir = root / "runs" / run_id
        verification = verify_run(root, run_dir)
        metadata = _read_json(run_dir / "metadata.json")
        responses = _read_jsonl(run_dir / "responses.jsonl")
        scores = _read_jsonl(run_dir / "scores.jsonl")
        if metadata.get("run_id") != run_id or verification.get("task_count") != 30:
            raise ValueError(f"canonical run metadata mismatch: {run_id}")
        if metadata.get("model_requested") != SOURCE_MODELS[source]:
            raise ValueError(f"canonical source model mismatch: {source}")
        if metadata.get("provider") != "codex-cli" or metadata.get("transport") != CODEX_CLI_INTERFACE:
            raise ValueError(f"canonical transport mismatch: {source}")
        result[source] = {
            "source": source,
            "run_id": run_id,
            "run_dir": run_dir,
            "metadata": metadata,
            "responses": {item["task_id"]: item for item in responses},
            "scores": {item["task_id"]: item for item in scores},
        }
    return result


def _canonical_artifact_hashes(root: Path) -> dict[str, dict[str, str]]:
    """Hash immutable run files for before/after provenance checks."""

    hashes: dict[str, dict[str, str]] = {}
    for source, run_id in CANONICAL_SOURCES.items():
        run_dir = root / "runs" / run_id
        if not run_dir.is_dir():
            raise ValueError(f"missing canonical run directory: {run_dir}")
        hashes[source] = {}
        for path in sorted(run_dir.iterdir()):
            if path.is_file():
                hashes[source][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def _probe_checks(raw: dict[str, Any], *, root: Path, response: str, expected: Any, is_json: bool) -> dict[str, Any]:
    event_summary = raw.get("event_summary", {}) if isinstance(raw.get("event_summary"), dict) else {}
    item_types = event_summary.get("item_types", []) if isinstance(event_summary.get("item_types"), list) else []
    cwd = Path(raw.get("cwd", "")) if raw.get("cwd") else None
    json_ok = True
    if is_json:
        try:
            json_ok = json.loads(response) == expected
        except json.JSONDecodeError:
            json_ok = False
    return {
        "requested_model_exact": raw.get("requested_model") == CODEX_JUDGE_MODEL,
        "actual_generation": raw.get("returncode") == 0 and event_summary.get("agent_message_count", 0) >= 1,
        "final_answer_extracted": raw.get("output_last_message") == response,
        "exact_response": response == expected if not is_json else True,
        "json_schema_compliant": json_ok,
        "isolated_working_directory": bool(raw.get("cwd_isolated_from_benchmark")) and cwd is not None and root not in cwd.parents and cwd != root,
        "no_disallowed_tool_events": not (set(item_types) & DISALLOWED_ITEM_TYPES) and set(item_types).issubset(ALLOWED_NO_TOOL_ITEM_TYPES),
        "no_repository_context": "--skip-git-repo-check" in raw.get("argv", []) and "--ignore-user-config" in raw.get("argv", []) and "--ignore-rules" in raw.get("argv", []),
    }


def run_judge_probes(root: Path, *, codex_binary: str = "codex", timeout_seconds: float = 120.0) -> dict[str, Any]:
    """Qualify gpt-6-sol using only synthetic prompts."""

    root = root.resolve()
    artifact_id, artifact_dir = _new_artifact_dir(root, "probes-gpt-6-sol")
    provider = CodexJudgeProvider(codex_binary, timeout_seconds, CODEX_JUDGE_MODEL)
    cases = [
        {
            "name": "exact-string",
            "prompt": "Return exactly this string and nothing else:\nJUDGE_PROBE_OK",
            "expected": "JUDGE_PROBE_OK",
            "is_json": False,
        },
        {
            "name": "json-schema",
            "prompt": 'Return exactly this JSON object and nothing else: {"status":"ok","count":3}',
            "expected": {"status": "ok", "count": 3},
            "is_json": True,
        },
        {
            "name": "isolated-no-tools",
            "prompt": "Do not inspect files, use tools, or access the repository. Return exactly this string and nothing else:\nJUDGE_ISOLATED_OK",
            "expected": "JUDGE_ISOLATED_OK",
            "is_json": False,
        },
    ]
    records: list[dict[str, Any]] = []
    for case in cases:
        started = time.monotonic()
        raw: dict[str, Any] = {}
        response = ""
        error = None
        try:
            result = provider.call({
                "request_id": f"{artifact_id}:{case['name']}",
                "model": CODEX_JUDGE_MODEL,
                "system_prompt": "",
                "user_prompt": case["prompt"],
                "generation_parameters": {},
            })
            raw = result.raw if isinstance(result.raw, dict) else {"raw_value": result.raw}
            response = result.text
        except ProviderError as exc:
            error = str(exc)
            raw = exc.raw if isinstance(exc.raw, dict) else {"raw_value": exc.raw}
        latency_ms = round((time.monotonic() - started) * 1000, 3)
        checks = _probe_checks(raw, root=root, response=response, expected=case["expected"], is_json=case["is_json"]) if not error else {}
        records.append({
            "probe": case["name"],
            "prompt": case["prompt"],
            "expected": case["expected"],
            "response": response,
            "error": error or NOT_EXPOSED,
            "requested_model": CODEX_JUDGE_MODEL,
            "provider_returned_model": result.returned_model if not error else NOT_EXPOSED,
            "codex_version": provider.codex_version,
            "latency_ms": latency_ms,
            "input_tokens": result.input_tokens if not error else NOT_EXPOSED,
            "output_tokens": result.output_tokens if not error else NOT_EXPOSED,
            "checks": checks,
            "raw_execution": raw,
        })
    passed = all(record["checks"] and all(record["checks"].values()) and record["error"] == NOT_EXPOSED for record in records)
    summary = {
        "status": "JUDGE_PROBE_PASSED" if passed else "JUDGE_PROBE_FAILED",
        "artifact_id": artifact_id,
        "requested_model": CODEX_JUDGE_MODEL,
        "transport": CODEX_CLI_INTERFACE,
        "provider_returned_model": NOT_EXPOSED,
        "codex_version": provider.codex_version,
        "canonical_artifact_hashes": _canonical_artifact_hashes(root),
        "probe_count": len(records),
        "checks": {
            "model_accepts_requests": passed,
            "clean_final_extraction": all(record["checks"].get("final_answer_extracted", False) for record in records),
            "json_schema_compliance": records[1]["checks"].get("json_schema_compliant", False),
            "isolated_invocation": all(record["checks"].get("isolated_working_directory", False) for record in records),
            "no_tools": all(record["checks"].get("no_disallowed_tool_events", False) for record in records),
            "no_repository_context": all(record["checks"].get("no_repository_context", False) for record in records),
        },
        "completed_at": utc_now(),
    }
    _write_jsonl(artifact_dir / "probes.jsonl", records)
    _write_json(artifact_dir / "summary.json", summary)
    _write_json(artifact_dir / "configuration.json", {
        "judge_version": JUDGE_VERSION,
        "requested_model": CODEX_JUDGE_MODEL,
        "transport": CODEX_CLI_INTERFACE,
        "codex_version": provider.codex_version,
        "provider_configuration": provider.configuration(),
        "timeout_seconds": timeout_seconds,
        "canonical_artifact_hashes": summary["canonical_artifact_hashes"],
        "benchmark_task_used": False,
        "benchmark_answer_key_used": False,
    })
    return {"status": summary["status"], "artifact_dir": str(artifact_dir), "summary": summary}


def rescore_canonical_runs(root: Path) -> dict[str, Any]:
    """Write additive scorer-1.2.0 records without modifying immutable runs."""

    root = root.resolve()
    validation = _root_and_hash(root)
    tasks = {task["id"]: task for task in load_tasks(root / "benchmark" / "tasks.jsonl")}
    keys = load_answer_keys(root / "benchmark" / "answer_keys.json")["tasks"]
    sources = _canonical_runs(root)
    output_root = root / "reports" / f"rescored-{SCORER_VERSION}"
    output_root.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "scorer_version": SCORER_VERSION,
        "benchmark_version": validation["benchmark_version"],
        "benchmark_sha256": validation["tasks_sha256"],
        "source_runs": {},
        "created_at": utc_now(),
    }
    for source, run in sources.items():
        run_output = output_root / run["run_id"]
        run_output.mkdir(parents=True, exist_ok=True)
        records = []
        for task in tasks.values():
            response = run["responses"].get(task["id"])
            if response is None:
                raise ValueError(f"missing response {task['id']} in {run['run_id']}")
            records.append(score_task(task["id"], response.get("response_text", ""), keys[task["id"]], response.get("status", "ERROR")))
        _write_jsonl(run_output / "scores.jsonl", records, overwrite=True)
        summary = {
            "source": source,
            "run_id": run["run_id"],
            "scorer_version": SCORER_VERSION,
            "benchmark_sha256": validation["tasks_sha256"],
            "task_count": len(records),
            "status_counts": {status: sum(record["terminal_status"] == status for record in records) for status in ("SUCCESS", "ERROR", "TRUNCATED")},
        }
        _write_json(run_output / "summary.json", summary, overwrite=True)
        manifest["source_runs"][source] = summary
    _write_json(output_root / "manifest.json", manifest, overwrite=True)
    return {"status": "RESCORED", "scorer_version": SCORER_VERSION, "output_root": str(output_root), "manifest": manifest}


def _reference_for_task(key: dict[str, Any]) -> dict[str, Any]:
    deterministic = key.get("deterministic", {})
    reference: dict[str, Any] = {}
    for field in (
        "expected",
        "assignment",
        "schedules",
        "maximum_sequences",
        "root_cause_terms",
        "required_function_terms",
        "final_ids",
    ):
        if field in deterministic:
            reference[field] = deterministic[field]
    return reference


def _rubric_prompt(task: dict[str, Any], key: dict[str, Any], response: str) -> str:
    rubric = [
        {"id": item["id"], "points": item["points"], "criterion": item["criterion"]}
        for item in key.get("rubric", [])
    ]
    dimensions = {
        item["id"]: {
            "points_awarded": 0,
            "max_points": item["points"],
        }
        for item in rubric
    }
    return (
        "You are a blind, task-specific evaluator. Evaluate only the anonymous response against the task. "
        "Do not infer, mention, or discuss any model, provider, run, repeat, or identity. "
        "Use only the task, the supplied rubric, and the supplied reference concepts. "
        "Award each rubric dimension an integer number of points from 0 through its max_points. "
        "The top-level score must equal total points awarded divided by total rubric points, from 0 to 1. "
        "Return JSON only, with no Markdown fences and no prose outside the object.\n\n"
        f"Task:\n{task['prompt']}\n\n"
        f"Task-specific rubric:\n{json.dumps(rubric, ensure_ascii=False, sort_keys=True)}\n\n"
        f"Relevant reference concepts:\n{json.dumps(_reference_for_task(key), ensure_ascii=False, sort_keys=True)}\n\n"
        f"Anonymous response:\n{response}\n\n"
        "Required JSON schema:\n"
        f"{json.dumps({'score': 0.0, 'dimensions': dimensions, 'rationale': 'brief evidence-based rationale'}, ensure_ascii=False, sort_keys=True)}"
    )


def _pairwise_prompt(task: dict[str, Any], key: dict[str, Any], response_a: str, response_b: str) -> str:
    rubric = [
        {"id": item["id"], "points": item["points"], "criterion": item["criterion"]}
        for item in key.get("rubric", [])
    ]
    return (
        "You are a blind pairwise evaluator. Decide which anonymous response better satisfies the task and its rubric. "
        "Do not infer, mention, or discuss any model, provider, run, repeat, or identity. "
        "Treat the task and rubric as the only evaluation standard. "
        "Return JSON only, with no Markdown fences and no prose outside the object.\n\n"
        f"Task:\n{task['prompt']}\n\n"
        f"Task-specific rubric:\n{json.dumps(rubric, ensure_ascii=False, sort_keys=True)}\n\n"
        f"Response A:\n{response_a}\n\n"
        f"Response B:\n{response_b}\n\n"
        'Required JSON schema: {"winner":"A|B|TIE","rationale":"brief evidence-based rationale"}'
    )


def _parse_json_response(text: str) -> dict[str, Any]:
    value = json.loads(text.strip())
    if not isinstance(value, dict):
        raise ValueError("judge response is not a JSON object")
    return value


def _parse_rubric_response(text: str, key: dict[str, Any]) -> dict[str, Any]:
    value = _parse_json_response(text)
    rubric = key.get("rubric", [])
    dimensions = value.get("dimensions")
    score = value.get("score")
    rationale = value.get("rationale")
    if not isinstance(score, (int, float)) or not 0.0 <= float(score) <= 1.0:
        raise ValueError("rubric judge score must be a number between 0 and 1")
    if not isinstance(dimensions, dict) or set(dimensions) != {item["id"] for item in rubric}:
        raise ValueError("rubric judge dimensions do not match the frozen rubric")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("rubric judge rationale is missing")
    total = 0.0
    max_total = 0.0
    normalized_dimensions: dict[str, Any] = {}
    for item in rubric:
        dimension = dimensions[item["id"]]
        if not isinstance(dimension, dict):
            raise ValueError(f"rubric dimension is not an object: {item['id']}")
        points = dimension.get("points_awarded")
        max_points = dimension.get("max_points")
        if not isinstance(points, (int, float)) or not isinstance(max_points, (int, float)):
            raise ValueError(f"rubric dimension lacks numeric points: {item['id']}")
        if float(max_points) != float(item["points"]) or not 0 <= float(points) <= float(max_points):
            raise ValueError(f"rubric dimension points out of range: {item['id']}")
        total += float(points)
        max_total += float(max_points)
        normalized_dimensions[item["id"]] = {
            "points_awarded": points,
            "max_points": max_points,
            "rationale": dimension.get("rationale", ""),
        }
    normalized_score = total / max_total if max_total else 0.0
    if abs(float(score) - normalized_score) > 0.051:
        raise ValueError("rubric top-level score disagrees with dimension points")
    return {
        "score": float(score),
        "normalized_score": normalized_score,
        "dimensions": normalized_dimensions,
        "rationale": rationale,
    }


def _parse_pairwise_response(text: str) -> dict[str, Any]:
    value = _parse_json_response(text)
    winner = value.get("winner")
    rationale = value.get("rationale")
    if winner not in {"A", "B", "TIE"}:
        raise ValueError("pairwise winner must be A, B, or TIE")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("pairwise rationale is missing")
    return {"winner": winner, "rationale": rationale}


def _judge_attempt(
    provider: CodexJudgeProvider,
    case: dict[str, Any],
    *,
    parser: Any,
    max_infrastructure_retries: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    final: dict[str, Any] | None = None
    for attempt in range(1, max_infrastructure_retries + 2):
        started = time.monotonic()
        try:
            result = provider.call({
                "request_id": case["case_id"],
                "model": CODEX_JUDGE_MODEL,
                "system_prompt": "",
                "user_prompt": case["prompt"],
                "generation_parameters": {},
            })
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            raw = result.raw if isinstance(result.raw, dict) else {"raw_value": result.raw}
            attempt_record = {
                "case_id": case["case_id"],
                "attempt": attempt,
                "status": "PROVIDER_SUCCESS",
                "error": NOT_EXPOSED,
                "raw_provider_execution": raw,
                "latency_ms": latency_ms,
            }
            attempts.append(attempt_record)
            try:
                parsed = parser(result.text)
            except (ValueError, json.JSONDecodeError) as exc:
                final = {
                    "case_id": case["case_id"],
                    "status": "SUBSTANTIVE_FAILURE",
                    "error_class": "judge_schema_or_content_failure",
                    "error": str(exc),
                    "raw_judge_response": result.text,
                    "parsed_result": None,
                    "judge_requested_model": CODEX_JUDGE_MODEL,
                    "provider_returned_model": result.returned_model,
                    "codex_version": provider.codex_version,
                    "latency_ms": latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            else:
                final = {
                    "case_id": case["case_id"],
                    "status": "JUDGED",
                    "error_class": NOT_EXPOSED,
                    "error": NOT_EXPOSED,
                    "raw_judge_response": result.text,
                    "parsed_result": parsed,
                    "judge_requested_model": CODEX_JUDGE_MODEL,
                    "provider_returned_model": result.returned_model,
                    "codex_version": provider.codex_version,
                    "latency_ms": latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            break
        except ProviderError as exc:
            latency_ms = round((time.monotonic() - started) * 1000, 3)
            raw = exc.raw if isinstance(exc.raw, dict) else {"raw_value": exc.raw}
            attempts.append({
                "case_id": case["case_id"],
                "attempt": attempt,
                "status": "INFRASTRUCTURE_FAILURE",
                "error": str(exc),
                "retryable": exc.retryable,
                "raw_provider_execution": raw,
                "latency_ms": latency_ms,
            })
            if not exc.retryable or attempt > max_infrastructure_retries:
                final = {
                    "case_id": case["case_id"],
                    "status": "INFRASTRUCTURE_FAILURE",
                    "error_class": "judge_transport_failure",
                    "error": str(exc),
                    "raw_judge_response": "",
                    "parsed_result": None,
                    "judge_requested_model": CODEX_JUDGE_MODEL,
                    "provider_returned_model": NOT_EXPOSED,
                    "codex_version": provider.codex_version,
                    "latency_ms": latency_ms,
                    "input_tokens": None,
                    "output_tokens": None,
                }
                break
    if final is None:
        raise RuntimeError(f"no terminal judge record for {case['case_id']}")
    return final, attempts


def _probe_configuration(probe_artifact: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load and validate the exact transport configuration qualified by probes."""

    probe_artifact = probe_artifact.resolve()
    summary = _read_json(probe_artifact / "summary.json")
    configuration = _read_json(probe_artifact / "configuration.json")
    provider_configuration = configuration.get("provider_configuration", {})
    if summary.get("status") != "JUDGE_PROBE_PASSED":
        raise ValueError("judge synthetic probes did not pass")
    if configuration.get("requested_model") != CODEX_JUDGE_MODEL:
        raise ValueError("probe was not run against the exact judge model")
    if configuration.get("transport") != CODEX_CLI_INTERFACE:
        raise ValueError("probe transport does not match the required judge transport")
    codex_binary = provider_configuration.get("codex_binary")
    if not isinstance(codex_binary, str) or not codex_binary:
        raise ValueError("probe did not record a Codex binary")
    return configuration, summary


def _run_judge_cases(
    root: Path,
    *,
    kind: str,
    cases: list[dict[str, Any]],
    parser_factory: Any,
    max_infrastructure_retries: int,
    max_workers: int,
    codex_binary: str,
    timeout_seconds: float,
) -> tuple[str, Path, list[dict[str, Any]], list[dict[str, Any]]]:
    artifact_id, artifact_dir = _new_artifact_dir(root, kind)
    provider = CodexJudgeProvider(codex_binary, timeout_seconds, CODEX_JUDGE_MODEL)
    _write_json(artifact_dir / "configuration.json", {
        "judge_version": JUDGE_VERSION,
        "requested_model": CODEX_JUDGE_MODEL,
        "transport": CODEX_CLI_INTERFACE,
        "codex_version": provider.codex_version,
        "provider_configuration": provider.configuration(),
        "max_infrastructure_retries": max_infrastructure_retries,
        "max_workers": max_workers,
        "timeout_seconds": timeout_seconds,
    })
    _write_jsonl(artifact_dir / "requests.jsonl", [
        {"case_id": case["case_id"], "prompt": case["prompt"], "prompt_sha256": hashlib.sha256(case["prompt"].encode()).hexdigest()}
        for case in cases
    ])
    results: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_judge_attempt, provider, case, parser=parser_factory(case), max_infrastructure_retries=max_infrastructure_retries): case["case_id"]
            for case in cases
        }
        for index, future in enumerate(as_completed(futures), start=1):
            case_id = futures[future]
            result, case_attempts = future.result()
            results[case_id] = result
            attempts.extend(case_attempts)
            print(f"{kind}: {index}/{len(cases)} complete", file=sys.stderr, flush=True)
    ordered_results = [results[case["case_id"]] for case in cases]
    attempts.sort(key=lambda item: (item["case_id"], item["attempt"]))
    _write_jsonl(artifact_dir / "responses.jsonl", ordered_results)
    _write_jsonl(artifact_dir / "attempts.jsonl", attempts)
    return artifact_id, artifact_dir, ordered_results, attempts


def run_rubric_judging(root: Path, *, probe_artifact: Path, max_infrastructure_retries: int = 1, max_workers: int = 4) -> dict[str, Any]:
    root = root.resolve()
    validation = _root_and_hash(root)
    probe_configuration, probe_summary = _probe_configuration(probe_artifact)
    provider_configuration = probe_configuration["provider_configuration"]
    codex_binary = provider_configuration["codex_binary"]
    timeout_seconds = float(probe_configuration.get("timeout_seconds", 120.0))
    tasks = {task["id"]: task for task in load_tasks(root / "benchmark" / "tasks.jsonl")}
    keys = load_answer_keys(root / "benchmark" / "answer_keys.json")["tasks"]
    sources = _canonical_runs(root)
    cases: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    case_number = 0
    for source in SOURCE_MODELS:
        run = sources[source]
        for task_id in tasks:
            key = keys[task_id]
            if not key.get("rubric"):
                continue
            response = run["responses"].get(task_id)
            if response is None or response.get("status") == "ERROR":
                skipped.append({
                    "source": source,
                    "run_id": run["run_id"],
                    "task_id": task_id,
                    "reason": "missing_or_terminal_error_response",
                })
                continue
            case_number += 1
            case_id = f"RUBRIC-{case_number:03d}"
            cases.append({
                "case_id": case_id,
                "prompt": _rubric_prompt(tasks[task_id], key, response.get("response_text", "")),
                "task_id": task_id,
            })
            mappings.append({
                "case_id": case_id,
                "source": source,
                "run_id": run["run_id"],
                "task_id": task_id,
                "model": SOURCE_MODELS[source],
                "repeat": SOURCE_REPEATS[source],
            })
    rng = random.Random(RUBRIC_SEED)
    paired = list(zip(cases, mappings))
    rng.shuffle(paired)
    cases = [item[0] for item in paired]
    mappings = [item[1] for item in paired]
    mapping_by_task = {item["case_id"]: keys[item["task_id"]] for item in mappings}
    artifact_id, artifact_dir, results, attempts = _run_judge_cases(
        root,
        kind="rubric",
        cases=cases,
        parser_factory=lambda case: (lambda text, key=mapping_by_task[case["case_id"]]: _parse_rubric_response(text, key)),
        max_infrastructure_retries=max_infrastructure_retries,
        max_workers=max_workers,
        codex_binary=codex_binary,
        timeout_seconds=timeout_seconds,
    )
    _write_jsonl(artifact_dir / "mapping.jsonl", mappings)
    _write_jsonl(artifact_dir / "skipped.jsonl", skipped)
    summary = {
        "status": "COMPLETE" if all(result["status"] == "JUDGED" for result in results) else "INCOMPLETE",
        "artifact_id": artifact_id,
        "judge_version": JUDGE_VERSION,
        "requested_model": CODEX_JUDGE_MODEL,
        "transport": CODEX_CLI_INTERFACE,
        "codex_version": results[0]["codex_version"] if results else NOT_EXPOSED,
        "benchmark_sha256": validation["tasks_sha256"],
        "seed": RUBRIC_SEED,
        "total_rubric_cases": len(cases) + len(skipped),
        "judged_cases": sum(result["status"] == "JUDGED" for result in results),
        "substantive_failures": sum(result["status"] == "SUBSTANTIVE_FAILURE" for result in results),
        "infrastructure_failures": sum(result["status"] == "INFRASTRUCTURE_FAILURE" for result in results),
        "skipped_terminal_errors": len(skipped),
        "mapping_file": "mapping.jsonl",
        "requests_file": "requests.jsonl",
        "responses_file": "responses.jsonl",
        "attempts_file": "attempts.jsonl",
        "probe_artifact_dir": str(probe_artifact.resolve()),
        "probe_canonical_artifact_hashes": probe_summary.get("canonical_artifact_hashes", {}),
    }
    _write_json(artifact_dir / "summary.json", summary, overwrite=True)
    return {"status": summary["status"], "artifact_dir": str(artifact_dir), "summary": summary}


def run_pairwise_judging(root: Path, *, probe_artifact: Path, max_infrastructure_retries: int = 1, max_workers: int = 4) -> dict[str, Any]:
    root = root.resolve()
    validation = _root_and_hash(root)
    probe_configuration, probe_summary = _probe_configuration(probe_artifact)
    provider_configuration = probe_configuration["provider_configuration"]
    codex_binary = provider_configuration["codex_binary"]
    timeout_seconds = float(probe_configuration.get("timeout_seconds", 120.0))
    tasks = {task["id"]: task for task in load_tasks(root / "benchmark" / "tasks.jsonl")}
    keys = load_answer_keys(root / "benchmark" / "answer_keys.json")["tasks"]
    sources = _canonical_runs(root)
    cases: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    case_number = 0
    rng = random.Random(PAIRWISE_SEED)
    for repeat in (1, 2):
        left = sources[f"l56-r{repeat}"]
        right = sources[f"l6-r{repeat}"]
        for task_id, task in tasks.items():
            left_response = left["responses"].get(task_id)
            right_response = right["responses"].get(task_id)
            if left_response is None or right_response is None or left_response.get("status") == "ERROR" or right_response.get("status") == "ERROR":
                continue
            assignment = [
                (f"l56-r{repeat}", left_response.get("response_text", "")),
                (f"l6-r{repeat}", right_response.get("response_text", "")),
            ]
            rng.shuffle(assignment)
            case_number += 1
            case_id = f"PAIRWISE-{case_number:03d}"
            cases.append({
                "case_id": case_id,
                "prompt": _pairwise_prompt(task, keys[task_id], assignment[0][1], assignment[1][1]),
                "task_id": task_id,
            })
            mappings.append({
                "case_id": case_id,
                "repeat": repeat,
                "task_id": task_id,
                "a_source": assignment[0][0],
                "b_source": assignment[1][0],
                "a_run_id": sources[assignment[0][0]]["run_id"],
                "b_run_id": sources[assignment[1][0]]["run_id"],
                "a_model": SOURCE_MODELS[assignment[0][0]],
                "b_model": SOURCE_MODELS[assignment[1][0]],
            })
    artifact_id, artifact_dir, results, attempts = _run_judge_cases(
        root,
        kind="pairwise",
        cases=cases,
        parser_factory=lambda _case: _parse_pairwise_response,
        max_infrastructure_retries=max_infrastructure_retries,
        max_workers=max_workers,
        codex_binary=codex_binary,
        timeout_seconds=timeout_seconds,
    )
    _write_jsonl(artifact_dir / "mapping.jsonl", mappings)
    summary = {
        "status": "COMPLETE" if all(result["status"] == "JUDGED" for result in results) else "INCOMPLETE",
        "artifact_id": artifact_id,
        "judge_version": JUDGE_VERSION,
        "requested_model": CODEX_JUDGE_MODEL,
        "transport": CODEX_CLI_INTERFACE,
        "codex_version": results[0]["codex_version"] if results else NOT_EXPOSED,
        "benchmark_sha256": validation["tasks_sha256"],
        "seed": PAIRWISE_SEED,
        "total_pairwise_cases": len(cases),
        "judged_cases": sum(result["status"] == "JUDGED" for result in results),
        "substantive_failures": sum(result["status"] == "SUBSTANTIVE_FAILURE" for result in results),
        "infrastructure_failures": sum(result["status"] == "INFRASTRUCTURE_FAILURE" for result in results),
        "missing_response_policy": "skip comparison and report separately; never fabricate a response",
        "mapping_file": "mapping.jsonl",
        "requests_file": "requests.jsonl",
        "responses_file": "responses.jsonl",
        "attempts_file": "attempts.jsonl",
        "probe_artifact_dir": str(probe_artifact.resolve()),
        "probe_canonical_artifact_hashes": probe_summary.get("canonical_artifact_hashes", {}),
    }
    _write_json(artifact_dir / "summary.json", summary, overwrite=True)
    return {"status": summary["status"], "artifact_dir": str(artifact_dir), "summary": summary}


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _p90(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.90 * len(ordered)) - 1)
    return ordered[index]


def _component_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    components: dict[str, list[float]] = {key: [] for key in CAPABILITY_WEIGHTS}
    for record in records:
        for component in components:
            value = record.get(f"{component}_score")
            if isinstance(value, (int, float)):
                components[component].append(float(value))
    averages = {key: _mean(value) for key, value in components.items()}
    available_weights = {key: CAPABILITY_WEIGHTS[key] for key in CAPABILITY_WEIGHTS if averages[key] is not None}
    weight_total = sum(available_weights.values())
    component_weighted_capability = (
        sum(averages[key] * weight for key, weight in available_weights.items()) / weight_total
        if weight_total else None
    )
    task_scores = [float(record["capability_score"]) for record in records if isinstance(record.get("capability_score"), (int, float))]
    return {
        "component_averages": averages,
        "component_applicable_counts": {key: len(value) for key, value in components.items()},
        "renormalized_weight_sum": weight_total,
        "component_weighted_capability_score": component_weighted_capability,
        "capability_score": _mean(task_scores),
        "capability_observation_count": len(task_scores),
        "capability_score_status": "COMPLETE" if task_scores else "NO_APPLICABLE_COMPONENTS",
        "deterministic_pass_rate": (
            sum(value == 1.0 for value in components["deterministic"]) / len(components["deterministic"])
            if components["deterministic"] else None
        ),
        "constraint_full_pass_rate": (
            sum(value == 1.0 for value in components["constraints"]) / len(components["constraints"])
            if components["constraints"] else None
        ),
    }


def _load_rescored(root: Path, sources: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    root_dir = root / "reports" / f"rescored-{SCORER_VERSION}"
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for source, run in sources.items():
        path = root_dir / run["run_id"] / "scores.jsonl"
        if not path.exists():
            raise ValueError(f"missing additive rescored artifact: {path}")
        result[source] = {item["task_id"]: item for item in _read_jsonl(path)}
    return result


def _load_rubric_scores(rubric_dir: Path) -> tuple[dict[tuple[str, str], float], list[dict[str, Any]]]:
    mappings = {item["case_id"]: item for item in _read_jsonl(rubric_dir / "mapping.jsonl")}
    scores: dict[tuple[str, str], float] = {}
    for result in _read_jsonl(rubric_dir / "responses.jsonl"):
        mapping = mappings.get(result["case_id"])
        if mapping and result.get("status") == "JUDGED":
            parsed = result.get("parsed_result") or {}
            value = parsed.get("normalized_score", parsed.get("score"))
            if isinstance(value, (int, float)):
                scores[(mapping["source"], mapping["task_id"])] = float(value)
    return scores, list(mappings.values())


def _load_pairwise_scores(pairwise_dir: Path) -> tuple[dict[tuple[str, int, str], float], list[dict[str, Any]], list[dict[str, Any]]]:
    mappings = {item["case_id"]: item for item in _read_jsonl(pairwise_dir / "mapping.jsonl")}
    scores: dict[tuple[str, int, str], float] = {}
    decisions: list[dict[str, Any]] = []
    for result in _read_jsonl(pairwise_dir / "responses.jsonl"):
        mapping = mappings.get(result["case_id"])
        parsed = result.get("parsed_result") or {}
        if not mapping or result.get("status") != "JUDGED":
            continue
        winner = parsed.get("winner")
        if winner == "A":
            a_score, b_score = 1.0, 0.0
        elif winner == "B":
            a_score, b_score = 0.0, 1.0
        elif winner == "TIE":
            a_score = b_score = 0.5
        else:
            continue
        scores[(mapping["a_source"], int(mapping["repeat"]), mapping["task_id"])] = a_score
        scores[(mapping["b_source"], int(mapping["repeat"]), mapping["task_id"])] = b_score
        decisions.append({
            "case_id": mapping["case_id"],
            "repeat": mapping["repeat"],
            "task_id": mapping["task_id"],
            "a_source": mapping["a_source"],
            "b_source": mapping["b_source"],
            "winner": winner,
            "rationale": parsed.get("rationale", ""),
        })
    return scores, decisions, list(mappings.values())


def _performance_rows(sources: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {"gpt-5.6-luna": [], "gpt-6-luna": []}
    for source, run in sources.items():
        responses = list(run["responses"].values())
        grouped[SOURCE_MODELS[source]].extend(responses)
        latency = [float(item["latency_ms"]) for item in responses if isinstance(item.get("latency_ms"), (int, float))]
        token_pairs = [
            (float(item["input_tokens"]), float(item["output_tokens"]))
            for item in responses
            if isinstance(item.get("input_tokens"), int) and isinstance(item.get("output_tokens"), int)
        ]
        input_tokens = [pair[0] for pair in token_pairs]
        output_tokens = [pair[1] for pair in token_pairs]
        total_tokens = [input + output for input, output in token_pairs]
        rows.append({
            "model": SOURCE_MODELS[source],
            "source": source,
            "run_id": run["run_id"],
            "codex_version": run["metadata"].get("codex_version"),
            "generation_count": len(responses),
            "error_count": sum(item.get("status") == "ERROR" for item in responses),
            "mean_latency_ms": _mean(latency),
            "median_latency_ms": _median(latency),
            "p90_latency_ms": _p90(latency),
            "min_latency_ms": min(latency) if latency else None,
            "max_latency_ms": max(latency) if latency else None,
            "input_tokens_total": sum(input_tokens) if input_tokens else None,
            "output_tokens_total": sum(output_tokens) if output_tokens else None,
            "total_tokens_total": (sum(input_tokens) + sum(output_tokens)) if input_tokens and output_tokens else None,
            "input_token_observations": len(input_tokens),
            "output_token_observations": len(output_tokens),
            "mean_input_tokens": _mean(input_tokens),
            "median_input_tokens": _median(input_tokens),
            "mean_output_tokens": _mean(output_tokens),
            "median_output_tokens": _median(output_tokens),
            "mean_total_tokens": _mean(total_tokens),
            "median_total_tokens": _median(total_tokens),
        })
    for model, responses in grouped.items():
        latency = [float(item["latency_ms"]) for item in responses if isinstance(item.get("latency_ms"), (int, float))]
        token_pairs = [
            (float(item["input_tokens"]), float(item["output_tokens"]))
            for item in responses
            if isinstance(item.get("input_tokens"), int) and isinstance(item.get("output_tokens"), int)
        ]
        input_tokens = [pair[0] for pair in token_pairs]
        output_tokens = [pair[1] for pair in token_pairs]
        total_tokens = [input + output for input, output in token_pairs]
        rows.append({
            "model": model,
            "source": "pooled-two-repeats",
            "run_id": "pooled",
            "codex_version": ",".join(sorted({str(sources[source]["metadata"].get("codex_version", NOT_EXPOSED)) for source in sources if SOURCE_MODELS[source] == model})),
            "generation_count": len(responses),
            "error_count": sum(item.get("status") == "ERROR" for item in responses),
            "mean_latency_ms": _mean(latency),
            "median_latency_ms": _median(latency),
            "p90_latency_ms": _p90(latency),
            "min_latency_ms": min(latency) if latency else None,
            "max_latency_ms": max(latency) if latency else None,
            "input_tokens_total": sum(input_tokens) if input_tokens else None,
            "output_tokens_total": sum(output_tokens) if output_tokens else None,
            "total_tokens_total": (sum(input_tokens) + sum(output_tokens)) if input_tokens and output_tokens else None,
            "input_token_observations": len(input_tokens),
            "output_token_observations": len(output_tokens),
            "mean_input_tokens": _mean(input_tokens),
            "median_input_tokens": _median(input_tokens),
            "mean_output_tokens": _mean(output_tokens),
            "median_output_tokens": _median(output_tokens),
            "mean_total_tokens": _mean(total_tokens),
            "median_total_tokens": _median(total_tokens),
        })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_reports(root: Path, *, rubric_dir: Path, pairwise_dir: Path) -> dict[str, Any]:
    root = root.resolve()
    validation = _root_and_hash(root)
    tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
    sources = _canonical_runs(root)
    rescored = _load_rescored(root, sources)
    rubric_scores, rubric_mappings = _load_rubric_scores(rubric_dir.resolve())
    pairwise_scores, pairwise_decisions, pairwise_mappings = _load_pairwise_scores(pairwise_dir.resolve())
    rubric_summary = _read_json(rubric_dir.resolve() / "summary.json")
    pairwise_summary = _read_json(pairwise_dir.resolve() / "summary.json")
    if rubric_summary.get("status") != "COMPLETE" or pairwise_summary.get("status") != "COMPLETE":
        raise ValueError("cannot aggregate incomplete judge artifacts")
    if rubric_summary.get("requested_model") != CODEX_JUDGE_MODEL or pairwise_summary.get("requested_model") != CODEX_JUDGE_MODEL:
        raise ValueError("judge artifacts do not use the authorized gpt-6-sol judge")
    probe_dir = Path(rubric_summary["probe_artifact_dir"]).resolve()
    probe_summary = _read_json(probe_dir / "summary.json")
    if probe_summary.get("canonical_artifact_hashes") != _canonical_artifact_hashes(root):
        raise ValueError("canonical run artifacts changed after synthetic judge probes")
    if pairwise_summary.get("probe_artifact_dir") != rubric_summary.get("probe_artifact_dir"):
        raise ValueError("rubric and pairwise judging did not use the same probe-qualified transport")

    records: list[dict[str, Any]] = []
    for source, run in sources.items():
        for task in tasks:
            task_id = task["id"]
            score = rescored[source][task_id]
            components = {
                "deterministic_score": score.get("deterministic_score"),
                "rubric_score": rubric_scores.get((source, task_id)),
                "constraints_score": score.get("constraint_score"),
                "pairwise_score": pairwise_scores.get((source, SOURCE_REPEATS[source], task_id)),
            }
            available = [(key.removesuffix("_score"), value) for key, value in components.items() if isinstance(value, (int, float))]
            weight_sum = sum(CAPABILITY_WEIGHTS[key] for key, _ in available)
            capability = sum(CAPABILITY_WEIGHTS[key] * float(value) for key, value in available) / weight_sum if weight_sum else None
            records.append({
                "source": source,
                "model": SOURCE_MODELS[source],
                "repeat": SOURCE_REPEATS[source],
                "run_id": run["run_id"],
                "task_id": task_id,
                "category": task["category"],
                "status": run["responses"][task_id].get("status"),
                **components,
                "capability_score": capability,
                "applicable_weight_sum": weight_sum,
                "scorer_version": SCORER_VERSION,
                "judge_version": JUDGE_VERSION,
            })

    overall: list[dict[str, Any]] = []
    for model in sorted({item["model"] for item in records}):
        model_records = [item for item in records if item["model"] == model]
        summary = _component_summary(model_records)
        summary.update({
            "model": model,
            "run_count": 2,
            "task_design_count": len(tasks),
            "generation_count": len(model_records),
            "error_count": sum(item["status"] == "ERROR" for item in model_records),
            "error_rate": sum(item["status"] == "ERROR" for item in model_records) / len(model_records),
            "mean_task_capability_score": _mean([item["capability_score"] for item in model_records if isinstance(item.get("capability_score"), (int, float))]),
        })
        overall.append(summary)

    categories: list[dict[str, Any]] = []
    for model in sorted({item["model"] for item in records}):
        for category in sorted({item["category"] for item in records}):
            subset = [item for item in records if item["model"] == model and item["category"] == category]
            summary = _component_summary(subset)
            summary.update({"model": model, "category": category, "task_observation_count": len(subset)})
            categories.append(summary)

    repeat_rows: list[dict[str, Any]] = []
    for model in sorted({item["model"] for item in records}):
        first = {item["task_id"]: item for item in records if item["model"] == model and item["repeat"] == 1}
        second = {item["task_id"]: item for item in records if item["model"] == model and item["repeat"] == 2}
        for component in ("capability_score", "deterministic_score", "rubric_score", "constraints_score", "pairwise_score"):
            pairs = [(first[task_id].get(component), second[task_id].get(component)) for task_id in first.keys() & second.keys()]
            numeric = [(float(a), float(b)) for a, b in pairs if isinstance(a, (int, float)) and isinstance(b, (int, float))]
            repeat_rows.append({
                "model": model,
                "component": component,
                "task_count": len(pairs),
                "both_scored_count": len(numeric),
                "exact_agreement_rate": (sum(a == b for a, b in numeric) / len(numeric)) if numeric else None,
                "mean_absolute_difference": _mean([abs(a - b) for a, b in numeric]),
            })

    pairwise_rows: list[dict[str, Any]] = []
    pairwise_counts = {"gpt-5.6-luna": {"W": 0, "L": 0, "T": 0}, "gpt-6-luna": {"W": 0, "L": 0, "T": 0}}
    for decision in pairwise_decisions:
        winner = decision["winner"]
        if winner == "A":
            winner_source = decision["a_source"]
        elif winner == "B":
            winner_source = decision["b_source"]
        else:
            winner_source = None
        for source in (decision["a_source"], decision["b_source"]):
            model = SOURCE_MODELS[source]
            result = "T" if winner == "TIE" else ("W" if source == winner_source else "L")
            pairwise_counts[model][result] += 1
        pairwise_rows.append({
            **decision,
            "winner_model": SOURCE_MODELS[winner_source] if winner_source else "TIE",
        })
    missing_pairwise = [
        {
            "repeat": item["repeat"],
            "task_id": item["task_id"],
            "reason": "gpt-5.6-luna Repeat 1 terminal ERROR; no response fabricated",
        }
        for item in records
        if item["source"] == "l56-r1" and item["status"] == "ERROR"
    ]

    replicated: list[dict[str, Any]] = []
    for task in tasks:
        task_id = task["id"]
        deltas: dict[str, float] = {}
        for repeat in (1, 2):
            old = next(item for item in records if item["source"] == f"l56-r{repeat}" and item["task_id"] == task_id)
            new = next(item for item in records if item["source"] == f"l6-r{repeat}" and item["task_id"] == task_id)
            if isinstance(old.get("capability_score"), (int, float)) and isinstance(new.get("capability_score"), (int, float)):
                deltas[f"r{repeat}"] = float(new["capability_score"]) - float(old["capability_score"])
        if len(deltas) == 2 and deltas["r1"] != 0 and deltas["r2"] != 0 and (deltas["r1"] > 0) == (deltas["r2"] > 0):
            replicated.append({
                "task_id": task_id,
                "category": task["category"],
                "direction": "improvement" if deltas["r1"] > 0 else "regression",
                "repeat_1_delta": deltas["r1"],
                "repeat_2_delta": deltas["r2"],
                "mean_delta": (deltas["r1"] + deltas["r2"]) / 2,
            })
    replicated.sort(key=lambda item: (item["direction"], -abs(item["mean_delta"])))

    performance = _performance_rows(sources)
    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(reports_dir / "per_task.csv", records)
    _write_csv(reports_dir / "per_category.csv", categories)
    _write_csv(reports_dir / "repeat_consistency.csv", repeat_rows)
    _write_csv(reports_dir / "pairwise.csv", pairwise_rows)
    _write_csv(reports_dir / "performance.csv", performance)
    results = {
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_sha256": validation["tasks_sha256"],
        "scorer_version": SCORER_VERSION,
        "judge": {
            "judge_version": JUDGE_VERSION,
            "requested_model": CODEX_JUDGE_MODEL,
            "transport": CODEX_CLI_INTERFACE,
            "provider_returned_model": NOT_EXPOSED,
            "picker_equivalence": "unverified",
            "rubric_seed": RUBRIC_SEED,
            "pairwise_seed": PAIRWISE_SEED,
            "rubric_artifact_dir": str(rubric_dir.resolve()),
            "pairwise_artifact_dir": str(pairwise_dir.resolve()),
            "probe_artifact_dir": str(probe_dir),
            "codex_version": rubric_summary.get("codex_version", NOT_EXPOSED),
            "rubric_judged_cases": rubric_summary.get("judged_cases"),
            "pairwise_judged_cases": pairwise_summary.get("judged_cases"),
            "codex_versions_capture": sorted({item["codex_version"] for item in performance if item.get("codex_version") not in {None, NOT_EXPOSED}}),
        },
        "sources": {
            source: {
                "run_id": run["run_id"],
                "model_requested": SOURCE_MODELS[source],
                "provider": run["metadata"].get("provider"),
                "transport": run["metadata"].get("transport", run["metadata"].get("interface")),
                "provider_returned_model": run["metadata"].get("provider_returned_model", NOT_EXPOSED),
                "picker_equivalence": run["metadata"].get("chatgpt_picker_equivalence", "unverified"),
                "codex_version": run["metadata"].get("codex_version"),
                "scorer_at_capture": run["metadata"].get("scorer_version"),
            }
            for source, run in sources.items()
        },
        "overall": overall,
        "categories": categories,
        "per_task": records,
        "repeat_consistency": repeat_rows,
        "pairwise": {
            "counts": pairwise_counts,
            "judged_count": len(pairwise_rows),
            "missing": missing_pairwise,
            "decisions": pairwise_rows,
        },
        "performance": performance,
        "primary_generation_count": sum(item["generation_count"] for item in performance if item["source"] != "pooled-two-repeats"),
        "canonical_run_ids": [sources[key]["run_id"] for key in CANONICAL_SOURCES],
        "replicated_changes": replicated,
        "aggregation": {
            "weights": CAPABILITY_WEIGHTS,
            "procedure": "For each task and model-repeat, average only applicable non-missing components after renormalizing their preregistered weights. Overall and category component averages likewise exclude non-applicable/missing values, then renormalize only over components with observations. Terminal ERROR has no capability component and is reported separately as an error.",
            "missing_is_zero": False,
        },
        "limitations": [
            "The four canonical runs use Codex CLI 0.153.4 for GPT-5.6 Luna and 0.156.0 for GPT-6 Luna; latency and token differences are end-to-end observations, not isolated architecture effects.",
            "Provider-returned model identity is not exposed and ChatGPT picker equivalence is unverified.",
            "The 30 tasks are repeated twice per model; the 60 model-task observations are not 60 independent task designs.",
            "The GPT-5.6 Luna Repeat 1 REAS-02 execution is an ERROR with no fabricated response or pairwise decision.",
            "Judge outputs are one evaluation per response/pair; no statistical significance claim is made.",
        ],
    }
    _write_json(reports_dir / "results.json", results, overwrite=True)
    _write_comparison_markdown(reports_dir / "comparison.md", results)
    _write_methodology_limits(reports_dir / "methodology_limitations.md", results)
    _write_executive_summary(reports_dir / "EXECUTIVE_SUMMARY.md", results)
    return results


def _number(value: Any, digits: int = 4) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.{digits}f}"
    return "n/a"


def _write_comparison_markdown(path: Path, results: dict[str, Any]) -> None:
    overall = {item["model"]: item for item in results["overall"]}
    lines = [
        "# GPT-5.6 Luna vs GPT-6 Luna comparison",
        "",
        "This comparison measures GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth. It does not establish direct equivalence to the ChatGPT model picker; picker equivalence is unverified and provider-returned model identity is `not_exposed`.",
        "",
        f"Benchmark: `{results['benchmark_version']}`",
        f"Benchmark SHA-256: `{results['benchmark_sha256']}`",
        f"Final scorer: `{results['scorer_version']}`",
        f"Primary generations represented: `{results['primary_generation_count']}` across four canonical runs.",
        "",
        "## Overall capability results",
        "",
        "The primary capability score is the arithmetic mean of the per-task normalized scores. For each task, only applicable components are included and their preregistered weights are renormalized. Missing and non-applicable components are not treated as zero.",
        "",
        "| Model | Capability | Deterministic | Rubric | Constraints | Pairwise | Error rate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for model in ("gpt-5.6-luna", "gpt-6-luna"):
        item = overall[model]
        averages = item["component_averages"]
        lines.append(
            f"| {model} | {_number(item['capability_score'])} | {_number(averages.get('deterministic'))} | {_number(averages.get('rubric'))} | {_number(averages.get('constraints'))} | {_number(averages.get('pairwise'))} | {_number(item['error_rate'])} |"
        )

    lines.extend(["", "## Category results", "", "| Model | Category | Capability | Deterministic | Rubric | Constraints | Pairwise |", "|---|---|---:|---:|---:|---:|---:|"])
    for item in results["categories"]:
        averages = item["component_averages"]
        lines.append(
            f"| {item['model']} | {item['category']} | {_number(item['capability_score'])} | {_number(averages.get('deterministic'))} | {_number(averages.get('rubric'))} | {_number(averages.get('constraints'))} | {_number(averages.get('pairwise'))} |"
        )

    pairwise = results["pairwise"]
    lines.extend([
        "",
        "## Blind pairwise preference",
        "",
        f"Judged pairs: `{pairwise['judged_count']}`. GPT-5.6 Luna W/L/T: `{pairwise['counts']['gpt-5.6-luna']['W']}/{pairwise['counts']['gpt-5.6-luna']['L']}/{pairwise['counts']['gpt-5.6-luna']['T']}`. GPT-6 Luna W/L/T: `{pairwise['counts']['gpt-6-luna']['W']}/{pairwise['counts']['gpt-6-luna']['L']}/{pairwise['counts']['gpt-6-luna']['T']}`.",
        "",
        "The GPT-5.6 Luna Repeat 1 REAS-02 execution was an ERROR. It was excluded from pairwise judging and no response was fabricated.",
        "",
        "## Repeat consistency",
        "",
        "See `repeat_consistency.csv` for component-level exact agreement and mean absolute differences across the two repeats. The two repeats are repeated observations of the same 30 task designs, not independent task samples.",
        "",
        "| Model | Component | Both scored | Exact agreement | Mean absolute difference |",
        "|---|---|---:|---:|---:|",
    ])
    for item in results["repeat_consistency"]:
        lines.append(f"| {item['model']} | {item['component']} | {item['both_scored_count']} | {_number(item['exact_agreement_rate'])} | {_number(item['mean_absolute_difference'])} |")

    lines.extend(["", "## End-to-end performance", "", "Performance is reported separately from capability and is not attributed solely to model architecture. GPT-5.6 Luna used Codex CLI 0.153.4; GPT-6 Luna used Codex CLI 0.156.0. Token counts include Codex transport/context overhead.", "", "| Model | Mean latency ms | Median | P90 | Min | Max | Mean input tokens | Mean output tokens | Mean total tokens |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for item in results["performance"]:
        if item["source"] != "pooled-two-repeats":
            continue
        lines.append(
            f"| {item['model']} | {_number(item['mean_latency_ms'], 1)} | {_number(item['median_latency_ms'], 1)} | {_number(item['p90_latency_ms'], 1)} | {_number(item['min_latency_ms'], 1)} | {_number(item['max_latency_ms'], 1)} | {_number(item['mean_input_tokens'], 1)} | {_number(item['mean_output_tokens'], 1)} | {_number(item['mean_total_tokens'], 1)} |"
        )

    improvements = [item for item in results["replicated_changes"] if item["direction"] == "improvement"][:5]
    regressions = [item for item in results["replicated_changes"] if item["direction"] == "regression"][:5]
    lines.extend(["", "## Largest replicated changes", ""])
    if improvements:
        lines.append("Replicated improvements across both repeats:")
        lines.append("")
        lines.extend(f"- `{item['task_id']}` ({item['category']}): mean capability delta `{item['mean_delta']:+.4f}` (Repeat 1 `{item['repeat_1_delta']:+.4f}`, Repeat 2 `{item['repeat_2_delta']:+.4f}`)." for item in improvements)
    else:
        lines.append("No non-zero capability improvement replicated across both repeats.")
    lines.append("")
    if regressions:
        lines.append("Replicated regressions across both repeats:")
        lines.append("")
        lines.extend(f"- `{item['task_id']}` ({item['category']}): mean capability delta `{item['mean_delta']:+.4f}` (Repeat 1 `{item['repeat_1_delta']:+.4f}`, Repeat 2 `{item['repeat_2_delta']:+.4f}`)." for item in regressions)
    else:
        lines.append("No non-zero capability regression replicated across both repeats.")

    lines.extend(["", "## Interpretation limits", "", "No forced overall winner is declared. No statistical significance claim is made. The report supports only observations on this frozen 30-task distribution, under the stated Codex transports and CLI versions. It does not establish universal capability, causal architectural explanations, or equivalence with the ChatGPT model picker.", "", "Detailed methodology and limitations are in `methodology_limitations.md`; machine-readable data are in `results.json` and the CSV artifacts."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_methodology_limits(path: Path, results: dict[str, Any]) -> None:
    lines = [
        "# Methodology and limitations for the completed comparison",
        "",
        "## Frozen inputs and primary evidence",
        "",
        f"- Benchmark: `{results['benchmark_version']}` with task SHA-256 `{results['benchmark_sha256']}`.",
        f"- Canonical runs: `{', '.join(results['canonical_run_ids'])}`.",
        f"- Primary generations: `{results['primary_generation_count']}`. Smoke/probe generations are excluded from this count.",
        f"- Final scorer: `{results['scorer_version']}`. The four raw run directories and their captured responses are not modified by rescoring or judging.",
        "- Comparison labels are GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth.",
        "- Provider-returned model identity is `not_exposed`; equivalence to the ChatGPT model picker is `unverified`.",
        "",
        "## Aggregation",
        "",
        "The preregistered component weights are deterministic/objective correctness 45%, task-specific rubric 30%, constraint compliance 15%, and blind pairwise preference 10%.",
        "",
        "For each model, repeat, and task, only components that apply to that task and have a valid score are included. The applicable preregistered weights are renormalized to sum to one for that task. Missing or non-applicable components are not assigned zero. The overall and category capability scores are arithmetic means of those per-task normalized scores; component averages and applicability counts are reported separately.",
        "",
        "Terminal execution errors have no correctness or constraint score. They remain in the denominator for generation/error reporting but not in capability-score averages. GPT-5.6 Luna Repeat 1 REAS-02 is the predefined missing-response case and has no fabricated output or pairwise decision.",
        "",
        "## Blind rubric judging",
        "",
        f"- Judge requested model: `{results['judge']['requested_model']}`.",
        f"- Judge transport: `{results['judge']['transport']}`; Codex version: `{results['judge']['codex_version']}`.",
        "- Each invocation used a fresh ephemeral Codex CLI session, a fresh temporary working directory outside the repository, read-only sandbox, disabled web and tools, disabled memories, ignored user configuration/rules, and no repository context.",
        "- Rubric prompts contained only the task prompt, frozen task-specific rubric, relevant reference concepts, and an anonymous response. They did not contain model identity, run ID, repeat, deterministic score, latency, tokens, comparison responses, or previous judge decisions.",
        f"- Rubric order was randomized with fixed seed `{results['judge']['rubric_seed']}`. Judged cases: `{results['judge']['rubric_judged_cases']}`.",
        "- Exact judge prompts, raw provider executions, raw final responses, parsed results, and anonymous mappings are preserved under the judge artifact directory in `results.json`.",
        "",
        "## Blind pairwise judging",
        "",
        "- Each pair contained the task, its rubric, Response A, and Response B only. A/B assignment was randomized independently per task and repeat with a fixed stored seed.",
        f"- Pairwise seed: `{results['judge']['pairwise_seed']}`. Judged pairs: `{results['judge']['pairwise_judged_cases']}`.",
        "- A/B mappings are stored separately from judge prompts and results. Model identities are not exposed to the judge prompt.",
        "",
        "## Performance caveat",
        "",
        "GPT-5.6 Luna capture used Codex CLI 0.153.4 and GPT-6 Luna capture used Codex CLI 0.156.0. Latency and token differences are end-to-end observations under different transport versions and cannot be attributed solely to model architecture. Token counts include Codex transport/context overhead. Performance is not part of the capability score.",
        "",
        "## Statistical and interpretive limits",
        "",
        "The two repeats provide repeat-variance evidence but do not turn the 60 observations per model into 60 independent task designs. No statistical significance test was run, so no significance claim is made. Replicated changes are defined as non-zero capability deltas with the same direction in both matched repeats; they are descriptive, not inferential.",
        "",
        "Synthetic judge probes are not benchmark tasks and are excluded from all primary counts and scores. No further Luna inference was performed during scoring, judging, or reporting.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_executive_summary(path: Path, results: dict[str, Any]) -> None:
    overall = {item["model"]: item for item in results["overall"]}
    improvements = [item for item in results["replicated_changes"] if item["direction"] == "improvement"][:3]
    regressions = [item for item in results["replicated_changes"] if item["direction"] == "regression"][:3]
    lines = [
        "# Executive summary",
        "",
        "This is a bounded comparison of GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth on the frozen `luna-comparison-v1.0` benchmark.",
        "",
        f"- GPT-5.6 Luna capability score: **{_number(overall['gpt-5.6-luna']['capability_score'])}**.",
        f"- GPT-6 Luna capability score: **{_number(overall['gpt-6-luna']['capability_score'])}**.",
        f"- Blind pairwise: GPT-5.6 Luna `{results['pairwise']['counts']['gpt-5.6-luna']['W']}/{results['pairwise']['counts']['gpt-5.6-luna']['L']}/{results['pairwise']['counts']['gpt-5.6-luna']['T']}` W/L/T; GPT-6 Luna `{results['pairwise']['counts']['gpt-6-luna']['W']}/{results['pairwise']['counts']['gpt-6-luna']['L']}/{results['pairwise']['counts']['gpt-6-luna']['T']}` W/L/T.",
        f"- Primary generations: `{results['primary_generation_count']}`. One GPT-5.6 Luna Repeat 1 execution, REAS-02, was an ERROR and was not fabricated or pairwise judged.",
        "",
        "## Replicated changes",
        "",
    ]
    if improvements:
        lines.append("Largest replicated improvements:")
        lines.extend(f"- `{item['task_id']}`: mean capability delta `{item['mean_delta']:+.4f}`." for item in improvements)
    else:
        lines.append("No non-zero improvement replicated across both repeats.")
    if regressions:
        lines.append("Largest replicated regressions:")
        lines.extend(f"- `{item['task_id']}`: mean capability delta `{item['mean_delta']:+.4f}`." for item in regressions)
    else:
        lines.append("No non-zero regression replicated across both repeats.")
    lines.extend([
        "",
        "## Bottom line",
        "",
        "The measurements describe this frozen task distribution and its repeat behavior. They do not justify a universal winner, a causal architecture claim, a statistical significance claim, or direct equivalence to a ChatGPT model-picker label.",
        "",
        f"Benchmark SHA-256: `{results['benchmark_sha256']}`. Final scorer: `{results['scorer_version']}`.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_capture_manifest(root: Path, results: dict[str, Any]) -> dict[str, Any]:
    """Write additive provenance for the completed Luna 6 comparison."""

    root = root.resolve()
    current_hashes = _canonical_artifact_hashes(root)
    probe_dir = Path(results["judge"]["probe_artifact_dir"])
    probe_summary = _read_json(probe_dir / "summary.json")
    manifest = {
        "benchmark_version": results["benchmark_version"],
        "benchmark_sha256": results["benchmark_sha256"],
        "frozen_benchmark_commit": FROZEN_BENCHMARK_COMMIT,
        "scorer_version": results["scorer_version"],
        "canonical_runs": results["sources"],
        "canonical_run_ids": results["canonical_run_ids"],
        "primary_generation_count": results["primary_generation_count"],
        "smoke_and_probe_runs_excluded": True,
        "raw_capture_artifact_hashes": current_hashes,
        "raw_capture_hashes_match_probe_baseline": current_hashes == probe_summary.get("canonical_artifact_hashes"),
        "judge": results["judge"],
        "reports": [
            "reports/comparison.md",
            "reports/results.json",
            "reports/per_task.csv",
            "reports/per_category.csv",
            "reports/repeat_consistency.csv",
            "reports/pairwise.csv",
            "reports/performance.csv",
            "reports/methodology_limitations.md",
            "reports/EXECUTIVE_SUMMARY.md",
        ],
        "created_at": utc_now(),
    }
    _write_json(root / "LUNA_6_CAPTURE_MANIFEST.json", manifest, overwrite=True)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blind judging and aggregation for the frozen Luna comparison")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)

    probes = subparsers.add_parser("probes", help="run synthetic non-benchmark judge probes")
    probes.add_argument("--codex-binary", default="codex")
    probes.add_argument("--timeout-seconds", type=float, default=120.0)

    subparsers.add_parser("rescore", help="rescore canonical runs with the frozen final scorer")

    for name in ("rubric", "pairwise"):
        command = subparsers.add_parser(name)
        command.add_argument("--probe-artifact", type=Path, required=True)
        command.add_argument("--max-infrastructure-retries", type=int, default=1)
        command.add_argument("--max-workers", type=int, default=4)

    aggregate = subparsers.add_parser("aggregate", help="write final comparison artifacts")
    aggregate.add_argument("--rubric-dir", type=Path, required=True)
    aggregate.add_argument("--pairwise-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "probes":
            result = run_judge_probes(args.root, codex_binary=args.codex_binary, timeout_seconds=args.timeout_seconds)
            status = result["status"]
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if status == "JUDGE_PROBE_PASSED" else 1
        if args.command == "rescore":
            result = rescore_canonical_runs(args.root)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "rubric":
            result = run_rubric_judging(args.root, probe_artifact=args.probe_artifact, max_infrastructure_retries=args.max_infrastructure_retries, max_workers=args.max_workers)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "COMPLETE" else 2
        if args.command == "pairwise":
            result = run_pairwise_judging(args.root, probe_artifact=args.probe_artifact, max_infrastructure_retries=args.max_infrastructure_retries, max_workers=args.max_workers)
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0 if result["status"] == "COMPLETE" else 2
        if args.command == "aggregate":
            results = aggregate_reports(args.root, rubric_dir=args.rubric_dir, pairwise_dir=args.pairwise_dir)
            manifest = write_capture_manifest(args.root, results)
            print(json.dumps({"status": "COMPLETE", "results": "reports/results.json", "capture_manifest": "LUNA_6_CAPTURE_MANIFEST.json", "primary_generation_count": results["primary_generation_count"], "raw_capture_hashes_match_probe_baseline": manifest["raw_capture_hashes_match_probe_baseline"]}, ensure_ascii=False, sort_keys=True))
            return 0
    except Exception as exc:
        status = "PROBE_ERROR" if args.command == "probes" else "EVALUATION_ERROR"
        print(json.dumps({"status": status, "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

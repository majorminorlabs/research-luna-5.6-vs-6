"""Frozen benchmark and answer-key validation.

The validator is intentionally provider-free.  It proves properties of the
benchmark before any model output can influence the frozen task set.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from pathlib import Path
from typing import Any, Iterable


EXPECTED_IDS = [
    "CODE-01", "CODE-02", "CODE-03", "CODE-04", "CODE-05", "CODE-06",
    "REAS-01", "REAS-02", "REAS-03", "REAS-04", "REAS-05",
    "EVID-01", "EVID-02", "EVID-03", "EVID-04", "EVID-05",
    "EXTR-01", "EXTR-02", "EXTR-03", "EXTR-04",
    "AGENT-01", "AGENT-02", "AGENT-03", "AGENT-04",
    "CTX-01", "CTX-02", "CTX-03",
    "WRITE-01", "WRITE-02", "WRITE-03",
]
EXPECTED_CATEGORIES = {"CODE", "REAS", "EVID", "EXTR", "AGENT", "CTX", "WRITE"}


class ValidationError(ValueError):
    """Raised when a frozen benchmark invariant is not satisfied."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_tasks(path: Path) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValidationError(f"blank line in tasks JSONL at line {line_number}")
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"invalid JSON at tasks line {line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValidationError(f"tasks line {line_number} is not an object")
            for field in ("id", "category", "prompt"):
                if not isinstance(value.get(field), str) or not value[field]:
                    raise ValidationError(f"tasks line {line_number} has invalid {field}")
            tasks.append(value)
    return tasks


def load_answer_keys(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), dict):
        raise ValidationError("answer_keys.json must contain a tasks object")
    return value


def solve_reas01() -> list[dict[str, str]]:
    """Independently enumerate REAS-01 after the documented correction."""

    solutions: list[dict[str, str]] = []
    people = ("Arin", "Bea", "Cole", "Dara")
    for experiments in itertools.permutations("WXYZ"):
        assignment = dict(zip(people, experiments))
        if assignment["Arin"] in {"W", "Z"}:
            continue
        if assignment["Bea"] == "X":
            continue
        if assignment["Cole"] in {"X", "Y", "Z"}:
            continue
        if assignment["Dara"] == "Z":
            continue
        if assignment["Bea"] == "Y":
            continue
        if assignment["Arin"] != "Y" and assignment["Bea"] != "Y":
            continue
        solutions.append(assignment)
    return solutions


def solve_reas04() -> list[str]:
    solutions: list[str] = []
    for schedule in itertools.permutations("ABCDE"):
        positions = {item: schedule.index(item) for item in schedule}
        if positions["A"] >= positions["C"]:
            continue
        if positions["D"] != positions["B"] + 1:
            continue
        if positions["E"] in {0, 4}:
            continue
        if positions["C"] == 4:
            continue
        if abs(positions["A"] - positions["E"]) == 1:
            continue
        solutions.append("".join(schedule))
    return solutions


def calculate_reas02() -> dict[str, float | int]:
    parameter_count = 27_000_000_000
    weight_gib = parameter_count * 4 / 8 / (2**30)
    workspace_gib = weight_gib * 0.12
    fixed_gib = 1.8
    capacity_gib = 18.0
    kv_gib = 0.42
    available_for_kv = capacity_gib - fixed_gib - weight_gib - workspace_gib
    return {
        "weight_memory_gib": weight_gib,
        "workspace_gib": workspace_gib,
        "available_for_kv_gib": available_for_kv,
        "maximum_sequences": int(available_for_kv // kv_gib),
    }


def canonical_compact_ranges(values: Iterable[int]) -> str:
    numbers = sorted(set(values))
    if not numbers:
        return ""
    parts: list[str] = []
    index = 0
    while index < len(numbers):
        end = index
        while end + 1 < len(numbers) and numbers[end + 1] == numbers[end] + 1:
            end += 1
        run_length = end - index + 1
        if run_length >= 3:
            parts.append(f"{numbers[index]}-{numbers[end]}")
        else:
            parts.extend(str(number) for number in numbers[index : end + 1])
        index = end + 1
    return ",".join(parts)


def _word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'-]+\b", text))


def check_extr03_constraints(text: str) -> dict[str, Any]:
    stripped = text.strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", stripped) if part.strip()]
    sentence_three = sentences[2].lower() if len(sentences) >= 3 else ""
    analogy_markers = ("analogy", "imagine", "as if", "similar to", "like a ", "like an ")
    return {
        "sentence_count": len(sentences),
        "first_prefix": bool(sentences and sentences[0].startswith("An index")),
        "second_contains_tradeoff": bool(len(sentences) >= 2 and "tradeoff" in sentences[1].lower()),
        "third_has_example": any(marker in sentence_three for marker in ("for example", "e.g.", "such as", "example:")),
        "has_semicolon": ";" in stripped,
        "has_analogy": any(marker in stripped.lower() for marker in analogy_markers),
        "word_count": _word_count(stripped),
    }


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def validate_benchmark(
    root: Path,
    *,
    require_manifest: bool = True,
) -> dict[str, Any]:
    benchmark_dir = root / "benchmark"
    tasks_path = benchmark_dir / "tasks.jsonl"
    keys_path = benchmark_dir / "answer_keys.json"
    manifest_path = benchmark_dir / "manifest.json"
    tasks = load_tasks(tasks_path)
    answer_keys = load_answer_keys(keys_path)

    task_ids = [task["id"] for task in tasks]
    if len(tasks) != 30:
        raise ValidationError(f"expected exactly 30 tasks, found {len(tasks)}")
    if len(set(task_ids)) != len(task_ids):
        raise ValidationError("task IDs are not unique")
    if task_ids != EXPECTED_IDS:
        raise ValidationError(f"task IDs/order differ from frozen list: {task_ids}")
    for task in tasks:
        if task["category"] not in EXPECTED_CATEGORIES:
            raise ValidationError(f"invalid category for {task['id']}: {task['category']}")
        if not task["prompt"].strip():
            raise ValidationError(f"empty prompt for {task['id']}")
    key_tasks = answer_keys["tasks"]
    if set(key_tasks) != set(task_ids):
        missing = sorted(set(task_ids) - set(key_tasks))
        extra = sorted(set(key_tasks) - set(task_ids))
        raise ValidationError(f"answer-key mismatch; missing={missing}, extra={extra}")

    reas01 = solve_reas01()
    expected_reas01 = key_tasks["REAS-01"]["deterministic"]["assignment"]
    if reas01 != [expected_reas01]:
        raise ValidationError(f"REAS-01 is not uniquely solved: {reas01}")
    reas04 = solve_reas04()
    if reas04 != key_tasks["REAS-04"]["deterministic"]["schedules"]:
        raise ValidationError(f"REAS-04 answer key mismatch: {reas04}")
    reas02 = calculate_reas02()
    if reas02["maximum_sequences"] != key_tasks["REAS-02"]["deterministic"]["maximum_sequences"]:
        raise ValidationError(f"REAS-02 answer key mismatch: {reas02}")
    if canonical_compact_ranges([8, 1, 3, 2, 2, 10, 11, 12, -2, -1]) != "-2,-1,1-3,8,10-12":
        raise ValidationError("canonical CODE-03 implementation failed its supplied example")

    exact_expected = {
        "EXTR-01": key_tasks["EXTR-01"]["deterministic"]["expected"],
        "EXTR-02": key_tasks["EXTR-02"]["deterministic"]["expected"],
        "EXTR-04": key_tasks["EXTR-04"]["deterministic"]["expected"],
        "EVID-03": key_tasks["EVID-03"]["deterministic"]["expected"],
    }
    for task_id, expected in exact_expected.items():
        if json.loads(_canonical_json(expected)) != expected:
            raise ValidationError(f"non-JSON answer key for {task_id}")
    ctx_prompt = next(task["prompt"] for task in tasks if task["id"] == "CTX-01")
    for required in ("Filler note 01", "Filler note 10", "The filler above is fixed benchmark content"):
        if required not in ctx_prompt:
            raise ValidationError(f"CTX-01 missing frozen filler marker: {required}")

    task_hash = sha256_file(tasks_path)
    answer_key_hash = sha256_file(keys_path)
    manifest: dict[str, Any] | None = None
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as handle:
            manifest = json.load(handle)
        if manifest.get("benchmark_version") != "luna-comparison-v1.0":
            raise ValidationError("manifest benchmark version is not luna-comparison-v1.0")
        if manifest.get("task_count") != 30:
            raise ValidationError("manifest task_count is not 30")
        if manifest.get("tasks_sha256") != task_hash:
            raise ValidationError("manifest tasks_sha256 does not match tasks.jsonl")
        if manifest.get("answer_keys_sha256") != answer_key_hash:
            raise ValidationError("manifest answer_keys_sha256 does not match answer_keys.json")
        if manifest.get("freeze_status") != "FROZEN":
            raise ValidationError("manifest does not mark the benchmark FROZEN")
    elif require_manifest:
        raise ValidationError("benchmark/manifest.json is required for a frozen validation")

    return {
        "status": "passed",
        "benchmark_version": "luna-comparison-v1.0",
        "task_count": len(tasks),
        "tasks_sha256": task_hash,
        "answer_keys_sha256": answer_key_hash,
        "reas01_solutions": reas01,
        "reas02": reas02,
        "reas04_solutions": reas04,
        "manifest": manifest,
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate the frozen Luna comparison benchmark")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--allow-missing-manifest", action="store_true")
    args = parser.parse_args()
    try:
        result = validate_benchmark(args.root, require_manifest=not args.allow_missing_manifest)
    except (OSError, ValidationError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2))
        raise SystemExit(1)
    print(json.dumps(result, indent=2, sort_keys=True))

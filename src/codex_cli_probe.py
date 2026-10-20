"""Run non-benchmark Codex CLI transport probes.

This module deliberately does not load benchmark tasks, answer keys, or the
benchmark runner.  Its outputs belong to transport qualification only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .runner import CODEX_CLI_INTERFACE, CODEX_LUNA_MODEL, CodexCLIProvider, ProviderError
except ImportError:
    from runner import CODEX_CLI_INTERFACE, CODEX_LUNA_MODEL, CodexCLIProvider, ProviderError


PROBES = (
    (
        "factual",
        "What is 2 + 2? Reply with exactly: four. Do not use tools.",
    ),
    (
        "json",
        'Return exactly this JSON object and nothing else: {"status":"ok","count":3}. Do not use markdown or tools.',
    ),
    (
        "coding",
        "Write a Python function named add_one(value) that returns value + 1. Return only the code. Do not use tools or files.",
    ),
)
DISALLOWED_ITEM_TYPES = {
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "web_search_call",
    "computer_call",
    "image_generation_call",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def run_probes(output_dir: Path, codex_binary: str, timeout_seconds: float) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    output_dir = output_dir.resolve()
    forbidden_roots = (repo_root / "benchmark", repo_root / "runs")
    if any(output_dir == root or root in output_dir.parents for root in forbidden_roots):
        raise ValueError("transport probe output must not be stored under benchmark/ or runs/")
    output_dir.mkdir(parents=True, exist_ok=False)

    provider = CodexCLIProvider(codex_binary, timeout_seconds)
    records: list[dict[str, Any]] = []
    cwd_values: list[str] = []
    for name, prompt in PROBES:
        payload = {
            "model": CODEX_LUNA_MODEL,
            "system_prompt": "",
            "user_prompt": prompt,
            "generation_parameters": {},
        }
        try:
            result = provider.call(payload)
            raw = result.raw if isinstance(result.raw, dict) else {}
            event_summary = raw.get("event_summary", {}) if isinstance(raw, dict) else {}
            item_types = event_summary.get("item_types", []) if isinstance(event_summary, dict) else []
            cwd = str(raw.get("cwd", ""))
            cwd_values.append(cwd)
            records.append({
                "probe": name,
                "prompt": prompt,
                "response_text": result.text,
                "raw_provider_execution": raw,
                "checks": {
                    "requested_model_exact": raw.get("requested_model") == CODEX_LUNA_MODEL,
                    "provider_returned_model_not_exposed": raw.get("provider_returned_model") == "not_exposed",
                    "final_answer_extraction_exact": raw.get("output_last_message") == result.text,
                    "isolated_working_directory": bool(raw.get("cwd_isolated_from_benchmark")) and cwd not in {str(repo_root), str(repo_root / "benchmark")},
                    "no_tool_item_types": not (set(item_types) & DISALLOWED_ITEM_TYPES),
                    "successful_process": raw.get("returncode") == 0,
                },
                "captured_at": utc_now(),
            })
        except ProviderError as exc:
            raw = exc.raw if isinstance(exc.raw, dict) else {}
            cwd = str(raw.get("cwd", "")) if isinstance(raw, dict) else ""
            cwd_values.append(cwd)
            records.append({
                "probe": name,
                "prompt": prompt,
                "error": str(exc),
                "raw_provider_execution": raw,
                "checks": {"successful_process": False},
                "captured_at": utc_now(),
            })

    checks = {
        "exact_requested_model": all(record["checks"].get("requested_model_exact", False) for record in records),
        "provider_identity_unexposed": all(record["checks"].get("provider_returned_model_not_exposed", False) for record in records),
        "final_answer_extraction": all(record["checks"].get("final_answer_extraction_exact", False) for record in records),
        "isolated_working_directories": all(record["checks"].get("isolated_working_directory", False) for record in records),
        "independent_invocations": len(cwd_values) == len(set(cwd_values)) == len(PROBES),
        "no_tool_events": all(record["checks"].get("no_tool_item_types", False) for record in records),
        "all_probes_succeeded": all(record["checks"].get("successful_process", False) for record in records),
    }
    summary = {
        "status": "passed" if all(checks.values()) else "failed",
        "transport": CODEX_CLI_INTERFACE,
        "requested_model": CODEX_LUNA_MODEL,
        "provider_returned_model": "not_exposed",
        "chatgpt_picker_equivalence": "unverified",
        "codex_version": provider.codex_version,
        "probe_count": len(records),
        "checks": checks,
        "completed_at": utc_now(),
    }
    write_jsonl(output_dir / "probes.jsonl", records)
    write_json(output_dir / "summary.json", summary)
    return {"output_dir": str(output_dir), **summary}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run synthetic, non-benchmark Codex CLI transport probes")
    default_output = Path(tempfile.mkdtemp(prefix="luna-codex-cli-probes-"))
    # The temporary directory is allocated before parsing only to keep the
    # default path explicit in the command result; it is not a benchmark run.
    default_output.rmdir()
    parser.add_argument("--output-dir", type=Path, default=default_output)
    parser.add_argument("--codex-binary", default="codex")
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    args = parser.parse_args(argv)
    try:
        result = run_probes(args.output_dir, args.codex_binary, args.timeout_seconds)
    except (OSError, ValueError, ProviderError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), flush=True)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

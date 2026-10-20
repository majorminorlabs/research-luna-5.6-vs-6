"""Single synthetic availability probe for the exact Luna 6 transport.

The probe intentionally does not load benchmark prompts or create a benchmark
run directory.  It only hashes the frozen task file for provenance, sends a
fixed synthetic prompt through the existing isolated Codex CLI provider, and
stores a separate probe record.
"""

from __future__ import annotations

import json
import os
import shlex
import time
import uuid
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .runner import (
        CODEX_6_LUNA_MODEL,
        CODEX_CLI_INTERFACE,
        NOT_EXPOSED,
        CodexCLIProvider,
        ProviderError,
        sha256_file,
        utc_now,
    )
except ImportError:
    from runner import (  # type: ignore
        CODEX_6_LUNA_MODEL,
        CODEX_CLI_INTERFACE,
        NOT_EXPOSED,
        CodexCLIProvider,
        ProviderError,
        sha256_file,
        utc_now,
    )


FROZEN_BENCHMARK_SHA256 = "ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d"
BENCHMARK_VERSION = "luna-comparison-v1.0"
PROBE_PROMPT = "Return exactly this string and nothing else:\nLUNA6_PROBE_OK"
EXPECTED_RESPONSE = "LUNA6_PROBE_OK"
AVAILABLE = "LUNA_6_AVAILABLE"
UNAVAILABLE = "LUNA_6_UNAVAILABLE"
PROBE_ERROR = "PROBE_ERROR"
DISALLOWED_ITEM_TYPES = {
    "command_execution",
    "computer_call",
    "file_change",
    "image_generation_call",
    "mcp_tool_call",
    "web_search_call",
}


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        handle.write("\n")


def _new_probe_dir(output_root: Path) -> tuple[str, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        probe_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        probe_dir = output_root / probe_id
        try:
            probe_dir.mkdir()
            return probe_id, probe_dir
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a unique Luna 6 probe directory")


def _redact_known_secrets(value: Any) -> Any:
    """Redact exact secret values without recording the environment itself."""

    secret_values = [
        candidate
        for key, candidate in os.environ.items()
        if any(marker in key.upper() for marker in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))
        and len(candidate) >= 8
    ]
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    if isinstance(value, list):
        return [_redact_known_secrets(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_known_secrets(item) for key, item in value.items()}
    return value


def _raw_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {"raw_value": raw}


def _event_summary(raw: dict[str, Any]) -> dict[str, Any]:
    summary = raw.get("event_summary")
    return summary if isinstance(summary, dict) else {}


def _before_generation(raw: dict[str, Any]) -> bool:
    summary = _event_summary(raw)
    return summary.get("agent_message_count", 0) == 0 and not raw.get("output_last_message")


def _error_text(error: str, raw: dict[str, Any]) -> str:
    pieces = [error]
    for key in ("stderr", "stdout_jsonl"):
        value = raw.get(key)
        if isinstance(value, str):
            pieces.append(value)
    return "\n".join(pieces).casefold()


def _is_model_access_rejection(error: str, raw: dict[str, Any]) -> bool:
    text = _error_text(error, raw)
    exact_patterns = (
        "model is not supported when using codex with a chatgpt account",
        "model is not supported with a chatgpt account",
        "unknown model",
        "model not found",
        "model is not available",
        "model unavailable",
        "access denied for model",
        "not authorized to use model",
    )
    return any(pattern in text for pattern in exact_patterns)


def _fallback_detected(raw: dict[str, Any]) -> bool:
    text = "\n".join(
        value
        for key in ("stderr", "stdout_jsonl")
        if isinstance((value := raw.get(key)), str)
    ).casefold()
    return any(pattern in text for pattern in ("fallback model", "fallback metadata", "defaulting to fallback", "model substitution"))


def _retry_command(args: Namespace) -> str:
    command = [
        "PYTHONPATH=src",
        "python3",
        "-m",
        "runner",
        "probe",
        "--model",
        CODEX_6_LUNA_MODEL,
        "--provider",
        "codex-cli",
    ]
    if args.codex_binary != "codex":
        command.extend(("--codex-binary", args.codex_binary))
    if args.timeout_seconds != 120.0:
        command.extend(("--timeout-seconds", str(args.timeout_seconds)))
    return shlex.join(command)


def _public_result(
    *,
    status: str,
    probe_path: Path,
    error_class: str,
    before_generation: bool | str,
    retry_command: str,
    provider_returned_model: str = NOT_EXPOSED,
    final_response: str = "",
) -> dict[str, Any]:
    result = {
        "status": status,
        "error_class": error_class,
        "rejection_before_generation": before_generation,
        "probe_artifact": str(probe_path),
        "retry_command": retry_command,
    }
    if status == AVAILABLE:
        result.update({
            "requested_model": CODEX_6_LUNA_MODEL,
            "transport": CODEX_CLI_INTERFACE,
            "provider_returned_model": provider_returned_model,
            "final_response": final_response,
        })
    return result


def run_probe(args: Namespace) -> dict[str, Any]:
    """Run exactly one synthetic probe and return a machine-readable result."""

    root = Path(args.root).resolve()
    output_root = Path(args.output_root).resolve() if args.output_root else root / "probes" / "luna6"
    if output_root == root / "benchmark" or (root / "benchmark") in output_root.parents:
        raise ValueError("probe artifacts cannot be stored under benchmark/")
    if output_root == root / "runs" or (root / "runs") in output_root.parents:
        raise ValueError("probe artifacts cannot be stored under runs/")

    probe_id, probe_dir = _new_probe_dir(output_root)
    probe_path = probe_dir / "probe.json"
    request_path = probe_dir / "request.json"
    raw_path = probe_dir / "raw_execution.json"
    retry_command = _retry_command(args)
    started_at = utc_now()
    benchmark_path = root / "benchmark" / "tasks.jsonl"
    benchmark_sha256 = NOT_EXPOSED
    benchmark_error = None
    try:
        benchmark_sha256 = sha256_file(benchmark_path)
    except (OSError, ValueError) as exc:
        benchmark_error = str(exc)

    request = {
        "probe_id": probe_id,
        "created_at": started_at,
        "requested_model": args.model,
        "transport": CODEX_CLI_INTERFACE,
        "provider": args.provider,
        "system_prompt": "",
        "user_prompt": PROBE_PROMPT,
        "generation_parameters": {},
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_sha256": benchmark_sha256,
        "benchmark_task_used": False,
    }
    _write_json(request_path, request)

    raw: dict[str, Any] = {}
    provider_configuration: Any = NOT_EXPOSED
    provider_returned_model = NOT_EXPOSED
    final_response = ""
    error = benchmark_error
    error_class = ""
    status = PROBE_ERROR
    rejection_before_generation: bool | str = "not_determined"
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | str = NOT_EXPOSED
    codex_version = NOT_EXPOSED
    generation_checks: dict[str, Any] = {}

    if args.provider != "codex-cli":
        error = f"probe requires provider codex-cli; received {args.provider!r}"
        error_class = "unsupported_provider"
    elif args.model != CODEX_6_LUNA_MODEL:
        error = f"probe requires exact model {CODEX_6_LUNA_MODEL!r}; received {args.model!r}"
        error_class = "wrong_requested_model"
    elif benchmark_error:
        error_class = "benchmark_provenance_unavailable"
    elif benchmark_sha256 != FROZEN_BENCHMARK_SHA256:
        error = f"frozen benchmark SHA mismatch: expected {FROZEN_BENCHMARK_SHA256}, got {benchmark_sha256}"
        error_class = "benchmark_provenance_mismatch"
    else:
        provider_started = time.monotonic()
        try:
            provider = CodexCLIProvider(args.codex_binary, args.timeout_seconds, args.model)
            codex_version = provider.codex_version
            provider_configuration = provider.configuration()
            if isinstance(provider_configuration, dict):
                provider_configuration = dict(provider_configuration)
                provider_configuration["raw_execution_artifact"] = "raw_execution.json"
            result = provider.call({
                "request_id": probe_id,
                "model": args.model,
                "system_prompt": "",
                "user_prompt": PROBE_PROMPT,
                "generation_parameters": {},
            })
            latency_ms = round((time.monotonic() - provider_started) * 1000, 3)
            raw = _raw_dict(result.raw)
            provider_returned_model = result.returned_model or NOT_EXPOSED
            final_response = result.text
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            event_summary = _event_summary(raw)
            item_types = event_summary.get("item_types", [])
            if not isinstance(item_types, list):
                item_types = []
            actual_generation = (
                raw.get("returncode") == 0
                and event_summary.get("agent_message_count", 0) >= 1
            )
            requested_model_exact = raw.get("requested_model") == CODEX_6_LUNA_MODEL
            identity_acceptable = provider_returned_model in {NOT_EXPOSED, CODEX_6_LUNA_MODEL}
            fallback_detected = _fallback_detected(raw)
            no_fallback_detected = requested_model_exact and identity_acceptable and not fallback_detected
            generation_checks = {
                "transport_exact": raw.get("transport") == CODEX_CLI_INTERFACE,
                "requested_model_exact": requested_model_exact,
                "provider_returned_model_acceptable": identity_acceptable,
                "actual_generation": actual_generation,
                "final_answer_extracted": raw.get("output_last_message") == final_response,
                "exact_final_answer": final_response == EXPECTED_RESPONSE,
                "no_fallback_detected": no_fallback_detected,
                "no_disallowed_tool_events": not (set(item_types) & DISALLOWED_ITEM_TYPES),
                "no_benchmark_task_used": True,
            }
            if all(generation_checks.values()):
                status = AVAILABLE
                error_class = ""
            else:
                status = PROBE_ERROR
                error_class = "probe_contract_mismatch"
                error = "one or more synthetic probe checks failed"
            rejection_before_generation = not actual_generation
        except ProviderError as exc:
            latency_ms = round((time.monotonic() - provider_started) * 1000, 3)
            error = str(exc)
            raw = _raw_dict(exc.raw)
            if isinstance(raw.get("codex_version"), str):
                codex_version = raw["codex_version"]
            if _is_model_access_rejection(error, raw):
                status = UNAVAILABLE
                error_class = "model_or_chatgpt_access_rejected"
                rejection_before_generation = _before_generation(raw)
            else:
                status = PROBE_ERROR
                error_class = "provider_or_transport_error"
                rejection_before_generation = _before_generation(raw) if raw else "not_determined"
        except (OSError, ValueError) as exc:
            latency_ms = round((time.monotonic() - provider_started) * 1000, 3)
            error = str(exc)
            error_class = "provider_or_transport_error"
            rejection_before_generation = "not_determined"

    if not isinstance(latency_ms, (int, float)):
        latency_ms = NOT_EXPOSED
    raw_artifact: Any = raw
    if error:
        raw_artifact = {"provider_error": error, "provider_raw_execution": raw}
    _write_json(raw_path, _redact_known_secrets(raw_artifact))

    finished_at = utc_now()
    summary = {
        "probe_id": probe_id,
        "status": status,
        "started_at": started_at,
        "finished_at": finished_at,
        "requested_model": args.model,
        "transport": CODEX_CLI_INTERFACE,
        "provider_returned_model": provider_returned_model,
        "codex_version": codex_version,
        "exit_status": raw.get("returncode", NOT_EXPOSED),
        "final_response": final_response,
        "expected_final_response": EXPECTED_RESPONSE,
        "latency_ms": latency_ms,
        "input_tokens": input_tokens if input_tokens is not None else NOT_EXPOSED,
        "output_tokens": output_tokens if output_tokens is not None else NOT_EXPOSED,
        "error_class": error_class,
        "error": error or NOT_EXPOSED,
        "error_message": raw.get("stderr", error or NOT_EXPOSED) if isinstance(raw.get("stderr", error or NOT_EXPOSED), str) else (error or NOT_EXPOSED),
        "rejection_before_generation": rejection_before_generation,
        "fallback_detected": _fallback_detected(raw),
        "generation_checks": generation_checks,
        "provider_configuration": provider_configuration,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_sha256": benchmark_sha256,
        "benchmark_task_used": False,
        "raw_execution_file": raw_path.name,
        "request_file": request_path.name,
    }
    _write_json(probe_path, _redact_known_secrets(summary))
    return _public_result(
        status=status,
        probe_path=probe_path,
        error_class=error_class,
        before_generation=rejection_before_generation,
        retry_command=retry_command,
        provider_returned_model=provider_returned_model,
        final_response=final_response,
    )

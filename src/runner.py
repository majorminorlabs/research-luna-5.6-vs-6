"""Provider-agnostic runner for the frozen Luna comparison benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from .reporting import generate_reports, load_run
    from .scorers import SCORER_VERSION, make_blind_pairing, score_task
    from .validators import ValidationError, load_answer_keys, load_tasks, sha256_file, validate_benchmark
except ImportError:
    from reporting import generate_reports, load_run
    from scorers import SCORER_VERSION, make_blind_pairing, score_task
    from validators import ValidationError, load_answer_keys, load_tasks, sha256_file, validate_benchmark


RUNNER_VERSION = "runner-1.0.0"
NOT_EXPOSED = "not_exposed"
CODEX_LUNA_MODEL = "gpt-5.6-luna"
CODEX_6_LUNA_MODEL = "gpt-6-luna"
CODEX_JUDGE_MODEL = "gpt-6-sol"
CODEX_CAPTURE_MODELS = frozenset({CODEX_LUNA_MODEL, CODEX_6_LUNA_MODEL})
CODEX_CLI_INTERFACE = "codex-cli-chatgpt-oauth"

# These are all supported by Codex CLI 0.153.4.  They are passed as explicit
# config overrides instead of relying on the user's project configuration.
CODEX_CLI_CONFIG_OVERRIDES = (
    'approval_policy="never"',
    'sandbox_mode="read-only"',
    'web_search="disabled"',
    "features.apps=false",
    "features.browser_use=false",
    "features.computer_use=false",
    "features.image_generation=false",
    "features.multi_agent=false",
    "features.plugins=false",
    "features.shell_tool=false",
    "features.skill_mcp_dependency_install=false",
    "features.skill_search=false",
    "features.sleep_tool=false",
    "features.tool_suggest=false",
    "features.view_image=false",
    "features.workspace_dependencies=false",
    'forced_login_method="chatgpt"',
    "hide_agent_reasoning=true",
    'history.persistence="none"',
    "memories.generate_memories=false",
    "memories.use_memories=false",
)
CODEX_CLI_REASONING_VALUES = {"none", "low", "medium", "high", "xhigh", "max", "ultra"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool, raw: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.raw = raw
        self.status_code = status_code


@dataclass
class ProviderResult:
    text: str
    returned_model: str
    finish_reason: str
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    raw: Any


def _usage_values(value: Any) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return None, None
    input_tokens = value.get("input_tokens", value.get("prompt_tokens"))
    output_tokens = value.get("output_tokens", value.get("completion_tokens"))
    return (int(input_tokens) if isinstance(input_tokens, (int, float)) else None,
            int(output_tokens) if isinstance(output_tokens, (int, float)) else None)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return "" if content is None else str(content)


def _parse_adapter_payload(payload: Any) -> ProviderResult:
    if isinstance(payload, str):
        return ProviderResult(payload, NOT_EXPOSED, NOT_EXPOSED, None, None, None, payload)
    if not isinstance(payload, dict):
        raise ProviderError("provider adapter returned neither JSON object nor text", retryable=False, raw=payload)
    if payload.get("error") and not any(key in payload for key in ("text", "response", "output_text")):
        error = payload["error"]
        retryable = bool(payload.get("retryable", True))
        raise ProviderError(f"provider adapter error: {error}", retryable=retryable, raw=payload)
    text = payload.get("text", payload.get("response", payload.get("output_text", "")))
    input_tokens, output_tokens = _usage_values(payload.get("usage"))
    if input_tokens is None and output_tokens is None:
        input_tokens, output_tokens = _usage_values(payload)
    cost_value = payload.get("cost_usd", payload.get("cost"))
    cost_usd = float(cost_value) if isinstance(cost_value, (int, float)) else None
    return ProviderResult(
        text=_content_to_text(text),
        returned_model=str(payload.get("model", payload.get("model_id", NOT_EXPOSED))),
        finish_reason=str(payload.get("finish_reason", NOT_EXPOSED)),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        raw=payload,
    )


class CommandProvider:
    def __init__(self, command: str, timeout_seconds: float):
        self.argv = shlex.split(command)
        if not self.argv:
            raise ValueError("provider command cannot be empty")
        self.timeout_seconds = timeout_seconds

    def call(self, request_payload: dict[str, Any]) -> ProviderResult:
        try:
            completed = subprocess.run(
                self.argv,
                input=json.dumps(request_payload, ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"provider command timed out after {self.timeout_seconds}s", retryable=True, raw={"stdout": exc.stdout, "stderr": exc.stderr}) from exc
        except OSError as exc:
            raise ProviderError(f"could not start provider command: {exc}", retryable=True) from exc
        if completed.returncode != 0:
            raise ProviderError(
                f"provider command exited with {completed.returncode}: {completed.stderr[-1000:]}",
                retryable=True,
                raw={"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr},
            )
        stdout = completed.stdout.strip()
        if not stdout:
            raise ProviderError("provider command returned empty output", retryable=True, raw={"stderr": completed.stderr})
        try:
            payload: Any = json.loads(stdout)
        except json.JSONDecodeError:
            payload = stdout
        return _parse_adapter_payload(payload)


class OpenAICompatibleProvider:
    def __init__(self, url: str, api_key_env: str, timeout_seconds: float):
        self.url = url
        self.api_key_env = api_key_env
        self.timeout_seconds = timeout_seconds

    def call(self, request_payload: dict[str, Any]) -> ProviderResult:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise ProviderError(f"environment variable {self.api_key_env} is not set", retryable=False)
        body = {
            "model": request_payload["model"],
            "messages": [
                {"role": "system", "content": request_payload.get("system_prompt", "")},
                {"role": "user", "content": request_payload["user_prompt"]},
            ],
        }
        body.update(request_payload.get("generation_parameters", {}))
        request = Request(
            self.url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_bytes = response.read()
                payload = json.loads(raw_bytes.decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            raise ProviderError(f"HTTP provider error {exc.code}", retryable=retryable, raw=raw, status_code=exc.code) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"HTTP provider transport error: {exc}", retryable=True) from exc
        if not isinstance(payload, dict):
            raise ProviderError("HTTP provider response was not a JSON object", retryable=False, raw=payload)
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderError("HTTP provider response had no choices", retryable=False, raw=payload)
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message", {}) if isinstance(choice, dict) else {}
        input_tokens, output_tokens = _usage_values(payload.get("usage"))
        cost_value = payload.get("cost_usd", payload.get("cost"))
        cost_usd = float(cost_value) if isinstance(cost_value, (int, float)) else None
        return ProviderResult(
            text=_content_to_text(message.get("content", choice.get("text", ""))),
            returned_model=str(payload.get("model", NOT_EXPOSED)),
            finish_reason=str(choice.get("finish_reason", NOT_EXPOSED)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            raw=payload,
        )


def _decode_process_bytes(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _codex_event_summary(stdout: str) -> dict[str, Any]:
    """Summarize JSONL events without replacing the exact raw stream."""

    event_types: list[str] = []
    item_types: list[str] = []
    usage: dict[str, Any] | None = None
    agent_message_count = 0
    malformed_lines = 0
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed_lines += 1
            continue
        if not isinstance(event, dict):
            malformed_lines += 1
            continue
        event_type = event.get("type")
        if isinstance(event_type, str):
            event_types.append(event_type)
        item = event.get("item")
        if isinstance(item, dict):
            item_type = item.get("type")
            if isinstance(item_type, str):
                item_types.append(item_type)
            if item_type == "agent_message":
                agent_message_count += 1
        if event_type == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return {
        "event_types": event_types,
        "item_types": item_types,
        "agent_message_count": agent_message_count,
        "malformed_jsonl_lines": malformed_lines,
        "usage": usage,
    }


class CodexCLIProvider:
    """Run the exact requested model through an isolated Codex CLI process.

    Codex is an agent harness rather than a bare completion endpoint.  This
    provider therefore keeps the final answer from ``--output-last-message``
    separate from the complete JSONL/stderr execution trace.  Every call gets
    a fresh temporary working directory, a fresh process, and an ephemeral
    Codex session.
    """

    interface = CODEX_CLI_INTERFACE

    def __init__(self, codex_binary: str, timeout_seconds: float, model: str = CODEX_LUNA_MODEL):
        resolved = shutil.which(codex_binary) if not os.path.isabs(codex_binary) else codex_binary
        self.codex_binary = resolved or codex_binary
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.codex_version = self._read_version()

    def _read_version(self) -> str:
        try:
            completed = subprocess.run(
                [self.codex_binary, "--version"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except OSError as exc:
            raise ProviderError(f"could not start Codex CLI: {exc}", retryable=False) from exc
        if completed.returncode != 0:
            raise ProviderError(
                f"Codex CLI --version exited with {completed.returncode}",
                retryable=False,
                raw={"stdout": _decode_process_bytes(completed.stdout), "stderr": _decode_process_bytes(completed.stderr)},
            )
        version = _decode_process_bytes(completed.stdout).strip()
        if not version:
            raise ProviderError("Codex CLI --version returned empty output", retryable=False)
        return version

    def configuration(self) -> dict[str, Any]:
        return {
            "transport": CODEX_CLI_INTERFACE,
            "requested_model": self.model,
            "provider_returned_model": NOT_EXPOSED,
            "chatgpt_picker_equivalence": "unverified",
            "codex_binary": self.codex_binary,
            "codex_version": self.codex_version,
            "sandbox": "read-only",
            "approval_policy": "never",
            "web_search": "disabled",
            "independent_invocation": True,
            "ephemeral_session": True,
            "history_persistence": "none",
            "memory_injection": "disabled",
            "working_directory": "fresh temporary directory per task",
            "config_overrides": list(CODEX_CLI_CONFIG_OVERRIDES),
            "argv_template": self._argv_template(),
            "raw_execution_artifact": "raw_execution.jsonl",
        }

    def _argv_template(self) -> list[str]:
        return [
            self.codex_binary,
            "exec",
            "--model",
            self.model,
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--color",
            "never",
            "--output-last-message",
            "<isolated>/final-answer.txt",
            *sum((["-c", override] for override in CODEX_CLI_CONFIG_OVERRIDES), []),
            "-",
        ]

    def _build_argv(self, output_path: Path, reasoning: str | None) -> list[str]:
        argv = [
            self.codex_binary,
            "exec",
            "--model",
            self.model,
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
            "--color",
            "never",
            "--output-last-message",
            str(output_path),
        ]
        overrides = list(CODEX_CLI_CONFIG_OVERRIDES)
        if reasoning is not None:
            overrides.append(f'model_reasoning_effort="{reasoning}"')
        for override in overrides:
            argv.extend(("-c", override))
        argv.append("-")
        return argv

    @staticmethod
    def _child_environment(cwd: Path) -> dict[str, str]:
        environment = os.environ.copy()
        # Keep CODEX_HOME so the CLI can use the existing authenticated store,
        # but do not inherit app/thread/session wiring from the parent process.
        for key in list(environment):
            if key.startswith("CODEX_") and key not in {"CODEX_HOME"}:
                environment.pop(key, None)
        for key in ("OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID"):
            environment.pop(key, None)
        environment["PWD"] = str(cwd)
        environment.pop("OLDPWD", None)
        return environment

    @staticmethod
    def _usage_values(usage: dict[str, Any] | None) -> tuple[int | None, int | None]:
        if not isinstance(usage, dict):
            return None, None
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        return (
            int(input_tokens) if isinstance(input_tokens, (int, float)) else None,
            int(output_tokens) if isinstance(output_tokens, (int, float)) else None,
        )

    def _raw_execution(
        self,
        *,
        request_payload: dict[str, Any],
        argv: list[str],
        cwd: Path,
        stdout: str,
        stderr: str,
        returncode: int | None,
        final_text: str,
        elapsed_ms: float,
    ) -> dict[str, Any]:
        event_summary = _codex_event_summary(stdout)
        return {
            "transport": CODEX_CLI_INTERFACE,
            "requested_model": request_payload.get("model", NOT_EXPOSED),
            "provider_returned_model": NOT_EXPOSED,
            "codex_version": self.codex_version,
            "argv": argv,
            "cwd": str(cwd),
            "cwd_isolated_from_benchmark": True,
            "prompt_sha256": hashlib.sha256(str(request_payload.get("user_prompt", "")).encode("utf-8")).hexdigest(),
            "prompt_bytes": len(str(request_payload.get("user_prompt", "")).encode("utf-8")),
            "returncode": returncode,
            "elapsed_ms": elapsed_ms,
            "stdout_jsonl": stdout,
            "stderr": stderr,
            "output_last_message": final_text,
            "event_summary": event_summary,
        }

    def call(self, request_payload: dict[str, Any]) -> ProviderResult:
        model = request_payload.get("model")
        target_model = getattr(self, "model", CODEX_LUNA_MODEL)
        allowed_models = getattr(self, "allowed_models", CODEX_CAPTURE_MODELS)
        if target_model not in allowed_models:
            raise ProviderError(
                f"codex-cli provider does not permit unregistered model {target_model!r}",
                retryable=False,
            )
        if model != target_model:
            raise ProviderError(
                f"codex-cli provider requires model {target_model!r}; received {model!r}",
                retryable=False,
            )
        prompt = request_payload.get("user_prompt")
        if not isinstance(prompt, str):
            raise ProviderError("codex-cli provider requires a string user_prompt", retryable=False)
        if request_payload.get("system_prompt"):
            raise ProviderError("codex-cli provider does not accept a benchmark system prompt", retryable=False)

        generation_parameters = request_payload.get("generation_parameters") or {}
        if not isinstance(generation_parameters, dict):
            raise ProviderError("generation_parameters must be an object", retryable=False)
        unsupported = {
            key: value
            for key, value in generation_parameters.items()
            if value not in (None, NOT_EXPOSED) and key != "reasoning"
        }
        if unsupported:
            raise ProviderError(
                "Codex CLI does not expose these requested generation parameters: " + ", ".join(sorted(unsupported)),
                retryable=False,
                raw={"unsupported_generation_parameters": unsupported},
            )
        reasoning = generation_parameters.get("reasoning")
        if reasoning in (None, NOT_EXPOSED):
            reasoning = None
        if reasoning is not None and reasoning not in CODEX_CLI_REASONING_VALUES:
            raise ProviderError(
                f"unsupported Codex reasoning value {reasoning!r}; expected one of {sorted(CODEX_CLI_REASONING_VALUES)}",
                retryable=False,
            )

        with tempfile.TemporaryDirectory(prefix="luna-codex-cli-") as temporary_directory:
            cwd = Path(temporary_directory)
            output_path = cwd / "final-answer.txt"
            argv = self._build_argv(output_path, reasoning)
            environment = self._child_environment(cwd)
            started = time.monotonic()
            try:
                completed = subprocess.run(
                    argv,
                    input=prompt.encode("utf-8"),
                    capture_output=True,
                    cwd=cwd,
                    env=environment,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                elapsed_ms = round((time.monotonic() - started) * 1000, 3)
                raw = self._raw_execution(
                    request_payload=request_payload,
                    argv=argv,
                    cwd=cwd,
                    stdout=_decode_process_bytes(exc.stdout),
                    stderr=_decode_process_bytes(exc.stderr),
                    returncode=None,
                    final_text="",
                    elapsed_ms=elapsed_ms,
                )
                raise ProviderError(
                    f"Codex CLI timed out after {self.timeout_seconds}s",
                    retryable=True,
                    raw=raw,
                ) from exc
            except OSError as exc:
                raise ProviderError(f"could not start Codex CLI: {exc}", retryable=False) from exc

            elapsed_ms = round((time.monotonic() - started) * 1000, 3)
            stdout = _decode_process_bytes(completed.stdout)
            stderr = _decode_process_bytes(completed.stderr)
            final_text = ""
            if output_path.exists():
                final_text = output_path.read_bytes().decode("utf-8")
            raw = self._raw_execution(
                request_payload=request_payload,
                argv=argv,
                cwd=cwd,
                stdout=stdout,
                stderr=stderr,
                returncode=completed.returncode,
                final_text=final_text,
                elapsed_ms=elapsed_ms,
            )
            if completed.returncode != 0:
                raise ProviderError(
                    f"Codex CLI exited with {completed.returncode}",
                    retryable=True,
                    raw=raw,
                )
            if not output_path.exists():
                raise ProviderError("Codex CLI completed without --output-last-message", retryable=True, raw=raw)

            input_tokens, output_tokens = self._usage_values(raw["event_summary"].get("usage"))
            return ProviderResult(
                text=final_text,
                returned_model=NOT_EXPOSED,
                finish_reason=NOT_EXPOSED,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=None,
                raw=raw,
            )


class CodexJudgeProvider(CodexCLIProvider):
    """The same isolated Codex transport, restricted to the blind judge model."""

    allowed_models = frozenset({CODEX_JUDGE_MODEL})


def _git_info(root: Path) -> dict[str, Any]:
    def run_git(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip()

    commit = run_git("rev-parse", "HEAD") or NOT_EXPOSED
    dirty = run_git("status", "--porcelain")
    return {"git_commit": commit, "git_dirty": bool(dirty) if dirty is not None else NOT_EXPOSED}


def _append_jsonl(path: Path, value: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _new_run_dir(runs_root: Path) -> tuple[str, Path]:
    runs_root.mkdir(parents=True, exist_ok=True)
    for _ in range(20):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:10]
        run_dir = runs_root / run_id
        try:
            run_dir.mkdir()
            return run_id, run_dir
        except FileExistsError:
            continue
    raise RuntimeError("could not allocate a unique run directory")


MANUAL_GENERATION_PARAMETERS = {
    "temperature": NOT_EXPOSED,
    "top_p": NOT_EXPOSED,
    "seed": NOT_EXPOSED,
    "max_output_tokens": NOT_EXPOSED,
    "reasoning": NOT_EXPOSED,
}


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _manual_run_artifacts(run_dir: Path) -> dict[str, Path]:
    return {
        "requests": run_dir / "requests.jsonl",
        "responses": run_dir / "responses.jsonl",
        "scores": run_dir / "scores.jsonl",
        "errors": run_dir / "errors.jsonl",
        "metadata": run_dir / "metadata.json",
        "summary": run_dir / "summary.json",
        "duplicates": run_dir / "duplicate_responses.jsonl",
    }


def _initialize_manual_run(root: Path, model: str, validation: dict[str, Any], task_ids: list[str]) -> tuple[str, Path, dict[str, Any]]:
    run_id, run_dir = _new_run_dir(root / "runs")
    artifacts = _manual_run_artifacts(run_dir)
    for name in ("requests", "responses", "scores", "errors"):
        artifacts[name].touch(exist_ok=False)
    started_at = utc_now()
    metadata = {
        "run_id": run_id,
        "benchmark_version": validation["benchmark_version"],
        "benchmark_sha256": validation["tasks_sha256"],
        "answer_keys_sha256": validation["answer_keys_sha256"],
        "git": _git_info(root),
        "model_requested": model,
        "exact_model_identifier_returned": NOT_EXPOSED,
        "provider": "chatgpt-manual",
        "interface": "chatgpt-manual",
        "started_at": started_at,
        "finished_at": NOT_EXPOSED,
        "system_prompt": NOT_EXPOSED,
        "generation_parameters": dict(MANUAL_GENERATION_PARAMETERS),
        "provider_configuration": {
            "capture_mode": "manual copy/paste through the user's ChatGPT interface",
            "model_picker_identity": NOT_EXPOSED,
        },
        "task_ids": task_ids,
        "max_retries": 0,
        "scorer_version": SCORER_VERSION,
        "runner_version": RUNNER_VERSION,
        "manual_capture": {
            "resume_supported": True,
            "duplicate_policy": "refuse unless --override-duplicate is explicit",
            "response_text_storage": "verbatim decoded terminal input",
        },
    }
    _write_new_json(artifacts["metadata"], metadata)
    return run_id, run_dir, metadata


def _manual_resume_run(root: Path, run_dir: Path, model: str) -> tuple[str, Path, dict[str, Any]]:
    artifacts = _manual_run_artifacts(run_dir)
    if not artifacts["metadata"].exists():
        raise ValidationError(f"manual run has no metadata.json: {run_dir}")
    if artifacts["summary"].exists():
        raise ValidationError(f"run is already complete; refusing to capture into it: {run_dir}")
    metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))
    if metadata.get("provider") != "chatgpt-manual":
        raise ValidationError("--resume target is not a chatgpt-manual run")
    if metadata.get("model_requested") != model:
        raise ValidationError("--resume model does not match the original manual run")
    if metadata.get("benchmark_sha256") != sha256_file(root / "benchmark" / "tasks.jsonl"):
        raise ValidationError("manual run benchmark hash does not match the frozen benchmark")
    return str(metadata["run_id"]), run_dir, metadata


def _read_manual_response(sentinel: str, stream: Any = None) -> str:
    """Read terminal lines without normalizing the pasted response."""

    input_stream = stream if stream is not None else sys.stdin
    lines: list[str] = []
    while True:
        line = input_stream.readline()
        if line == "":
            raise EOFError("input ended before the capture terminator was entered")
        if line.rstrip("\r\n") == sentinel:
            return "".join(lines)
        lines.append(line)


def export_prompts(root: Path, output: Path) -> dict[str, Any]:
    validation = validate_benchmark(root)
    tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
    sections = [
        "LUNA-COMPARISON-V1.0 PROMPT EXPORT",
        f"TASKS_SHA256: {validation['tasks_sha256']}",
        "Copy only the text between BEGIN_PROMPT and END_PROMPT for each task.",
        "",
    ]
    for task in tasks:
        sections.extend([
            f"===== TASK {task['id']} ({task['category']}) =====",
            "BEGIN_PROMPT",
            task["prompt"],
            "END_PROMPT",
            "",
        ])
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(sections))
        handle.write("\n")
    return {"status": "exported", "output": str(output), "task_count": len(tasks), "tasks_sha256": validation["tasks_sha256"]}


def _manual_summary(run_id: str, validation: dict[str, Any], responses: list[dict[str, Any]], started_at: str, task_ids: list[str]) -> dict[str, Any]:
    status_counts = {status: sum(response.get("status") == status for response in responses) for status in ("SUCCESS", "ERROR", "TRUNCATED")}
    latencies = [response["latency_ms"] for response in responses if isinstance(response.get("latency_ms"), (int, float))]
    return {
        "run_id": run_id,
        "benchmark_version": validation["benchmark_version"],
        "benchmark_sha256": validation["tasks_sha256"],
        "selected_task_count": len(task_ids),
        "benchmark_task_count": len(task_ids),
        "complete": len(responses) == len(task_ids) and {response.get("task_id") for response in responses} == set(task_ids),
        "terminal_result_count": len(responses),
        "status_counts": status_counts,
        "error_rate": status_counts["ERROR"] / len(responses) if responses else 1.0,
        "truncation_rate": status_counts["TRUNCATED"] / len(responses) if responses else 1.0,
        "latency": {
            "count": len(latencies),
            "mean_ms": sum(latencies) / len(latencies) if latencies else None,
            "min_ms": min(latencies) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
        },
        "tokens": {"input_total": NOT_EXPOSED, "output_total": NOT_EXPOSED, "total": NOT_EXPOSED},
        "cost_usd_total": NOT_EXPOSED,
        "retries_total": 0,
        "exact_model_identifiers_returned": [NOT_EXPOSED],
        "started_at": started_at,
        "finished_at": utc_now(),
        "capture_mode": "manual",
        "scoring_status": "DETERMINISTIC_COMPONENTS_CAPTURED; RUBRIC_AND_PAIRWISE_PENDING",
    }


def manual_capture_run(args: argparse.Namespace, *, resume_dir: Path | None = None) -> dict[str, Any]:
    root = Path(args.root).resolve()
    validation = validate_benchmark(root)
    tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
    answer_keys = load_answer_keys(root / "benchmark" / "answer_keys.json")["tasks"]
    task_ids = [task["id"] for task in tasks]
    if resume_dir is None:
        run_id, run_dir, metadata = _initialize_manual_run(root, args.model, validation, task_ids)
    else:
        run_id, run_dir, metadata = _manual_resume_run(root, resume_dir.resolve(), args.model)
    artifacts = _manual_run_artifacts(run_dir)
    responses = _read_jsonl_records(artifacts["responses"])
    response_ids = [response.get("task_id") for response in responses]
    if len(response_ids) != len(set(response_ids)):
        raise ValidationError("manual run already contains duplicate terminal task IDs")
    existing = set(response_ids)
    if args.task_id:
        if len(args.task_id) != len(set(args.task_id)):
            raise ValidationError("duplicate --task-id values")
        unknown = sorted(set(args.task_id) - set(task_ids))
        if unknown:
            raise ValidationError(f"unknown task IDs: {unknown}")
        capture_ids = args.task_id
    else:
        capture_ids = [task_id for task_id in task_ids if task_id not in existing]
    duplicate_ids = [task_id for task_id in capture_ids if task_id in existing]
    if duplicate_ids and not args.override_duplicate:
        raise ValidationError(f"refusing duplicate task capture {duplicate_ids}; pass --override-duplicate explicitly")
    if duplicate_ids and not args.task_id:
        raise ValidationError("--override-duplicate requires explicit --task-id values")
    task_by_id = {task["id"]: task for task in tasks}
    print(f"Manual run {run_id}: {len(existing)}/{len(task_ids)} captured.")
    for task_id in capture_ids:
        task = task_by_id[task_id]
        sentinel = f"__LUNA_CAPTURE_END_{run_id}_{task_id}__"
        request_id = f"{run_id}:{task_id}:manual"
        _append_jsonl(artifacts["requests"], {
            "request_id": request_id,
            "task_id": task_id,
            "attempt": 1,
            "created_at": utc_now(),
            "model_requested": args.model,
            "system_prompt": NOT_EXPOSED,
            "rendered_user_prompt": task["prompt"],
            "generation_parameters": dict(MANUAL_GENERATION_PARAMETERS),
            "provider": "chatgpt-manual",
            "manual_instruction": "Paste the exact prompt into a new Luna 5.6 ChatGPT conversation, then paste the complete response below.",
        })
        print(f"\n[{task_id}] Open a new ChatGPT conversation and select Luna 5.6.")
        print("--- BEGIN EXACT PROMPT ---")
        print(task["prompt"], end="")
        print("\n--- END EXACT PROMPT ---")
        print(f"Paste the complete raw response below. End with a line containing only: {sentinel}")
        capture_started = time.monotonic()
        try:
            raw_response = _read_manual_response(sentinel)
        except (EOFError, KeyboardInterrupt):
            print(f"\nCapture interrupted. Resume with: PYTHONPATH=src python3 -m runner manual-capture --model {args.model!r} --resume {run_dir}")
            return {"status": "interrupted", "run_id": run_id, "run_dir": str(run_dir), "captured": len(existing), "total": len(task_ids)}
        response_record = {
            "request_id": request_id,
            "task_id": task_id,
            "attempt": 1,
            "status": "SUCCESS",
            "response_text": raw_response,
            "returned_model": NOT_EXPOSED,
            "finish_reason": NOT_EXPOSED,
            "latency_ms": round((time.monotonic() - capture_started) * 1000, 3),
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
            "retries": 0,
            "truncated": False,
            "created_at": utc_now(),
            "capture_timestamp": utc_now(),
        }
        if task_id in existing:
            _append_jsonl(artifacts["duplicates"], {
                "duplicate_of_task_id": task_id,
                "captured_at": response_record["capture_timestamp"],
                "manual_override": True,
                "response": response_record,
            })
            print(f"Recorded explicit duplicate for {task_id}; primary terminal result remains unchanged.")
            continue
        _append_jsonl(artifacts["responses"], response_record)
        _append_jsonl(artifacts["scores"], score_task(task_id, raw_response, answer_keys[task_id], "SUCCESS"))
        existing.add(task_id)
        print(f"Captured {len(existing)}/{len(task_ids)}: {task_id}")

    responses = _read_jsonl_records(artifacts["responses"])
    if len(responses) != len(task_ids) or {response.get("task_id") for response in responses} != set(task_ids):
        print(f"Run incomplete: {len(responses)}/{len(task_ids)} terminal results. Resume with: PYTHONPATH=src python3 -m runner manual-capture --model {args.model!r} --resume {run_dir}")
        return {"status": "incomplete", "run_id": run_id, "run_dir": str(run_dir), "captured": len(responses), "total": len(task_ids)}
    summary = _manual_summary(run_id, validation, responses, metadata["started_at"], task_ids)
    _write_new_json(artifacts["summary"], summary)
    print(f"Manual capture complete: {len(task_ids)}/{len(task_ids)} captured.")
    return {"status": "complete", "run_id": run_id, "run_dir": str(run_dir), "captured": len(task_ids), "total": len(task_ids), "summary": summary}


def manual_capture(args: argparse.Namespace) -> dict[str, Any]:
    if args.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    if args.resume and args.repeat != 1:
        raise ValueError("--resume can be used only with --repeat 1")
    results: list[dict[str, Any]] = []
    for repeat_index in range(args.repeat):
        result = manual_capture_run(args, resume_dir=args.resume if repeat_index == 0 else None)
        results.append(result)
        if result["status"] != "complete":
            break
    if len(results) == 1:
        return results[0]
    return {
        "status": "complete" if all(result["status"] == "complete" for result in results) else "incomplete",
        "repeat_count": args.repeat,
        "runs": results,
    }


def _explicit_generation_parameters(args: argparse.Namespace) -> dict[str, Any]:
    values = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "seed": args.seed,
        "max_output_tokens": args.max_output_tokens,
        "reasoning": args.reasoning,
    }
    return {key: (value if value is not None else NOT_EXPOSED) for key, value in values.items()}


def _provider_parameters(args: argparse.Namespace) -> dict[str, Any]:
    values = _explicit_generation_parameters(args)
    return {key: value for key, value in values.items() if value != NOT_EXPOSED}


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    validation = validate_benchmark(root)
    tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
    answer_keys = load_answer_keys(root / "benchmark" / "answer_keys.json")["tasks"]
    selected_ids = args.task_id or [task["id"] for task in tasks]
    task_by_id = {task["id"]: task for task in tasks}
    unknown = sorted(set(selected_ids) - set(task_by_id))
    if unknown:
        raise ValidationError(f"unknown task IDs: {unknown}")
    if len(set(selected_ids)) != len(selected_ids):
        raise ValidationError("duplicate --task-id values")

    if args.provider == "command":
        if not args.provider_command:
            raise ValueError("--provider-command is required for --provider command")
        provider: Any = CommandProvider(args.provider_command, args.timeout_seconds)
    elif args.provider == "codex-cli":
        provider = CodexCLIProvider(args.codex_binary, args.timeout_seconds, args.model)
    elif args.provider == "openai-compatible":
        if not args.api_url:
            raise ValueError("--api-url is required for --provider openai-compatible")
        provider = OpenAICompatibleProvider(args.api_url, args.api_key_env, args.timeout_seconds)
    else:
        raise ValueError(f"unsupported provider: {args.provider}")

    run_id, run_dir = _new_run_dir(root / "runs")
    started_at = utc_now()
    system_prompt = args.system_prompt
    if args.system_prompt_file:
        system_prompt = Path(args.system_prompt_file).read_text(encoding="utf-8")
    max_retries = args.max_retries
    if max_retries is None:
        max_retries = 0 if args.provider == "codex-cli" else 2
    if max_retries < 0:
        raise ValueError("--max-retries must be at least 0")
    generation_parameters = _explicit_generation_parameters(args)
    provider_parameters = _provider_parameters(args)
    requests_path = run_dir / "requests.jsonl"
    responses_path = run_dir / "responses.jsonl"
    scores_path = run_dir / "scores.jsonl"
    errors_path = run_dir / "errors.jsonl"
    raw_execution_path = run_dir / "raw_execution.jsonl"
    # Create all JSONL artifacts up front, including an explicitly empty error
    # log for a clean run.  This makes the required artifact set stable.
    for artifact_path in (requests_path, responses_path, scores_path, errors_path, raw_execution_path):
        artifact_path.touch(exist_ok=False)

    responses: list[dict[str, Any]] = []
    score_records: list[dict[str, Any]] = []
    returned_models: list[str] = []
    retry_total = 0
    for task_id in selected_ids:
        task = task_by_id[task_id]
        final_response: dict[str, Any] | None = None
        for attempt in range(1, max_retries + 2):
            request_id = f"{run_id}:{task_id}:attempt-{attempt}"
            request_payload = {
                "request_id": request_id,
                "model": args.model,
                "system_prompt": system_prompt,
                "user_prompt": task["prompt"],
                "generation_parameters": provider_parameters,
                "task_id": task_id,
                "benchmark_version": validation["benchmark_version"],
            }
            _append_jsonl(requests_path, {
                "request_id": request_id,
                "task_id": task_id,
                "attempt": attempt,
                "created_at": utc_now(),
                "model_requested": args.model,
                "system_prompt": system_prompt,
                "rendered_user_prompt": task["prompt"],
                "generation_parameters": generation_parameters,
                "provider": args.provider,
            })
            request_started = time.monotonic()
            try:
                result = provider.call(request_payload)
                _append_jsonl(raw_execution_path, {
                    "request_id": request_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "created_at": utc_now(),
                    "provider": args.provider,
                    "raw_provider_execution": result.raw,
                })
                latency_ms = round((time.monotonic() - request_started) * 1000, 3)
                status = "TRUNCATED" if result.finish_reason.lower() in {"length", "max_tokens", "truncated"} else "SUCCESS"
                final_response = {
                    "request_id": request_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "status": status,
                    "response_text": result.text,
                    "raw_provider_response": result.raw,
                    "returned_model": result.returned_model,
                    "finish_reason": result.finish_reason,
                    "latency_ms": latency_ms,
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                    "cost_usd": result.cost_usd,
                    "retries": attempt - 1,
                    "truncated": status == "TRUNCATED",
                    "created_at": utc_now(),
                }
                returned_models.append(result.returned_model)
                break
            except ProviderError as exc:
                _append_jsonl(raw_execution_path, {
                    "request_id": request_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "created_at": utc_now(),
                    "provider": args.provider,
                    "raw_provider_execution": exc.raw,
                })
                retry_total += 1 if exc.retryable and attempt <= max_retries else 0
                _append_jsonl(errors_path, {
                    "request_id": request_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "created_at": utc_now(),
                    "error_type": "provider",
                    "message": str(exc),
                    "retryable": exc.retryable,
                    "status_code": exc.status_code,
                    "raw_error": exc.raw,
                })
                if exc.retryable and attempt <= max_retries:
                    continue
                final_response = {
                    "request_id": request_id,
                    "task_id": task_id,
                    "attempt": attempt,
                    "status": "ERROR",
                    "response_text": "",
                    "returned_model": NOT_EXPOSED,
                    "finish_reason": NOT_EXPOSED,
                    "latency_ms": round((time.monotonic() - request_started) * 1000, 3),
                    "input_tokens": None,
                    "output_tokens": None,
                    "cost_usd": None,
                    "retries": attempt - 1,
                    "truncated": False,
                    "error": str(exc),
                    "created_at": utc_now(),
                }
                break
        if final_response is None:
            raise RuntimeError(f"no terminal response produced for {task_id}")
        _append_jsonl(responses_path, final_response)
        responses.append(final_response)
        score = score_task(task_id, final_response.get("response_text", ""), answer_keys[task_id], final_response["status"])
        _append_jsonl(scores_path, score)
        score_records.append(score)

    status_counts = {status: sum(response["status"] == status for response in responses) for status in ("SUCCESS", "ERROR", "TRUNCATED")}
    latencies = [response["latency_ms"] for response in responses if isinstance(response.get("latency_ms"), (int, float))]
    input_tokens = [response["input_tokens"] for response in responses if isinstance(response.get("input_tokens"), int)]
    output_tokens = [response["output_tokens"] for response in responses if isinstance(response.get("output_tokens"), int)]
    costs = [response["cost_usd"] for response in responses if isinstance(response.get("cost_usd"), (int, float))]
    exact_returned = sorted(set(returned_models))
    exact_model_identifier_returned: Any = exact_returned[0] if len(exact_returned) == 1 else (exact_returned if exact_returned else NOT_EXPOSED)
    summary = {
        "run_id": run_id,
        "benchmark_version": validation["benchmark_version"],
        "benchmark_sha256": validation["tasks_sha256"],
        "selected_task_count": len(selected_ids),
        "benchmark_task_count": len(tasks),
        "complete": selected_ids == [task["id"] for task in tasks] and all(response["status"] in {"SUCCESS", "TRUNCATED", "ERROR"} for response in responses),
        "terminal_result_count": len(responses),
        "status_counts": status_counts,
        "error_rate": status_counts["ERROR"] / len(responses) if responses else 1.0,
        "truncation_rate": status_counts["TRUNCATED"] / len(responses) if responses else 1.0,
        "latency": {
            "count": len(latencies),
            "mean_ms": sum(latencies) / len(latencies) if latencies else None,
            "min_ms": min(latencies) if latencies else None,
            "max_ms": max(latencies) if latencies else None,
        },
        "tokens": {
            "input_total": sum(input_tokens) if input_tokens else None,
            "output_total": sum(output_tokens) if output_tokens else None,
            "total": sum(input_tokens) + sum(output_tokens) if input_tokens and output_tokens else None,
        },
        "cost_usd_total": sum(costs) if costs else None,
        "retries_total": retry_total,
        "exact_model_identifiers_returned": exact_returned or [NOT_EXPOSED],
        "scoring_status": "DETERMINISTIC_COMPONENTS_CAPTURED; RUBRIC_AND_PAIRWISE_PENDING",
    }
    metadata = {
        "run_id": run_id,
        "benchmark_version": validation["benchmark_version"],
        "benchmark_sha256": validation["tasks_sha256"],
        "answer_keys_sha256": validation["answer_keys_sha256"],
        "git": _git_info(root),
        "model_requested": args.model,
        "requested_model": args.model,
        "exact_model_identifier_returned": exact_model_identifier_returned,
        "provider_returned_model": exact_model_identifier_returned,
        "provider": args.provider,
        "interface": getattr(provider, "interface", args.provider),
        "transport": getattr(provider, "interface", args.provider),
        "chatgpt_picker_equivalence": "unverified" if args.provider == "codex-cli" else NOT_EXPOSED,
        "codex_version": provider.codex_version if args.provider == "codex-cli" else NOT_EXPOSED,
        "started_at": started_at,
        "finished_at": utc_now(),
        "system_prompt": system_prompt,
        "generation_parameters": generation_parameters,
        "provider_configuration": {
            "api_url": args.api_url if args.provider == "openai-compatible" else NOT_EXPOSED,
            "api_key_env": args.api_key_env if args.provider == "openai-compatible" else NOT_EXPOSED,
            "command": args.provider_command if args.provider == "command" else NOT_EXPOSED,
            "codex_cli": provider.configuration() if args.provider == "codex-cli" else NOT_EXPOSED,
        },
        "task_ids": selected_ids,
            "max_retries": max_retries,
            "scorer_version": SCORER_VERSION,
            "runner_version": RUNNER_VERSION,
        }
    _write_new_json(run_dir / "metadata.json", metadata)
    _write_new_json(run_dir / "summary.json", summary)
    return {"run_id": run_id, "run_dir": str(run_dir), "metadata": metadata, "summary": summary, "scores": score_records}


def verify_run(root: Path, run_dir: Path) -> dict[str, Any]:
    validate_benchmark(root)
    required = ("metadata.json", "requests.jsonl", "responses.jsonl", "scores.jsonl", "errors.jsonl", "summary.json")
    missing = [name for name in required if not (run_dir / name).exists()]
    if missing:
        raise ValidationError(f"run is missing required artifacts: {missing}")
    with (run_dir / "metadata.json").open(encoding="utf-8") as handle:
        metadata = json.load(handle)
    with (run_dir / "summary.json").open(encoding="utf-8") as handle:
        summary = json.load(handle)
    with (run_dir / "responses.jsonl").open(encoding="utf-8") as handle:
        responses = [json.loads(line) for line in handle if line.strip()]
    task_ids = metadata.get("task_ids", [])
    response_ids = [response.get("task_id") for response in responses]
    if len(responses) != len(task_ids) or set(response_ids) != set(task_ids):
        raise ValidationError("run does not contain exactly one terminal result per selected task")
    if any(response.get("status") not in {"SUCCESS", "ERROR", "TRUNCATED"} for response in responses):
        raise ValidationError("run contains an invalid terminal status")
    if summary.get("terminal_result_count") != len(task_ids):
        raise ValidationError("summary terminal result count does not match responses")
    if summary.get("benchmark_sha256") != sha256_file(root / "benchmark" / "tasks.jsonl"):
        raise ValidationError("run benchmark hash does not match frozen tasks")
    if metadata.get("provider") == "codex-cli" and not (run_dir / "raw_execution.jsonl").exists():
        raise ValidationError("codex-cli run is missing raw_execution.jsonl")
    return {"status": "passed", "run_id": metadata.get("run_id"), "task_count": len(task_ids), "statuses": {status: sum(response["status"] == status for response in responses) for status in ("SUCCESS", "ERROR", "TRUNCATED")}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Luna 5.6 vs Luna 6 frozen benchmark harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate-benchmark")
    validate_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    validate_parser.add_argument("--allow-missing-manifest", action="store_true")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    run_parser.add_argument("--model", required=True, help="exact model identifier to request; never inferred")
    run_parser.add_argument("--provider", choices=("command", "codex-cli", "openai-compatible"), required=True)
    run_parser.add_argument("--provider-command")
    run_parser.add_argument("--codex-binary", default="codex", help="Codex CLI executable for --provider codex-cli")
    run_parser.add_argument("--api-url")
    run_parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    run_parser.add_argument("--system-prompt", default="")
    run_parser.add_argument("--system-prompt-file")
    run_parser.add_argument("--temperature", type=float)
    run_parser.add_argument("--top-p", type=float)
    run_parser.add_argument("--seed", type=int)
    run_parser.add_argument("--max-output-tokens", type=int)
    run_parser.add_argument("--reasoning")
    run_parser.add_argument("--max-retries", type=int, default=None, help="explicit infrastructure retry count; defaults to 0 for codex-cli and 2 for other providers")
    run_parser.add_argument("--timeout-seconds", type=float, default=120.0)
    run_parser.add_argument("--task-id", action="append", help="restrict to one or more task IDs; omit for all 30")

    probe_parser = subparsers.add_parser("probe", help="run one synthetic Luna 6 availability probe")
    probe_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    probe_parser.add_argument("--model", required=True, help="must be exactly gpt-6-luna")
    probe_parser.add_argument("--provider", choices=("codex-cli",), required=True)
    probe_parser.add_argument("--codex-binary", default="codex", help="Codex CLI executable")
    probe_parser.add_argument("--timeout-seconds", type=float, default=120.0)
    probe_parser.add_argument("--output-root", type=Path, help="probe artifact root; defaults to probes/luna6")

    verify_parser = subparsers.add_parser("verify-run")
    verify_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    verify_parser.add_argument("--run-dir", type=Path, required=True)

    report_parser = subparsers.add_parser("report")
    report_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    report_parser.add_argument("--run-dir", type=Path, action="append", required=True, help="one or more completed run directories")

    pairwise_parser = subparsers.add_parser("pairwise-prompt")
    pairwise_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    pairwise_parser.add_argument("--task-id", required=True)
    pairwise_parser.add_argument("--run-dir", type=Path, action="append", required=True, help="exactly two run directories")
    pairwise_parser.add_argument("--seed", type=int, required=True)

    manual_parser = subparsers.add_parser("manual-capture")
    manual_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    manual_parser.add_argument("--model", required=True, help="display label to record, e.g. Luna 5.6")
    manual_parser.add_argument("--repeat", type=int, default=1)
    manual_parser.add_argument("--resume", type=Path, help="resume an interrupted chatgpt-manual run directory")
    manual_parser.add_argument("--task-id", action="append", help="optional explicit task selection; required with duplicate override")
    manual_parser.add_argument("--override-duplicate", action="store_true", help="allow explicitly selected duplicate capture into duplicate_responses.jsonl")

    export_parser = subparsers.add_parser("export-prompts")
    export_parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    export_parser.add_argument("--output", type=Path, required=True, help="new output file; existing files are never overwritten")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-benchmark":
            result = validate_benchmark(args.root.resolve(), require_manifest=not args.allow_missing_manifest)
        elif args.command == "run":
            result = run_benchmark(args)
        elif args.command == "probe":
            try:
                from .luna6_probe import run_probe
            except ImportError:
                from luna6_probe import run_probe
            result = run_probe(args)
        elif args.command == "verify-run":
            result = verify_run(args.root.resolve(), args.run_dir.resolve())
        elif args.command == "report":
            result = generate_reports(args.root.resolve(), [path.resolve() for path in args.run_dir])
        elif args.command == "pairwise-prompt":
            if len(args.run_dir) != 2:
                raise ValueError("pairwise-prompt requires exactly two --run-dir values")
            validate_benchmark(args.root.resolve())
            tasks = {task["id"]: task for task in load_tasks(args.root.resolve() / "benchmark" / "tasks.jsonl")}
            keys = load_answer_keys(args.root.resolve() / "benchmark" / "answer_keys.json")["tasks"]
            if args.task_id not in tasks:
                raise ValueError(f"unknown task ID: {args.task_id}")
            runs = [load_run(path.resolve()) for path in args.run_dir]
            responses: dict[str, str] = {}
            for run in runs:
                metadata = run["metadata"]
                identity = metadata.get("exact_model_identifier_returned") or metadata.get("model_requested") or NOT_EXPOSED
                run_id = metadata.get("run_id") or Path(run["run_dir"]).name
                response = next((item for item in run["responses"] if item.get("task_id") == args.task_id), None)
                if response is None:
                    raise ValueError(f"run {run_id} has no response for {args.task_id}")
                responses[f"{identity}@{run_id}"] = response.get("response_text", "")
            result = make_blind_pairing(tasks[args.task_id], keys[args.task_id].get("rubric", []), responses, args.seed)
        elif args.command == "manual-capture":
            result = manual_capture(args)
        elif args.command == "export-prompts":
            result = export_prompts(args.root.resolve(), args.output.resolve())
        else:
            raise ValueError(f"unknown command: {args.command}")
    except (OSError, ProviderError, ValueError, ValidationError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "probe":
        return 0 if result.get("status") == "LUNA_6_AVAILABLE" else (2 if result.get("status") == "LUNA_6_UNAVAILABLE" else 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

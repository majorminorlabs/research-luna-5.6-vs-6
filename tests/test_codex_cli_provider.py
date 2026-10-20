import argparse
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.runner import (
    CODEX_CLI_INTERFACE,
    CODEX_6_LUNA_MODEL,
    CODEX_JUDGE_MODEL,
    CODEX_LUNA_MODEL,
    CodexJudgeProvider,
    CodexCLIProvider,
    ProviderResult,
    ProviderError,
    _codex_event_summary,
    run_benchmark,
    verify_run,
)


class CodexCLIProviderTests(unittest.TestCase):
    def test_event_summary_keeps_tool_and_usage_metadata_separate_from_raw_stream(self):
        stdout = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "synthetic"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 11, "output_tokens": 7}}),
        ])
        summary = _codex_event_summary(stdout)
        self.assertEqual(summary["event_types"], ["thread.started", "item.completed", "turn.completed"])
        self.assertEqual(summary["item_types"], ["agent_message"])
        self.assertEqual(summary["usage"]["input_tokens"], 11)
        self.assertEqual(summary["malformed_jsonl_lines"], 0)

    def test_rejects_non_target_model_before_starting_a_model_process(self):
        provider = object.__new__(CodexCLIProvider)
        provider.codex_binary = "codex"
        provider.timeout_seconds = 10
        provider.codex_version = "codex-cli 0.153.4"
        with patch("src.runner.subprocess.run") as run:
            with self.assertRaises(ProviderError):
                provider.call({"model": "gpt-6-sol", "user_prompt": "synthetic", "system_prompt": "", "generation_parameters": {}})
        run.assert_not_called()

    def test_luna6_target_is_forwarded_without_substitution(self):
        provider = object.__new__(CodexCLIProvider)
        provider.codex_binary = "codex"
        provider.timeout_seconds = 10
        provider.codex_version = "codex-cli 0.153.4"
        provider.model = CODEX_6_LUNA_MODEL
        argv = provider._argv_template()
        self.assertIn(CODEX_6_LUNA_MODEL, argv)
        self.assertNotIn(CODEX_LUNA_MODEL, argv)

    def test_judge_target_is_forwarded_only_by_judge_provider(self):
        provider = object.__new__(CodexJudgeProvider)
        provider.codex_binary = "codex"
        provider.model = CODEX_JUDGE_MODEL
        argv = provider._argv_template()
        self.assertIn(CODEX_JUDGE_MODEL, argv)
        self.assertNotIn(CODEX_6_LUNA_MODEL, argv)

    def test_capture_provider_rejects_judge_target_before_starting_process(self):
        provider = object.__new__(CodexCLIProvider)
        provider.codex_binary = "codex"
        provider.timeout_seconds = 10
        provider.codex_version = "codex-cli 0.156.0"
        provider.model = CODEX_JUDGE_MODEL
        with patch("src.runner.subprocess.run") as run:
            with self.assertRaises(ProviderError):
                provider.call({"model": CODEX_JUDGE_MODEL, "user_prompt": "synthetic", "system_prompt": "", "generation_parameters": {}})
        run.assert_not_called()

    def test_final_answer_comes_from_output_file_and_trace_is_preserved(self):
        final_bytes = b"exact\nanswer\n"
        trace = "\n".join([
            json.dumps({"type": "thread.started", "thread_id": "synthetic"}),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "wrapper"}}),
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 13, "output_tokens": 4}}),
        ]) + "\n"

        def fake_run(argv, **kwargs):
            if argv[-1:] == ["--version"]:
                return subprocess.CompletedProcess(argv, 0, b"codex-cli 0.153.4\n", b"")
            output_path = Path(argv[argv.index("--output-last-message") + 1])
            output_path.write_bytes(final_bytes)
            self.assertEqual(kwargs["input"], "synthetic prompt\n".encode("utf-8"))
            self.assertNotEqual(str(kwargs["cwd"]), str(Path.cwd()))
            self.assertEqual(kwargs["cwd"], Path(kwargs["env"]["PWD"]))
            self.assertIn("--ephemeral", argv)
            self.assertIn("--ignore-user-config", argv)
            self.assertIn("--ignore-rules", argv)
            self.assertIn("--json", argv)
            self.assertIn("-", argv)
            return subprocess.CompletedProcess(argv, 0, trace.encode("utf-8"), b"progress\n")

        with patch("src.runner.subprocess.run", side_effect=fake_run):
            provider = CodexCLIProvider("codex", 10)
            result = provider.call({
                "model": CODEX_LUNA_MODEL,
                "user_prompt": "synthetic prompt\n",
                "system_prompt": "",
                "generation_parameters": {},
            })

        self.assertEqual(result.text, final_bytes.decode("utf-8"))
        self.assertEqual(result.returned_model, "not_exposed")
        self.assertEqual(result.input_tokens, 13)
        self.assertEqual(result.output_tokens, 4)
        self.assertEqual(result.raw["output_last_message"], result.text)
        self.assertEqual(result.raw["stdout_jsonl"], trace)
        self.assertEqual(result.raw["stderr"], "progress\n")
        self.assertEqual(result.raw["transport"], CODEX_CLI_INTERFACE)

    def test_rejects_generation_controls_that_codex_does_not_expose(self):
        provider = object.__new__(CodexCLIProvider)
        provider.codex_binary = "codex"
        provider.timeout_seconds = 10
        provider.codex_version = "codex-cli 0.153.4"
        with patch("src.runner.subprocess.run") as run:
            with self.assertRaises(ProviderError):
                provider.call({
                    "model": CODEX_LUNA_MODEL,
                    "user_prompt": "synthetic",
                    "system_prompt": "",
                    "generation_parameters": {"temperature": 0.2},
                })
        run.assert_not_called()

    def test_runner_writes_separate_raw_execution_artifact_for_codex_runs(self):
        source_root = Path(__file__).resolve().parents[1]

        class FakeProvider:
            interface = CODEX_CLI_INTERFACE
            codex_version = "codex-cli 0.153.4"

            def __init__(self, _binary, _timeout, _model):
                pass

            def configuration(self):
                return {
                    "transport": CODEX_CLI_INTERFACE,
                    "requested_model": CODEX_LUNA_MODEL,
                    "provider_returned_model": "not_exposed",
                }

            def call(self, _payload):
                return ProviderResult(
                    text="synthetic transport response",
                    returned_model="not_exposed",
                    finish_reason="not_exposed",
                    input_tokens=1,
                    output_tokens=2,
                    cost_usd=None,
                    raw={"stdout_jsonl": '{"type":"turn.completed"}\n', "stderr": "", "cwd_isolated_from_benchmark": True},
                )

        with tempfile.TemporaryDirectory(prefix="luna-runner-codex-test-") as temp:
            root = Path(temp)
            shutil.copytree(source_root / "benchmark", root / "benchmark")
            args = argparse.Namespace(
                root=root,
                model=CODEX_LUNA_MODEL,
                provider="codex-cli",
                provider_command=None,
                codex_binary="codex",
                api_url=None,
                api_key_env="OPENAI_API_KEY",
                system_prompt="",
                system_prompt_file=None,
                temperature=None,
                top_p=None,
                seed=None,
                max_output_tokens=None,
                reasoning=None,
                max_retries=None,
                timeout_seconds=10.0,
                task_id=["CODE-01"],
            )
            with patch("src.runner.CodexCLIProvider", FakeProvider):
                result = run_benchmark(args)

            run_dir = Path(result["run_dir"])
            raw_records = [json.loads(line) for line in (run_dir / "raw_execution.jsonl").read_text(encoding="utf-8").splitlines()]
            metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(len(raw_records), 1)
            self.assertEqual(raw_records[0]["raw_provider_execution"]["stdout_jsonl"], '{"type":"turn.completed"}\n')
            self.assertEqual(metadata["requested_model"], CODEX_LUNA_MODEL)
            self.assertEqual(metadata["transport"], CODEX_CLI_INTERFACE)
            self.assertEqual(metadata["provider_returned_model"], "not_exposed")
            self.assertEqual(metadata["chatgpt_picker_equivalence"], "unverified")
            self.assertEqual(metadata["max_retries"], 0)
            self.assertEqual(verify_run(root, run_dir)["status"], "passed")


if __name__ == "__main__":
    unittest.main()

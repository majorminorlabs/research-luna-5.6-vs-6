import argparse
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.luna6_probe import (
    AVAILABLE,
    CODEX_6_LUNA_MODEL,
    CODEX_CLI_INTERFACE,
    FROZEN_BENCHMARK_SHA256,
    PROBE_PROMPT,
    UNAVAILABLE,
    run_probe,
)
from src.runner import CodexCLIProvider, NOT_EXPOSED, ProviderError, ProviderResult


class Luna6ProbeTests(unittest.TestCase):
    def test_provider_forwards_exact_luna6_slug(self):
        provider = object.__new__(CodexCLIProvider)
        provider.codex_binary = "codex"
        provider.model = CODEX_6_LUNA_MODEL
        self.assertIn(CODEX_6_LUNA_MODEL, provider._argv_template())
        self.assertNotIn("gpt-5.6-luna", provider._argv_template())

    def _args(self, root: Path, output_root: Path | None = None) -> argparse.Namespace:
        return argparse.Namespace(
            root=root,
            model=CODEX_6_LUNA_MODEL,
            provider="codex-cli",
            codex_binary="codex",
            timeout_seconds=10.0,
            output_root=output_root,
        )

    def _root_with_frozen_benchmark(self):
        source_root = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory(prefix="luna6-probe-test-")
        root = Path(temporary.name)
        shutil.copytree(source_root / "benchmark", root / "benchmark")
        return temporary, root

    def test_success_records_synthetic_generation_without_creating_run(self):
        temporary, root = self._root_with_frozen_benchmark()
        self.addCleanup(temporary.cleanup)

        class FakeProvider:
            codex_version = "codex-cli synthetic"
            interface = CODEX_CLI_INTERFACE

            def __init__(self, _binary, _timeout, model):
                self.model = model

            def configuration(self):
                return {"transport": CODEX_CLI_INTERFACE, "requested_model": self.model}

            def call(self, payload):
                self.payload = payload
                return ProviderResult(
                    text="LUNA6_PROBE_OK",
                    returned_model=NOT_EXPOSED,
                    finish_reason=NOT_EXPOSED,
                    input_tokens=5,
                    output_tokens=1,
                    cost_usd=None,
                    raw={
                        "transport": CODEX_CLI_INTERFACE,
                        "requested_model": CODEX_6_LUNA_MODEL,
                        "provider_returned_model": NOT_EXPOSED,
                        "codex_version": self.codex_version,
                        "returncode": 0,
                        "output_last_message": "LUNA6_PROBE_OK",
                        "stdout_jsonl": '{"type":"item.completed","item":{"type":"agent_message"}}\n',
                        "stderr": "",
                        "event_summary": {
                            "agent_message_count": 1,
                            "item_types": ["agent_message"],
                            "usage": {"input_tokens": 5, "output_tokens": 1},
                        },
                    },
                )

        with patch("src.luna6_probe.CodexCLIProvider", FakeProvider):
            result = run_probe(self._args(root))

        self.assertEqual(result["status"], AVAILABLE)
        probe_path = Path(result["probe_artifact"])
        summary = json.loads(probe_path.read_text(encoding="utf-8"))
        request = json.loads((probe_path.parent / "request.json").read_text(encoding="utf-8"))
        raw = json.loads((probe_path.parent / "raw_execution.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["benchmark_sha256"], FROZEN_BENCHMARK_SHA256)
        self.assertEqual(summary["final_response"], "LUNA6_PROBE_OK")
        self.assertTrue(all(summary["generation_checks"].values()))
        self.assertEqual(request["user_prompt"], PROBE_PROMPT)
        self.assertFalse(request["benchmark_task_used"])
        self.assertEqual(raw["output_last_message"], "LUNA6_PROBE_OK")
        self.assertFalse((root / "runs").exists())

    def test_chatgpt_model_rejection_is_unavailable_before_generation(self):
        temporary, root = self._root_with_frozen_benchmark()
        self.addCleanup(temporary.cleanup)

        class FakeProvider:
            codex_version = "codex-cli synthetic"

            def __init__(self, _binary, _timeout, _model):
                pass

            def configuration(self):
                return {"transport": CODEX_CLI_INTERFACE}

            def call(self, _payload):
                raise ProviderError(
                    "Codex CLI exited with 1",
                    retryable=False,
                    raw={
                        "transport": CODEX_CLI_INTERFACE,
                        "requested_model": CODEX_6_LUNA_MODEL,
                        "provider_returned_model": NOT_EXPOSED,
                        "returncode": 1,
                        "output_last_message": "",
                        "stderr": "The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account.",
                        "stdout_jsonl": "",
                        "event_summary": {"agent_message_count": 0, "item_types": ["error"]},
                    },
                )

        with patch("src.luna6_probe.CodexCLIProvider", FakeProvider):
            result = run_probe(self._args(root))

        self.assertEqual(result["status"], UNAVAILABLE)
        self.assertEqual(result["error_class"], "model_or_chatgpt_access_rejected")
        self.assertTrue(result["rejection_before_generation"])
        probe_path = Path(result["probe_artifact"])
        summary = json.loads(probe_path.read_text(encoding="utf-8"))
        raw = json.loads((probe_path.parent / "raw_execution.json").read_text(encoding="utf-8"))
        self.assertTrue(summary["rejection_before_generation"])
        self.assertIn("not supported", raw["provider_raw_execution"]["stderr"])
        self.assertFalse((root / "runs").exists())


if __name__ == "__main__":
    unittest.main()

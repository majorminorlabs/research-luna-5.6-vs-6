import contextlib
import io
import json
import shutil
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from src.runner import _initialize_manual_run, _read_manual_response, export_prompts, manual_capture_run, verify_run
from src.validators import load_tasks, validate_benchmark


ROOT = Path(__file__).resolve().parents[1]


class ManualCaptureTests(unittest.TestCase):
    def test_response_reader_preserves_pasted_lines(self):
        import io

        sentinel = "__END__"
        pasted = "first line\n\nsecond line with  spaces  \n"
        self.assertEqual(_read_manual_response(sentinel, io.StringIO(pasted + sentinel + "\n")), pasted)

    def test_prompt_export_preserves_frozen_prompt_text_and_order(self):
        tasks = load_tasks(ROOT / "benchmark" / "tasks.jsonl")
        with tempfile.TemporaryDirectory(prefix="luna-prompt-export-") as temp:
            output = Path(temp) / "prompts.txt"
            result = export_prompts(ROOT, output)
            self.assertEqual(result["task_count"], 30)
            exported = output.read_text(encoding="utf-8")
            cursor = 0
            for task in tasks:
                begin = f"===== TASK {task['id']} ({task['category']}) =====\nBEGIN_PROMPT\n"
                start = exported.index(begin, cursor) + len(begin)
                end = exported.index("\nEND_PROMPT", start)
                self.assertEqual(exported[start:end], task["prompt"])
                cursor = end + len("\nEND_PROMPT")

    def test_manual_run_initialization_uses_manual_identity_and_not_exposed_controls(self):
        with tempfile.TemporaryDirectory(prefix="luna-manual-run-") as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "benchmark", root / "benchmark")
            (root / "runs").mkdir()
            validation = validate_benchmark(root)
            tasks = load_tasks(root / "benchmark" / "tasks.jsonl")
            run_id, run_dir, metadata = _initialize_manual_run(root, "Luna 5.6", validation, [task["id"] for task in tasks])
            self.assertEqual(metadata["run_id"], run_id)
            self.assertEqual(metadata["provider"], "chatgpt-manual")
            self.assertEqual(metadata["exact_model_identifier_returned"], "not_exposed")
            self.assertTrue(all(value == "not_exposed" for value in metadata["generation_parameters"].values()))
            self.assertEqual(
                {path.name for path in run_dir.iterdir()},
                {"metadata.json", "requests.jsonl", "responses.jsonl", "scores.jsonl", "errors.jsonl"},
            )

    def test_interrupted_manual_run_resumes_and_preserves_raw_response(self):
        with tempfile.TemporaryDirectory(prefix="luna-manual-resume-") as temp:
            root = Path(temp)
            shutil.copytree(ROOT / "benchmark", root / "benchmark")
            (root / "runs").mkdir()
            args = Namespace(root=root, model="Luna 5.6", task_id=None, override_duplicate=False)

            first_values = iter(["raw first\n\nwith  spaces  \n", "raw second", EOFError()])

            def first_capture(_sentinel):
                value = next(first_values)
                if isinstance(value, BaseException):
                    raise value
                return value

            with patch("src.runner._read_manual_response", side_effect=first_capture), contextlib.redirect_stdout(io.StringIO()):
                interrupted = manual_capture_run(args)
            self.assertEqual(interrupted["status"], "interrupted")
            self.assertEqual(interrupted["captured"], 2)

            remaining_values = iter([f"raw remaining {index}" for index in range(28)])
            with patch("src.runner._read_manual_response", side_effect=lambda _sentinel: next(remaining_values)), contextlib.redirect_stdout(io.StringIO()):
                completed = manual_capture_run(args, resume_dir=Path(interrupted["run_dir"]))
            self.assertEqual(completed["status"], "complete")
            verified = verify_run(root, Path(interrupted["run_dir"]))
            self.assertEqual(verified["task_count"], 30)
            responses = [json.loads(line) for line in (Path(interrupted["run_dir"]) / "responses.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(responses[0]["response_text"], "raw first\n\nwith  spaces  \n")


if __name__ == "__main__":
    unittest.main()

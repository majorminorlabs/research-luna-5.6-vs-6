import json
import unittest
from pathlib import Path

from src.validators import EXPECTED_IDS, calculate_reas02, load_tasks, solve_reas01, solve_reas04, validate_benchmark


ROOT = Path(__file__).resolve().parents[1]


class TaskValidationTests(unittest.TestCase):
    def test_frozen_benchmark_validates(self):
        result = validate_benchmark(ROOT)
        self.assertEqual(result["task_count"], 30)
        self.assertEqual(result["benchmark_version"], "luna-comparison-v1.0")

    def test_ids_and_categories(self):
        tasks = load_tasks(ROOT / "benchmark" / "tasks.jsonl")
        self.assertEqual([task["id"] for task in tasks], EXPECTED_IDS)
        self.assertEqual({task["category"] for task in tasks}, {"CODE", "REAS", "EVID", "EXTR", "AGENT", "CTX", "WRITE"})

    def test_programmatic_reasoning_answers(self):
        self.assertEqual(solve_reas01(), [{"Arin": "Y", "Bea": "Z", "Cole": "W", "Dara": "X"}])
        self.assertEqual(solve_reas04(), ["ACEBD"])
        self.assertEqual(calculate_reas02()["maximum_sequences"], 5)

    def test_ctx_filler_is_frozen_in_prompt(self):
        tasks = load_tasks(ROOT / "benchmark" / "tasks.jsonl")
        prompt = next(task["prompt"] for task in tasks if task["id"] == "CTX-01")
        self.assertIn("Filler note 01", prompt)
        self.assertIn("Filler note 10", prompt)
        self.assertIn("must not be generated at runtime", prompt)


if __name__ == "__main__":
    unittest.main()

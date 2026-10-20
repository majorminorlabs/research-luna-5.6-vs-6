import json
import unittest
from pathlib import Path

from src.validators import EXPECTED_IDS, load_answer_keys, load_tasks


ROOT = Path(__file__).resolve().parents[1]


class AnswerKeyTests(unittest.TestCase):
    def test_every_task_has_answer_key(self):
        tasks = load_tasks(ROOT / "benchmark" / "tasks.jsonl")
        keys = load_answer_keys(ROOT / "benchmark" / "answer_keys.json")["tasks"]
        self.assertEqual(set(keys), set(EXPECTED_IDS))
        self.assertEqual(set(task["id"] for task in tasks), set(keys))

    def test_exact_keys_are_json_values(self):
        keys = load_answer_keys(ROOT / "benchmark" / "answer_keys.json")["tasks"]
        for task_id in ("EXTR-01", "EXTR-02", "EXTR-04", "EVID-03"):
            expected = keys[task_id]["deterministic"]["expected"]
            self.assertEqual(json.loads(json.dumps(expected)), expected)

    def test_frozen_correction_is_documented_in_prompt_and_key(self):
        tasks = {task["id"]: task for task in load_tasks(ROOT / "benchmark" / "tasks.jsonl")}
        keys = load_answer_keys(ROOT / "benchmark" / "answer_keys.json")["tasks"]
        self.assertIn("Cole did not run Z", tasks["REAS-01"]["prompt"])
        self.assertEqual(keys["REAS-01"]["deterministic"]["assignment"]["Cole"], "W")


if __name__ == "__main__":
    unittest.main()

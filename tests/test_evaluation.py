import json
import tempfile
import unittest
from pathlib import Path

from src.evaluation import (
    CODEX_JUDGE_MODEL,
    _load_pairwise_scores,
    _pairwise_prompt,
    _parse_pairwise_response,
    _parse_rubric_response,
    _probe_checks,
)


class EvaluationInfrastructureTests(unittest.TestCase):
    def test_rubric_parser_normalizes_and_rejects_mismatched_score(self):
        key = {
            "rubric": [
                {"id": "one", "points": 2, "criterion": "criterion"},
                {"id": "two", "points": 1, "criterion": "criterion"},
            ]
        }
        valid = json.dumps({
            "score": 2 / 3,
            "dimensions": {
                "one": {"points_awarded": 2, "max_points": 2, "rationale": "yes"},
                "two": {"points_awarded": 0, "max_points": 1, "rationale": "no"},
            },
            "rationale": "evidence",
        })
        parsed = _parse_rubric_response(valid, key)
        self.assertAlmostEqual(parsed["normalized_score"], 2 / 3)
        with self.assertRaises(ValueError):
            _parse_rubric_response(valid.replace(str(2 / 3), "0.1"), key)

    def test_pairwise_parser_requires_exact_winner_domain(self):
        self.assertEqual(_parse_pairwise_response('{"winner":"TIE","rationale":"same"}')['winner'], "TIE")
        with self.assertRaises(ValueError):
            _parse_pairwise_response('{"winner":"C","rationale":"bad"}')

    def test_judge_prompts_are_identity_blind(self):
        task = {"prompt": "Return the requested result."}
        key = {"rubric": [{"id": "quality", "points": 1, "criterion": "is correct"}]}
        prompt = _pairwise_prompt(task, key, "Response one", "Response two")
        self.assertNotIn("gpt-5.6", prompt.lower())
        self.assertNotIn("gpt-6", prompt.lower())
        self.assertNotIn("run-id", prompt.lower())
        self.assertIn("Response A:", prompt)
        self.assertIn("Response B:", prompt)
        self.assertNotIn(CODEX_JUDGE_MODEL, prompt)

    def test_probe_rejects_non_agent_item_types(self):
        raw = {
            "requested_model": CODEX_JUDGE_MODEL,
            "returncode": 0,
            "output_last_message": "OK",
            "cwd": "/tmp/probe",
            "cwd_isolated_from_benchmark": True,
            "argv": ["--skip-git-repo-check", "--ignore-user-config", "--ignore-rules"],
            "event_summary": {"agent_message_count": 1, "item_types": ["agent_message", "collab_tool_call"]},
        }
        checks = _probe_checks(raw, root=Path("/repo"), response="OK", expected="OK", is_json=False)
        self.assertFalse(checks["no_disallowed_tool_events"])

    def test_pairwise_scores_keep_repeats_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "mapping.jsonl").write_text(
                "\n".join([
                    json.dumps({"case_id": "one", "repeat": 1, "task_id": "T", "a_source": "l56-r1", "b_source": "l6-r1"}),
                    json.dumps({"case_id": "two", "repeat": 2, "task_id": "T", "a_source": "l56-r2", "b_source": "l6-r2"}),
                ]) + "\n",
                encoding="utf-8",
            )
            (path / "responses.jsonl").write_text(
                "\n".join([
                    json.dumps({"case_id": "one", "status": "JUDGED", "parsed_result": {"winner": "A", "rationale": "r1"}}),
                    json.dumps({"case_id": "two", "status": "JUDGED", "parsed_result": {"winner": "B", "rationale": "r2"}}),
                ]) + "\n",
                encoding="utf-8",
            )
            scores, decisions, _ = _load_pairwise_scores(path)
            self.assertEqual(scores[("l56-r1", 1, "T")], 1.0)
            self.assertEqual(scores[("l56-r2", 2, "T")], 0.0)
            self.assertEqual(len(decisions), 2)


if __name__ == "__main__":
    unittest.main()

import unittest

from src.scorers import (
    SCORER_VERSION,
    aggregate_scores,
    build_pairwise_prompt,
    make_blind_pairing,
    normalize_pairwise_decision,
    score_pairwise_decision,
    score_task,
)
from src.validators import canonical_compact_ranges, check_extr03_constraints


class ScorerTests(unittest.TestCase):
    def test_scorer_version_is_incremented_for_audit_fixes(self):
        self.assertEqual(SCORER_VERSION, "scorers-1.2.0")

    def test_code01_accepts_root_cause_inflections(self):
        key = {
            "deterministic": {
                "method": "code01",
                "root_cause_terms": ["mutation", "iteration"],
                "required_function_terms": ["for", "cancelled", "remove"],
            }
        }
        response = "The list mutates during iteration, so the loop skips an item."
        response += " for job in jobs: remove cancelled"
        response += " [1, 3, 5]"
        score = score_task("CODE-01", response, key)
        self.assertTrue(score["deterministic_details"]["checks"]["root_cause"])

    def test_code01_accepts_explicit_list_change_wording(self):
        key = {
            "deterministic": {
                "method": "code01",
                "root_cause_terms": ["mutation", "iteration"],
                "required_function_terms": ["for", "cancelled", "remove"],
            }
        }
        response = "Removing a job changes the list while the for loop is iterating."
        response += " for job in jobs: remove cancelled"
        response += " [1, 3, 5]"
        score = score_task("CODE-01", response, key)
        self.assertTrue(score["deterministic_details"]["checks"]["root_cause"])

    def test_reas01_accepts_explicit_markdown_assignment_table(self):
        key = {
            "deterministic": {
                "method": "reas01",
                "assignment": {"Arin": "Y", "Bea": "Z", "Cole": "W", "Dara": "X"},
            }
        }
        response = "| Researcher | Experiment |\n|---|---|\n| Arin | Y |\n| Bea | Z |\n| Cole | W |\n| Dara | X |"
        score = score_task("REAS-01", response, key)
        self.assertEqual(score["deterministic_score"], 1.0)

    def test_reas01_accepts_unicode_dash_assignments(self):
        key = {
            "deterministic": {
                "method": "reas01",
                "assignment": {"Arin": "Y", "Bea": "Z", "Cole": "W", "Dara": "X"},
            }
        }
        response = "Arin–Y, Bea–Z, Cole–W, Dara–X"
        score = score_task("REAS-01", response, key)
        self.assertEqual(score["deterministic_score"], 1.0)

    def test_write02_allows_negated_better_overall_statement(self):
        response = "The measurements do not show that Q4 is better overall."
        score = score_task("WRITE-02", response, {"rubric": []})
        self.assertEqual(score["constraint_score"], 1.0)

    def test_write02_rejects_affirmative_better_overall_statement(self):
        response = "Q4 is better overall."
        score = score_task("WRITE-02", response, {"rubric": []})
        self.assertEqual(score["constraint_score"], 2 / 3)

    def test_reas04_ignores_insignificant_spacing_between_schedule_letters(self):
        key = {"deterministic": {"method": "reas04", "schedules": ["ACEBD"]}}
        score = score_task("REAS-04", "A C E B D\n", key)
        self.assertEqual(score["deterministic_score"], 1.0)
        self.assertTrue(score["deterministic_details"]["whitespace_normalized"])

    def test_reas05_does_not_count_nested_hypothesis_bullets_as_actions(self):
        response = "1. First diagnostic\n   - Hypothesis tested\n2. Second diagnostic\n   - Hypothesis tested\n3. Third diagnostic\n   - Hypothesis tested"
        score = score_task("REAS-05", response, {"rubric": []})
        self.assertEqual(score["constraint_score"], 1.0)
        self.assertEqual(score["constraint_details"]["top_level_action_count"], 3)

    def test_agent01_accepts_numbered_bold_action_labels(self):
        response = "\n".join(
            f"{index}. **ACTION:** step\n**WHY:** reason\n**ROLLBACK:** undo"
            for index in range(1, 9)
        )
        score = score_task("AGENT-01", response, {"rubric": []})
        self.assertEqual(score["constraint_score"], 1.0)
        self.assertEqual(score["constraint_details"]["action_label_count"], 8)

    def test_terminal_error_is_not_scored_as_model_incorrectness(self):
        key = {"deterministic": {"method": "reas02", "maximum_sequences": 5}, "rubric": []}
        score = score_task("REAS-02", "", key, terminal_status="ERROR")
        self.assertIsNone(score["deterministic_score"])
        self.assertIsNone(score["constraint_score"])
        self.assertEqual(score["scoring_status"], "NOT_SCORED_TERMINAL_ERROR")

    def test_compact_ranges_canonical_implementation(self):
        self.assertEqual(canonical_compact_ranges([8, 1, 3, 2, 2, 10, 11, 12, -2, -1]), "-2,-1,1-3,8,10-12")
        self.assertEqual(canonical_compact_ranges([]), "")
        self.assertEqual(canonical_compact_ranges([1, 2]), "1,2")

    def test_extr03_constraints(self):
        response = "An index speeds lookup by storing searchable keys. It has a tradeoff because writes need maintenance. For example, an index on users.email can speed an email lookup."
        details = check_extr03_constraints(response)
        self.assertEqual(details["sentence_count"], 3)
        self.assertTrue(details["first_prefix"])
        self.assertTrue(details["second_contains_tradeoff"])
        self.assertTrue(details["third_has_example"])
        self.assertFalse(details["has_semicolon"])
        self.assertLessEqual(details["word_count"], 65)

    def test_exact_json_score(self):
        key = {"deterministic": {"method": "json_exact", "expected": {"a": 1}}}
        score = score_task("T", '{"a":1}', key)
        self.assertEqual(score["deterministic_score"], 1.0)
        self.assertEqual(score["constraint_score"], None)

    def test_blind_pairing_does_not_put_model_names_in_judge_prompt(self):
        task = {"id": "T", "prompt": "Do the task."}
        rubric = [{"criterion": "Correctness"}]
        pairing = make_blind_pairing(task, rubric, {"luna-5.6": "A response", "luna-6": "B response"}, 17)
        self.assertFalse(pairing["judge_input_contains_model_ids"])
        self.assertNotIn("luna-5.6", pairing["judge_prompt"])
        self.assertNotIn("luna-6", pairing["judge_prompt"])
        self.assertEqual(normalize_pairwise_decision("TIE"), "TIE")
        result = score_pairwise_decision(pairing, "A")
        self.assertEqual(result["normalized_decision"], "A")
        self.assertEqual(result["winner"], pairing["model_for_a"])

    def test_capability_stays_pending_without_judgments(self):
        aggregate = aggregate_scores([{"deterministic_score": 1.0, "constraint_score": 1.0, "rubric_score": None, "pairwise_score": None}])
        self.assertIsNone(aggregate["capability_score"])
        self.assertEqual(aggregate["capability_score_status"], "PENDING_COMPONENTS")


if __name__ == "__main__":
    unittest.main()

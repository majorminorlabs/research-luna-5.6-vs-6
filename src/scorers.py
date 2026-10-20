"""Task-aware scoring and blind pairwise-judging helpers.

No model is called here.  Exact checks are deterministic; rubric and pairwise
components remain explicitly pending until a configured judge supplies them.
"""

from __future__ import annotations

import json
import random
import re
from collections import defaultdict
from typing import Any, Iterable

try:  # package import
    from .validators import check_extr03_constraints
except ImportError:  # direct ``PYTHONPATH=src`` import
    from validators import check_extr03_constraints


CAPABILITY_WEIGHTS = {
    "deterministic": 0.45,
    "rubric": 0.30,
    "constraints": 0.15,
    "pairwise": 0.10,
}

SCORER_VERSION = "scorers-1.2.0"


def _words(text: str) -> list[str]:
    return re.findall(r"\b[\w'-]+\b", text)


def _has_number(text: str, number: int) -> bool:
    return bool(re.search(rf"(?<!\d){number}(?!\d)", text))


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip()).lower()


def _root_cause_term_present(text: str, term: str) -> bool:
    """Match the intended root-cause terms across ordinary word inflections."""

    patterns = {
        "mutation": r"(?:\bmutat(?:e|es|ed|ing|ion|ions)\b|\b(?:changes|modifies|alters|updates)\s+(?:the\s+)?(?:list|array|collection)\b)",
        "iteration": r"\biterat(?:e|es|ed|ing|ion|ions)\b",
    }
    pattern = patterns.get(term)
    if pattern is None:
        return bool(re.search(rf"\b{re.escape(term)}\b", text, re.I))
    return bool(re.search(pattern, text, re.I))


def _top_level_list_item_count(text: str) -> tuple[int, int | None]:
    """Count list items at the shallowest indentation level.

    Nested hypothesis bullets must not be counted as additional ranked actions.
    """

    items: list[tuple[int, str]] = []
    for line in text.splitlines():
        match = re.match(r"^(?P<indent>[ \t]*)(?P<marker>(?:\d+[.)]|[-*]))[ \t]+", line)
        if match:
            indent = len(match.group("indent").expandtabs(4))
            items.append((indent, match.group("marker")))
    if not items:
        return 0, None
    minimum_indent = min(indent for indent, _ in items)
    return sum(indent == minimum_indent for indent, _ in items), minimum_indent


def _action_label_count(text: str) -> int:
    """Count numbered or plain Markdown ACTION labels, including bold labels."""

    pattern = r"(?im)^[ \t]*(?:\d+[.)][ \t]+)?[*_]{0,2}ACTION[*_]{0,2}[ \t]*:"
    return len(re.findall(pattern, text))


def _json_exact(text: str, expected: Any) -> tuple[float, dict[str, Any]]:
    try:
        actual = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return 0.0, {"json_valid": False, "error": str(exc)}
    passed = actual == expected
    return float(passed), {"json_valid": True, "exact_match": passed}


def _deterministic_score(task_id: str, text: str, key: dict[str, Any]) -> tuple[float | None, dict[str, Any]]:
    definition = key.get("deterministic", {})
    method = definition.get("method")
    if method == "json_exact":
        return _json_exact(text, definition["expected"])
    if method == "code01":
        lower = text.lower()
        terms = definition["root_cause_terms"]
        root_cause = all(_root_cause_term_present(lower, term) for term in terms)
        final_ids = bool(re.search(r"\[\s*1\s*,\s*3\s*,\s*5\s*\]", text))
        function = all(term in lower for term in definition["required_function_terms"])
        passed = [root_cause, final_ids, function]
        return sum(passed) / len(passed), {"checks": {"root_cause": root_cause, "final_ids": final_ids, "function": function}}
    if method == "reas01":
        assignment = definition["assignment"]
        checks = {}
        for person, experiment in assignment.items():
            inline = bool(re.search(rf"\b{person}\b[ \t]*(?:[-:=]|is)[ \t]*{experiment}\b", text, re.I))
            unicode_dash = bool(re.search(rf"\b{person}\b[ \t]*(?:[–—])[ \t]*{experiment}\b", text, re.I))
            table = bool(re.search(rf"(?im)^[ \t]*\|?[ \t]*{person}[ \t]*\|[ \t]*{experiment}[ \t]*\|?[ \t]*$", text))
            checks[person] = inline or unicode_dash or table
        return sum(checks.values()) / len(checks), {"checks": checks}
    if method == "reas02":
        passed = _has_number(text, int(definition["maximum_sequences"])) and any(word in text.lower() for word in ("sequence", "sequences"))
        return float(passed), {"maximum_sequences": definition["maximum_sequences"], "match": passed}
    if method == "reas04":
        raw_lines = [line.strip() for line in text.splitlines() if line.strip()]
        actual = [re.sub(r"[ \t]+", "", line.upper().strip("` .,;:")) for line in raw_lines]
        expected = [str(value).upper() for value in definition["schedules"]]
        passed = actual == expected
        return float(passed), {
            "actual_lines": actual,
            "raw_lines": raw_lines,
            "expected_lines": expected,
            "whitespace_normalized": actual != raw_lines,
        }
    if method == "evid03":
        try:
            actual = json.loads(text.strip())
        except json.JSONDecodeError as exc:
            return 0.0, {"json_valid": False, "error": str(exc)}
        expected = definition["expected"]
        checks = {claim: actual.get(claim) == value for claim, value in expected.items()} if isinstance(actual, dict) else {}
        return (sum(checks.values()) / len(expected) if checks else 0.0), {"checks": checks, "extra_keys": sorted(set(actual) - set(expected)) if isinstance(actual, dict) else []}
    if method == "extr03_constraints":
        checks = check_extr03_constraints(text)
        passed = [
            checks["sentence_count"] == definition["sentence_count"],
            checks["first_prefix"] == True,
            checks["second_contains_tradeoff"] == True,
            checks["third_has_example"] == True,
            checks["has_semicolon"] == False,
            checks["has_analogy"] == False,
            checks["word_count"] <= definition["max_words"],
        ]
        return sum(passed) / len(passed), {"checks": checks, "passed": passed}
    if method == "agent03":
        lower = text.lower()
        operation = "search_all_files" in lower and "max_worker_retries" in lower
        cost = bool(re.search(r"\b(?:cost|total|minimum)\D{0,12}3\b", lower)) or bool(re.search(r"\b3\s*(?:units|points|dollars)?\b", lower))
        return (float(operation and cost), {"operation": operation, "cost": cost})
    if method == "agent04":
        action_lines = [line.strip().upper() for line in text.splitlines() if line.strip()]
        chosen = next((line for line in action_lines if line in {"CONTINUE", "STOP", "REQUEST_MORE_BUDGET"}), None)
        passed = chosen == definition["action"]
        return float(passed), {"chosen_action": chosen, "expected_action": definition["action"]}
    if method == "contains_all":
        checks = {required: required.lower() in text.lower() for required in definition["required"]}
        return sum(checks.values()) / len(checks), {"checks": checks}
    return None, {"reason": "no deterministic scorer for this task"}


def _constraint_score(task_id: str, text: str) -> tuple[float | None, dict[str, Any]]:
    words = len(_words(text))
    checks: dict[str, bool] = {}

    if task_id == "EXTR-03":
        details = check_extr03_constraints(text)
        checks = {
            "three_sentences": details["sentence_count"] == 3,
            "starts_an_index": details["first_prefix"],
            "tradeoff_in_sentence_two": details["second_contains_tradeoff"],
            "example_in_sentence_three": details["third_has_example"],
            "no_semicolon": not details["has_semicolon"],
            "no_analogy": not details["has_analogy"],
            "max_65_words": details["word_count"] <= 65,
        }
    elif task_id in {"EVID-01", "EVID-05", "CTX-02", "WRITE-02"}:
        maximum = {"EVID-01": 180, "EVID-05": 150, "CTX-02": 80, "WRITE-02": 130}[task_id]
        checks = {f"max_{maximum}_words": words <= maximum}
        if task_id == "WRITE-02":
            lower = text.lower()
            checks["no_significance_claim"] = "statistically significant" not in lower and "statistically insignificant" not in lower
            better_overall_sentences = re.findall(r"[^.!?]*(?:better overall|overall, better)[^.!?]*[.!?]?", lower)
            affirmative_better = any(
                not re.search(r"\b(?:not|never|no|doesn['’]?t|does not|do not|cannot|can't)\b", sentence)
                for sentence in better_overall_sentences
            )
            checks["no_better_overall_claim"] = not affirmative_better
    elif task_id == "WRITE-01":
        checks = {"between_90_and_120_words": 90 <= words <= 120}
    elif task_id == "AGENT-01":
        action_count = _action_label_count(text)
        checks = {"at_most_eight_steps": 1 <= action_count <= 8, "has_action_why_rollback": all(label in text.upper() for label in ("ACTION:", "WHY:", "ROLLBACK:"))}
    elif task_id == "AGENT-02":
        numbered = re.findall(r"(?m)^\s*\d+[.)]\s+", text)
        checks = {"exactly_five_ordered_actions": len(numbered) == 5, "does_not_continue_rollout": "continue rollout" not in text.lower()}
    elif task_id == "AGENT-04":
        checks = {"max_40_words": words <= 40}
    elif task_id == "REAS-05":
        action_count, action_indent = _top_level_list_item_count(text)
        checks = {"three_actions": action_count == 3}
    elif task_id == "CTX-01":
        checks = {"one_sentence": len([part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part.strip()]) == 1}
    elif task_id == "CTX-03":
        checks = {"mentions_both_conflicts": "csv" in text.lower() and "schema_version" in text.lower()}
    elif task_id == "WRITE-03":
        checks = {"nonempty": bool(text.strip())}
    else:
        return None, {"reason": "no mechanical constraint checks declared"}

    details = {"checks": checks, "word_count": words}
    if task_id == "AGENT-01":
        details["action_label_count"] = action_count
    if task_id == "REAS-05":
        details["top_level_action_count"] = action_count
        details["top_level_indent"] = action_indent
    return (sum(checks.values()) / len(checks) if checks else None), details


def score_task(task_id: str, text: str, key: dict[str, Any], terminal_status: str = "SUCCESS") -> dict[str, Any]:
    if terminal_status == "ERROR":
        deterministic = None
        deterministic_details = {"reason": "terminal ERROR is an infrastructure/model execution failure; correctness not scored"}
        constraints = None
        constraint_details = {"reason": "terminal ERROR is an infrastructure/model execution failure; constraints not scored"}
        scoring_status = "NOT_SCORED_TERMINAL_ERROR"
    else:
        deterministic, deterministic_details = _deterministic_score(task_id, text, key)
        constraints, constraint_details = _constraint_score(task_id, text)
        scoring_status = "PENDING_RUBRIC_AND_PAIRWISE" if key.get("rubric") else "DETERMINISTIC_ONLY"
    return {
        "task_id": task_id,
        "terminal_status": terminal_status,
        "deterministic_score": deterministic,
        "deterministic_details": deterministic_details,
        "rubric_score": None,
        "constraint_score": constraints,
        "constraint_details": constraint_details,
        "pairwise_score": None,
        "scoring_status": scoring_status,
        "scorer_version": SCORER_VERSION,
    }


def apply_rubric_score(score_record: dict[str, Any], value: float, *, source: str) -> dict[str, Any]:
    if not 0.0 <= value <= 1.0:
        raise ValueError("rubric score must be between 0 and 1")
    result = dict(score_record)
    result["rubric_score"] = value
    result["rubric_source"] = source
    return result


def normalize_pairwise_decision(raw: str) -> str:
    cleaned = raw.strip().upper()
    if cleaned in {"A", "B", "TIE"}:
        return cleaned
    match = re.search(r"\b(TIE|A|B)\b", cleaned)
    if not match:
        raise ValueError("pairwise judge response did not contain A, B, or TIE")
    return match.group(1)


def build_pairwise_prompt(task: dict[str, Any], rubric: Iterable[dict[str, Any]], response_a: str, response_b: str) -> str:
    rubric_text = "\n".join(f"- {item['criterion']}" for item in rubric)
    return (
        "You are a blind evaluator. Do not infer or discuss model identities.\n\n"
        f"Task:\n{task['prompt']}\n\n"
        f"Task-specific rubric:\n{rubric_text}\n\n"
        f"Response A:\n{response_a}\n\n"
        f"Response B:\n{response_b}\n\n"
        "Which response better satisfies the task and rubric? Reply with exactly one token: A, B, or TIE."
    )


def make_blind_pairing(task: dict[str, Any], rubric: Iterable[dict[str, Any]], responses: dict[str, str], seed: int) -> dict[str, Any]:
    if len(responses) != 2:
        raise ValueError("blind pairing requires exactly two model responses")
    model_ids = list(responses)
    random.Random(seed).shuffle(model_ids)
    model_a, model_b = model_ids
    prompt = build_pairwise_prompt(task, rubric, responses[model_a], responses[model_b])
    return {
        "task_id": task["id"],
        "seed": seed,
        "model_for_a": model_a,
        "model_for_b": model_b,
        "judge_prompt": prompt,
        "judge_input_contains_model_ids": False,
    }


def score_pairwise_decision(pairing: dict[str, Any], raw_judge_response: str) -> dict[str, Any]:
    decision = normalize_pairwise_decision(raw_judge_response)
    model_a = pairing["model_for_a"]
    model_b = pairing["model_for_b"]
    if decision == "A":
        winner, loser = model_a, model_b
    elif decision == "B":
        winner, loser = model_b, model_a
    else:
        winner = loser = None
    return {
        "task_id": pairing["task_id"],
        "raw_judge_response": raw_judge_response,
        "normalized_decision": decision,
        "winner": winner,
        "loser": loser,
    }


def aggregate_scores(score_records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(score_records)
    available: dict[str, list[float]] = defaultdict(list)
    for record in records:
        for key, field in (("deterministic", "deterministic_score"), ("rubric", "rubric_score"), ("constraints", "constraint_score"), ("pairwise", "pairwise_score")):
            value = record.get(field)
            if isinstance(value, (int, float)):
                available[key].append(float(value))
    component_averages = {key: (sum(values) / len(values) if values else None) for key, values in available.items()}
    missing = [key for key in CAPABILITY_WEIGHTS if component_averages.get(key) is None]
    capability = None if missing else sum(component_averages[key] * CAPABILITY_WEIGHTS[key] for key in CAPABILITY_WEIGHTS)
    return {
        "task_count": len(records),
        "capability_score": capability,
        "capability_score_status": "COMPLETE" if capability is not None else "PENDING_COMPONENTS",
        "missing_components": missing,
        "component_averages": component_averages,
        "deterministic_pass_rate": (
            sum(value == 1.0 for value in available.get("deterministic", [])) / len(available["deterministic"])
            if available.get("deterministic") else None
        ),
    }

# Luna 5.6 scorer audit

Audit date: 2026-09-22

Benchmark: `luna-comparison-v1.0`

Frozen benchmark SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`

Frozen benchmark commit: `de4283d944257b0fdaf15e116309b0df59e6e103`

The original run score files remain untouched at `scorers-1.0.0`. The
objective fixes below increment the scorer to `scorers-1.1.0`; revised scores
are additive files under `reports/` and are not replacements for captured
responses or original scores.

## Findings

| Task | Classification | Finding | Revised treatment |
|---|---|---|---|
| CODE-01 | `BUG_FIX` | The matcher required the exact nouns `mutation` and `iteration`, while both responses used ordinary inflections such as `mutates`/`mutating` and `iterating`. | Match the narrowly defined word families; both outputs identify mutation during iteration. |
| REAS-01 | `ROBUSTNESS_FIX` | Repeat 1 gives all four assignments in an explicit Markdown table, but the matcher only accepted inline `Person = Experiment`-style forms. | Parse explicit table rows. The model's separate claim that the frozen facts were non-unique remains a substantive response issue for rubric/constraint review; no LLM judgment is inferred here. |
| REAS-02 | `BUG_FIX` | Repeat 1 is a provider timeout with no model response. | Do not score terminal `ERROR` as model incorrectness; preserve the timeout as an infrastructure/model-execution failure. |
| REAS-04 | `ROBUSTNESS_FIX` | Repeat 1 returns `A C E B D`, which is the sole schedule with insignificant inter-letter whitespace. | Remove only whitespace within a schedule line before comparing canonical schedule symbols. |
| REAS-05 | `BUG_FIX` | The parser counted the three indented hypothesis bullets as three extra actions, producing six list markers instead of three ranked diagnostics. | Count list items at the shallowest indentation level. |
| AGENT-01 | `BUG_FIX` | Both responses contain exactly eight numbered bold `**ACTION:**` labels, but the matcher did not recognize the numbered/bold Markdown form. | Recognize the explicit numbered/bold label form and retain the at-most-eight constraint. |
| CTX-01 | No change | Repeat 2 is a genuine model-output failure, not extraction contamination. | Preserve the `586`-word response and `one_sentence = false` result. |

## Boundary checks

- JSON-only, sentence-count, word-limit, label, and output-only constraints were
  not whitespace-normalized or otherwise relaxed.
- No answer key, task prompt, benchmark manifest, or captured response was
  changed.
- No rubric or blind pairwise judgment was performed.
- The revised score for Repeat 1 `REAS-02` is `null`, not `0`; the terminal
  timeout remains in the immutable response/error artifacts.
- The Repeat 1 `REAS-01` deterministic result is mechanically recognized as a
  complete assignment from its table, but the existing rubric remains pending
  and can evaluate the contradictory non-uniqueness claim separately.

## Revised score artifacts

- `reports/luna56_repeat1_scores-scorers-1.1.0.jsonl`
- `reports/luna56_repeat2_scores-scorers-1.1.0.jsonl`
- `reports/luna56_smoke_scores-scorers-1.1.0.jsonl`
- `reports/luna56_repeat_comparison.json`
- `reports/luna56_repeat_comparison.md`

The original `runs/*/scores.jsonl`, `responses.jsonl`, `raw_execution.jsonl`,
and other run artifacts are immutable evidence and were not overwritten.

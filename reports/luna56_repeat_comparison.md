# Luna 5.6 repeat comparison

Benchmark: `luna-comparison-v1.0`
Tasks SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`
Original scorer: `scorers-1.0.0`
Revised scorer: `scorers-1.1.0`

## Primary repeats

| Repeat | Run | Terminal status | Original deterministic | Revised deterministic | Original constraints | Revised constraints |
|---|---|---|---:|---:|---:|---:|
| repeat 1 | `20260922T210505Z-666f0e58c7` | `{'ERROR': 1, 'SUCCESS': 29, 'TRUNCATED': 0}` | 0.7222 | 1.0000 | 0.8846 | 1.0000 |
| repeat 2 | `20260922T212837Z-09b6935a04` | `{'ERROR': 0, 'SUCCESS': 30, 'TRUNCATED': 0}` | 0.9722 | 1.0000 | 0.8077 | 0.9231 |

The original score files are preserved. Revised deterministic/constraint aggregates exclude terminal errors instead of treating an absent model response as an incorrect answer; rubric and pairwise components were not run.

## Objective scorer changes

| Run | Task | Class | Original → revised |
|---|---|---|---|
| `primary_repeat_1` | `CODE-01` | `BUG_FIX` | deterministic_score: `0.6666666666666666` → `1.0` |
| `primary_repeat_1` | `REAS-01` | `ROBUSTNESS_FIX` | deterministic_score: `0.0` → `1.0` |
| `primary_repeat_1` | `REAS-02` | `BUG_FIX` | deterministic_score: `0.0` → `None` |
| `primary_repeat_1` | `REAS-04` | `ROBUSTNESS_FIX` | deterministic_score: `0.0` → `1.0` |
| `primary_repeat_1` | `REAS-05` | `BUG_FIX` | constraint_score: `0.0` → `1.0` |
| `primary_repeat_1` | `AGENT-01` | `BUG_FIX` | constraint_score: `0.5` → `1.0` |
| `primary_repeat_2` | `CODE-01` | `BUG_FIX` | deterministic_score: `0.6666666666666666` → `1.0` |
| `primary_repeat_2` | `REAS-05` | `BUG_FIX` | constraint_score: `0.0` → `1.0` |
| `primary_repeat_2` | `AGENT-01` | `BUG_FIX` | constraint_score: `0.5` → `1.0` |
| `smoke` | `CODE-01` | `BUG_FIX` | deterministic_score: `0.6666666666666666` → `1.0` |

Full rationale and boundaries are in `SCORER_AUDIT.md`; revised per-task records are in the two `reports/luna56_*_scores-scorers-1.1.0.jsonl` files.

## Named run findings

- `CODE-01`: both responses identify list mutation during iteration; the old lexical matcher missed inflections.
- `REAS-01` Repeat 1: the final Markdown table contains all four correct assignments. Its separate claim that the frozen facts were non-unique remains available for rubric/constraint review; no LLM judgment was performed.
- `REAS-02` Repeat 1: the 120-second Codex timeout is preserved as an infrastructure/model-execution failure and is not scored as model incorrectness in the revised artifact.
- `REAS-04` Repeat 1: `A C E B D` is normalized to the sole canonical schedule `ACEBD`.
- `REAS-05` and `AGENT-01`: both repeats satisfy the requested three top-level diagnostics and eight labeled steps; nested bullets and Markdown emphasis caused the old parser failures.
- `CTX-01` Repeat 2: the raw final-answer file and normalized response are identical; the 586-word prompt/source restatement is a genuine model-output failure, not extraction contamination.

## Luna 6 transport status

The official API catalog lists `gpt-6-luna`, but the installed `codex-cli 0.153.4` using the existing ChatGPT OAuth account rejected that slug with: `The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account.` No Luna 6 benchmark task was sent. See `LUNA_6_TRANSPORT.md` and `reports/luna6_transport_probe.json`.

## Limitations

- Capability scoring remains pending until rubric and blind pairwise components are explicitly supplied.
- This is a 30-task frozen distribution and does not establish universal model superiority.


# Final deterministic scorer audit

Audit date: 2026-09-22

Benchmark: `luna-comparison-v1.0`
Frozen benchmark SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`
Frozen benchmark commit: `de4283d944257b0fdaf15e116309b0df59e6e103`

The four canonical run directories and all captured responses remain unchanged. `scorers-1.2.0` writes additive rescored records under `reports/rescored-scorers-1.2.0/`; the earlier `scorers-1.1.0` artifacts remain available for comparison.

## Findings

| Task | Classification | Exact issue | Treatment |
|---|---|---|---|
| CODE-01 | `ROBUSTNESS_FIX` | GPT-6 Luna Repeat 1 correctly stated that `jobs.remove(job)` changes the list during iteration, but the matcher only recognized mutation word-family forms such as `mutates`. | Accept narrowly defined `changes`, `modifies`, `alters`, or `updates` applied to a list/array/collection. The required root-cause meaning is unchanged. |
| REAS-01 | `ROBUSTNESS_FIX` | GPT-6 Luna Repeat 1 gave the exact assignment with a Unicode en dash separator, which the ASCII inline matcher did not recognize. | Accept Unicode en dash and em dash as assignment separators. The required assignment is unchanged. |
| WRITE-02 | `ROBUSTNESS_FIX` | GPT-6 Luna Repeat 1 explicitly negated the phrase `better overall`, but substring matching treated the quoted phrase as an affirmative claim. | Inspect the sentence containing the phrase and preserve it when a local negation is present. The constraint semantics are unchanged. |
| CTX-01 | No change | The long GPT-5.6 Luna Repeat 2 and GPT-6 Luna Repeat 2 outputs genuinely violate the one-sentence constraint. | Preserve the `one_sentence = false` result. |

## Before and after

The values below compare the prior `scorers-1.1.0` result with the final additive `scorers-1.2.0` result. A pair is shown as `deterministic / constraint`.

| Source | Run ID | CODE-01 | REAS-01 | WRITE-02 | CTX-01 |
|---|---|---:|---:|---:|---:|
| GPT-5.6 R1 | `20260922T210505Z-666f0e58c7` | 1.000 / n/a -> 1.000 / n/a | 1.000 / n/a -> 1.000 / n/a | n/a / 1.000 -> n/a / 1.000 | 1.000 / 1.000 -> 1.000 / 1.000 |
| GPT-5.6 R2 | `20260922T212837Z-09b6935a04` | 1.000 / n/a -> 1.000 / n/a | 1.000 / n/a -> 1.000 / n/a | n/a / 1.000 -> n/a / 1.000 | 1.000 / 0.000 -> 1.000 / 0.000 |
| GPT-6 R1 | `20260922T221739Z-eb57b67d06` | 0.667 / n/a -> 1.000 / n/a | 0.000 / n/a -> 1.000 / n/a | n/a / 0.667 -> n/a / 1.000 | 1.000 / 1.000 -> 1.000 / 1.000 |
| GPT-6 R2 | `20260922T223440Z-c5ae59da51` | 1.000 / n/a -> 1.000 / n/a | 1.000 / n/a -> 1.000 / n/a | n/a / 1.000 -> n/a / 1.000 | 1.000 / 0.000 -> 1.000 / 0.000 |

`n/a` means the frozen scorer declares no mechanical component for that task, not zero. GPT-5.6 Luna Repeat 1 REAS-02 remains a terminal execution `ERROR` and is not scored as an incorrect response.

## Freeze decision

The three changes above are robustness fixes only. They do not alter answer keys, task prompts, rubric criteria, or the meaning of any score. `scorers-1.2.0` is frozen for the final aggregation. The original `scorers-1.1.0` artifacts and immutable raw captures are retained.

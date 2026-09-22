# GPT-5.6 Luna vs GPT-6 Luna

*A frozen 30-task, 120-generation comparison through Codex CLI*

**GPT-6 Luna got faster. GPT-5.6 Luna still scored higher.**

We captured GPT-5.6 Luna before it disappeared, froze the benchmark, and ran the same 30 tasks twice against GPT-6 Luna.

This repository is a bounded comparison of **GPT-5.6 Luna** and **GPT-6 Luna** as exposed through Codex CLI authenticated via ChatGPT OAuth. Requested model slugs were `gpt-5.6-luna` and `gpt-6-luna`. Provider-returned model identity was **not_exposed**. Equivalence to a ChatGPT model-picker label is **unverified**. Frozen benchmark: **luna-comparison-v1.0**.

The longer write-up is in [article/draft.md](article/draft.md). Full measurements, task notes, and protocol detail are in [reports/full-report.md](reports/full-report.md).

## Result summary

Across 30 frozen task designs and two repeats per requested model (120 primary executions), GPT-5.6 Luna’s overall capability score was **0.9064** and GPT-6 Luna’s was **0.8616**. GPT-5.6 had a **1.67%** error rate (one ERROR on Repeat 1 REAS-02; no response was fabricated). GPT-6 had **0%** errors. GPT-6 was faster on mean, median, and P90 latency, and used fewer pooled tokens. Pairwise judging of 59 pairs gave GPT-5.6 23 wins, GPT-6 14 wins, and 22 ties. One pair was skipped because of the REAS-02 execution error.

These are scores on this frozen set. The design is small (30 tasks, two repeats). No statistical-significance claim is supported. Broad categories are not measures of intelligence or general capability.

## Headline measurements

| Measure | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| Overall capability | 0.9064 | 0.8616 |
| Error rate | 1.67% | 0% |
| Mean latency | 16,833.6 ms | 7,619.0 ms |
| Median latency | 8,670.0 ms | 6,020.2 ms |
| P90 latency | 42,791.2 ms | 14,189.0 ms |
| Input tokens, pooled | 884,792 | 775,607 |
| Output tokens, pooled | 25,652 | 12,245 |
| Total tokens, pooled | 910,444 | 787,852 |

## Category capability

| Category | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| AGENT | 0.9658 | 0.8034 |
| CODE | 0.8473 | 0.7938 |
| CTX | 0.9280 | 0.7720 |
| EVID | 0.8928 | 0.9110 |
| EXTR | 0.9318 | 0.9068 |
| REAS | 0.9592 | 0.8838 |
| WRITE | 0.8333 | 0.9848 |

GPT-6 scored higher on EVID and WRITE. GPT-5.6 scored higher on AGENT, CODE, CTX, EXTR, and REAS.

## Pairwise result

Semantic/pairwise judge: requested `gpt-6-sol` through the same transport (Codex CLI 0.156.0). Judge identity was not exposed. Same-vendor judge bias is possible.

| Outcome | Count |
|---|---:|
| Pairs judged | 59 |
| GPT-5.6 Luna wins | 23 |
| GPT-6 Luna wins | 14 |
| Ties | 22 |
| Skipped (GPT-5.6 Repeat 1 REAS-02 ERROR) | 1 |

## Latency comparison

GPT-6 Luna’s mean latency was 7,619.0 ms versus 16,833.6 ms for GPT-5.6 Luna. Median: 6,020.2 ms vs 8,670.0 ms. P90: 14,189.0 ms vs 42,791.2 ms. Pooled output tokens were 12,245 vs 25,652.

GPT-5.6 capture used Codex CLI **0.153.4**; GPT-6 capture used **0.156.0**. Latency and token counts are end-to-end observations and cannot be attributed solely to model architecture. Token counts include Codex transport and context overhead.

## Benchmark design

Thirty task designs: CODE (6), REAS (5), EVID (5), EXTR (4), AGENT (4), CTX (3), WRITE (3). Two repeats per requested model; 120 primary executions.

Named mean capability deltas (averaged across two repeats), from the final report:

**GPT-6 higher than GPT-5.6**

- **CODE-04 (+0.3571):** one PostgreSQL query with filtered 2026 completed-order aggregates, keep customers with zero qualifying orders, sort.
- **EVID-05 (+0.1818):** bounded assessment of controlled benchmark evidence, an independent replication, a developer’s subjective claim, and a single production report.
- **WRITE-01 (+0.1818):** 90–120 word factual executive update that avoids declaring a winner and explains why deployment is premature.
- **WRITE-02 (+0.1818):** concise quantization-tradeoff explanation without a significance or overall-superiority claim.

**GPT-6 lower than GPT-5.6**

- **CODE-02 (−0.6786):** concurrent async requests, input-order preservation, cancel unfinished work, propagate original exceptions, validate.
- **AGENT-02 (−0.3377):** five ordered deployment actions that restore service first, preserve diagnostic evidence, and do not continue rollout while investigating.
- **CTX-02 (−0.3182):** explain a latency incident from a complete timeline; identify the early hypothesis later evidence weakens.
- **REAS-05 (−0.2208):** ranked diagnostic actions and the hypothesis each tests in a localhost/remote-timeout incident.

## Scoring methodology

Final scorer: **scorers-1.2.0**. Frozen prompts, answer keys, and scoring definitions. Independent sessions. No retries for model-quality failures. One GPT-5.6 Repeat 1 REAS-02 execution was an ERROR and was handled as missing/error.

CTX-01 had a genuine one-sentence constraint failure in GPT-5.6 Repeat 2 and GPT-6 Repeat 2. The scorer audit preserved those failures; they are not a parser bug.

## Repeat methodology

Repeats are two observations of the same 30 designs, not independent task samples.

- GPT-5.6: 29/30 pairs with both capability scores; exact agreement 65.5%; MAD 0.0445.
- GPT-6: 30/30 pairs; exact agreement 53.3%; MAD 0.0877.

## Transport and judge caveats

Same transport family: Codex CLI with ChatGPT OAuth, fresh ephemeral sessions and temporary directories, read-only sandbox, disabled web/tools/memories, ignored user config/rules, no repository context.

CLI versions differed (0.153.4 vs 0.156.0). Judge requested `gpt-6-sol`; identity not exposed; same-vendor bias possible. Provider-returned model identity: not_exposed. Picker-label equivalence: unverified.

## Repository structure

Public repository: **luna-5.6-vs-6-benchmark**.

- [reports/full-report.md](reports/full-report.md) — full report
- [article/draft.md](article/draft.md) — article draft
- [figures/](figures/) — publication figures and captions
- [methodology/](methodology/) — protocol and scorer audit
- [benchmark/](benchmark/) — frozen prompts, answer keys, and manifest
- [results/](results/) — machine-readable scores, performance, and pairwise tables
- [artifacts/](artifacts/) — sanitized capture, scoring, and judge artifacts

## Reproducibility

Canonical runs:

- `20260922T210505Z-666f0e58c7`
- `20260922T212837Z-09b6935a04`
- `20260922T221739Z-eb57b67d06`
- `20260922T223440Z-c5ae59da51`

Protocol: frozen prompts/keys/scoring; independent sessions; no quality retries; isolation as above.

## Artifact provenance

Raw executions were preserved, including the REAS-02 ERROR. Scorer **scorers-1.2.0**. Semantic/pairwise judge via Codex CLI 0.156.0 requesting `gpt-6-sol`.

## Frozen benchmark SHA

**luna-comparison-v1.0**
SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`

## Citation note

Cite this as a bounded Codex CLI comparison of requested slugs `gpt-5.6-luna` and `gpt-6-luna` on frozen benchmark **luna-comparison-v1.0** (SHA-256 above). Do not treat scores as a general ranking, a ChatGPT picker-label result, or a statistically significant difference. See [reports/full-report.md](reports/full-report.md) and [article/draft.md](article/draft.md).

# GPT-6 Luna got faster. GPT-5.6 Luna still scored higher.

## We captured GPT-5.6 Luna before it disappeared, froze the benchmark, and ran the same 30 tasks twice against GPT-6 Luna.

This lab compared two requested model slugs — `gpt-5.6-luna` and `gpt-6-luna` — as they were actually reached through Codex CLI authenticated with ChatGPT OAuth. The comparison is bounded. It is not a ranking of ChatGPT product labels, not a claim about general intelligence, and not a statistical test. The frozen pack is `luna-comparison-v1.0`. Provider-returned model identity was `not_exposed`. Equivalence to any ChatGPT model-picker label is unverified.

We ran the work because GPT-5.6 Luna was leaving the surface we could still reach. If a later reader wants to know how that snapshot behaved next to GPT-6 Luna on the same prompts, the only honest option is a frozen task set, independent sessions, and preserved raw artifacts. That is what this article reports.

## What was tested

The pack contains 30 task designs:

- CODE: 6
- REAS: 5
- EVID: 5
- EXTR: 4
- AGENT: 4
- CTX: 3
- WRITE: 3

Each requested model was run twice. That is 120 primary task executions. One of those executions failed: GPT-5.6 Repeat 1 on REAS-02 returned an ERROR. No substitute response was invented. The scorer treated it as missing/error. The final scorer was `scorers-1.2.0`.

Canonical run IDs:

- `20260922T210505Z-666f0e58c7`
- `20260922T212837Z-09b6935a04`
- `20260922T221739Z-eb57b67d06`
- `20260922T223440Z-c5ae59da51`

Semantic and pairwise judging used requested `gpt-6-sol` on the same transport family, Codex CLI 0.156.0. Judge identity was not exposed. Same-vendor judge bias is possible and is not ruled out.

The benchmark SHA-256 is `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`.

## Fairness controls

Prompts, answer keys, and scoring definitions were frozen. Sessions were independent. Model-quality failures were not retried.

Both captures used the same isolation approach: Codex CLI with ChatGPT OAuth, fresh ephemeral sessions, temporary directories, a read-only sandbox, disabled web/tools/memories, ignored user config and rules, and no repository context.

The CLI versions were not identical. GPT-5.6 capture used Codex CLI 0.153.4. GPT-6 capture used 0.156.0. Latency and token counts are therefore end-to-end observations of model plus transport. They cannot be attributed solely to model architecture. Token counts include Codex transport and context overhead.

These controls make the two series comparable as CLI-exposed snapshots. They do not make the series equivalent to ChatGPT UI behavior, and they do not cancel judge-vendor overlap.

## Headline results

On overall capability, GPT-5.6 Luna scored 0.9064. GPT-6 Luna scored 0.8616.

Error rate was 1.67% for GPT-5.6 Luna and 0% for GPT-6 Luna. The GPT-5.6 error rate is the single REAS-02 Repeat 1 execution error already noted.

Latency, end to end:

| Measure | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| Mean | 16,833.6 ms | 7,619.0 ms |
| Median | 8,670.0 ms | 6,020.2 ms |
| P90 | 42,791.2 ms | 14,189.0 ms |

GPT-6 Luna was substantially faster on mean, median, and P90. The mean gap is larger than the median gap, which is consistent with a heavier GPT-5.6 tail (P90 42,791.2 ms versus 14,189.0 ms). That is a latency observation under two CLI versions, not a proof of architectural speed.

Pooled tokens:

| | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| Input | 884,792 | 775,607 |
| Output | 25,652 | 12,245 |
| Total | 910,444 | 787,852 |

GPT-6 Luna used fewer pooled tokens, with the largest relative drop on output (12,245 versus 25,652). Shorter output is not automatically better. Some tasks reward completeness; WRITE tasks in this pack also penalize overclaiming. Token totals include transport overhead, so they are not a clean measure of “model verbosity” alone.

Pairwise judging covered 59 pairs. GPT-5.6 Luna won 23, GPT-6 Luna won 14, and 22 were ties. One pair was skipped because GPT-5.6 Repeat 1 REAS-02 was an execution error. Pairwise preference therefore tracks the capability gap in direction — more GPT-5.6 wins than GPT-6 wins, with a large tie mass — without turning the table into a tournament ranking.

None of these headline numbers support a significance claim. There are 30 designs and two repeats per model.

## Category scores are uneven

Broad category averages:

| Category | GPT-5.6 Luna | GPT-6 Luna |
|---|---:|---:|
| AGENT | 0.9658 | 0.8034 |
| CODE | 0.8473 | 0.7938 |
| CTX | 0.9280 | 0.7720 |
| EVID | 0.8928 | 0.9110 |
| EXTR | 0.9318 | 0.9068 |
| REAS | 0.9592 | 0.8838 |
| WRITE | 0.8333 | 0.9848 |

GPT-6 Luna is higher on WRITE (0.9848 vs 0.8333) and slightly higher on EVID (0.9110 vs 0.8928). GPT-5.6 Luna is higher on AGENT, CODE, CTX, EXTR, and REAS, with the largest category gaps on AGENT (0.9658 vs 0.8034) and CTX (0.9280 vs 0.7720).

That split is the actual story. GPT-6 Luna is not “worse at everything.” GPT-5.6 Luna is not “better at everything.” Category labels are also not comprehensive measures of intelligence. AGENT here is four tasks. WRITE is three. A 0.15 swing on a three-task bucket is a local result, not a personality of the model family.

## Named task changes

The final report’s mean capability deltas, averaged across the two repeats, identify four improvements and four regressions for GPT-6 relative to GPT-5.6.

**Improvements (GPT-6 minus GPT-5.6):**

- **CODE-04, +0.3571.** One PostgreSQL query: filtered 2026 completed-order aggregates, keep customers with zero qualifying orders, and sort. This is the largest named gain.
- **EVID-05, +0.1818.** Bounded assessment of controlled benchmark evidence, an independent replication, a developer’s subjective claim, and a single production report. The task rewards source discipline, not a winner declaration.
- **WRITE-01, +0.1818.** A 90–120 word factual executive update that avoids declaring a winner and explains why deployment is premature.
- **WRITE-02, +0.1818.** A concise explanation of a quantization tradeoff without a significance claim or an overall-superiority claim.

Those WRITE gains match the category table. GPT-6 Luna was better, on this pack, at staying inside a constrained factual register.

**Regressions (GPT-6 minus GPT-5.6):**

- **CODE-02, −0.6786.** Concurrent async requests, preserve input order, cancel unfinished work, propagate the original exception, and validate. This is the largest named drop, and it sits inside a CODE category that is still mixed because CODE-04 moved the other way.
- **AGENT-02, −0.3377.** Five ordered deployment actions: restore service first, preserve diagnostic evidence, and do not continue rollout while investigating.
- **CTX-02, −0.3182.** Explain a latency incident from a complete timeline and identify the early hypothesis later evidence weakens.
- **REAS-05, −0.2208.** Rank diagnostic actions and name the hypothesis each action tests in a localhost/remote-timeout incident.

The regression cluster is operational: concurrency and cancellation, incident sequencing, evidence that arrives late, and diagnostic ranking. The improvement cluster is mixed: one SQL aggregation task, one evidence-bounded assessment, and two writing tasks that forbid overclaim.

A reader who wants a single winner has to ignore that split. We are not going to ignore it.

## Repeat variance

Repeats are repeated observations of the same 30 designs, not independent task samples. Do not treat two repeats as a new draw from some larger task universe.

GPT-5.6 Luna: 29 of 30 task pairs produced both capability scores (REAS-02 Repeat 1 missing). Exact agreement 65.5%. Mean absolute difference 0.0445.

GPT-6 Luna: 30 of 30 pairs produced both scores. Exact agreement 53.3%. Mean absolute difference 0.0877.

GPT-6 Luna was less stable across repeats on this pack: lower exact agreement and nearly double MAD. That does not by itself explain the overall capability gap, and it does not license averaging the two models into one “true” score. It does mean a one-shot demo of either slug is a weak substitute for these paired runs.

CTX-01 had a genuine one-sentence constraint failure in GPT-5.6 Repeat 2 and GPT-6 Repeat 2. The scorer audit preserved those failures. This is not a parser bug. Treating it as a parser bug would inflate both models and hide a real constraint miss.

## What the measurements support, and what they do not

They support these statements, and only these:

1. On `luna-comparison-v1.0`, with two repeats, scorer `scorers-1.2.0`, and the four canonical runs named above, GPT-5.6 Luna’s overall capability (0.9064) exceeded GPT-6 Luna’s (0.8616).
2. GPT-6 Luna was faster on mean, median, and P90 latency in this capture, and used fewer pooled tokens, especially output tokens.
3. Pairwise preference, 59 judged pairs, favored GPT-5.6 Luna 23–14 with 22 ties, after skipping the error pair.
4. Capability change is task-local: CODE-04, EVID-05, WRITE-01, and WRITE-02 improved for GPT-6; CODE-02, AGENT-02, CTX-02, and REAS-05 declined.
5. Repeat MAD was higher for GPT-6 Luna (0.0877 vs 0.0445).
6. One GPT-5.6 execution was an ERROR; GPT-6 had a 0% error rate on the 60 executions in its two repeats.

They do not support:

- Statistical significance.
- Equivalence to a ChatGPT picker name.
- Attribution of latency or tokens to model architecture alone (CLI 0.153.4 vs 0.156.0; transport overhead included).
- A claim that either model is generally more capable, more careful, or more “agentic.”
- Treating category averages as intelligence subscales.
- Treating the pairwise judge as vendor-neutral. Requested judge was `gpt-6-sol`; identity not exposed; same-vendor bias remains possible.
- Filling in the missing REAS-02 response.

Deployment decisions need more than 30 frozen designs. This pack is a snapshot comparison, not a release gate.

## Why the raw artifacts were preserved

The interesting failure modes here are easy to erase by “helpfulness.”

If REAS-02 Repeat 1 had been retried until a completion appeared, the error rate would have been cosmetic. If CTX-01’s one-sentence constraint misses had been blamed on the parser, both models would look cleaner than they were. If only category averages were kept, CODE-04’s gain and CODE-02’s collapse would cancel into a mild CODE story. If pairwise ties were dropped, 22 of 59 judgments would vanish.

Artifacts exist so a later reader can re-score with `scorers-1.2.0`, inspect the ERROR, re-read the pairwise skip, and check the four canonical run IDs against the frozen SHA-256. We are not asking anyone to trust a narrative that replaced the files.

The public release keeps the frozen tasks, raw responses, scoring tables, judge artifacts, methodology, and generated figures together in the [publication repository](https://github.com/majorminorlabs/research-luna-5.6-vs-6).

The files also lock the scope: Codex CLI, ChatGPT OAuth, requested slugs `gpt-5.6-luna` and `gpt-6-luna`, identity `not_exposed`. Anyone who maps this article onto a ChatGPT UI label is making a claim this capture did not make.

## Closing

GPT-6 Luna, as reached here, completed the 30-task pack twice with no execution errors, lower latency, and shorter pooled output. GPT-5.6 Luna scored higher overall, won more pairwise judgments than it lost, and held large leads on several operational tasks, while losing ground on constrained writing and one SQL aggregation task.

That is a tradeoff measured on a small frozen pack, not a coronation. GPT-5.6 Luna is gone from this surface. The comparison is the record we could still make: same 30 designs, two repeats, independent sessions, and the artifacts left in place.

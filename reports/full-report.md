# GPT-5.6 Luna vs GPT-6 Luna comparison

This comparison measures GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth. It does not establish direct equivalence to the ChatGPT model picker; picker equivalence is unverified and provider-returned model identity is `not_exposed`.

Benchmark: `luna-comparison-v1.0`
Benchmark SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`
Final scorer: `scorers-1.2.0`
Primary generations represented: `120` across four canonical runs.

## Overall capability results

The primary capability score is the arithmetic mean of the per-task normalized scores. For each task, only applicable components are included and their preregistered weights are renormalized. Missing and non-applicable components are not treated as zero.

| Model | Capability | Deterministic | Rubric | Constraints | Pairwise | Error rate |
|---|---:|---:|---:|---:|---:|---:|
| gpt-5.6-luna | 0.9064 | 1.0000 | 0.9829 | 0.9615 | 0.5763 | 0.0167 |
| gpt-6-luna | 0.8616 | 1.0000 | 0.9243 | 0.9615 | 0.4237 | 0.0000 |

## Category results

| Model | Category | Capability | Deterministic | Rubric | Constraints | Pairwise |
|---|---|---:|---:|---:|---:|---:|
| gpt-5.6-luna | AGENT | 0.9658 | 1.0000 | 0.9643 | 1.0000 | 0.8750 |
| gpt-5.6-luna | CODE | 0.8473 | 1.0000 | 0.9484 | n/a | 0.5000 |
| gpt-5.6-luna | CTX | 0.9280 | 1.0000 | 1.0000 | 0.8333 | 0.6667 |
| gpt-5.6-luna | EVID | 0.8928 | 1.0000 | 1.0000 | 1.0000 | 0.4500 |
| gpt-5.6-luna | EXTR | 0.9318 | 1.0000 | 1.0000 | 1.0000 | 0.6250 |
| gpt-5.6-luna | REAS | 0.9592 | 1.0000 | 1.0000 | 1.0000 | 0.7778 |
| gpt-5.6-luna | WRITE | 0.8333 | n/a | 1.0000 | 1.0000 | 0.0833 |
| gpt-6-luna | AGENT | 0.8034 | 1.0000 | 0.8790 | 1.0000 | 0.1250 |
| gpt-6-luna | CODE | 0.7938 | 1.0000 | 0.8770 | n/a | 0.5000 |
| gpt-6-luna | CTX | 0.7720 | 1.0000 | 0.7500 | 0.8333 | 0.3333 |
| gpt-6-luna | EVID | 0.9110 | 1.0000 | 1.0000 | 1.0000 | 0.5500 |
| gpt-6-luna | EXTR | 0.9068 | 1.0000 | 1.0000 | 1.0000 | 0.3750 |
| gpt-6-luna | REAS | 0.8838 | 1.0000 | 0.9857 | 1.0000 | 0.2222 |
| gpt-6-luna | WRITE | 0.9848 | n/a | 1.0000 | 1.0000 | 0.9167 |

## Blind pairwise preference

Judged pairs: `59`. GPT-5.6 Luna W/L/T: `23/14/22`. GPT-6 Luna W/L/T: `14/23/22`.

The GPT-5.6 Luna Repeat 1 REAS-02 execution was an ERROR. It was excluded from pairwise judging and no response was fabricated.

## Repeat consistency

See `repeat_consistency.csv` for component-level exact agreement and mean absolute differences across the two repeats. The two repeats are repeated observations of the same 30 task designs, not independent task samples.

| Model | Component | Both scored | Exact agreement | Mean absolute difference |
|---|---|---:|---:|---:|
| gpt-5.6-luna | capability_score | 29 | 0.6552 | 0.0445 |
| gpt-5.6-luna | deterministic_score | 11 | 1.0000 | 0.0000 |
| gpt-5.6-luna | rubric_score | 26 | 1.0000 | 0.0000 |
| gpt-5.6-luna | constraints_score | 13 | 0.9231 | 0.0769 |
| gpt-5.6-luna | pairwise_score | 29 | 0.6552 | 0.2241 |
| gpt-6-luna | capability_score | 30 | 0.5333 | 0.0877 |
| gpt-6-luna | deterministic_score | 12 | 1.0000 | 0.0000 |
| gpt-6-luna | rubric_score | 27 | 0.8519 | 0.0782 |
| gpt-6-luna | constraints_score | 13 | 0.9231 | 0.0769 |
| gpt-6-luna | pairwise_score | 29 | 0.6552 | 0.2241 |

## End-to-end performance

Performance is reported separately from capability and is not attributed solely to model architecture. GPT-5.6 Luna used Codex CLI 0.153.4; GPT-6 Luna used Codex CLI 0.156.0. Token counts include Codex transport/context overhead.

| Model | Mean latency ms | Median | P90 | Min | Max | Mean input tokens | Mean output tokens | Mean total tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gpt-5.6-luna | 16833.6 | 8670.0 | 42791.2 | 3619.5 | 120010.8 | 14996.5 | 434.8 | 15431.3 |
| gpt-6-luna | 7619.0 | 6020.2 | 14189.0 | 3367.6 | 24257.4 | 12926.8 | 204.1 | 13130.9 |

## Largest replicated changes

Replicated improvements across both repeats:

- `CODE-04` (CODE): mean capability delta `+0.3571` (Repeat 1 `+0.3571`, Repeat 2 `+0.3571`).
- `EVID-05` (EVID): mean capability delta `+0.1818` (Repeat 1 `+0.1818`, Repeat 2 `+0.1818`).
- `WRITE-01` (WRITE): mean capability delta `+0.1818` (Repeat 1 `+0.1818`, Repeat 2 `+0.1818`).
- `WRITE-02` (WRITE): mean capability delta `+0.1818` (Repeat 1 `+0.1818`, Repeat 2 `+0.1818`).

Replicated regressions across both repeats:

- `CODE-02` (CODE): mean capability delta `-0.6786` (Repeat 1 `-1.0000`, Repeat 2 `-0.3571`).
- `AGENT-02` (AGENT): mean capability delta `-0.3377` (Repeat 1 `-0.3377`, Repeat 2 `-0.3377`).
- `CTX-02` (CTX): mean capability delta `-0.3182` (Repeat 1 `-0.3182`, Repeat 2 `-0.3182`).
- `REAS-05` (REAS): mean capability delta `-0.2208` (Repeat 1 `-0.1818`, Repeat 2 `-0.2597`).
- `AGENT-01` (AGENT): mean capability delta `-0.2121` (Repeat 1 `-0.1818`, Repeat 2 `-0.2424`).

## Interpretation limits

No forced overall winner is declared. No statistical significance claim is made. The report supports only observations on this frozen 30-task distribution, under the stated Codex transports and CLI versions. It does not establish universal capability, causal architectural explanations, or equivalence with the ChatGPT model picker.

Detailed methodology and limitations are in [reports/methodology-limitations.md](methodology-limitations.md); machine-readable data are in [results/results.json](../results/results.json) and the CSV artifacts.

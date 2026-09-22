# Methodology

## Scope and freeze

`luna-comparison-v1.0` contains exactly 30 permanently ordered JSONL task records. `benchmark/tasks.jsonl` is the benchmark source of truth; `benchmark/answer_keys.json` contains deterministic answers and task-specific rubrics. `benchmark/manifest.json` binds the benchmark version to SHA-256 hashes. Any task correction after a model run would require a new benchmark version and would invalidate affected comparisons.

The benchmark is intentionally small. It uses standard-library validation and does not depend on an evaluator model for deterministic facts. Raw model output is never used to modify tasks or answer keys.

## Pre-freeze validation

The validator independently enumerates REAS-01 and REAS-04, calculates REAS-02, executes the canonical CODE-03 behavior against its supplied example, parses exact JSON keys, checks the extraction constraints, and verifies the fixed long-context filler. REAS-01 originally was not unique: Bea and Cole could swap W and Z. Before any model execution, the task was repaired by adding the single constraint `Cole did not run Z`, producing the unique assignment Arin-Y, Bea-Z, Cole-W, Dara-X. This is the only task correction in v1.0.

## Run protocol

Every run gets a new UTC run ID and a new directory. The runner refuses to reuse a run directory. It writes every request attempt, terminal response, deterministic score, provider error, raw provider execution, metadata record, and summary. A complete run has exactly one terminal response per task, including failures; silent omission is invalid. Codex CLI runs default to zero retries; only explicitly configured retryable provider/transport failures are retried. A response caused by the model itself is not retried as a quality failure.

The metadata records:

- benchmark and answer-key hashes;
- Git commit and dirty state when the checkout is a Git repository;
- requested model and exact returned model identifier, or `not_exposed`;
- provider/interface and non-secret configuration identifiers;
- UTC times, system prompt, rendered user prompts, and generation controls;
- latency, token counts, finish reason, retries, errors, and truncation.

Automated runs additionally write `raw_execution.jsonl`, which preserves the complete provider execution trace separately from the normalized terminal response.

## Codex CLI transport qualification

The qualified automated path measures `gpt-5.6-luna as exposed through Codex CLI authenticated via ChatGPT OAuth`. It does not establish equivalence with the ChatGPT Luna picker. The adapter records:

- `requested_model: gpt-5.6-luna`;
- `transport: codex-cli-chatgpt-oauth`;
- `provider_returned_model: not_exposed`;
- `chatgpt_picker_equivalence: unverified`;
- Codex CLI version and the non-secret command/configuration used.

Each task is an independent `codex exec` invocation with `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--skip-git-repo-check`, `--sandbox read-only`, `--json`, and `--output-last-message`. The process runs in a fresh temporary directory outside the benchmark repository. The only task-specific input sent to the model is the exact frozen task prompt; runner metadata and answer keys are not forwarded. The child environment removes inherited Codex app/thread/session variables and API-key environment variables while retaining the authenticated Codex store needed for ChatGPT OAuth.

The final answer is extracted from the exact bytes written by `--output-last-message`. JSONL stdout and stderr are retained without using status events, reasoning events, tool traces, or wrapper metadata as the benchmark response. The adapter refuses non-target model slugs, refuses a benchmark system prompt, rejects generation controls not exposed by Codex CLI, and does not retry inside the adapter. Runner infrastructure retries are opt-in.

Before any frozen prompt is eligible for this path, `src/codex_cli_probe.py` runs three synthetic probes: a factual response, constrained JSON, and a small coding response. The qualification recorded on 2026-09-22 passed all three with exact requested-model checks, distinct isolated directories, exact final-answer extraction, no shell/web/MCP/file tool events, and exposed usage counts. The raw synthetic evidence was stored outside `runs/` at `<synthetic-probe-dir>
Unavailable interface controls are recorded as `not_exposed`, never guessed. API keys are read from the named environment variable and are not written to artifacts.

## Manual ChatGPT capture

Manual capture is the fallback when the ChatGPT subscription interface does not expose a verifiable provider model ID through an approved programmatic path. It records `provider` and `interface` as `chatgpt-manual`, records the user-supplied display label as `model_requested`, and records `exact_model_identifier_returned` and UI-only generation controls as `not_exposed`. The task prompt is printed from the frozen JSONL record; it is not reconstructed or normalized. Terminal input is accumulated line-by-line until a run/task-specific terminator and the resulting string is written unchanged as `response_text`.

Manual runs create the normal `metadata.json`, `requests.jsonl`, `responses.jsonl`, `scores.jsonl`, `errors.jsonl`, and final `summary.json`. Metadata and JSONL files are created without overwriting. An interrupted run has no final summary and can resume from the existing response IDs. Resume skips completed tasks and validates the benchmark hash. Explicit duplicate capture is allowed only with both a selected task ID and `--override-duplicate`; it is append-only in `duplicate_responses.jsonl` and never replaces the primary terminal response.

`export-prompts` writes one new file containing all prompts in task order with visible delimiters. The delimiters are export framing; the bytes between each prompt marker are the stored prompt content. This is a convenience for copy/paste and is not a new benchmark artifact.

## Score architecture

The final capability score is outcome-first:

| Component | Weight | Use |
|---|---:|---|
| Objective/deterministic correctness | 45% | Exact answers and mechanical checks where the outcome is observable |
| Task-specific rubric | 30% | Criteria tailored to the task rather than a generic quality score |
| Constraint compliance | 15% | Requested format, length, scope, and safety constraints |
| Blind pairwise preference | 10% | A configured judge compares de-identified responses |

Latency, input tokens, output tokens, total tokens, error rate, and truncation rate are reported separately. They are not capability points. For each task, only applicable components with valid scores are included and their preregistered weights are renormalized to sum to one. Missing and non-applicable components are not treated as zero. Overall and category capability scores are arithmetic means of per-task normalized scores, with component averages and applicable counts reported separately. A terminal execution error has no correctness or constraint score and is reported separately as an error.

Exact tasks use strict JSON or mechanical matching. Open tasks keep their own rubric: examples include cancellation and exception propagation for CODE-02, evidence discipline for EVID-01, rollback preservation for AGENT-01, and factual preservation for WRITE-03. Multiple technically defensible answers can receive credit when they satisfy the observable rubric.

## Blind judging

The final judge is requested as `gpt-6-sol` through `codex-cli-chatgpt-oauth`, using Codex CLI `0.156.0`. Before any benchmark judging, synthetic non-benchmark probes verify model acceptance, generation, final-answer extraction, JSON/schema compliance, isolated invocation, no tool events, and no repository context. Each judge invocation then uses a fresh ephemeral process in a fresh temporary directory with read-only sandbox, disabled web/tools/memories, ignored user configuration/rules, and no repository context.

For rubric judging, the prompt contains only the task prompt, task-specific rubric, relevant expected concepts/reference, and one anonymous response. It excludes model identity, run ID, repeat, deterministic score, latency, tokens, comparison responses, and previous decisions. Rubric order uses a stored fixed seed. For pairwise judging, the prompt contains only the task, task-specific rubric, Response A, and Response B; a separate stored mapping records which source was assigned A/B. The accepted pairwise winner is exactly `A`, `B`, or `TIE`; the exact prompt, raw provider execution, raw final response, parsed result, requested judge model, provider-returned identity, Codex version, latency, and token counts are preserved under `judge_artifacts/`. Substantive schema/content failures are not retried; only explicitly recorded infrastructure retries are permitted.

The canonical four-run comparison is described as GPT-5.6 Luna vs GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth. Provider-returned capture identity remains `not_exposed`, and equivalence to the ChatGPT model picker is `unverified`.

## Statistical and interpretive limits

The 30 frozen tasks are a measured suite, not a population claim. One run per model is sufficient for the urgent Luna 5.6 capture, while a second repeat is desirable if access permits. No statistical significance claim is made unless an appropriate test is actually calculated from the available repeated observations. A score difference alone does not establish real-world capability, causality, or universal superiority.

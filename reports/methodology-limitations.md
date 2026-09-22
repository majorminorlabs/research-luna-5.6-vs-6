# Methodology and limitations for the completed comparison

## Frozen inputs and primary evidence

- Benchmark: `luna-comparison-v1.0` with task SHA-256 `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`.
- Canonical runs: `20260922T210505Z-666f0e58c7, 20260922T212837Z-09b6935a04, 20260922T221739Z-eb57b67d06, 20260922T223440Z-c5ae59da51`.
- Primary generations: `120`. Smoke/probe generations are excluded from this count.
- Final scorer: `scorers-1.2.0`. The four raw run directories and their captured responses are not modified by rescoring or judging.
- Comparison labels are GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth.
- Provider-returned model identity is `not_exposed`; equivalence to the ChatGPT model picker is `unverified`.

## Aggregation

The preregistered component weights are deterministic/objective correctness 45%, task-specific rubric 30%, constraint compliance 15%, and blind pairwise preference 10%.

For each model, repeat, and task, only components that apply to that task and have a valid score are included. The applicable preregistered weights are renormalized to sum to one for that task. Missing or non-applicable components are not assigned zero. The overall and category capability scores are arithmetic means of those per-task normalized scores; component averages and applicability counts are reported separately.

Terminal execution errors have no correctness or constraint score. They remain in the denominator for generation/error reporting but not in capability-score averages. GPT-5.6 Luna Repeat 1 REAS-02 is the predefined missing-response case and has no fabricated output or pairwise decision.

## Blind rubric judging

- Judge requested model: `gpt-6-sol`.
- Judge transport: `codex-cli-chatgpt-oauth`; Codex version: `codex-cli 0.156.0`.
- Each invocation used a fresh ephemeral Codex CLI session, a fresh temporary working directory outside the repository, read-only sandbox, disabled web and tools, disabled memories, ignored user configuration/rules, and no repository context.
- Rubric prompts contained only the task prompt, frozen task-specific rubric, relevant reference concepts, and an anonymous response. They did not contain model identity, run ID, repeat, deterministic score, latency, tokens, comparison responses, or previous judge decisions.
- Rubric order was randomized with fixed seed `2026092201`. Judged cases: `107`.
- Exact judge prompts, raw provider executions, raw final responses, parsed results, and anonymous mappings are preserved under the judge artifact directory in `results.json`.

## Blind pairwise judging

- Each pair contained the task, its rubric, Response A, and Response B only. A/B assignment was randomized independently per task and repeat with a fixed stored seed.
- Pairwise seed: `2026092202`. Judged pairs: `59`.
- A/B mappings are stored separately from judge prompts and results. Model identities are not exposed to the judge prompt.

## Performance caveat

GPT-5.6 Luna capture used Codex CLI 0.153.4 and GPT-6 Luna capture used Codex CLI 0.156.0. Latency and token differences are end-to-end observations under different transport versions and cannot be attributed solely to model architecture. Token counts include Codex transport/context overhead. Performance is not part of the capability score.

## Statistical and interpretive limits

The two repeats provide repeat-variance evidence but do not turn the 60 observations per model into 60 independent task designs. No statistical significance test was run, so no significance claim is made. Replicated changes are defined as non-zero capability deltas with the same direction in both matched repeats; they are descriptive, not inferential.

Synthetic judge probes are not benchmark tasks and are excluded from all primary counts and scores. No further Luna inference was performed during scoring, judging, or reporting.

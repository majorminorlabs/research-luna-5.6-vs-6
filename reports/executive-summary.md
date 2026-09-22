# Executive summary

This is a bounded comparison of GPT-5.6 Luna and GPT-6 Luna as exposed through Codex CLI authenticated via ChatGPT OAuth on the frozen `luna-comparison-v1.0` benchmark.

- GPT-5.6 Luna capability score: **0.9064**.
- GPT-6 Luna capability score: **0.8616**.
- Blind pairwise: GPT-5.6 Luna `23/14/22` W/L/T; GPT-6 Luna `14/23/22` W/L/T.
- Primary generations: `120`. One GPT-5.6 Luna Repeat 1 execution, REAS-02, was an ERROR and was not fabricated or pairwise judged.

## Replicated changes

Largest replicated improvements:
- `CODE-04`: mean capability delta `+0.3571`.
- `EVID-05`: mean capability delta `+0.1818`.
- `WRITE-01`: mean capability delta `+0.1818`.
Largest replicated regressions:
- `CODE-02`: mean capability delta `-0.6786`.
- `AGENT-02`: mean capability delta `-0.3377`.
- `CTX-02`: mean capability delta `-0.3182`.

## Bottom line

The measurements describe this frozen task distribution and its repeat behavior. They do not justify a universal winner, a causal architecture claim, a statistical significance claim, or direct equivalence to a ChatGPT model-picker label.

Benchmark SHA-256: `ad1fd9a562246f195dc4ce0a14cab02abcd76e868b9f58dbc98fb2e12e77e12d`. Final scorer: `scorers-1.2.0`.

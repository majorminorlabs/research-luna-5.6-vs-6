# Transport and identity

The comparison is described as GPT-5.6 Luna vs GPT-6 Luna as exposed through
Codex CLI authenticated via ChatGPT OAuth. The requested slugs were
`gpt-5.6-luna` and `gpt-6-luna`. The provider did not expose a returned model
identity, so the published value is `not_exposed`. Equivalence to the ChatGPT
model picker is `unverified`.

Both captures used the same transport family and isolation controls: a fresh
ephemeral session per task, a new temporary directory, read-only sandbox,
disabled web/tools/memories, ignored user configuration and rules, and no
repository context. Model-quality failures were not retried.

The Codex CLI versions differed: 0.153.4 for GPT-5.6 Luna and 0.156.0 for
GPT-6 Luna. Latency and token counts are therefore end-to-end observations of
the complete CLI path. Token counts include transport/context overhead and are
not a clean model-only token meter. See [METHODOLOGY.md](METHODOLOGY.md),
[CODEX_CLI_TRANSPORT.md](CODEX_CLI_TRANSPORT.md), and
[LUNA_6_TRANSPORT.md](LUNA_6_TRANSPORT.md) for the detailed qualification
record.

Semantic and pairwise judging requested `gpt-6-sol` through the same transport
using Codex CLI 0.156.0. The judge's returned identity was also not exposed;
same-vendor judge bias remains possible.

# Codex CLI transport qualification

Status: `LUNA_56_CODEX_CAPTURE_READY`

This document qualifies the installed Codex CLI as an automated transport for
the frozen benchmark. It does not start the benchmark and does not establish
that the Codex target is identical to the Luna 5.6 option in the ChatGPT model
picker.

## Identity boundary

The requested model slug is exactly:

```text
gpt-5.6-luna
```

The installed CLI is `codex-cli 0.153.4`. Local Codex diagnostics report the
default provider as OpenAI, the stored authentication mode as ChatGPT, the
configured model as `gpt-5.6-luna`, and no provider-returned server model in the
diagnostic response. The adapter therefore records:

```text
requested_model:             gpt-5.6-luna
transport:                   codex-cli-chatgpt-oauth
provider_returned_model:     not_exposed
chatgpt_picker_equivalence:  unverified
```

The official API catalog independently lists `gpt-5.6-luna` as an API model,
but that page does not establish equivalence between the API model, Codex's
ChatGPT-authenticated route, and the ChatGPT UI picker:

- [GPT-5.6 Luna model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna)

## Verified CLI surface

The adapter uses only interfaces confirmed by the installed `codex exec
--help` and the official non-interactive documentation:

- `--model gpt-5.6-luna` selects the requested slug;
- `-` reads the complete prompt from stdin;
- `--json` emits structured JSONL events;
- `--output-last-message <path>` writes the final agent message separately;
- `--ephemeral` avoids persisted session rollout files;
- `--ignore-user-config` and `--ignore-rules` avoid user/project configuration
  and exec-policy contamination;
- `--skip-git-repo-check` permits an empty temporary directory;
- `--sandbox read-only` and `approval_policy="never"` prevent writable agent
  actions or approval waits;
- `web_search="disabled"` disables web search.

Official references: [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
and [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

## Adapter behavior

`src/runner.py` exposes `--provider codex-cli`. For each task it:

1. creates a new temporary working directory outside the repository;
2. starts a new Codex process and a new ephemeral session;
3. forwards only the exact `user_prompt` string as stdin;
4. strips inherited Codex app/thread/session variables and API-key environment
   variables from the child, while retaining `CODEX_HOME` for the authenticated
     ChatGPT store;
5. disables the locally exposed shell, web, app, browser, computer, image,
   plugin, skill, multi-agent, and memory paths with explicit config overrides;
6. reads `response_text` only from the bytes written by
   `--output-last-message`;
7. preserves the complete emitted JSONL stdout, stderr, command, temporary
   working directory, event summary, and output-file contents in the raw
   provider record;
8. records that raw provider record in both `responses.jsonl` and the separate
   append-only `raw_execution.jsonl` artifact.

For the frozen Luna 5.6 capture, the adapter refuses a model other than
`gpt-5.6-luna`. The prepared Luna 6 path accepts only the separately named
official target `gpt-6-luna`; the current ChatGPT-authenticated route rejects
that target before generation, as documented in `LUNA_6_TRANSPORT.md`. The
adapter refuses a benchmark system prompt, and rejects `temperature`, `top_p`, `seed`, and
`max_output_tokens` because Codex CLI does not expose those controls. An
explicit `--reasoning` value is mapped to the verified
`model_reasoning_effort` configuration key. The adapter never retries. The
runner's `--max-retries N` is the only retry control and must be explicit for
Codex runs; its default is zero for this provider.

## Synthetic contamination qualification

The qualification command is separate from the benchmark runner and does not
load `benchmark/tasks.jsonl`, answer keys, or `runs/`:

```sh
PYTHONPATH=src python3 -m codex_cli_probe \
  --output-dir <synthetic-probe-dir>```

The recorded result passed all three probes:

```text
probe count:                  3
exact requested model:        PASS
provider identity exposed:    NO (correctly recorded not_exposed)
final-answer extraction:      PASS
independent invocations:      PASS
isolated working directories: PASS
shell/web/MCP/file tools:     none observed
usage events:                 present for all three
```

Observed event streams contained `thread.started`, `turn.started`, one
`agent_message` item, and `turn.completed`; no tool item was emitted. The raw
synthetic records remain outside the benchmark run namespace at:

```text
<synthetic-probe-dir>/probes.jsonl
<synthetic-probe-dir>/summary.json
```

No frozen benchmark prompt was sent during qualification.

## Commands for the benchmark

Do not run either command until capture is explicitly authorized. The first is
the requested three-task smoke only:

```sh
PYTHONPATH=src python3 -m runner run \
  --model gpt-5.6-luna \
  --provider codex-cli \
  --max-retries 0 \
  --task-id CODE-01 \
  --task-id REAS-02 \
  --task-id EXTR-01
```

Complete 30-task capture:

```sh
PYTHONPATH=src python3 -m runner run \
  --model gpt-5.6-luna \
  --provider codex-cli \
  --max-retries 0
```

Each completed run should be verified before any Luna 6 work begins:

```sh
PYTHONPATH=src python3 -m runner verify-run --run-dir runs/<run-id>
```

These commands request the target slug through Codex CLI. They do not label
the result as a ChatGPT UI picker capture.

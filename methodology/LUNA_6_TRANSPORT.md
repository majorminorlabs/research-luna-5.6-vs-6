# Luna 6 transport and capture record

Status on 2026-09-22: `gpt-6-luna` is the exact requested Luna 6 slug in the
official OpenAI model catalog. An earlier `codex-cli 0.153.4` ChatGPT OAuth
probe rejected it before generation; after the route became available through
`codex-cli 0.156.0`, both canonical Luna 6 repeats completed successfully.

Evidence:

- Official API catalog: [GPT-6 Luna](https://developers.openai.com/api/docs/models)
  lists model ID `gpt-6-luna`.
- `codex-cli 0.153.4 doctor` reports the OpenAI provider, stored ChatGPT auth,
  no stored API key, and no provider-returned server model.
- The earlier synthetic, non-benchmark invocation using the same isolated
  Codex CLI transport, `gpt-6-luna`, ChatGPT auth, read-only sandbox,
  ephemeral session, disabled tools, and no retries returned:

  ```text
  The 'gpt-6-luna' model is not supported when using Codex with a ChatGPT account.
  ```

- That earlier probe emitted no final answer and sent zero frozen benchmark
  prompts. Its redacted summary is preserved in `reports/luna6_transport_probe.json`.
- The two successful canonical run IDs are `20260922T221739Z-eb57b67d06` and
  `20260922T223440Z-c5ae59da51`, both requested as `gpt-6-luna`, through
  `codex-cli-chatgpt-oauth`, with provider-returned identity `not_exposed`.

## Equivalence result

The transport controls matched the Luna 5.6 capture: Codex CLI, ChatGPT OAuth,
fresh temporary working directory per task, ephemeral session, read-only
sandbox, approval `never`, web/tools/memory disabled, exact prompt forwarding,
and `--max-retries 0`. The only requested model change was the exact slug
`gpt-6-luna`. Provider-returned identity remains `not_exposed`, and equivalence
to the ChatGPT model picker remains `unverified`.

## Capture commands when the route is enabled

The commands below are historical capture commands. They must not be rerun for
this frozen comparison; the four canonical runs are already immutable.

Repeat 1:

```sh
PYTHONPATH=src python3 -m runner run \
  --model gpt-6-luna \
  --provider codex-cli \
  --max-retries 0
```

Repeat 2: run the same command once more; the runner creates a new run
directory. Verify each resulting run before comparison:

```sh
PYTHONPATH=src python3 -m runner verify-run --run-dir runs/<run-id>
```

No additional Luna 6 benchmark inference is permitted for this comparison.

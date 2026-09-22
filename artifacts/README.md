# Published artifacts

This directory preserves the evidence needed to audit the comparison without
publishing authentication state.

- `runs/` contains the four canonical run directories and their requests,
  responses, raw provider executions, scores, errors, metadata, and summaries.
- `capture-manifests/` contains the capture manifests and benchmark provenance.
- `scoring/` contains the final additive scorer manifest and rescored records.
- `judging/` contains the synthetic judge probes, blind rubric/pairwise
  requests and responses, parsed results, and the separate anonymous mappings.

Machine-specific checkout, home-directory, and temporary-directory prefixes
were replaced in metadata and execution envelopes. The model response text,
frozen prompts, task IDs, scores, and hashes were not substantively changed.
No credentials, API keys, authentication caches, or raw Codex auth state are
published.

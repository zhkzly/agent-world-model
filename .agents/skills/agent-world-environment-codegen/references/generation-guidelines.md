# Contract Project Generation Guidelines

Use one generic skill for all environments. Do not create one skill per generated environment.

## Freedom Boundary

The generated environment can be a Python package, local service, MCP server, CLI surface, database-backed app, HTTP API, or a combination. The requirement and source artifacts decide what is implemented.

The framework only fixes the consumer boundary:

- static `contract.json`;
- `candidate_manifest.json`;
- eight runtime ABI interfaces;
- package-relative files and hashes;
- deterministic reset, invoke, verify, trace, and teardown behavior.

## Runtime ABI

Expose these interfaces through adapter entrypoints declared in `contract.json`:

- `describe(input) -> object`
- `setup(input) -> object`
- `reset(input) -> object`
- `health(input) -> object`
- `invoke(input) -> object`
- `verify(input) -> object`
- `export_trace(input) -> object`
- `teardown(input) -> object`

Each return value should include `status`. Failures should include `error.code`, `error.kind`, `retryable`, and useful diagnostics.

## State And Trace

Make `reset` episode-scoped. Return an `episode_id`, initial observation, available tools, and state evidence such as a snapshot hash when possible.

Make `invoke` append structured trace events. Each event should identify the episode, task, tool, arguments or redacted arguments, result, step index, and state evidence when possible.

Make `export_trace` return either inline events or a package-relative event reference plus a hash.

## Verification

Make `verify` deterministic. It should inspect state, trace, files, database rows, service state, or API results. Avoid LLM judging in the generated verifier.

The positive case should succeed only after the required tool calls or state changes occurred. A negative case with missing or wrong evidence must fail.

## Packaging

Keep all generated implementation files under `generated/`. Keep runner-only logs and scratch output under `agent-output/`.

Never write secrets, API keys, auth tokens, absolute local paths, or live credential-bearing URLs into generated artifacts.

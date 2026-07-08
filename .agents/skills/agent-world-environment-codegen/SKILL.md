---
name: agent-world-environment-codegen
description: Generate Agent World contract-project executable environments from pipeline artifacts. Use when Codex or another code agent is asked to implement an environment project under an isolated workspace from input/artifacts, input/schemas, input/implementation_contract.json, or repair packets.
---

# Agent World Environment Codegen

## Objective

Implement a complete executable environment project from the provided artifacts. Let the environment need determine the code structure, data model, tools, services, database, MCP server, CLI, HTTP API, or Python package. Do not force a fixed runtime file template.

The framework only requires a stable contract-project boundary so downstream systems can set up, reset, invoke, verify, export traces, package, and release the generated environment.

## Required Inputs

Read these files before implementation when present:

- `input/implementation_contract.json`
- `input/framework-replay-contract.json`
- `input/artifacts/*.json`
- `input/schemas/*.schema.json`
- `input/failure-packet.json` on repair attempts

Treat schema files under `input/schemas/` as the machine contract. This skill is guidance, not the schema source of truth.

## Required Outputs

Write the candidate under the isolated workspace:

```text
generated/
  contract.json
  source/
  state/
  adapters/
  scripts/
  spec/
agent-output/
  candidate_manifest.json
  local_check_report.json
```

`generated/source/` is free-form project code. Use whatever structure the environment requires.

`generated/contract.json` must declare the eight runtime ABI interfaces:

- `describe`
- `setup`
- `reset`
- `health`
- `invoke`
- `verify`
- `export_trace`
- `teardown`

MCP, CLI, HTTP, database, local service, or Python callable details belong behind these interfaces as adapters. Do not add top-level required interfaces for specific surfaces.

## Implementation Procedure

1. Read the requirement, task set, surface plan, verifier plan, replay contract, and schemas.
2. Design the environment state, logical tools, concrete surfaces, reset model, trace model, and deterministic verifier.
3. Implement the free-form project under `generated/source/`, plus state fixtures under `generated/state/`.
4. Implement adapter entrypoints under `generated/adapters/` or `generated/scripts/` that expose the eight ABI interfaces declared in `contract.json`.
5. Write task, tool, verifier, and surface descriptors under `generated/spec/`.
6. Run a local generated self-check and write `agent-output/local_check_report.json`; self-check code must create the report directory before writing so it still works after packaging.
7. Write `agent-output/candidate_manifest.json` only after the candidate has the final file hashes.

## Candidate Manifest Rules

`candidate_manifest.json` must use package-relative paths:

- `candidate_dir` must be `generated`.
- `contract_ref` must point to `contract.json`.
- Every file under `generated/` must appear in `generated_files[]`, except Python bytecode cache files.
- Every `generated_files[]` item must include `path`, `kind`, `sha256`, and `source_refs`.
- Do not use absolute paths, home-relative paths, `..`, symlink escapes, credentials, or secret-bearing URLs.

Use the file kinds allowed by `input/schemas/candidate_manifest.schema.json`.

## Verification Rules

Generated self-checks are only supporting evidence. The framework will independently:

- validate schemas, paths, hashes, and package-relative references;
- call the eight ABI interfaces;
- reset episodes for accepted tasks;
- replay positive tool calls through `invoke`;
- call `verify` for positive and negative cases;
- call `export_trace` and check event evidence;
- call `teardown`.

Do not make release decisions from stdout or from the generated self-check.

For more guidance, read `references/generation-guidelines.md`.

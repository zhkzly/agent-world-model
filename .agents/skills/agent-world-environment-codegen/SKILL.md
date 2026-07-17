---
name: agent-world-environment-codegen
description: Generate or repair a real Agent World Environment Candidate from frozen EnvironmentDesign, WorldSpec, ImplementationContract, Task Materializer v3 schema, or disclosed Builder findings. Use for isolated environment implementation under candidate/, Runtime ABI v2, Task Materializer v3, public self-checks, and public tests.
---

# Agent World Environment Codegen

## Objective

Compile the frozen design into a self-contained executable environment whose state transitions
are owned by program code. The framework—not this Agent—owns validation, repair routing, release,
packaging, Registry publication, and training-suite selection.

## Inputs and trust boundary

Read all immutable files that exist under `inputs/`, especially:

- `environment-design.json`
- `world-spec.json`
- `implementation-contract.json`
- `task-materializer-output.schema.json`
- the current `repair-disclosure-*.json` on repair turns

Treat `inputs/` as build-time information only. A restored `candidate/` tree must install, import,
start, reset, invoke, test, and self-check with no sibling `inputs/` directory. Compile required
public schemas and constants into candidate source or declared package data. Never open
`../inputs`, workspace paths, Codex state, prior Judge artifacts, or undisclosed evidence at
runtime or from public tests.

## Required project

Create or repair only `candidate/` as a Python 3.12 uv virtual project:

- `pyproject.toml` with `[tool.uv] package = false`
- closed, wheel-installable `uv.lock`
- non-empty declared `LICENSE`
- Runtime implementation and entry module
- Task Materializer v3 callable and entry module
- runnable public self-check
- real standalone public tests

Do not include `.venv`, caches, bytecode, build output, symlinks, undeclared files, credentials,
host paths, or generated release/Judge claims.

## Runtime and task contracts

Implement `agent-world.runtime.v2` exactly from `implementation-contract.json`. Implement every
WorldSpec tool and code-owned transition for unseen uint64 seeds. Bind the reset actor for the
episode; project reset/invoke observations to the declared actor visibility; keep snapshot as the
full Judge-only state. Do not accept task ids, expected answers, evaluator goals, verifier IR,
oracle data, sealed data, or release metadata.

Expose exactly:

`materialize(seed, task_type, actor, difficulty) -> task-materialization-v3`

Echo the four inputs and return only the schema-authorized public goal and initial config fields.
Make identical calls deterministic and make declared difficulty dimensions materially affect the
goal or initial state. Never create authoritative reward, answer, witness, or release logic.

Read [references/generation-guidelines.md](references/generation-guidelines.md) when implementing
or repairing Runtime protocol details, component isolation, or portability.

## Validation and completion

Run real uv/public checks. Test from the project root and ensure imports still work when the
candidate tree is copied alone. Return the complete structured `CandidateCompletion`, not a patch.
All declared paths are relative to the physical `candidate/` project root; do not repeat the outer
directory. Report a real blocker instead of using templates, mocks, fixed replay cases, or fake
success evidence.

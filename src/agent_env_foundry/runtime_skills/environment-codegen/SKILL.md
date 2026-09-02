---
name: environment-codegen
description: Build a real executable agent environment from one frozen BuilderProjection.
---

# Environment Code Generation Method

Read `BUILDER_PROJECTION.json` and `ENVIRONMENT_CONTRACT.md` completely before
designing the project. The projection is immutable authority; do not edit either
input file.

1. Translate each Requirement and InitialWorldRelation into real observable
   behavior. Preserve its authority, precondition/postcondition, refusal
   condition, prohibited mutation, and falsifiable consequence when present.
2. Choose domain-appropriate tools, schemas, dependencies, and native storage.
   These are your design decisions; do not ask the framework for a template.
3. Make `reset(None)` build a meaningful coherent default world and use the
   public start schema for any additional reset-only beginning situation needed
   to reach every accepted workflow precondition. Treat reset as an initial
   observation: expose discovery anchors, but keep the complete answer to a
   query/read Requirement behind its public read tool. Do not make a query
   artificially non-trivial by returning its answer in reset and later
   requiring a redundant tool call. Do not rely on hidden setup actions or
   native patches.
4. Return structured, chainable tool data and fully describe every emitted
   public leaf in the reset/tool output schemas. Execute state changes against native
   persistent state in the assigned instance directory. Never return canned
   success or maintain load-bearing state only in process memory.
5. Implement `generated_environment.release:read_state(instance_directory)` as
   a protected, task-neutral, read-only projection of real persistent state and
   describe it with `docs/schemas/state.json`. It must not define capabilities,
   success, reward or a Task distribution, and it must never mutate the instance.
6. Implement the complete actor project, public/protected schemas/documentation,
   package data, and diagnostic tests. Do not write release, conformance or Task
   metadata; the Host assembles EnvironmentRelease/3. Do not write TaskSemantics,
   a Task checker or a Qualification Verifier.
   Include tests for native state change, multi-step value reuse, refusal
   without prohibited mutation, reset, reload, instance isolation, and the
   absence of complete query-answer leakage from reset. Tests must also prove
   `read_state` schema conformance, deterministic repeated reads and no mutation.
   For every public tool, execute at least one representative real observation
   and validate its fixed success/refusal envelope. On success, validate only
   `observation["data"]` against that ToolSpec's `output_schema`; never wrap the
   fixed `{ok,data,error}` envelope inside `output_schema`. Business assertions
   alone do not prove schema conformance.
   Cross-check native identifiers and protected state against independent
   backend truth; never prove a parser correct only by round-tripping its own
   output or by checking that the result is a string.
7. Declare and lock every runtime and test dependency yourself in the project's
   `pyproject.toml` and `uv.lock` (test tools such as a test runner belong in a
   dev dependency group). Install and run through the project's own uv
   environment; the host executes tests only with this project's
   `.venv/bin/python`, so a dependency missing from the locked project fails
   factually. No framework template or dependency list exists to inherit.
8. Run real uv lock, tests, and build commands. Repair the project from factual
   command output. Do not weaken the projection or contract to make checks pass.

Do not create Tasks, rewards, verifiers, trajectories, MCP/HTTP transports,
mock positive paths, domain-specific framework hooks, or compatibility readers.

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
   to reach every accepted workflow precondition. Do not rely on hidden setup
   actions or native patches.
4. Return structured, chainable tool data and fully describe every emitted
   public leaf in the reset/tool output schemas. Execute state changes against native
   persistent state in the assigned instance directory. Never return canned
   success or maintain load-bearing state only in process memory.
5. Implement the complete release envelope, public documentation, package data,
   and diagnostic tests. Include tests for native state change, multi-step value
   reuse, refusal without prohibited mutation, reset, and instance isolation. The
   reload test must create one factory object, reset and mutate, close it, create a
   second factory object for the same directory, then invoke without another reset
   and observe the committed state.
6. Declare and lock every runtime and test dependency yourself in the project's
   `pyproject.toml` and `uv.lock` (test tools such as a test runner belong in a
   dev dependency group). Install and run through the project's own uv
   environment; the host executes tests only with this project's
   `.venv/bin/python`, so a dependency missing from the locked project fails
   factually. No framework template or dependency list exists to inherit.
7. Run real uv lock, tests, and build commands. Repair the project from factual
   command output. Do not weaken the projection or contract to make checks pass.

Do not create Tasks, rewards, verifiers, trajectories, MCP/HTTP transports,
mock positive paths, domain-specific framework hooks, or compatibility readers.

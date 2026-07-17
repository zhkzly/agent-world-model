---
name: engineer-agent-world
description: Design, implement, or repair an Agent World executable environment from typed Foundry artifacts. Use for WorldSpec/design synthesis, real Runtime and Task Materializer v3 code generation, or same-session candidate repair without evaluator authority or sealed evaluation.
---

# Engineer Agent World

Build a real programmatic environment whose observable behavior is defined by `WorldSpec`.

## Design mode

1. Use evidence claims for real-world facts; mark unsupported choices as bounded product
   decisions or unknowns.
2. Define state, ToolSurface, ToolSemantics, transition constraints, permissions, observations,
   errors, idempotency, transactions, rollback, concurrency, and task distributions together.
3. Keep tasks, runtime behavior, and verification requirements derived from the same WorldSpec.
4. Return exactly the requested structured contract version.

## Build mode

1. Read only Builder-visible artifacts. Never search for or infer sealed cases, expected answers,
   case labels, or release decisions.
2. Create a complete project in the assigned workspace with `pyproject.toml`, `uv.lock`, a
   non-empty `LICENSE` declared by `[project].license` and file role `license`, a parameterized Task
   Materializer v3 callable, standalone public-test scripts, and a real Runtime. Do not create candidate,
   Judge, envpkg, SBOM, supply-chain, or release manifests/results; framework code derives those
   only after physical inspection.
3. Keep the uv root virtual and non-installed (`[tool.uv] package = false`); use only locked
   registry wheels that Judge can install offline without source builds or network access.
4. Implement `agent-world.runtime.v2` over stdio JSONL: handshake, reset, invoke, snapshot, close.
   Runtime inputs are task-agnostic; state transitions occur in program code.
5. The materializer returns only the exact v3 call echo, typed `public_goal`, and
   `initial_config`. It never authors an instruction, evaluator goal, answer, expected output,
   solution trace, or evaluation witness; framework code renders/projects/verifies those.
6. Support unseen seeds, entity identifiers, valid parameters, and action sequences. Do not use
   fixed replay maps, environment-id branches, fixture registries, generated `verify()`, mocks,
   stubs, or template-only success.
7. Make every public test directly runnable as `.venv/bin/python relative/test_path.py` with no
   network or writable source tree. Run the real build and public tests. Their results support
   repair and failures block release, but their content never authorizes a PASS verdict.

## Repair mode

Modify the existing candidate in the same workspace and thread. Address disclosed Findings
without weakening contracts, detecting tests, embedding expected values, or bypassing a gate.

# Remove hardcoded domain probes

## Goal

Make request-driven environment generation genuinely pipeline-generated instead of selecting hardcoded booking/library/project-board probes.

The user requirement is strict: this task is not complete if the normal request-driven success path still depends on domain constants, keyword-specific branches, generated runtime templates, task ids, verifier replay cases, or source packet generators for examples such as booking, library lending, or project board. The framework must take a raw request or source seed, build source-grounded artifacts, generate task/verifier/runtime contracts, ask a code agent to write executable environment code, execute that code through framework-owned checks, repair failures, and package/release only after verification.

## Current Problem

The project has a strong S0-S11 workflow skeleton, agent runner workspaces, replay contracts, executable checks, and bounded repair. However the request-driven implementation still contains hardcoded probe domains:

- `agent_world/request_driven.py` contains booking constants, keyword matching, source packet generation, task/verifier synthesis, runtime code templates, package/release metadata, and generated candidate helpers.
- `agent_world/library_lending.py` contains the same class of hardcoded request-driven path for library lending.
- `agent_world/pipeline.py` has request-driven implementation branches that know about `BOOKING_ENVIRONMENT_ID`.
- `agent_world/replay_contract.py` currently contains hardcoded replay tool calls for booking, library, and project-board.
- `agent_world/independent_verifier.py` contains domain-specific independent replay functions.
- Current docs still describe booking/library as request-driven success probes.

Those paths are useful historical fixtures, but they do not satisfy the user's goal of an automatically generated environment pipeline.

## Requirements

1. Replace the normal `run_request_driven_pipeline()` success path with a generic pipeline-generated path. The path must not special-case booking, library, project-board, or any other example domain.
2. Domain planning must produce a generated `environment_id`, domain summary, constraints, and source plan from the raw request/source seed without keyword selecting a prebuilt domain.
3. Source discovery must build source evidence from raw request and/or configured local source paths. If a live search/agent backend is configured, it may enrich source evidence through `AgentBackend`; otherwise it must record explicit local/raw-request evidence instead of fabricating a domain pack.
4. Knowledge extraction, environment spec, logical tool graph, task set, surface plan, verifier plan, and implementation request must be derived from upstream artifacts, not from domain constants.
5. The code implementation step must be agent-backed for the normal request-driven success path. Deterministic templates are not acceptable as the normal generated-environment implementation.
6. The framework must still own final validation: path/hash/security checks, generated check execution, generic framework replay from `framework-replay-contract.json`, bounded repair, and package/release.
7. `framework-replay-contract.json` must be generated from `TaskSet`, `SurfacePlan`, and `VerifierPlan`; it must not contain domain-specific hardcoded replay cases in production code.
8. The independent verifier/checker must execute generated files using the generated replay contract, not built-in booking/library/project-board replay code.
9. Existing fixture/regression modules may remain only as legacy tests or historical examples. They must not be used by `request_driven_node_registry()` or `run_request_driven_pipeline()` success path.
10. Documentation must be corrected or deleted where it claims booking/library hardcoded probes are the current target architecture.
11. Use `uv` for validation commands.

## Acceptance Criteria

- [ ] `run_request_driven_pipeline()` on a new raw request succeeds through the generic path and produces a generated environment id that is not `booking-service-lite`, `library-lending-lite`, `project-board-lite`, or `support-desk-lite`.
- [ ] The normal request-driven success path uses agent-backed generated code, not deterministic domain templates.
- [ ] `agent_world/request_driven.py`, `agent_world/pipeline.py`, `agent_world/replay_contract.py`, and the generic independent verifier/check path contain no production branches or constants for booking/library/project-board/support-desk domains.
- [ ] Any remaining booking/library/project-board/support-desk code is isolated under fixture/legacy tests or explicitly historical docs and cannot be reached from `request_driven_node_registry()`.
- [ ] `framework-replay-contract.json` replay cases are generated from artifact data and contain concrete tool calls/tasks from the pipeline output.
- [ ] The framework candidate check can execute a generated candidate via the generic replay contract and return structured observations.
- [ ] A broken generated candidate feeds a structured observation into bounded repair and can pass after one repair attempt in tests.
- [ ] A generated candidate with forged self-check output is rejected by the generic framework check.
- [ ] Docs and progress logs no longer describe booking/library probes as the current success criterion.
- [ ] Existing legacy regressions that are intentionally kept still pass, or are rewritten/deleted if they only asserted hardcoded probes.
- [ ] `uv run pytest tests/agent_world` passes.

## Out Of Scope

- Do not implement real GPU training, verl/Ray/vLLM/SGLang workers, or trainer feedback loops.
- Do not bind the system to Codex specifically. Use `AgentBackend`; tests may use a mock/process runner.
- Do not claim arbitrary internet search is complete unless a real source/search backend is explicitly implemented and verified.
- Do not preserve booking/library hardcoding by moving it behind a differently named strategy registry.

# Document project alignment

## Goal

Bring the current project documentation and Trellis task record back into alignment with the repository's true state.

The user previously advanced this older project without following the Trellis workflow. This task reconstructs the missing Trellis planning context, checks the current documents against code and tests, and corrects document drift without changing runtime behavior.

The user's actual product intent is a loop-engineering environment factory:

- A user gives a direct environment need or capability gap.
- The system immediately starts a fixed, auditable workflow: search/discovery when needed, source extraction, task construction, code-agent implementation, checks, verifier gates, packaging, and release preparation.
- LLMs or agents such as Codex are used only at explicit nodes where judgment, search, code writing, review, or repair is needed.
- Deterministic workflow code owns stage order, state, retries, gates, records, and release decisions.
- Generated environments should later be consumable by training/evaluation systems, even though the real trainer loop is not fully implemented yet.
- In practice, an environment is backend code plus state, tools/surfaces, tasks, verifiers, and package metadata. Codex-like code agents should be able to implement that backend code from source documents and generated specs.
- The framework must verify that generated backend code is executable, passes task/verifier checks, and can enter loop feedback/repair until it is correct or bounded failure is recorded.
- Deployment, verl sampling, SFT data production, and training-result-driven environment iteration are downstream dynamic workflows. They are important future consumers, but not the core scope of this documentation-alignment task.

## Background

Confirmed source of truth:

- `docs/agent-world-environment-generation.zh.md` is the primary task source.
- `AGENTS.md` says `docs/project-progress-and-corrections.zh.md` is the living progress and drift log.
- `README.md` is the public project summary and should distinguish implemented probes from future generic generation.
- Current code includes `agent_world.pipeline`, `agent_world.request_driven`, `agent_world.library_lending`, `agent_world.generated_bundle`, and `agent_world.independent_verifier`.
- Current tests include Goal 02-12 coverage, including request-driven booking and library probe paths.
- `docs/loop-engineering.md` frames the core engineering approach: move repeated prompt-driven work into fixed workflows whose stages, state, evaluator gates, logging, replay, and stop/resume points are represented outside the model's hidden reasoning.

Confirmed current state from inspection:

- `request_driven_node_registry()` adds explicit `DomainPlan` and `StrategySelection` stages before S0-S11.
- `run_request_driven_pipeline()` can release `booking-service-lite` for booking/ticket raw requests.
- Library lending raw requests can release `library-lending-lite` through the same request-driven entrypoint.
- Manual `project_board_lite_node_registry()` with a booking request still releases `project-board-lite`; tests intentionally treat that as not Goal 12 success.
- Generated bundle packaging writes `envpkg/runtime/generated/<bundle_id>/` and `envpkg/release/generated-runtime-index.yaml`.
- Framework-owned independent verifier strategies exist for `project-board-lite`, `booking-service-lite`, and `library-lending-lite`.
- Bounded repair records are framework-controlled through `PipelineRunConfig.max_repair_attempts` / `AGENT_WORLD_MAX_REPAIR_ATTEMPTS`.

## Requirements

1. Reconstruct Trellis planning artifacts for this documentation-alignment work.
2. Review the primary source document, README, progress/correction log, Goal 02-12 docs, and relevant code/tests.
3. Correct documentation that is stale, internally inconsistent, or likely to mislead future work.
4. Preserve the core boundary: the project is still not a generic arbitrary-domain environment generator.
5. Keep old `awm` CLI compatibility claims conservative; do not document new behavior unless code/tests support it.
6. Do not change business/runtime code unless a documentation check reveals a small, necessary metadata fix.
7. Do not rewrite user-created uncommitted code or unrelated documents.
8. Make loop-engineering intent explicit: deterministic orchestration should own process control, while LLM/agent calls are auditable workflow nodes.
9. Keep AWM/AW influence framed as evidence and examples: database/file-backed state transitions and MCP/CLI/Python/HTTP surfaces are possible surface/state choices, not mandatory universal constraints.
10. Clarify that "generated environment" means generated executable backend/runtime code plus state, tool surfaces, verifier, tasks, and release package, not merely JSON/YAML planning artifacts.
11. Keep deployment/training/sampling and training-feedback environment iteration as downstream or future loops unless current code/tests prove the path.
12. Use `uv` as the default Python environment and validation command entrypoint in project docs.

## Acceptance Criteria

- [x] `prd.md`, `design.md`, and `implement.md` exist for this Trellis task and reflect the current evidence.
- [x] `README.md` and `docs/project-progress-and-corrections.zh.md` clearly separate implemented facts from remaining limitations.
- [x] Goal documents that mix historical target language with completed-state language are adjusted or annotated where necessary.
- [x] `docs/agent-world-environment-generation.zh.md` remains the authoritative task source and is not weakened by downstream summaries.
- [x] The documentation mentions the current request-driven probe status for both `booking-service-lite` and `library-lending-lite`.
- [x] The documentation explains that the desired end state is direct-request environment construction with search/source discovery, code-agent implementation, verifier gates, packaging, and future training/eval consumption.
- [x] The documentation uses loop-engineering language consistently: fixed workflow, explicit state, explicit agent nodes, deterministic gates, replayable records.
- [x] The documentation states that environment generation must eventually produce executable backend/runtime code and not stop at specs.
- [x] The documentation identifies training/deployment/verl/SFT consumption as downstream flow, with training-result-driven environment iteration deferred.
- [x] Python validation examples use `uv run ...` unless documenting generated bundle commands that intentionally run inside a package runtime directory.
- [x] The documentation does not claim generic arbitrary-domain generation, live network discovery, live Codex/Claude/mini-swe-agent default execution, true trainer integration, or universal verifier synthesis.
- [x] Documentation checks include at least source/text search and targeted tests or import checks relevant to the documented state.
- [x] `docs/project-progress-and-corrections.zh.md` is updated if the review finds a misunderstanding or state correction.

## Out Of Scope

- Implementing Goal 13 or a new product feature.
- Generalizing request-driven planning beyond the registered booking/library probes.
- Adding live network source discovery.
- Integrating real trainer loops, GPU, Ray, vLLM, SGLang, verl, TRL, OpenRLHF, or LLaMA-Factory as core dependencies.
- Reworking Trellis infrastructure or bootstrap guideline tasks.
- Cleaning unrelated uncommitted changes.

## Evidence To Recheck During Execution

- `agent_world/pipeline.py`: request-driven registry, generated bundle packaging hook, repair loop.
- `agent_world/request_driven.py`: booking planner/selector/source/synthesis/codegen/package docs.
- `agent_world/library_lending.py`: second request-driven probe.
- `agent_world/independent_verifier.py`: verifier strategy dispatcher and task records.
- `agent_world/generated_bundle.py`: package-relative generated runtime consumer.
- `tests/agent_world/test_goal12_request_driven_pipeline.py`: booking/library request-driven acceptance.
- `tests/agent_world/test_goal11_independent_verifier_bounded_repair.py`: forged check rejection and repair loop.

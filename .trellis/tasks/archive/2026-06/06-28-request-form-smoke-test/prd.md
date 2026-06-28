# Request form smoke test

## Goal

验证用户要求的交互形式：给系统一段自然语言环境需求后，系统能直接启动 request-driven environment generation path，而不是人工手动选择某个领域 registry。

本任务是 smoke/evidence task，不新增产品功能。它要用当前代码和当前环境配置跑一个端到端探针，确认已提交 baseline 是否真的符合“直接给需求，立刻执行，生成可验证环境包”的最小形态。

## Confirmed Facts

- 当前 task 开始时 git worktree clean。
- `docs/agent-world-environment-generation.zh.md` 声明 env/config 入口包括：
  - `AGENT_WORLD_AGENT_BACKEND`
  - `AGENT_WORLD_OPENAI_BASE_URL` with fallback to `OPENAI_BASE_URL`
  - `AGENT_WORLD_OPENAI_API_KEY` with fallback to `OPENAI_API_KEY`
  - `AGENT_WORLD_OPENAI_MODEL` with fallback to `OPENAI_MODEL`
  - `AGENT_WORLD_SMOKE_OPENAI_MODEL`
  - `AGENT_WORLD_OPENAI_API_VERSION`
  - `AGENT_WORLD_CODE_AGENT_CMD` / `AGENT_WORLD_CODEX_CMD`
- Code confirms `load_agent_backend_config_from_env()` reads `AGENT_WORLD_OPENAI_BASE_URL` before `OPENAI_BASE_URL`.
- Current shell environment has relevant variable names set, including `AGENT_WORLD_OPENAI_BASE_URL`, `AGENT_WORLD_OPENAI_API_KEY`, `AGENT_WORLD_OPENAI_MODEL`, `AGENT_WORLD_SMOKE_OPENAI_MODEL`, and fallback `OPENAI_*` names.
- Secrets and base URL values must not be printed in the conversation or committed. It is acceptable for code to use them through environment lookup.
- The first English request-form smoke exposed a planner bug: `booking` matched the library token `book` through bare substring matching and routed to `library-lending-lite`.
- The planner bug was fixed by using token-boundary matching for ASCII tokens while preserving substring matching for Chinese tokens.

## Requirements

1. Run a deterministic request-form smoke using `run_request_driven_pipeline()` with a raw booking/reservation request.
2. Verify the smoke result proves:
   - domain planner selected `booking-service-lite`,
   - strategy selector ran,
   - generated runtime package exists under `envpkg/runtime/generated/<bundle_id>/`,
   - package index exists at `envpkg/release/generated-runtime-index.yaml`,
   - independent verifier passed positive and negative records,
   - S0-S11/request lineage is present,
   - result did not come from manually selecting `project_board_lite_node_registry()`.
3. Run existing Goal 12 regression tests with `uv`.
4. Attempt a configured live/backend smoke only if current environment makes it safe and explicit enough:
   - do not print or commit API key values,
   - do not print base URL value,
   - do not require live success for this task if credentials/network/model access fail,
   - record live result as `pass`, `skip`, or `blocked/fail` with failure class only.
5. Keep outputs in `/tmp` or task notes; do not commit generated env packages or traces.

## Acceptance Criteria

- [x] Deterministic raw-request smoke passes and reports `booking-service-lite`.
- [x] Packaged generated runtime check passes from the package directory.
- [x] Existing Goal 12 pytest suite passes.
- [x] Live/backend smoke is attempted or explicitly skipped with a concrete reason.
- [x] No API key, auth token, or base URL value is printed or committed.
- [x] Task record captures commands and result summary.

## Out Of Scope

- Generalizing to arbitrary domains.
- Adding a new domain strategy.
- Modifying codegen prompts or generated runtime implementation.
- Committing generated smoke outputs.
- Debugging external provider account/model/network failures beyond recording the failure class.

## Notes

- This is a lightweight task; PRD-only is sufficient unless execution uncovers a code defect.

## Result Summary

- Initial deterministic smoke with English booking/reservation wording incorrectly produced `library-lending-lite`; this was caused by matching `book` inside `booking`.
- Fix: `agent_world.request_driven._matched_tokens()` and `agent_world.library_lending.matches_domain()` now use ASCII token-boundary matching.
- Regression: `test_goal12_english_booking_request_does_not_match_library_book_substring` was added.
- Deterministic request-form smoke result after fix:
  - `status=pass`
  - `environment_id=booking-service-lite`
  - generated files: `runtime.py`, `seed_state.json`, `verifier.py`, `surface_descriptor.json`, `check_replay.py`, `build_manifest.yaml`
  - independent verifier: 3 positive and 3 negative records
  - packaged generated runtime check: pass
  - artifact flow: `DomainPlan -> StrategySelection -> NeedSpec -> SourceEvidenceIndex -> KnowledgePack -> EnvironmentSpec -> LogicalToolGraph -> TaskSet -> SurfacePlan -> VerifierPlan -> FeasibilityReport -> ImplementationRequest -> GeneratedEnvironmentBundle -> IndependentVerificationReport -> EnvironmentPackagePlan -> ReleaseManifest`
- Live backend smoke:
  - configured backend kind: `llm`
  - base URL/API key/model/smoke model/network/auth were present but values were not printed
  - minimal chat-completions invocation status: pass
- Validation:
  - `uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py`: 10 passed
  - `uv run --offline pytest tests/agent_world`: 101 passed, 1 skipped
- Work commit: `cd3588c Fix request planner token matching`

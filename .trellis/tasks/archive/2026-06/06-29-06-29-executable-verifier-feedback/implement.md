# Implementation Plan

## Checklist

1. Add shared contract/observation helpers.
   - Define replay contract builder from pipeline artifacts and existing strategy knowledge.
   - Define framework check observation helpers for prerequisite/task/exception evidence.

2. Write `input/framework-replay-contract.json` in runner workspaces.
   - Keep existing markdown files for human-readable guidance.
   - Ensure tests assert contract presence and key fields.

3. Add framework-owned candidate check/preflight API.
   - Reuse independent verifier strategies.
   - Return JSON-compatible observation.
   - Optionally expose module CLI if small and low-risk.

4. Improve independent verifier evidence.
   - Capture traceback with `traceback.format_exc()`.
   - Record task/case/call/phase where possible.
   - Add expected/actual evidence to task observations.
   - Avoid turning task replay exceptions into only global prerequisite failures.

5. Feed observations into repair packets.
   - Add `framework_check_observation`.
   - Preserve existing relative candidate path/hash behavior.
   - Redact secret values and avoid absolute local candidate paths.

6. Update tests.
   - Workspace packet contains machine-readable replay contract.
   - Candidate check returns JSON observation for pass and fail.
   - Runtime exception includes traceback and task/call context.
   - Forged `check_replay.py` remains rejected.
   - Existing generated bundle success paths still pass.

7. Update docs/spec.
   - Record the workflow-level meaning in project progress/corrections.
   - Update backend quality guideline for executable verifier feedback workflow.

## Validation Commands

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world/test_goal09_code_agent_runner.py
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world
UV_CACHE_DIR=/tmp/uv-cache uv run --offline python -m compileall -q agent_world
git diff --check
```

## Risk Points

- Independent verifier is shared release authority. Keep changes additive and preserve existing report fields.
- The observation contract crosses pipeline, verifier, generated bundle, runner workspace, repair packet, package check, and tests.
- Avoid absolute path leakage in repair input.
- Do not accidentally make live Codex/network required by tests.
- Do not encode booking-only concepts into the top-level replay contract envelope.

## Rollback

Revert shared contract/observation helpers and workspace packet additions together. If verifier evidence changes break compatibility, keep the old `task_records` and add observation as an optional field instead of replacing existing keys.

# Implementation Plan

## Checklist

1. Add generic request-driven synthesis module.
   - DomainPlan from raw request/source seed without domain keyword tables.
   - SourceEvidenceIndex from raw request and local source paths.
   - KnowledgePack / tool graph / task set / verifier plan / surface plan from upstream artifact data.

2. Replace `request_driven_node_registry()` factories.
   - Stop calling booking/library probe functions.
   - Make normal implementation mode agent-backed.
   - Ensure no `BOOKING_ENVIRONMENT_ID` branch is used in request-driven implementation.

3. Generalize replay contract.
   - Remove hardcoded `_tool_calls(environment_id, task_id)` cases.
   - Generate replay cases from task/tool artifact fields.

4. Add generic generated candidate checker.
   - Execute replay cases from `framework-replay-contract.json` or equivalent artifact data.
   - Produce structured observation.
   - Reject forged generated `check_replay.py` success.

5. Isolate or delete hardcoded request-driven probes.
   - Keep only legacy fixture tests if still valuable.
   - Remove/import-split production reachability from request-driven path.

6. Update tests.
   - New arbitrary raw request release through generic path.
   - Generated environment id is not any previous hardcoded domain.
   - Broken candidate repairs from observation.
   - Forged self-check rejected.
   - Negative grep/assertions for production hardcoded domain branches.

7. Update docs and specs.
   - Correct current progress and source task docs.
   - Remove claims that booking/library probes are the current success target.

8. Validate and publish.
   - Run targeted tests.
   - Run `uv run pytest tests/agent_world`.
   - Commit, archive Trellis task, record journal.
   - Push to private remote.

## Validation Commands

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world/test_goal12_request_driven_pipeline.py
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world/test_goal09_code_agent_runner.py
UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world
UV_CACHE_DIR=/tmp/uv-cache uv run --offline python -m compileall -q agent_world
git diff --check
git push private main
```

## Risk Points

- It is easy to fake completion by moving booking constants behind a registry. Do not do that.
- Generic checker must execute generated files; schema validation alone is not enough.
- Tests must not depend on live network/model credentials.
- Removing hardcoded probes may require deleting or rewriting Goal 12 tests/docs that encode the old acceptance probe.

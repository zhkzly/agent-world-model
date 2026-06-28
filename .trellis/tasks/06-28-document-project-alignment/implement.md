# Implementation Plan

## Checklist

- [x] Re-read primary source and current progress docs before editing.
- [x] Re-read `docs/loop-engineering.md` and reflect its fixed-workflow vs prompt-only distinction in the project docs.
- [x] Reflect the user's clarification that environments are generated backend/runtime code packages, not just plans.
- [x] Reflect that training/deployment/verl/SFT and training-feedback environment iteration are downstream/future dynamic loops.
- [x] Reflect the user's preference and project rule that Python commands use `uv`.
- [x] Identify concrete documentation drift with file references.
- [x] Patch Trellis planning artifacts.
- [x] Patch public/project docs with conservative state language.
- [x] Patch Goal docs only where wording is misleading or stale.
- [x] Run documentation searches for unsupported claims.
- [x] Run targeted tests for request-driven pipeline and generated verifier/package claims.
- [x] Update progress/correction log if a new drift item is discovered.
- [x] Summarize changed files, validation commands, and any residual risk.

## Candidate Files

- `README.md`
- `docs/project-progress-and-corrections.zh.md`
- `docs/goal-12-request-driven-generation-pipeline.zh.md`
- `docs/agent-world-environment-generation.zh.md`
- This task directory under `.trellis/tasks/06-28-document-project-alignment/`

## Validation Commands

Use `uv` for Python commands:

```bash
uv run pytest tests/agent_world/test_goal12_request_driven_pipeline.py
uv run pytest tests/agent_world/test_goal08_agent_backed_codegen.py
uv run pytest tests/agent_world
```

Text checks:

```bash
rg -n "generic|arbitrary|通用|任意|已完成|当前实现状态|live|Codex|trainer|verl|request-driven|booking-service-lite|library-lending-lite" README.md docs
```

## Rollback Points

- If a doc edit changes the project meaning rather than clarifying it, revert that hunk only.
- If tests show a documented capability is false, update the doc to lower the claim instead of changing code under this task.
- If unrelated uncommitted files shift during the task, do not revert them; inspect only if they affect documentation truth.

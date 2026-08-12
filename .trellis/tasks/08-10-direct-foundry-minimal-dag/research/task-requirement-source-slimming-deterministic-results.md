# Deterministic results — TaskRequirement source slimming

- Date: 2026-08-12
- Allowed plan digest:
  `sha256:c013eb6ef26f717920b22228476ce883cdebc558bb97ae42de92f0c6694c1e85`
- Scope: TaskRequirement-only model source projection and compiler handoff.

The independent implement worker reported:

- `uv run pytest tests/test_design_semantics.py` — 72 passed.
- `uv run pytest` — 261 passed.
- `uv run ruff format --check agent_world/design.py tests/test_design_semantics.py` — passed.
- `uv run ruff check agent_world/design.py tests/test_design_semantics.py` — passed.
- `uv run mypy agent_world` — passed for 13 source files.
- `uv run python -m compileall -q agent_world` — passed.

The implementation removes deterministic `error_kind` from the model-owned
TaskRequirement source rule, injects framework-owned `None` before the existing
strict RuleDraft compiler, and projects each task input semantic once. It does
not alter the compiled TaskRequirement/RuleDraft shape, graph, retries, SDK,
Candidate, Judge, Registry, Repair, Expand, or Consumer contracts.

These checks prove deterministic source/compiler compatibility only. No live
Luna node, Candidate process, Judge, Registry publication, Direct E2E, Repair,
Expand, or Consumer result is claimed.

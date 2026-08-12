# Expected closed-object field Feedback — deterministic results

- Date: 2026-08-12
- Plan digest: `c98eb85128760cdff40a0b7566dc6090659834b8f59a19bb8899639d347d3238`

## Results

- `uv run pytest -q tests/test_design_semantics.py tests/test_graph_contracts.py`
  -> `109 passed in 4.12s`
- `uv run ruff format --check .` -> `22 files already formatted`
- `uv run ruff check .` -> `All checks passed!`
- `uv run mypy agent_world` -> `Success: no issues found in 13 source files`
- `uv run python -m compileall -q agent_world` -> passed
- `uv run pytest -q tests/test_legacy_firewall.py` -> `2 passed in 0.18s`
- `uv run pytest -q` -> `245 passed in 13.37s`

The commands ran serially from the product worktree. No Provider, Candidate,
Judge, Registry or release operation was invoked.

## Non-claims

These results prove deterministic consistency only. They do not prove that
Luna will repair the Curriculum proposal, that Curriculum or later Design
Artifacts will commit, or that Candidate/Judge/Registry/E2E will pass.

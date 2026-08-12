# Curriculum actionable Feedback progress — deterministic results

Date: 2026-08-12

Scope: exact implementation authorized by plan digest
`77d5ec2da849fea1258dec535cd59b053fd4f6c4454cfad2ea681bae9f509b74`.
No Provider, Candidate process, Judge, Registry, or release call was made by
these checks.

## Results

- `uv run pytest -q tests/test_graph_contracts.py tests/test_design_semantics.py`
  -> `109 passed in 4.11s`
- `uv run ruff format --check .` -> `22 files already formatted`
- `uv run ruff check .` -> `All checks passed!`
- `uv run mypy agent_world` -> `Success: no issues found in 13 source files`
- `uv run python -m compileall -q agent_world` -> passed
- `uv run pytest -q tests/test_legacy_firewall.py` -> `2 passed in 0.18s`
- `uv run pytest -q` -> `245 passed in 13.02s`

All commands were run serially by the main session from
`/home/kelong/pycodes/foundry-direct-graph`. The earlier nested check worker's
interrupted parallel runs are not product evidence and are superseded by the
serial results above.

## Non-claims

This proves only deterministic implementation consistency. It does not prove
that Luna will produce an accepted Curriculum, that downstream Design nodes
will commit, that a Candidate will execute, that Judge will pass, or that a
Registry package will be published.

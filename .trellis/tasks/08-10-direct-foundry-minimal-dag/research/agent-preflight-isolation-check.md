# Independent check — Agent preflight isolation

- Decision: **allow**
- Plan digest: `6e33d4e88c9fc7f20442189d8b429cd3222cd8f4c062357ca863c85484bc27ff`
- Scope checked: only the private Codex-provider override tuple and its exact
  `CodexConfig.config_overrides` regression assertion.

## Exact verification

`agent_world/invocation.py` appends exactly these two entries, after the two
existing retry overrides:

```text
skills.bundled.enabled = false
features.plugins = false
```

`tests/test_agent_route_config.py` asserts the same complete tuple in the same
order. The focused diff hunk contains only those two additions at each allowed
touch point. No configuration/profile/helper/dynamic-discovery/retry/route/
sandbox/Skill/graph/downstream behavior was changed by this allowed hunk.

## Results

- `uv run pytest -q tests/test_agent_route_config.py`: pass (20 passed)
- `uv run pytest -q`: pass (101 passed)
- `uv run ruff format --check .`: pass (21 files already formatted)
- `uv run ruff check .`: pass
- `uv run mypy agent_world`: pass
- `uv run python -m compileall -q agent_world`: pass
- `uv run pytest -q tests/test_legacy_firewall.py`: pass (2 passed)
- `git diff --check`: pass

## Nonclaims

This deterministic review does not prove pinned-SDK runtime behavior, a live
Agent/model preflight, singleton surface preservation after a real turn,
candidate isolation, Judge/Registry release, or the end-to-end product target.
No live SDK, model, or E2E invocation was made.

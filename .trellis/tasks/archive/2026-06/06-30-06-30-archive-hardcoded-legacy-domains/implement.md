# Implementation Plan

1. Inventory imports and legacy-term references across `agent_world/`, `tests/agent_world/`, `tests/fixtures/`, and current docs.
2. Delete or detach executable legacy modules:
   - fixture packages
   - legacy runtime/rollout/training/package/replay/workflow modules
   - environment-id keyed helper modules
   - environment-id keyed verifier and pipeline branches
3. Update package exports and imports so only generic framework modules remain.
4. Replace legacy tests with generic request-driven generated-bundle tests and keep `awm` CLI tests.
5. Update current docs and progress log to match the new active slice.
6. Validate:
   - `UV_CACHE_DIR=/tmp/uv-cache uv run --offline pytest tests/agent_world -q`
   - `UV_CACHE_DIR=/tmp/uv-cache uv run --offline python -m compileall agent_world tests`
   - `git diff --check`
   - `rg` audit for legacy hardcoded terms in executable code
7. Commit and push to the private remote.

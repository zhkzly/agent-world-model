# Direct SDK format Feedback — implementation check

- Decision: **allow**
- Matching plan digest: `sha256:12fc5ef06c9d829acd7b70a6d4f13dc4151f9027919cec838eef60e2bb07e621`
- Scope: the reviewed Direct-only adapter and Design-transaction change is proportionate to the stated ~105-line ceiling. It adds no Agent, `CorrectionPacket`, compiler aggregation, graph, Candidate, Judge, Registry, or Observe authority.

## Findings (fixed)

- None. No code changes were needed.

## Findings (not fixed)

- None.

## Verification

- Official SDK path: `OpenAI` uses the configured API root, explicit `timeout=300` and `max_retries=0`, JSON-object response mode, a context-managed client, and no output-token argument. Fallback remains limited to the existing retryable safe transport/HTTP classifications.
- Direct format path: a completed nonempty `stop` non-object returns only local raw content plus safe model/usage; the Design transaction persists safe operation evidence and the safe `direct_response_not_json` attempt state. The raw text is used only for the exact four-message Direct conversation and is absent from persisted artifacts.
- Terminal path: a second malformed result is terminal with two calls and no third call; generic compiler correction and release behavior remain unchanged.
- Contract sync: the Direct-only exception is present in the source-of-truth text and `node-contracts.md`; no generic feedback contract was expanded.
- `uv run pytest -q tests/test_agent_route_config.py tests/test_design_semantics.py tests/test_graph_contracts.py`: pass (122 passed).
- `uv run pytest -q`: pass (225 passed).
- `uv run ruff format --check .`: pass.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass.
- `uv run python -m compileall -q agent_world`: pass.
- Providers: not invoked.

No issues found after the bounded review and requested verification.

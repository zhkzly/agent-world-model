# Direct live usage R1 deterministic check

Date: 2026-08-11

## Decision

Decision: allow

The exact repair-plan digest is `91640dda2714099ed6e8c34fb68dc77d6baae58085f9f208ca7fe7b53736bece`, matching the current `direct-live-usage-repair-plan.md` and its matching independent allow. The R1 delta is confined to the authorized four-file slice:

- `agent_world/invocation.py`: `DirectChatBackend` projects only valid non-negative integer provider `prompt_tokens` and `completion_tokens` to canonical `input_tokens` and `output_tokens`, preserves valid `total_tokens`, and retains no provider payload.
- `agent_world/contracts.py`: `OperationEvidence` accepts only the closed canonical token-key set; both provider aliases are rejected before Artifact persistence.
- `tests/test_agent_route_config.py`: mocked Direct-provider normalization verifies valid values and rejection-by-omission of invalid values.
- `tests/test_graph_contracts.py`: verifies alias rejection plus `assurance.operation` cold persistence in the committed WorkRecord assurance closure.

The producer/consumer chain remains unchanged: GraphRunner persists `OperationEvidence` as immutable `assurance.operation` before compilation and includes its ref in `WorkRecord.assurance_refs`; the Package telemetry compiler cold-reads and reconstructs the same closed `OperationEvidence` contract. ArtifactStore's generic Prompt-shaped-field safety remains unchanged. No reference or mutation path targets stale run `run_0fe1d0215d644837a43cfe7fc9994abe`.

No graph topology, route/fallback/retry, Prompt, runtime Skill, Artifact safety rule, persistence authority, error/recovery path, later-child handoff, or public Observe schema drift was found in the R1 slice. The pre-existing cleanroom changes outside this exact slice were intentionally left untouched.

## Verification

- Focused tests: `uv run pytest tests/test_agent_route_config.py tests/test_graph_contracts.py` — pass (41 passed).
- Full tests: `uv run pytest` — pass (97 passed).
- Ruff format: `uv run ruff format --check .` — pass (21 files already formatted).
- Ruff lint: `uv run ruff check .` — pass.
- TypeCheck: `uv run mypy agent_world` — pass (13 source files).
- Compile: `uv run python -m compileall -q agent_world` — pass.
- Legacy firewall: `uv run pytest tests/test_legacy_firewall.py` — pass (2 passed).
- Diff whitespace: `git diff --check` — pass.

## Explicit non-claims

This deterministic check does not claim that the stale run compiled or became terminal, that any fresh provider invocation or `world_architecture` proof has run, or that real Agent execution, Candidate, Integration, Judge, Registry publication, Repair, Expand, Consumer, or end-to-end product completion has been proven. It does not authorize historical-run mutation or any change outside the allowed R1 scope.

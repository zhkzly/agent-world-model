# R1 implementation check — WorldArchitecture contract disclosure

- Date: 2026-08-11
- Reviewed plan digest: `7a61ad505b522b50ab51c5ce35e384fc6b9a82c9b426d2b6b9938b07fa1bb0cc` (recomputed SHA-256: match)
- Predecessor: `cross-layer-review-7beeb872-architecture-contract.md` (`block`)
- Current authority: `cross-layer-review-7a61ad50-architecture-contract-r1.md` (`allow`)

## Decision: allow

`DesignExecutor._direct_architecture` supplies the exact approved canonical
`output_shape` string.  It discloses the existing closed root/tool shapes,
kebab and snake identifier bounds, text/list limits, uniqueness, the empty
`arguments` versus nonempty `result_fields` distinction, and the authority
field exclusions.

The focused regression uses the actual `_direct_architecture` transaction and
a capturing Direct stub.  It makes exactly one invocation, compares the
delivered `output_shape` by exact equality, and verifies that the valid
proposal is committed as the unchanged architecture Artifact payload.

Inspection found no R1 change to the compiler helpers or validation contract,
`_direct_commit`, graph topology, retry/correction behavior, schemas, or
downstream consumers.  The literal occurs only in `agent_world/design.py` and
the focused assertion in `tests/test_graph_contracts.py` within the inspected
R1 scope.

## Verification

- `uv run pytest -q tests/test_graph_contracts.py`: pass — 25 passed.
- `uv run pytest -q`: pass — 101 passed.
- `uv run ruff format --check .`: pass — 21 files already formatted.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world`: pass — no issues in 13 source files.
- `uv run python -m compileall -q agent_world`: pass.
- `uv run pytest -q tests/test_legacy_firewall.py`: pass — 2 passed.
- `git diff --check`: pass.

## Non-claims

This deterministic allow does not claim a real-provider WorldArchitecture
commit, any later Direct-node success, modeling pass, Candidate, Integration,
Judge, package, Registry publication, Repair, Expand, Consumer, or E2E
completion.  No live model, Agent, or E2E proof was run.

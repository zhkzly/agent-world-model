# Independent implementation check — remaining Design Direct contract closure R2

- Date: 2026-08-12
- Decision: **block**
- Reviewed critic allow: `cross-layer-review-df78d60d-remaining-design-direct-r2.md`
- Exact reviewed plan digest: `sha256:df78d60dce150753a8251e5f809321dc303f6fe0417fd02ae47ed7d6b7e13650`
- Reviewed plan revision: `remaining-design-direct-contract-closure`, revision 2/2
- Check scope: the bounded Design-source/compiler closure only; no provider or E2E execution was run.

## Files and scope

Reviewed implementation files:

- `agent_world/design.py`
- `agent_world/contracts.py` (`SharedToolContract` invariant only)
- `tests/test_design_semantics.py`
- `tests/test_graph_contracts.py`
- `tests/test_direct_release.py`
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md`

The worktree contains pre-existing uncommitted Direct-foundation work outside
this revision. The targeted files have the current R2 edit timestamps; the
compatibility consumers `graph.py`, `candidate.py`, `observe.py`, and
`config.py` predate them and were inspected without modification. No review
write changed production or test code.

## Findings (not fixed)

1. **The required real RuleDraft failure-class regression is absent.**
   `tests/test_design_semantics.py` verifies that `_RULE_DRAFT_SHAPE` is present
   in each recipient prompt and verifies a different
   `shared_tool_semantics_invalid` correction cap. It has no exercise of a
   malformed `tool_semantics` RuleDraft root (the real terminal class), no
   assertion for `tool_semantics_invalid`, and no valid `errors[]` RuleDraft
   using a legal bounded `error_kind`. Therefore it does not prove the stated
   `errors[]` grammar/bound or that the actual first malformed ToolSemantics
   proposal receives the exact correction and a valid second proposal commits
   within two calls.

   This is a validation/contract-evidence gap, not a formatting, type, or
   import repair. Per the reviewer scope it was not silently changed.

## Verified ABI and role boundaries

- `_RULE_DRAFT_SHAPE` is one shared source string and is included byte-for-byte
  in ToolSemantics, WorldRules, and TaskRequirement prompt shapes. Its
  `error_kind` text matches the compiler's `_NAME.fullmatch` rule:
  `[a-z][a-z0-9_]{0,63}`, with null required in non-error sections.
- Curriculum preserves the existing `task_family_id` grammar and the
  hyphen-permitting `[a-z][a-z0-9_-]{0,39}` dimension/level grammar; the
  compiler and cold dataclasses agree.
- SharedTool source output no longer echoes frozen coordinates. Framework binds
  the ordered group, injects ToolDraft's tool/shared digest and TaskRequirement's
  family index, computes the shared digest from the injected typed payload, and
  `SharedToolContract` rejects non-integer, duplicate, overlap, unknown, and
  out-of-order policy bindings.
- ModelingGate receives the same typed Design ports. Candidate projection,
  package metadata, Registry cold-read digest reconstruction, and safe Observe
  remain consumers of the compiled typed ABI; their focused and full tests pass.
- The six affected semantic works remain `designer` / `direct_llm` / `direct`
  with no Skill or workspace. Framework retains compilation, digests, Work,
  Gate, and release authority. Agent and candidate-process roles are unchanged;
  no graph node, edge, route, retry mode, or release owner was added.

## Verification

- Focused tests: `uv run pytest -q tests/test_design_semantics.py tests/test_graph_contracts.py tests/test_direct_release.py` — **pass** (`109 passed`)
- Full tests: `uv run pytest -q` — **pass** (`203 passed`)
- Legacy firewall: `uv run pytest -q tests/test_legacy_firewall.py` — **pass** (`2 passed`)
- Format: `uv run ruff format --check .` — **pass** (`22 files already formatted`)
- Lint: `uv run ruff check .` — **pass**
- TypeCheck: `uv run mypy agent_world` — **pass** (`13 source files`)
- Compile: `uv run python -m compileall -q agent_world` — **pass**
- Diff whitespace: `git diff --check` — **pass**
- Production Python: **10,311 lines**, within the approved **10,320** ceiling.

## Non-claims

This is a static implementation check only. It does not claim a repaired
provider call, complete Design run, Candidate execution, Judge result, Registry
publication, released EnvironmentPackage, Repair, Expand, or Consumer proof.

## Next permitted proof

Do not run the diagnostic suffix or a public Direct/provider proof yet. The
main coordinator must first record this static regression gap and obtain a
fresh bounded plan/critic authorization for the missing real ToolSemantics
RuleDraft/error-kind regression (the reviewed lineage is already revision 2/2).
After that focused test proves the actual correction/commit path, rerun this
check gate before the prescribed provider proof sequence.

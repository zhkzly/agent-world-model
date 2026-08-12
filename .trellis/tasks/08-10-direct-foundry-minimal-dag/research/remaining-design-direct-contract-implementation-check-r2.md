# Independent re-check — remaining Design Direct contract closure R2

- Date: 2026-08-12
- Decision: **allow**
- Reviewed critic allow: `cross-layer-review-df78d60d-remaining-design-direct-r2.md`
- Exact plan digest: `sha256:df78d60dce150753a8251e5f809321dc303f6fe0417fd02ae47ed7d6b7e13650`
- Plan revision: `remaining-design-direct-contract-closure`, revision 2/2
- Scope: static re-check of the sole prior regression-evidence block. No provider or E2E execution was run, and no production behavior was changed.

## Plan and prior-block closure

`check.jsonl` references the current matching `Decision: allow` critic record
and the prior `remaining-design-direct-contract-implementation-check.md`
block. The raw SHA-256 of the current approved plan is exactly
`df78d60dce150753a8251e5f809321dc303f6fe0417fd02ae47ed7d6b7e13650`.

The prior sole block is closed by
`test_tool_semantics_rule_root_correction_commits_bounded_error_kind` in
`tests/test_design_semantics.py`:

- Its first `register_member` ToolSemantics proposal has malformed
  `$.preconditions[0]` RuleDraft root fields.
- The second call for that same tool receives exactly
  `tool_semantics_invalid` with path `$.preconditions[0]`, the closed-object
  condition, and expected category `object`.
- The replacement is complete and commits an `errors[]` RuleDraft with
  `error_kind = "a" + "b" * 63`, a legal 64-code-point value; the committed
  ToolDraft retains that exact value and its WorkRecord is `passed`.
- The recorded calls are exactly `register_member`, `register_member`, then
  `tool_2`, proving the existing one-local-correction/two-call bound for the
  corrected shard without changing the multi-tool topology.

The test was modified after the prior block. `find agent_world -name '*.py'
-newer <prior-block-record>` returned no files; `design.py`, `contracts.py`,
`graph.py`, `candidate.py`, and `observe.py` all predate that block. Thus this
closure is new deterministic evidence, not a product-code or trust-boundary
change.

## Role, ABI, and scope review

- The six semantic Design nodes remain `designer` / `direct_llm` / `direct`,
  with no mounted Skill or workspace. The static two-graph NodeSpec/EdgeSpec
  declaration and one-local-correction topology are unchanged.
- `_RULE_DRAFT_SHAPE` remains byte-identical across ToolSemantics, WorldRules,
  and TaskRequirement, including the errors-only
  `[a-z][a-z0-9_]{0,63}` 1..64-code-point rule. The compiler still rejects
  malformed source values through `DesignError` with a typed path.
- The framework still owns frozen coordinates, compiler/digest construction,
  WorkRecord/Gate/Findings, and release. Agent and candidate-process roles,
  CandidateGraph, Registry, and Observe were not changed.
- SharedTool exact partition/order and cold typed validation, Curriculum's
  hyphen-permitting name grammar and DifficultySchema ABI, typed index/error
  paths, ModelingGate closure, Candidate/package projections, Registry
  cold-read compatibility, and safe Observe consumers remain covered by the
  focused and full suites.
- No generic scheduler, dynamic graph/plugin layer, new route, retry mode,
  runtime authority, or later-child Repair/Expand/Consumer behavior was added.

## Verification

- Focused regression: `uv run pytest -q tests/test_design_semantics.py -k tool_semantics_rule_root_correction_commits_bounded_error_kind` — **pass** (`1 passed, 45 deselected`)
- Focused suite: `uv run pytest -q tests/test_design_semantics.py tests/test_graph_contracts.py tests/test_direct_release.py` — **pass** (`110 passed`)
- Full suite: `uv run pytest -q` — **pass** (`204 passed`)
- Legacy firewall: `uv run pytest -q tests/test_legacy_firewall.py` — **pass** (`2 passed`)
- Format: `uv run ruff format --check .` — **pass** (`22 files already formatted`)
- Lint: `uv run ruff check .` — **pass**
- Type check: `uv run mypy agent_world` — **pass** (`13 source files`)
- Compile: `uv run python -m compileall -q agent_world` — **pass**
- Diff whitespace: `git diff --check` — **pass**
- Production Python: **10,311 lines**, within the approved **10,320** ceiling.

## Findings (fixed)

- File: `tests/test_design_semantics.py`
- Issue: The prior check lacked a regression for the actual malformed
  ToolSemantics RuleDraft root and legal error-kind replacement path.
- Fix: The implementation-side test now drives that exact correction and
  commit path. This re-check made no code or test edits.

## Findings (not fixed)

None. No behavioral, contract, owner, producer/consumer, validation, or scope
issue was found in the allowed slice.

## Non-claims

This is deterministic static evidence only. It does not claim a repaired
provider response, a complete Design run, Candidate execution, independent
Judge result, Registry publication, released EnvironmentPackage, Repair,
Expand, Consumer, SFT, or RL proof.

## Next permitted diagnostic proof

Run only the already-authorized immutable-parent diagnostic suffix: regenerate
strict SharedTool semantics from the failed run's exact Architecture/Evidence
refs, then invoke only `tool_semantics[register_member]` and inspect safe
Work/Artifact/operation and Observe facts. It must not resume/adopt the failed
run, publish, infer release, or produce Registry evidence. Only if that suffix
passes within the existing correction bound may a fresh public Direct request
run to terminal Observe; any new terminal requires a new Observe-driven
Diagnosis Record.

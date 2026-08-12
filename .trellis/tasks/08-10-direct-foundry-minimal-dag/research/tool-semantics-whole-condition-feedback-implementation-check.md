# Whole-condition ToolSemantics Feedback — independent implementation check

## Decision

**allow** — the reviewed implementation matches plan digest
`76c57a0fd6aff39b39f105936d9952b14539a9917aa193a08ae0bab1ab478cd8`.
`sha256sum research/tool-semantics-whole-condition-feedback-plan.md` reproduced
that exact digest. No provider or E2E call was made during this check.

## Findings (fixed)

- None. No mechanical in-scope defect was found, so no production or test file
  was modified by this check.

## Findings (not fixed)

- None.

## Scope and compatibility review

- Reviewed: `agent_world/design.py` and `tests/test_design_semantics.py`.
  Read-only verification also covered `agent_world/graph.py`,
  `tests/test_graph_contracts.py`, the latest safe run proof, diagnosis, plan,
  matching cross-layer allow, and the applicable feedback guidance.
- Semantic Feedback now identifies the supplied path as exactly one observed
  occurrence, explicitly disclaims observation of any other occurrence, and
  instructs the model to inspect the complete immediately preceding proposal
  and repair every occurrence governed by the same condition and expected
  category. It remains a concrete next-user instruction requiring one complete
  JSON replacement and a whole-object self-check.
- Format Feedback remains root-wide (`path $`) and has no semantic
  all-occurrence claim.
- The EffectDraft diagnostic is acceptance-equivalent: direct finite JSON
  scalar or scalar-list of at most 32 values, or the exact frozen
  `{kind:"semantic_ref",semantic_index:<one-based index>}` object. Literal
  wrappers remain rejected; an unfrozen semantic reference and non-null
  `preserve`/`reject` retain their distinct diagnostics.
- The compiler accepted set, parser, node/edge declarations, graph correction
  ceiling, routes, fallback, sharding, Artifact/Work persistence, candidate and
  downstream contracts, Skills, and release/Observe boundaries remain unchanged
  by this approved two-file scope. `GraphRunner` still limits ToolSemantics to
  three proposals, and the tested operation evidence contains no raw rejected
  response or rendered Feedback.
- No `.trellis/spec/` update is needed: the existing debugging guide already
  requires framework-authored next-user feedback, complete replacement,
  whole-result self-check, and ephemeral rejected output. This recipient-level
  wording is an approved local realization, not a new reusable contract.

## Verification

- `uv run pytest -q tests/test_design_semantics.py::test_direct_feedback_keeps_format_root_wide_and_semantic_whole_condition tests/test_design_semantics.py::test_tool_semantics_strict_progress_uses_ephemeral_four_message_feedback tests/test_design_semantics.py::test_effect_value_acceptance_and_precise_rejection_conditions tests/test_design_semantics.py::test_shared_tool_format_feedback_reuses_only_ephemeral_rejected_output tests/test_graph_contracts.py::test_tool_semantics_third_invalid_proposal_stops_without_a_fourth_call tests/test_graph_contracts.py::test_tool_semantics_format_failure_never_admits_a_third_proposal` — **7 passed**.
- `uv run pytest` — **238 passed** (238 collected).
- `uv run ruff format --check .` — **pass** (22 files already formatted).
- `uv run ruff check .` — **pass**.
- `uv run mypy agent_world` — **pass** (13 source files).
- `uv run python -m compileall -q agent_world` — **pass**.
- `uv run pytest -q tests/test_legacy_firewall.py` — **2 passed**.

## Non-claims and next permitted proof

This is deterministic implementation evidence only. It does not prove that
Luna repairs every matching occurrence, that ToolSemantics commits, or any
later Design, Candidate, Integration, Judge, Registry, Direct E2E, Repair,
Expand, or Consumer/SFT/RL boundary.

**One exact frozen `reserve_tool` proof is permitted:** run the recorded
frozen-parent `design/tool_semantics[reserve_tool]` Luna leaf once with its
exact EvidenceGraph, WorldArchitecture, and SharedToolSemantics refs, then
read Observe immediately. A new terminal requires a new diagnosis; no fourth
proposal, blind retry, or E2E is authorized.

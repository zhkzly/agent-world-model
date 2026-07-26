# WorldRules Diagnostic and Ownership Report

## Scope and durable evidence

- Target coordinate: `design/world_rules` in captured scope
  `generate-job:ba03ff3dce4e303593c64e2d`.
- Initial evidence was a completed proposal-semantic failure whose only
  frontier issue was the non-actionable generic
  `framework_diagnostic_incomplete` at `semantic_output`.
- After feedback-boundary migration, one isolated real `grok-4.5` WorldRules
  node produced two typed `initial_state_rule_id_prefix` issues. That result
  had enough safe code/path/condition/category evidence to identify the next
  ownership defect; no raw provider output was retained or used.

## Four-way decision

| Owner | Decision | Evidence and repair |
| --- | --- | --- |
| Feedback / observability | Selected first | 26 direct WorldRules compiler `ValueError` sites could collapse into the generic fallback. They now produce typed safe diagnostics; the generic catch-all remains fail-closed for truly unknown defects. |
| Prompt | Selected after the typed ID evidence | The active WorldRules prompt omitted the exact reset/invariant section split, required families, and framework ownership of optional `rule_id`. It now states all three without relaxing validation. |
| Skill | Selected after the typed ID evidence | The tool-free Engineer Skill contained ToolSemantics guidance but no WorldRules ownership rules. It now carries durable, closed guidance for section families and framework-derived IDs. |
| Code / contract | Selected after the typed ID evidence | Both WorldRules sequence compilers accepted Agent-supplied mechanical IDs without deterministic prefixes. The final compiler canonicalizes supplied IDs away, derives `rule:state:<ordinal>` / `rule:world:<ordinal>`, and persists only the canonical source. |

Rule family remains Agent-owned and actionable. ID prefix/duplicate checks are
framework-owned, typed, observable, and non-retryable; they never enter an
Agent correction brief.

## Same-boundary inventory and proof

- Migrated all 26 direct bare-error sites in the seven WorldRules compiler
  validators (state shape, initial-state rules, tool-plan inventory, tool
  schema, tool-surface schema, tool inventory, world skeleton).
- Audited the active production `WorldRulesLeaf` prompt, generic prompt and
  transport/correction projection, Engineer Skill, all three legacy
  WorldRules prompt builders, both WorldRules sequence compilers, and source
  persistence. The generic base prompt, JSON envelope, and correction brief
  were not defective for the mechanics-only ID condition.
- Added constructed valid-input tests for typed diagnostic code/path/
  actionability/no-value-disclosure, structural bare-error absence, prompt and
  Skill projection, work-graph revision, and full `compile_world_rules`
  canonicalization from arbitrary Agent IDs to deterministic executable IDs.
- Focused WorldRules/Scheduler/test-node regressions: `128 passed`; Ruff and
  mypy passed.

## Real isolated confirmation

The single permitted fresh isolated `test-node` execution used the repaired
code and `grok-4.5`. Safe observability reports
`head_status=committed`, `validation_status=passed`,
`frontier_progress=resolved`, no failure code, and an empty frontier. The
enclosing scene is `committed` with no stuck coordinate. It is diagnostic-only
and non-releasable; no downstream node was dispatched.

## Supplementary test-run caveat

A broad `pytest tests/agent_world -x -vv` run passed through 51% but stalled
in the verifier cancellation/straggler test with no terminal diagnostic, so it
was interrupted and is not reported as green. Its test feedback is an
independent observability/async-cleanup investigation, not WorldRules evidence.

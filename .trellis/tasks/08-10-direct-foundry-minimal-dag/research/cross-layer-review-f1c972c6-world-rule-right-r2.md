# Research: cross-layer-review-f1c972c6-world-rule-right-r2

- Query: Review plan `f1c972c62d6b2d9478b70c24656453892901a3cd365c0938da46ae15954b1d0e`, revision 2/2, for the closed-union repair of `PredicateDraft.right` and its existing Direct WorldRules failure-record regression.
- Scope: internal, read-only cross-layer critic; one validator condition and focused regression only.
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `f1c972c62d6b2d9478b70c24656453892901a3cd365c0938da46ae15954b1d0e` (SHA-256 recomputed from the written revision).
- Plan lineage / revision: `world-rule-predicate-right`, revision 2/2 (final permitted revision).
- Scope classification: local validation-boundary correction. No graph, node, Prompt, schema, owner, retry, release, or downstream-contract change is authorized.
- Trigger and evidence: static diagnosis `diagnosis-world-rule-predicate-right.md`; no real execution or Observe scene exists or is inferred.
- Affected trust boundary: framework compilation of `PredicateDraft.right` before a Direct `world_rules` proposal can commit, plus the existing safe terminal persistence for rejection.

## Findings

Revision 2 resolves the sole revision-1 blocker. The current branch at `agent_world/design.py:345-378` can accept a non-dict before `set`, `.get`, and `dict` are reached. The plan instead requires a local `valid_right` guard that first establishes `dict` type and then accepts only the two unchanged exact shapes: literal or bounded semantic reference (`world-rule-predicate-right-plan.md:9-17`). Thus malformed dictionaries, `None`, and sequences cannot reach object-only operations; they take the existing exact-path `DesignError` route.

The preserved product target is: natural-language `EnvironmentRequest` -> evidence-grounded executable environment -> independent verification -> immutable Registry `EnvironmentPackage` -> safe Observe facts. This change advances only honest rejection of malformed WorldRules source; it makes no release or E2E claim.

```text
Direct WorldRules proposal
  -> Designer `_compile_rules` closed-union guard
  -> DesignError(`world_rules_invalid`, exact `.right` path)
  -> existing GraphRunner local-correction / fail transaction
  -> validation + route-free Finding + failed WorkRecord
  -> no committed WorldRules output; downstream work remains unavailable
```

Compatibility is explicit and unchanged:

- Designer remains the sole compiler of the Direct LLM RuleDraft (`design.md:304-317`; `node-contracts.md:282-307`). Both valid payload meanings remain semantically and structurally identical.
- `GraphRunner.execute` already catches `NodeExecutionError`, of which `DesignError` is the safe subtype, and `GraphRunner.fail` persists the validation, route-free Finding, and failed WorkRecord (`agent_world/graph.py:487-539`, `:699-784`). The plan does not alter it.
- Finding, WorkRecord, Observe, CandidateGraph, Repair, Expand, and Consumer receive no new shape or artifact. They continue to see only committed WorldRules artifacts; rejection produces the existing terminal record instead.

## Smallest permitted implementation and proof

Implement only the guarded `valid_right` closed union in `agent_world/design.py::_compile_rules`. Do not add a helper, schema, validator layer, node, retry, or control-plane mechanism.

The focused regression in `tests/test_design_semantics.py` must prove:

1. Exact literal and exact semantic-reference right shapes still compile.
2. `{}` and an unknown-kind object reject with `DesignError`.
3. `None` and `['kind', 'value']` reject with `DesignError`, never raw `ValueError`, `TypeError`, or `AttributeError`.
4. Two invalid proposals through the existing Direct `world_rules` transaction consume the one local correction and persist `world_rules_invalid` validation, route-free Finding, and failed WorkRecord with no WorldRules output.

The smallest deterministic and true handler-boundary proof is that existing Direct WorldRules transaction through `DesignExecutor._direct_rules` and `GraphRunner`, followed by inspection of its persisted records. It is not a provider, candidate-process, Judge, Registry, or live Direct proof.

## Non-claims and next permitted gate

- This allow does not claim the tests pass, the repair is implemented, or any live Direct, Repair, Expand, Consumer, Judge, Registry, or EnvironmentPackage behavior is proven.
- It does not authorize scope expansion beyond the specified condition and regression.
- The allow expires if this plan digest, its validation/persistence trust boundary, or the relevant execution scene changes.
- Next permitted gate: the main planner records this matching allow in the task context, then dispatches implementation of this exact local change followed by its focused deterministic checks. Any new consumer impact or proof failure requires a new diagnosis/plan/review lineage.

## Caveats / Not Found

- This was a static, read-only plan review; no production code or tests were modified or run.
- No external references were needed. No Observe scene exists for this static defect.

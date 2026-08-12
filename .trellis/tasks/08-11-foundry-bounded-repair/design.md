# Foundry bounded automatic repair — design

## Flow

```text
failed Work/Gate
  -> framework Finding
  -> RepairController.resolve(finding, graph declarations, ledger)
  -> RepairDecision
  -> new target revision with AgentCorrectionBrief
  -> dependency invalidation
  -> graph re-entry
  -> new terminal evaluation
```

`RepairController` is a small deterministic function/component owned by
Controller. It is not a Node, Agent or second graph runner.

## Contracts

```text
RepairDeclaration:
  finding_category, subject_kind, local_owner_coordinate
  optional_semantic_parent_coordinate, max_jump=1

RepairLedger:
  finding_lineage, same_owner_attempts, semantic_backjumps
  prior_blocking_claim_sets, prior_output_semantic_digests
  global_budget_lease_ref

WorkInvalidation:
  invalidation_id, invalidated_work_ref, repair_decision_ref
  replacement_work_ref?, reason_code

RepairDecision:
  finding_ref, target_coordinate, target_revision
  correction_brief_ref, invalidated_refs, retained_refs
  attempt_index, jump_distance, budget_lease_ref
  outcome: authorized | needs_human | exhausted | no_progress
```

Framework creates `AgentCorrectionBrief` from the exact violated condition,
observed safe evidence and expected output constraint. It is input data to the
original owner transaction, not control-plane instructions the model may edit.

Target selection order is fixed:

1. Re-resolve the subject Artifact envelope and producer WorkRecord, re-derive
   its owner, expected claim and dependency closure, and reject a mismatch with
   the immutable Finding.
2. Exact producer/owner of the Finding subject when locally repairable.
3. Its single declared semantic parent only when the local output cannot
   satisfy the violated condition.
4. Otherwise `needs_human`.

No-progress is true when the same blocking claim set remains and the relevant
committed output semantic digest does not change. A structurally different but
semantically equivalent model response does not reset the budget.

Invalidation follows immutable `WorkRecord.dependency_refs` from the replaced
revision. Sibling/unrelated refs survive. The Controller appends
`WorkInvalidation`; old Work records remain immutable and inspectable, while
the resolved Work view projects the invalidator. New Work records point at new
inputs and cannot accidentally adopt an invalidated predecessor.

## Proof boundary

The live proof must traverse a real model/Agent owner and a real candidate or
Judge boundary. Deterministic unit tests prove routing mechanics but cannot be
reported as repair completion. Observe is read after both failed and repaired
terminals.

## Non-designs

There is no learned router, LLM diagnosis node, generic retry decorator,
priority queue, scheduler service or repair plugin registry.

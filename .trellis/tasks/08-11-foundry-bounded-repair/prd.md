# Foundry bounded automatic repair

## Goal

Add the smallest framework-owned repair loop that can turn a real, precisely
attributed failed Work revision into a corrected revision without rerunning the
whole system, giving Judge routing authority or creating a scheduler platform.

This is child 2 of `08-11-foundry-complete-v1`.

## Explicit dependency

- Do not start until `08-10-direct-foundry-minimal-dag` has completed with an
  exact clean-worktree commit and frozen `ArtifactRef`, `WorkRecord`, `Finding`,
  graph-coordinate and package contracts.
- Record that commit and contract digest in this task before critic review.
- If the dependency meaning changes, this plan and its critic allow expire.

## Requirements

- Consume only framework-produced Findings. The stored owner/expected condition
  are evidence, not routing authority: Repair must re-derive owner from
  `Finding.subject_ref` -> ArtifactEnvelope producer -> Node owner table and
  reject any mismatch. Judge/model output cannot name a retry target,
  invalidation set, budget action or release action.
- Resolve the target from the reverified subject producer, exact WorkRecord
  dependency refs and the owning graph's closed repair declarations.
- Commit an immutable `RepairDecision` before redispatch. It records target,
  bounded data-only feedback, invalidated and retained refs, budget lease,
  attempt index, jump distance and outcome.
- Allow at most two same-owner revisions and one one-hop semantic-parent jump
  for a Finding lineage. Detect no progress and stop honestly.
- Recompute invalidation from dependency closure. Preserve unrelated Artifacts
  and completed Work. Never mutate Direct WorkRecords; append one immutable
  framework-owned `WorkInvalidation` per invalidated revision.
- Re-enter only `DesignGraph` or `CandidateGraph` at the selected coordinate;
  cross-graph repair returns to the Controller through one explicit result.
- Ambiguous ownership, a larger required jump, budget exhaustion or repeated
  no progress produces `needs_human`/non-release.
- Observe exposes safe revision, Finding, invalidation, retention and budget
  facts without becoming a router.

## Acceptance criteria

- [ ] Deterministic tests cover Finding owner/condition mismatch rejection,
  same-owner repair, one-hop backjump, append-only descendant invalidation,
  unrelated retention, ambiguity, no progress and budget exhaustion.
- [ ] A real negative execution creates a genuine validator/Integration/Judge
  Finding; no test directly fabricates the success-state RepairDecision.
- [ ] One authorized Agent/LLM owner receives bounded feedback, creates a fresh
  revision, and the affected graph reaches a new real terminal verdict.
- [ ] The proof shows exact before/after blocking claims and retained unrelated
  Artifact refs through Observe.
- [ ] Normal successful Direct execution remains unchanged and does not need to
  manufacture a Finding.
- [ ] No LLM Router, generic retry middleware, scheduler, callback system or
  second control authority is added.

## Out of scope

- Unbounded autonomous self-healing, arbitrary graph search, cross-request
  repair, human approval UI or repair-policy learning.
- Repairing unavailable providers, credentials or permissions by changing
  semantic Artifacts.
- Expand-specific selection policy; this child only provides reusable bounded
  graph revision behavior.

## Blocking open questions

None. Exact upstream commit/digest is a start gate, not a product decision.

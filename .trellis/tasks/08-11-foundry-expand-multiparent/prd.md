# Foundry Expand and multi-parent evolution

## Goal

Implement the core innovation beyond first-package generation: evolve released
environments toward user-directed or evidence-discovered capabilities, using
real technical documentation and one or several exact parent packages, while
reusing the same complete independent generation and release path.

This is child 3 of `08-11-foundry-complete-v1`.

## Explicit dependency

- Hard dependency: completed `08-10-direct-foundry-minimal-dag` commit with
  frozen DesignGraph, CandidateGraph, package, Registry and lineage contracts.
- Optional execution dependency: completed bounded-repair commit. Campaign
  candidates may use its repair behavior, but Campaign meaning and a successful
  proof cannot require a deliberately forced repair.
- Record all consumed commits/digests before critic review. Any shared contract
  drift expires this plan.

## Requirements

- `CampaignRequest` accepts exact/request/Pool anchors, a bounded direction,
  permitted technical source requests, operator allowlist, policy id, seed,
  independent budget and release profile.
- Framework freezes the exact CampaignRequest, release profile, eligible parent
  package/receipt/semantic refs, source requests and catalog revision,
  policy/operator revisions, seed and budget before the first `Policy.ask`.
- Before every selected parent is used, framework reads its exact current
  Registry record and persists a `PackageUseAdmission`. Quarantine,
  supersession, non-release or identity mismatch blocks the intent before
  Design/Build while leaving CampaignSnapshot bytes unchanged.
- Search/Fetch/Extract obtains real technical material; a Researcher Agent may
  synthesize bounded evidence-backed clues but cannot select parents, mutate
  code, judge or publish.
- V1 exposes only `ask`, `tell`, `should_stop` and implements deterministic
  `directed@1`; no generic policy/plugin platform.
- V1 supports the minimum tool-first semantic change needed for proofs:
  `ToolSurface` and `Composite`. Operator output is an untrusted typed intent;
  framework admission and Designer compilation remain authoritative.
- Designer receives safe parent semantics, admitted clues and intent and emits
  a complete child Design. Framework computes the authoritative non-empty
  `SemanticDelta`.
- Every child Design carries a complete newly compiled per-task-family
  `DifficultySchema`. An operator may change difficulty semantics only through
  the normal Curriculum/TaskRequirement design path; framework never unions
  parent levels or lets CandidateBuild define them.
- Only CandidateBuild receives exact verified read-only parent source closures,
  and only after Design commit. Framework never automatically merges source.
- Every child is a fresh self-contained candidate, independently integrated,
  judged and released or honestly rejected.
- `CandidateOutcome` keeps execution, hard-gate and release status separate and
  binds exact infrastructure, semantic-delta and lineage evidence. An
  infrastructure error cannot be scored as failed/low-fitness candidate
  quality; one generic status is forbidden.
- Semantic and implementation lineage are separate. Neither inherits a parent
  verdict.
- Observe exposes frozen snapshot, source/clue commitments, intents, policy
  checkpoints, candidate outcomes and released lineage safely.

## Acceptance criteria

- [ ] A real single-parent Campaign uses retrieved technical documentation,
  produces a non-empty tool/world/task semantic change and publishes a fresh
  independently judged child.
- [ ] A real multi-parent Campaign selects at least two exact released package
  digests and gives CandidateBuild their verified source closures read-only.
- [ ] The multi-parent child is self-contained and behaviorally proves at least
  one capability attributable to each parent plus one task requiring their
  integrated behavior.
- [ ] Each released child package cold-reads its own complete difficulty schema
  and valid selections through the shared Materializer/Judge contract; no
  parent-only or merged free-form difficulty domain survives.
- [ ] Parent evaluator/sealed/private state is never mounted; the child imports
  no mutable parent at runtime and inherits no verdict.
- [ ] At least one honest non-release CandidateOutcome is retained without
  stopping the Campaign unless policy/budget says so.
- [ ] Campaign can run with no training feedback. Removing optional capability
  priority input does not alter evidence, gates or release authority.
- [ ] A frozen Campaign resumes with byte-identical snapshot and Policy inputs
  after mutable release profile, source catalog or optional feedback changes.
  A post-freeze Registry quarantine/supersession instead appends a safe blocked
  admission and prevents parent use without mutating the snapshot.
- [ ] Candidate infrastructure error has mandatory evidence, remains distinct
  from hard-gate/release status and is excluded from candidate-quality ranking.
- [ ] Replacing `directed@1` behind the three-method interface would not require
  changes to DesignGraph, CandidateGraph, Runtime, Judge or Registry, but no
  second policy is implemented in v1.

## Out of scope

- Population-scale search, distributed campaigns, a general evolutionary
  framework, learned policy, arbitrary source-code merger or large operator
  catalog.
- Treating source diffs, parent count or model novelty scores as evolution
  success without a semantic delta and behavioral proof.
- EnvironmentFamily/composite runtime identities; the output remains one
  ordinary EnvironmentPackage.
- Requiring rollout/training feedback to run or release a Campaign.

## Blocking open questions

None. Real useful multi-parent composition is explicitly part of v1.

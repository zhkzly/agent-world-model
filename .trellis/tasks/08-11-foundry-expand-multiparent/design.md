# Foundry Expand and multi-parent evolution — design

## Campaign state machine

```text
CampaignRequest
  -> freeze CampaignSnapshot
  -> ExpansionSource Search/Fetch/Extract + Researcher synthesis
  -> Policy.ask
  -> framework admission
  -> current parent PackageUseAdmission
  -> ToolSurface or Composite operator intent
  -> DesignGraph
  -> CandidateGraph
  -> CandidateOutcome
  -> Policy.tell
  -> should_stop or next ask
```

`ExpandCampaign` is a bounded outer state machine, not a third generic graph.
It persists each transition so it can resume from the exact snapshot and policy
checkpoint without rerunning completed sources or inheriting mutable Registry
state.

## Closed v1 contracts

```text
CampaignRequest:
  anchors[], direction, source_specs[], operator_allowlist[]
  policy_id=directed@1, seed, budget, release_profile_ref

CampaignSnapshot:
  campaign_id, request_ref, release_profile_ref
  exact_parent_refs: tuple[EnvironmentPackageRef]
  exact_parent_semantic_refs[], source_requests[], source_catalog_revision
  direction, operator_revisions[], policy_revision
  seed, budget_lease_refs[], capability_priority_ref?

EvidenceClue:
  clue_id, source_record_refs[], claim, affected_dimensions[]
  confidence_class, limitations[]

MutationIntent:
  intent_id, parent_refs[], clue_refs[], operator_id
  parameters, target_dimensions[]

PolicyCheckpoint:
  campaign_id, round, considered_intent_refs[]
  outcome_refs[], remaining_budget, deterministic_state_digest

CandidateOutcome:
  intent_ref, design_ref, integration_ref?, judge_ref?
  execution_status: completed | infrastructure_error
  infrastructure_evidence_ref?
  hard_gate_status: passed | failed | inconclusive | not_run
  release_status: released | not_released
  package_ref?
  semantic_delta_ref, semantic_lineage_ref, implementation_lineage_ref
  coverage, diversity, fidelity_risk, cost, repair_depth
```

Every `exact_parent_ref` includes package id/version/package digest/manifest
digest/Registry receipt and exact release closure. Snapshot persistence binds
those refs plus the request/release/source/policy/operator revisions. Resume
never rewrites these bytes or changes Policy input from mutable profile,
catalog or feedback state. Separately, before every admitted intent uses a
selected parent, framework reads the current exact Registry record and appends
the parent-purpose `PackageUseAdmission`; quarantine, supersession,
non-release or identity mismatch blocks before Design/Build.

Campaign `StopDecision`, including `needs_human` and `budget_exhausted`, is not
a package release status. Infrastructure-error CandidateOutcome requires exact
evidence, retains the last factual hard-gate status, is always not released and
is excluded from candidate-quality ranking by `directed@1`.

`directed@1` deterministically ranks admitted parent/clue/operator combinations
against the explicit direction and remaining budget. Optional aggregate
capability feedback only contributes a bounded priority field; it cannot create
EvidenceClues or satisfy admission.

`ToolSurface` adds/removes/changes an Agent-visible tool contract based on real
evidence. `Composite` selects compatible semantic aspects from multiple parent
projections and defines an integrated target; it does not merge files. The
normal Designer reconstructs the full WorldSpec/Tool/Task/Verifier/
Implementation contract and framework computes the delta.

That complete Task contract includes newly compiled per-family
`DifficultySchema` values. Parent schemas are semantic evidence only: Designer
must emit a complete Curriculum, framework compiles it, and CandidateBuild,
Integration, Judge and the eventual Consumer use the exact child schema. No
automatic union, default level or candidate-authored domain is permitted.

## Parent source boundary

After child Design commit, framework re-resolves each exact parent package,
verifies receipt and source-tree digest, and materializes one read-only root
containing only candidate source closure, applicable dependencies and license
facts. CandidateBuild receives these roots plus the child Design and writes a
new workspace. Parent sealed/evaluator/Judge/Registry internals are excluded.

Useful multi-parent proof requires:

1. two exact released parent refs;
2. a child semantic delta naming meaningful aspects from both;
3. behavioral gates exercising a capability from each parent;
4. one materialized task whose success requires both capabilities;
5. a fresh package with no runtime parent dependency.

## Identity and lineage

Boundary-preserving evolution may create a new version of one package. A
substantial WorldBoundary change or multi-parent composition creates a new
package id. `SemanticLineage` records parent semantic refs and delta;
`ImplementationLineage` records exact parent/final source digests and bounded
physical reuse facts derived by framework scan.

## Observe

`observe campaign` projects snapshot, source outcomes, clues, ask/tell
checkpoints, parent-use admission verdict/reason and Registry revision,
admitted/rejected intents, candidate outcomes, budget and lineage. It omits
prompts, raw private source roots, credentials and evaluator data and has no
control methods.

Deterministic restart tests mutate release profile, source catalog and optional
feedback after freeze and require byte-identical snapshot/Policy inputs. A
separate post-freeze quarantine/supersession test requires the same unchanged
snapshot plus a blocked admission before Design/Build. Outcome decoding rejects
a generic combined status, missing infrastructure evidence or missing delta/
lineage refs.

## Anti-overdesign

The first implementation is one Python campaign component, one deterministic
policy and two small typed operators. It does not introduce dynamic registries,
policy plugins, a generic population store, a new graph engine or automatic
source conflict resolution.

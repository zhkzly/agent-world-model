# Agent World Foundry complete v1 — system design

## 1. Architectural rule

The system has three executable paths and one read-only plane:

```text
EnvironmentRequest -> Direct preparation -----------+
                                                     |
Registry parents + technical evidence -> Expand ----+-> DesignGraph
                                                          |
                                                          v
                                                   CandidateGraph
                                                          ^
                                                          |
                                                bounded RepairController
                                                          |
                                                          v
                                                       Registry
                                                          |
                                             Consumer -> Episode -> SFT / RL

durable Work / Artifact / Finding / Campaign / Registry / Episode facts
                                  -> Observe (read only)
```

Direct preparation and Expand do not share one giant loop. They produce the
same bounded `DesignRequest`; `DesignGraph` and `CandidateGraph` are the only
reusable generation graphs. Repair is deterministic control around failed Work
revisions. Consumer is a separate downstream service. Observe is a projection,
not an execution graph.

## 2. Authority and execution taxonomy

| Boundary | Owner | Model execution |
| --- | --- | --- |
| Job admission, Artifact commit, budgets, routing, invalidation, release | Framework / Controller | None |
| Semantic source proposals | Designer-owned Work | `DIRECT_LLM` |
| Research synthesis, build planning, challenge and code generation | Explicit role Work | Tool-enabled `AGENT` with one Skill |
| Schema compilation, source scan, gates, reward, termination | Framework | None |
| Generated Runtime | Untrusted isolated `CANDIDATE_PROCESS` | None by default |
| Independent verdict | Judge framework over real candidate execution | No routing authority |
| Registry publication | Registry framework | None |
| Observe | Read-only framework projection | None |

One compact `NodeSpec` carries coordinate, owner, input/output ports, execution
kind and terminal effect. One `EdgeSpec` maps committed output Artifact ports to
consumer input ports and declares deterministic success/failure routing. The
runner dispatches by `execution_kind`; there are no Node subclasses.

Judge produces claim verdicts and Findings. It does not know graph topology.
`RepairController` resolves a Finding's subject provenance against graph-local
repair declarations and immutable dependencies.

## 3. Reusable graph boundaries

### 3.1 DesignGraph

```text
DesignRequest
  -> research plan/acquisition/synthesis
  -> world architecture
  -> shared and per-tool semantics
  -> world rules
  -> curriculum/task requirements
  -> deterministic compiler + Modeling Gate
  -> EnvironmentDesign
```

Direct uses an empty parent/delta projection. Expand supplies safe exact-parent
semantic refs, admitted evidence clues and an admitted mutation intent. Both
produce a complete design; neither passes a patch as a Design.

### 3.2 CandidateGraph

```text
EnvironmentDesign -> BuildImplementationPlan ----+
                                                 +-> CandidateBuild
EnvironmentDesign -> VerifierIntent -> compiler -+       |
                                                         v
                                                    source closure
                                                         |
                                                         v
                                                    Integration
                                                         |
                                                         v
                                            independent Judge -> Package -> Registry
```

CandidateBuild receives a writable fresh child workspace. On Expand only, it
may also receive verified read-only parent source roots after the complete child
Design commit. Integration begins from the candidate and Design; Judge joins an
exact passed Integration with the compiled verifier. A failed Integration is
terminal until RepairController authorizes a new revision.

## 4. Shared durable contracts

The field meanings below and the compatibility table are binding before Direct
implementation. Child designs may choose mechanical Python/Pydantic names, but
no shared field, authority, consumer mapping or persistence rule is deferred.

```text
ArtifactRef:
  artifact_id, kind, digest, package/run-relative path, media_type
  # producer/dependencies are resolved from the immutable ArtifactEnvelope

WorkRecord:
  coordinate, owner, execution_kind, semantic_revision_digest
  input_refs, dependency_refs, output_refs
  validation_ref?, assurance_refs, finding_refs, status, safe_code?
  invalidated_by=null

WorkInvalidation:
  invalidation_id, invalidated_work_ref, repair_decision_ref
  replacement_work_ref?, reason_code

Finding:
  finding_id, failed_claim_ref, subject_ref, evidence_refs
  expected_condition, owner, code, category, severity
  blocks_release, fingerprint

RepairDecision:
  finding_ref, target_coordinate, target_revision
  feedback_ref, invalidated_refs, retained_refs
  attempt_index, jump_distance, budget_lease_ref, outcome

EnvironmentPackageRef:
  package_id, version, package_digest, manifest_digest, registry_receipt_ref
  design_ref, candidate_manifest_ref, judge_report_ref, integration_ref
  semantic_lineage_ref, implementation_lineage_ref

DifficultySchema:
  task_family_id, ordered dimensions[{name, meaning,
    ordered levels[{name, meaning}]}], key_order, schema_digest

DifficultySelection:
  closed ordered mapping[str, str]  # every schema key exactly once

PackageUseAdmission:
  admission_id, purpose: campaign_parent | episode
  package_ref, registry_record_ref, registry_status
  verdict: admitted | blocked
  reason_code: currently_released | not_released | quarantined | superseded |
               identity_mismatch
```

Only framework code computes digests, sizes, dependency closures, Findings,
RepairDecisions, manifests and release facts.

`WorkRecord.invalidated_by=null` is the immutable Direct baseline. Repair never
mutates that record; it appends one framework-owned `WorkInvalidation`, and the
resolved Work view projects its `repair_decision_ref` as `invalidated_by`. This
keeps invalidation queryable without implementing RepairController in Direct or
overwriting history.

### 4.1 Parent-owned compatibility table

These meanings must be implemented by the Direct child before its first code
change. They are inert durable handoffs, not dormant Repair, Campaign or
Consumer control logic.

| Shared handoff | Producer and closed field meaning | Framework owner | Immediate and later consumers | Persistence and invalidation | Safe Observe projection | Deterministic compatibility test |
| --- | --- | --- | --- | --- | --- | --- |
| `NodeSpec` / `WorkRecord` | Static graph declares `execution_kind = FRAMEWORK | DIRECT_LLM | AGENT | CANDIDATE_PROCESS`; terminal Work records exact ordered input refs, direct causal dependency refs, outputs, validation/assurance/Finding refs and baseline `invalidated_by=null`. `CANDIDATE_PROCESS` means an untrusted process is the execution boundary while the component owner still validates and commits. | Node owner validates; Controller persists; model/candidate never writes it. | Runner and Observe immediately; Repair invalidation, Registry closure and final dossier later. | Immutable WorkRecord in run store. Repair later appends `WorkInvalidation`; descendants are selected from `dependency_refs`, never stage names. | coordinate/revision, owner, execution kind, dependency/output IDs, status and resolved invalidator ref only. | Round-trip every execution kind; reject missing/reordered dependencies and non-framework `invalidated_by`; prove Integration/Judge process execution does not transfer commit authority. |
| `Finding` | `finding_id`, failed claim, subject, nonempty evidence, expected condition, framework-derived owner domain, safe code/category/severity, `blocks_release`, fingerprint. It contains no target coordinate, retry, jump, budget, invalidation or release action. | Validator/Judge proposes evidence; owning framework Gate constructs and commits the Finding. | Direct terminal/Observe immediately; Repair re-verification and release closure later. | Immutable Artifact. Repair recomputes owner from subject envelope + owner table and rejects a mismatching stored owner before routing. | safe id, subject/claim/evidence commitments, expected condition, owner domain, severity and blocking effect. | Reject model-authored or mismatched owner, absent evidence/condition, routing fields and inconsistent severity/`blocks_release`. |
| Released `EnvironmentPackageRef` | Registry emits exact package id/version/package digest/manifest digest/receipt plus Design, CandidateManifest, passed Integration, Judge and separate semantic/implementation lineage refs. Direct lineage has `origin=direct` and no parents. | Package node builds closure; Registry cold-reads and alone emits the released ref/receipt. | Observe immediately; Campaign parent admission and Suite admission later. | Package bytes/manifest are immutable Registry content; ref and receipt are run Artifacts. Any digest/receipt mismatch makes the ref inadmissible, never repaired in place. | package coordinate/digests, safe lineage refs, verdict refs and receipt commitment. | Cold-read from another cwd, rehash bytes/manifest, verify receipt and exact passed closure; reject omitted/mismatched lineage or verdict refs. |
| `DifficultySchema` / `DifficultySelection` | Curriculum proposes ordered semantic dimensions and 2..5 levels per dimension; framework compiles a per-family schema and requires every key once in declaration order with one admitted level. TaskRequirement cannot redefine it and Materializer can only exact-echo a valid selection. | Designer framework compiles/commits; Integration/Judge and Consumer validate; candidate and caller have no schema authority. | TaskRequirement, CandidateBuild contract, Integration/Judge and package immediately; Expand rebuilt Design and Consumer Episode later. | Schema digest is bound into TaskRequirement, EnvironmentDesign, `tasks/curriculum.json`, protocol and manifest. A semantic change creates a new Design/package; it never mutates a released schema. | task family, dimension/level names and schema commitment; no generated private values. | Reject missing/extra/duplicate/reordered/unknown values, prove paired admitted levels change goal or initial state, cold-read same digest, and admit future EpisodeRequest against that exact schema. |
| `CampaignSnapshot` / package-use admission / `CandidateOutcome` | Snapshot binds request ref, release-profile ref, exact parent package+receipt+semantic refs, frozen source requests/catalog revision, policy/operator revisions, direction, seed and budget leases. Each selected parent use has a separate current-status `PackageUseAdmission`. Outcome separately records execution, hard-gate and release status plus infrastructure/delta/lineage evidence. | Registry owns current release status; Campaign framework records admission and persists snapshots/outcomes; Policy only proposes selection. CandidateGraph/Registry produce outcome facts. | Policy ask/tell and Observe; final dossier and optional Consumer selection later. | Snapshot/checkpoint/outcome are immutable or append-only. Current Registry checks may append an admission fact but never rewrite a resumed snapshot or its Policy inputs; current profile/catalog changes remain irrelevant. | safe snapshot commitments, admission verdict/reason and Registry revision, policy round, intent/outcome statuses, budget and lineage; no parent source or credentials. | Freeze/restart, then quarantine/supersede a parent: snapshot bytes stay identical and use is blocked before Design/Build. Reject ambiguous outcome status, missing infrastructure evidence or missing delta/lineage evidence. |
| `SuiteSnapshot` / package-use admission / Episode | Suite contains nonempty exact `EnvironmentPackageRef`s, therefore id/version/package digest/manifest digest/receipt and release closure, plus task selection and seed policy. Public Episode request binds one member and selection fields only; private Materializer output supplies reset state. | Registry owns current release status; Consumer framework records admission, revalidates package/receipt, materializes the task privately and computes reward/termination. | Episode service, SFT exporter, RL adapter and Observe. | Suite remains immutable. Every new Episode appends a current-status admission; changed bytes/receipt or quarantine/supersession blocks startup without changing Suite. Private materialization is scoped to the Episode and never enters public serialization. | suite/package commitments, admission verdict/reason and Registry revision, public task commitment, lifecycle, public reward/termination only. | Resolve across cwd/restart; quarantine/supersede after freeze and prove unchanged Suite plus blocked Episode. Reject caller `initial_config`; private canaries cover API, SFT, RL, logs and Observe. |

Changing any row's meaning invalidates the parent allow and every uncompleted
child allow that consumes it.

### 4.2 Expand contracts

```text
CampaignRequest:
  anchor_refs[], direction, source_specs[], operator_allowlist[]
  policy_id, seed, budget, release_profile_ref

CampaignSnapshot:
  campaign_id, request_ref, release_profile_ref
  exact_parent_refs[], exact_parent_semantic_refs[]
  frozen_source_requests[], source_catalog_revision
  direction, operator_revisions[], policy_revision, seed, budget_leases
  optional_capability_priority_ref

MutationIntent:
  intent_id, selected_parent_refs[], clue_refs[], operator_id
  bounded_parameters, target_dimensions

SemanticDelta:
  exact_parent_semantic_refs[], operator_id, changed_subjects[]
  changed_tool_world_task_aspects[], evidence_refs[], identity_decision

CandidateOutcome:
  intent_ref, design_ref
  execution_status: completed | infrastructure_error
  infrastructure_evidence_ref?
  hard_gate_status: passed | failed | inconclusive | not_run
  release_status: released | not_released
  package_ref?, semantic_descriptor, coverage_descriptor
  diversity_descriptor, fidelity_risk, cost, repair_depth, lineage_refs[]
```

Policy has only `ask`, `tell` and `should_stop`. `directed@1` is the sole v1
policy. Framework admission freezes and revalidates parent/source/operator
eligibility. Before each admitted intent uses a selected parent, framework
reads the exact current Registry record and appends `PackageUseAdmission`.
`quarantined`, `superseded`, non-released or identity-mismatched status blocks
that use before Design/Build without mutating CampaignSnapshot. Policy never
merges code or changes release facts.

`needs_human` and `budget_exhausted` are Campaign `StopDecision` outcomes, not
package release statuses. An infrastructure-error CandidateOutcome requires an
exact evidence ref; its last known hard-gate status remains factual and its
release status is `not_released`. Policy and Observe keep it out of candidate-
quality scoring.

For multiple parents, framework resolves every exact Registry package and
creates one bounded read-only `ParentSourceClosure` per digest containing only
candidate source, applicable dependency metadata and license facts. Designer
sees semantic projections, not source. CandidateBuild may reuse/adapt/combine
the roots into one fresh self-contained child. Framework performs no semantic
file merge. A child cannot import a parent at runtime.

`SemanticLineage` answers which environment meanings changed;
`ImplementationLineage` answers which exact source closures were available and
what final physical closure was produced. Neither carries a Judge verdict.

### 4.3 Consumer contracts

```text
SuiteSnapshot:
  suite_id, exact_package_refs: nonempty tuple[EnvironmentPackageRef]
  task_selection, seed_policy, created_at, snapshot_digest

EpisodeRequest:
  suite_ref, package_ref, task_type, seed, actor
  difficulty: DifficultySelection for exact package TaskRequirement

MaterializedEpisodeInput:  # framework-private; never publicly serialized
  episode_request_ref, materializer_result_ref
  public_task, initial_config, evaluator_goal

PublicTask:
  episode_id, public_instruction, visible_actor, tool_schemas

EpisodeAction:
  episode_id, step_index, tool_id, arguments, idempotency_key

EpisodeStep:
  observation, public_result?, public_error?, reward, terminated, truncated

EpisodeResult:
  episode_id, package_ref, task_commitment, public_trajectory_ref
  total_reward, termination_reason, step_count
```

Private evaluator goals, full state, sealed cases, verifier IR and release
policy never enter these public records. The framework materializes tasks and
computes reward/termination. Before materialization, it appends a current
Registry `PackageUseAdmission`; any blocked result ends startup while the Suite
stays immutable. The public caller cannot provide `initial_config`.
Materializer returns it inside `MaterializedEpisodeInput`; Consumer passes it
only to Runtime reset and excludes it from public APIs, logs, SFT, RL and
Observe. The SFT exporter maps public trajectories to one documented training-
row schema. The RL adapter only translates reset/step; it does not own
environment truth.
Consumer loads and validates the exact package `DifficultySchema` before
calling Materializer. It rejects a selection with missing, extra, duplicate,
reordered or unknown values and never creates a Consumer-only level domain.

## 5. Repair state transition

```text
terminal failed Work/Gate
  -> framework Finding committed
  -> deterministic owner lookup
  -> budget/no-progress/ambiguity checks
  -> RepairDecision
  -> new target Work revision with bounded feedback
  -> invalidate dependency descendants
  -> resume owning graph at the target coordinate
```

Same-owner revisions are capped at two and one-hop semantic backjump at one per
Finding lineage. No progress means the blocking claim set and relevant output
semantics did not improve. Ambiguous ownership, exhausted budget or a required
larger jump becomes honest `needs_human`/non-release. Repair does not become a
generic scheduler.

## 6. Observe read model

Observe projects the same durable records at four levels:

- L0: Direct run, Campaign, Suite/Episode and terminal release/non-release.
- L1: graph or campaign topology and current coordinates.
- L2: Work revisions, repair transitions, policy checkpoints and Episode steps.
- L3: safe Artifact refs, Finding claims, evidence commitments and Registry
  receipts.

Blocked package-use admission is shown as the exact package coordinate,
purpose, current Registry revision, verdict and closed safe reason code. The
snapshot remains visible as the unchanged historical selection fact.

Observe can repeat digest/receipt checks before displaying `released`, but it
cannot produce or modify the release fact. It stores safe commitments and
counts rather than prompts, secrets, sealed data, private state or raw source.

## 7. Runtime and development model selection are separate

Runtime product routes remain minimal:

| Route | Primary | Fallback | Purpose |
| --- | --- | --- | --- |
| `direct` | `gpt-5.6-luna` | `gpt-5.3-codex-spark` | Prompt-only structured semantic work |
| `agent` | `gpt-5.6-luna` | `gpt-5.3-codex-spark` | Real Codex SDK session + Skill + tools + workspace |

Search/Fetch/Extract providers are Research tools, not model routes.

Development subagents are dispatched separately and always explicitly:

| Work | Provider/model | Access |
| --- | --- | --- |
| System research and cross-layer critic | Codex `gpt-5.6-terra` | Fresh, read-only except task `research/` record |
| Ordinary implementation | Codex `gpt-5.6-terra` | Child worktree write scope |
| Ordinary check | Codex `gpt-5.6-terra` | Review plus mechanical fixes only |
| Failure diagnosis / cross-layer investigation | Codex `gpt-5.6-terra` | Read-only evidence plus task `research/` record |

Every development-worker spawn includes
`--provider codex --model gpt-5.6-terra`, even though the three Trellis agent
profiles are also pinned to Terra. The explicit spawn and resulting
review/proof record retain the resolved model identity. Neither mechanism
changes the runtime product route table above.

## 8. Delivery and migration

- Product edits happen only in the clean `foundry-direct-graph` worktree.
- Children execute sequentially against exact predecessor commits; each child
  may use a short descendant branch if needed, but merges only after its own
  proof and check.
- Parent completion is a final integration review/dossier, not another
  orchestration implementation.
- Existing legacy code is neither ported nor kept as a compatibility fallback.
  A source-reference firewall rejects imports or runtime references to it.

## 9. Anti-overdesign budget

V1 adds only two static domain graphs, one deterministic repair controller, one
bounded campaign with one policy, the minimum semantic operators needed for the
real proofs, one Consumer/Episode service, one SFT exporter, one thin RL
adapter and read-only Observe projections.

Any proposal for a generic scheduler, dynamic graph/plugin system, arbitrary
merge engine, population service, trainer, permission manager, profile DSL,
callback framework or compatibility layer is blocked unless a current
acceptance criterion cannot be met without it.

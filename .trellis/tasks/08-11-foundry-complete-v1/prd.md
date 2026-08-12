# Agent World Foundry complete v1

## Goal and product value

Deliver one coherent v1 of the Agent World environment-generation system:
an arbitrary natural-language need can become an evidence-grounded,
executable, independently verified and Registry-published
`EnvironmentPackage`; bounded failures can be repaired; released environments
can evolve from real technical evidence and one or several exact parents; and
the resulting packages can drive leak-free SFT data and online RL Episodes.

This parent task owns the shared contracts, child ordering and final integrated
acceptance. It is not itself a product-code implementation target.

The source of truth remains `docs/agent-world-environment-generation.zh.md`.
This task deliberately chooses the smallest complete v1 of that product rather
than reproducing the legacy scheduler, StateGraph or compatibility paths.

## Confirmed facts

- The clean implementation lineage is
  `/home/kelong/pycodes/foundry-direct-graph`, branch
  `foundry-direct-graph`, currently based on `9562c05` and clean. Product code
  must be implemented there, not by extracting behavior from the dirty legacy
  root.
- The cleanroom has a real Direct spine and minimal Observe, but not the agreed
  graph contracts, automatic repair, Expand campaign, real multi-parent proof,
  or Consumer/SFT/RL path.
- Direct and Expand must converge on the same complete Design -> Build ->
  Integration -> independent Judge -> Registry trust path. Expand is a separate
  outer campaign, not a late Direct node.
- Multiple parents are exact released environment packages/source closures,
  not multiple policy rules. A child is self-contained and inherits no parent
  verdict.
- Consumer and training are downstream of exact Registry packages. Removing
  all training adapters must leave Direct and Expand unchanged.
- Observe is a read-only projection of durable facts. It never routes, retries,
  judges, mutates or publishes.
- The previous Direct-only critic allow for digest `afad1826...` expired when
  the scope broadened to complete v1.
- A frozen Campaign/Suite keeps exact bytes, but it is not a permanent license
  to use a package. Every attempted parent use and every new Episode must read
  the package's current Registry status; quarantine or supersession blocks the
  use without rewriting the snapshot.
- Candidate infrastructure failure is not candidate quality. It has an
  explicit execution status and evidence, separate from hard-gate and release
  status.
- `initial_config` is private Materializer output. A training caller selects
  task parameters but cannot provide, read or serialize the Runtime reset
  configuration.
- Difficulty is a package-owned task contract, not a free-form caller or
  candidate label. Curriculum proposes bounded dimensions/levels once,
  framework compiles one exact per-family `DifficultySchema`, and Direct,
  Expand, Judge, package and Consumer reuse it without independent widening.

## System paths and task map

| Child | Deliverable | Explicit dependency |
| --- | --- | --- |
| `08-10-direct-foundry-minimal-dag` | Shared Artifact/Work/package foundation, `DesignGraph`, `CandidateGraph`, canonical Runtime/Materializer, one real Direct release | This parent contract and source of truth only |
| `08-11-foundry-bounded-repair` | Deterministic bounded repair with revision/invalidation evidence and one real negative-to-repaired proof | Completed Direct child at an exact commit and its frozen Artifact/Finding contracts |
| `08-11-foundry-expand-multiparent` | Documentation-grounded single-parent evolution and useful real multi-parent composition | Completed Direct child; Repair may be reused but Expand success must not depend on a forced repair |
| `08-11-foundry-consumer-sft-rl` | Exact-package Suite, isolated public Episodes, one SFT export and one online RL proof | Frozen Registry/package/Runtime contracts; final acceptance consumes a released Expand package |

Parent/child position is not treated as a dependency mechanism. Every child
must repeat its dependency and refuse to start against a different or
unreviewed upstream contract.

## Requirements

### R1. One product architecture and one clean implementation lineage

- All children implement in the clean `foundry-direct-graph` lineage through
  ordered commits or descendant branches; no child imports or copies legacy
  runtime/control-plane code.
- The five product authorities remain `FoundryController`,
  `EnvironmentDesigner`, `EnvironmentBuilder`, `EnvironmentJudge` and
  `EnvironmentRegistry`. Repair, Campaign, Consumer, graph execution and
  Observe remain small internal mechanisms.
- There is one Artifact authority, one Judge verdict, one Release Kernel and
  one Registry publication path.

### R2. Small domain graphs, not a workflow platform

- `DesignGraph` converts a bounded `DesignRequest` into a complete compiled
  `EnvironmentDesign`.
- `CandidateGraph` converts that design into an integrated, independently
  judged, optionally released `EnvironmentPackage`.
- A node is one execution transaction. Its route is one of `FRAMEWORK`,
  `DIRECT_LLM`, `AGENT` or `CANDIDATE_PROCESS`; roles do not require subclasses.
- Edges carry framework-validated Artifact refs and deterministic routing.
  Raw model output never crosses an edge.
- No generic scheduler product, dynamic node registry, YAML graph DSL,
  callback/event bus, plugin framework or graph inheritance hierarchy is in
  scope.

### R3. Shared contracts are frozen before child implementation

The parent design must define the cross-child meaning and authority of:

- `ArtifactRef`, `WorkRecord`, `Finding`, `RepairDecision` and invalidation;
- `EnvironmentDesign`, candidate source closure, `EnvironmentPackageRef`,
  Registry receipt and semantic/implementation lineage;
- framework-owned package-use admission against current Registry status,
  without mutating a frozen Campaign/Suite;
- framework-compiled per-task-family `DifficultySchema` and closed ordered
  `DifficultySelection`, shared by Materializer, Judge, package and Consumer;
- `CampaignRequest`, frozen campaign snapshot, evidence clue,
  `MutationIntent`, `SemanticDelta` and `CandidateOutcome`;
- multi-parent admission, read-only parent source closure and self-contained
  child rules;
- `SuiteSnapshot`, `PublicTask`, Episode request/action/step/result,
  framework-owned reward and termination;
- safe Observe scenes for Direct run, repair revision, Campaign and Episode.

Each child may add private fields only when it preserves these meanings. Any
shared contract change expires downstream critic approvals.

### R4. Direct generation

- One fresh, non-fixture natural-language request must use real research,
  model/Agent calls, candidate process isolation, independent Judge and
  Registry publication.
- Runtime supports parameterized task materialization plus handshake,
  `reset`, `invoke`, private snapshot and close with unknown seeds.
- Integration failure stops before Judge and Registry. Release binds the exact
  passed Integration, Design and candidate closure.

### R5. Bounded automatic repair

- Judge and validators produce route-free Findings with exact subject,
  evidence, owner and violated condition.
- Framework-owned deterministic rules select the smallest owning Work; no LLM
  Router or Judge routing field is introduced.
- The v1 budget allows at most two same-owner revisions and at most one
  one-hop semantic backjump for one Finding lineage, with global no-progress
  detection and honest `needs_human`/non-release on ambiguity or exhaustion.
- Descendants are invalidated from immutable dependency closure; unrelated
  Artifacts are retained.

### R6. Expand and useful multi-parent evolution

- `ExpandCampaign` freezes exact parent refs, direction, real technical-source
  requests, operator allowlist, seed and independent budget before `ask`.
- Framework rechecks every selected parent's exact current Registry status at
  use time. `quarantined`, `superseded`, non-released or identity-mismatched
  packages produce a durable blocked admission fact and never reach Design or
  Build; the frozen snapshot itself remains unchanged.
- v1 implements one bounded `directed@1` policy and the smallest useful
  semantic operators; it does not build a general policy platform.
- Policy selects, Operator expresses a typed semantic mutation, Designer
  rebuilds a complete child Design, and only CandidateBuild may receive
  verified parent source closures after Design commit.
- Single-parent and multi-parent children run the same CandidateGraph and earn
  fresh Integration, Judge and Registry results.
- `CandidateOutcome` separately records execution, hard-gate and release
  status. Infrastructure error requires exact evidence and is never ranked as
  a failed or low-fitness candidate.
- A useful multi-parent success must demonstrate at least one independently
  verified capability from each of two exact released parents and at least one
  task requiring their integrated behavior. Mounting two roots or copying two
  files is not success.

### R7. Observe everywhere, authority nowhere

- Every key graph family, repair revision, campaign decision, release and
  Episode emits durable safe facts from which Observe projects L0 system,
  L1 graph/campaign, L2 node/revision and L3 Artifact/Finding evidence views.
- Observe excludes credentials, prompts, private workspaces, raw candidate
  source, sealed cases, evaluator goals and private state.
- Product Alignment Checkpoints are written at key child/proof/release
  boundaries and explicitly state what remains unproved.

### R8. Consumer, SFT and RL remain downstream

- Consumer resolves exact package digests into an immutable Suite snapshot and
  launches isolated Episodes through a framework-owned service.
- Every new Episode obtains a current Registry admission result. Quarantine,
  supersession, non-release or identity mismatch blocks startup without
  mutating the Suite.
- The public Episode request contains only suite/package and task-selection
  fields. Framework invokes the untrusted Materializer and carries its
  `initial_config` to Runtime through a private internal handoff that is absent
  from public APIs, SFT rows, RL input, logs and Observe.
- Training code sees only PublicTask, observation, public tool schema/action,
  public result/error, scalar reward and termination.
- One SFT exporter records a leak-free public trajectory. One thin online RL
  adapter drives the same Episode API; no optimizer or training framework is
  implemented in Foundry.
- Optional aggregate capability feedback may rank future Expand candidates but
  is neither world evidence nor a release gate. Expand works when it is absent.

### R9. Development critic and subagent dispatch

- The cross-layer critic is a development-time read-only gate, never a runtime
  node. A parent review spans every affected graph/subsystem; each child also
  receives a fresh review of its own producer -> consumer -> downstream chain.
- The current Direct-only wording in the critic Skill must be generalized to
  the complete-v1 scope before product implementation, without creating a
  second planning framework.
- The derived `docs/direct-rewrite-execution-map.zh.md` must be minimally
  synchronized: retain its node/executor taxonomy, but replace its stale
  Direct-only first-slice exclusions with this parent/child task map. The
  canonical product document remains authoritative.
- Every independent Codex worker is dispatched with an explicit model; model
  inheritance from the main session is forbidden for this task tree.
- System research, cross-layer critic, implementation and check workers are
  each spawned with explicit `--provider codex --model gpt-5.6-terra`; no
  child may inherit or omit its development-worker model. Runtime product
  `direct`/`agent` routes remain a separate configuration.

## Acceptance criteria

- [ ] All four children are independently planned, critic-allowed,
      implemented, checked and archived against explicit upstream commits.
- [ ] Every declared development research/critic/implement/check dispatch in
      the parent and children explicitly selects Codex `gpt-5.6-terra`; the
      runtime product route table is unchanged by that development-only rule.
- [ ] A fresh real Direct request publishes package `P_direct`; disabling any
  required real backend fails honestly rather than selecting a fixture or
  template path.
- [ ] A separate real negative proof produces a precise Finding, performs one
  bounded repair, retains unrelated Artifacts and reaches a fresh verdict; its
  revision history is visible through Observe.
- [ ] A real documentation-grounded single-parent Campaign publishes a child
  with a non-empty semantic delta and fresh verdict.
- [ ] A post-freeze parent quarantine/supersession leaves CampaignSnapshot
  bytes unchanged but records a safe blocked-use admission and prevents Design
  or Build; infrastructure failure remains separately evidenced and is not
  scored as candidate quality.
- [ ] A real Campaign selects two exact released parents and publishes one
  self-contained child whose tests prove a capability from each parent plus an
  integrated cross-parent task; semantic and implementation lineage are both
  recorded without inherited verdicts.
- [ ] An immutable Suite including an exact released Expand package executes
  unknown-seed isolated Episodes, exports one leak-free SFT trajectory and
  completes one online RL Episode through the same public protocol.
- [ ] A post-freeze package quarantine/supersession leaves SuiteSnapshot bytes
      unchanged but blocks a new Episode, and no caller can inject or observe
      Materializer `initial_config` through API, SFT, RL, logs or Observe.
- [ ] Direct and every evolved child package carry one cold-readable difficulty
      schema per task family; Materializer/Judge and Consumer accept the same
      complete ordered selections and reject missing, extra, duplicate,
      reordered or unknown levels before candidate use.
- [ ] Removing Consumer/training adapters leaves Direct and Expand tests and
  real entry points functional; removing capability feedback leaves Campaign
  admission/release semantics unchanged.
- [ ] Observe reconstructs the linked Direct, repair, Campaign, package and
  Episode evidence without holding control authority or exposing private data.
- [ ] Lint, type checking, deterministic tests, package-relative execution,
  offline build policy, secret scan and a legacy-reference firewall pass.
- [ ] Final integration evidence contains exact commits, package digests,
  Artifact/Work refs, Registry receipts and honest non-claims; graph tests or
  model JSON alone are never reported as product completion.

## Out of scope

- A generic graph/workflow/scheduler product, distributed execution or event
  bus.
- A policy/plugin DSL, automatic arbitrary source merger, population-scale
  AlphaEvolve reproduction or a large operator catalog.
- A training framework, optimizer, model-serving layer or token-accounting
  platform.
- A configurable permission/capability/profile system around Codex SDK.
- Legacy `awm` CLI, runtime ABI v1, replay compatibility, fixed environment
  registries, fixed task ids or hidden fixture success paths.
- Claiming broad environment diversity, training quality improvement or
  production scalability from the bounded v1 proofs.

## Blocking open questions

None. The user approved the complete-v1 boundary and the current-use Registry
eligibility, infrastructure-outcome and private-reset policies on 2026-08-11.

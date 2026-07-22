# Feedback / Pipeline Architecture Audit

Status: planning evidence, not an implementation claim.

## Project purpose and decision rule

The product turns a natural-language environment need into a genuinely executable,
programmatic Agent environment that can later be consumed by rollout/evaluation/veRL.
The generated Runtime, not an LLM text simulation, owns state transition.  Code owns
workflow authority, Artifact readiness, budgets, validation, repair, invalidation and
release.  Agents own bounded research, semantic design, code generation and semantic
challenge.  Direct Generation must work without Discovery, Evolve or training feedback;
Evolve must expand coverage through the same trusted generation path.

No architecture change is accepted merely because it looks cleaner.  It must bind to:

1. a preserved real failure or performance case;
2. an executable regression that fails for the old causal mechanism; or
3. an explicitly labelled hypothesis that must be reproduced before the change ships.

Mocks, template success paths and fixed hotel-specific branches are not evidence.

## Preserved real bad-case corpus

### BC-01: seven hotel Direct attempts never crossed Design

Artifact store: `.agent-world-live/batched-hotel/state/artifacts`.
Request: `hotel-booking-batched-20260719-01`.

| Run | Terminal failure |
|---|---|
| `run:4b7ce4c7b15149fca96da25bb72e1160` | `generation_cancelled` |
| `run:96aafaf42b214e92b2a28c6151daf2e2` | `design_agent.environment-engineer.output` |
| `run:128002f281ad4d5a8f064374a0db7eae` | `design_agent.environment-engineer.repair_denied` |
| `run:6e37cb825ca944129b361504550c4a7a` | `design_agent.environment-engineer.output` |
| `run:91ae8d6acadd4bfe89dc9380bea8c565` | `design_agent.environment-engineer.output` |
| `run:a89d6bfa73384f76ad6f90172c4146ad` | `operator_cancelled` |
| `run:d8dd78a081ce4942b56e67e8466ede8c` | `design_agent.environment-engineer.repair_denied` |

Consequence: there is no real evidence that the current Direct graph can reach Builder,
Integration, Judge, Registry or an envpkg release for this canonical request.

### BC-02: latest batched repair spent 50,645 tokens without moving its frontier

Run: `run:d8dd78a081ce4942b56e67e8466ede8c`.

- exact EvidenceGraph checkpoint was reused; Research was not repeated;
- the only semantic transaction was `design.tool-semantics-batch`;
- initial turn: about 99.9 s / 22,737 tokens;
- continued correction: about 83.4 s / 27,908 tokens;
- total invocation: about 183.4 s / 50,645 tokens;
- before and after were the same four issues at
  `tools.{0..3}.reliability`, phase `tool_semantics_batch_preflight`, frontier 30;
- each issue message was only “The compiled tool component violates a closed semantic
  contract.”, so paths existed but the violated condition/allowed value did not;
- RepairLedger correctly classified the completed correction as `no_progress` and denied
  another attempt.

This proves both sides of the problem: stopping repeated no-progress is correct, but a
generic diagnostic can make the single allowed Agent correction incapable of acting.

### BC-03: root diagnostics destroyed causal repair information

Runs `run:128002f281ad4d5a8f064374a0db7eae` and
`run:91ae8d6acadd4bfe89dc9380bea8c565` contain
`schema_value_error_root`.  The latter first repaired an exact string-pattern error and
advanced from shape frontier 10 to semantic frontier 20, then degraded to the root error.
The framework could distinguish stage movement, but the Agent could not see a specific
semantic condition to repair.

Regression requirement: a deterministic schema/reference/type failure must disclose a
stable issue code, exact safe path, violated condition and safe expected/allowed category.
A root-only mechanical diagnostic must fail the framework diagnostic-quality check before
it can consume an LLM repair turn.

### BC-04: issue identity and validation frontier both matter

Run `run:6e37cb825ca944129b361504550c4a7a` changed from an architecture tool-count error at
frontier 15 to five state ownership/visibility errors at frontier 20, then returned to the
original tool-count error at frontier 15.  The final step was oscillation, not progress,
even though the immediate issue set changed.

Regression requirement: progress is a tuple of normalized issue identities, validation
frontier and lineage history.  Code, not an LLM, detects unchanged sets, strict progress,
stage regression and A→B→A oscillation.

### BC-05: old microsharding amplified work without yielding a Design

Artifact store: `.agent-world-live/recovery/state/artifacts`.
Request: `hotel-booking-recovery-20260718-01`.
Run: `run:c96ab6b04eb54f0c8718c3a83864b1bf`.

- Design failed with `design_agent.environment-engineer.repair_denied`;
- Controller accounted 32 Agent turns, 915,880 LLM tokens and two repair attempts;
- telemetry observed 41 invocation turns and 1,054,859 provider token total;
- wall critical path was about 1,776.8 s;
- no Build, Integration or Judge attempt was committed;
- the Artifact graph contains per-entity and per-tool microshards.

This is direct evidence to delete the unreachable microsharded Designer implementation,
retain batching and make physical shards subordinate to a logical transaction commit.
It also exposes a separate accounting discrepancy between controller-accounted and
provider-observed turns/tokens that must remain `unknown/explained`, never silently agree.

### BC-06: one local failure creates a redundant authority graph

The latest run's snapshot lists, for one failed local transaction, two FeedbackResults,
two RepairTargets, two RepairLedgerEntry revisions/attempt records, two structured repair
evidence records, two structured repair Findings, two control events and two dispositions,
followed by a component failure Finding.  Production code writes FeedbackResult but has no
reader that derives readiness, routing or ClaimVector from it; Controller constructs the
release ClaimVector separately immediately before release.

This is evidence that leaf diagnostics, feedback evaluation, routing authority and audit
events are duplicated rather than layered.  The replacement must demonstrate fewer
durable object kinds for the same local correction while retaining exact provenance,
budget settlement and crash recovery.

### BC-07: Builder had no bounded time-to-first-write failure

Historical live observation in Trellis session `019f75c5-89ae-70f1-bd82-be3be1feaa62`:
Builder ran about 896 seconds and timed out without producing candidate files.  A later
isolated observation reported that an older run first patched at about 13.9 minutes.
No corresponding Builder candidate Artifact survived in the current two state roots, so
the prompt/skill cause is not proven.

Supported conclusion: Builder needs an observable time-to-first-progress/write SLA,
durable workspace progress and an isolated diagnostic command.  Unsupported conclusion:
that the prompt, skills or model is definitely the cause.  That must be tested separately.

### BC-08: Integration and final Judge repeat work on identical bytes

Source inspection is exact even though the hotel runs never reached these nodes:

- `EnvironmentJudge.evaluate_integration` performs candidate closure, clean materialize,
  supply chain, static assurance/public tests, public self-check, Runtime protocol,
  task materialization and clean deployment smoke;
- `EnvironmentJudge.evaluate` performs candidate closure, a second clean materialize,
  supply chain, static assurance/public tests, public self-check, Runtime protocol,
  task materialization and clean deployment again, then adds task reachability,
  public/repair behavior cases and sealed cases.

Classification: confirmed duplicate execution in the success path, but its measured live
cost is still a hypothesis because BC-01 prevented reaching it.  A pre-refactor deterministic
call-graph regression and a post-refactor real candidate run must measure it.

### BC-09: retry policy has multiple sources of truth

Confirmed code facts:

- Designer owns `maximum_structured_reworks` (default 2);
- Builder owns `maximum_precommit_reworks` (default 2) and
  `maximum_repair_attempts` (default 3 / app-derived from job maxima);
- Verifier owns configured `maximum_structured_reworks` (default config 3);
- each FeedbackContract independently declares zero, one or two attempts;
- RepairLedger applies its own local limit (two at distance 0, one at distance 1);
- Controller separately reserves and consumes repair attempts in branch and judge loops.

BC-02 through BC-05 show the user-visible effect: attempt counts, reserved turns and
terminal denial depend on several layers.  The target must have one executable policy per
repairable logical Artifact and one global cost ceiling; component loops must query it.

### BC-10: Direct and Evolve do not yet share the complete Design work graph

Confirmed code fact, not yet a live failure:

- Direct uses ResearchPlan, real Research, EvidenceSynthesis, WorldArchitecture,
  optional SharedToolSemantics, one or more ToolSemanticsBatch transactions, WorldRules,
  TaskCurriculum and Modeling Gate;
- Evolve calls `ExpansionEnvironmentDesigner.expand`, which executes ResearchPlan, real
  Research, EvidenceSynthesis and one atomic `ExpansionDesignDraft` transaction, then
  enters the shared Build/Judge/Release path.

The compiler is partly shared, but the semantic transaction graph, feedback policy,
checkpointing and repair granularity are not.  Before changing it, add an executable
topology contract that proves Generate and Expand instantiate the same logical Design
WorkGraph with different frozen inputs.

### BC-11: Evolve bypasses the global repair authority before Build

Independent source audit found that Expansion calls `run_structured_agent` for its
ResearchPlan, EvidenceSynthesis and monolithic ExpansionDesignDraft without a
FeedbackContract, RepairTargetRef or semantic transaction identity.  The Controller also
does not inject StructuredRepairAuthority into Expansion.  Nevertheless the common helper
still loops over Designer `maximum_structured_reworks`.

This is stronger than a topology difference: Evolve currently owns an unaccounted local
retry path that bypasses the global RepairLedger and SemanticNodeCommit.  The regression
must prove that Generate and Expand both instantiate the same repair-controlled WorkGraph;
no component may retry a semantic proposal without one RepairAction authorization.

### BC-12: sandbox child-watcher limitation looked like a framework hang

The resumed baseline progressed normally through 59%, then
`test_verifier_supervisor_cancels_real_straggler_and_keeps_success_checkpoint` did not
terminate in the managed filesystem sandbox.  A minimal reproduction proved that
`asyncio.create_subprocess_exec` could start a child there but `await process.wait()` did not
receive its exit, while synchronous `subprocess.wait()` succeeded.  Running the exact test
outside that namespace passed in 0.60 seconds; the complete suite then passed with 492 tests
and two declared skips in 55.70 seconds.

Classification: execution-environment limitation, not a Verifier production defect.  The
lesson is still relevant to observability: a diagnostic runner must distinguish its own
isolation limitations from target failure and terminate with an explicit infrastructure
result.  Production cancellation code must not be changed to accommodate this sandbox.

### Independently reproduced shared-tool control failure

The skeptical review executed the real catalog validation through `uv`: the production
contract `feedback.design.tool_semantics` declares repair slot `tool_semantics_batch`, while
the shared-tool transaction constructs slot `shared_tool_semantics`.  Calling
`PRODUCTION_FEEDBACK.require_for_target` deterministically raises
`ValueError: feedback contract slot does not match repair target slot`.  This is now a
reproduced defect rather than a source-only hypothesis.

### BC-16: provider continuation exists but transaction recovery does not

Source and live-session inspection establish both halves:

- `InvocationBackend.invoke(InvocationRequest(session=...))` and the Codex adapter support a
  continued structured-output turn on the same provider thread;
- `EnvironmentDesigner.run_structured_agent` keeps the session, last shape-valid candidate,
  repair projection roots and current repair prompt only in process memory;
- the durable NodeAttempt stores only a hashed Agent session id, so phase resume cannot
  revalidate and restore the exact semantic transaction after restart;
- rerunning Direct from a phase checkpoint therefore starts the complete semantic node again.

A production continuation checkpoint must be private and framework-owned.  It binds the opaque
backend handle, provider/backend/model/profile/schema/config digests, exact immutable inputs,
semantic transaction and attempt identity, last actionable ValidationReport, authorized mutation
roots, RepairAction/ledger/budget refs and a confidential candidate commitment.  It never enters
an envpkg, Registry record or public trace.  Resume must obtain a new budget lease and repair
authorization before invoking the backend.

### BC-17: bounded progress was real but the physical batch still did not converge

Run `run:a11204339b724e768a93889339194764` reused the hotel EvidenceGraph and architecture,
then executed one real five-tool semantic transaction with `gpt-5.4-mini`:

- three Agent turns, 97,995 tokens and about 323.4 seconds;
- initial frontier 10: tuple/collection shape errors and an incomplete tool collection;
- first correction advanced to frontier 30 with 15 exact Rule pointer/selector issues;
- second correction changed those to 10 exact selector key/value issues;
- both repairs were classified `progressed`, but the declared two-correction ceiling ended the
  transaction with no committed batch.

The ceiling behaved as designed: one normal local correction plus one strict-progress bonus.
Increasing retries would merely recreate an expensive open loop.  The causal follow-up is to
reduce proposal complexity or derive mechanical fields from the frozen catalog, preserve the
successful sibling/batch boundary, and prove convergence on a fresh real batch.

### BC-18: the ten-question policy is not yet the production authority

`agent_world/control/work.py` defines the target vocabulary—WorkDefinition, numeric budgets,
ValidationReport, FeedbackEvaluation, RepairPolicy, RepairAction and WorkCommit—and its tests
exercise diagnostic quality and progress classification.  Its module contract explicitly says
it is not wired into legacy orchestration.  Production still executes FeedbackContract,
component-local `maximum_*_reworks`, legacy RepairLedger authorization and separately assembled
Controller release claims.

Consequently the ten questions are answered in the design, but not yet enforced once for every
runtime boundary.  This is the primary migration target.  Prompt tuning and additional real model
calls are paused until the single authority can at least own Design semantic transactions.

## Current logical and physical topology

### Product-level components (retain)

1. FoundryController: authority, readiness, leases, routing, invalidation and release.
2. EnvironmentDesigner: evidence-backed WorldSpec/Task/Implementation semantics.
3. EnvironmentBuilder: real Codex code generation and candidate source closure.
4. EnvironmentJudge: isolated real execution and independent assurance.
5. EnvironmentRegistry: physical, atomic publication and package truth.

Research, Runtime Supervisor, Verifier compiler, telemetry and repair are internal
mechanisms, not additional product-level Agents or services.

### Direct semantic work before Build

| Logical work | Physical work | Current evaluator |
|---|---|---|
| Research evidence | plan LLM → real search/fetch/extract → synthesis LLM | code validates plan, references and EvidenceGraph closure |
| World architecture | one Engineer LLM | code compiles boundary/state/tool inventory and skeleton |
| World behavior | optional shared-contract LLM per multi-batch group; one or more tool-batch LLM calls; code group closure | code compiles transitions, errors, authority, reliability and cross-tool closure |
| World rules | one Engineer LLM | code compiles reset/global invariants over frozen behavior |
| Task curriculum | one Engineer LLM | code compiles TaskRequirement/materializer/evaluator contracts |
| Modeling boundary | no LLM | code validates evidence/model/task closure and maturity |

The logical work count is not itself excessive.  The proven excess came from the retired
per-field/per-tool microshards and from repeated durable control objects around a leaf
failure.  Physical batches must remain observable and independently retainable without
becoming product-level stages or independent release authorities.

## Current verification boundary inventory

This is the first-pass boundary catalog.  Leaf checks inside each row are diagnostics;
they are not automatically separate feedback policies or repair authorities.

| Boundary | Claim | Evaluator | Cost | Failure owner / minimal repair Artifact | Effect |
|---|---|---|---|---|---|
| Research plan compile | bounded questions cover workflow/tool/state/authority/error/risk | code over LLM proposal | L0 validation + L2 proposal | current ResearchPlan | reject transaction |
| Evidence compile | claims bind fetched passages; conflicts/unknowns preserved | code over real fetch + LLM synthesis | L0/L1 validation + L2 proposal | EvidenceSynthesis | block semantic compile |
| Architecture compile | boundary/state/tool vocabulary closes | code over LLM proposal | L0 + L2 proposal | WorldArchitecture source | block behavior compile |
| Behavior batch compile | tool transition/error/authority/reliability closes | code over LLM proposal | L0 + L2 proposal | exact behavior batch; shared contract only when causal | block world closure |
| World rule compile | reset/global invariant rules close over frozen behavior | code over LLM proposal | L0 + L2 proposal | WorldRules source or one direct behavior parent | block task compile |
| Curriculum compile | tasks are typed and bound to frozen world | code over LLM proposal | L0 + L2 proposal | TaskCurriculum source | block Modeling Gate |
| Modeling Gate | exact Design has evidence/model/task closure | code | L0 | precise Design semantic source | block Build |
| Builder precommit | source workspace and declared candidate closure are structurally valid | code over real Codex workspace | L0 + L2 codegen | CandidateWorkspace | block Integration |
| Verifier intent compile | Challenger intent compiles into framework-owned IR | code over Challenger proposal | L0 + L2 proposal | exact intent batch | block release only |
| Integration | exact candidate installs and executes public protocol/materializer/smoke | real subprocess + deterministic checks | L1 | CandidateWorkspace; Design only with exact one-hop evidence | block release |
| Release assurance | reachability, behavior/property, sealed and fresh deployment pass | real subprocess | L3 | exact causal Candidate/Task/Verifier Artifact | block release |
| Observability closure | required spans/usage/provenance exist or are explicitly unknown | code | L0 | telemetry projection, never semantic Artifact | block release |
| Registry publication | exact ready bytes/claims/metadata are atomically committed and reread | code + filesystem | L1 | publication transaction | no earlier semantic rework; fail release |

## Confirmed control-plane defects

1. `hybrid` currently conflates expensive LLM proposal generation with cheap deterministic
   evaluation.  Cost and executor cannot be reasoned about independently.
2. Every leaf validator is encouraged to register a FeedbackContract even when it has no
   independent routing or release decision value.
3. FeedbackResult is currently a durable write-only fact, while ClaimVector is assembled
   separately.  There is no single authoritative evidence-to-maturity derivation.
4. Finding owner is framework-authored but still supplied as an enum and then trusted by
   RepairRouter; the router does not derive ownership from Claim producer + exact Artifact
   dependency edges as the source document requires.
5. NodeCommit and SemanticNodeCommit overlap: one commits top-level NodeAttempt terminal
   state, the other commits Designer semantic transactions, but there is no shared
   hierarchical WorkAttempt/WorkCommit identity.
6. Retry authority is split among component loop bounds, FeedbackContract, RepairLedger,
   Controller reservations and job budget.
7. Integration evidence is not accepted as digest-bound input to Release Assurance, so
   final Judge repeats deterministic and public execution work.
8. The CLI has inspect/resume/cancel but no real `diagnose`, `retry-node` or `no-rework`
   execution surface.  Long-pipeline downstream diagnosis therefore depends on replaying
   the ordinary success path.
9. `designer/service.py` retains an unreachable retired microsharded implementation and
   retired skeleton recovery helpers, materially increasing reasoning and maintenance
   surface after BC-05 already rejected that topology.
10. The optional shared-tool path passes repair slot `shared_tool_semantics` through the
    `feedback.design.tool_semantics` contract whose declared slot is
    `tool_semantics_batch`; this should fail closed when a 5–8 coupled-tool group actually
    reaches the path.  It is a deterministic reproduction candidate, not yet a live case.
11. Live run `run:db1e771349b149808c669801e58407f6` progressed from shape frontier 10
    to semantic frontier 30, then stopped after 73,417 tokens and about 355.7 seconds.
    Replay of the exact continuation proved that 11 generic root issues all came from 62
    non-empty Rule pointers lacking the RFC 6901 leading slash.  Segment-wise core model
    construction erased the Rule/clause/term paths.
12. The same live continuation exposed a Rule-language closure gap rather than only a
    formatting defect: array-backed `bookings`, `search_sessions`, and
    `payment_authorizations` were addressed as if a direct pointer could select the record
    matching current action arguments.  A direct RFC 6901 pointer cannot express that
    relation; passing it would defer failure to Runtime `MISSING`.

## BC-14/15 architecture decision

- Core Rule validators own stable typed error codes; Designer validates the complete Rule
  payload and aggregates every sibling Rule path instead of copying core validators.
- `RuleContextCatalog` binds `args`, `tool_result`, `observation`, `pre_state`, and
  `post_state` to frozen schemas and rejects unreachable pointers and type drift before Build.
- Dynamic state-record selection uses the closed, non-recursive `lookup_by_key` Rule term.
  Runtime scans at most the existing bounded container limit, returns missing for no match,
  and fails closed for duplicate matches.
- No blanket leading-slash normalization is allowed.  It could turn an obvious syntax error
  into a later false path through an array.  Deterministic normalization requires a unique,
  schema-proven target and durable observability; otherwise the exact Rule remains LLM-owned.

## Evidence-constrained target direction (not yet frozen)

1. Keep the five product components and one release path.
2. Represent semantic work as a shared typed WorkGraph used by Generate and Expand;
   differences are frozen input context, not a separate Designer success path.
3. Keep Architecture, WorldBehavior and TaskCurriculum separate because they own distinct
   independently repairable semantics; combine physical shards under aggregate commits.
4. Separate `ProposalExecution` (LLM/real tool cost) from `ValidationPolicy` (usually code)
   and from `AssurancePolicy` (real execution / optional semantic advisory).
5. Emit exact `ValidationReport` diagnostics for leaf checks.  Only a boundary evaluation
   that changes readiness, routing or release state creates a durable FeedbackEvaluation.
6. Derive ClaimVector/maturity from active digest-bound terminal evaluations rather than
   writing an unrelated projection at release time.
7. Derive repair owner and invalidation from the Claim/Artifact WorkGraph.  Agent and
   validator owner text is a hint, never authority.
8. One local repair by default; a second only for an explicit policy and code-proven
   progress.  One causal parent hop maximum; distance two requires human authority.
9. Preserve successful sibling commits and invalidate only descendants of the repaired
   Artifact coordinate.
10. Integration produces reusable digest/toolchain/profile-bound evidence.  Release
    Assurance consumes it and runs only added reachability/property/sealed/fresh-release
    claims.  Independence may require a fresh install/deployment, but not blind replay of
    every static/public gate.
11. Add a real diagnostic execution surface with `--no-rework`.  A diagnostic Artifact is
    non-releasable.  Whether an automatic provisional Builder becomes the default remains
    unproven and must not be introduced without measured evidence.
12. Add Builder first-progress/write telemetry and a bounded no-progress terminal result;
    do not infer prompt or skill cause until an isolated real Builder reproduction exists.
13. Give tests and diagnostic subprocesses the same named-operation deadline and terminal
    observability required from production nodes; classify BC-12 as infrastructure and keep
    the passing Verifier supervisor behavior unchanged.

## Required proof sequence

1. Preserve the two state roots read-only as regression evidence.
2. Add deterministic failing regressions for root diagnostic rejection, progress/oscillation,
   single repair truth, feedback-to-claim consumption, shared-tool slot mismatch, sibling
   retention, Generate/Expand WorkGraph parity and Integration evidence reuse.
3. Run existing unit/type/lint suites after each control-contract change.
4. Run isolated real Designer from the existing EvidenceGraph checkpoint in no-rework mode.
5. Run isolated real Builder against a committed valid Design and measure time to first
   progress/write.
6. Run real Integration before waiting for final Verifier completion.
7. Run final Release Assurance consuming the exact Integration evidence.
8. Only then run the canonical fresh request “用户预订宾馆” from Research through Registry
   with real search, `gpt-5.4-mini`, real subprocesses, no manual Artifact edits and no mocks.
9. Run a separate live negative/rework acceptance so a successful happy path is not the
   only evidence for the repair control plane.

## Independent ten-question implementation audit

An independent code-path audit confirmed that the boundary matrix answers the ten questions at
the target-design level, but production does not yet enforce those answers from one authority.
The most important implementation gaps are:

1. `control/work.py` is tested target vocabulary but explicitly not wired into orchestration.
2. `hybrid` conflates an expensive Agent proposal with the deterministic compiler that judges it.
3. Numeric cost limits remain split across component meters and Controller leases.
4. Retry authority remains split across component loop maxima, FeedbackContract, RepairLedger and
   the job BudgetLedger.
5. A local failure still writes RepairTarget, evidence, FeedbackResult, ControlEvent,
   Disposition, Finding and RepairLedgerEntry instead of one report/evaluation/action chain.
6. FeedbackResult is not consumed to derive readiness; release claims are assembled separately.
7. Repair owner and invalidation are not derived from exact WorkGraph coordinates.
8. Integration evidence is not reused by final Judge under a digest/toolchain/profile key.
9. Transaction continuation state is process-local, so restart cannot resume the minimal repair.
10. RuleContextCatalog currently protects ToolSemantics Rules but not yet WorldRules and task rule
    contexts.
11. Evolve still uses a monolithic Design path and bypasses the shared repair-controlled graph.
12. Builder first-progress/first-write fields exist in the target contract but are not yet the
    production SLA authority.

The first migration slice is `ToolSemanticsBatch`, because BC-02, BC-03, BC-14, BC-15 and BC-17
all exercise it with real provider output.  Acceptance requires that its proposal, deterministic
validation, terminal Claim evaluation, repair authorization, continuation checkpoint, cost and
commit all come from one WorkDefinition.  Only after this slice passes preserved bad cases may
the same mechanism replace other semantic boundaries.

## BC-18: policy-only definition change caused unnecessary upstream work

A real resume after adding process-recovery authority changed the full WorkDefinition digest for
every semantic node. ResearchPlan itself was restored from immutable history without another LLM
turn, but the pre-search EvidenceSynthesis checkpoint lookup considered only the current mutable
head; it therefore performed six new searches and fifteen fetches before a new 28-second synthesis.

Decision after independent adversarial review:

- keep `definition_digest` for complete future execution authority;
- add `acceptance_digest` for immutable successful output reuse;
- keep `repair_epoch_digest` for exact failure/repair history;
- require an explicit validator executable revision in acceptance identity;
- release any superseded running lease and persist `interrupted` before historical reactivation;
- never let cache reactivation replace an active semantic RepairAction.

Regression proof: policy-only budget/recovery/timing changes preserve acceptance and reactivate the
exact WorkCommit; validator revision changes fail closed; no active BudgetLease remains orphaned.

## BC-19: a Design-only cutover was mistaken for a production control-plane cutover

Independent call-graph audits confirmed that the new Work control plane terminates at
ModelingBoundary.  Builder, Verifier, Integration, ReleaseAssurance, Package, Registry, late
Design revision and Expansion still execute through combinations of NodeAttempt, FeedbackResult,
the legacy RepairLedger and component-local retry loops.  A live hotel run therefore exercises
"new Design + old downstream" and cannot prove the framework refactor complete.

Required regression and deletion condition:

- one production graph manifest binds Research through Registry before downstream scheduling;
- Builder and Verifier complete out of order while exact successful siblings remain committed;
- Integration starts from a committed Candidate without waiting for Verifier;
- release readiness is derived only from active WorkCommits and FeedbackEvaluations;
- an import/call-graph check rejects production imports/calls of FeedbackContract,
  FeedbackResult, the legacy RepairLedger, NodeAttempt/NodeCommit and component semantic retry
  counters after cutover.

## BC-20: the initial Work kernel was too narrow for downstream execution

The current WorkDefinition is sufficient for one structured semantic proposal but does not yet
prove an exact Builder workspace/output closure, validation/assurance execution cost, dynamic
shard join, or WorkAttempt telemetry ownership.  Merely wrapping downstream services would create
a cosmetic single vocabulary while leaving the actual scheduler and evidence authority split.

Decision: add explicit Artifact slot contracts, ValidationExecution, AssuranceExecution,
WorkGroup/JoinPolicy and scheduler-owned telemetry before downstream cutover.  Leaf probes remain
inside one report; these additions model execution authority and joins, not more product gates.
## BC-21 — Design-only WorkGraph masquerades as package release evidence

- Live/source fact: the production manifest currently terminates at `modeling_boundary`, while
  Builder, Verifier, Integration, Judge and Registry remain under legacy authorities.
- Failure: Registry accepts the Design readiness Artifact as the WorkGraph proof for a complete
  package; a later Direct Design revision does not emit replacement graph/readiness at all.
- Required regression: only a full Research-to-Registry manifest with an exact
  `release_candidate` milestone may enter package preparation, and only RegistryPublication may
  establish `released`.
- Proof class: source-proven; full production replacement pending.

## BC-22 — Completed assurance execution hides failed probes

- Reproduction: a process can finish and write evidence saying Reset/Step failed while the old
  contract records only `AssuranceExecution.status=completed`.
- Failure: a passing deterministic report can then satisfy the boundary without typed probe
  verdicts.
- Regression: `AssuranceReport` binds the exact policy/runtime/freshness and every required probe;
  any failed/inconclusive/error probe prevents WorkCommit.
- Proof class: deterministic regression implemented; real Integration cutover pending.

## BC-23 — Parent revision leaves stale child and aggregate commits active

- Reproduction: child resume used its own historical `attempt.input_refs`, so a replaced parent
  could not make it stale. Aggregate readiness also lacked exact child-commit binding.
- Regression: Scheduler recomputes expected inputs topologically from current parent commits;
  stale descendants are not active, blocked groups expose exact evaluation refs, and aggregate
  commits bind every frozen child commit.
- Proof class: deterministic regression implemented; scheduler production dispatch pending.

## BC-24 — Read-only Scheduler hid a broken executable input fingerprint

- Reproduction: the first call to real `WorkScheduler.dispatch_one()` reached
  `resolve_inputs()` and failed because `WorkCoordinate` and `ArtifactRef` model objects were sent
  directly to canonical JSON serialization.
- Failure: all previous scheduler tests asserted only state projection; no test proved the object
  could dispatch even one ready leaf, so a core handoff defect remained invisible.
- Regression: a two-node Package -> Registry graph is driven by `run_until_stalled`; each leaf
  executes under the real WorkControlRuntime and commits before the next node resolves inputs.
- Proof class: deterministic real framework execution implemented; production component registry
  pending.

## BC-25 — Execution evidence was authorized after the expensive work

- Reproduction: validation and assurance reports could be constructed before their lease and
  dispatch authority existed; proposal attempts did not distinguish never-dispatched from
  dispatched-but-unknown work.  Two processes could also reserve the same scope budget snapshot.
- Failure: recovery could replay a real model/process call, undercount unknown consumption or
  oversell a global job budget while still producing apparently valid evidence.
- Regression: `OperationRun` owns a durable scheduled -> running -> terminal lifecycle; the Work
  head must point to running before execution.  A persistent flock-serialized scope ledger admits
  only one of two real processes competing for the same `agent_turns=1` capacity, and terminal
  settlement is idempotent.
- Proof class: crash/accounting kernel regression implemented; every production leaf still needs
  migration before this protects the complete Direct path.

## BC-26 — an authorized repair could fail budget admission and strand a running attempt

Live scheduler bootstrap for the unmodified need `用户预订宾馆` exercised a real tool-provider
outage. The first Acquisition operation created an infrastructure report and the policy
authorized its bounded local retry. In the first budget envelope the second attempt could not
reserve the global repair/tool capacity. Before this correction, `BudgetExceeded` escaped leaf
dispatch after the new WorkAttempt had started; no `OperationRun` existed, but the WorkHead
remained `running` and recovery could not tell whether any external work had occurred.

The repair is deliberately framework-owned rather than a looser retry: Scheduler may terminalize
only a no-active-operation admission failure. It records safe exhausted dimensions, report and
evaluation, marks the attempt `budget_exhausted`, fails the head and closes the authorized
RepairAction ledger entry as `exhausted`. An active operation remains the executor's/recovery
responsibility because its cost may be unknown. The regression drives the exact failed-proposal
then unaffordable-repair sequence and proves that only the first proposal invocation occurred.

## BC-27 — real bootstrap distinguishes an available model from an unavailable research provider

An isolated real structured invocation using the explicit configured OpenAI-compatible endpoint
and `grok-4.5` completed in about 2.8 seconds. The inherited process endpoint differed, so the
test used only a per-process override; it did not edit user authentication or global config.
The subsequent four-node scheduler bootstrap used the same real model and the actual
Search/Fetch/Extract toolchain. `ResearchPlan` committed. `ResearchAcquisition` made two policy-
bounded real tool attempts and both reported the external provider unavailable; it became
`blocked`, so EvidenceSynthesis and WorldArchitecture correctly did not dispatch.

This is negative live evidence, not a partial pass and not a model/codegen diagnosis. It proves
the model adapter/control route and provider-failure routing separately, but it cannot establish
an EvidenceGraph, EnvironmentDesign, Candidate or release. Future live tests must reuse the
committed Plan only when its exact inputs remain valid, change/repair the actual research provider
configuration, and retain this outage outcome rather than replacing it with static evidence.

## BC-28 — least-privilege dispatch and recovery used different input closures

The strict Direct graph correctly treats a dependency as causal lineage and `input_slots` as
artifact disclosure. `resolve_inputs()` therefore passed only declared typed parent outputs to a
child. `snapshot()`, however, rebuilt the historical input fingerprint from **all** parent
consumer refs. The resulting WorkCommit was accepted at dispatch but became immediately `stale`
during recovery/reconciliation. This can leave a valid final graph permanently unable to open
Package and Registry while every local leaf appears successful.

Root category: cross-layer contract plus change-propagation failure. The initial least-privilege
fix changed dispatch but missed the reuse path. The structural correction is one shared helper for
the exact external-root plus typed-parent-output closure, used by both snapshot and dispatch;
parent commit refs remain lineage only. The deterministic regression commits a parent with one
allowed and one sealed output, verifies that the child receives only the allowed ref, and verifies
the child is `ready` in a fresh snapshot. Separate real Package→Registry Scheduler closure and
pre-package observability tests confirm downstream readiness reaches publication without a
Controller fallback. This is framework execution evidence, not a live generated-environment
claim.

## Bug Analysis: BC-28 input-closure drift

### 1. Root Cause Category

- **Category**: B/C — cross-layer contract plus change-propagation failure.
- **Specific Cause**: dispatch enforced typed disclosure while snapshot/reuse reconstructed an
  all-parent-output fingerprint. The code had two representations of the same WorkAttempt input
  closure, so acceptance and recovery disagreed.

### 2. Why Fixes Failed

1. The first least-privilege change fixed only `resolve_inputs()`, because its immediate live
   symptom was an undeclared artifact reaching the next Agent.
2. Existing tests inspected resolved inputs but did not reconcile a committed child in a fresh
   Scheduler snapshot; downstream publication therefore had no regression covering reuse.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
|---|---|---|---|
| P0 | Architecture | One `_all_input_refs` helper is the only fingerprint closure authority | DONE |
| P0 | Test | Allowed/sealed parent test asserts dispatch and snapshot both accept the child | DONE |
| P1 | Code-spec | Causality/disclosure contract specifies snapshot parity and error matrix | DONE |
| P1 | Integration | Package→Registry Scheduler closure exercises downstream readiness | DONE |

### 4. Systematic Expansion

- **Similar Issues**: every recovery/cache/invalidation path must use the same accepted-input
  transform as initial dispatch; direct head lookup is forbidden for Package closure.
- **Design Improvement**: dependency lineage and artifact disclosure are separate typed relations,
  not one overloaded parent-output list.
- **Process Improvement**: after any scheduler change, test one initial dispatch and one fresh
  snapshot/recovery before spending a real model turn.

### 5. Knowledge Capture

- [x] Updated the backend executable contract.
- [x] Recorded the bad case and deterministic regression.
- [x] Updated the source-of-truth migration status without claiming live E2E.

## BC-29 — actionable semantic feedback and live accounting were projected away

The post-BC-28 real hotel run completed its real research and Architecture prefix, then reached
`shared_tool_semantics`.  Its deterministic semantic validator reported four exact classes:
partitioning of frozen tool ids, compensation endpoints, and missing error-policy coverage.  The
leaf boundary converted each into a `ValidationIssue` with only the generic text “the deterministic
structured-output contract was violated.”  One local correction was therefore authorized with no
usable condition or allowed category; it returned the same issue tuple and the Scheduler correctly
stopped it as `repair_no_progress_terminal`.

The same run showed a separate observation contradiction: the Scheduler had already reserved and
settled durable operation leases, but the DirectJob terminal snapshot had not yet been written.
`run inspect` consequently displayed zero use and zero active leases while telemetry showed a
running real invocation.  Scheduler work spans also lacked the Direct root parent despite sharing
the same trace id.

Root category: B/C cross-layer information-loss and duplicated projection authority.  This is not
a reason to widen repair budgets or weaken validation: code knew the diagnostic and the accounting,
but discarded it while crossing boundaries.

The correction is structural:

1. `StructuredSemanticIssue` now carries safe condition/category values and the one-shot boundary
   preserves them in the report used by RepairAction; the no-progress key remains exact and local.
2. `run inspect` reads the immutable Scheduler scope lease ledger for active Direct runs, sums only
   settled actual/unknown commitments and separately exposes active reservation.  The final
   DirectJob snapshot remains a terminal projection, not a second mutable scheduler.
3. WorkAttempt spans inherit the active matching Direct root; a mismatched active trace fails
   rather than silently forming a disconnected trace tree.

Regression evidence is intentionally deterministic and non-claiming: a semantic boundary test
preserves the exact safe feedback, a ledger test disproves stale-zero observation, and a real
Scheduler deterministic leaf proves the span tree.  A new live run is still required; this bad
case must not be marked resolved merely because its information path is repaired.

## BC-30 — a real Agent timeout stranded its dispatched non-replayable operation

The next `grok-4.5` hotel Direct run committed ResearchPlan, real Acquisition and EvidenceSynthesis,
then WorldArchitecture exceeded its declared 360-second operation budget. `invoke_structured_once`
correctly constructed `LeafExecutionFailure(agent_invocation_timeout)` with the entire reserved
token envelope as unknown.  It had already resolved the isolated profile and issued Scheduler
dispatch id, but it created `AgentExecutionProvenance` only after a terminal provider result.
`SchedulerLeafExecutor._finish_exception` therefore rejected the timeout as an agent failure
without provenance, raised `WorkRuntimeError`, and Controller projected a broad Direct failure
while the WorkHead/OperationRun remained active.

Root category: B/C boundary-ordering defect. The provider timeout is an expected real execution
outcome, not a model semantic correction and not authority to replay a non-replayable call.

The correction constructs provenance immediately after the profile and dispatch id are bound,
before `backend.invoke`. Timeout, cancellation-envelope and transport failures now carry that
provenance into failed ProposalExecution, lease settlement and typed Evaluation. A deterministic
hanging-backend regression proves the exact timeout contains the dispatch id/profile/model and the
existing Scheduler backend-error test proves such a failure becomes a terminal evaluation. A fresh
live request is still required; the prior failed head/result remains immutable evidence and is not
replayed or manually edited.

## BC-31 — a correctly authorized semantic correction was invoked without its diagnostics

The next real hotel run reached `shared_tool_semantics`, where deterministic validation produced
three safe, field-addressable failures: exact frozen-tool partition coverage for atomicity and
concurrency domains, plus error-policy coverage. The Scheduler correctly authorized one local
repair. Its second Agent request, however, was byte-for-byte equivalent in remediation knowledge:
`WorkExecutionContext` carried `repair_action_ref`, but every production Agent leaf ignored it
when building its prompt. The stateless model consequently returned the same invalid semantic
proposal and the RepairLedger correctly denied it as `repair_no_progress_terminal`.

Root category: B/C control-to-executor information-loss. This was neither a reason to weaken the
compiler nor evidence that an additional blind retry would help. `RepairAction` must remain code
authority; the missing capability was a narrow, safe projection of the rejected conditions.

The structural fix adds `AgentCorrectionBrief`. `SchedulerLeafExecutor` follows the immutable
`RepairAction -> FeedbackEvaluation -> ValidationReport` chain, verifies that it binds the target
`WorkDefinition`, and exposes only blocking `code/path/violated_condition/expected_category`
facts. `invoke_structured_once` appends this data-only brief to a fresh call for every production
Agent leaf. It exposes no action id, budget, mutation root, routing coordinate, owner,
invalidation, or release data. Infrastructure retries receive no brief because they have no
rejected semantic candidate. Regression tests prove both the exact Scheduler two-attempt path and
the rendered-prompt confidentiality boundary. A fresh live run is in progress; BC-31 is not a
release claim until that run demonstrates the affected production leaf behavior.

## BC-32 — post-proposal Artifact materialization both rejected a valid correction and stranded it

The BC-31 live rerun proved that SharedTool correction dispatch received a new real Agent call. Its
second output passed the deterministic shared-tool compiler and committed
`design.shared_tool_semantics_source`. The next immutable write failed before the corresponding
contract Artifact: Final Design appended `architecture_ref` and `evidence_ref` to a dependency
tuple that already contained both through the Scheduler parent-input closure. ArtifactStore
correctly rejected duplicate DAG edges.

The generic leaf exception path then lost the already completed Agent provenance and attempted an
Agent failure without it. The framework raised `WorkRuntimeError`, Direct projected a broad error,
and the WorkHead retained a running Proposal OperationRun even though its scope lease had been
settled. This is framework control failure, not a model semantic failure; neither a relaxed
validator nor another correction can repair it.

The correction makes all Final Design immutable dependency closures set-like through one
`_unique_refs` transform. It also records `AgentProposalOutcome` after a successful structured
turn. If subsequent compiler/Artifact materialization raises, Scheduler consumes that task-local
provenance to terminalize the current operation with measured usage and a non-retryable
`agent_postproposal_framework_error`; no active WorkHead or blind retry remains. Regression drives
the exact post-Agent generic exception and asserts terminal operations, measured token/turn usage,
and a blocked non-retryable report. A new real run is required after this correction; BC-32 remains
immutable bad-case evidence.

## BC-33 — bounded correction exposed avoidable shared-contract construction load

The first post-BC-32 real `用户预订宾馆` run reached the new `SharedToolSemantics` path with real
research and six real Agent calls. Its first shared-contract output omitted frozen members from
atomicity/concurrency partitions. The safe correction brief was demonstrably delivered: the next
proposal resolved that issue but exposed missing error-policy coverage. The third proposal
reintroduced the original partition failure. The global RepairLedger therefore classified the
sequence as A→B→A oscillation and stopped it with no active lease or OperationRun.

This is a good control-plane outcome: code did not treat the changed issue code as “no progress,”
did not leak RepairAction controls, and did not spend unlimited model calls. It also reveals a
prompt-design issue: the model had to repeat the same frozen tool set across several structurally
complete collections without an explicit construction invariant.

The correction is deliberately not a hotel fixture or compiler relaxation. The shared-tool prompt
now names `coupling_group.ordered_tool_ids` as the only vocabulary, requires exact coverage for
the three domain collections and error-policy coverage, and permits one full-set domain where no
evidence warrants a finer split. The deterministic compiler remains the authority and the
existing A→B→A cap remains unchanged. A prompt-contract regression ensures this generic rule and
the frozen ids remain present. The full deterministic suite passed after the change; a new live
request remains required before claiming an executable EnvironmentPackage.

## BC-34 — a committed semantic leaf exposed an unbound physical successor

A fresh real `grok-4.5` hotel Direct request completed live Research, EvidenceSynthesis and
WorldArchitecture, then committed `SharedToolSemantics` on its first proposal. This is evidence
that BC-33's generic frozen-set construction rule helped at its intended semantic boundary; it did
not use a hotel fixture, compiler relaxation, or extra correction. The next `ToolSemanticsBatch`
was ready in the frozen Design graph, yet Direct stopped before dispatching it.

The cause was framework topology drift. `tool_semantics_batch_definition` intentionally gives its
physical batch the semantic stage `world_behavior` and the stable artifact slot
`tool_semantics_batch`. `DirectWorkRunner` selected the leaf by the old stage spelling
`tool_semantics_batch`, so it omitted an executor. `WorkScheduler.run_until_stalled` then treated a
ready-but-unbound node as ordinary stalling, while Direct's blocked projection listed only terminal
semantic `blocked` nodes; the public result consequently said `unknown scheduler coordinate` even
though the frozen graph contained an exact ready coordinate.

This is neither an Agent failure nor a Validator finding. The structural correction binds the
ToolSemantics leaf by its stable artifact slot, and `WorkScheduler` now raises typed
`WorkExecutorMissingError` with safe coordinate fields whenever a ready/repair-ready Work has no
executor. Controller projects that type as `scheduler_executor_missing`; it cannot enter a Repair
ledger or spend another model turn. Deterministic regressions prove both the precise missing
coordinate and the otherwise differing `world_behavior`/`tool_semantics_batch` pair. The failed
run remains immutable evidence (four real Agent turns, six searches, no active lease or operation)
and must not be resumed; a new request is still required before any release claim.

## BC-35 — an unconfigured monetary envelope blocked real parallel tool batches

The next live hotel run proved BC-34: both physical ToolSemanticsBatch coordinates were actually
dispatched after SharedToolSemantics committed. Before either provider call, both closed as
`budget_exhausted(monetary_cost)`. The Direct budget intentionally defaults to zero monetary cost
for a provider that reports no trustworthy price, but `tool_semantics_batch_definition` alone
silently defaulted each batch to a one-unit monetary reservation. This made a normal two-batch
topology impossible even though no monetary policy had been configured.

The correction removes that implicit one-unit envelope. A leaf has zero monetary reservation unless
its caller explicitly declares a measured-price limit; tests that synthesize an observed price now
pass their own explicit envelope and still prove settlement rejects overspend. Thus zero is no
longer a fabricated observed price or a hidden per-leaf budget: it means no monetary admission
policy was configured. Provider price availability remains observable as unknown and must not be
claimed as zero in experiment reporting. A fresh run is required to exercise the now-dispatched
batch proposals and downstream Builder/Registry path.

## BC-36 — ToolSemantics cross-field checks classified candidate mistakes as framework defects

The first post-BC-35 real hotel run crossed both parallel ToolSemanticsBatch provider dispatches.
Each batch then returned a mixture of legitimate candidate semantics failures (for example Rule
namespace/evidence closure and access/reliability constraints) and sixteen
`framework_diagnostic_incomplete` findings rooted at `conditions`, `state_transition`, `errors`,
and `behavior`. The Scheduler correctly refused a blind correction because that code means the
framework has not disclosed a safe causal condition. The problem was in the validator boundary:
several proposal-owned cross-field checks still raised raw `ValueError`; their known safe paths
were lost when the batch aggregator converted them to a report.

This is not a reason to relax the semantic compiler, add a global LLM judge, or increase retries.
It is a feedback-contract defect. The correction converts proposal-owned tool Rule, error-code,
behavior and final cross-component closure failures into `StructuredSemanticIssue` values with
stable code, source-facing path, violated condition and expected category. The prefixing boundary
now preserves those latter two values instead of overwriting them with generic text. Frozen schema
corruption remains a non-retryable framework diagnostic. Behavior validation keeps only
cross-component uniqueness rather than repeating every per-section Rule failure.

The regression starts from a real compiled counter world, introduces a wrong tool Rule prefix and
an unknown evidence reference, and proves the exact `tools.0.conditions...` issues remain
actionable through the feedback router with no `framework_diagnostic_incomplete`. A fresh live
hotel request is still required: this deterministic bad-case proof establishes feedback quality,
not an EnvironmentPackage release.

## BC-37 — mechanically authored Rule IDs and repeated diagnostics overwhelmed one local repair

The next `用户预订宾馆` live run proved BC-35 and BC-36 at the dispatch boundary: all ToolSemantics
calls reached the provider and every semantic issue was actionable. It nevertheless stopped at the
two physical batches after one authorized correction each. Initial/corrected reports contained
96/136 and 187/180 blockers respectively. The dominant classes were repeated `tool_rule_id_prefix`,
`rule_lookup_key_field_missing` and `rule_pointer_unreachable`; passing the whole issue list to the
second prompt asked a single Engineer to repair many copies of the same schema construction mistake.

This is neither a reason to loosen pointer/authority/reliability validation nor evidence that the
budget is too small. Rule namespace and ordinal are framework identity mechanics, not business
semantics, so ToolSemanticsBatch now deterministically writes `rule:<tool>:<section>:<ordinal>` and
the Agent may omit `rule_id`. The full immutable ValidationReport still records every exact issue.
Only the data-only AgentCorrectionBrief is compressed by safe `(code, condition, expected)` clusters
with count, normalized affected paths and up to three representative paths; its prompt states that
each cluster applies to all matching replacement fields. RepairAction authority remains hidden.

Focused regressions prove canonical Rule IDs and a sixteen-issue pointer cluster with intact scope.
The new prompt also receives RuleContextCatalog projections and exact selector construction rules.
A further real Direct run is required to measure whether the revised proposal boundary reaches the
downstream Builder/Verifier/Registry path; BC-37 is not a release claim.

## BC-38 — frozen WorldSpec `$ref` hid selector facts, so Tool batch repair rewrote an impossible contract

A later real `用户预订宾馆` Direct run reached both physical ToolSemantics batches with six real
Agent calls, real search/fetch/extract, and no monetary admission rejection. One batch corrected
successfully. The other changed from 132 to 148 actionable blockers: every one was either
`rule_lookup_key_field_missing` or `rule_pointer_unreachable`. Scheduler consumed exactly the two
declared local repairs and terminated the failing batch as no-progress; it did not reopen
Research, Architecture, SharedToolSemantics, or its successful sibling.

Inspection of the immutable frozen state schema showed the real cause. WorldState collections have
`items: {"$ref":"#/$defs/<entity>"}`. The original RuleContextCatalog and pointer validator read
only inline item `properties`, so their prompt projection contained no collection item fields or
primary keys, and the validator could only tell the Agent the generic category “one of the item
fields”. The Agent was asked to copy selector facts that framework code had failed to expose.

The first deterministic correction resolves finite local JSON-Schema `$ref` chains, rejects
external/cyclic references, and uses resolved entity schemas for catalog, pointer and type closure.
The broader correction removes the remaining mechanical transcription surface for the production
ToolSemantics leaf: the Agent must choose `bound_reference` or `bound_lookup_by_key` binding ids
from a per-tool frozen catalog. Framework code expands each id into source, pointer, collection,
primary key, selected item field and value type before the unchanged executable Rule compiler/Judge
ABI runs. Raw ToolSemantics references/selectors now fail closed; WorldRules and Curriculum retain
their own source forms until their contexts are equally frozen. This is neither a compiler
relaxation nor a new retry loop. It reduces the Agent's role to business relation selection and
keeps exact runtime state addressing programmatic.

Focused schema, compiler, scheduler and WorldSpec tests pass. A complete suite and a new live
request remain required; the failed run is immutable bad-case evidence, not release evidence.

## BC-39 — a partial telemetry projection falsely suggested that authorized repairs bypassed control

The fresh `hotel-booking-live-grok-20260722-bound-rule-bindings` request was intentionally stopped
after its first two physical ToolSemantics batches failed and both second calls had begun. A
superficial live trace showed two new spans with `attempt=1`, `repair_depth=0`,
`repair_mode=initial`, while `run inspect` showed only settled repair charges. That first
projection was incorrectly interpreted as the same coordinates restarting without a RepairAction.

Durable control artifacts falsified that conclusion. Both active attempts were `ordinal=2`, bound
the exact same immutable input closure as their parent attempt, had `repair_attempt_charge=1`, and
each referenced a distinct local `RepairAction` with `target_coordinate=current_coordinate`,
`jump_distance=0`, `repair_attempt_ordinal=1` and source `FeedbackEvaluation`. Historical live
evidence provides the required comparison: one earlier ToolSemantics shard committed after this
same authorized chain, while an independent sibling terminalized as
`repair_denied_repair_no_progress_terminal`; deterministic repair and recovery regressions likewise
reject an unauthorized continuation or duplicate charge.

Root classification is therefore **observability projection**, not a Scheduler/RepairLedger control
escape. `WorkControlRuntime._start_attempt_span()` records the durable ordinal but leaves telemetry
at its default repair depth, and the running CLI view does not yet project each active repair's
lineage or distinguish its active reservation from settled usage. The stopped process left active
operations that must be reconciled by the existing recovery path; they must not be silently freed
or replayed.

This case also produced two different first-attempt content failures: one opaque frozen binding
selection failure and one permission-scope coverage failure. They are evidence for a separate
ToolSemantics input/output-representation investigation, not evidence for a single common control
defect. No execution-control refactor is authorized from BC-39. Before any semantic-IR/prompt
change, collect cross-request issue distributions, repair yield, token/time cost and an independent
review; then compare an input representation improvement against framework-derived permission
closure and against retaining the current bounded repair boundary.

### BC-39 follow-up — evidence-constrained observability correction

The correction scope is deliberately observational. The three independent live requests
`hotel-booking-live-grok-20260721-feedback-typed`,
`hotel-booking-live-grok-20260722-bounded-feedback`, and
`hotel-booking-live-grok-20260722-bound-rule-bindings` each contained an ordinal-two
ToolSemantics attempt whose telemetry projection said `repair_depth=0`. The bounded-feedback run
also contains a successful ordinal-two attempt, so this is not a stopped-process artefact.

`WorkControlRuntime` now reads the already durable `RepairAction` only when it starts the
corresponding telemetry span. It records the semantic repair depth, decision, action revision and
process-recovery ordinal. Initial and stale-supersession attempts remain depth zero. The real-Agent
one-shot envelope likewise labels a child invocation as `authorized_repair` or `process_recovery`
from the existing immutable WorkAttempt; this label is never read by Scheduler, Repair Ledger,
budget admission, validation, invalidation or release code.

The regression drives one initial ToolSemantics attempt, one authorized local correction and one
physical process recovery under the same semantic action. It proves their projected modes/depths,
the exact action revision and one recovery ordinal. Focused lint and 17 deterministic scheduler,
one-shot and runtime tests passed. This is still not proof of a completed generated environment,
does not reconcile the intentionally stopped live job, and does not authorize a ToolSemantics
representation or control-plane redesign without further multi-case evidence.

## BC-40 — Architecture source-model validators erased known field contracts before repair

A fresh real `gpt-5.3-codex-spark` run for `用户预订宾馆` completed real ResearchPlan,
Search/Fetch/Extract and EvidenceSynthesis, then completed its WorldArchitecture Agent
invocation. The subsequent Pydantic parse recorded 60 non-actionable
`framework_diagnostic_incomplete` issues at `state_entities.*.fields.*` and
`tool_inventory.*.interface.*`, plus four ordinary `schema_too_short` issues. No RepairAction
was created, every operation/lease terminalized, and no Builder/Judge/Registry suffix ran.

The fail-closed terminal was correct: the generic error contract cannot safely authorize an Agent
to guess. Independent audit established that this is an Architecture **source-model** boundary:
the nested field/lifecycle validators raised raw Pydantic `ValueError`, and
`pydantic_validation_diagnostic` intentionally maps unknown `value_error` to a non-retryable
framework diagnostic. It is not evidence of Scheduler, BudgetLedger, RepairLedger or release
authority failure. Two earlier ToolSemanticsBatch reports share the same generic symptom but use
a different compiler path; they do not prove a common source-level root.

The bounded correction changes only two repeatedly observed Architecture source contracts:
compact field type/bounds/enum relations and lifecycle field semantics now raise allowlisted
`PydanticCustomError` values. Their safe code, path, condition and expected category survive the
one-shot boundary. Unknown raw validators remain non-actionable, and no routing/budget/retry
policy changes. Deterministic one-shot regressions cover both known contracts and the unknown
fallback; focused tests, Ruff and mypy pass. A new real run is required to show that the
Architecture WorkCommit and any subsequent repair are actually produced. This bad-case fix is not
a release claim.

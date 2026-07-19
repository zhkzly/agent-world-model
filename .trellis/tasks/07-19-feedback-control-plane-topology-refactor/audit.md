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

# Implementation and Proof Plan

Every phase starts by restating the product purpose: natural-language need to a real,
programmatic, independently verified and publishable Agent environment; code owns control
authority, Agents own bounded semantic work, and no mock/fixed replay can establish success.

Implementation is a clean break.  Each phase begins with a regression for its preserved bad
case and ends with deterministic tests.  Real execution is staged so downstream defects are
found before another multi-hour full run.

## Phase 0: freeze evidence and establish a terminating baseline

1. Preserve `.agent-world-live/batched-hotel` and `.agent-world-live/recovery` read-only.
2. Convert BC-01 through BC-18 into a machine-readable regression manifest containing run
   refs, expected diagnosis and proof classification (`live`, `reproduced`, `source`,
   `hypothesis`).
3. Isolate the hanging Verifier straggler test with process/event timestamps; determine
   framework defect versus sandbox limitation; make it terminate without weakening the
   cancellation/checkpoint/unknown-token assertions.
4. Record lint, mypy and all 494 test results as the pre-refactor baseline.

Exit: baseline commands terminate, every architectural claim is linked to evidence or marked
hypothesis.

## Phase 1: establish the replacement control contracts

1. Add WorkDefinition, WorkCoordinate, WorkAttempt and WorkCommit.
2. Add ProposalPolicy, ValidationPolicy, AssurancePolicy and numeric OperationBudget.
3. Add SafeValidationIssue/ValidationReport diagnostic-quality validation.
4. Add FeedbackEvaluation as the unique boundary terminal.
5. Add RepairPolicy, RepairAction and unified progress classification.
6. Add ReadinessProjection derived from active commits/evaluations.
7. Add contract round-trip, closed-schema, authority-boundary and tamper tests.
8. Add Artifact input/output slot contracts, ValidationExecution, AssuranceExecution,
   WorkGroup/JoinPolicy and scheduler-owned WorkAttempt telemetry before treating the kernel as
   capable of running Builder, Verifier, Integration or ReleaseAssurance.

Bad-case regressions first: BC-02/03/04/06/09.  This is schema preparation only; no production
boundary may double-write old and new authorities.  Exit: generic root diagnostics cannot request
repair and the contracts are ready for clean replacement in Phase 2.

## Phase 2: replace Designer control plane and remove microsharding

> 2026-07-19 clean-break correction: component-by-component production cutover is forbidden.
> The kernel and each one-attempt executor may be developed and exercised in diagnostic mode,
> but the first `mode=production` switch must be one complete Direct vertical slice from
> ResearchPlan through RegistryPublication.  A Design-only production graph creates two
> authorities, cannot repair/release consistently, and must not be used as package release
> evidence.

1. Prove `ToolSemanticsBatch` first in an isolated, non-release acceptance runtime: one
   WorkDefinition owns proposal budget, deterministic compiler, ValidationReport,
   FeedbackEvaluation, RepairPolicy, RepairAction, private continuation and WorkCommit.  This
   harness must not enter the ordinary Generate success path while other nodes remain old.
2. Define the shared logical Generation WorkGraph and GenerateSeed/ExpansionSeed adapters.
3. Move Direct ResearchEvidence, Architecture, Behavior, Rules, Curriculum and Modeling into
   WorkDefinitions.
4. Split shared behavior contract from tool-batch policy and fix the reproduced slot mismatch.
5. Commit physical shards hierarchically; retain successful siblings by exact dependency.
6. Route every correction through RepairAction/RepairLedger in diagnostic execution; do not
   expose a production success path until Builder, Verifier, Integration, ReleaseAssurance,
   Observability, Package and Registry are scheduler-owned too.
7. Persist and restore a private semantic continuation checkpoint only after a new repair and
   budget authorization validates all lineage/input/profile/schema/config digests.
8. Extend RuleContextCatalog to WorldRules and task/Verifier Rule contexts.
9. Delete old microsharded/skeleton recovery code after parity tests.

The production cutover is not allowed to stop at ModelingBoundary.  Merely pre-registering
downstream coordinates is also insufficient: the same scheduler must actually dispatch them,
own their leases/evaluations/repair/invalidation and derive both `release_candidate_ready` and
`released` milestones from their active commits.

Bad-case regressions first: BC-02 through BC-05 and BC-13 through BC-18.  Exit: the
existing hotel EvidenceGraph checkpoint can execute Design in bounded no-rework and bounded
repair modes with exact diagnostics and complete usage.

### 2026-07-19 implementation checkpoint

- Added closed WorkDefinition/Attempt/ProposalExecution/ValidationReport/FeedbackEvaluation/
  RepairAction/WorkRepairLedgerEntry/WorkCommit contracts with actual/unknown/conservative
  usage and monetary limits.
- Added real file-lock CAS WorkControlStore, explicit invalidation `supersede`, framework
  GenerationWorkGraph, private NodeContinuationStore, WorkRepairLedger, WorkReadinessProjection
  and executable WorkControlRuntime.
- Isolated ToolSemantics acceptance writes real Artifacts and BudgetLeases. Preserved bad cases
  prove strict progress grants one bonus, unchanged/regression terminates, restart restores the
  durable action/ledger/leases, and only an exact WorkCommit resumes. It produces none of the old
  local Feedback/Finding/SemanticNodeCommit Artifacts.
- Independent review found and the implementation closed three initial P0 defects: fake
  WorkAttempt commits are rejected by full Attempt/Proposal/Report/Evaluation/Lease/DAG checks;
  CAS tokens must correspond to a live flock; frontier advancement cannot retain old blockers.
- Current regression: `525 passed, 2 skipped`; Ruff and mypy pass for `agent_world/control`.
- This is not yet a production cutover. Designer/Builder/Verifier/Controller still execute the
  old authority path and must be replaced and deleted, not adapted or double-written.
- Independent production audit proved the current Design-only graph can be mistaken for release
  evidence and revised Direct Design loses its graph/readiness closure entirely.  Accordingly,
  the next production change is a complete vertical cut, not a Designer-only cut.

### 2026-07-19 clean-break execution-authority checkpoint

- Replaced post-hoc proposal/validation/assurance accounting with durable `OperationRun`
  scheduled/running/terminal revisions.  The Work head must point at the running dispatch before
  a real backend, validator or probe is allowed to execute.
- Added a flock-serialized persistent scope budget store.  Two real OS processes competing for
  one `agent_turns=1` reservation prove that exactly one can reserve; settlement is idempotent and
  conflicting re-settlement fails closed.  `process_calls` is now an independent budget dimension.
- Removed proposal/validation/assurance lease and execution ownership from `WorkAttempt`; an
  attempt now binds exact terminal OperationRuns and derives usage from them.
- Added the only allowed releasable topology compiler:
  `Design -> Build || Verifier -> Integration -> ReleaseAssurance -> Observability -> Package ->
  RegistryPublication`, with separate release-candidate and released milestones.  A caller cannot
  use this compiler to stop at ModelingBoundary.
- Upgraded `WorkScheduler` from a read-only projection to bounded async dispatch of ready waves.
  It opens authorized repair attempts itself, passes an exact immutable execution envelope to one
  leaf executor, and refuses a leaf that returns with an active operation or without a durable
  Commit/RepairAction/terminal evaluation.
- The first real dispatcher regression exposed and fixed an untested canonicalization defect in
  `resolve_inputs`: WorkCoordinate and ArtifactRef objects had never been converted to canonical
  JSON because the old Scheduler never called this path.
- Focused topology/dispatcher regression is `11 passed`; focused Ruff and mypy pass.

This is still **not** the production cutover. `FoundryController` continues to invoke the legacy
Design/Build/Integration/Judge/Release orchestration, and the component retry loops still exist.
The next implementation unit is therefore not another contract: it is the complete Direct leaf
executor registry and Controller switch, followed immediately by deletion of the old authorities.

### 2026-07-21 macro audit and clean-break correction

Independent Controller and Research audits confirmed that the Scheduler and complete graph are
currently shadow control planes: `FoundryController.generate()` still enters legacy component
loops, and Research has not made all immutable inputs, operation closure and failure routing
available to Scheduler.  A release-fixture regression then exposed a stronger causal defect:
the old `ClaimVector` cites `WorkReadiness`, package metadata cites that vector, but the
readiness projection needs the Package WorkCommit.  The old fixture evaded the cycle by treating
a ModelingBoundary-only production graph as release-ready.

Therefore the next implementation sequence is fixed as follows:

1. Add durable `GenerationContext` and `WorkGraphEpoch`; freeze a real bootstrap epoch only for
   the bounded Architecture discovery, then derive and persist one complete final topology.
2. Make `complete_generation_work_graph` reject missing Research/Design closure and make every
   partial graph diagnostic/non-releasable.  Do not add compatibility exceptions to Registry or
   fixtures.
3. Replace `ClaimVector` release authority with a pre-package `ReleaseDossier`, then rename the
   current Registry-after-staging dossier to `PublicationDossier`.  Package commit precedes
   release-candidate readiness; publication commit precedes released readiness.
4. Rewrite Registry and its test harness around that exact causal order.  Test fixtures may
   construct typed artifacts for negative Registry cases, but are not a production invocation
   path and cannot be called by Controller.
5. Only then add the one-attempt Direct leaf executor registry and switch `generate()` in one
   vertical cut.  Remove old Controller/Feedback/Repair component loops rather than preserving
   an adapter.

The new fail-closed manifest rule intentionally breaks 21 Registry/expansion tests that depend
on the obsolete Design-only fixture.  They are recorded migration failures, not candidates for a
relaxation.  Targeted WorkGraph/Scheduler tests remain green after the terminal-coordinate
correction; no live end-to-end run is claimed.

## Phase 3: make Evolve an input policy to the same WorkGraph

1. Retain replaceable sampling, mutation/operator and selection interfaces.
2. Convert selected MutationIntent plus parents into ExpansionSeed.
3. Remove monolithic ExpansionDesignDraft success path.
4. Use the same ResearchEvidence through ModelingBoundary definitions, repair authority and
   commit/resume semantics as Generate.
5. Add topology and execution tests proving only seed context differs.

Bad-case regression first: BC-10/11.  Exit: one real expansion candidate reaches a compiled
full Design through the shared graph; no retry occurs outside the global ledger.

## Phase 4: Builder progress, isolated diagnosis and bounded codegen

1. Adapt Builder to WorkAttempt/FeedbackEvaluation/RepairAction.
2. Journal scheduled/start/heartbeat/first-progress/first-write/end with file counts and
   sanitized deltas, never source names if policy forbids them.
3. Enforce a configurable no-progress deadline distinct from total deadline.
4. Implement diagnostic WorkGraph mode and CLI from Design/Candidate with `--no-rework`.
5. Implement exact `retry-node` with DAG validation and non-releasable diagnostics.
6. Run a real isolated Builder from a committed hotel Design with `gpt-5.4-mini`; measure
   first progress/write before deciding prompt/skill changes.

Bad-case regression first: BC-07.  Exit: a real Candidate is written and precommit checked,
or a typed bounded terminal result explains why; silence cannot last to the total timeout.

## Phase 5: assurance evidence reuse and release derivation

1. Produce digest/profile/toolchain-bound IntegrationEvidence.
2. Start real Integration as soon as Candidate commits; Verifier remains parallel.
3. Refactor ReleaseAssurance to consume matching Integration evidence and run only additive
   reachability/property/sealed/fresh-release work.
4. Derive ClaimVector and maturity from active evaluations/commits.
5. Remove duplicate static/public/protocol/materializer execution and write-only feedback
   projection.
6. Keep independent fresh deployment and fail closed on evidence-key mismatch.

Bad-case regression first: BC-06/08.  Exit: call counters prove no blind duplicate checks;
real Candidate installation, Reset/Step and task materialization pass.

## Phase 6: observability and recovery closure

1. Emit stable spans/events for all WorkAttempts, invocations, search/fetch/parser calls,
   Builder workspace progress and Judge subprocesses.
2. Separate controller-accounted, provider-observed, bounded and unknown usage.
3. Add critical path, token/time/search/tool/rework/reuse/invalidation summaries and baseline
   comparison to CLI inspect/metrics.
4. Make resume settle interrupted work and reconstruct readiness only from durable authority
   objects.
5. Ensure periodic error audit summarizes evidence without changing routing automatically.

Bad-case regression first: BC-05/07/12.  Exit: accounting discrepancies remain visible and
all long operations have terminal/progress observability.

## Phase 7: documentation and clean deletion

1. Update the canonical source document before declaring implementation complete: leaf
   validators produce ValidationReport; only decision boundaries register policy.
2. Update configuration, CLI and package docs with diagnostic and metrics commands.
3. Delete old FeedbackContract/FeedbackResult authority path, NodeCommit duplication,
   component retry maxima and unreachable Designer/Evolve paths.
4. Run `rg` absence checks for old CLI/ABI/replay/fixed environment branches.

Exit: documentation describes only the executable new path and no compatibility layer is on
the success path.

## Phase 8: staged real proof

Run each stage with real dependencies and retain exact Artifact refs:

1. real ResearchPlan, search/fetch/extract and EvidenceGraph;
2. real shared Designer through EnvironmentDesign;
3. real isolated Builder through Candidate;
4. clean install and deployment;
5. Runtime `Reset` and multiple `Step` calls;
6. Task Materializer v3 and public self-check;
7. real Challenger compilation and ReleaseAssurance including sealed checks;
8. envpkg assembly and Registry atomic reread.

No stage is skipped because an earlier stage was expensive.  A completed prior Artifact is
reused by digest; no manual edits are permitted.

## Phase 9: canonical and negative live acceptance

1. Start a fresh run from exactly `用户预订宾馆` using configured real search and the explicit
   configured OpenAI-compatible profile (`grok-4.5` preferred; `gpt-5.4-mini` only if selected
   as a documented quota/availability fallback), normal reasoning, real subprocesses and no mock
   backend.
2. Require final `RELEASED`, package ref, Registry record and executable Reset/Step evidence.
3. Run a separate negative case that triggers one actionable local repair and proves bounded
   progress/no-progress behavior.
4. Produce the experimental report: stage latency distribution, critical path, token input /
   output / total, Agent turns, search/fetch/parser calls, subprocess/test counts, first-write,
   repair transitions, reuse/invalidation, duplicate-work savings and explicit unknowns.

Exit: the product goal is demonstrated by real E2E, not inferred from unit tests.

## Verification commands

Commands may be refined as the CLI changes, but every phase uses `uv`:

```text
uv run ruff check agent_world tests/agent_world
uv run mypy agent_world
uv run pytest -q tests/agent_world
uv run agent-world doctor --config <real-config>
uv run agent-world run diagnose --from <design-ref> --until integration --no-rework
uv run agent-world run inspect <request-id> --metrics
```

The final run command and exact state root are recorded in the live acceptance report.  No
credential or API key is copied into task documents, traces or packages.

## 2026-07-21 next executable sequence: DirectWorkRunner vertical slice

The first production switch must be one complete Direct vertical slice. Do not wrap old
`EnvironmentDesigner.generate()` as a Scheduler leaf: it performs its own retry, Feedback and
WorkCommit work, which would preserve a second control plane inside the new one.

1. Extract one-shot, profile-isolated structured Agent invocation from Designer. It performs no
   retry and returns safe `LeafValidationFailure` diagnostics plus actual provenance/usage.
2. Implement Scheduler leaves for ResearchPlan, real search/fetch/extract Acquisition,
   EvidenceSynthesis and WorldArchitecture; freeze and execute the diagnostic bootstrap epoch.
3. Derive coupling groups only from the committed Architecture; freeze the final graph preserving
   exact bootstrap commits. Add Design behavior/rules/curriculum/modeling leaves until the final
   `EnvironmentDesign` commits under Scheduler authority.
4. Wire existing one-attempt Builder/Verifier/Integration/ReleaseAssurance/Observability/
   Package/Registry leaves into one `DirectWorkRunner`; test a non-mock complete fixture
   vertical slice including a physical Candidate deployment and atomic Registry reread.
5. Replace the public Controller path and delete the old direct loop, legacy feedback/repair
   release projection and component-local correction authority. Only after deletion run the
   opt-in live hotel request with the configured provider model.

The immediate deterministic regressions are: every pre-package final-graph attempt must appear
in telemetry closure; a code-leaf Pydantic failure must preserve a safe field path rather than
become generic `leaf_execution_error`. Both must pass before new leaves are added.

## 2026-07-21 progress after control-plane audit

Completed and regression-tested:

1. Safe deterministic Pydantic projection in the shared leaf kernel.
2. Pre-package telemetry now requires every final-graph pre-package WorkAttempt.
3. A one-turn structured-Agent primitive with Scheduler dispatch identity/provenance and no local
   repair loop.
4. A Scheduler-owned `ResearchPlanLeaf` that consumes only `GenerationContext` and emits one
   durable ResearchPlan Artifact.
5. Scheduler inputs retain `GenerationContext` for every coordinate rather than dropping it after
   the first node.
6. `ResearchAcquisition` is a public Artifact contract and `ResearchAcquisitionLeaf` invokes the
   real search/fetch/extract toolchain outside the WorkHead lock, then commits its complete source
   closure.
7. Search, fetch and extract are independently counted in `ResearchBundle`, telemetry and total
   tool budget. A work/source budget must reserve at least `search_calls + 2` calls; checkpoint
   reuse records unknown historical counts instead of zero.
8. `EvidenceSynthesisLeaf` is a one-shot, tool-free Researcher leaf consuming only the committed
   acquisition closure and emitting exact `design.evidence_synthesis` plus `design.evidence_graph`
   outputs under Scheduler authority.
9. `WorldArchitectureLeaf` is a one-shot, tool-free isolated Engineer leaf consuming only the
   committed synthesis/graph closure. Its deterministic compiler emits exact architecture source,
   WorldSkeleton and framework-derived ToolCouplingPlan outputs, and the four-node diagnostic
   bootstrap can be frozen after all four real WorkCommits.
10. WorkGraph's underscore role id is translated once at the SDK boundary to the established
    hyphenated profile id, so Architecture receives the actual least-privilege Engineer profile
    rather than a silent researcher fallback or ambient credentials.
11. Scheduler now terminalizes a failed operation-budget admission only when no OperationRun has
    started: it writes exact safe budget evidence, error report, blocking evaluation and terminal
    `budget_exhausted` attempt, then closes any authorized repair ledger entry as `exhausted`.
    This prevents BC-26's orphaned running head without pretending an unstarted retry made
    semantic progress.
12. A real isolated `grok-4.5` structured probe completed using the explicitly supplied
    per-process endpoint. A subsequent real four-node `用户预订宾馆` bootstrap committed
    ResearchPlan but stopped at Acquisition after two bounded real provider-unavailable outcomes.
    It is retained as negative live evidence only; no Design, Candidate or release is claimed.

Next implementation boundary:

1. Derive the only final production epoch from the committed ToolCouplingPlan while retaining the
   byte-identical bootstrap definitions and commits; do not create a shadow Design path.
2. Move behavior/rules/curriculum/modeling into leaf-sized Scheduler transactions before wiring existing
   Builder/Verifier/Integration/Release leaves. Do not invoke or wrap legacy `generate()`.

### 2026-07-21 production cutover and closure verification

The Direct Controller switch and three-epoch `DirectWorkRunner` are now implemented. Bootstrap,
final Design and final release use strict typed input contracts, while Builder, Verifier,
Integration, Assurance, Observability, Package and Registry are Scheduler leaves rather than a
second Controller workflow. This does **not** complete the live hotel acceptance: the latest real
provider run reached SharedToolSemantics and stopped through the bounded no-progress policy.

The current deterministic proof deliberately separates framework closure from model quality:

1. a least-privilege parent with allowed and sealed outputs makes its child `ready` both during
   dispatch and a fresh Scheduler snapshot;
2. real Scheduler `Package -> RegistryPublication` execution builds the package closure, stages,
   rereads and atomically releases the envpkg in about 44 seconds;
3. pre-package observability includes every final-graph attempt; and
4. a possibly spent historical Direct snapshot fails closed without Agent replay, while a
   nonpassing Judge Report cannot assemble an EnvironmentPackage.

The next task is not another local retry relaxation. It is a staged real run with the current
explicit model/profile and research provider, followed by a fresh Request-to-Registry acceptance
only after each newly reached boundary has its own evidence. No Controller fallback, fixture, or
manual Artifact edit may turn that run into a success.

### 2026-07-21 diagnostic and observability repair

The next real run exposed a framework information-loss failure rather than a validation-policy
failure: `SharedToolSemantics` had safe, path-addressed semantic diagnostics, but the structured
leaf adapter replaced their violated condition and expected category with generic text before its
one Scheduler-authorized local correction.  The fix preserves those two safe fields end-to-end;
no-progress continues to compare the exact issue tuple, so an error changing into a different
error remains progress but does not become a false pass.

The same evidence showed that live Direct inspection read only the terminal Controller snapshot,
although Scheduler operations had already updated durable scope leases.  Inspection now reads the
Scheduler lease ledger for active actual/unknown/reserved projection, and WorkAttempt spans inherit
the Direct root.  This is observability-only: it does not add an Agent call, alter a gate, or create
a second control plane.  Focused lint, typing and 20 deterministic tests pass; a full suite and a
fresh real hotel Request-to-Registry run remain required before any live success claim.

### 2026-07-22 timeout settlement repair

The next real hotel run crossed all research leaves and timed out in WorldArchitecture after the
actual SDK invocation had already streamed for its bounded operation duration. The timeout adapter
had correct unknown-budget handling but constructed Agent provenance too late, so the leaf terminal
writer rejected it and left the OperationRun active. Provenance now binds Scheduler dispatch id and
resolved profile before the provider call; timeout/transport results become a normal terminal
ProposalExecution + Validation/Evaluation under the existing replay policy. Focused lint, mypy and
14 deterministic one-shot/Scheduler tests pass. This is not a retry relaxation and does not repair
or replay the failed run; increase an explicit per-run wall policy only when a fresh real request is
authorized to spend it.

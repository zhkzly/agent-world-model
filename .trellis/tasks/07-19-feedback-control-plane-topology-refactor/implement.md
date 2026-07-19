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

Bad-case regressions first: BC-02/03/04/06/09.  This is schema preparation only; no production
boundary may double-write old and new authorities.  Exit: generic root diagnostics cannot request
repair and the contracts are ready for clean replacement in Phase 2.

## Phase 2: replace Designer control plane and remove microsharding

1. Migrate `ToolSemanticsBatch` first as the live proof boundary: one WorkDefinition owns
   proposal budget, deterministic compiler, ValidationReport, FeedbackEvaluation,
   RepairPolicy, RepairAction, private continuation and WorkCommit.  Remove its old
   FeedbackResult/Event/Disposition/Finding retry chain rather than double-writing.
2. Define the shared logical Generation WorkGraph and GenerateSeed/ExpansionSeed adapters.
3. Move Direct ResearchEvidence, Architecture, Behavior, Rules, Curriculum and Modeling into
   WorkDefinitions.
4. Split shared behavior contract from tool-batch policy and fix the reproduced slot mismatch.
5. Commit physical shards hierarchically; retain successful siblings by exact dependency.
6. Route every correction through RepairAction/RepairLedger; delete local semantic retry
   counters as authorities.
7. Persist and restore a private semantic continuation checkpoint only after a new repair and
   budget authorization validates all lineage/input/profile/schema/config digests.
8. Extend RuleContextCatalog to WorldRules and task/Verifier Rule contexts.
9. Delete old microsharded/skeleton recovery code after parity tests.

Bad-case regressions first: BC-02 through BC-05 and BC-13 through BC-18.  Exit: the
existing hotel EvidenceGraph checkpoint can execute Design in bounded no-rework and bounded
repair modes with exact diagnostics and complete usage.

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

1. Start a fresh run from exactly `用户预订宾馆` using configured real search and Codex auth,
   exact model `gpt-5.4-mini`, normal reasoning, real subprocesses and no mock backend.
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

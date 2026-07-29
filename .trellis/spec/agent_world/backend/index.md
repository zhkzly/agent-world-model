# agent_world Backend Guidelines

Read `docs/agent-world-environment-generation.zh.md` first.

Rules:

- Keep success paths artifact-driven.
- Keep all model/agent execution behind `InvocationBackend`; production uses the isolated
  `CodexSdkBackend` adapter and pipeline core never calls provider SDKs directly.
- Give Researcher, Environment Engineer, and Challenger separate capability profiles;
  skills, hooks, tools, credentials, source views, and sealed evidence are deny-by-default.
- Direct Generation is independent. Discovery is non-blocking and Evolve is optional;
  neither may bypass `WorldSpec -> Builder -> Judge -> Registry`.
- Treat tool surface, tool semantics, state/transition constraints, and task scope as
  Evolve genotype. Source-code reuse is only a Builder implementation strategy.
- Do not add mock, template, replay, fixed-environment, compatibility, or alternate
  production success paths.
- Keep release decisions framework-owned.
- Keep package paths relative and movable.
- Keep live model/network tests opt-in.
- Run `uv run pytest tests/agent_world` before claiming this slice still works.

## Local execution state roots and live observability

For a normal `generate` or E2E run, configure `state_root` outside the
reserved `.agent-world-live/` tree; this repository uses
`.agent-world-staged/<run>/state` for durable, gitignored normal-run evidence.
`ObservabilityRoot` deliberately rejects ordinary state beneath
`.agent-world-live/`, so that location is not a valid way to make a normal
E2E private.

`.agent-world-live/` is only for private live diagnostics such as doctor state
and marked `test-node` clones. A test-node clone has its own explicit marker;
do not infer that a normal Generate run may use the same path.

Read on demand:

- `docs/configuration.zh.md` — safe normal configuration shape and state-root
  choice.
- `agent_world/app.py` — application-level reserved-live guard.
- `agent_world/observability/paths.py` — scene-cache path guard and its exact
  failure meaning.

## Artifact DAG verification

### 1. Scope / Trigger

- Applies whenever `ArtifactStore` resolves one or more `ArtifactRef` values and recursively
  verifies their dependency graph.

### 2. Signatures

- Public reads keep their existing signatures; recursive helpers accept a verification map scoped
  to that one public read or batch normalization call.

### 3. Contracts

- Memoize a verified revision only inside the current call graph, keyed by revision identity.
- Never retain verified content across public calls: every later read must reopen and re-hash disk
  state so post-read tampering remains detectable.

### 4. Validation & Error Matrix

- Missing dependency -> artifact-not-found error.
- Hash, attestation, identity, or dependency mismatch -> integrity error.
- A shared valid dependency -> verify once per call, then reuse that verified value.

### 5. Good/Base/Bad Cases

- Good: a diamond DAG is linear in unique revisions and a later tamper still fails.
- Base: a single revision is reopened and verified on each public read.
- Bad: no memoization causes exponential traversal; global memoization hides later tampering.

### 6. Tests Required

- Assert a shared DAG completes without repeated exponential reads.
- Read once, mutate an on-disk revision or blob, and assert the next public read fails closed.

### 7. Wrong vs Correct

- Wrong: cache a verified revision on the store instance.
- Correct: pass one local `dict[revision_id, verified_revision]` through recursive verification and
  discard it when the public call returns.

## Invocation transport recovery and provider routing

### 1. Scope / Trigger

- Applies when changing `AgentBackendConfig`, `ResolvedAgentProfile`, `CodexSdkBackend`, or a
  structured Designer node's retry behavior.

### 2. Signatures

- `AgentBackendConfig.openai_base_url: HttpUrl | None`
- `InvocationError.retryable: bool`
- `EnvironmentDesigner.run_structured_agent(...) -> (typed_output, InvocationResult...)`

### 3. Contracts

- `openai_base_url` is non-secret, API-key-only, credential-free, hashed profile input and is
  materialized into the isolated `$CODEX_HOME/config.toml`; never inherit it ambiently.
- A retryable failed result remains in lineage. Retry the exact immutable prompt in a fresh
  session, within the existing turn/repair lease; do not treat it as semantic correction.
- Controller failure evidence records backend code, retryable flag and attempt count without raw
  provider messages.

### 4. Validation & Error Matrix

- `openai_base_url` + ChatGPT login -> configuration error.
- `openai_base_url` + non-OpenAI custom provider id -> configuration error.
- URL credentials/query/fragment -> configuration error.
- retryable backend failure + remaining lease -> fresh-session node retry.
- non-retryable failure or exhausted retry lease -> `DesignerError` and release-blocking Finding.

### 5. Good/Base/Bad Cases

- Good: transient TLS/provider failure, failed result retained, second real turn succeeds.
- Base: first real turn succeeds; no retry is scheduled.
- Bad: reuse a partially failed session, silently change prompt/model/provider, loop without a hard
  lease, or reclassify infrastructure failure as a WorldSpec defect.

### 6. Tests Required

- Assert retry uses `session is None`, identical prompt, `repair_mode=backend_retry`, and returns
  both failed and successful results.
- Assert compatible base URL is in materialized config/public profile but API key is absent.
- Live acceptance must still run the real configured model; unit doubles do not prove production.

### 7. Wrong vs Correct

- Wrong: abort the whole GenerateJob on every `turn_failed`, or read `OPENAI_BASE_URL` from ambient
  worker environment.
- Correct: adapter marks only retryable terminal failures; Designer schedules a bounded fresh turn;
  Profile Resolver explicitly materializes and hashes the configured base URL.

## Designer phase checkpoint recovery

### 1. Scope / Trigger

- Applies whenever Direct Generation fails after research has produced a typed `EvidenceGraph`.

### 2. Signatures

- `DesignPhaseCheckpoint.phase: Literal["evidence_graph"]` on the production path.
- `EnvironmentDesigner.adopt_latest_phase_checkpoint(...) -> ArtifactRef`
- `EnvironmentDesigner.resume_from_phase_checkpoint(...) -> DesignBundle`

### 3. Contracts

- The only stable checkpoint binds exact job, request and EvidenceGraph revisions by hash.
- Resume adopts the unique valid EvidenceGraph for the same immutable job/request.
- Evidence resume performs no Researcher, search, fetch or extract call and reports zero new
  research usage; it recompiles World Boundary and downstream world nodes.
- Cross-request evidence reuse requires a separate explicit freshness/adoption policy and is not
  inferred from similar natural-language text.

### 4. Validation & Error Matrix

- Exact unique EvidenceGraph -> adopt the typed evidence checkpoint and resume before
  WorldArchitecture.
- Any `world_skeleton` phase -> reject as retired microsharded ABI.
- Multiple candidate revisions -> `checkpoint.ambiguous`.
- Missing, dependency-unbound, ABI-mismatched or semantically invalid artifact -> fail closed.

### 5. Good/Base/Bad Cases

- Good: one world-modeling failure resumes from EvidenceGraph without a new research directory.
- Base: initial generation researches once and commits the EvidenceGraph checkpoint immediately.
- Bad: create a new request id after every downstream failure, silently choose one of several
  revisions, or claim that an uncommitted model transaction is a safe recovery point.

### 6. Tests Required

- Assert adopted evidence binds exact request/job/graph revisions.
- Assert public Designer and Controller APIs cannot adopt or resume a `world_skeleton` checkpoint.
- Assert evidence resume has empty invocation prefix, zero research usage and a
  `design_phase_resumed` event.
- Live acceptance must show `design-resume/resumed-evidence-checkpoint.json` and no new research
  workspace or external search calls.

### 7. Wrong vs Correct

- Wrong: treat Designer as one atomic stage and restart Direct Research after a downstream schema
  validation failure.
- Correct: retain immutable evidence lineage, revalidate its checkpoint, and rerun only the
  dependent world-compilation suffix.

## Compact architecture and deterministic schema compilation

### 1. Scope / Trigger

- Applies whenever Designer turns one `WorldArchitectureSourceDraft` into state and tool schemas.

### 2. Signatures

- Model output: compact entity field and tool interface semantics; no schema graph or JSON Schema.
- Framework output: closed Entity/Tool Schema IR and Draft 2020-12 JSON Schema.

### 3. Contracts

- The Agent owns names, business meanings, scalar categories, nullability, cardinality and bounded
  scalar constraints. It owns neither a schema node graph nor raw JSON Schema syntax.
- Framework code deterministically owns root objects, ids, references, requiredness, array items,
  nullable unions, scalar constraints, lifecycle closure and `additionalProperties=false`.
- `WorldArchitectureSourceDraft.model_json_schema()` must stay compact enough for one transaction;
  adding schema-compiler mechanics to it is an ownership regression.

### 4. Validation & Error Matrix

- Duplicate/invalid business field or frozen identity drift -> one architecture correction.
- Broken framework reference, invalid compiled Draft or open object -> framework defect; do not ask
  the Agent to repair compiler syntax.
- More than the bounded tool count/context size -> reject scope before invocation or partition only
  the ToolSemantics transaction, never split schema mechanics into per-field turns.

### 5. Good/Base/Bad Cases

- Good: an optional repeated guest-name field compiles into a required root property whose value is
  a nullable array with framework-owned `items`.
- Base: an empty tool input compiles into a closed object without model-authored schema keywords.
- Bad: ask the model to author node ids, `required`, `items`, `properties` or references.

### 6. Tests Required

- Assert compact entity/tool fields compile to valid closed Drafts with stable ids/references.
- Assert Architecture structured-output schema excludes state/tool Schema IR fields and stays under
  the fixed size budget.
- Assert compiler failures are framework failures and cannot consume semantic repair attempts.

### 7. Wrong vs Correct

- Wrong: retry malformed model-authored Schema IR with increasingly detailed examples.
- Correct: keep only business meaning in typed Agent output and all schema mechanics in a small,
  deterministic, fully tested framework compiler.

## Prohibited per-entity schema sharding

The retired microsharded Designer asked the Agent to author a Schema IR once per entity/tool and
then tried to recover individual shards. Do not restore it. Entity cardinality may increase compact
architecture output and deterministic compiler work, but must not increase Agent transaction count.
Validation diagnostics still use stable field paths and monotonic frontiers; A-to-B progress is
real progress, while A-to-B-to-A within one RepairTarget family is oscillation and stops locally.

## Control-plane bad-case admission before a structural refactor

### 1. Scope / Trigger

Apply before changing Scheduler, RepairLedger, BudgetLedger, invalidation, release authority,
semantic proposal representation, or an alleged cross-scope reuse policy because of a live run,
telemetry observation, or a new design plan.

### 2. Signatures

- ValidationReport(issue.code, issue.path, issue.violated_condition, issue.expected_category)
- FeedbackEvaluation(subject_ref, validation_policy_digest, terminal_decision)
- RepairAction -> WorkRepairLedgerEntry -> WorkAttempt
- WorkCommit(job_ref, request_ref, acceptance_digest, immutable_input_closure)

### 3. Contracts

- Record each claim as confirmed fact, reproducible hypothesis, or unverified plan assertion,
  together with its exact bad-case/Artifact references.
- A one-off live trace may authorize observability or a local fail-closed repair only. A
  Scheduler/Repair/Release redesign needs two independent cases or one case plus a deterministic
  regression that reproduces the same causal mechanism.
- Reuse is only for the exact job/request/acceptance closure unless an explicit freshness and
  adoption policy authorizes another scope. A natural-language need fingerprint is never enough.
- Issue progress is the code-defined issue/frontier/lineage lattice; raw issue count alone is not
  a progress metric.

### 4. Validation & Error Matrix

- Missing safe path/condition/category -> framework_diagnostic_incomplete, no Agent repair.
- Repeated normalized issue state -> no-progress terminal; a recurring ancestor -> oscillation
  terminal.
- Ready coordinate without an exact executor -> scheduler_executor_missing, no semantic repair.
- Reuse with a changed job/request/acceptance closure -> reject adoption before dispatch.

### 5. Good / Base / Bad Cases

- Good: BC-29/31 preserve safe semantic diagnostics and one authorized correction.
- Base: BC-17 may advance a validation frontier while exposing a different issue set; it is not
  evidence that issue count must shrink.
- Bad: BC-39 telemetry looked like an unauthorized retry, but durable artifacts proved it was an
  observability defect; do not redesign control authority from the projection.

### 6. Tests Required

- The changed boundary has a failing-then-passing deterministic regression and its bad-case IDs.
- A current-head live acceptance is run only after production preflight; it records profile digest,
  model, usage provenance and exact Artifact refs without credentials or provider transcripts.
- Any reuse change proves both exact-closure reuse and fail-closed cross-scope rejection.

### 7. Wrong vs Correct

- Wrong: infer a global typed-hole redesign or cross-campaign cache from one expensive run.
- Correct: isolate the mechanical contract, prove it with a bounded regression and independent
  evidence, then preserve the real semantic and fresh-execution gates.

## Batched tool semantics and WorldRules

### 1. Scope / Trigger

- Applies after compact architecture schemas compile and before TaskCurriculum.

### 2. Signatures

- Agent transactions: up to two `ToolSemanticsBatchSourceDraft` values (at most four coupled tools
  each), then one `WorldRuleSemanticsSourceDraft` for initial-state and global invariants.
- Framework output: closed ToolContracts and WorldModel Rule IR.

### 3. Contracts

- Partition tools by shared state and transaction coupling, not by environment id.
- Tool batches have exact RepairTarget identity and stable order. Current scheduler is sequential;
  concurrency is allowed only after backend capacity, lease accounting and deterministic commit
  behavior are proven.
- WorldRules owns business initial-state/invariant meaning only. Framework validates every path and
  compiles Rule IR; it never asks the model to repair framework-generated ids or schema syntax.
- `WorldRuleSemanticsSourceDraft.RuleDraft.rule_id` is optional input mechanics, never business
  meaning. Before persistence or core compilation, framework code canonicalizes it away and derives
  `rule:state:<ordinal>` for `initial_state_rules.initial_state_constraints` and
  `rule:world:<ordinal>` for `invariants` from the frozen section plus ordinal.
- Rule family remains Agent-owned semantic content: the first section uses `initial_state` and the
  second uses `invariant`. A wrong family is a safe actionable diagnostic; an identity prefix or
  duplicate failure is a non-retryable framework invariant and must not enter an
  `AgentCorrectionBrief`.
- The full pre-Build Direct proposal graph has at most eight base turns: two research,
  architecture, an optional multi-batch shared contract, one or two tool batches, world rules and
  curriculum. A global WorkGraph budget currently reserves at most two semantic corrections, so
  the hard envelope is ten turns. No component-local counter may grant work beyond that envelope;
  a second correction for one logical Artifact requires code-proven strict progress.

### 4. Validation & Error Matrix

- Unknown business path in Agent RuleDraft -> local WorldRules correction.
- Invalid framework-compiled path/id/schema -> framework failure, no semantic correction.
- Wrong WorldRules source family -> local WorldRules correction with a section-relative path;
  arbitrary/missing Agent IDs -> canonical source plus deterministic compiled identity, not a
  correction prompt.
- A framework-owned fixed input-byte, hidden output-token, or arbitrary short first-progress/
  first-write deadline must not reject, truncate, or prematurely cancel a ToolSemantics
  transaction. First-progress/first-write remain observations; record any real
  Provider/transport physical terminal safely, then select a route, transport, workspace-input,
  or topology change from evidence.
- Provider retryable failure below the bound -> bounded fresh-session retry under the same target.

### 5. Good/Base/Bad Cases

- Good: reserve/cancel tools that share booking state are one batch; global inventory non-negativity
  is expressed once in WorldRules and compiled by code.
- Base: one small tool produces one tool batch and one WorldRules transaction.
- Bad: invoke one Agent per precondition/postcondition field or merge rules into a giant architecture
  prompt that spends ten minutes before producing its first artifact.

### 6. Tests Required

- Assert eight tools form at most two stable batches and nested tool identity drift fails locally.
- Assert WorldRules compile only after all tool batches and preserve source evidence bindings.
- Assert arbitrary WorldRules `rule_id` values are absent from the persisted canonical source and
  compile to the two framework namespaces; assert a wrong section family remains the only
  corresponding actionable source diagnostic.
- Measure every real semantic transaction's wall time, tokens, repair mode and projection size.

### 7. Wrong vs Correct

- Wrong: spend the retry lease on one redundant 250+ KiB transaction or on per-field turns.
- Correct: send compact business semantics in bounded transactions and compile all executable
  contracts in framework code.

## Modeling uncertainty closure and no-progress protection

### 1. Scope / Trigger

- Applies when the Modeling Gate reports `unresolved_assumptions_forbidden` for Direct Generation.

### 2. Signatures

- `AssumptionIssue(issue_id, statement, origins)`
- `AssumptionResolutionDraft(issue_id, question, disposition, claim, fidelity)`
- `FoundryController._modeling_unresolved(...) -> tuple[str, ...]`

### 3. Contracts

- Collect model-owned issues from EvidenceGraph, EnvironmentDesign, WorldSpec and every
  CoverageDimension; deduplicate identical statements but retain every exact origin.
- One lightweight Assumption Closure turn resolves the whole frozen issue set. Compile each result
  back only into its owning fields; bounded coverage omissions become known divergences.
- Both initial and revised Modeling Gate findings use this route. Explicit request-level human
  unknowns remain human-owned.
- If a directed revision leaves the blocking issue set unchanged, stop with
  `design_rework_no_progress`; never fall back to whole-design regeneration.

### 4. Validation & Error Matrix

- product decision -> supported product-decision Claim plus synthetic-policy Fidelity.
- bounded out of scope -> supported bounded-assumption Claim, bounded-approximation Fidelity, and
  coverage known divergence where applicable.
- needs human -> retain the exact owning unknown and fail the gate closed.
- issue id/order/origin mismatch -> reject the Agent output within its bounded node lease.

### 5. Good/Base/Bad Cases

- Good: three evidence questions and three coverage gaps close in one typed turn.
- Base: no model-owned issues means the closure route is not invoked.
- Bad: clear only EvidenceGraph questions, treat a known limitation as unresolved forever, or
  rename a revised gate failure so it triggers a 500 KiB EnvironmentDesign rewrite.

### 6. Tests Required

- Assert identical statements across four artifact sources become one issue with four origins.
- Assert revised-gate findings still select Assumption Closure.
- Assert bounded coverage resolutions remove unknowns and preserve known divergences.
- Assert an unchanged blocking set terminates instead of recursing.

### 7. Wrong vs Correct

- Wrong: count every explanatory coverage string as an unresolved release question.
- Correct: keep unresolved questions, policy decisions and known divergences as distinct semantics,
  and stop automatic repair when its issue fingerprint makes no progress.

## Work identity, successful acceptance, and repair epochs

- `definition_digest` binds the complete policy for a new execution: executor, budgets,
  deadlines, validation, repair routing, mutation authority, and topology.
- `acceptance_digest` alone decides whether an immutable passing `WorkCommit` remains reusable.
  It binds exact inputs separately plus coordinate, Claim, dependency topology, output contract,
  acceptance transform, explicit validator executable revision, assurance requirements, and
  success maturity.
- `repair_epoch_digest` binds full definition, exact inputs, validation policy, and repair policy;
  progress, retry ordinals, and no-progress decisions never cross epochs.
- Changing token/time limits, timing prose, or repair/recovery caps must not invalidate an already
  accepted output. Changing input refs, Claim, schema/transform, validator revision, assurance, or
  maturity must fail closed and require a new success.
- Before reactivating historical success over a running head, release its real active lease, persist
  an interrupted attempt, then atomically repoint the head. Never replace active semantic repair
  authority with cache recovery.
- Bad case: adding one process-recovery field changes every full WorkDefinition digest and reruns
  ResearchPlan/Evidence despite unchanged acceptance. Required regression tests must distinguish
  policy-only changes from validator/schema changes and verify no orphaned lease remains.

## Judge Finding groups and executable RepairAction accounting

### 1. Scope / Trigger

- Applies when one Judge/Integration report contains multiple Findings and Controller authorizes
  downstream or upstream repair.

### 2. Signatures

- `RepairRouter.route_many(Sequence[tuple[Finding, ArtifactRef]]) -> tuple[RepairDirective, ...]`
- `RepairDirective.related_finding_refs: tuple[ArtifactRef, ...]`
- `RepairLedgerEntry.related_finding_refs: tuple[ArtifactRef, ...]`

### 3. Contracts

- Persist every Finding independently, then group by framework-resolved `(owner_node, action)`.
- One group creates one directive, one ledger entry and consumes one actual `repair_attempts` unit.
- The directive cites one primary ref plus every related ref; its evidence and disclosure are the
  safe union of all group members.

### 4. Validation & Error Matrix

- Empty group -> value error.
- Mixed owner/action in `route_group` -> value error.
- Repeated primary/related ref or duplicate related ref -> contract validation error.
- Authorized structured correction without remaining vector budget ->
  `StructuredRepairDenied(global_repair_budget_exhausted)`.

### 5. Good/Base/Bad Cases

- Good: five runtime Findings produce one Builder work order with five cited refs.
- Base: one Finding produces one action and no related refs.
- Bad: consume five repair attempts because one real execution exposed five symptoms.

### 6. Tests Required

- Assert same-owner Findings produce one route/ledger entry and retain every ref/summary.
- Assert mixed owners produce separate actions.
- Assert completion consumes the authoritative `BudgetLedger.repair_attempts` dimension.

### 7. Wrong vs Correct

```python
# Wrong: evidence cardinality becomes execution cardinality.
routes = tuple(router.route(finding, ref) for finding, ref in findings)

# Correct: framework groups evidence into executable work.
routes = router.route_many(findings)
```

## Research telemetry and release observability closure

### 1. Scope / Trigger

- Applies to each real ResearchToolchain search/fetch/extract and every envpkg release.

### 2. Signatures

- Operations: `research.search`, `research.fetch`, `research.extract` WorkSpans.
- `TelemetryReleaseSummary.required_operation_attempts`
- `TelemetryReleaseSummary.required_metric_observations`
- CLI: `metrics summarize --trace-id ...`; `metrics compare --trace-id BASE --trace-id CANDIDATE`.

### 3. Contracts

- Open and flush a span before each provider operation; close it with typed terminal status.
- Store provider plus query/URL SHA-256 only, never raw query, URL credentials or body.
- Pre/post publish require successful search/fetch/extract spans and observations for total tokens,
  search calls, fetch calls and extracted documents. Unknown token value remains unknown.
- Registry independently checks the exact operation/metric key sets and positive observation counts.

### 4. Validation & Error Matrix

- Missing operation or metric category -> `release_observability_unhealthy` before publish.
- Registry sees incomplete typed closure -> `ReleaseRejectedError`.
- One-trace compare -> value error; summarize accepts one or more traces.
- Sensitive telemetry key/value -> `TelemetryError`.

### 5. Good/Base/Bad Cases

- Good: fallback fetch has a failed primary span and a passed Jina span, both auditable.
- Base: one search, one fetch and one extraction produce three child spans.
- Bad: record only aggregate `search_calls=3`, or write missing provider usage as zero.

### 6. Tests Required

- Assert per-operation spans exist and raw query/URL text is absent.
- Assert trace distributions preserve unknown counts and baseline deltas.
- Tamper required operation/metric keys and assert Registry rejects the release.

### 7. Wrong vs Correct

```python
# Wrong: terminal aggregate cannot explain latency or partial failure.
telemetry.record_research_bundle(bundle)

# Correct: span every real boundary, then also record the terminal aggregate.
span = start("research.fetch", identity_hash=sha256(url))
source = await fetcher.fetch(url)
span.finish(status="passed")
```

## Shared Generate/Expand WorkGraph and canonical design compilation

### 1. Scope / Trigger

- Applies to every Direct Generate and Evolve-selected Expansion candidate.
- Triggered after a GenerateSeed or ExpansionSeed is frozen and whenever one exact logical Design
  Artifact is repaired.

### 2. Signatures

- Seed adapters: `GenerateSeed | ExpansionSeed -> GenerationContext`.
- Shared logical work: `ResearchEvidence -> WorldArchitecture -> WorldBehavior -> WorldRules ->
  TaskCurriculum -> ModelingBoundary`.
- Stage outputs are compact typed semantic sources; framework compilation produces the complete
  `EnvironmentDesignDraft` and, for Expansion, the authoritative SemanticDelta against parents.
- `ExpansionDesignDraft` is not a production success boundary.

### 3. Contracts

- Generate and Expand instantiate the same WorkDefinitions, ValidationPolicies, RepairPolicies and
  WorkCommit hierarchy. They differ only in frozen GenerationContext: Expansion adds exact parent
  refs, MutationIntent, coverage target and admitted clues.
- Agent owns compact business field/tool meaning, executable world Rule semantics, curriculum
  topology and ordered task semantics. It does not own schema graphs or protocol syntax.
- Framework exclusively compiles StateSchema/ToolSurface/WorldModel, task reset/public/evaluator
  schemas, goal bindings, reachability, RewardSpec and VerificationRequirements.
- Reward is task-outcome aggregation fixed at 0/+1/-1 with failure-over-success precedence; Rule
  count cannot amplify it.
- Expansion MutationIntent includes operation, subject identity, exact parent refs, changed aspects
  and rationale. The authoritative SemanticDelta, including every `after`, is framework-computed
  only after the common complete Design commits.
- Every semantic correction is authorized by the same global RepairLedger. Expansion may not use
  `EnvironmentDesigner.maximum_structured_reworks` as an independent retry authority.
- Provider-normalized output schemas must retain the same forbidden-field boundary; checking only
  Pydantic `model_fields` is insufficient.

### 4. Validation & Error Matrix

- Task draft order/identity differs from CurriculumPlan -> reject the structured Agent turn.
- Compact architecture contains an unsupported field semantic -> reject Architecture locally.
- A root task-reset projection failure after typed IR validation -> framework invariant failure;
  persist the state-shape subject and do not trigger semantic rework.
- Task reset schema changes only because framework recompiled a changed state -> no TaskScopeDelta.
- Curriculum distribution changes -> one TaskDistributionDelta with exact framework before hash.
- Mutation scope differs from framework-computed parent diff -> reject the owning shared stage or
  final identity boundary; do not regenerate one giant design.
- Agent output includes raw state/tool schema, task schema/binding/reward/verification, unresolved
  release blockers, or delta `after` -> closed output-schema validation error before adoption.

### 5. Good/Base/Bad Cases

- Good: ExpansionSeed requests a task success-Rule mutation; shared Research/Architecture/Behavior
  commits are reused only when their exact inputs remain valid, Curriculum is revised locally,
  framework recompiles reward/goal closure and computes TaskScopeDelta.
- Base: Direct GenerateSeed traverses the same WorkDefinitions without parent-delta constraints.
- Bad: ask Expansion for one complete design transaction, retry it outside RepairLedger, accept
  `reward=99`, or let a delta carry an Agent-authored complete TaskRequirement.

### 6. Tests Required

- Assert Generate and Expand instantiate the same ordered logical WorkDefinitions and repair
  authority; only their seed/context types differ.
- Assert no Expansion `run_structured_agent` call can retry without a RepairAction authorization.
- Assert stage semantic sources have no reward/verification fields and TaskRequirement source has
  no protocol schemas or bindings.
- Assert compact architecture exposes business field/tool meaning rather than raw schema or Schema
  IR mechanics.
- Differentially assert compiled reset schema comes from the frozen world and reward values are
  canonical.
- Assert duplicate success Rules remain +1 and simultaneous success/failure returns -1 with
  succeeded=false.
- Assert provider output-schema normalization still excludes forbidden fields.
- Assert MutationIntent cannot carry `after` and framework-computed delta exactly matches parent and
  committed full Design.
- Assert state plus derived task-schema recompilation has state delta but no task delta, and seed
  space alone produces TaskDistributionDelta.
- Assert structural state unions fail at state-schema IR before curriculum/task invocations.

### 7. Wrong vs Correct

```python
# Wrong: Expansion bypasses shared stages and global repair authority.
draft = await invoke(model=ExpansionDesignDraft)

# Correct: adapt a frozen seed, run the shared graph, then compute delta in code.
context = adapt_seed(expansion_seed)
design = await generation_work_graph.run(context)
delta = compile_semantic_delta(parent, design)
```

## Agent-facing contracts must expose every structural choice

### 1. Scope / Trigger

- Applies to every `AgentOutput` passed to a real InvocationBackend.
- Especially applies when a durable/core contract owns `model_validator` cross-field rules.

### 2. Signatures

- Agent Rule output: discriminated `RuleDraft` clause/term ADTs.
- Framework compiler: `RuleDraft -> RuleClause/Rule`.
- Core Rule IR remains the Builder/Judge/release contract and retains defense-in-depth validators.

### 3. Contracts

- Provider JSON Schema must expose operator-specific fields. An Agent must never guess a constraint
  that exists only in a Pydantic post-validator.
- Existence, schema, equality, ordered and containment clauses are distinct schema branches.
- Ordered clauses explicitly declare `number`, `date` or `date-time`; framework code performs the
  finite numeric/ISO temporal comparison.
- Cross-object set closure that JSON Schema cannot express belongs to a framework compiler
  preflight producing stable code/path/message diagnostics, not a hidden Agent-output validator.
- Direct-flow Agent source contracts must have no reachable `model_validator`; enforce this with a
  static schema-reachability test.

### 4. Validation & Error Matrix

- Illegal clause field combination -> provider/schema failure before semantic repair.
- Valid Draft with inconsistent constant/arithmetic semantics -> compiler-owned typed diagnostic.
- Invalid ISO temporal runtime value -> `RuleEvaluationError`, fail closed.
- Same typed diagnostic after correction -> RepairLedger no-progress; do not increase retry count.

### 5. Tests Required

- JSON Schema rejects `exists + right`, `schema_valid` without schema, binary without right and
  ordered clauses without ordering.
- Every clause family round-trips Draft -> core Rule -> evaluator.
- Temporal comparisons execute dates/date-times and reject invalid/unbounded values.
- Static audit asserts no reachable hidden model validators for every direct Agent source root.

## Scheduler-owned research closure and exact tool accounting

### 1. Scope / Trigger

- Applies when implementing or changing `ResearchPlanLeaf`, `ResearchAcquisitionLeaf`,
  `EvidenceSynthesisLeaf`, `ResearchToolchain`, or a research `WorkDefinition`.

### 2. Signatures

- `research_plan_work_definition(scope_id, agent_wall_seconds, agent_token_limit)`
- `research_acquisition_work_definition(scope_id, dependency_coordinate, wall_seconds,
  maximum_search_calls, maximum_tool_calls)`
- `research_synthesis_work_definition(scope_id, dependency_coordinate, agent_wall_seconds,
  agent_token_limit)`
- `ResearchBundle(search_calls, fetch_calls, extract_calls)`

### 3. Contracts

- Every research WorkAttempt retains exactly one external `control.generation_context`; downstream
  parent outputs are additional causal inputs, never a replacement for this root authority.
- Plan outputs exactly one `design.research_plan`. Acquisition outputs exactly one
  `design.research_acquisition`, one passage pack, and every raw/metadata/extracted source ref.
  Synthesis consumes that full acquisition closure and outputs exactly one synthesis plus one
  `design.evidence_graph`; it cannot read mutable Designer state or run tools.
- A successful admitted document spends and observes one search/fetch/extract sequence. The
  maximum tool budget must reserve every planned search plus at least one fetch and extraction;
  with a configured fallback fetcher it also reserves the potential fallback fetch.
- Reused checkpoints record unknown historical search/fetch/extract counts rather than zero or a
  fabricated successful operation.

### 4. Validation & Error Matrix

- Missing/mismatched `GenerationContext`, request, parent record, passage pack, or source closure
  -> non-repairable framework preflight failure.
- Unknown claim/evidence reference or no supported observed claim -> field-addressed Agent
  validation failure; Scheduler alone may authorize its bounded local correction.
- Research provider outage -> real-tools infrastructure outcome; no blind query rewrite.
- Tool budget insufficient for `search + fetch + extract` -> fail before external work.

### 5. Good/Base/Bad Cases

- Good: plan -> real acquisition -> synthesis has three WorkCommits, and the synthesis attempt
  input closure contains context, record, passage pack and source refs.
- Base: an empty Search result reports one real search and zero fetch/extract calls.
- Bad: count extract as free, let synthesis reread an old source workspace, or pass only a source
  URL/summary to the model.

### 6. Tests Required

- Assert `ResearchToolchain` counts search, fetch and extract separately and never exceeds the
  declared aggregate tool budget.
- Assert Scheduler integration commits Plan/Acquisition/Synthesis in order and EvidenceGraph
  claims bind the acquired evidence ids.
- Assert checkpoint-reuse telemetry has unknown, not zero, extract metrics.
- Assert a source contract with fewer than `search_calls + 2` tool calls fails validation.

### 7. Wrong vs Correct

```python
# Wrong: aggregate only the calls that used a network socket.
usage = BudgetUsage(tool_calls=bundle.search_calls + bundle.fetch_calls)

# Correct: extraction is a real tool/process boundary and remains observable.
usage = BudgetUsage(
    tool_calls=bundle.search_calls + bundle.fetch_calls + bundle.extract_calls
)
```

## Scheduler-owned operation-budget terminalization

### 1. Scope / Trigger

- Applies when a leaf asks the framework to schedule a real model, tool, validator or assurance
  operation after its `WorkAttempt` has already begun. It is especially important for an
  otherwise-authorized local repair whose remaining global budget cannot admit another operation.

### 2. Signatures

- `WorkScheduler.dispatch_one(...)`
- `WorkControlRuntime.terminate_budget_exhausted(lock, definition, dimensions)`
- `WorkRepairLedger.exhaust_budget(entry_id)`

### 3. Contracts

- Admission is framework-owned: a leaf may request an operation but cannot turn an insufficient
  global `BudgetLedger` into a local retry, a fabricated proposal, or an unclosed running attempt.
- Scheduler catches `BudgetExceeded` only while no `OperationRun` is active. Once an external
  operation is running, its executor must settle that operation; swallowing it would hide
  unknown real cost.
- Terminalization writes a safe budget-exhaustion evidence Artifact, an error
  `ValidationReport`, a blocking `FeedbackEvaluation`, and a terminal `WorkAttempt` with status
  `budget_exhausted`; the `WorkHead` becomes `failed`.
- If the failed admission was an authorized repair, its exact `RepairAction` ledger entry closes
  as `exhausted`. This is accounting, not semantic no-progress and it never grants another turn.
- The terminal report names only valid numeric budget dimensions and never claims that the Agent,
  search provider, validator or candidate code executed.

### 4. Validation & Error Matrix

- Initial operation has sufficient lease -> normal single leaf execution and normal settlement.
- Authorized repair has no remaining `repair_attempts`/operation capacity -> deterministic
  `budget_exhausted` terminalization before the second real execution.
- `BudgetExceeded` while an `OperationRun` is active -> framework error; preserve the active run
  for its executor/recovery path rather than inventing a terminal result.
- Unknown budget dimension or a non-running head -> framework invariant failure, never a
  user-facing semantic repair.

### 5. Good/Base/Bad Cases

- Good: the first acquisition outage creates one local repair authorization; a second acquisition
  is admitted and either produces real tool telemetry or a real provider outcome.
- Base: the initial acquisition cannot reserve tools, so it terminates once with exact budget
  evidence and no external call.
- Bad: start a second WorkAttempt, let lease admission raise, then leave the head `running` with
  no active operation; a later scheduler pass must not be forced to guess whether an Agent ran.

### 6. Tests Required

- Drive a real Scheduler leaf through a failed first proposal, then deny the authorized repair at
  global budget admission; assert only the first proposal executed and the ledger is `exhausted`.
- Assert an Agent/backend error that returned no candidate output still receives its terminal
  report/evaluation instead of failing output-slot validation before routing.
- Assert terminalization rejects an active `OperationRun` and does not erase unknown execution
  cost.

### 7. Wrong vs Correct

```python
# Wrong: a repair was allowed by policy, so let the leaf retry even after global admission failed.
await leaf_executor(context)  # can leave a running WorkAttempt with no operation

# Correct: policy authorization and budget admission are separate facts.
try:
    await leaf_executor(context)
except BudgetExceeded as error:
    await runtime.terminate_budget_exhausted(lock, definition, error.dimensions)
```

## Scheduler-owned interrupted-operation recovery

### 1. Scope / Trigger

- Applies when a process exits after `OperationRun` is persisted but before proposal, validation,
  assurance, or budget settlement reaches a terminal state. It is a control-plane recovery path,
  not a second executor implementation.

### 2. Signatures

- `ProposalPolicy.replay_mode: deterministic | idempotent_with_key | queryable | non_replayable`
- `WorkControlRuntime.reconcile_abandoned_operation(lock, definition)`
- `DirectWorkRunner._reconcile_abandoned_operations(graph, runtime)`

### 3. Contracts

- Reconciliation runs only while the durable DirectJob owner lock proves there is no concurrent
  executor. It preserves the original operation id and settles token/turn/tool use as `unknown`,
  never as zero.
- Recovery writes a terminal interrupted attempt, an error validation report, and a typed feedback
  decision. A local infrastructure retry is possible only for `deterministic`,
  `idempotent_with_key`, or `queryable` policy and must still consume the existing repair/budget
  authority; `non_replayable` fails closed.
- `research_acquisition_work_definition` is `queryable`; a model/code-generation leaf remains
  `non_replayable` unless its provider supplies a real idempotency guarantee.
- A production DirectJob passes its controller `run_id` to the Scheduler as the unique telemetry
  trace id. Diagnostic harness traces cannot be attached to a production run projection.
- On recovery, close every pre-existing running span for that trace as
  `owner_process_interrupted`, retaining provider metrics, before creating the replacement root.
  Project the exact settled scope-lease actual/unknown totals into the DirectJob snapshot.
- A terminal Direct summary names only truly blocked logical coordinates, never opaque coordinate
  hashes or merely waiting descendants.

### 4. Validation & Error Matrix

- Interrupted queryable research -> interrupted evidence plus one existing local repair route.
- Interrupted non-replayable agent invocation -> terminal block with unknown usage; no blind
  prompt replay.
- Old operation lease present before new reservation -> reconcile first; never report a false
  `budget_exhausted` caused by an orphaned reservation.
- Any attempt to reconcile without the durable owner lock -> framework invariant failure.

### 5. Tests Required

- Parameterize queryable and non-replayable Operations. Assert identical unknown usage accounting
  but repair authorization only for queryable.
- Interrupt a Direct graph between scheduler persistence and executor return, restart it, and
  assert metrics, Controller snapshot, and leaf spans share exactly one run id.

## Typed infrastructure retryability

### 1. Scope / Trigger

- Applies when a real model, search, fetch, parser, build, or judge operation reaches a terminal
  execution error. A status of `error` alone is never retry authority.

### 2. Signatures

- `LeafExecutionFailure(..., retryable: bool = True)`
- `ValidationReport.infrastructure_retryable -> bool`
- `WorkControlRuntime._authorize_next_or_fail(...)`

### 3. Contracts

- A leaf emits one safe error code, causal operation path, expected remedy category, and explicit
  retryability. It never opens a second attempt itself.
- `ValidationReport.infrastructure_retryable` is true only for an `error` report whose blocker
  diagnostics are explicitly retryable. Empty/opaque error reports fail closed.
- Scheduler still checks the single `RepairPolicy` and global budget before creating an
  `infrastructure_retry` RepairAction. `retryable=True` is necessary but never sufficient.
- `ResearchAcquisition` marks an all-search `upstream_unavailable` result non-retryable: repeating
  the same provider and full query envelope is not a causal repair. Process interruption remains
  eligible only through replay-mode recovery (`queryable`, `deterministic`, or
  `idempotent_with_key`).

### 4. Validation & Error Matrix

- Typed transient/replay-safe failure plus retry budget -> one Scheduler-authorized retry.
- `retryable=False` provider/configuration/permission boundary -> terminal blocking evaluation;
  no RepairAction and no second external call.
- Empty/generic error report -> terminal block; framework must add a typed diagnostic before any
  retry policy can apply.
- Interrupted `queryable` operation -> recovery report with an explicit retryable issue and
  conservative unknown usage; `non_replayable` interruption remains terminal.

### 5. Good/Base/Bad Cases

- Good: an interrupted idempotent search is reconciled, charged, and retried once under its
  existing repair policy.
- Base: one unavailable search provider creates safe failure evidence and leaves no active lease.
- Bad: convert every provider `error` to `infrastructure_retry`, consume a fresh full search budget,
  and then report `budget_exhausted` without gaining information.

### 6. Tests Required

- Give a leaf enough global budget and `maximum_infrastructure_retries=1`, raise
  `LeafExecutionFailure(retryable=False)`, and assert exactly one proposal invocation, no
  RepairAction, and a terminal typed report.
- Parameterize interrupted queryable/non-replayable operations; assert only the former exposes an
  explicit retryable recovery diagnostic.

### 7. Wrong vs Correct

```python
# Wrong: the status discards causal retry information.
if report.status == "error":
    authorize_infrastructure_retry()

# Correct: code uses the leaf's typed, safe classification plus global policy.
if report.infrastructure_retryable and policy.permits_infrastructure_retry:
    authorize_infrastructure_retry()
```

## Actionable semantic diagnostics and live Scheduler observation

### 1. Scope / Trigger

- Applies to every shape-valid structured Agent proposal rejected by a semantic compiler, and to
  every `run inspect` while a Scheduler-owned Direct run is active.
- Introduced after a real hotel run reached `shared_tool_semantics`: the validator knew the exact
  violated shared-tool constraints, but the leaf conversion replaced them with a generic contract
  message.  The one authorized correction therefore had no usable cause.

### 2. Contracts

- `StructuredSemanticIssue` carries a closed code, exact location, safe `violated_condition` and
  safe `expected_category`.  `invoke_structured_once` must preserve all four fields in the
  `LeafValidationFailure`, then in `ValidationReport` and the bounded RepairAction packet.
- A Scheduler-authorized semantic correction must compile its immutable
  `RepairAction -> FeedbackEvaluation -> ValidationReport` chain into an `AgentCorrectionBrief`
  containing only blocker `(code, path, violated_condition, expected_category)` facts. The new
  one-shot invocation appends that brief to the original bounded prompt and returns a complete
  replacement output. It must never project repair policy, budget, action id, mutation authority,
  graph coordinate, invalidation, owner, or release state into Agent-facing text.
- Known semantic diagnostics may never be collapsed to generic text before an Agent correction.
  If the condition cannot be safely disclosed, it is a framework/output-contract failure and does
  not consume a semantic correction.
- No-progress equality uses the safe issue tuple `(code, path, violated_condition,
  expected_category)`, not a coarse `value_error` or category label.
- `DurableLeaseBudgetCoordinator` is the live Direct budget authority.  `run inspect` sums its
  settled leases for observed/unknown/conservative usage and exposes active lease reservation.
  `JobRunSnapshot` remains the terminal summary, not a competing mutable control plane.
- A Scheduler `WorkAttempt` span must use the active Direct root span as `parent_span_id` when
  both trace ids agree.  A mismatched active trace is a framework error; missing provider usage is
  `unknown`, never zero.
- Agent dispatch identity plus resolved provider/model/profile/schema are known before the SDK
  call.  A timeout or pre-envelope transport exception must carry that provenance through the
  failed ProposalExecution, settle the complete unknown reservation, and reach one terminal
  Validation/Evaluation.  It must never strand the non-replayable OperationRun because a terminal
  provider envelope did not arrive.

### 3. Required Tests

- Shape-valid semantic failure retains its exact safe condition and expected category through the
  one-shot boundary.
- A live reader with a stale zero Direct snapshot but one settled plus one active scope lease
  reports ledger usage and active reservation.
- A Scheduler deterministic leaf started below an activated Direct root has that root as its
  telemetry parent.
- A timed-out one-shot Agent turn preserves its Scheduler dispatch provenance for terminal
  settlement.
- A real Scheduler correction dispatch receives no brief on attempt one and the exact safe
  blocker brief on attempt two; the repair ledger resolves only after that second proposal commits.
- A completed Agent turn followed by compiler/Artifact materialization failure settles the same
  Proposal OperationRun with its known actual/unknown usage and non-retryable framework evidence.
  It must not leave a running WorkHead or spend a second Agent turn. Artifact dependency closures
  are set-like: deduplicate `ArtifactRef`s before every immutable write.

## Repair-lineage telemetry is a read-only projection

### 1. Scope / Trigger

- Applies when `WorkControlRuntime` starts an initial `WorkAttempt`, a Scheduler-authorized repair,
  a stale supersession, or a physical recovery; it also applies to the child real-Agent invocation.
- Use this rule after any trace appears to show a repeated proposal without a repair, before changing
  Scheduler, `WorkRepairLedger`, budget, invalidation, or release code.

### 2. Signatures

- `WorkControlRuntime._start_attempt_span(..., repair_action, repair_action_ref, repair_mode,
  process_recovery_ordinal) -> (trace_id, span_id)`
- Work span fields: `attempt`, `repair_depth`; attributes: `repair_mode`,
  `repair_action_revision`, `repair_decision`, `repair_attempt_ordinal`,
  `process_recovery_ordinal`.
- `InvocationRequest.metadata`: `repair_mode`, `repair_attempt_charge`.

### 3. Contracts

- The span may read a durable `RepairAction` only to project it. `repair_depth` is that action's
  semantic `repair_attempt_ordinal`, not the physical WorkAttempt ordinal.
- Initial and stale-supersession attempts have depth zero. An authorized repair reports its durable
  decision; a physical recovery retains that semantic depth and reports `process_recovery`.
- Invocation metadata is derived from immutable `WorkAttempt` state and is observational only. No
  telemetry field may authorize a repair, reserve/settle budget, route invalidation, or affect
  readiness/release.

### 4. Validation & Error Matrix

- Action without its exact `ArtifactRef`, or vice versa -> `WorkRuntimeError`; do not write a
  partial causal projection.
- Negative recovery ordinal -> `WorkRuntimeError`.
- Missing provider metrics -> unknown usage; never infer repair authority from a child span alone.
- A stopped worker with active operations -> recovery reconciliation; telemetry must not free or
  replay its lease.

### 5. Good / Base / Bad Cases

- Good: a local correction's second physical attempt has depth one and the exact action revision;
  its child invocation says `authorized_repair`.
- Base: initial proposal is depth zero and `initial`.
- Bad: default every retry span to `repair_depth=0`/`initial`, then treat the observation as a
  Scheduler bypass and rewrite repair authority from one trace.

### 6. Tests Required

- Drive initial proposal -> authorized correction -> interrupted physical recovery; assert span
  modes, semantic depth, exact action revision, and recovery ordinal.
- Parameterize initial/authorized-repair/process-recovery `WorkAttempt`s through
  `invoke_structured_once`; assert child metadata but no extra invocation/retry.
- Compare at least two historical live traces before changing any execution-control rule.

### 7. Wrong vs Correct

```python
# Wrong: telemetry defaults create a false control-plane diagnosis.
telemetry.start_span(attempt=attempt.ordinal)

# Correct: the durable action is projected, never interpreted as authority.
telemetry.start_span(
    attempt=attempt.ordinal,
    repair_depth=repair_action.repair_attempt_ordinal,
    attributes={"repair_mode": repair_action.decision},
)
```

## Causal dependencies versus input disclosure

### 1. Scope / Trigger

- Applies to every Scheduler-dispatched Direct/Evolve leaf. It was introduced after a real hotel
  run completed Research through WorldArchitecture and then failed before the first Design Agent:
  `shared_tool_semantics` depended on EvidenceSynthesis but did not need its full synthesis
  Artifact.

### 2. Signatures

- `WorkScheduler.resolve_inputs(coordinate: WorkCoordinate) -> ResolvedWorkInputs`
- `WorkScheduler.snapshot() -> WorkScheduleSnapshot`
- `WorkScheduler._all_input_refs(definition, parent_commits) -> tuple[ArtifactRef, ...]`

### 3. Contracts

- `WorkDefinition.dependency_coordinates` are causal edges only: parent changes invalidate the
  child and parent WorkCommit refs remain in scheduler lineage.
- `WorkDefinition.input_slots` are a least-privilege disclosure contract: only parent
  `consumer_refs` whose type is explicitly declared enter `WorkExecutionContext.parent_output_refs`
  and the WorkAttempt input fingerprint.
- Direct/Evolve graph compilation uses `strict_input_contracts=True`: every dependent leaf must
  declare a non-empty input contract, and each non-external slot must have a sufficient typed output
  from a direct dependency. This runs before any provider, search, Builder, or Judge call.
- Generic diagnostic graphs may omit slots while being assembled; they are never a production
  success path. An empty-slot diagnostic consumer retains full parent outputs only for framework
  harness compatibility, never for a strict Direct/Evolve graph.
- Package is an explicit closure consumer. It must receive Design, WorldSpec, Candidate, manifest,
  build record, implementation lineage, Verifier IR, Integration report, Judge report and telemetry
  summary via declared slots; it must not discover these by reading arbitrary active WorkHeads.

### 4. Validation & Error Matrix

- Direct dependency lacks a producer for a required non-external typed slot -> graph freeze error
  before an external operation.
- Parent commit is absent/stale -> child is `waiting`/`stale`; it cannot receive an inferred
  artifact through a head lookup.
- Parent has both allowed and sealed outputs -> resolve, dispatch, and snapshot reuse retain only
  the allowed output; every parent commit ref remains in lineage.
- Snapshot recomputes a different closure from dispatch -> framework defect. Both paths must call
  the same input-closure helper; do not repair it by widening the child's declared inputs.

### 5. Good / Base / Bad Cases

- Good: a Design leaf causally depends on EvidenceSynthesis yet consumes only the declared
  architecture/coupling artifacts; recovery reuses its exact commit.
- Base: a root-only leaf consumes only `GenerationContext` and has no parent commit.
- Bad: dispatch filters sealed output but snapshot fingerprints every parent output, so recovery
  marks a correct least-privilege commit stale and Package/Registry never become ready.

### 6. Tests Required

- A strict graph declaring an input type with no direct producer must reject at graph freeze.
- A committed parent exposing one allowed and one sealed artifact must resolve only the allowed
  ref for a child that declares the allowed type; its parent WorkCommit lineage remains present.
- A real Direct graph reconstructed from committed bootstrap outputs must pass strict closure before
  the first downstream Agent dispatch.
- Assert the same least-privilege closure makes the downstream work `ready` in `snapshot()` after
  it was already accepted by `resolve_inputs()`.

### 7. Wrong vs Correct

```python
# Wrong: causality accidentally becomes blanket data access.
parent_output_refs.extend(parent_commit.consumer_refs)

# Correct: causality and disclosure are separate, typed relations.
parent_commit_refs.append(parent_commit_ref)
parent_output_refs.extend(
    ref for ref in parent_commit.consumer_refs
    if ref.artifact_type in declared_input_types
)
```

## Shared-tool semantic transaction completion

### 1. Scope / Trigger

- Applies to `SharedToolSemanticsLeaf` whenever a frozen `ToolCouplingGroupPlan` has more than
  one tool. A real hotel run demonstrated that an otherwise semantic proposal can repeatedly omit
  one member from domain coverage and exhaust its bounded local repair budget.

### 2. Signatures

- `_shared_prompt(inputs, architecture, coupling_group, evidence) -> str`
- `ToolCouplingGroupPlan.ordered_tool_ids`
- `SharedToolSemanticsSourceDraft.{atomicity_domains, concurrency_domains,
  idempotency_domains, error_policies}`

### 3. Contracts

- The frozen ordered ids are the only legal member vocabulary. Each of the first three domain
  collections partitions that exact set once; error policies cover every member at least once.
- The Agent may choose semantic grouping. When evidence does not establish a finer distinction,
  one domain over the complete set is an explicitly permitted conservative construction.
- The prompt is a construction aid only. `compile_shared_tool_semantics` remains the sole
  validator; it may reject an implausible or inconsistent semantic policy and its safe issue set
  remains the only input to a bounded correction.

### 4. Validation & Error Matrix

- Omitted or duplicated domain member -> `shared_contract_partition`, local semantic correction
  only when the safe report is actionable.
- Error policies omit a frozen member -> `shared_error_coverage`, same bounded route.
- A resolved partition failure reappears after a different failure -> A→B→A oscillation; stop
  rather than add an unbounded third semantic repair.

### 5. Good / Base / Bad Cases

- Good: one complete domain and one complete error policy cover every frozen tool; compiler then
  validates the selected atomicity/concurrency/idempotency semantics.
- Base: evidence justifies several domains, but every frozen id still appears exactly once in each
  domain class.
- Bad: encode a hotel-specific output, auto-fill the Agent draft in framework code, or weaken the
  compiler because the model omitted a member.

### 6. Tests Required

- Assert the rendered prompt names the exact-partition, conservative full-domain, and error
  coverage constraints and includes the frozen ids.
- Preserve the existing compiler regression for partition diagnostics and the Scheduler regression
  for safe correction-brief disclosure/no-progress stopping.

### 7. Wrong vs Correct

```python
# Wrong: hide a repeated-model formatting failure by accepting partial coverage.
if missing_members:
    accept_partial_shared_contract()

# Correct: guide construction, then keep the deterministic boundary authoritative.
prompt_requires_complete_frozen_coverage()
compile_shared_tool_semantics(source, group=group, evidence_graph=evidence)
```

## Frozen-graph executor completeness

### 1. Scope / Trigger

- Applies to each Direct/Evolve epoch after topology freeze and before its first external operation.
  A real hotel run committed shared tool semantics, then revealed a ready physical tool batch with
  no registered leaf because its semantic stage and artifact slot intentionally had different names.

### 2. Signatures

- `DirectWorkRunner._design_executors(...) -> dict[work_id, WorkExecutor]`
- `WorkScheduler.run_until_stalled(executors=...) -> tuple[WorkDispatchResult, ...]`
- `WorkExecutorMissingError(coordinates: tuple[WorkCoordinate, ...])`

### 3. Contracts

- A leaf binding represents the physical executor contract; route it by the stable `artifact_slot`
  when a semantic `stage` names a broader lifecycle position.
- A `ready` or `repair_ready` Work without a binding is a typed framework integration failure, not
  semantic feedback, not an LLM routing question, and not a retryable empty scheduler result.
- The error may disclose only safe coordinate fields. Controller maps it to
  `scheduler_executor_missing`; it must not create RepairAction/AgentCorrectionBrief or charge a
  new Agent envelope.

### 4. Validation & Error Matrix

- `world_behavior` plus `tool_semantics_batch` slot -> ToolSemanticsBatch leaf is registered.
- Ready/repair-ready definition absent from executor mapping -> fail closed with all exact safe
  coordinates.
- Waiting descendant with a missing parent -> remain waiting; it is not an executor-missing error.
- Terminal semantic `blocked` work -> keep its ValidationReport/FeedbackEvaluation route; do not
  conflate it with executor wiring.

### 5. Good / Base / Bad Cases

- Good: SharedToolSemantics commits, each ready ToolSemanticsBatch has a leaf, and the next
  Scheduler wave dispatches it.
- Base: an epoch has no ready dynamic work because it is waiting for an uncommitted causal parent.
- Bad: return an empty scheduler result, later project `unknown scheduler coordinate`, or hand the
  missing framework binding to an Agent for repair.

### 6. Tests Required

- A real scheduler graph with a ready definition and `{}` executors raises
  `WorkExecutorMissingError` containing that coordinate.
- A physical tool batch whose stage is `world_behavior` and slot is `tool_semantics_batch` appears
  in Direct's executor mapping.

### 7. Wrong vs Correct

```python
# Wrong: a semantic lifecycle name is mistaken for the physical executor kind.
if definition.coordinate.stage == "tool_semantics_batch":
    bind_tool_batch_leaf()

# Correct: the frozen output slot is the physical leaf contract.
if definition.coordinate.artifact_slot == "tool_semantics_batch":
    bind_tool_batch_leaf()
```

## Explicit monetary admission and unknown-price telemetry

### 1. Scope / Trigger

- Applies when an Invocation backend supplies no trustworthy price, which is normal for a
  compatible endpoint. A live Direct run reached two parallel tool-batch leaves, but an old leaf
  default silently reserved one monetary unit for each and rejected both before provider dispatch.

### 2. Contracts

- `OperationBudget.monetary_cost == 0` means no monetary admission policy was configured. It does
  not mean a provider measured a zero price.
- A leaf may reserve a nonzero monetary amount only when its framework caller explicitly supplies
  a measured-price envelope. Tests that synthesize price must also supply that envelope.
- `InvocationUsage.monetary_cost: float | None` is optional provider evidence. If absent,
  telemetry writes `invocation.monetary_cost` with `value=null` and `provenance=unknown`.
- Token, turn, wall-time, concurrency, tool, and bounded-repair envelopes remain hard even when
  monetary admission is absent. Never use price ambiguity to grant an unlimited loop.

### 3. Error Matrix

- Unpriced compatible provider + default tool batch -> dispatch is admissible; cost metric is
  unknown, not zero.
- Explicit measured-price envelope + proposal over limit -> deterministic budget exhaustion before
  another external call.
- Invalid negative/nonfinite provider price -> contract error; never store or aggregate it.

### 4. Tests Required

- Assert the default ToolSemanticsBatch monetary reservation is zero.
- Assert an unpriced Invocation produces a nullable unknown cost metric.
- Preserve the explicit-envelope settlement test that rejects an over-spend.

## ToolSemantics proposal diagnostics must never cross as raw `ValueError`

### 1. Scope / Trigger

- Applies to `ToolConditionsDraft`, `ToolStateTransitionDraft`, `ToolErrorsDraft`,
  `ToolBehaviorDraft`, and `ToolSemanticsDraft` after their source shape has compiled.
- A live hotel run reached parallel physical tool batches and exposed raw cross-field validation
  errors as non-actionable `framework_diagnostic_incomplete` roots.

### 2. Contracts

- A failure caused by Agent-authored tool semantics must be a `StructuredSemanticIssue` with a
  stable code, exact source-facing path, safe `violated_condition`, and safe
  `expected_category`.
- `_prefixed_validation_issues` preserves a StructuredSemanticIssue's condition/category; it may
  only use generic fallback text when the issue deliberately omitted those fields.
- Compiler-owned frozen-input corruption remains a non-retryable framework diagnostic. Do not
  relabel it as candidate repair just to obtain another Agent turn.
- Behavior-level validation owns only cross-component conditions. It must not duplicate every
  condition/transition/error Rule failure already reported by the corresponding source section.

### 3. Tests Required

- Start with a compiled non-fixture world, make a tool Rule use the wrong frozen namespace and an
  unknown evidence id, then assert both exact paths remain actionable after batch prefixing.
- Assert neither issue is `framework_diagnostic_incomplete` and that their condition/category
  reach the routed `SafeValidationIssue` unchanged.

## Architecture Agent-output diagnostics must use an explicit safe error allowlist

### 1. Scope / Trigger

- Applies to every `WorldArchitectureSourceDraft` nested `AgentOutput` validator and its
  `invoke_structured_once -> pydantic_validation_diagnostic -> ValidationReport` boundary.
- A real `gpt-5.3-codex-spark` hotel run returned a shape-level Architecture proposal with
  60 field-addressable Pydantic `value_error` items. The former generic projection correctly
  blocked blind repair, but hid the safe contracts needed for one causal replacement.

### 2. Signatures

- Agent-output validators raise an allowlisted `PydanticCustomError(code, safe_message)` for a
  proposal-owned contract.
- `pydantic_validation_diagnostic(...) -> ValidationDiagnostic` maps the same code to a stable
  `schema_<code>`, safe `violated_condition`, and `expected_category`.
- Unknown Pydantic `value_error` and `assertion_error` remain
  `framework_diagnostic_incomplete(retryable=False)`.

### 3. Contracts

- `CompactFieldSemanticDraft` must expose explicit safe codes for string-only
  format/enumeration, numeric-only bounds, bound ordering, and duplicate enumerations.
- `StateFieldSourceDraft` must expose an explicit safe code for the lifecycle contract:
  mutable role, string value type, and non-empty enum values.
- The code, path, condition, and expected category may enter the bounded
  `AgentCorrectionBrief`; rejected values, Pydantic message context, RepairAction fields,
  budgets, coordinates, and release state may not.

### 4. Validation & Error Matrix

- Allowlisted Architecture source-model condition -> actionable `schema_<code>` at the nested
  source path; at most the existing Scheduler-authorized local correction may consume it.
- Unknown raw validator error -> non-actionable framework diagnostic; no RepairAction.
- Shape-valid Architecture compiler failure -> use an explicit `StructuredValidationError` only
  when the compiler can provide a safe source-facing condition; otherwise remain a framework
  blocker.

### 5. Good / Base / Bad Cases

- Good: a numeric field with `string_format=email` returns
  `schema_compact_field_string_constraints` and a safe correction condition.
- Base: a valid string lifecycle field with enum values produces no validation issue.
- Bad: map every Pydantic `value_error` to an actionable retry, or include raw exception text in
  the prompt/report.

### 6. Tests Required

- Exercise `invoke_structured_once` through an Architecture-field root for string constraint and
  lifecycle violations; assert exactly one invocation and the code/path/condition/category.
- Exercise an unknown raw `ValueError`; assert `framework_diagnostic_incomplete` remains
  non-retryable.
- Keep a compiler-boundary matrix separate from source-model validation. A historical
  ToolSemantics `ValueError` symptom is not proof that Architecture has the same source-level
  cause.

### 7. Wrong vs Correct

```python
# Wrong: safe location, but no safe causal condition; the model must guess.
raise ValueError("minimum cannot exceed maximum")

# Correct: closed code/message become a safe ValidationReport issue.
raise PydanticCustomError(
    "compact_field_bounds_order",
    "minimum cannot exceed maximum",
)
```

## ToolSemantics mechanical identities and bounded correction projection

### 1. Scope / Trigger

- Applies to every production `ToolSemanticsBatchSourceDraft` and its one Scheduler-authorized
  correction.
- A live hotel run produced 96--187 safe blockers per batch. Most were repeated Rule namespace or
  schema-selector failures, so forwarding every exact path made the correction prompt larger while
  adding no causal decision value.

### 2. Contracts

- The framework derives every tool Rule id from the frozen `tool_id`, semantic section and ordinal:
  `rule:<tool_id>:<section>:<ordinal>`. An Agent may omit `rule_id`; any submitted value is replaced
  before the source artifact and core Rule IR are committed.
- `PermissionRuleSourceDraft.required_scopes_by_actor` is the non-empty, Agent-authored permission
  actor map. Its keys are the complete allowed actor set; the source contract and compact protocol
  must not also ask the Agent for `allowed_actors`. The compiler derives a canonical core
  `PermissionRule.allowed_actors` tuple from those keys, while the core Runtime/Judge contract keeps
  its defense-in-depth set-closure validation. No actor or scope may be synthesized by framework
  code.
- The Agent still owns only business Rule meaning, references, evidence and typed relations. It
  never owns namespaces, cross-artifact identity or control-plane identifiers.
- `ValidationReport` retains all exact `ValidationIssue` instances. `AgentCorrectionBrief` is a
  prompt-only, data-only projection grouped by `(code, violated_condition, expected_category)`;
  each cluster has occurrence count, affected normalized path patterns and at most three exact
  representative paths.
- The projection must never include RepairAction policy, budget, coordinate, mutation authority,
  invalidation, owner or release data. A cluster means every matching occurrence in the complete
  replacement, not merely the displayed sample paths.

### 3. Tests Required

- Compile a ToolConditions source whose submitted Rule id has an arbitrary value; assert the
  compiled Rule has the framework-derived namespace and ordinal.
- Assert the source model and versioned compact schema reject a repeated `allowed_actors` field and
  an empty scope map; compile a valid map and assert the core allowed-actor projection is derived
  exactly from its keys.
- Construct sixteen repeated pointer diagnostics; assert one correction cluster preserves count,
  normalized scope and three representatives while the full issue tuple remains intact.

## Frozen Tool Rule bindings, not Agent-authored state addressing

### 1. Scope / Trigger

- Applies only to production `ToolSemanticsBatchSourceDraft`, after `WorldSkeleton` and its exact
  `ToolSurface` schemas are frozen.
- A real hotel run showed composed state collections use local JSON Schema `$ref` entries. An
  inline-only RuleContextCatalog therefore disclosed no item fields/primary keys and expanded one
  mechanical selector mistake into 132--148 field diagnostics.

### 2. Contracts

- Rule context resolution must dereference only finite local `#` / RFC 6901 references. External,
  missing, or cyclic refs are framework-invalid context and never trigger semantic Agent repair.
- The Tool Agent may author `bound_reference(binding_id)` or `bound_lookup_by_key(binding_id, key)`.
  It chooses business relations and one frozen binding selector; in a compact provider prompt that
  selector may be a deterministic opaque alias which materializes to exactly one immutable binding.
  It does not author raw source, RFC 6901 pointer, collection pointer, primary-key field, selected
  item pointer, or value type.
- A lookup binding is indivisible: framework derives collection + source + one primary key + one
  selected item field/value type together. The Agent may provide only a constant or another bound
  reference as the lookup key.
- A reference-key lookup is one further composite frozen binding, not two independently selected
  aliases. Framework code derives a pair only when the lookup primary-key field name equals the
  direct reference's terminal RFC 6901 field name and both frozen value types are identical. One
  compact alias selects the entire lookup/reference pair; the Tool wire has no `key_binding_id`.
  This is a mechanical schema relation, not an inferred business equivalence. Constant-key
  lookups continue to select one frozen lookup plus one explicitly typed literal.
- The deterministic materializer must expand bindings before the existing executable core Rule IR
  compiler. Runtime, Judge and Builder continue to consume only `RuleValueRef` /
  `RuleLookupByKey`; the bound forms never enter executable artifacts.
- Any raw or unknown Tool binding is a stable, local, actionable compiler failure. It must not be
  accepted as a compatibility form, silently guessed, or converted into a global retry.
- A compact alias is a prompt/input projection, never an executable ABI: it must resolve to one
  member of the exact frozen catalog before Rule compilation. Unknown aliases, aliases from another
  tool/context, scalar shortcuts and raw bindings fail at the same materialization boundary.
- Do not apply this rule wholesale to WorldRules/Curriculum: task-local goal semantics are not
  necessarily frozen at ToolSemantics time.

### 3. Tests Required

- Use a composed root schema whose collection item is `{"$ref":"#/$defs/entity"}`; catalog prompt
  projection must disclose the resolved collection, primary key and item fields, and a valid lookup
  must close.
- Materialize a bound args reference plus a bound post-state collection lookup and assert the exact
  raw Designer Rule source is framework-derived.
- Assert prompt aliases are deterministic, omit long immutable binding digests, and each alias
  reconstructs exactly one original reference or lookup binding; the output compiler must still
  reject an unknown alias.
- Assert split lookup/reference aliases cannot inhabit the Tool wire; a composite alias expands to
  the existing executable `lookup_by_key`, and no pair with a different terminal field or value
  type enters the frozen catalog.
- A raw `/bookings/status` Tool reference must fail with `tool_rule_binding_required` before core
  Rule compilation.

## Recursive structured-output transport compatibility

### 1. Scope / Trigger

- Applies when a real configured provider accepts the shallow `json_envelope` schema but rejects a
  prompt carrying a recursive logical Pydantic schema, especially `RuleDraft`-bearing output.
- This is established only by a real profile-matched probe with safe status/token observations;
  a unit double cannot classify a provider limit.

### 2. Contracts

- Provider request transport may constrain only the shallow `{"artifact_json": string}` schema.
  Decode either its JSON-string document or a compatibility gateway's object-valued
  `artifact_json` document, then require the exact same original Pydantic source model, frozen
  RuleContext materialization and deterministic compiler. Scalars, arrays and malformed JSON are
  transport-invalid. Do not create a permissive transport success path.
- A rule-bearing leaf may substitute a versioned compact **Agent-facing protocol** for the generated
  recursive JSON Schema text only after a real rejection. The protocol describes a strict existing
  source-model subset; it does not introduce a DSL, raw expression text, raw pointers, unsupported
  rule variants, fixture data or a special environment branch.
- Every compact Rule clause must state its exact operator-owned field closure. In particular,
  `equal`/`not_equal`/`contains`/`not_contains` must omit `ordering`, while comparison operators
  require it. The environment-engineer skill may repeat this exact mechanical check, but no prompt
  wording may relax the closed source schema.
- A compact `bound_lookup_by_key.key` is likewise a closed sub-ADT: only a constant or frozen
  `bound_reference` alias is permitted. Arithmetic, nested lookup, raw reference/pointer, bare
  identifier, and scalar shortcut forms must remain rejected by the unchanged source model.
- The compact protocol must explicitly state every required output root and permitted bound term
  form. Prompt text never authorizes a retry, changes release policy, or overrides local validation.
- A small-schema control completion does not prove Design, Builder, Judge or Registry success.

### 3. Tests Required

- Exact-envelope JSON-string and object-valued decode, plus Pydantic/model/compiler acceptance of
  a compact-protocol-shaped document; scalar/array payloads remain rejected.
- Rejection of missing roots, raw Tool references/selectors and unsupported compact forms at the
  same existing local validation boundary.
- Construct an equality clause carrying `ordering`; assert the compact schema and the unchanged
  Pydantic source model both reject it before compiler acceptance.
- Construct a lookup whose `key` carries arithmetic; assert the compact schema and source model
  reject it before frozen binding materialization.
- A real profile-matched transport probe that stores only safe result category and measured usage;
  the subsequent full Direct E2E is still mandatory.

### 4. Validation & Error Matrix

- Provider rejects the outer request before a result -> safe backend terminal such as
  `turn_failed_provider_rejected`; preserve measured/unknown usage and do not classify a model
  proposal.
- Provider completes the shallow envelope but the decoded document raises a typed
  `schema_*`/semantic compiler issue -> `LeafValidationFailure` with safe code and path. This is
  a failed compact-protocol probe, not transport success.
- Provider completes, the unchanged source model parses, frozen bindings materialize, and the
  deterministic compiler accepts -> compact-protocol probe passes. It is still non-release
  evidence and does not establish Design, Builder, Judge, Package, or Registry success.
- Repeated safe shape failures for one compact-protocol revision -> stop that revision before a
  full Direct request. Any new protocol revision or explicit profile decision requires a new
  bad-case admission and a bounded probe; never loop by changing only prose or retries.

### 5. Good / Base / Bad Cases

- Good: a real configured Engineer profile returns one compact ToolSemantics document whose exact
  inner JSON passes `ToolSemanticsBatchSourceDraft`, `RuleContextCatalog` materialization, and
  `compile_tool_semantics_batch`.
- Base: a shallow-envelope small-schema control completes. It proves the endpoint can run an
  InvocationBackend turn, not that a recursive Rule-bearing proposal is compatible.
- Bad: provider output reaches Pydantic but supplies a scalar where a frozen actor array is
  required, an unsupported transaction literal, a non-string concurrency description, or no valid
  tool member. Do not expose the rejected payload, coerce it, retry it as an infrastructure error,
  or start a full Direct campaign from this result.

### 6. Tests Required

- The one-shot transport test must prove that an explicit compact protocol replaces generated
  recursive-schema prompt text while the original output model still parses the returned object.
- A ToolSemantics regression must construct a compact-protocol-shaped JSON document, pass it
  through JSON-mode Pydantic parsing and the real batch compiler, then prove a raw reference fails
  as `tool_rule_binding_required` at the existing materializer boundary.
- A live probe records only safe terminal category, safe issue code/path, profile digest, model,
  and observed/unknown usage. It must neither persist raw output nor write a releasable Artifact.

### 7. Wrong vs Correct

```python
# Wrong: a gateway completed, so skip the typed ToolSemantics boundary.
if invocation.succeeded:
    mark_compact_transport_compatible()

# Correct: completion must traverse the existing inner acceptance chain.
source = ToolSemanticsBatchSourceDraft.model_validate_json(inner_json)
compile_tool_semantics_batch(source, rule_contexts_by_tool=frozen_catalogs)
mark_probe_passed_only_after_compilation()
```

## Terminal provider rejection is not infrastructure retry authority

### 1. Scope / Trigger

- Applies when one real Agent `InvocationResult` is unsuccessful with the safe terminal code
  `turn_failed_provider_rejected`.
- A completed provider stream ending in this category is evidence that the active request contract
  is incompatible. It is not evidence of a transient network interruption.

### 2. Signatures

- `invoke_structured_once(...) -> LeafExecutionFailure` maps the terminal code to
  `agent_backend_turn_failed_provider_rejected` with `retryable=False`.
- Existing Scheduler evaluation consumes that flag through `ValidationReport.infrastructure_retryable`;
  a false value must terminate the WorkHead without a `RepairAction`.

### 3. Contracts

- The failure retains only the safe code, bounded category, real invocation provenance, and
  observed/unknown budget usage. It never persists provider text, request payload, endpoint, or
  credentials.
- A new call requires a causal external change such as a measured input/protocol revision or an
  explicit profile/endpoint decision. It must use a fresh request or approved new attempt, never a
  resume of the rejected request.
- Do not broaden this rule to timeouts, rate limits, or explicit provider-unavailable categories
  without their own evidence and retry contract.

### 4. Validation & Error Matrix

- `turn_failed_provider_rejected` -> non-retryable terminal error; no infrastructure retry.
- local Pydantic/compiler failure with safe fields -> normal Scheduler-owned semantic correction
  only when its existing repair policy authorizes one.
- timeout/rate-limit/provider-unavailable -> retain their configured infrastructure policy; do not
  infer their behavior from a compatibility rejection.

### 5. Good / Base / Bad Cases

- Good: a fake backend marks the rejection retryable, but the one-shot boundary still returns a
  non-retryable failure and the Scheduler cannot redispatch it.
- Base: a provider timeout remains classified by its own retry policy.
- Bad: propagate a generic backend `retryable=True` flag for a known provider rejection and spend
  a second identical ToolSemantics call.

### 6. Tests Required

- Return `InvocationStatus.FAILED` with `turn_failed_provider_rejected` and an intentionally true
  backend retry flag; assert one-shot emits the safe prefixed code with `retryable is False`.
- Run Scheduler/Repair recovery tests with an exact `repair_scope_id`; assert scope filtering does
  not discard an active same-scope RepairLedger entry after a process restart.

### 7. Wrong vs Correct

```python
# Wrong: generic worker retryability spends an identical call after a contract rejection.
retryable = result.error.retryable

# Correct: the fixed terminal taxonomy overrides that generic flag.
retryable = safe_code not in {"turn_failed_provider_rejected"}
```

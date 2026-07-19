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
- The full pre-Build Direct proposal graph has at most eight base turns: two research,
  architecture, an optional multi-batch shared contract, one or two tool batches, world rules and
  curriculum. A global WorkGraph budget currently reserves at most two semantic corrections, so
  the hard envelope is ten turns. No component-local counter may grant work beyond that envelope;
  a second correction for one logical Artifact requires code-proven strict progress.

### 4. Validation & Error Matrix

- Unknown business path in Agent RuleDraft -> local WorldRules correction.
- Invalid framework-compiled path/id/schema -> framework failure, no semantic correction.
- Transaction projection above 192 KiB or total turn bound -> reject before invocation.
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

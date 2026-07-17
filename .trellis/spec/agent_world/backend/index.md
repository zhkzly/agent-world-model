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

- Applies whenever Direct Generation fails after research has produced a typed `EvidenceGraph`, or
  after the evidence-backed `WorldSkeleton` has been committed.

### 2. Signatures

- `DesignPhaseCheckpoint.phase: Literal["evidence_graph", "world_skeleton"]`
- `EnvironmentDesigner.adopt_latest_phase_checkpoint(...) -> ArtifactRef`
- `EnvironmentDesigner.resume_from_phase_checkpoint(...) -> DesignBundle`

### 3. Contracts

- A checkpoint binds exact job, request, input artifact revisions and `designer-v4` ABI by hash.
- Resume selects the most advanced unique valid phase for the same immutable job/request.
- Evidence resume performs no Researcher, search, fetch or extract call and reports zero new
  research usage; it recompiles World Boundary and downstream world nodes.
- Cross-request evidence reuse requires a separate explicit freshness/adoption policy and is not
  inferred from similar natural-language text.

### 4. Validation & Error Matrix

- Exact unique WorldSkeleton checkpoint -> resume Designer tail.
- No WorldSkeleton but exact unique EvidenceGraph -> adopt typed evidence checkpoint and resume
  before World Boundary.
- Multiple candidate revisions -> `checkpoint.ambiguous`.
- Missing, dependency-unbound, ABI-mismatched or semantically invalid artifact -> fail closed.

### 5. Good/Base/Bad Cases

- Good: one state-schema failure resumes from EvidenceGraph without a new research directory.
- Base: initial generation researches once and commits the EvidenceGraph checkpoint immediately.
- Bad: create a new request id after every downstream failure, silently choose one of several
  revisions, or replay search merely because WorldSkeleton was not reached.

### 6. Tests Required

- Assert adopted evidence binds exact request/job/graph revisions.
- Assert evidence resume has empty invocation prefix, zero research usage and a
  `design_phase_resumed` event.
- Live acceptance must show `design-resume/resumed-evidence-checkpoint.json` and no new research
  workspace or external search calls.

### 7. Wrong vs Correct

- Wrong: treat Designer as one atomic stage and restart Direct Research after a downstream schema
  validation failure.
- Correct: retain immutable evidence lineage, revalidate its checkpoint, and rerun only the
  dependent world-compilation suffix.

## Tool schema semantic IR compilation

### 1. Scope / Trigger

- Applies whenever Environment Designer authors input, output, or observation schemas for a
  frozen `ToolSurfacePlan`.

### 2. Signatures

- Model output: `ToolSchemaIRDraft`.
- Framework output: `ToolSchemaDraft` containing closed Draft 2020-12 JSON Schema.

### 3. Contracts

- The Agent authors a flat, closed, acyclic, fully reachable typed node graph; it does not author
  raw JSON Schema syntax.
- Framework code deterministically compiles object requiredness, array items, unions, scalar
  constraints, and `additionalProperties=false`.
- The compiled artifact depends on the exact IR artifact; resume revalidates the IR, recompiles it,
  and requires byte-equivalent typed content.

### 4. Validation & Error Matrix

- Unknown, cyclic, duplicate or unreachable node -> semantic rework at the schema IR node.
- Tool id or schema kind drift -> semantic rework.
- Compiled Draft invalid or compiled artifact differs from its IR -> fail closed.
- Same-job pre-IR compiled artifact -> reusable only after current full Draft validation.

### 5. Good/Base/Bad Cases

- Good: an observation has a required id and an array of union results; IR compiles required at the
  object level, one schema under items, and alternatives under `anyOf`.
- Base: a closed empty input object compiles without model-authored JSON Schema keywords.
- Bad: ask the model to place `required`, `items`, or `properties` directly in arbitrary JSON.

### 6. Tests Required

- Assert required fields, nested arrays and unions compile to a valid closed Draft.
- Assert cycles and unknown/unreachable references fail before compilation.
- Assert provider structured-output normalization accepts `ToolSchemaIRDraft`.

### 7. Wrong vs Correct

- Wrong: retry malformed model-authored JSON Schema with increasingly detailed examples.
- Correct: keep business shape decisions in typed Agent output and syntax ownership in a small,
  deterministic, fully tested framework compiler.

## State entity schema semantic IR compilation

### 1. Scope / Trigger

- Applies whenever Designer compiles one frozen `StateEntityPlan` into an entity schema.

### 2. Signatures

- Model output: `StateEntitySchemaIRDraft(entity, root_node_id, nodes)`.
- Framework output: `StateEntitySchemaDraft(entity, json_schema)` and immutable
  `StateEntitySchema`.

### 3. Contracts

- The Agent owns field type, requiredness, enum and nesting semantics, but never raw JSON Schema
  object syntax.
- Pydantic models own only closed output shape and scalar types. Framework preflight owns every
  node-local, graph-closure, frozen-plan and lifecycle invariant and reports all independently
  checkable failures in one `ValidationDiagnostic`.
- The root graph is an object, closed, acyclic and fully reachable; its root fields equal the
  frozen union of primary-key and mutable fields.
- Framework deterministically owns `properties`, `required`, `additionalProperties`, `items`,
  `anyOf` and final Draft 2020-12 validation.
- Treat scalar constraints as intersections. If `const` belongs to `enum`, compile the equivalent
  canonical `const` form without Agent rework; reject only a disjoint `const`/`enum` pair as an
  unsatisfiable semantic constraint.
- Diagnostics use stable field/index paths and framework-authored messages; never route on or
  persist Pydantic `msg`, `input`, `ctx`, or rejected Agent identifiers.
- Validation frontiers are monotonic: transport precedes shape, graph closure precedes frozen-plan
  checks, and compilation runs only after preflight is empty. Moving from an earlier failure to a
  newly reachable later failure is progress even when issue codes are disjoint.
- Concurrent Designer shards are all-settled. Each successful independent shard commits before the
  first original leaf error is propagated; never cancel already-paid sibling work that resume can
  safely reuse.
- Commit the IR before the compiled artifact. A compiled artifact may depend on exactly one IR;
  resume recompiles and revalidates it without another model turn.

### 4. Validation & Error Matrix

- Unknown, cyclic, duplicate or unreachable node -> local structured correction.
- Entity identity or root-field drift -> reject the IR revision.
- Lifecycle node missing or enum differs from the frozen plan -> reject the IR revision.
- Compiled schema open/invalid -> framework error; never ask the model to hand-author syntax.

### 5. Good/Base/Bad Cases

- Good: payment fields and lifecycle enum compile to a closed object and commit IR before schema.
- Base: one id-only entity compiles in one model turn.
- Bad: expose arbitrary `dict[str, JsonValue]` JSON Schema syntax to the Agent, then repeatedly
  prompt it to add `type` or `additionalProperties`.

### 6. Tests Required

- Assert closed compilation, exact planned fields and lifecycle enum.
- Assert cycles, unplanned fields and identity drift fail before a compiled Artifact is committed.
- Assert node-local constraints are aggregated, an unknown/non-object root advances to frozen-plan
  diagnostics after correction, and transport -> shape -> semantic failures never become false
  no-progress.
- Assert equivalent `enum` + `const` intersections canonicalize without a model turn while a
  disjoint pair fails with a typed unsatisfiable-constraint issue.
- Assert a committed IR resumes without an InvocationBackend call.
- Live acceptance must prove a previously failing entity advances without replaying earlier
  Research/Entity nodes.

### 7. Wrong vs Correct

- Wrong: classify every distinct raw-schema failure as one `semantic_contract_violation`, causing
  real progress to be treated as no-progress, or make the Agent discover independent invariants
  one expensive turn at a time.
- Correct: make raw syntax structurally unrepresentable, aggregate safe typed issues at the deepest
  reachable frontier, and treat any later-frontier correction as progress.

## World closure semantic projection

### 1. Scope / Trigger

- Applies after all ToolContracts are assembled and before authoring global invariant Rules.

### 2. Signatures

- Framework input: full validated `WorldSkeleton` plus ToolContracts.
- Agent input: `WorldClosureContext` with a deduplicated `WorldClosureConstraint` catalog and
  RulePaths that reference catalog ids.

### 3. Contracts

- Preserve executable references, constants, bounded arithmetic, operators, boolean composition,
  error state effects, descriptions, rule ids and evidence bindings.
- Remove repeated contract schema versions and clause ids; deduplicate clauses by exact semantic
  content. Elide only `schema_valid` bodies already retained and validated by framework code.
- Compact canonical context must remain at or below 192 KiB.

### 4. Validation & Error Matrix

- Unknown or unreachable constraint id -> local typed validation failure.
- Hash collision with different semantic content -> fail closed.
- Projection above 192 KiB -> fail before model invocation and shard the owning node.
- Provider retryable failure below the bound -> bounded fresh-session retry remains allowed.

### 5. Good/Base/Bad Cases

- Good: several transition variants share assignment clauses; one catalog entry is referenced by
  each RulePath while their distinct descriptions and boolean composition remain visible.
- Base: one small tool produces one closed catalog and one global closure turn.
- Bad: inline every complete ToolContract and repeat schema/version/clause metadata for every rule.

### 6. Tests Required

- Assert projected operator and state pointers match source clauses.
- Assert semantically identical clauses deduplicate and every catalog entry is reachable.
- Measure a real multi-tool acceptance context below the fixed bound before live invocation.

### 7. Wrong vs Correct

- Wrong: spend the entire retry lease on multiple provider turns with a redundant 250+ KiB
  ToolContract projection.
- Correct: framework retains full contracts, sends only a closed typed semantic projection, and
  independently validates the resulting invariants against the original complete world.

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

## Owner-scoped semantic revision and canonical design compilation

### 1. Scope / Trigger

- Applies to Direct design revision and both initial/rework Expansion design turns.
- Triggered whenever an Agent must replace complete design semantics after a Finding or mutation.

### 2. Signatures

- Agent output: `EnvironmentSemanticSourceDraft(world, curriculum_plan, task_requirements)` where
  `world` is `WorldSemanticSourceIRDraft`, not `WorldModelDraft`.
- Framework compiler: `EnvironmentDesigner._compile_semantic_source(...) -> EnvironmentDesignDraft`.
- Expansion output: `ExpansionDesignDraft(semantic_source, semantic_delta)` where delta entries are
  claim drafts without `after`.

### 3. Contracts

- Agent owns bounded state/tool schema node graphs, executable world Rule semantics, curriculum
  topology and ordered TaskRequirement Rule IR.
- Framework exclusively compiles StateSchema/ToolSurface/WorldModel, task reset/public/evaluator
  schemas, goal bindings, reachability, RewardSpec and VerificationRequirements.
- Reward is task-outcome aggregation fixed at 0/+1/-1 with failure-over-success precedence; Rule
  count cannot amplify it.
- Expansion claims include operation, subject identity, exact parent `before_hash`, changed aspects
  and rationale. The authoritative SemanticDelta, including every `after`, is framework-computed.
- Provider-normalized output schemas must retain the same forbidden-field boundary; checking only
  Pydantic `model_fields` is insufficient.

### 4. Validation & Error Matrix

- Task draft order/identity differs from CurriculumPlan -> reject the structured Agent turn.
- Typed StateEntitySchemaIR contains an unsupported union -> reject that owning structured turn.
- A root task-reset projection failure after typed IR validation -> framework invariant failure;
  persist the state-shape subject and do not trigger semantic rework.
- Task reset schema changes only because framework recompiled a changed state -> no TaskScopeDelta.
- Curriculum distribution changes -> one TaskDistributionDelta with exact framework before hash.
- Declared delta metadata differs from framework diff -> reject the Expansion design turn.
- Agent output includes raw state/tool schema, task schema/binding/reward/verification, unresolved
  release blockers, or delta `after` -> closed output-schema validation error before adoption.

### 5. Good/Base/Bad Cases

- Good: Agent changes a task success Rule; framework recompiles goal schema, reward and full rule
  closure, then computes a TaskScopeDelta containing the compiled task.
- Base: Agent preserves semantics; canonical compilation produces the same owned protocol fields.
- Bad: ask for a complete `EnvironmentDesignDraft`, accept `reward=99`, or let TaskScopeDelta carry
  an Agent-authored complete TaskRequirement.

### 6. Tests Required

- Assert semantic source has no reward/verification fields and TaskRequirementDraft has no protocol
  schemas or bindings.
- Assert semantic source exposes StateEntitySchemaIR/ToolSchemaIR rather than raw state/tool schema.
- Differentially assert compiled reset schema comes from the frozen world and reward values are
  canonical.
- Assert duplicate success Rules remain +1 and simultaneous success/failure returns -1 with
  succeeded=false.
- Assert provider output-schema normalization still excludes forbidden fields.
- Assert delta claims reject `after` and must exactly match framework-computed metadata.
- Assert state plus derived task-schema recompilation has state delta but no task delta, and seed
  space alone produces TaskDistributionDelta.
- Assert structural state unions fail at state-schema IR before curriculum/task invocations.

### 7. Wrong vs Correct

```python
# Wrong: repair Agent owns framework protocol and release policy.
draft = await invoke(model=EnvironmentDesignDraft)

# Correct: Agent owns semantics; framework recompiles protocol and policy.
source = await invoke(model=EnvironmentSemanticSourceDraft)
draft = designer._compile_semantic_source(source, evidence_graph=graph, evidence_graph_ref=ref)
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

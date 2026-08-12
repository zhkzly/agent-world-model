# R9 closed node and handoff contracts — C5 plus complete-v1 ABI

This file is part of design revision 9, closure lineage `C5`, and the
complete-v1 parent ABI reconciliation. It does not change the two-graph
architecture or implement future control loops. C5 retains C1's schema/owner,
C2 difficulty, C3 verified flat store and C4 hashed pip-sync decisions while
closing finite lock selection, stdlib-empty and project-discovery facts from
the C4 full-scope block. Python/Pydantic names may change
mechanically; field meaning, authority and visibility may not change without a
new plan review.

All records use closed schemas: unknown fields are rejected. Every `ArtifactRef`
contains `artifact_id`, `kind`, `digest`, package-relative/run-relative `path`
and `media_type`. Model output never contains an `ArtifactRef`.

## 1. Framework provenance contracts

```text
WorkCoordinate:
  run_id: str
  graph_id: "design" | "candidate"
  node_id: closed node/family ID
  shard_key: str | null
  revision: positive int

ArtifactEnvelope[T]:
  kind: closed Artifact kind
  schema_version: positive int
  producer: WorkCoordinate
  output_ports: nonempty ordered tuple[closed port name]
  semantic_revision_digest: sha256
  dependencies: ordered tuple[ArtifactRef]
  payload: T

WorkRecord:
  coordinate: WorkCoordinate
  owner: "controller" | "designer" | "builder" | "judge" | "registry"
  execution_kind: "framework" | "direct_llm" | "agent" | "candidate_process"
  semantic_revision_digest: sha256
  input_refs: ordered tuple[ArtifactRef]
  dependency_refs: ordered tuple[ArtifactRef]
  output_refs: ordered tuple[ArtifactRef]
  validation_ref: ArtifactRef | null       # null only for not_run/pre-validation error
  assurance_refs: ordered tuple[ArtifactRef]
  finding_refs: ordered tuple[ArtifactRef]
  status: "passed" | "failed" | "inconclusive" | "error" | "not_run"
  safe_code: closed safe code | null
  invalidated_by: null                       # immutable Direct baseline
```

The Artifact envelope is content-addressed together with producer, exact
declared output ports and dependencies. For an Edge input, framework matches
the exact producer node and source port. One immutable multi-output envelope
may back multiple named bindings, but each binding still selects a declared
source port and the flattened dependency list stores the envelope once. A
WorkRecord is written by framework only after a node revision reaches one
terminal evaluation. `DirectRun` stores the exact ordered WorkRecord refs;
Observe reconstructs graph facts from these records instead of coarse stage
strings.

`input_refs` are the exact port values consumed/disclosed by the transaction;
`dependency_refs` are the exact ordered direct causal dependencies used for
readiness and future invalidation. They may overlap but are not inferred from
one another. `candidate_process` records Integration/Judge execution across the
untrusted Runtime boundary while the declared framework owner retains
validation and Artifact commit authority. Direct always writes
`invalidated_by=null`. The repair child appends a separate immutable
`WorkInvalidation` rather than mutating this record.

`passed` requires nonempty committed outputs and a passed validation record.
`not_run` requires empty outputs/assurance/Findings and null validation;
`failed`/`inconclusive` require validation or assurance evidence plus a Finding;
pre-validation infrastructure `error` may have null validation but must carry a
safe code. These invariants are framework-validated before persistence.

The framework owner of every current node is closed here; implementation may
not invent another owner or release authority:

```text
designer:
  research_plan, research_acquire, research_synthesis,
  world_architecture, shared_tool_semantics, tool_semantics, world_rules,
  curriculum_plan, task_requirement, modeling_gate, verifier_intent
builder:
  build_plan, candidate_build, integration
judge:
  judge
controller:
  package                       # the single framework ReleaseKernel decision
registry:
  registry                      # physical re-verification + atomic publication
```

`package` is the one ReleaseKernel boundary: it may create a ReleaseDossier and
Package only after all required hard claims for the exact revision pass.
`registry` may independently reject or atomically publish that exact package,
but it cannot reinterpret Judge evidence or create a second release decision.

Current R9 Finding is framework-owned and deliberately route-free:

```text
Finding:
  finding_id: stable framework digest/id
  failed_claim_ref: ArtifactRef
  subject_ref: ArtifactRef
  evidence_refs: nonempty ordered tuple[ArtifactRef]
  expected_condition: bounded safe condition
  owner: "controller" | "designer" | "builder" | "judge" | "registry"
  code: closed safe code
  category: closed observation category
  severity: "block_revision" | "block_integration" | "block_release"
  blocks_release: bool
  fingerprint: sha256
```

The framework derives `owner` from the subject Artifact envelope and the closed
node-owner table; it is evidence about the responsible domain, not a route.
`blocks_release` is derived from the claim/severity and cannot contradict them.
The Finding contains no target coordinate, next node, retry, budget,
invalidation, jump distance or release action. The current task persists it and
terminates the affected Direct run honestly. The bounded-repair child re-derives
and verifies owner/condition against subject/evidence provenance before adding a
framework-owned route decision.

## 2. Common model boundary

Every model call receives one frozen projection plus, at most, one framework
correction packet. Direct R9 carries one first compiler-detected issue rather
than adding an issue aggregation subsystem:

```text
CorrectionPacket:
  code: closed validation code
  path: exact model-output path
  violated_condition: short safe condition
  expected_category: closed expected category
```

It contains no owner, target, budget, Gate state, hidden test, sealed value or
downstream verdict. Default local correction count is one; a second requires
framework-proven strict progress and the global budget. Provider retry uses the
same immutable projection and is not semantic correction.

Every model/Agent `NodeSpec` that declares one local correction must pass that
packet into the second physical invocation. A compiler error without a safe,
exact packet is terminal. Provider/transport, candidate source, dependency,
process, Integration, Judge, Package and Registry failures never enter local
correction. A completed, nonempty Direct LLM response with
`finish_reason=stop` that fails only strict JSON-object parsing may use an
in-memory format Feedback turn. Default nodes still stop after one such
correction. A Direct node explicitly declaring two corrections may use the
second only after a format-first path: for another format replacement or a
newly parsed exact semantic issue. Semantic-first then format is terminal, and
proposal three never authorizes proposal four. Rejected text is only the
immediately preceding assistant message; it is never persisted, exposed to
Observe, or added to `CorrectionPacket`.

Forbidden model/Agent output authority, recursively:

```text
ArtifactRef / WorkRecord / Finding / GateResult / JudgeReport / RepairDecision
Budget / PermissionDecision / CandidateManifest / ReleaseDossier
RegistryReceipt / hash / digest / file size / release or completion verdict
```

Every model-visible evidence collection is a one-based `CitationCatalog`:

```text
CitationCatalogItem:
  index: positive int
  source_label: safe public label
  source_url: sanitized URL
  excerpt: bounded text
```

Models cite catalog indexes. Framework alone maps indexes to persistent
evidence IDs/refs.

### Minimal Codex Agent adapter

Agent execution keeps the cleanroom's one thin SDK boundary. `AgentRoute` has
exactly `model`, `base_url` and `api_key_env`. `CodexAgentBackend` creates one
ephemeral `AsyncCodex` thread using the locked `openai-codex==0.144.4`,
`wire_api="responses"`, SDK request/stream retries set to zero and the constant
`Sandbox.full_access`; it returns the existing `InvocationResult` or
`InvocationError`. Primary-to-fallback selection remains the only adapter-level
retry.

For each turn, framework creates one temporary `CODEX_HOME`, copies exactly one
product-owned Skill bundle under `skills/<name>/`, computes the bundle closure
digest before and after the turn, and deletes the directory after closing the
SDK session. It passes only the selected credential environment handle and does
not inherit ambient Skills, Hooks, MCP or Codex config. This isolation is for
deterministic Skill discovery, not a new permission system. There is no custom
capability matrix, permission evaluator, configurable sandbox mode,
`ProfileResolver`, callback lifecycle, worker protocol or plugin/profile DSL.

The true-boundary preflight uses a unique public marker present only inside the
mounted bundle. The real turn must report the initial `Available skills` names
as the exact singleton plus that marker; framework separately verifies the
physical singleton closure, closure digest, non-ambient `CODEX_HOME`, SDK
session close and cleanup. A mismatch fails closed as
`agent_skill_surface_unverified`. It adds no runtime node or release authority.

## 3. Research nodes

### `research_plan` — AGENT / Researcher

Graph input: `DesignRequestRef` and optional prior `EvidenceGraphRef`.

Model-visible projection:

```text
ResearchPlanInput:
  need: str
  origin: "direct" | "expand"
  allowed_source_classes: tuple["web" | "repository" | "api_docs"]
  known_claim_summaries: bounded tuple[str]
  unresolved_dimensions: bounded tuple[CoverageDimension]
  parent_semantic_summaries: bounded tuple[str]
  correction: CorrectionPacket | null
```

Closed model output:

```text
ResearchPlanDraft:
  queries: 1..6 unique str
  questions_to_resolve: 1..12 str
```

Prompt objective: identify the minimum real evidence required to model the
requested tool/world/task semantics. Runtime Skill:
`research-world-evidence`. It cannot claim evidence, coverage, Design validity
or release.

Framework validation rejects duplicate/empty queries, disallowed source kinds,
credential/private URLs and unbounded requests. Committed output is
`ResearchPlanRef`.

### `research_acquire` — FRAMEWORK

Input: `ResearchPlanRef`, source policy and budget. Output:
`SourceRecordRef[] + CitationCatalogRef` from real Search/Fetch/Extract
adapters. Each source record binds sanitized URL, retrieval timestamp, provider,
content digest/length and extraction status. Snippets and search titles alone
cannot become evidence.

### `research_synthesis` — AGENT / Researcher

Model-visible projection:

```text
ResearchSynthesisInput:
  need: str
  questions_to_resolve: tuple[str]
  citations: CitationCatalog
  correction: CorrectionPacket | null
```

Closed model output:

```text
ResearchSynthesisDraft:
  claims: 1..32 of
    {statement: str,
     kind: "observed" | "bounded_inference",
     citation_indexes: nonempty unique tuple[int]}
  conflicts: 0..16 of
    {statement: str, citation_indexes: at least two unique int}
  gaps: 0..16 of
    {dimension: CoverageDimension, missing_fact: str}
```

Prompt objective: synthesize only citation-backed claims and explicit gaps.
Same Researcher Skill; no design/code/Gate output. Framework maps citations,
validates provenance/claim closure, computes CoverageMap and commits
`EvidenceGraphRef + CoverageMapRef`.

## 4. Direct semantic nodes

All nodes below are `DIRECT_LLM`, mount no Skill/tool/workspace and receive the
same common forbidden-authority instruction. Their Prompt is their complete
method plus the node-specific objective below.

Framework supplies a closed `SemanticCatalog` of one-based indexes for compiled
actors/entities/fields/tools/rules. Model output references catalog indexes,
never internal IDs.

Shared source `RuleDraft` ADT (the same exact declaration is disclosed to
ToolSemantics, WorldRules, and TaskRequirement):

```text
Right = {kind:"literal",value:finite JSON scalar|finite scalar list[0..32]} |
        {kind:"semantic_ref",semantic_index:frozen SemanticCatalog index}
PredicateDraft = {left_semantic_index:frozen SemanticCatalog index,
                  operator:eq|ne|lt|le|gt|ge|contains|not_contains|exists|not_exists,
                  right:Right}; exists/not_exists require literal null
EffectDraft = {target_semantic_index:frozen SemanticCatalog index,
               operation:set|increment|decrement|add|remove|preserve|reject,
               value:finite JSON scalar|finite scalar list[0..32]|semantic_ref};
               preserve/reject require null
RuleDraft = {when:0..6 PredicateDraft,effects:1..6 EffectDraft,
             error_kind:null in non-error sections|[a-z][a-z0-9_]{0,63} in errors only
             (1..64 code points),rationale:stripped nonempty text<=300 code points,
             citation_indexes:0..8 unique frozen CitationCatalog indexes;[] without a catalog}
```

Framework validates paths/operators/value categories and compiles RuleDrafts to
core Rule IR. Free-form rationale never becomes executable logic.

### `world_architecture`

Input projection: need, relevant EvidenceGraph/Coverage claims and citations.

Closed output:

```text
Field:
  name: snake name 1..64
  category: "text" | "integer" | "number" | "boolean" |
            "timestamp" | "identifier" | "enum" | "list"
  required: boolean
  values: 1..16 unique nonempty strings iff category="enum" or "list";
          otherwise omitted
  entity_ref: optional actual-relation snake name

WorldArchitectureSourceDraft:
  boundary:
    {name: stripped text 1..160, purpose: stripped text 1..4096 Unicode code points,
     system_of_record: stripped text 1..160, authority: stripped text 1..160,
     actors: 1..8 unique stripped text 1..80}
  entities: 1..16 of
    {name: stripped text 1..64, purpose: stripped text 1..300,
     fields: 1..24 uniquely named Field}
     # an entity-owned field's entity_ref, when present, exactly names an emitted entity
  tools: one coherent minimal JSON array of 1..8
    {name: stripped text 1..64, purpose: stripped text 1..300,
     actor_names: 1..frozen_actor_count unique declared actor names,
     argument_fields: 0..24 uniquely named Field,
     result_fields: 1..24 uniquely named Field}
     # tool argument/result entity_ref is optional and may be an external snake-name relation label
  known_divergences: 0..16 of
    {statement: stripped text 1..500, kind: "observed" | "bounded_inference",
     citation_indexes: 1..6 frozen one-based indexes}
```

Objective: define identity, authority, entity meaning and one coherent minimal
tool surface; combine related workflow actions when needed to stay within the
tool bound. Before returning, and after any correction, recheck the complete
object against every disclosed field, cardinality, uniqueness, reference, actor
and citation rule. Framework assigns IDs, JSON Schema, required/reference closure and a
ToolCouplingPlan. Output commits `WorldArchitectureRef + SemanticCatalogRef`.
The compiler maps semantic `required` to JSON Schema `required`; the model does
not emit schema keywords. Text is capped at 4096 Python Unicode code points,
integers at signed 64-bit, numbers must be finite, identifiers at 128 characters and lists
at 32 items. Field names are unique within their owner. Enum/list/reference
conditions above are exact, and catalog references must resolve before commit.

### `shared_tool_semantics[group]`

Input projection: exact ordered tool catalog indexes, shared-state summary and
the safe EvidenceGraph citation catalog.

Closed output:

```text
SharedToolSemanticsSourceDraft:
  atomicity | concurrency | idempotency: 1..group_size arrays; each contains
    1..group_size frozen tool indexes and partitions every member exactly once
    from the ordered input tool_indexes; unless evidence requires a finer
    split, one domain containing that complete ordered group is valid
  ordering: 0..8 stripped nonempty text items, each <=500 code points
  compensation: 0..8 stripped nonempty text items, each <=160 code points
  error_policy: one stripped nonempty shared-policy string <=500 code points,
    applying to the complete frozen group
```

Objective: return one compact complete JSON object, cover every member exactly
once in all three shared dimensions, and recheck it after correction. Framework
injects the frozen ordered group, binds the shared policy to its members, validates
the exact partitions, and digests/commits one shared contract. No node is
materialized when no multi-tool group exists.

### `tool_semantics[tool]`

Input projection: one exact tool, related semantic catalog, optional committed
shared contract and citations.

Closed output:

```text
ToolSemanticsSourceDraft:
  preconditions: 1..6 non-error RuleDraft
  transitions: 1..6 non-error RuleDraft with at least one state-changing effect
  postconditions: 0..6 non-error RuleDraft
  errors: 0..6 errors-only RuleDraft
```

Objective: minimum sufficient complete behavior for the frozen tool, without
examples, trajectories, echoed tool/shared-contract fields, schema mechanics,
reward or verifier data; recheck every section after correction. Framework binds
the frozen tool/shared contract and compiles one independently committed Artifact.

### `world_rules`

Input projection: compact compiled World/Tool closure and unresolved coverage.

Closed output:

```text
WorldRulesSourceDraft:
  initial_rules: 0..8 non-error RuleDraft with citation_indexes=[]
  invariants: 0..16 non-error RuleDraft with citation_indexes=[]
```

Objective: only initial-state and cross-entity/tool rules not already expressed
locally; empty invariants are valid. Recheck the complete object after correction.
Framework rejects tautologies, schema restatement and duplicate rules.

### `curriculum_plan`

Input projection: compiled capability/tool/actor catalog, world rules, and the
safe EvidenceGraph citation catalog.

Closed output:

```text
CurriculumPlanSourceDraft:
  families: 1..8 ordered items
    {task_family_id: [a-z][a-z0-9_]{0,63} (1..64 code points),
     objective: stripped nonempty text <=500,
     actor_index: one frozen actor index,
     tool_indexes: 1..tool_count unique frozen indexes,
     dimensions: 1..6 ordered items
       {name: [a-z][a-z0-9_-]{0,39} (1..40 code points),
        meaning: stripped nonempty text <=300,
        levels: 2..5 uniquely named ordered items
          {name: [a-z][a-z0-9_-]{0,39} (1..40 code points),
           meaning: stripped nonempty text <=300}},
     sampling_intent: stripped nonempty text <=300,
     citation_indexes: 1..6 unique frozen indexes}
```

Objective: define bounded parameterized task families, not fixed task IDs,
seeds, rewards or verifier cases. The accepted dimension/level grammar includes
hyphens and is disclosed without normalization or tightening. Framework rejects
duplicate names, empty meanings, out-of-bound counts and invalid frozen indexes,
then derives task coordinates/order and compiles exactly one per-family contract:

```text
DifficultySchema:
  task_family_id: framework-derived stable ID
  dimensions: ordered tuple of
    {name: str, meaning: str,
     levels: ordered tuple[{name: str, meaning: str}]}
  key_order: exact tuple of dimension names  # framework-derived
  schema_digest: sha256                       # framework-derived
```

`DifficultySelection` is the closed JSON mapping `mapping[str, str]` whose
insertion/key order exactly equals `key_order`; all declared dimensions are
required once and only once, and each value must name one corresponding level.
The duplicate-aware decoder rejects duplicate keys before mapping construction.
Missing, extra, reordered, duplicate or out-of-domain entries are validation
failures; there is no coercion, default level, partial selection or free-form
extension. Framework owns compilation and validation. The Direct LLM owns only
the bounded semantic names/meanings, while candidate code owns neither.

### `task_requirement[task]`

Input projection is the exact one-copy task semantic view:

- `family`: objective, actor/tool scope, one semantic `DifficultySchema`
  containing only dimensions, meanings and ordered levels, sampling intent, and
  family citation indexes;
- one global `semantic_catalog.bindings` catalog;
- each relevant tool's surface plus its preconditions, transitions,
  postconditions and errors, with no repeated bindings or computed digest;
- WorldRules `initial_rules` and `invariants`, without Artifact or digest
  metadata; and
- the safe `CitationCatalog` accepted by the rule compiler plus the existing
  reachability policy.

No field in this projection carries an Artifact ref, `work_refs`, or a digest.
Dimension/level names and meanings are read-only context for authoring task
semantics.

Closed output:

```text
TaskRequirementSourceDraft:
  public_goal_fields: 1..12 unique frozen SemanticCatalog indexes
  initial_rules: 0..8 TaskRequirementRuleDraft
  success_rules: 1..8 TaskRequirementRuleDraft
  failure_rules: 0..8 TaskRequirementRuleDraft
  terminal_rules: 1..8 TaskRequirementRuleDraft

TaskRequirementRuleDraft:
  when: 0..6 PredicateDraft
  effects: 1..6 EffectDraft
  rationale: stripped nonempty text <=300 code points
  citation_indexes: 0..8 unique frozen CitationCatalog indexes
```

Objective: complete one frozen task family's reset/success/failure/termination
semantics and recheck every section after correction. This task-only source
shape is closed before framework copies each rule and injects its fixed
non-error value for the existing strict generic RuleDraft compiler. A
model-supplied `error_kind`, including `null`, is an extra source field and
fails; ToolSemantics and WorldRules retain their unchanged shared generic
RuleDraft source contract. Framework injects the task family index, compiles
closed public-goal/initial-config schemas, instruction template,
EvaluatorGoalBinding template, RewardSpec, TerminationSpec and
VerificationRequirements. The committed TaskRequirement refers to the exact
read-only `DifficultySchema` and cannot redefine it.

`TaskRequirementRef` has a direct ordered dependency on `CurriculumPlanRef`.
Its semantic revision binds this exact source projection and output contract,
including the difficulty dimensions, meanings, levels and order; changing any
of those semantics invalidates that task requirement, `modeling_gate`, the
resulting `EnvironmentDesign`, and CandidateGraph descendants. Unaffected
task-family coordinates remain separate dependencies for the bounded-repair
child.

## 5. Agent advisory/build nodes

### `build_plan` — AGENT / Environment Engineer

Visible input:

```text
BuildPlanInput:
  world_contract: minimum public implementation projection
  materializer_contract: closed request/result schemas
  runtime_contract: exact five-operation protocol
  implementation_contract: required files/dependencies/limits
  correction: CorrectionPacket | null
```

Closed output:

```text
BuildPlanDraft:
  steps: 1..12 of
    {goal: str, suggested_paths: tuple[relative path],
     contract_sections: nonempty tuple[str], self_check: str}
  risks: 0..8 str
```

Skill: `engineer-build-planning`. Read-only workspace. Suggested paths are
advisory and never a manifest. Framework validates path safety/contract refs and
commits BuildPlan.

### `verifier_intent` — AGENT / Challenger

Visible input contains compact Design/Task/Rule/tool public projections and no
candidate source.

Closed R9 output:

```text
VerifierIntentDraft:
  checks: 1..8 of
    {task_family_index: one-based frozen task-family index,
     tool_index: one-based frozen public-tool index,
     family: "unknown_seed" | "alternate_difficulty" |
             "idempotency_key_variation" | "argument_variation",
     argument_index: one-based declared argument index iff
                     family="argument_variation"; otherwise null,
     risk: 1..280-char semantic reason}
```

Skill: `challenge-agent-world`. This is the smallest executable subset of the
canonical Verifier IR for R9, not a generic verifier language. Framework
validates catalog refs and family applicability, then assigns case IDs and
private uint64 seeds/idempotency keys/type-preserving argument mutations. Model
output cannot contain a case ID, seed, concrete mutation/value, public/sealed
partition, expected result, verdict or release threshold. Persisted
VerifierBundle projection contains only public commitments and counts; concrete
private cases remain in same-run Judge memory and never enter CandidateBuild,
ordinary ArtifactStore, package or Observe. Judge must execute every compiled
case in a fresh candidate process. Baseline claims retain exact expected-value
checks; variation cases enforce the compiled public response schema, declared
result types, idempotency/restart and safe state transition rather than treating
the Challenger's risk text as a verdict.

### `candidate_build` — AGENT / Environment Engineer

Visible workspace files are exactly:

```text
inputs/design.json
inputs/implementation-contract.json
inputs/build-plan.json
inputs/repair-packet.json          # absent in current R9 task
parents/<verified digest>/...      # absent for Direct; read-only in Expand child
```

No challenge/verifier/Judge/release file or projection exists.

Closed completion output:

```text
CandidateCompletionDraft:
  summary: str
  self_checks: 0..12 of
    {name: str,
     observed: "passed" | "failed" | "not_run",
     note: str}
  known_limits: 0..8 str
```

Skill: `engineer-environment-codegen`; fresh writable candidate workspace.
Completion is advisory. Framework scans the physical closure, rejects unsafe
paths/symlinks/dependencies/secrets, computes file hashes/sizes/tree digest and
commits CandidateManifest/EnvironmentCandidate.

## 6. Offline candidate installation

Before any candidate process starts, framework canonical-parses
`pyproject.toml` and `uv.lock`. The current slice accepts only registry wheel
dependencies already fixed by the lock. It rejects before invoking `uv`:

- root or dependency build backends and any selected source distribution;
- `tool.uv.sources`, `uv.toml`, workspaces, dependency groups and editable
  installs;
- Git, URL, path, directory and local dependencies;
- candidate-defined index/default-index/extra-index/find-links configuration;
- a lock source outside the one framework-configured registry;
- a selected wheel without exact lock hash/size or without a matching wheel in
  the framework's trusted wheel store.

Framework copies only those hash/size-verified wheels into an empty
framework-owned run-local wheel directory, keeps uv's run-local cache separate,
and commits one `AdmittedLockClosure` before invoking uv. Each entry contains
canonical distribution name, exact version and admitted wheel filename/hash/
size candidates. Framework derives one complete transitive active closure and
fails closed on markers, extras, forks, duplicate/multiple versions or any
shape requiring resolution. It compiles only normalized `name==version` plus
the admitted hash set into a temporary framework-owned requirements file;
candidate strings are never copied verbatim. Framework invokes the tested
`uv 0.11.29` without a shell using exactly these two argument policies:

```text
uv venv
  --no-project
  --python <framework-python>
  --no-python-downloads
  --config-file <framework-owned-empty-uv.toml>
  <fresh-venv>

uv pip sync
  --python <fresh-venv-python>
  --offline
  --no-build
  --strict
  --allow-empty-requirements
  --require-hashes
  --no-index
  --find-links <run-local-verified-wheel-store>
  --config-file <framework-owned-empty-uv.toml>
  --cache-dir <run-local-verified-wheel-cache>
  <framework-owned-hashed-requirements.txt>
```

Both commands execute from one fresh framework-owned working directory outside
the candidate root. The local `--find-links` directory is the sole
wheel-ingestion surface and is
always paired with `--no-index`; framework never edits uv's private cache
format. `uv pip sync` never receives the candidate root, `pyproject.toml` or
`uv.lock`, so `tool.uv.sources` and project installation are not an installer
input. The explicit environment is a minimal framework allowlist; candidate and
ambient `UV_*`, index, proxy, credential, Python-path and config variables are
absent. Empty requirements are admitted only for an exactly empty stdlib-only
closure. Runtime and Materializer are launched from scanned source entrypoints
with the fresh interpreter. Source, lock, requirements and wheel-store digests
are rechecked after sync. Framework enumerates installed distributions and
requires exact canonical `(name, version)` set equality with the admitted
closure; duplicates, missing, extra or candidate-root distributions fail.
Missing wheels or any preflight/install mutation produces an
honest Integration failure; network or build fallback is forbidden.

C1 adds no package-index client, wheel downloader or dependency configuration
platform. The first live Direct proof may be stdlib-only. A deployment may
provide a framework-owned trusted wheel store through the existing composition
root; an absent requested wheel fails honestly and is not fetched during
Integration.

The Builder-visible Runtime response ABI and the supervisor use the same five
closed top-level envelopes; missing or additional fields are rejected:

```text
handshake -> {operations: ["handshake", "reset", "invoke", "snapshot", "close"]}
reset     -> {status: "ok"}
invoke    -> {status: "ok", result: <exact frozen result keys and JSON types>}
snapshot  -> {state: <safe JSON object>}       # framework/Judge private
close     -> {status: "ok"}
```

This is the fixed Runtime ABI, not a configurable schema engine. Snapshot state
is never projected into PublicTask, candidate inputs, package, telemetry or
Observe.

## 7. Trusted materialization and evaluator chain

Candidate Task Materializer accepts:

```text
MaterializationRequest:
  seed: uint64
  task_type: frozen task-family ID
  actor: allowed actor ID
  difficulty: DifficultySelection validated against the exact TaskRequirement
```

It may return only:

```text
MaterializerResult:
  seed: exact echo
  task_type: exact echo
  actor: exact echo
  difficulty: exact echo
  public_goal: closed data matching compiled public-goal schema
  initial_config: closed data matching compiled initial-config schema
```

It cannot return instruction text, evaluator goal, expected solution, reward,
termination, verifier data, seed override or hidden state.

Exact echo means the returned ordered key/value sequence is identical to the
admitted request after duplicate-aware parsing; semantic equality of an
unordered object is insufficient. Framework validates the request before
launching candidate code and validates the echo again before using
`public_goal` or `initial_config`.

Framework then performs the authoritative conversion:

```text
TaskRequirement + MaterializerResult
  -> validate exact echoes and closed schemas
  -> render PublicTask.public_instruction from frozen instruction template
  -> bind private EvaluatorGoalBinding from compiled Rule/goal templates
  -> create Runtime reset(seed, actor, initial_config)
  -> Judge evaluates real state/snapshot against Rule IR,
     EvaluatorGoalBinding, RewardSpec and TerminationSpec
```

Integration proves materializer determinism, exact echoes, unknown seed/actor/
difficulty handling, reset/invoke/idempotency/snapshot/restart/teardown. Judge
freshly materializes independent episodes and proves task reachability and
verifier claims. PublicTask never exposes EvaluatorGoalBinding or snapshot.
For at least one family it runs two valid selections differing in one declared
level and requires a corresponding `public_goal` or `initial_config` semantic
change, not only a label/instruction change. It also proves an invalid level and
missing/extra/duplicate/reordered keys fail before Judge/release.

## 8. Portable package and Registry closure

The current R9 package is not `manifest.json + runtime.py`. Minimum physical
closure is:

```text
envpkg.toml
manifest.json
pyproject.toml
uv.lock
LICENSE
world/world_spec.json
world/rule_ir.json
tasks/curriculum.json
tasks/materializer_protocol.json
evidence/provenance.json
evidence/assurance.json
evidence/fidelity.json
sbom/sbom.json
<framework-scanned candidate source closure>
```

`tasks/curriculum.json` contains the exact ordered per-family
`DifficultySchema` values and digests used by TaskRequirement and the
Materializer protocol. Registry cold-read recompiles/revalidates them and
rejects a package whose curriculum, task, protocol or manifest commitments
disagree. A future Consumer must use this schema directly rather than define a
new one.

`envpkg.toml` binds package coordinate/origin/parent refs, relative runtime and
materializer entrypoints, exact source-tree and `uv.lock` digests,
World/Rule/Task contract digests, CandidateManifest, passed IntegrationReport,
JudgeReport, pre-package ReleaseDossier and pre-publish
TelemetryReleaseSummary digests. It does not bind Manifest digest, avoiding a
hash cycle. The framework/Registry typed Manifest binds the physical closure,
contracts, source tree, dependency closure, build/Judge/dossier refs and
lineage. Provenance binds exact input Artifact refs and separate semantic/
implementation lineage. Assurance projects hard claim IDs/status, evidence
commitments and actual budget without sealed details. Fidelity records evidence,
known divergences and limits. SBOM is recompiled from physical
`pyproject.toml`/`uv.lock`; phase-one license state remains explicitly `unknown`
unless hard supply-chain evidence verifies it.

Package excludes sealed cases, evaluator instances, expected output corpus,
solution, secret, Agent transcript, absolute workspace path and mutable parent
dependency.

Registry stages and cold-reads every file, canonical-parses metadata, recompiles
SBOM, rehashes source/package bytes, checks Artifact producer/dependency closure,
confirms Integration passed for the exact Design/Candidate, confirms Judge used
that Integration and VerifierBundle, and verifies the pre-package dossier plus
TelemetryReleaseSummary before atomic publication. The summary is a minimal
framework Artifact derived from WorkRecords and operation evidence; it proves
required real Direct/Agent/search/fetch/extract categories occurred and keeps
unavailable usage as `unknown`, never zero. It is not a dashboard or second
control plane. Observe reports `released` only after repeating the package/
receipt digest check.

After atomic publication, Registry alone emits this released handoff:

```text
EnvironmentPackageRef:
  package_id: str
  version: immutable version
  package_digest: sha256
  manifest_digest: sha256
  registry_receipt_ref: ArtifactRef
  design_ref: ArtifactRef
  candidate_manifest_ref: ArtifactRef
  integration_ref: ArtifactRef               # exact passed IntegrationReport
  judge_report_ref: ArtifactRef
  semantic_lineage_ref: ArtifactRef
  implementation_lineage_ref: ArtifactRef

RegistryReceipt:
  package_id: str
  version: immutable version
  package_digest: sha256
  manifest_digest: sha256
  registry_revision: str
  published_at: timestamp
```

The package bytes do not contain their post-publication receipt, avoiding a
hash cycle. The released ref and receipt are immutable run Artifacts that bind
the same cold-read package/manifest and exact Design/Candidate/passed
Integration/Judge closure. Direct semantic lineage records `origin=direct` and
empty parent refs; implementation lineage records the exact final source-tree
digest. Campaign and Suite admission later consume this ref and must reject any
package, manifest or receipt mismatch.

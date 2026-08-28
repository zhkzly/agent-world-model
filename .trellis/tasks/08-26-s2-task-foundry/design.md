# S2 Goal-First Task Foundry — Technical Design

## 1. Feasibility verdict

The redesigned S2 is implementable, but only for a clean S1 v2 release that
publishes independently qualified taskable semantics.

The unqualified claim below is rejected:

> Given arbitrary tool descriptions, reset and opaque native state, infer every
> meaningful Task, its setup and a trustworthy verifier.

A trace proves that one execution occurred. It does not establish why the result
is a natural user goal, what collateral is forbidden, what alternative routes
are valid, or whether the verifier checks the intended relation.

The implementable boundary is:

```text
S1 independently qualifies reusable capability semantics
-> S2 deterministically compiles concrete Tasks
-> checker freezes
-> final public instruction freezes
-> public Agent proves reachability twice
-> adversarial admission seals the TaskPack
```

## 2. Design decisions and deletions

### Retained evidence principles

- real public execution;
- protected native truth;
- public/protected information separation;
- checker-before-witness ordering;
- fresh equivalent starts;
- argument-provenance checks;
- no-op/near-miss/collateral/answer challenges;
- structural corpus accounting and downstream evaluation.

### Deleted old architecture

- mandatory Graph Task lane;
- mandatory Programmatic Task lane;
- persistent universal tool graph and edge taxonomy;
- random-walk chain length as Task difficulty;
- path-first Task meaning;
- per-Task unrestricted generated TruthExtractor/OutcomeVerifier;
- hidden setup programs and direct native mutation;
- custom WitnessRecipe/value-expression DSL;
- persistent `QuarantinedCandidate` lifecycle;
- LLM Judge as final Task truth;
- universal State IR/snapshot restore;
- custom Registry/service/MCP/HTTP semantics;
- demo/MVP/canned Task completion paths.

The design adds only two semantic layers:

```text
S1 qualified capability atom
S2 bounded GoalProgram composition
```

## 3. End-to-end architecture

```text
S1 Research
  Need + evidence
  -> accepted Development Brief + Requirement/workflow IDs

S1 Environment Builder (Codex SDK)
  Brief + actor contract
  -> executable actor uv project
  -> start schema/data, tools, native state, docs/tests

S1 independent semantic planning
  Brief + public surface
  -> Host-frozen expected capability/condition relations

S1 Semantics Author (separate Codex SDK thread/workspace)
  frozen expected relations
  + public surface
  + decode-only read-only candidate/native view after freeze
  -> release-local TaskSemantics uv project

S1 Semantic Qualification (Host)
  public executions + independent native reads + physical negatives
  -> qualified CapabilitySpecs/start cases/evaluators

S1 Publication v2
  actor project + TaskSemantics project + evidence/digests
  -> immutable EnvironmentRelease v2

S2 Release Admission
  prepare/open exact release in isolated process

S2 Blueprint Compiler (deterministic Host Python)
  capabilities + start cases + bindings + corpus policy
  -> TaskBlueprint candidates

S2 Checker Compiler (deterministic Host Python)
  Blueprint + protected start facts/bindings
  -> frozen TaskChecker

S2 Instruction Renderer (deterministic Host Python)
  public Blueprint frame
  -> exact canonical instruction + answer schema

S2 Witness Runner (Responses tool-calling Agent)
  exact instruction + actor surface only
  -> successful public trace #1
  -> successful fresh public trace #2

S2 Admission Host
  checker challenges + leakage/provenance audits
  -> TaskPack or typed rejection

S2 Assessment/Corpus
  independent actor trials -> TaskAssessment
  TaskPacks + assessments + policy -> CorpusManifest
```

## 4. Exact role and SDK boundaries

| Component | Implementation | Inputs | Outputs | Cannot decide |
| --- | --- | --- | --- | --- |
| Research producer/reviewer | existing Responses SDK paths | Need, search/read evidence | accepted Brief | environment/Task truth |
| Environment Builder | Python Codex SDK | frozen BuilderProjection + actor contract | actor uv project | release admission, Tasks |
| Expected-semantics freeze | existing independent Qualification-style model turn + Host validation | Brief, public docs/tools/probes | typed expected capability records | manifests/verdict |
| Semantics Author | Python Codex SDK, fresh thread/workspace | frozen records, read-only candidate view | TaskSemantics uv project | Host IDs/verdict, Task instances |
| Semantic Qualification | deterministic Host runner + independent native readers | actor + semantics projects | evidence and release verdict | model consensus |
| Blueprint/compiler/checker/instruction | deterministic framework Python | qualified contracts/facts/policy | TaskDefinition | domain semantics beyond contracts |
| Witness/assessment policy | Responses tool-calling Agent inside Host loop | exact instruction + actor surface | actions/final answer | checker or truth |
| Admission/corpus | deterministic framework Python | traces/facts/checker/policy | TaskPack/Assessment/Manifest | new Task meaning |

### Prompt ownership

Prompts/Skills are versioned method inputs, not semantic runtime authority.

- `environment-codegen/SKILL.md`: tells Codex how to write the actor project.
- new `task-semantics-codegen/SKILL.md`: tells Codex how to write TaskSemantics.
- new `witness-agent/SKILL.md`: guides the public tool-calling policy.

Schemas, source digests, execution, challenge generation and verdicts remain
Host code. A prompt rule without a corresponding deterministic check is not a
product contract.

## 5. EnvironmentRelease v2 and preparation

### 5.1 Representative immutable layout

```text
EnvironmentRelease/
├── release.json
├── payload-manifest.json
├── qualification.json
├── actor/                      # generated actor uv project
├── semantics/                  # generated protected TaskSemantics uv project
├── dist/
├── docs/
└── licenses/
```

The outer descriptor binds:

```text
actor project digest and factory
TaskSemantics digest and factory
public start/reset schemas and docs
qualification digest
locked preparation metadata
```

No v1/v2 compatibility loader is implemented.

### 5.2 Prepared release API

```python
prepared = prepare_release(release_path, cache_root)
with prepared.open(instance_directory) as session:
    actor = session.actor
    trusted = session.trusted
```

`prepare_release` verifies exact bytes, creates a release-specific locked runtime
and records runtime identity. `open` launches an isolated child interpreter for
that exact release. The Host exposes typed proxies, not arbitrary imports.

The implementation reuses the current `_qualification_runner` subprocess and
Host-journal pattern. A small internal stdin/stdout transport is an implementation
detail; no public service, Registry, HTTP or MCP protocol is added.

Actor projection:

```python
reset(start)
tools()
invoke(tool_name, arguments)
close()
```

Trusted projection:

```python
start_cases(seed, limit)
inspect()
capabilities()
enumerate_bindings(capability_id, facts)
evaluate_atom(request)
evaluate_condition(request)
```

The trusted proxy never exposes general source imports or native writes.

## 6. Protected TaskSemantics contract

```python
class TaskSemantics(Protocol):
    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]: ...
    def inspect(self, instance_directory: Path) -> JSONValue: ...
    def capabilities(self) -> tuple[CapabilitySpec, ...]: ...
    def enumerate_bindings(
        self, capability_id: str, facts: JSONValue
    ) -> tuple[BindingCandidate, ...]: ...
    def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult: ...
    def evaluate_condition(
        self, request: ConditionCheckRequest
    ) -> ConditionCheckResult: ...
```

`evaluate_condition` may return `unsupported` when the release declares no
conditional Tasks. All return values validate against release-bound JSON schemas.

### 6.1 StartCase

```python
@dataclass(frozen=True)
class StartCase:
    case_id: str
    reset_input: JSONObject | None
    regime_tags: tuple[str, ...]
```

Properties:

- deterministic from release ID, seed and limit;
- valid against `start_schema`;
- reset-only;
- no hidden/public setup calls;
- replayed and semantically aligned during S1 Qualification;
- regime tags are protected corpus metadata, not actor hints.

### 6.2 CapabilitySpec

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    requirement_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    actor_role: str
    task_kind: Literal["query", "state_change", "process"]
    intent_label: str
    protected_binding_schema: JSONObject
    public_descriptor_schema: JSONObject
    facets: tuple[FacetSpec, ...]
    conditions: tuple[ConditionSpec, ...]
    answer_fields: tuple[AnswerFieldSpec, ...]
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    supported_goal_kinds: tuple[GoalKind, ...]
    rendering: RenderingSpec
```

- `requirement_ids` prove Need/Brief grounding.
- `workflow_ids` license cross-capability `AllGoal` composition.
- scopes are opaque release-local labels used only for conflict checks.
- supported kinds prevent the Host from inventing `If`/`ForEach` semantics.
- rendering contains labels, not an arbitrary executable template.

### 6.3 FacetSpec

```python
@dataclass(frozen=True)
class FacetSpec:
    name: str
    value_schema: JSONObject
    allowed_operators: tuple[Literal["eq","neq","lt","lte","gt","gte","min","max"], ...]
    public_label: str
    visibility: Literal["task_literal", "reset", "public_tool"]
```

S1 Qualification demonstrates that `reset` and `public_tool` facets are actually
actor-observable. A `task_literal` facet may be stated in the instruction because
S1 has certified it as a user-facing descriptor.

### 6.4 ConditionSpec

```python
@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    public_label: str
    visibility: Literal["reset", "public_tool"]
    binding_scope: Literal["world", "selected_binding"]
```

The semantics package evaluates the condition from protected facts; S1
Qualification separately proves that the actor can observe the same condition.
A refusal encountered by one witness is not a condition declaration.

### 6.5 AnswerFieldSpec and RenderingSpec

```python
@dataclass(frozen=True)
class AnswerFieldSpec:
    field_id: str
    schema: JSONObject
    public_label: str

@dataclass(frozen=True)
class RenderingSpec:
    imperative: str
    target_noun: str
    answer_phrase: str | None
```

The Host owns grammar and punctuation. Release-local labels carry domain meaning.
This avoids arbitrary generated instruction templates while retaining natural
wording.

### 6.6 BindingCandidate

```python
@dataclass(frozen=True)
class BindingCandidate:
    semantic_key: str
    eligible: bool
    reason_codes: tuple[str, ...]
    protected_binding: JSONObject
    public_descriptor: JSONObject
    facets: JSONObject
```

`semantic_key` aligns the business referent across fresh starts. It is not
required to equal a native row ID, UUID, inode or Git object ID.

The renderer and public Agent receive only `public_descriptor`/public facets.
Ineligible candidates are retained for boundary/wrong-target challenges.

### 6.7 Atomic checks

```python
@dataclass(frozen=True)
class AtomCheckRequest:
    capability_id: str
    before_facts: JSONValue
    after_facts: JSONValue
    protected_binding: JSONObject
    trace_projection: tuple[TraceEvent, ...]
    final_answer: JSONValue | None

@dataclass(frozen=True)
class AtomCheckResult:
    initially_satisfied: bool
    satisfied: bool
    required_effects_ok: bool
    collateral_ok: bool
    answer_ok: bool | None
    process_ok: bool | None
    report_values: JSONObject
    failure_codes: tuple[str, ...]
```

Atomic evaluation provides no scalar reward.

## 7. S1 semantics authoring and qualification

### 7.1 No new Agent organization

The Semantics Author extends the existing Builder-independent Qualification
mechanism. It is not a new multi-Agent workflow.

Host flow:

```text
Brief-derived expected relations generated in a fresh context
-> Host validates coverage and freezes EXPECTED_TASK_SEMANTICS.json
-> Host stages read-only candidate/public/native view
-> Codex SDK writes semantics project in a separate workspace
-> Host runs uv/schema/source-separation checks
-> Host executes public/native semantic tests and physical negatives
-> repair the owning code path or fail closed
```

### 7.2 Codex workspace inputs

Immutable Host files:

```text
EXPECTED_TASK_SEMANTICS.json
TASK_SEMANTICS_CONTRACT.md
PUBLIC_SURFACE.json
read-only candidate view
```

Codex owns release-specific native decoding, capability specs, binding
enumeration, start-case generation and evaluators. It cannot edit the actor
project, Host manifests or verdicts.

### 7.3 Qualification obligations per Taskable capability

1. an eligible StartCase exists;
2. `inspect` agrees with an independently authored native reader;
3. bindings identify the intended entity and public descriptor;
4. a real public success changes the intended atomic result;
5. no-op remains false;
6. wrong target and boundary near miss remain false;
7. required effects and forbidden collateral are distinguished;
8. answer fields are grounded in actual facts;
9. declared public facets/conditions are actor-observable;
10. fresh reset reproduces the same business predicates;
11. physical mutations of inspector/evaluator logic are detected while the
    controlled release remains executable.

Marker-only, declaration-only, syntax/import/crash negatives do not count.

### 7.4 Failure ownership and repair

- Actor behavior contradicts frozen Brief relation: `EnvironmentDefect`; return
  factual public/native evidence to the Environment Builder and rebuild.
- Actor is correct but semantics code misreads/checks it: `SemanticsDefect`;
  repair the same Semantics Author thread/workspace.
- Expected relation itself is unsupported/incorrect: return to Research/Brief.
- Provider/dependency failure: retry identical bytes or end typed Infrastructure.

Any actor repair invalidates the semantics project and reruns semantic authoring
and Qualification.

## 8. S2 TaskBlueprint and GoalProgram

### 8.1 Selection is not a Goal node

```python
@dataclass(frozen=True)
class SelectorSpec:
    selector_id: str
    capability_id: str
    filters: tuple[FacetPredicate, ...]
    rank: RankSpec | None
    cardinality: Literal["exactly_one", "any_one", "all"]
```

Selectors bind named slots from pre-execution candidates. Unique selection fails
on ties; `any_one` and `all` are rendered explicitly.

### 8.2 Four-node GoalProgram

```python
type GoalProgram = AtomGoal | AllGoal | IfGoal | ForEachGoal

@dataclass(frozen=True)
class AtomGoal:
    capability_id: str
    binding_slot: str

@dataclass(frozen=True)
class AllGoal:
    children: tuple[GoalProgram, ...]

@dataclass(frozen=True)
class IfGoal:
    condition_id: str
    binding_slot: str | None
    then_goal: GoalProgram
    else_goal: GoalProgram

@dataclass(frozen=True)
class ForEachGoal:
    selector_id: str
    capability_id: str
```

Standalone `Select` and `Report` nodes are removed. They did not represent
independent user goals and would require unnecessary compiler/interpreter nodes.

### 8.3 Reporting

```python
@dataclass(frozen=True)
class ReportFieldRef:
    atom_path: tuple[int, ...]
    field_id: str

@dataclass(frozen=True)
class ReportSpec:
    fields: tuple[ReportFieldRef, ...]
```

The final answer schema is compiled from the referenced qualified
`AnswerFieldSpec`s.

### 8.4 TaskBlueprint and concrete TaskDefinition

```python
@dataclass(frozen=True)
class TaskBlueprint:
    selectors: tuple[SelectorSpec, ...]
    goal: GoalProgram
    report: ReportSpec | None

@dataclass(frozen=True)
class TaskDefinition:
    task_id: str
    release_id: str
    semantics_digest: str
    start_case: StartCase
    blueprint: TaskBlueprint
    protected_bindings: JSONObject
    public_instruction_frame: JSONObject
    canonical_instruction: str
    answer_schema: JSONObject | None
    checker: CheckerArtifact
```

TaskDefinition identity excludes witness traces, actor-model trials and corpus
policy.

## 9. Deterministic Blueprint enumeration

The first implementation uses no LLM for Blueprint creation.

```python
def enumerate_blueprints(capabilities, bindings, policy):
    # Atomic Goals
    for capability in capabilities:
        for selector in compile_valid_selectors(capability, bindings, policy):
            yield TaskBlueprint(
                selectors=(selector,),
                goal=AtomGoal(capability.capability_id, selector.selector_id),
                report=optional_report(capability, policy),
            )

    # Collection Goals
    for capability in capabilities_supporting("foreach"):
        for selector in compile_multi_target_selectors(capability, bindings):
            yield TaskBlueprint((selector,), ForEachGoal(selector.selector_id, capability.id), None)

    # Conditional Goals
    for capability in capabilities_supporting("if"):
        for condition in capability.conditions:
            yield from compile_non_vacuous_conditionals(capability, condition, bindings)

    # Cross-capability Goals
    for group in group_by_shared_workflow_id(capabilities):
        for compatible_children in bounded_compatible_combinations(group, max_children=3):
            yield AllGoal(compatible_children)
```

Host rejection rules:

- no accepted Requirement/workflow anchor;
- unsupported goal kind;
- hidden or unrenderable selector;
- unresolved unique tie;
- empty/all-vacuous selection;
- duplicated/redundant atom;
- `AllGoal` without shared workflow ID or with incompatible scopes;
- `IfGoal` with no qualified public condition or equivalent branches;
- nesting/child/selector budget exceeded;
- checker already true at start.

Corpus observations may prioritize enumeration order but cannot add predicates.

## 10. TaskChecker compilation

### 10.1 Checker artifact

Checker is canonical data interpreted by Host code, not arbitrary generated
Python.

```python
@dataclass(frozen=True)
class CheckerArtifact:
    task_definition_preimage_digest: str
    goal_program: GoalProgram
    selector_resolutions: JSONObject
    protected_bindings: JSONObject
    answer_schema: JSONObject | None
    semantics_digest: str
```

### 10.2 Evaluation rules

- `AtomGoal`: call qualified `evaluate_atom` for the bound semantic key.
- `AllGoal`: require every child; allowed scope is only the qualified union.
- `IfGoal`: evaluate the qualified condition from before facts and exactly the
  chosen branch.
- `ForEachGoal`: require all selected semantic keys and reject modifications to
  non-selected bindings covered by the capability scope.
- `ReportSpec`: parse JSON and compare each field with checked atom report values.

Trace is projected only to capability-declared process predicates. Outcome Tasks
do not compare against a reference trace.

### 10.3 Freeze gate

```text
compile checker
-> canonical serialize + digest
-> persist immutable artifact
-> evaluate initial before==after/no trace/no answer
-> require not satisfied
-> only then render final instruction
```

The Host records an ordering event so tests can prove no witness-model call
occurred before checker/instruction freeze.

## 11. Canonical instruction rendering

Renderer inputs:

```text
CapabilitySpec labels
public BindingCandidate descriptors/facets
SelectorSpec/GoalProgram/ReportSpec
actor-visible reset context
```

Renderer never sees protected bindings, native fields or a witness trace.

Host grammar covers:

- imperative intent;
- exact public target/filters/rank/cardinality;
- conditional wording from qualified ConditionSpec;
- conjunction/complete-set wording;
- structured reporting requirement.

Audits:

1. every Blueprint slot/constraint appears exactly once;
2. no unknown constraint appears;
3. no protected/native value or field name appears;
4. no tool name/reference order appears;
5. no answer value appears;
6. unique/set-valued wording matches selector cardinality;
7. reset context and instruction together provide all Task literals.

The resulting string is immutable and is the exact input to witness and later S3
actor runs. The core path does not paraphrase it.

## 12. Public witness runner

### 12.1 Responses loop, not Codex SDK

The witness is an acting policy, not a code-generation task. The Host uses the
OpenAI Responses API with function tools derived from the release ToolSpecs.

Host loop:

```python
while budget.remaining:
    response = model.respond(instruction, prior_public_items, available_tools)
    for tool_call in response.tool_calls:
        observation = actor.invoke(tool_call.name, tool_call.arguments)
        journal.record(tool_call, observation)
        feed observation back
    if response.final_answer is not None:
        break
```

The Host owns dispatch, schema validation, budgets, exact prior items, journal
and final answer parsing.

### 12.2 Visibility

The policy receives only:

```text
canonical instruction
public reset observation/context
public environment docs/limitations
ToolSpecs
ToolObservations
answer schema
```

It never receives GoalProgram, checker, semantics, native state, protected
binding or failure-clause feedback.

### 12.3 Public-operand provenance

For each tool-argument leaf, Host records one of:

```text
TaskLiteralRef
ResetObservationRef
ToolObservationRef
ToolSchemaConstant
AgentChoice
```

`AgentChoice` is allowed only when the value is not a protected-only binding,
not fixed by a Task constraint and not used by the checker as a target/answer
operand. A value equal to a protected-only identifier without public origin
rejects the run.

Error-message/prose scraping is never a provenance source. `contract.*` errors
provide no values or capability evidence.

### 12.4 Two fresh constructive witnesses

A TaskPack requires two successful runs on separate instances materialized from
the same StartCase. Both use the exact canonical instruction and satisfy the
same frozen checker. IDs/routes may differ.

The pack stores concrete traces, final answers, provenance reports, before/after
fact digests and checker results. No custom replay expression language or
removal-replay engine is required.

A bounded failure is `NoPublicWitness`, not mathematical impossibility.

## 13. Admission challenges

### 13.1 Layering

- S1 Qualification proves atomic inspector/evaluator sensitivity physically.
- S2 proves concrete selector/composition/instruction/answer sensitivity.

### 13.2 Required challenge records

| Challenge | Construction | Expected |
| --- | --- | --- |
| positive witness 1/2 | real public runs | satisfied |
| no-op | initial facts as terminal | failed |
| wrong/near-miss target | ineligible or alternate BindingCandidate + public attempt when reachable | failed |
| partial All | execute/retain subset child facts | failed |
| incomplete ForEach | omit at least one selected key | failed |
| collateral | positive goal plus extra public action on unrelated binding when reachable | failed |
| wrong answer | Host mutates structured answer | failed |
| alternative route | independent successful public run with differing action signature | satisfied |
| process violation | same terminal relation with prohibited order/action when reachable | failed |

Every category is `passed`, `failed` or `not_applicable(reason)`. Crashing or
unreachable mutants do not improve scores.

### 13.3 Checker mutation testing

Host creates canonical checker mutations:

- drop one `AllGoal` child;
- reduce `ForEach` selected set;
- change selector resolution;
- ignore collateral;
- ignore answer/process requirement.

The concrete challenge suite must kill every applicable mutation. A surviving
mutation is `CheckerDefect`.

### 13.4 Instruction defect detection

Two witness successes prove one policy can recover the wording. Independent
TaskAssessment later diagnoses broader recoverability. A repeatable alternate
interpretation is an `InstructionDefect` only when causal evidence shows the
instruction admits a meaning inconsistent with the checker.

## 14. Identities and projections

### 14.1 TaskDefinition

Identity binds semantic content only:

```text
release/semantics IDs
StartCase
Blueprint and protected/public bindings
checker artifact
canonical instruction and answer schema
```

### 14.2 TaskPack

```python
@dataclass(frozen=True)
class TaskPack:
    taskpack_id: str
    definition: TaskDefinition
    witness_evidence: tuple[WitnessRun, WitnessRun]
    admission_evidence: AdmissionReport
```

TaskPack excludes independent model trials, empirical difficulty and corpus
policy.

Public projection:

```text
task/release IDs
canonical instruction
actor-visible reset context
answer schema
public limitations
```

Protected projection:

```text
StartCase/reset input
GoalProgram/selectors/bindings
checker and semantics digests
admission evidence
```

Witness traces remain protected audit evidence and are not acting hints.

### 14.3 TaskAssessment

```python
@dataclass(frozen=True)
class TaskAssessment:
    assessment_id: str
    taskpack_id: str
    model_id: str
    policy_digest: str
    runner_digest: str
    run_results: tuple[AssessmentRun, ...]
    reliability: float
    calls: int
    tokens: int
    latency_ms: int
    failure_labels: tuple[str, ...]
```

Difficulty is assessment-relative and never appears in TaskDefinition structural
fingerprints.

### 14.4 CorpusManifest

Binds selected TaskPack IDs, selected assessment IDs, corpus policy, seed and
selection evidence. It may change when the target model/training budget changes
without rewriting TaskPacks.

## 15. Structural diversity and selection

```python
@dataclass(frozen=True)
class TaskFingerprint:
    capability_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    goal_shape: str
    selector_operators: tuple[str, ...]
    relation_count: int
    public_binding_depth: int
    start_regimes: tuple[str, ...]
    answer_required: bool
    process_required: bool
```

Selection:

1. remove exact TaskDefinition/checker duplicates;
2. group structural fingerprints;
3. apply text-near-duplicate filtering inside groups;
4. apply declared capability/shape/start budgets;
5. use TaskAssessment reliability/cost for the target corpus;
6. retain surplus/rejected records for audit.

Internal coverage is not a claim of complete Task-space coverage.

## 16. Direct coordinator

```python
def synthesize_tasks(
    release_path: Path,
    *,
    policy: CorpusPolicy,
    budget: SynthesisBudget,
    routes: ModelRoutes,
) -> SynthesisResult:
    prepared = prepare_release(release_path, policy.cache_root)
    release = admit_release_v2(prepared)

    admitted: list[TaskPack] = []
    audits: list[CandidateAudit] = []

    for start_case in release.trusted.start_cases(policy.seed, budget.start_cases):
        with prepared.open(new_instance_dir()) as session:
            reset_observation = session.actor.reset(start_case.reset_input)
            before = session.trusted.inspect()
            capabilities = session.trusted.capabilities()
            bindings = {
                cap.capability_id: session.trusted.enumerate_bindings(
                    cap.capability_id, before
                )
                for cap in capabilities
            }

        for blueprint in enumerate_blueprints(capabilities, bindings, policy):
            definition_or_rejection = compile_definition(
                release,
                start_case,
                reset_observation,
                before,
                bindings,
                blueprint,
            )
            if isinstance(definition_or_rejection, Rejection):
                audits.append(definition_or_rejection.audit)
                continue

            definition = definition_or_rejection
            witnesses = run_two_public_witnesses(prepared, definition, routes.witness)
            if witnesses is None:
                audits.append(no_witness_audit(definition))
                continue

            admission = challenge_task(prepared, definition, witnesses)
            if not admission.accepted:
                audits.append(admission.audit)
                continue

            admitted.append(seal_taskpack(definition, witnesses, admission))

    assessments = assess_for_policy(admitted, routes.assessment, policy)
    manifest = select_corpus(admitted, assessments, policy)
    return SynthesisResult(admitted, assessments, manifest, tuple(audits))
```

The actual implementation streams candidates and isolates instances; the
pseudocode fixes ownership and order.

## 17. Package shape without premature fragmentation

Start with the smallest files that have distinct owners:

```text
src/agent_env_foundry/
  existing modules
  preparation.py          # release v2 prepare/open/proxies
  semantics.py            # TaskSemantics models/validation
  qualification.py        # extend existing independent authoring/qualification
  release.py
  publication.py

src/agent_task_foundry/
  models.py               # immutable objects/serialization/projections
  compiler.py             # selectors, GoalProgram, checker, instruction
  runner.py               # Responses public episode runner/provenance
  admission.py            # witnesses/challenges/TaskPack
  corpus.py               # TaskAssessment/fingerprint/manifest
  api.py                  # direct coordinator
```

Split a file only when a real ownership/test boundary appears. Do not start with
plugins, workflow engines, graph runtimes, registries or service topology.

## 18. Error ownership

```text
InfrastructureFailure
  provider/dependency/timeout/process failure; semantic identities unchanged

EnvironmentDefect
  actor project violates frozen Brief/public/native behavior

SemanticsDefect
  TaskSemantics misdecodes or mis-evaluates a correct actor world

UnsupportedCapability
  deterministic/publicly observable Task semantics unavailable

RejectedBlueprint
  invalid workflow, selector, cardinality, initial truth or hidden constraint

CheckerDefect
  challenge false acceptance/rejection or surviving checker mutation

InstructionDefect
  slot/leakage/cardinality mismatch or proven alternate meaning

NoPublicWitness
  bounded public search failed

RejectedTaskPack
  intrinsic admission failure

RejectedForCorpus
  valid TaskPack does not fit target model/reliability/cost/distribution policy
```

Every repair reruns the dependent chain. Environment changes invalidate
TaskSemantics and all descendant Tasks.

## 19. Concrete walkthrough: ocean-container dispute

Qualified release semantics:

```text
capability: submit a timely dispute for an eligible invoice
workflow: invoice-dispute-management
facets: carrier, charge_amount, deadline, eligibility
required: matching dispute exists with submitted status
forbidden: unrelated invoices/disputes unchanged
answer field: dispute_reference
```

S2:

```text
StartCase contains several current-user invoices and one unique max charge
Selector: eligible && carrier == task literal; rank max(charge_amount)
AtomGoal: submit_dispute(selected_invoice)
Report: dispute_reference
```

Order:

```text
inspect/bind
-> checker freezes selected semantic key and collateral relation
-> canonical instruction freezes
-> witness Agent uses public snapshot and submit tool
-> two fresh runs satisfy checker with public invoice references
-> no-op, late/lower invoice, collateral and wrong answer fail
-> TaskPack seals
```

The Task never contains a database row ID or tool sequence.

## 20. Concrete walkthrough: filesystem/Git

Qualified release semantics may expose one atomic `repair_and_commit` capability
or two capabilities sharing workflow `repository-maintenance`.

A concrete Task selects a public file/module/failing-check descriptor, requires
checks to pass and a reachable commit, optionally reports commit ID, and forbids
protected metadata/unrelated-file changes.

The checker freezes file/check/ref/object relations before the exact instruction
is shown to the witness Agent. Different correct patches and tool orders pass;
no-op, wrong file, failing tests, uncommitted worktree, unreachable commit,
collateral edit and wrong commit answer fail.

## 21. Validation and anti-overdesign gates

Mechanical tests:

- release/semantics schema and digest binding;
- process isolation and projection separation;
- Codex workspace input immutability;
- capability/condition physical-negative sensitivity;
- deterministic selector/Goal/checker/instruction compilation;
- checker-before-instruction-before-model-call order;
- public-operand provenance and protected-guess rejection;
- two fresh witness runs;
- checker mutation kill and alternative-route acceptance;
- TaskDefinition/TaskPack/Assessment/Manifest identity separation;
- structural deduplication and deterministic corpus selection.

Real evidence:

- regenerate SQLite and filesystem/Git releases with the same frozen framework;
- meet PRD Task-yield/structure/start floors;
- freeze code/prompts/contracts and run a held-out Need;
- run matched-budget baselines and report downstream value.

No additional semantic abstraction, Agent role, protocol or package is added
unless a real failing cross-domain/held-out case demonstrates that the current
contract cannot express the required behavior.

# S2 Goal-First Task Foundry — Technical Design

## 1. Feasibility verdict

The redesigned S2 is implementable for S1 v2 releases that publish independently
qualified taskable semantics.

The following stronger claim is rejected:

> Tool descriptions, reset and opaque native state are sufficient to infer every
> meaningful Task and a trustworthy verifier.

A trace proves only that one execution occurred. It does not establish user
intent, required versus allowed effects, forbidden collateral, valid alternative
routes or verifier correctness.

The implementable boundary is:

```text
S1 qualifies reusable capability/condition/composition semantics
-> S2 compiles concrete Goal-first Tasks deterministically
-> checker freezes
-> final public instruction freezes
-> public Agent proves reachability twice
-> adversarial admission seals the TaskPack
```

## 2. Why the old S2 is replaced

The old Graph/Programmatic proposal is rejected because it made search mechanism
precede Task meaning, allowed correlated Task/solution/verifier errors, built
truth after seeing the reference path and required too many generated roles.

Retained principles:

```text
real public execution
protected native truth
public/protected separation
checker-before-witness
fresh equivalent starts
operand provenance
near-miss/collateral/answer challenges
structural corpus accounting
```

Deleted product mechanisms:

```text
mandatory Graph/Programmatic lanes
persistent universal tool graph
random-walk length as difficulty
per-Task unrestricted truth/verifier Python
hidden setup/native mutation/snapshot restore
WitnessRecipe/value-expression DSL
persistent QuarantinedCandidate lifecycle
LLM final judge
universal State IR
Registry/service/MCP/HTTP semantics
demo/MVP/canned Task paths
```

Only two semantic layers remain:

```text
S1 qualified taskable capability atom
S2 bounded GoalProgram composition
```

## 3. End-to-end architecture

```text
S1 Research
  Need + evidence
  -> Development Brief + Requirement/workflow IDs

S1 Environment Builder (Codex SDK)
  frozen BuilderProjection + actor contract
  -> actor uv project, start space, tools, native state, docs/tests

S1 expected-semantics freeze
  fresh independent typed model turn + Host validation
  -> frozen capability/condition/composition expectations

S1 TaskSemantics Author (separate Codex SDK workspace/thread)
  frozen expectations + public surface
  + decode-only read-only candidate/native view after freeze
  -> protected TaskSemantics uv project

S1 Semantic Qualification (Host)
  public executions + independent native reads + physical negatives
  -> qualified semantics evidence

S1 Publication v2
  actor project + semantics project + evidence/digests
  -> immutable EnvironmentRelease v2

S2 Release Admission
  prepare separate actor/semantics runtimes

S2 Compiler (deterministic Host Python)
  StartCases + CapabilitySpecs + bindings + policy
  -> TaskBlueprint + frozen TaskChecker + final instruction

S2 Witness Runner (Responses tool-calling Agent)
  exact final instruction + actor surface only
  -> successful fresh public traces #1 and #2

S2 Admission Host
  provenance + concrete challenges + checker mutations
  -> TaskPack or typed rejection

S2 Assessment/Corpus
  independent Responses trials -> TaskAssessment
  TaskPacks + assessments + policy -> CorpusManifest
```

## 4. Exact role and SDK boundaries

| Component | Mechanism | May see protected facts | Writes persistent code | Owns verdict |
| --- | --- | :---: | :---: | :---: |
| Research producer/reviewer | existing Responses SDK paths | no | no | Host aggregation |
| Environment Builder | Python Codex SDK | Builder workspace only | actor project | no |
| Expected-semantics freeze | fresh typed model turn + Host validation | no source before freeze | no | no |
| TaskSemantics Author | Python Codex SDK, fresh workspace | read-only after freeze | semantics project | no |
| Semantic Qualification | Host runner/native readers | yes | Host evidence only | yes |
| S2 compiler/checker/instruction | deterministic framework Python | contracted bindings/facts | framework artifacts | yes |
| Witness/assessment policy | Responses function-tool loop | no | no | no |
| Admission/corpus | deterministic framework Python | checker inputs only | evidence/manifests | yes |

### Prompt ownership

Prompts are versioned method inputs, not semantic runtime authority.

```text
environment-codegen/SKILL.md
  guides actor project authoring

task-semantics-codegen/SKILL.md
  guides semantics project authoring

witness-agent/SKILL.md
  guides public policy behavior
```

Every load-bearing prompt rule has a corresponding schema, Host validation,
real execution gate or explicit non-authority status. Framework compilation,
identity and verdicts are code, not prompt text.

## 5. EnvironmentRelease v2 and preparation

### 5.1 Immutable layout

```text
EnvironmentRelease/
├── release.json
├── payload-manifest.json
├── qualification.json
├── actor/                       # generated actor uv project
├── semantics/                   # generated protected semantics uv project
├── dist/
├── docs/
└── licenses/
```

The outer descriptor binds actor/semantics entry points and digests, public
schemas/docs, Qualification digest and locked preparation metadata. No v1
compatibility loader exists.

### 5.2 Prepared release API

```python
prepared = prepare_release(release_path, cache_root)
with prepared.open(instance_directory) as session:
    actor = session.actor
    trusted = session.trusted
```

Preparation creates two exact locked runtimes:

```text
actor runtime
  actor project installed
  instance read/write

semantics runtime
  semantics project installed
  actor project not installed/importable
  instance access checked read-only by Host tree manifests
```

`open` launches separate child interpreters/proxies. The Host checks the instance
manifest before and after every trusted call and rejects any mutation.

Implementation reuses the existing subprocess/Host-journal pattern. A small
internal stdin/stdout transport is private implementation detail; no public
service, Registry, HTTP or MCP protocol is introduced.

Actor proxy:

```python
reset(start)
tools()
invoke(tool_name, arguments)
close()
```

Trusted proxy:

```python
start_cases(seed, limit)
inspect()
capabilities()
enumerate_bindings(capability_id, facts)
evaluate_atom(request)
evaluate_condition(request)
```

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

All outputs validate against release-bound JSON schemas. `evaluate_condition`
may return unsupported when the release declares no conditional Tasks.

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
- reset input validates against `start_schema`;
- reset-only, no setup program;
- replayed and semantically aligned during S1 Qualification;
- regime tags are protected corpus metadata, not actor hints.

### 6.2 CapabilitySpec

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    requirement_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    composition_rules: tuple[CompositionRule, ...]
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

`requirement_ids` ground the capability. `workflow_ids` identify the business
workflow but do not by themselves authorize composition. Scopes are opaque
release-local labels used only by deterministic conflict checks.

### 6.3 CompositionRule

```python
@dataclass(frozen=True)
class CompositionRule:
    rule_id: str
    workflow_id: str
    kind: Literal["all"]
    capability_ids: tuple[str, ...]
    max_occurrences: int
```

A rule explicitly licenses one bounded cross-capability `AllGoal` set. This
prevents inverse/alternative actions in the same broad workflow from being
concatenated merely because their scopes do not collide.

### 6.4 FacetSpec

```python
@dataclass(frozen=True)
class FacetSpec:
    name: str
    value_schema: JSONObject
    allowed_operators: tuple[
        Literal["eq","neq","lt","lte","gt","gte","min","max"], ...
    ]
    public_label: str
    visibility: Literal["task_literal", "reset", "public_tool"]
    public_schema_pointer: str | None
```

- `task_literal`: S1 certifies it as a user-facing descriptor that may be stated.
- `reset`: value exists at a validated reset-observation path.
- `public_tool`: value exists at the declared ToolSpec output-schema pointer and
  is demonstrated by public execution.

A broad `{"type":"object"}` output schema cannot authorize a nested public
operand/facet without an explicit schema path.

### 6.5 ConditionSpec

```python
@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    public_label: str
    visibility: Literal["reset", "public_tool"]
    binding_scope: Literal["world", "selected_binding"]
    true_capability_ids: tuple[str, ...]
    false_capability_ids: tuple[str, ...]
    report_field: AnswerFieldSpec | None
```

S1 Qualification proves that the actor can observe the same condition and that
both branch licenses map to accepted Brief relations. A refusal observed in one
trace is not a condition declaration.

A branch may be goal-less only when `report_field` supports explicit
“otherwise report” behavior.

### 6.6 AnswerFieldSpec and RenderingSpec

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

The Host owns grammar/punctuation. Release-local labels carry domain meaning and
are schema-checked; there is no arbitrary executable template.

### 6.7 BindingCandidate

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

`semantic_key` aligns a business referent across fresh starts, not incidental IDs.
Renderer/public policy receive only public descriptor/facets. Ineligible
candidates support wrong-target/boundary challenges.

### 6.8 Atomic and condition checks

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

Condition evaluation analogously returns boolean/observability/report values.
No scalar reward is returned.

## 7. S1 semantics authoring and Qualification

### 7.1 No new Agent organization

The semantics route extends existing Builder-independent Qualification. It does
not introduce Researcher/Critic/Reviewer/Arbiter product roles.

```text
fresh typed expected-semantics turn
-> Host validates complete Requirement/workflow coverage
-> freeze EXPECTED_TASK_SEMANTICS.json
-> stage PUBLIC_SURFACE.json and read-only candidate view
-> Codex SDK writes semantics project
-> Host checks uv/schema/import separation
-> Host executes native/public/physical Qualification
```

### 7.2 Codex workspace inputs

Immutable Host inputs:

```text
EXPECTED_TASK_SEMANTICS.json
TASK_SEMANTICS_CONTRACT.md
PUBLIC_SURFACE.json
read-only candidate view staged after freeze
```

Codex owns release-specific native decoding, start cases, capability/condition/
composition records, binding enumeration and evaluators. It cannot edit actor
bytes, Host manifests or verdicts.

### 7.3 Qualification obligations per Taskable capability

1. eligible StartCase exists;
2. inspect agrees with independent native reader;
3. bindings identify intended entity/public descriptor;
4. real public success flips intended atomic truth;
5. no-op/wrong target/boundary remain false;
6. required effects/forbidden collateral differ;
7. answer/report fields are grounded;
8. declared facets and conditions are publicly observable at qualified schema
   paths;
9. fresh reset reproduces business predicates;
10. semantics calls do not mutate instance state;
11. semantics cannot import actor business code;
12. physical inspector/evaluator mutants are killed while executable.

Marker/declaration-only, syntax/import/crash negatives do not count.

### 7.4 Failure ownership

```text
EnvironmentDefect
  actor behavior contradicts frozen Brief/public/native relation
  -> rebuild actor; invalidate and regenerate semantics

SemanticsDefect
  actor is correct but semantics misreads/evaluates
  -> repair same semantics thread/workspace

Research/Brief defect
  expected relation unsupported/incorrect
  -> return upstream

InfrastructureFailure
  provider/dependency/process failure
  -> retry identical identities or fail typed
```

## 8. S2 TaskBlueprint and GoalProgram

### 8.1 SelectorSpec

```python
@dataclass(frozen=True)
class SelectorSpec:
    selector_id: str
    capability_id: str
    filters: tuple[FacetPredicate, ...]
    rank: RankSpec | None
    cardinality: Literal["exactly_one", "any_one", "all"]
```

Selectors bind named slots from pre-execution candidates. `exactly_one` rejects
ties; `any_one`/`all` wording is explicit.

### 8.2 Four-node GoalProgram

```python
type GoalProgram = AtomGoal | AllGoal | IfGoal | ForEachGoal

@dataclass(frozen=True)
class AtomGoal:
    capability_id: str
    binding_slot: str

@dataclass(frozen=True)
class AllGoal:
    composition_rule_id: str
    children: tuple[GoalProgram, ...]

@dataclass(frozen=True)
class IfGoal:
    condition_id: str
    binding_slot: str | None
    then_goal: GoalProgram | None
    else_goal: GoalProgram | None

@dataclass(frozen=True)
class ForEachGoal:
    selector_id: str
    capability_id: str
```

Selection and reporting are Blueprint attributes. Standalone `Select`/`Report`
nodes are deleted because they are not independent user goals.

At least one `IfGoal` branch has a goal. A goal-less branch requires a qualified
condition report field referenced by the Blueprint report.

### 8.3 Reporting

```python
type ReportSourceRef = AtomReportRef | ConditionReportRef

@dataclass(frozen=True)
class ReportSpec:
    fields: tuple[ReportSourceRef, ...]
```

Final answer schema is compiled from qualified answer/condition fields.

### 8.4 TaskBlueprint and TaskDefinition

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

TaskDefinition identity excludes witness evidence, model trials and corpus policy.

## 9. Deterministic Blueprint enumeration

No LLM is required.

```python
def enumerate_blueprints(capabilities, bindings, policy):
    for capability in capabilities:
        for selector in compile_valid_selectors(capability, bindings, policy):
            yield atomic_blueprint(capability, selector, optional_report=True)

        if "foreach" in capability.supported_goal_kinds:
            yield from foreach_blueprints(capability, bindings, policy)

        if "if" in capability.supported_goal_kinds:
            for condition in capability.conditions:
                yield from conditional_blueprints(capability, condition, bindings, policy)

    for rule in all_composition_rules(capabilities):
        yield from explicitly_licensed_all_blueprints(rule, capabilities, bindings, policy)
```

Host rejects:

- missing Requirement/taskability evidence;
- unsupported goal kind;
- hidden/unrenderable selector;
- unresolved unique tie;
- empty/vacuous selection;
- duplicate/redundant atom;
- AllGoal not exactly licensed by CompositionRule;
- incompatible scopes;
- IfGoal condition/branch not licensed or branches equivalent;
- goal-less branch without condition report;
- nesting/child/selector budget exceeded;
- checker already true at start.

Corpus observations may prioritize enumeration, never add predicates.

## 10. TaskChecker compilation

Checker is canonical Host-interpreted data, not arbitrary generated Python.

```python
@dataclass(frozen=True)
class CheckerArtifact:
    task_preimage_digest: str
    goal_program: GoalProgram
    selector_resolutions: JSONObject
    protected_bindings: JSONObject
    answer_schema: JSONObject | None
    semantics_digest: str
```

Evaluation:

- `AtomGoal`: call qualified `evaluate_atom` for bound semantic key.
- `AllGoal`: verify exact CompositionRule, require every child, allow only
  qualified scope union.
- `IfGoal`: evaluate condition from before facts and exactly the selected branch;
  validate condition report when branch is goal-less.
- `ForEachGoal`: require all selected keys and reject covered non-selected
  mutations.
- `ReportSpec`: parse JSON and compare checked atom/condition report values.

Trace is projected only for capability-declared process predicates. Outcome Tasks
do not compare reference and acting traces.

Freeze gate:

```text
compile checker
-> canonical serialize/digest/persist
-> evaluate before==after, empty trace, no answer
-> require not satisfied
-> render/audit final instruction
-> persist TaskDefinition
-> only now allow witness model call
```

A Host ordering journal makes this mechanically testable.

## 11. Canonical instruction rendering

Inputs:

```text
RenderingSpec and qualified labels
public BindingCandidate descriptors/facets
SelectorSpec/GoalProgram/ReportSpec
actor-visible reset context
```

Renderer never sees protected bindings/native fields/witness trace.

Host grammar expresses:

- imperative intent;
- target/filter/rank/cardinality;
- qualified condition and branch behavior;
- conjunction/complete-set semantics;
- structured reporting.

Audits:

1. every Blueprint slot/constraint appears exactly once;
2. no unknown/strengthened constraint;
3. no protected/native value/field;
4. no tool name/reference order;
5. no answer leakage;
6. unique/set wording matches cardinality;
7. reset context + instruction supply every Task literal.

The exact rendered string is immutable and used by witness and S3. Core path has
no paraphraser.

## 12. Public Responses episode runner

### 12.1 Acting loop

Witness is policy execution, not code generation. Host uses OpenAI Responses
function tools derived from ToolSpecs:

```python
while budget.remaining:
    response = model.respond(instruction, prior_public_items, tools)
    for call in response.tool_calls:
        observation = actor.invoke(call.name, call.arguments)
        journal.record(call, observation)
        feed(observation)
    if response.final_answer is not None:
        break
```

Host owns dispatch, schema validation, budgets, exact prior items, journal, usage
and final answer parsing.

### 12.2 Visibility

Policy receives only:

```text
canonical instruction
public reset observation/context
public docs/limitations
ToolSpecs/ToolObservations
answer schema
```

No GoalProgram/checker/semantics/native/protected data or clause-level failure
feedback is exposed.

### 12.3 Load-bearing provenance

Each argument leaf is classified:

```text
TaskLiteralRef
ResetObservationRef
ToolObservationRef at qualified schema pointer
ToolSchemaConstant
AgentChoice
```

`AgentChoice` is allowed only when it is not a target, answer or fixed Task
constraint and does not equal a protected-only binding. Free commit messages are
one example. Prose/error scraping is forbidden; `contract.*` provides no value.

### 12.4 Two fresh witnesses

TaskPack requires two successful runs on separate instances from the same
StartCase. Both use the exact instruction and same checker. IDs/routes may differ.

Store concrete traces, answers, provenance reports, before/after fact digests and
checker results. No WitnessRecipe/expression/removal-replay subsystem.

Bounded failure is `NoPublicWitness`, not logical impossibility.

## 13. Admission challenges

### 13.1 Layering

S1 proves atomic semantics physically. S2 proves concrete selector/composition/
instruction/answer behavior.

### 13.2 Challenge matrix

| Challenge | Construction | Expected |
| --- | --- | --- |
| witnesses #1/#2 | real public runs | satisfied |
| no-op | initial facts as terminal | failed |
| wrong/near-miss target | ineligible/alternate candidate + public attempt when reachable | failed |
| partial All | omit child result | failed |
| incomplete ForEach | omit selected key | failed |
| collateral | positive goal + extra unrelated public action when reachable | failed |
| wrong report | mutate atom/condition structured answer | failed |
| alternative route | independent successful differing action signature | satisfied |
| process violation | same terminal relation, prohibited process when reachable | failed |

Each is `passed`, `failed` or `not_applicable(reason)`. Crashing/unreachable
mutants do not improve evidence.

### 13.3 Checker mutation testing

Canonical mutations:

```text
drop All child
shrink ForEach set
change selector resolution
change If branch
ignore collateral
ignore answer/process field
```

Every applicable mutation must be killed. Survivor -> `CheckerDefect`.

### 13.4 Instruction defects

Two witness successes prove constructive recoverability for the witness policy.
Independent TaskAssessment measures broader recoverability. A Task is intrinsically
rejected only when causal evidence shows leakage, missing/extra constraints,
cardinality mismatch or repeatable alternate meaning inconsistent with checker.

## 14. Identities and projections

### 14.1 TaskDefinition

Binds semantic content:

```text
release/semantics IDs
StartCase
Blueprint + protected/public bindings
checker artifact
canonical instruction + answer schema
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

Excludes model trials, empirical difficulty and corpus policy.

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
Goal/selectors/bindings
checker/semantics digests
admission evidence
```

Witness traces remain protected audit evidence.

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

Difficulty is assessment-relative, not structural Task identity.

### 14.4 CorpusManifest

Binds selected TaskPack IDs, selected TaskAssessment IDs, policy, seed and
selection evidence. It may change for another target model/budget without
rewriting TaskPacks.

## 15. Structural diversity and selection

```python
@dataclass(frozen=True)
class TaskFingerprint:
    capability_ids: tuple[str, ...]
    workflow_ids: tuple[str, ...]
    composition_rule_ids: tuple[str, ...]
    goal_shape: str
    selector_operators: tuple[str, ...]
    relation_count: int
    public_binding_depth: int
    start_regimes: tuple[str, ...]
    answer_required: bool
    process_required: bool
```

Selection:

1. exact TaskDefinition/checker dedup;
2. structural grouping;
3. text-near-duplicate filtering inside groups;
4. capability/shape/start budgets;
5. separate TaskAssessment reliability/cost;
6. audit surplus/rejections.

Internal coverage is not complete Task-space coverage.

## 16. Direct S2 coordinator

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
    admitted, audits = [], []

    for start_case in release.trusted.start_cases(policy.seed, budget.start_cases):
        with prepared.open(new_instance_dir()) as session:
            reset_obs = session.actor.reset(start_case.reset_input)
            before = session.trusted.inspect()
            caps = session.trusted.capabilities()
            bindings = {
                cap.capability_id: session.trusted.enumerate_bindings(
                    cap.capability_id, before
                )
                for cap in caps
            }

        for blueprint in enumerate_blueprints(caps, bindings, policy):
            definition = compile_definition(
                release, start_case, reset_obs, before, bindings, blueprint
            )
            if isinstance(definition, Rejection):
                audits.append(definition.audit)
                continue

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

Actual code streams candidates/instances; pseudocode fixes ownership/order.

## 17. Package shape without premature fragmentation

```text
src/agent_env_foundry/
  existing modules
  preparation.py
  semantics.py
  qualification.py       # extend current independent route
  release.py
  publication.py

src/agent_task_foundry/
  models.py
  compiler.py
  runner.py
  admission.py
  corpus.py
  api.py
```

Split only after real ownership/test evidence. No plugins, graph runtime,
workflow engine, Registry or service topology.

## 18. Error ownership

```text
InfrastructureFailure
EnvironmentDefect
SemanticsDefect
UnsupportedCapability
RejectedBlueprint
CheckerDefect
InstructionDefect
NoPublicWitness
RejectedTaskPack
RejectedForCorpus
```

Every correction creates/revalidates affected identities. Actor change
invalidates semantics and all descendant Tasks.

## 19. Concrete walkthroughs

### 19.1 Ocean-container dispute

Qualified semantics:

```text
capability submit_timely_dispute
workflow invoice-dispute-management
facets carrier, charge_amount, deadline, eligibility
required matching submitted dispute
forbidden unrelated invoice/dispute changes
answer dispute_reference
```

S2 selects the unique maximum eligible invoice for a stated carrier, freezes the
checker, renders the exact instruction, executes two public witnesses and
rejects no-op, late/lower invoice, collateral and wrong-reference outcomes.
No database row ID/tool path enters the Task.

### 19.2 Filesystem/Git

Qualified semantics may expose one `repair_and_commit` capability or an explicit
CompositionRule joining `repair` and `commit` under repository-maintenance.

Checker freezes file/check/ref/object/collateral relations before instruction.
Different correct patches and public tool orders pass. No-op, wrong file, failing
tests, uncommitted worktree, unreachable commit, collateral edit and wrong
commit answer fail.

## 20. Validation and anti-overdesign gates

Mechanical tests:

- v2 digest/preparation/two-runtime separation;
- semantics no-mutation/no-actor-import;
- separate Codex workspace inputs;
- capability/condition/composition physical sensitivity;
- deterministic selector/Goal/checker/instruction;
- checker-before-instruction-before-model-call order;
- ToolSpec public schema-path validation;
- public/protected provenance and protected-guess rejection;
- two fresh witnesses;
- checker mutation kill/alternative-route acceptance;
- TaskDefinition/TaskPack/Assessment/Manifest identity separation;
- structural dedup/corpus selection.

Real evidence:

- regenerate SQLite and Git releases with the same frozen framework;
- meet PRD anti-demo floors;
- freeze code/prompts/contracts and run a held-out Need;
- run matched-budget baselines/downstream value tests.

No new semantic object, Agent role, protocol or package is added unless a real
SQLite/Git/held-out failure cannot be expressed by the current capability,
composition/condition, selector, four-node Goal, checker, instruction and public
trace contracts.

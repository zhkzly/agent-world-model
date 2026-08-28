# S2 Goal-First Task Foundry — Technical Design

## 1. Feasibility verdict

The redesigned S2 is implementable, but only after changing the S1 release
contract.

The following stronger claim is not implementable with trustworthy guarantees:

> Given only arbitrary tool descriptions, a reset function and opaque native
> state, automatically infer every meaningful Task, its setup and its verifier.

A successful trace can show that one sequence ran. It cannot by itself establish
why the achieved relation is a natural user goal, which changes are required or
allowed, which side effects are forbidden, or whether a different path should
also pass.

The implementable boundary is:

> S1 publishes independently qualified, parameterized taskable capability
> semantics for the executable world; S2 deterministically compiles those
> semantics into Task Blueprints, samples starts and bindings, freezes a checker,
> proves public solvability, renders the instruction and admits only challenged
> Tasks.

This boundary does not require human-written Task generators for every release.
It does require a separate semantic-authoring and qualification step during S1.
That step may use a coding model, but the Host owns execution, identity,
challenge generation and the final verdict.

## 2. Why the previous S2 is replaced

The previous proposal made Graph-based and Programmatic generation mandatory
Task sources. That design is rejected for five reasons.

1. **Action-chain-first semantics.** A connected or successful tool sequence is
   not necessarily one coherent user intent.
2. **Correlated self-validation.** A model-generated instruction, solution and
   verifier may share the same semantic error.
3. **Late truth construction.** Deriving the verifier from the reference run
   makes the path evidence influence the definition of success.
4. **Per-Task native-decoder duplication.** Generating a new unrestricted
   TruthExtractor for every Task repeats release-specific decoding and expands
   the failure surface.
5. **Mechanism becomes architecture.** Graph/random-walk/program synthesis are
   search strategies. Requiring both adds complexity without improving the
   semantic contract.

The redesign keeps the useful evidence principles—public-only action,
provenance, fresh replay, native verification and adversarial challenges—but
changes the order:

```text
qualified meaning
-> Blueprint
-> frozen checker
-> public solution
-> instruction
```

not:

```text
sampled tool path
-> instruction
-> verifier inferred from that path
```

## 3. End-to-end architecture

```text
S1 Research
  Need + evidence
  -> accepted Development Brief and Requirement IDs

S1 Environment Builder
  Brief
  -> executable environment project
  -> reset/tools/invoke/close
  -> real native state

S1 Semantic Author (independent of Builder thread)
  frozen Brief-derived expected relations
  + public environment surface
  + decode-only source/native access after freeze
  -> release-local SemanticsBundle candidate

S1 Semantic Qualification
  real public executions
  + independent native reads
  + physical near misses
  + start-space replay
  -> qualified taskable capability contracts

S1 Publication v2
  exact executable project
  + exact protected SemanticsBundle
  + public docs and schemas
  + qualification evidence/digests
  -> immutable EnvironmentRelease

S2 Release Admission
  exact release preparation/opening
  -> validated public and protected surfaces

S2 Blueprint Compiler
  qualified CapabilitySpecs
  + deterministic start/binding sampling
  + corpus policy
  -> parameterized GoalProgram / TaskBlueprint

S2 Checker Compiler
  GoalProgram + pre-execution facts/bindings
  -> frozen TaskChecker

S2 Public Planner
  public Task projection only
  -> executed reference trace
  -> provenance-closed WitnessRecipe
  -> fresh replay satisfying the frozen checker

S2 Instruction Renderer
  Blueprint public frame
  -> instruction
  -> leakage and semantic-integrity audit

S2 Admission
  atomic qualification evidence
  + composition challenges
  + alternative path
  + independent actor trials
  -> TaskPack or typed rejection

S2 Corpus Selector
  TaskPack fingerprints + costs + difficulty
  -> declared SFT/RL corpus
```

## 4. Trust and information boundaries

| Component | May see protected native facts | May mutate state | Semantic authority |
| --- | :---: | :---: | --- |
| S1 Environment Builder | yes, in its own workspace | builds environment | none over final qualification |
| S1 Semantic Author | yes, read-only after expected relations freeze | writes semantics workspace only | proposes capability semantics |
| S1 Qualification Host | yes, through independent readers | controlled public calls and disposable physical mutants | admits/rejects release semantics |
| S2 Blueprint Compiler | capability contracts and protected bindings | no | deterministic composition rules |
| S2 Checker Compiler | exact Blueprint and protected start facts | no | compiles already-qualified meaning |
| S2 Public Planner | no | public tools on isolated instance | proves one public route only |
| S2 Instruction Renderer | public Blueprint frame only | no | wording only |
| S2 Admission Host | yes | public calls on challenge instances | applies frozen checker and policy |
| Independent acting policy | no | public tools on its episode | none over Task truth |
| S3 trusted runtime | yes, checker inputs only | materializes and runs episode | executes frozen TaskPack semantics |

No model verdict can override a deterministic environment, semantic-qualification
or TaskChecker failure.

## 5. EnvironmentRelease v2

### 5.1 Release shape

The outer release remains one immutable artifact. A representative layout is:

```text
EnvironmentRelease/
├── release.json
├── payload-manifest.json
├── qualification.json
├── project/                    # actor environment
├── semantics/                  # protected release-local semantics package
│   ├── manifest.json
│   ├── schemas/
│   └── src/
├── dist/
├── docs/
└── licenses/
```

`release.json` binds at least:

```text
actor-project digest and entry point
protected-semantics digest and entry point
public Brief/docs/schema paths
qualification digest
release preparation metadata
```

The format is a clean v2 contract. The implementation does not add a v1/v2
compatibility loader.

### 5.2 Prepared release runtime

S1 adds one reusable consumer API:

```python
prepared = prepare_release(release_path, cache_root)
with prepared.open(instance_directory) as session:
    public = session.actor
    trusted = session.trusted
```

The host object is transport-neutral. Internally, one exact release executes in
an isolated interpreter/process prepared from its frozen dependencies. This
prevents imports from different generated packages colliding in a long-lived S2
or S3 process.

The actor projection exposes only:

```python
reset(start)
tools()
invoke(tool_name, arguments)
close()
```

The trusted projection exposes only the protected SemanticsBundle and immutable
runtime identity. S2 cannot import arbitrary environment business functions.

A custom network service, Registry, HTTP protocol or MCP server is unnecessary.
Process isolation is an implementation boundary behind the Python API.

## 6. Protected SemanticsBundle

The protected bundle is release-specific. It is not a universal normalized
world state and does not require different domains to share table or field
names.

```python
class SemanticsBundle(Protocol):
    def start_cases(
        self,
        seed: int,
        limit: int,
    ) -> tuple[StartCase, ...]: ...

    def inspect(
        self,
        instance_directory: Path,
    ) -> JSONValue: ...

    def capabilities(self) -> tuple[CapabilitySpec, ...]: ...

    def enumerate_bindings(
        self,
        capability_id: str,
        facts: JSONValue,
    ) -> tuple[BindingCandidate, ...]: ...

    def evaluate_atom(
        self,
        request: AtomEvaluationRequest,
    ) -> AtomEvaluation: ...
```

Every method has a current consumer:

- `start_cases` supplies reproducible Task starts;
- `inspect` supplies protected before/after facts;
- `capabilities` defines qualified user-facing Task atoms;
- `enumerate_bindings` finds concrete parameterized instances;
- `evaluate_atom` provides deterministic atomic truth for checker composition.

No generic snapshot restore, direct native write or unrestricted query interface
is added.

### 6.1 StartCase

```python
@dataclass(frozen=True)
class StartCase:
    case_id: str
    reset_input: JSONObject | None
    regime_tags: tuple[str, ...]
```

Requirements:

- deterministic from release digest, seed and limit;
- valid against `start_schema`;
- reset-only—no private or public setup program;
- sufficiently varied to exercise declared taskable capabilities and boundary
  regimes;
- replayed by S1 Qualification.

### 6.2 CapabilitySpec

```python
@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    requirement_ids: tuple[str, ...]
    actor_role: str
    task_kind: Literal["query", "state_change", "process"]
    intent_label: str
    binding_schema: JSONObject
    public_descriptor_schema: JSONObject
    facets: tuple[FacetSpec, ...]
    answer_schema: JSONObject | None
    read_scopes: tuple[str, ...]
    write_scopes: tuple[str, ...]
    supported_nodes: tuple[GoalNodeKind, ...]
    rendering: RenderingSpec
```

`read_scopes` and `write_scopes` are release-local symbolic labels used for
composition conflict checks and fingerprints. The framework never interprets a
label such as a database table or Git ref.

A CapabilitySpec must map to accepted Brief Requirements and a user-facing
intent. Internal maintenance helpers and accidental public tool combinations do
not automatically become capabilities.

### 6.3 FacetSpec

A facet is an instruction-safe, selector-safe property of a candidate binding.

```python
@dataclass(frozen=True)
class FacetSpec:
    name: str
    value_schema: JSONObject
    allowed_operators: tuple[
        Literal["eq", "neq", "lt", "lte", "gt", "gte", "min", "max"]
    ]
    public_label: str
    visibility: Literal["task_literal", "reset", "public_tool"]
```

S1 Qualification must show that a `public_tool` facet is actually recoverable
from public observations. Protected facts may compute the value, but the value
cannot be used as a hidden acting operand.

### 6.4 BindingCandidate

```python
@dataclass(frozen=True)
class BindingCandidate:
    semantic_key: str
    protected_binding: JSONObject
    public_descriptor: JSONObject
    facets: JSONObject
```

`semantic_key` aligns equivalent business referents across fresh starts. It is
not required to equal a native row ID, generated UUID, file inode or Git object
ID.

The public descriptor is the only binding material the Blueprint renderer or
public planner may receive. The protected binding is checker-only.

### 6.5 AtomEvaluation

```python
@dataclass(frozen=True)
class AtomEvaluation:
    initially_satisfied: bool
    goal_satisfied: bool
    required_effects_satisfied: bool
    collateral_ok: bool
    answer_ok: bool | None
    process_ok: bool | None
    fact_projection: JSONObject
    failures: tuple[EvaluationFailure, ...]
```

The atomic evaluator checks business relations, required effects, forbidden
collateral and answer/process obligations. It does not return a scalar reward.

## 7. S1 semantic authoring and qualification

### 7.1 Anti-circular authoring order

For each accepted user-facing Requirement:

```text
freeze expected actor, precondition, outcome, refusal and collateral relations
-> inspect public docs/tools and run public probes
-> only then inspect source/native layout for decoding
-> author release-local semantics code
-> Host executes and challenges it
```

The Semantic Author does not receive the Builder conversation, Builder tests or
S2 Task candidates.

### 7.2 Qualification obligations

For every taskable capability, S1 Qualification proves:

1. at least one StartCase contains an eligible binding;
2. `inspect` agrees with an independent native reader;
3. `enumerate_bindings` identifies the intended entity and public descriptor;
4. a real public success flips the intended atomic evaluation;
5. a no-op does not flip it;
6. wrong-entity and boundary near misses remain rejected;
7. prohibited collateral is detected;
8. required public facets are actually visible;
9. applicable business refusals preserve prohibited state;
10. fresh reset reproduces the same business predicates.

Physical near misses modify a disposable controlled copy or its package-owned
start data while preserving executable behavior. A marker-only or declaration-
only flip is not evidence.

### 7.3 Coverage outcome

Every core user-facing Brief Requirement receives one of:

```text
Taskable(capability IDs, evidence)
NotTaskable(reason, evidence)
Unsupported(reason)
```

Silent omission is invalid. S1 may still publish an environment with a disclosed
non-taskable Requirement only when the product policy permits it; S2 never
pretends that omitted capability exists.

## 8. GoalProgram: the bounded Task Blueprint IR

GoalProgram is deliberately small. It is not arbitrary Python and not a
universal business-rule language.

```python
type GoalProgram = (
    Atom
    | Select
    | If
    | All
    | ForEach
    | Report
)
```

### 8.1 Atom

```text
Atom(capability_id, binding_ref)
```

Requires one qualified atomic capability on one binding.

### 8.2 Select

```text
Select(candidate_capability, filters, optional rank, child)
```

Selects a binding using qualified public facets and applies the child goal to
that binding. The compiler rejects ties when the instruction implies a unique
target, or renders set-valued semantics when multiple targets are allowed.

### 8.3 If

```text
If(public_condition, then_goal, else_goal)
```

The condition must be grounded in actor-observable start/tool information and a
qualified facet or refusal code. A reference policy's accidental fallback does
not create a conditional Task.

### 8.4 All

```text
All(child_goals)
```

All children must be semantically coherent and compatible. The compiler checks
qualified read/write scopes and rejects unexplained cross-intent concatenation.

### 8.5 ForEach

```text
ForEach(selector, child_atom)
```

Applies one atomic outcome to the complete selected set. The checker rejects
partial completion and modifications outside that set.

### 8.6 Report

```text
Report(structured_expression)
```

Adds a deterministic structured final-answer requirement derived from qualified
facts or public execution results. It never exposes the answer in the Task.

### 8.7 Blueprint identity

```python
@dataclass(frozen=True)
class TaskBlueprint:
    release_id: str
    semantics_digest: str
    goal_program: GoalProgram
    public_frame: PublicInstructionFrame
    capability_evidence: tuple[str, ...]
    fingerprint_seed: JSONObject
```

A Blueprint is parameterized. A concrete TaskInstance additionally binds one
StartCase and one set of protected/public BindingCandidates.

## 9. Deterministic Blueprint synthesis

### 9.1 Candidate sources

S2 uses two proposal sources but one semantic authority:

```text
Need/Brief-backed capability algebra
execution and corpus observations used as search priorities
```

The second source may prioritize underrepresented facets, state regimes or
model-failure patterns. It cannot invent a new predicate outside qualified
capabilities.

### 9.2 Compilation rules

The Host enumerates bounded Blueprint candidates from:

```text
qualified capability
× supported GoalProgram node
× valid public facet operator
× compatible capability composition
× declared corpus policy
```

An LLM may propose or rank typed candidates to reduce search cost. Every field
must validate against the same deterministic compiler. Free-form LLM Task text
is not a Blueprint.

### 9.3 No accidental complexity

The compiler rejects:

- an `All` composition with no shared actor/intent relation;
- duplicated atoms that do not change the goal;
- an `If` whose branches have the same accepted outcome;
- selectors that are not publicly expressible;
- unique-selection Tasks with unresolved ties;
- Tasks already true at the start;
- a longer Blueprint whose removal test preserves identical semantics.

## 10. Start and binding instantiation

```python
@dataclass(frozen=True)
class StartRecipe:
    release_id: str
    start_case_id: str
    reset_input: JSONObject | None
```

Instantiation executes:

```text
fresh prepared instance
-> reset(StartCase.reset_input)
-> public reset observation
-> protected inspect
-> enumerate candidate bindings
-> bind Blueprint slots
-> compile/freeze TaskChecker
-> assert checker(initial, initial, empty_trace, no_answer) is false
```

No S2 setup call is hidden from the actor because S2 performs no setup calls at
all. World diversity belongs to the qualified S1 start space.

A binding is admitted only when every acting-time value is either:

- stated in the public instruction/reset context;
- a documented public constant;
- discoverable through public tools; or
- produced by an earlier successful public observation during execution.

## 11. Checker-before-witness construction

### 11.1 TaskChecker

```python
class TaskChecker(Protocol):
    def evaluate(
        self,
        before_facts: JSONValue,
        after_facts: JSONValue,
        public_trace: tuple[TraceEvent, ...],
        final_answer: JSONValue | None,
    ) -> TaskResult: ...
```

`TaskResult` is:

```text
satisfied
failed(reason codes and fact projection)
abstain(insufficient trusted evidence)
```

The checker is compiled from:

```text
GoalProgram
+ StartCase facts
+ protected binding set
+ qualified atomic evaluators
+ answer schema
+ explicit process predicates
```

Its serialized program/configuration and dependencies are frozen before the
public planner starts. Reference tool names, arguments, observations and final
answer are excluded from checker construction.

### 11.2 Composition semantics

- `Atom`: use its qualified atomic evaluation.
- `Select`: independently recompute the qualifying/selected binding set from
  protected start facts and assert the achieved binding matches it.
- `If`: evaluate the qualified condition and exactly the selected branch.
- `All`: require every child and union only the declared allowed scopes.
- `ForEach`: require all and only selected bindings to satisfy the child atom.
- `Report`: parse the declared JSON answer and resolve its values to checked
  facts/public results.

The checker does not compare the acting trace with the reference trace. Trace
predicates are used only when the Task explicitly constrains process.

## 12. Public-only planning and WitnessRecipe

### 12.1 Planner visibility

The reference planner receives exactly:

```text
natural-language instruction or canonical public frame
actor-visible reset observation
public environment docs/limitations
ToolSpec[]
ToolObservation stream
answer schema
```

It does not receive the SemanticsBundle, protected binding, GoalProgram,
TaskChecker, native state or an answer key.

### 12.2 Planner implementation

The first implementation uses one bounded tool-calling planner with real model
calls and host-owned trace capture. It may search, backtrack, branch, loop and
perform deterministic local computation.

There is no separate Graph product subsystem and no requirement to write a
free-form Python program. Later search optimizers can share the same planner
interface when evidence shows a need.

### 12.3 Provenance closure

After an execution satisfies the frozen checker, the Host compiles the concrete
trace into a restricted recipe:

```python
type ValueExpr = (
    TaskSlotRef
    | ResetObservationRef
    | PublicConstant
    | ToolResultRef
    | DeterministicSelect
)

@dataclass(frozen=True)
class WitnessStep:
    tool_name: str
    arguments: dict[str, ValueExpr]

@dataclass(frozen=True)
class WitnessRecipe:
    steps: tuple[WitnessStep, ...]
    answer_expression: ValueExpr | JSONObject | None
```

Every literal must have a public origin. Prose mining, protected IDs and error-
message scraping are forbidden.

### 12.4 Fresh replay

A new equivalent StartCase materialization resolves all dynamic references from
new observations and replays the recipe. The already-frozen checker must pass.
Incidental identifiers may differ; semantic keys and business predicates must
agree.

Removal replay deletes each step in turn. A step that supplies no later value,
changes no required outcome and satisfies no explicit process rule is removed.

## 13. Instruction rendering and auditing

The canonical renderer consumes only `PublicInstructionFrame`, qualified public
labels and the structured GoalProgram shape. It does not see the witness.

```python
@dataclass(frozen=True)
class PublicInstructionFrame:
    actor_label: str
    intent_label: str
    public_constraints: JSONObject
    selector_description: JSONObject | None
    conditional_description: JSONObject | None
    answer_requirement: JSONObject | None
```

Core Tasks use deterministic rendering. Optional LLM paraphrases are separate
surface variants and are accepted only when a structured parser recovers the
same frame and an independent actor trial shows no new interpretation.

Audits reject:

- values present only in protected bindings;
- database/native implementation field names;
- tool names or required reference order;
- omitted or strengthened constraints;
- answer or unique target leakage;
- pronouns or descriptions that match multiple bindings contrary to checker
  semantics.

## 14. Adversarial admission

### 14.1 Layered responsibility

S1 physically validates each atomic capability and its native evaluator. S2
validates Blueprint composition, binding, instruction, answer and process
semantics. This avoids regenerating a full native verifier for every Task while
still testing the complete TaskPack.

### 14.2 Required challenge matrix

| Challenge | Expected result |
| --- | --- |
| positive reference | satisfied |
| fresh reference replay | satisfied |
| no-op | failed |
| wrong binding/target | failed |
| selector boundary near miss | failed |
| one omitted child of `All` | failed |
| incomplete `ForEach` set | failed |
| required goal plus collateral action | failed |
| wrong/stale/malformed answer | failed |
| valid alternative public route | satisfied |
| same terminal state with process violation | failed for process Task |

Composition-level fact mutations are deterministic and generated from the typed
GoalProgram. Applicable physical challenges additionally run public tool calls
on disposable starts. A challenge counts only when its targeted condition is
reachable and the rest of the evidence remains valid.

### 14.3 Actor trials

After logical admission, an independent acting policy runs the final public Task
projection. Trials diagnose:

```text
wording recoverability
public observability
practical feasibility
checker false negatives
interaction/token cost
empirical difficulty and reliability
```

Constructive replay proves existence. Actor success rate does not redefine
truth. Systematic independent failure blocks corpus admission rather than being
renamed “very hard.”

The actor loop is a reusable library consumed by both S2 trials and later S3; S2
does not create a second incompatible rollout engine.

## 15. TaskPack

```python
@dataclass(frozen=True)
class TaskPack:
    taskpack_id: str
    release_id: str
    semantics_digest: str
    start_recipe: StartRecipe
    goal_program: GoalProgram
    instruction: str
    public_reset_context: JSONValue
    answer_schema: JSONObject | None
    checker_artifact: ArtifactRef
    protected_bindings: tuple[BindingCandidate, ...]
    witness_recipe: WitnessRecipe
    solvability_evidence: EvidenceRef
    challenge_evidence: EvidenceRef
    trial_evidence: EvidenceRef
    fingerprint: TaskFingerprint
    quality_report: TaskQualityReport
```

The identity hashes canonical component bytes/digests without embedding itself
inside the preimage.

Public projection:

```text
TaskPack/release IDs
instruction
public reset context
public process constraints
answer schema
public limitations
```

Protected S3 projection:

```text
StartRecipe
GoalProgram and bindings
frozen checker
semantics references
challenge evidence
```

The reference witness may remain protected audit evidence; an acting policy
never receives it.

## 16. Corpus selection

### 16.1 Fingerprint

```python
@dataclass(frozen=True)
class TaskFingerprint:
    capability_signature: tuple[str, ...]
    goal_ast_shape: str
    selector_operators: tuple[str, ...]
    relation_count: int
    public_binding_depth: int
    state_regimes: tuple[str, ...]
    answer_required: bool
    process_required: bool
    witness_control_flow: str
    empirical_difficulty: str
```

Parameter substitutions and paraphrases do not count as new structural cells.

### 16.2 Selection policy

1. remove exact Blueprint/checker duplicates;
2. group semantic near duplicates by fingerprint and public frame;
3. enforce declared capability, AST, state-regime and difficulty budgets;
4. select the highest-quality/reliability candidates within each group;
5. record rejected surplus instead of inflating corpus size.

Quality-diversity or novelty search may implement step 4 later. The architecture
requires only the fingerprint and explicit policy.

### 16.3 External value test

Corpus diversity is a hypothesis until matched-budget training/evaluation shows
better held-out generalization than simpler sampling. S2 reports internal
structure and downstream utility separately.

## 17. Concrete walkthrough: ocean-container dispute

Assume S1 qualifies:

```text
capability: submit a timely dispute for one eligible invoice
facets: carrier, charge amount, due date, dispute eligibility
required effect: dispute relation created with submitted status
forbidden collateral: unrelated invoice/dispute relations unchanged
answer: dispute reference when requested
```

S2 builds:

```text
Select eligible current-user invoices
  filter carrier == requested carrier
  rank max(charge amount)
  Atom submit_dispute(selected)
  Report dispute_reference
```

Execution:

```text
start_cases chooses a world containing multiple invoices and one unique maximum
-> inspect/enumerate binds protected invoice identities and public descriptors
-> checker freezes the selected semantic key and required/collateral relations
-> public planner uses world_snapshot and submit_dispute
-> trace passes checker
-> WitnessRecipe binds invoice reference from successful public observation
-> fresh replay resolves a new public value and passes the same predicates
-> instruction renderer states user intent and public constraints, not tool path
```

Challenges include no-op, late invoice, lower-amount eligible invoice, unrelated
invoice mutation, missing dispute row, stale reported reference and another valid
public search route.

## 18. Concrete walkthrough: filesystem/Git

Assume S1 qualifies:

```text
capability: modify repository content so declared checks pass and create a commit
facets: public file/module label, failing check, branch
required effects: intended file relation changed, checks pass, reachable commit
forbidden collateral: protected metadata/unrelated files unchanged
answer: resulting commit identifier when requested
```

S2 builds an atomic or `All` Blueprint depending on whether edit-and-commit is one
qualified capability or two compatible capabilities.

The checker freezes before planning and validates file bytes/modes, check result,
Git index/ref/object relations and collateral scopes. The public planner may use
discovery, read, edit, check, diff and commit tools. A different correct source
edit and a different valid tool ordering pass if they satisfy the same frozen
relations. No Task requires reproducing the reference patch.

Challenges include no-op, editing the wrong file, tests still failing, an
uncommitted worktree, a commit not reachable from the target ref, protected
metadata mutation, wrong commit answer and an alternative valid code change.

## 19. Failure and abstention model

```text
InfrastructureFailure
  provider/dependency/timeout/process failure with identical semantic identities

ReleaseDefect
  reproducible actor or protected-semantics contract violation in published bytes

UnsupportedCapability
  no qualified deterministic semantics or public observability

RejectedBlueprint
  invalid composition, ambiguity, initial satisfaction or hidden operand

NoPublicWitness
  bounded planner failed; does not prove mathematical impossibility

CheckerDefect
  challenge false acceptance/rejection or unstable facts

InstructionDefect
  leakage, mismatch or independent-agent alternate interpretation

RejectedForCorpus
  logically valid Task that misses declared reliability/cost/distribution policy
```

Retries never change Task or release semantics. A correction creates a new
component identity and reruns all affected gates.

## 20. Deletion list

The implementation must not carry forward these old product objects merely for
compatibility:

- mandatory Graph Task lane;
- mandatory Programmatic Task lane;
- persistent universal tool graph and weak/independent edge taxonomy;
- random-walk chain length as difficulty;
- per-Task unrestricted generated TruthExtractor plus separate generated
  OutcomeVerifier;
- hidden ordered public setup program in StartRecipe;
- duplicate StartRecord fields already derivable from frozen evidence;
- persistent `QuarantinedCandidate` lifecycle;
- LLM Judge as final Task reward;
- universal normalized State IR or generic snapshot restoration;
- custom Registry, mutable `latest`, MCP/HTTP semantics or provider call IDs;
- demo/MVP mode, canned Task fixtures or domain-specific framework branches.

## 21. Code ownership and package shape

A direct package split keeps S1 and S2 ownership visible without introducing a
workflow engine:

```text
src/agent_env_foundry/
  existing S1 code
  preparation.py
  semantics_contract.py
  semantic_qualification.py

src/agent_task_foundry/
  models.py
  release.py
  blueprint.py
  checker.py
  planner.py
  instruction.py
  admission.py
  corpus.py
  api.py
```

The implementation remains one imperative coordinator per stage. No graph
runtime, plugin framework, service mesh or generalized scheduler is introduced.

## 22. Validation strategy

### Mechanical tests

- canonical identity and digest binding;
- schema validation and public/protected projection separation;
- GoalProgram compilation and rejection rules;
- checker-before-witness artifact ordering;
- provenance closure and dynamic replay;
- instruction round-trip/leakage checks;
- mutation/challenge sensitivity;
- corpus deduplication and deterministic selection.

### Real cross-domain evidence

The existing SQLite-backed and filesystem/Git Needs are regenerated under the
new S1 v2 contract. Both must traverse the exact same framework code and all
applicable S2 stages.

### Held-out transfer

After code, prompts and capability protocol freeze, an independently selected
Need must produce:

```text
qualified EnvironmentRelease v2
-> taskable capabilities
-> admitted Tasks
-> S3-shaped recreation and verification
```

without a framework commit adding domain labels, field names, evaluators or Task
templates.

### Matched-budget baselines

Compare:

1. LLM writes Task directly from docs/tools;
2. successful public trajectory is abstracted into a Task;
3. previous Graph/Programmatic proposal;
4. new qualified-capability GoalProgram compiler;
5. human-authored Task/checker sample as a quality reference, not a scalable
   production path.

Report Task yield, public replay, checker mutation kill rate, false acceptance,
instruction defects, structural fingerprints, actor success/reliability,
interaction cost and held-out downstream performance.

## 23. Design restraint

This design adds only two new semantic layers:

```text
S1 qualified taskable capability atom
S2 bounded GoalProgram composition
```

They are necessary because raw execution does not define user intent or a
verifier. Everything else is an execution, packaging or evidence mechanism with
a named consumer.

No additional abstraction should enter implementation unless a real failing
cross-domain or held-out case demonstrates that these two layers cannot express
the required behavior.

# S2 Goal-First Task Foundry

## Goal

Build the complete S2 stage that consumes a qualified executable world and
produces release-bound Agent Tasks that are publicly solvable, deterministically
verifiable, well-posed, non-trivial, reproducible and Need-anchored. S2 also
selects structurally diverse, low-redundancy corpora and records model-relative
difficulty/cost without making those measurements part of Task truth.

The old Graph/Programmatic-first proposal is superseded. Backward compatibility
with the previous S1/S2 proposal is not required.

## Product outcome

```text
natural-language Need
-> S1 executable actor environment
-> independently qualified release-local TaskSemantics
-> immutable EnvironmentRelease v2
-> S2 deterministic TaskBlueprint generation
-> freeze TaskChecker
-> render/audit final canonical instruction
-> public Agent solves that exact instruction on fresh real environments
-> checker/instruction challenges
-> TaskPack
-> separate TaskAssessment
-> CorpusManifest
```

A successful command, green unit suite, one happy path, hand-picked Task, demo,
mock or manually tailored framework branch is not S2 completion.

## Feasibility boundary

S2 does not claim that arbitrary tool descriptions and opaque state are enough to
recover every meaningful Task and verifier. Automatic synthesis is supported
only for S1 v2 releases that publish and independently qualify:

1. isolated deterministic `reset(start)` worlds;
2. structured public tools and observations;
3. a protected read-only semantic state inspector;
4. parameterized user-facing capability contracts anchored to accepted Brief
   Requirements/workflows;
5. deterministic atomic outcome, collateral, answer and optional process checks;
6. a deterministic generator of valid reset inputs with meaningful variation.

A world that cannot expose deterministic task truth under this contract is
`Unsupported`. S2 cannot replace missing semantics with an LLM Judge.

## Good Task contract

### Intrinsic Task qualities

Every admitted Task must be:

1. **Publicly solvable.** The exact final instruction is solved successfully on
   at least two fresh equivalent instances using only actor-visible context,
   ToolSpecs, public ToolObservations and deterministic local reasoning.
2. **Reliably verifiable.** Its frozen checker rejects applicable no-op, wrong
   target, boundary near miss, partial completion, collateral damage and
   wrong/stale answer cases, while accepting a genuinely valid alternative route.
3. **Well-posed.** Every material constraint is explicit; protected IDs, native
   fields, tool names, reference order and ground-truth answers are absent.
4. **Non-trivial.** The checker is false at the initial state. Query/report Tasks
   do not receive their answer directly in the instruction or reset observation.
5. **Reproducible.** Repeating the same release and StartCase reconstructs the
   same business predicates even when incidental IDs or bytes differ.
6. **Need-anchored and natural.** Every atomic capability maps to accepted Brief
   Requirements. Cross-capability composition requires a qualified shared
   workflow ID; accidental tool connectivity is insufficient.
7. **Path-open.** Outcome Tasks are checked by state/answer/process truth, not by
   equality with the reference trace.
8. **Training-targeted.** The Task targets named qualified Agent capabilities.
   Actual difficulty and learning value are measured separately.

### Corpus qualities

A selected corpus must additionally be:

- structurally diverse across Goal shape, selector operators, capability/workflow,
  state regime, public binding depth and answer/process requirements;
- deduplicated at TaskBlueprint/checker semantics before text similarity;
- balanced for its declared SFT or RL use;
- evaluated by matched-budget held-out performance rather than internal coverage
  claims.

Parameter substitution and paraphrasing do not create new Task structures.

## Exact execution ownership

### Deterministic framework Python

Framework code owns:

- release v2 parsing, preparation, process isolation and identities;
- public/protected projection separation;
- TaskSemantics schema/runtime validation;
- deterministic StartCase iteration and TaskBlueprint enumeration;
- GoalProgram and TaskChecker compilation/execution;
- canonical instruction rendering and leakage/coverage audits;
- public tool dispatch, trace capture and argument-provenance validation;
- fresh-run admission, challenge verdicts, TaskPack identities;
- TaskAssessment storage, semantic deduplication and corpus selection.

These responsibilities cannot exist only in prompts.

### Python Codex SDK

Codex SDK is used only for persistent release-local code authoring:

1. **Environment Builder:** writes the actor environment project, native storage,
   start schema/data, tools, docs and diagnostic tests.
2. **Independent Semantics Author:** after Host-frozen expected relations, writes
   the protected TaskSemantics package that decodes native state and implements
   capability/binding/evaluation contracts.

Codex outputs are proposals. Host code owns manifests, execution, native reads,
physical negatives, repair feedback and final release verdict.

### OpenAI Responses tool-calling Agent

A Host-owned Responses loop is used for:

- constructive public witness search after final instruction freeze;
- later independent TaskAssessment trials.

It sees only the exact instruction, public reset context, docs/limitations,
ToolSpecs and ToolObservations. It never receives TaskSemantics, GoalProgram,
checker, protected binding, native state or answer key.

The core implementation has no LLM paraphraser. Adding a paraphrase later creates
another instruction variant that repeats public solving and admission.

## Required S1 v2 handoff

### Public actor surface

```python
reset(start: JSONObject | None) -> JSONValue
tools() -> tuple[ToolSpec, ...]
invoke(tool_name: str, arguments: JSONObject) -> ToolObservation
close() -> None
```

### Protected TaskSemantics surface

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

`evaluate_condition` is required only when a release declares conditional Tasks.
The protected package is release-specific, unavailable to the acting Agent and
independently qualified against native state. It is not a universal State IR.

### StartCase

```python
@dataclass(frozen=True)
class StartCase:
    case_id: str
    reset_input: JSONObject | None
    regime_tags: tuple[str, ...]
```

StartCases are deterministic from release identity, seed and limit; valid against
the public start schema; reset-only; and replayed during S1 Qualification.

### CapabilitySpec

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

`workflow_ids`, scopes and supported kinds are release-local symbolic contracts.
The framework compares them but never interprets domain labels.

### BindingCandidate

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

The public descriptor/facets are the only binding material available to the
instruction renderer or public Agent. The protected binding is checker-only.
Ineligible/near-miss candidates support challenge construction.

### ConditionSpec and answer fields

A `ConditionSpec` names a qualified condition, public wording and how the actor
can observe it (`reset` or `public_tool`). S1 Qualification proves that
observability. An accidental refusal in one trace cannot become an `If` condition.

An `AnswerFieldSpec` names a structured field, schema and public label whose value
is returned by atomic evaluation only after real execution.

### Prepared release runtime

S1 provides:

```python
prepared = prepare_release(release_path, cache_root)
with prepared.open(instance_directory) as session:
    actor = session.actor
    trusted = session.trusted
```

Each prepared release runs in an isolated interpreter/process built from exact
locked bytes. S2/S3 do not depend on a development checkout or same-process import
cache behavior. The implementation reuses the existing subprocess/journal
pattern; it does not introduce a Registry, network service, HTTP or MCP protocol.

## S2 semantic objects

### SelectorSpec

A selector binds one public/protected `BindingCandidate` slot through qualified
facets:

```text
filters: eq/neq/lt/lte/gt/gte
optional rank: min/max
cardinality: exactly_one | any_one | all
```

Unique selection rejects unresolved ties. Set-valued semantics are rendered
explicitly.

### Bounded GoalProgram

The core AST has four goal nodes:

```text
AtomGoal      one qualified capability applied to one binding slot
AllGoal       all compatible child goals
IfGoal        one qualified public condition selects exactly one branch
ForEachGoal   one atomic capability applied to the complete selected set
```

Selection and reporting are TaskBlueprint attributes, not standalone AST nodes.
This avoids unnecessary compiler/interpreter nodes.

```python
@dataclass(frozen=True)
class TaskBlueprint:
    selectors: tuple[SelectorSpec, ...]
    goal: GoalProgram
    report: ReportSpec | None
```

`ReportSpec` references only declared `AnswerFieldSpec` values from checked atoms.
Goal nesting depth, child count and selector count are bounded by corpus policy.

### TaskDefinition, TaskPack, TaskAssessment and CorpusManifest

```text
TaskDefinition
  exact release/semantics IDs
  StartCase
  selectors/GoalProgram/report
  protected/public bindings
  frozen checker
  final canonical instruction and answer schema

TaskPack
  TaskDefinition
  two fresh public witness traces + provenance reports
  deterministic challenge/admission evidence

TaskAssessment
  TaskPack ID
  model/policy/runner/prompt identities
  pass/failure labels, calls, tokens, latency and empirical difficulty

CorpusManifest
  selected TaskPack IDs
  selected TaskAssessment IDs
  corpus policy and deterministic selection evidence
```

Changing model trials does not rewrite TaskDefinition or TaskPack semantics.
Systematic actor failure excludes a TaskPack from a corpus unless causal analysis
shows an actual wording/observability/checker defect.

## Requirements

### R1. Exact identity and trust separation

- Every object binds one exact release and TaskSemantics digest.
- Acting projections cannot deserialize trusted methods, native state, protected
  bindings, checker or admission evidence.
- Changing release, semantics, start, Blueprint, checker, instruction or answer
  contract creates a new TaskDefinition identity.

### R2. Qualified capabilities are the only Task truth source

- Tool graphs, successful traces and model consensus cannot invent predicates.
- Every Taskable capability maps to accepted Requirement IDs and discriminating
  S1 physical qualification.
- Missing semantics return to S1 and require a new release; S2 cannot patch them.

### R3. Deterministic Blueprint generation

The Host enumerates candidates from:

```text
qualified CapabilitySpecs
× StartCases/BindingCandidates
× allowed selector operators
× supported Goal kinds
× shared workflow IDs and compatible scopes
× corpus policy
```

- `AllGoal` across different capabilities requires a shared qualified workflow
  ID and compatible scopes.
- `IfGoal` references only a qualified `ConditionSpec`.
- `ForEachGoal` is allowed only when the capability declares that kind.
- Redundant atoms, vacuous branches, hidden selectors and already-satisfied goals
  are rejected.
- No LLM is required to generate Blueprints.

### R4. Native-backed instantiation

For each StartCase:

1. reset a fresh isolated instance;
2. capture public reset observation and protected facts;
3. enumerate eligible and near-miss bindings;
4. instantiate selectors/GoalProgram;
5. compile/freeze TaskChecker;
6. prove the initial checker is false and selection/cardinality is unambiguous.

Protected values may select/verify a Task but cannot become public arguments.

### R5. Checker-before-instruction-before-witness

The non-negotiable order is:

```text
Blueprint + start facts/bindings
-> compile and digest-freeze TaskChecker
-> render and audit final canonical instruction
-> public witness Agent receives exactly that instruction
```

The reference trace, planner reasoning and returned answer are never checker or
instruction inputs. The checker evaluates before/after facts, declared trace
predicates and parsed structured answer without reference-path equality.

### R6. Canonical instruction integrity

- Rendering uses release-qualified intent/facet/condition/answer labels and Host
  grammar; it never sees a witness trace.
- Mechanical audits prove every public slot is represented exactly once, reject
  omitted/strengthened constraints, and reject tool/native/protected/answer/path
  leakage.
- The exact rendered string is the Task instruction used for witness search and
  later S3 execution.

### R7. Public constructive solvability

- One Host-owned Responses tool loop receives the exact final instruction and
  public actor surface only.
- A witness run counts only when real execution satisfies the frozen checker.
- The Host validates each tool-argument leaf against a typed Task slot, reset
  observation leaf, ToolSpec enum/const or earlier successful ToolObservation
  leaf. Prose/error scraping and protected literals are forbidden.
- The same Task is solved successfully on at least two fresh equivalent starts.
  The two concrete traces may use different dynamic IDs and routes.
- The TaskPack stores actual traces and provenance reports. No custom
  `WitnessRecipe`/value-expression DSL or removal-replay subsystem is required.
- Bounded witness failure returns `NoPublicWitness`; it is not proof of logical
  impossibility.

### R8. Adversarial admission

S1 physical qualification establishes atomic inspector/evaluator sensitivity.
S2 additionally runs applicable concrete/composition challenges:

- no-op;
- wrong target or ineligible/near-miss binding;
- one omitted `AllGoal` child;
- incomplete `ForEachGoal` set;
- correct target plus collateral public action;
- malformed/wrong/stale answer;
- valid alternative route;
- same terminal result with a declared process violation.

Checker-spec mutations (drop child, ignore collateral, ignore answer, change
selector) must be killed by the challenge suite. Crashing or unreachable mutants
do not count. Non-applicable categories carry a typed reason.

### R9. TaskAssessment and training utility

- Independent actor trials reuse the same neutral Responses episode runner but
  use an independently configured model/policy lineage.
- Assessments record reliability, failure attribution and interaction cost.
- Assessment never changes checker truth or TaskPack identity.
- Matched-budget downstream evaluation is the final evidence of training value.

### R10. Corpus selection

- Structural fingerprint excludes empirical difficulty and model identity.
- Fingerprint includes capability/workflow IDs, Goal shape, selector operators,
  relation count, public binding depth, start regimes and answer/process flags.
- Exact Blueprint/checker duplicates are removed before text similarity.
- Corpus policy combines structure with separate TaskAssessment evidence.
- Internal coverage is never reported as complete Task-space coverage.

### R11. Fail closed

Typed non-success outcomes include:

```text
InfrastructureFailure
ReleaseDefect
UnsupportedCapability
RejectedBlueprint
CheckerDefect
InstructionDefect
NoPublicWitness
RejectedTaskPack
RejectedForCorpus
```

No LLM Judge, hidden setup, native patch, compatibility reader, hard-coded domain
checker or canned Task may convert failure into admission.

## Acceptance criteria

### Code and trust gates

- [ ] EnvironmentRelease v2 binds actor and TaskSemantics packages, exact digests,
  start schemas and public preparation/open metadata.
- [ ] Environment Builder and Semantics Author use separate Codex SDK workspaces
  and cannot see each other's conversations/tests.
- [ ] Host framework, not prompts, owns all deterministic compilation, execution,
  identity and verdict paths.
- [ ] Acting/witness/assessment Agents cannot access trusted projections.
- [ ] Checker digest is frozen before final instruction and witness model calls.
- [ ] No admitted tool argument lacks public provenance.
- [ ] Every applicable checker mutation/challenge is killed, with no material
  false acceptance and no alternative-route false rejection.

### Anti-demo real-release floors

For each of the two contrasting conformance releases:

- [ ] at least 20 admitted TaskPacks after semantic deduplication;
- [ ] at least 4 distinct canonical Goal/selector structure signatures;
- [ ] at least 2 qualified StartCase regimes;
- [ ] every core `Taskable` capability yields at least one TaskPack or a new
  evidence-backed `UnsupportedCapability` disposition;
- [ ] exact released bytes pass cold S3-shaped recreation.

Parameter-only instances and paraphrases cannot satisfy structure floors.

After framework/code/prompt freeze, one independently selected held-out Need must
produce without framework domain edits:

- [ ] at least 10 admitted TaskPacks;
- [ ] at least 3 distinct canonical structure signatures;
- [ ] at least 2 taskable capabilities or an explicit method-falsifying result;
- [ ] complete public solvability, checker, leakage and cold recreation evidence.

### Research/value gates

- [ ] Matched-budget baselines compare LLM-only Task writing, trajectory-first
  abstraction, the old Graph/Programmatic proposal and the new compiler.
- [ ] Report Task yield, witness/fresh success, hidden-operand rejection,
  checker mutation kill/false acceptance, instruction defects, structural
  redundancy, cost and held-out downstream performance.
- [ ] Fixture-only tests never authorize semantic completion.

## Fatal rejection criteria

The method must be reconsidered rather than cosmetically patched if:

- held-out releases require framework domain names/field rules;
- TaskSemantics cannot achieve discriminating physical-negative sensitivity
  without manual Task-specific repair;
- public solvability depends on protected values;
- checker false acceptance remains material for wrong-target/collateral cases;
- Task yield remains below preregistered floors despite complete actor surfaces;
- structural diversity gives no matched-budget held-out benefit over simpler
  baselines;
- correlated environment/semantics errors repeatedly survive independent S1
  Qualification.

## Out of scope

- compatibility with environment-package v1 or previous S2 artifacts;
- subjective Tasks without deterministic state/answer/process evidence;
- custom Registry/service/MCP/HTTP semantics;
- arbitrary LLM-authored verifier Python;
- hidden setup calls or generic snapshot restore;
- S3 trajectory persistence/reward mapping and S4 optimizer implementation;
- claims of universal Task-space coverage.

## Planning status

This document is implementation authority only after the user approves the
coherent PRD/design/implementation package and the task is activated. The user
has explicitly waived the `plan-document-write` Patrol for this planning update.

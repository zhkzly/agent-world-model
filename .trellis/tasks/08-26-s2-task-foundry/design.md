# S2 Goal-First Task Foundry — Technical Design

## 1. Causal architecture

```text
BuilderProjection
-> actor project
-> PublicSurfaceManifest
-> Expected TaskSemantics
-> TaskSemantics project + Native Auditor project
-> positive capability qualification
-> Qualification receipt
-> EnvironmentRelease
-> cold preparation
-> Goal compiler
-> public witnesses + minimal negatives
-> TaskPack
-> assessment/corpus
```

Every arrow has one owner. Later layers may consume earlier evidence but do not
reimplement the same proof.

## 2. Visibility

| Participant | Sees | Does not see |
|---|---|---|
| Environment Builder | BuilderProjection, environment contract | Tasks, checker, reward |
| Expected Semantics turn | Need relations, public schemas/ToolSpecs | actor source, native state |
| TaskSemantics Author | expected meaning, public surface, read-only actor view | Native Auditor source |
| Native Auditor Author | expected meaning, public surface, read-only actor view | TaskSemantics source |
| Public witness Agent | instruction, reset observation, ToolSpecs/results, answer schema | protected bindings/state/checker |

## 3. Core and release identity

The pre-publication Core binds:

```text
expected semantics digest
actor project digest/factory
TaskSemantics project digest/factory
Native Auditor project digest/factory
PublicSurfaceManifest digest
```

Qualification evidence and receipt bind the Core. Publication copies exact
bytes, writes canonical manifests, then derives the final Release ID. There is
no provisional release or hash fixed point.

## 4. Public surface

The release exposes:

```python
reset(start: JSONObject | None) -> JSONValue
tools() -> tuple[ToolSpec, ...]
invoke(tool_name: str, arguments: JSONObject) -> ToolObservation
close() -> None
```

ToolObservation is exactly:

```text
success: {ok: true,  data: <output_schema>, error: null}
failure: {ok: false, data: null,            error: {code,message,details?}}
```

## 5. TaskSemantics

TaskSemantics provides StartCases, capability/binding enumeration, protected
inspection, Atom evaluation, and condition evaluation. It owns:

- required semantic effects;
- collateral rules;
- required public process;
- final-answer truth and report values.

It must not write native state.

## 6. Native Auditor

The independent auditor reads before/after native instances and the public
descriptor/trace. It returns only native effects and collateral axes. It exists
to challenge actor/TaskSemantics self-agreement without duplicating public
answer or process logic.

Framework compares:

```text
TaskSemantics.required_effects_ok == NativeAudit.required_effects_ok
TaskSemantics.collateral_ok       == NativeAudit.collateral_ok
```

No other axis is cross-reader authority.

## 7. Answer source validation

Static validation resolves every source against sealed schemas. Physical
validation then resolves it against the representative execution:

```text
source declaration
-> reset/descriptor/trace occurrence
-> exact JSON value
-> TaskSemantics.report_values[field]
-> submitted final answer
```

Null is allowed only when the field schema allows it and no applicable source
occurrence exists. Qualification evidence records the reset observation and
matching occurrences.

## 8. S1 qualification algorithm

```text
for capability in catalog:
    choose first StartCase with one eligible binding
    run one public qualification episode
    evaluate TaskSemantics
    run independent native audit
    compare native effects/collateral
    validate AnswerField source occurrences
    validate task_kind against before/after semantic state
    seal positive case
require every capability represented
```

S1 does not run task-specific counterexamples. Those depend on a frozen Task,
not merely a capability.

## 9. Publication and preparation

Publication validates exact project identities, receipt digests, positive case
coverage, schema/catalog closure, and copied bytes. Cold preparation:

- verifies descriptor/payload/receipt digests;
- installs exact actor and TaskSemantics projects;
- checks live ToolSpecs, capability catalog, and StartCases equal sealed values;
- opens a real Consumer session.

It does not replay the entire historical qualification matrix on every open.

## 10. Atom compilation and admission

```text
release + StartCase + binding
-> checker preimage/digest
-> final answer schema
-> instruction/digest
-> Task
-> two fresh public witnesses
-> no-op
-> wrong target, if another Task exists
-> wrong answer, if schema permits
-> AtomTaskPack
```

Only one answer schema is compiled per capability/binding. Answer-field
singletons are not Task structures.

## 11. ForEach

ForEach freezes the complete eligible semantic-key set. Admission requires:

- two fresh witnesses satisfying every member;
- no-op rejects every member;
- one representative omitted member fails while retained members pass.

Reverse-order replay, every-member omissions, AgentChoice perturbations,
collateral manufacture, and per-Task result mutations belong to optional paper
robustness experiments.

## 12. If

An If Task freezes one qualified condition and the condition-selected Atom
branch. Each branch keeps its own necessary answer schema. Admission requires
two fresh executions where:

- the public condition still selects the frozen branch;
- the selected branch checker passes.

The production TaskPack does not run an artificial flipped-branch mutant.

## 13. All

All is allowed only by an explicit CompositionRule. It freezes all required
children and uses the same minimal pattern as ForEach: two witnesses, no-op,
and one representative missing child.

## 14. TaskPack, assessment, corpus

TaskPack contains immutable Task truth and admission evidence. TaskAssessment
contains independent success rate, cost, and difficulty. CorpusManifest selects
TaskPacks without rewriting either Task truth or assessment.

Corpus counts and structure distributions are experiment outputs, not product
identity or release admission fields.

## 15. Error ownership

```text
EnvironmentDefect       actor/public/native behavior wrong
SemanticsDefect         TaskSemantics effects/process/answer wrong
NativeAuditDefect       independent native effects/collateral wrong
InstructionDefect       public wording/source contract wrong
CheckerDefect           applicable Task negative is accepted
NoPublicWitness         bounded public policy cannot solve Task
InfrastructureFailure   provider/dependency/process failure
RejectedBlueprint       deterministic Task construction invalid
RejectedForCorpus       valid Task excluded by experiment policy
```

Fix the first incorrect owner. Never add domain patches or compatibility paths.

## 16. Anti-overdesign boundary

Do not add another reader, Agent role, package state, challenge taxonomy,
mutation format, workflow engine, Registry, service protocol, or reward system
without a demonstrated product claim that existing components cannot prove.

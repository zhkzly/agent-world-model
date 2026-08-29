# S2 Goal-First Task Foundry — Technical Design

## 1. Feasibility decision

The complete S2 is implementable only after S1 publishes independently checked
task semantics. A clean-room TaskSemantics Author is independent from the actor
Builder, but `inspect` and `evaluate_atom` from that same package cannot validate
each other. Therefore S1 uses one additional qualification-only native verifier
lineage. This is necessary verifier independence, not a product Agent node.

The design rejects both weaker alternatives:

- treating TaskSemantics as its own independent oracle;
- introducing a universal native-state/schema/query DSL in Framework code.

## 2. Complete causal graph

```text
Need
-> Research / Development Brief
-> Environment Builder -----------------------------> actor A
-> source-blind ExpectedTaskSemantics freeze -------> expectations E
       ├-> TaskSemantics Author ---------------------> semantics S
       └-> Qualification Verifier Author ------------> verifier N

Host derives Core ID K(E,A,S,N,schemas,docs,factories)
-> shared locked materialization of A/S/N
-> physical Qualification over public calls + two native readers
-> evidence manifest Qe
-> strict passed receipt Q(K,Qe)
-> Publisher seals immutable EnvironmentRelease v2 R
-> cold verify/replay R

R
-> deterministic Blueprint/checker/instruction compiler
-> TaskDefinition T with logical binding plan
-> fresh public witness W1 (rebind on materialization 1)
-> fresh public witness W2 (rebind on materialization 2)
-> challenges + live checker mutations
-> TaskPack P
-> independent TaskAssessment A*
-> CorpusManifest C
```

No downstream artifact flows backward into an upstream semantic decision.

## 3. Code-author visibility matrix

| Producer | Sees | Must not see | Writes |
| --- | --- | --- | --- |
| Environment Builder | BuilderProjection, actor contract | expected semantics, Tasks, verifier | actor uv project |
| Expected semantics turn | Need/Brief Requirements/workflows | actor source/native fields, semantics/verifier | typed document only |
| TaskSemantics Author | E, public surface, read-only actor view | verifier source/results/feedback | semantics uv project |
| Verifier Author | E, public surface, read-only actor view | semantics source/results/feedback | verifier uv project |
| Witness/assessment Agent | final instruction, public context/tools | E/S/N/checker/protected data | calls + answer only |

Host code owns every manifest, digest, process, evidence row and verdict.

## 4. Pre-publication core identity

### 4.1 Core document

```python
@dataclass(frozen=True)
class QualificationCore:
    expected_semantics_digest: str
    actor_project_digest: str
    actor_factory: str
    semantics_project_digest: str
    semantics_factory: str
    verifier_project_digest: str
    verifier_factory: str
    start_schema_digest: str
    reset_observation_schema_digest: str
    public_documents_digest: str

    @property
    def core_id(self) -> str: ...  # RFC 8785 + SHA-256
```

The Core is derived from frozen bytes. It is not serialized as a public package
type and has no mutable status. Any actor, semantics, verifier, schema, factory
or document change creates a new Core and invalidates all evidence.

The Host also freezes canonical data documents before receipt sealing:

```text
public-surface.json       start/reset schemas, public docs, exact ToolSpec catalog
qualified-catalog.json    exact CapabilitySpec/ConditionSpec/CompositionRule catalog
requirement-coverage.json every Requirement disposition -> capability/case evidence
qualified-start-cases.json exact StartCases S2 may materialize
```

`actor.tools()` and `trusted.capabilities()` must reproduce their sealed catalog
digests in every prepared session. The live StartCase generator must reproduce
the sealed qualified set; S2 cannot request an unqualified generated case.

### 4.2 Acyclic release identity

```text
K = H(core document)
Qe = H(evidence manifest bound to K)
Q = H(strict passed receipt bound to K and Qe)
P = H(final payload manifest including A/S/N/evidence/docs)
R = H(final release descriptor binding P and Q)
```

Qualification never references `R`. Publication never edits a Core member or
Qualification evidence. No provisional EnvironmentRelease is created.

## 5. Shared project materialization

One internal project installer owns copy, locked uv sync, interpreter isolation,
origin verification and import-deny checks:

```python
materialize_project(ProjectInput, cache_root, role) -> RuntimeLock
```

Qualification calls it for actor, semantics and verifier. Sealed-release
preparation calls the same function for actor and semantics only. This avoids a
second cache format, sync implementation or child transport.

Release runtime remains exactly two surfaces. The verifier runtime exists only
during Qualification/cold audit and is never returned by `prepare_release`.

## 6. Qualification verifier contract

### 6.1 Fixed factory

```python
generated_qualification_verifier.release:make_verifier
```

### 6.2 Request and result

```python
@dataclass(frozen=True)
class NativeVerificationRequest:
    capability_id: str
    start_case_id: str
    public_descriptor: JSONObject
    public_trace: tuple[TraceEvent, ...]
    final_answer: JSONValue | None
    before_instance_directory: Path
    after_instance_directory: Path

@dataclass(frozen=True)
class NativeVerificationResult:
    initially_satisfied: bool
    satisfied: bool
    required_effects_ok: bool
    collateral_ok: bool
    answer_ok: bool | None
    process_ok: bool | None
    report_values: JSONObject
    failure_codes: tuple[str, ...]
```

The verifier reads native state directly from the two instance directories. It
must not import actor/TaskSemantics/Host packages or execute actor business
functions. Host tree manifests prove each call is read-only.

It receives the public descriptor and public trace, never the TaskSemantics
protected binding or facts. This prevents a wrong protected mapping from being
copied into both sides of the comparison.

Failure to resolve the intended native referent from those public inputs is an
`UnsupportedCapability` result, not permission to reveal a hidden ID.

### 6.3 Qualification case execution

For each Taskable capability and qualified StartCase:

```text
create before and after instance directories
reset both with identical reset input
inspect both through TaskSemantics
enumerate an eligible logical referent
run a public-only Responses episode against after
inspect after
TaskSemantics.evaluate_atom(before facts, after facts, protected binding, trace, answer)
Verifier.verify(before path, after path, public descriptor, trace, answer)
compare all axes/report values
repeat applicable physical negatives and fresh replay
```

The Responses policy gets capability intent and public descriptor as a
qualification instruction, not a hidden tool sequence. Its trace is evidence,
not semantic authority.

### 6.4 Required physical matrix

```text
positive public success       -> both satisfied
no-op                         -> both failed
wrong/ineligible target       -> both failed
boundary near miss            -> both failed
required answer correct       -> both answer_ok
wrong/stale answer            -> both failed
prohibited collateral         -> both failed
required process omitted      -> both failed
fresh equivalent replay       -> same business outcome
```

Non-applicable rows require a typed reason anchored to the capability contract.
Executable semantic/verifier mutants must be killed independently.

## 7. Qualification receipt and release layout

### 7.1 Layout

```text
EnvironmentRelease/
├── release.json
├── payload-manifest.json
├── qualification/
│   ├── receipt.json
│   ├── evidence-manifest.json
│   ├── evidence/
│   └── verifier/                 # archived audit-only uv project
├── actor/
├── semantics/
├── docs/
├── dist/
└── licenses/
```

`receipt.json`, `release.json` and `payload-manifest.json` are excluded from
their own identity preimages. Verifier/evidence bytes are ordinary manifest
members. The descriptor directly binds the receipt digest.

### 7.2 Receipt admission

`verify_release_v2` performs both byte-closure verification and strict receipt
admission. A receipt must have exact keys, `verdict="passed"`, match the
recomputed Core, match project/catalog/coverage digests and bind an evidence
manifest whose required categories are complete.

A separate internal layout verifier may support pre-publication assembly tests,
but `prepare_release` and every S2 entry point accept only admitted releases.

### 7.3 Runtime versus audit projection

```python
admit_release_v2(path) -> AdmittedReleaseView
audit_release_v2(path) -> QualificationAuditView
```

`AdmittedReleaseView` exposes release identity, sealed public surface/catalog/
StartCases and prepared actor/TaskSemantics sessions. It contains no verifier
factory/path, native evidence or Qualification trace. `QualificationAuditView`
is used only for cold receipt replay. S2 compiler and public runner accept only
the admitted view type.

## 8. Stable public references

```python
@dataclass(frozen=True)
class PublicValueSource:
    kind: Literal["task_literal", "reset", "tool_output", "tool_schema_constant"]
    tool_name: str | None
    json_pointer: str | None
    value: JSONValue | None
```

Rules:

- `task_literal` stores the stable value and no pointer;
- `reset` stores an exact reset-observation pointer;
- `tool_output` stores tool name plus output-schema pointer;
- `tool_schema_constant` stores tool/input pointer plus exact constant;
- every public descriptor/facet leaf and required answer field declares one;
- schema pointers must resolve through explicit `properties/items`; broad object
  schemas do not authorize descendants.

Qualification executes each non-literal source and proves value agreement.

Run evidence resolves a source declaration to one occurrence:

```python
@dataclass(frozen=True)
class PublicValueOccurrence:
    source_digest: str
    materialization_id: str
    instruction_slot: str | None
    trace_event_seq: int | None
    json_pointer: str | None
```

Repeated calls to the same tool remain distinguishable by `trace_event_seq`.

## 9. Logical bindings and fresh materialization

```python
@dataclass(frozen=True)
class LogicalBindingRef:
    slot: str
    capability_id: str
    semantic_key: str
    selector_id: str
    instruction_values: JSONObject

@dataclass(frozen=True)
class ResolvedBinding:
    logical_ref_digest: str
    materialization_id: str
    protected_binding: JSONObject
    public_descriptor: JSONObject
    source_evidence_digest: str

@dataclass(frozen=True)
class LogicalSelection:
    selector: SelectorSpec
    semantic_keys: tuple[str, ...]
```

TaskDefinition/checker template bind `LogicalBindingRef`, never a concrete
protected binding. Each witness/challenge:

1. resets a new instance;
2. inspects and enumerates bindings;
3. resolves the same semantic key/selector;
4. validates stable instruction values and public sources;
5. stores `ResolvedBinding` only in run evidence.

Member `slot` is unique per logical referent; multiple member slots may point to
the same selection's `selector_id`. The full SelectorSpec exists once in
`LogicalSelection`, so a multi-member ForEach set is representable without
duplicating or conflating member and set identity.

If a stable instruction value changes across equivalent starts, the Blueprint is
rejected. Dynamic IDs must be discovered through a qualified public source.

Every TaskDefinition freezes one `LogicalSelection` per selector. Composition
identity lives only in `AllGoal`; ForEach identity lives only in `ForEachGoal`,
so no duplicate annotation can become orphaned. Recursive Goal validation must
consume every frozen binding and selector exactly once through the Goal graph.
Every materialization resolves the same semantic-key tuple and cardinality in
stable order; `exactly_one`/`any_one` contain one frozen member and `all`
contains the complete non-empty tuple. Missing, extra, tied or newly eligible
members reject the run.

## 10. Goal evaluation context

```python
@dataclass(frozen=True)
class GoalEvaluationContext:
    current_slot: str
    resolved_bindings: tuple[ResolvedBinding, ...]
    composition_rule_id: str | None
    foreach_selector_id: str | None
    permitted_sibling_slots: tuple[str, ...]
```

`AtomCheckRequest` includes this context. The release-local evaluator uses it to
separate the current atom's forbidden collateral from effects required by
selected siblings. Framework validates that sibling slots exactly match the
CompositionRule or ForEach selection; there is no second generic scope policy.

## 11. Deterministic S2 compiler

Input:

```text
admitted release
StartCases
CapabilitySpecs / BindingCandidates / public sources
bounded synthesis policy
```

Output order:

```text
enumerate valid selectors and four-node Goals
resolve logical bindings on the compile materialization
compile checker template
prove checker false initially
freeze checker digest
render canonical instruction from stable public values
audit slot/cardinality/source/leakage coverage
freeze instruction and TaskDefinition
only then allow a witness model call
```

The compiler interprets only release-local IDs and declared contracts. It never
branches on booking, SQLite, Git, native field names or broad workflow labels.

## 12. Checker interpreter

- `AtomGoal`: call `evaluate_atom` with run-local resolved binding/context.
- `AllGoal`: require every child and exact CompositionRule membership.
- `IfGoal`: evaluate the qualified public condition and selected branch.
- `ForEachGoal`: resolve the complete selected set and require every member.
- `ReportSpec`: validate structured answer fields against semantic results.

Outcome checkers do not compare witness routes. Trace projection is used only by
capabilities with declared process obligations.

## 13. Public Responses runner

```python
run_public_episode(
    actor,
    instruction,
    reset_context,
    tool_specs,
    answer_schema,
    route,
    budget,
) -> EpisodeRun
```

The Host derives strict function tools from ToolSpecs, dispatches real calls,
feeds exact observations back, records usage and validates the final answer.
Every argument leaf is classified against instruction/reset/tool-output/schema
sources. Protected/unresolved/load-bearing AgentChoice values reject the run.

Before each qualification/witness/assessment episode, Host creates a fresh
`EpisodeIdentity` from route/prompt/runner/materialization IDs and starts with no
previous response ID or conversation items. Only items produced inside that
episode may be replayed to the model.

Two witness runs use distinct materialization IDs and independent binding
resolution. They may use different dynamic IDs/routes while satisfying the same
logical Task/checker.

## 14. Admission and corpus

Before witness execution, Host derives a canonical `AdmissionPlan` from the
TaskDefinition and qualified catalog. Every challenge/mutation category is
`applicable(spec)` or `not_applicable(reason)` before any result is seen.
Admission then runs concrete no-op, wrong target, partial All/ForEach,
collateral, answer, process and alternative-route challenges plus the planned
checker mutations. Unreachable/crashing mutants do not improve evidence, and no
planned row may disappear from the final report.

```text
TaskDefinition + W1 + W2 + AdmissionReport -> TaskPack
TaskPack + independent policy trials -> TaskAssessment
TaskPacks + assessments + corpus policy -> CorpusManifest
```

Assessment/corpus changes never rewrite TaskPack truth.

## 15. Error ownership

```text
ResearchDefect            Brief/expected relation wrong
EnvironmentDefect         actor/native behavior wrong
SemanticsDefect           TaskSemantics disagrees with native/public evidence
VerifierDefect            independent verifier wrong or non-discriminating
InfrastructureFailure     provider/dependency/process failure
UnsupportedCapability     required truth cannot be independently verified
RejectedBlueprint         deterministic Task construction invalid
CheckerDefect             challenge/mutation survives
InstructionDefect         public wording/source contract invalid
NoPublicWitness           bounded acting policy found no solution
RejectedTaskPack          intrinsic admission failed
RejectedForCorpus         valid TaskPack excluded by corpus policy
```

When semantic and verifier outputs disagree without decisive public/native
evidence, fail closed and re-author the implicated artifact in an isolated
context. Never patch Framework with domain logic.

## 16. Anti-overdesign boundary

Forbidden without a demonstrated cross-domain failure:

- restoring any deleted v1 module or test fixture;
- another Agent organization beyond the three code artifacts and public acting policy;
- provisional release/candidate/quarantine package formats;
- second installer/transport/cache implementation;
- Registry, queue, service, MCP or HTTP product topology;
- universal state/tool graph, SQL/effect language or arbitrary per-Task verifier;
- hidden setup, native writes or snapshot restoration;
- generic read/write-scope algebra in addition to CompositionRule/selected siblings;
- S3 reward or optimizer implementation inside S2.

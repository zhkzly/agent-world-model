# S2 Good-Task Sampling Foundry — Technical Design

## 1. System boundary

```text
S1 sealed EnvironmentRelease
  public: reset / tools / invoke / close / schemas / observations
  trusted: StartCases / bindings / qualified TaskSemantics
                         |
                         v
S2 sampler proposals -> Good Task admission -> TaskPack corpus
                         |
                         v
S3 public episode + verified facts + reward/abstention
```

S2 trusts sealed S1 semantics only for capabilities S1 actually qualified. It
does not infer a world ontology or ask S1 to publish Tasks. S3 must not reinterpret
Task truth.

## 2. Persistent versus ephemeral objects

Only identity-bearing outputs survive a run:

```text
TaskSpecification
StartRecipe
VerifierBundle
AdmissionEvidence
TaskPackManifest
TaskAssessment        # separate from Task truth
CorpusManifest        # separate selection identity
```

These may be sections of one TaskPack directory; they do not require seven
packages or services.

Sampler graphs, solution programs, exploration traces, rejected candidates and
challenge workspaces are evidence or run-local proposals. They are not public
Task ABIs.

TaskSpecification is one object with two ordered sections, not two Task types:

```text
semantic section  # parameterized meaning, frozen at Stage 2
binding section   # public values filling frozen slots, appended at Stage 5
```

## 3. Fixed causal order

```text
0. prepare exact release
1. disposable public discovery
2. draft and coverage-check parameterized TaskSpecification
3. compile provisional task-local VerifierBundle V0
4. materialize Start independently and enumerate public bindings
5. bind concrete Task and freeze instruction/checker/answer contract
6. search public witness and replay on a fresh instance
7. close/reopen when required, extract truth, run challenges
8. seal TaskPack
9. assess policy difficulty and select CorpusManifest
```

The order is semantic, not merely a call sequence:

- Stage 1 may propose; it cannot define truth.
- Stages 2–3 freeze meaning before a successful trace exists.
- Stage 6 cannot see protected checker outcomes while searching.
- A Stage 7 semantic defect restarts Stage 2. A verifier implementation defect
  restarts Stage 3 and reruns every applicable challenge.
- Stage 9 never changes TaskPack validity.

## 4. Common sampler boundary

All samplers emit one canonical ephemeral JSON proposal:

```text
CandidateTaskProposal/1
  sampler: {kind: direct|graph|programmatic, version}
  release_id
  requirement_ids[]
  obligation_ids[]
  objective
  goal_shape: atom|all|if|foreach
  capability_ids[]
  composition_rule_id?
  condition_id?
  public_slots[]:
    {slot_id, capability_id, cardinality, facet_constraints[]}
  public_evidence_refs[]: {kind, digest}
```

Framework canonicalizes and schema-validates this exact shape before coverage
work. Sampler-specific graphs/programs remain behind evidence digests, so they
cannot create de facto internal Task ABIs.

More than one capability is legal only when `composition_rule_id` resolves to a
sealed S1 CompositionRule covering those capabilities/workflow. Executed
adjacency alone cannot license a composed objective.

It contains no expected dynamic answer, protected binding, verifier result,
reward, difficulty label or admission verdict.

### 4.1 Graph sampler

The Graph sampler builds a disposable graph from executed public evidence:

```text
reset disposable instance
-> call a public tool with public-provenance arguments
-> retain ToolObservation
-> derive later candidate arguments only from public values/schema constants
-> execute the later call
-> record observed value-flow and state-enablement edges
-> sample bounded paths/subgraphs anchored to one Requirement objective
```

An LLM may rank or describe candidate edges, but an unexecuted LLM edge is not
an executable dependency. Successful paths prove only reachability.

Only two edge kinds enter proposal evidence:

```text
value_flow:
  exact earlier ToolObservation JSON pointer -> exact later argument pointer

state_enablement:
  on equivalent fresh starts, the same later tool+arguments fails before the
  earlier action and succeeds after it, with the earlier required effect
  confirmed by qualified TaskSemantics
```

Temporal adjacency alone is not an edge.

### 4.2 Programmatic sampler

The Programmatic sampler asks a public-only planner for a bounded run-local JSON
solution program. It is not Python and has only four operations:

```text
call(tool_name, arguments from literal/reset/prior observation)
if(public observation pointer, then, else)
for_each(public observation array, bounded body)
finish(final-answer references)
```

No arbitrary loop, import, filesystem, network, native state or verifier call is
available. The program is sampler evidence, not a persistent DSL or Task ABI.

Execution is:

```text
Requirement + public schemas + reset observation
-> proposed control program over tool calls and public values
-> execute on disposable instance
-> return structured failure to the same proposal lineage when repairable
-> fresh replay the repaired program
-> derive CandidateTaskProposal from Requirement + executed public evidence
```

The solution program is not shipped as the answer or enforced as the only
valid route.

### 4.3 Direct compiler baseline

The existing Capability/Atom/ForEach/If compiler is retained as a deterministic
grounded baseline. It is evaluated under the same budget and the same Good Task
gates as Graph and Programmatic proposals.

## 5. TaskSpecification and bidirectional coverage

The Stage 2 semantic section freezes:

```text
Requirement anchors
objective and actors
quantifiers, public slot definitions and source constraints
required effects
allowed effects
forbidden effects
answer fields and public sources
required process milestones, if process is itself part of the user objective
applicable and explicitly irrelevant Requirement obligations
```

It has a semantic digest before Start. Stage 5 may append concrete public
descriptors/values to the binding section, but any change to objective,
quantifiers, effects, answers, process or obligation disposition creates a new
semantic version and restarts V0.

S1 seals a compact obligation catalog before S2 begins:

```text
RequirementObligation
  obligation_id
  requirement_id
  kind: precondition|effect|answer|process|refusal|collateral
  canonical_text_digest
  applicability_handle
```

Applicability is not S2-authored. The handle is one finite S1-owned form over
already-qualified semantics:

```text
always
start_case(case_id)
binding_eligible(capability_id)
condition_branch(condition_id, true|false)
facet_predicate(capability_id, facet_name, allowed_operator, public_literal)
```

This is a narrow expected-semantics section, not a general expression language.
Framework evaluates it against sealed StartCase/BindingCandidate/Condition/Facet
values.

Coverage is checked in both directions:

```text
for semantic predicate in TaskSpecification/V0:
    require one S1 obligation_id or qualified semantic operation

for obligation in sealed S1 catalog:
    applicable = evaluate_S1_handle(obligation.applicability_handle)
    if applicable:
        require included_by(predicate_id)
    else:
        permit irrelevant(obligation_id, evaluated_handle_evidence)
```

Instruction spans, schemas and public source pointers are recorded separately
as disclosure/provenance evidence. They can show that the acting policy sees a
constraint or operand; they can never authorize the semantic predicate.

A fresh semantic challenger may identify a wrong predicate mapping or wrong
applicability result from the same public S1 catalog, but it cannot create/delete
obligations or handles, change evaluation, or authorize admission. Framework
fails closed on unresolved challenge findings. LLM agreement is not proof of
hidden-world truth; the claim is limited to the sealed S1 obligation catalog.

## 6. VerifierBundle V0

Parametric V0 is compiled after semantic-section freeze. Concrete public
bindings instantiate its frozen slots after Start without adding or weakening a
predicate.

It contains a bounded evaluation plan that calls qualified release-local
TaskSemantics operations for frozen slot definitions and their later bound
public values:

```text
decode Start/before/after facts read-only
resolve current logical bindings
evaluate required/allowed/forbidden effects
evaluate declared process milestones against the public trace
derive exact structured answer truth from declared public sources
combine child predicates for Atom / All / If / ForEach
```

V0 is not unrestricted per-Task Python. A release-specific representation
decoder remains owned and qualified by S1. S2 compiles composition and concrete
bindings; it does not learn allowed state changes from a witness diff.

## 7. Start, concrete binding and public freeze

Start materialization is reset-only. Sampler exploration calls never become a
hidden setup prefix: a load-bearing call must remain part of the public Task
process, or the candidate is rejected/requested as a future qualified S1
StartCase. Native writes and hidden snapshots are never allowed.

For each Candidate Task:

```text
materialize Start A
materialize Start B
verify semantic-equivalent public regimes
enumerate public BindingCandidates independently
resolve the same logical referents
bind public descriptor values
freeze TaskSpecification + StartRecipe + V0 + answer schema
render final canonical instruction
audit public closure and answer opacity
```

The Host seals compact `PublicClosureEvidence`:

```text
task_semantic_digest
constraint_disclosures[]: {predicate_id, obligation_id, instruction_span_digest}
operand_sources[]: {slot_or_answer_field, public_source_kind, pointer_or_span}
answer_opacity[]: {answer_field, absent_from_instruction, absent_from_reset}
```

Every load-bearing predicate/operand must appear exactly once. Dynamic answers
whose declared source is a future ToolObservation are rejected if already
resolved from instruction/reset. A fresh public-view critic may reject ambiguity
or unnatural wording, but cannot authorize a missing deterministic entry.

Dynamic IDs need not match across starts; their logical constraints and public
rediscovery path must match.

## 8. Public witness, replay and reload

The witness policy receives exactly the future S3 public view. It does not see
sampler programs, semantic keys, expected branches, protected facts, V0 output
or reference answers.

```text
run exact instruction on Start A
-> capture public tool trace and final answer
-> verify all load-bearing argument provenance
-> close actor/trusted processes
-> reopen same native instance when persistence/process reload is declared
-> evaluate V0

repeat independently on Start B
```

The current SQLite failure case is mandatory regression evidence: a Task that
says “reopen and confirm” must be rejected if the trace/checker only performs an
in-process read.

When reload is required, AdmissionEvidence contains one Host-produced section:

```text
ReloadEvidence/1
  release_id, task_id, attempt_id       # generated before execution; no witness hash cycle
  native_instance_id                 # assigned before creating its directory
  acting_session_id
  reopened_session_id                # distinct session, same native_instance_id
  ordered_lifecycle_event_digest     # reset once -> act -> close -> reopen(no reset)
  pre_close_facts_digest
  post_reopen_facts_digest
  post_reopen_checker_result_digest
```

The Host event journal binds both session IDs to one run-local native instance;
absolute temporary paths are not product identity. The reader rejects reused
session IDs, another native instance, a second reset, missing close, or checker
evaluation before reopen.

## 9. Challenge plan without a Cartesian matrix

Framework derives an applicability plan before witness search. Each category is
either physically executed or records a deterministic non-applicability reason.

| Category | Applicable when | Required evidence |
|---|---|---|
| initial/no-op | always | frozen checker rejects Start/empty trace |
| wrong entity | another public compatible referent exists | control Task succeeds; selected Task fails |
| wrong/stale answer | answer schema has a constructible distinct value | real baseline trace plus modified answer fails |
| partial/omitted obligation | Task has multiple members/effects/obligations | retained parts may pass; omitted part fails Task |
| near-miss | public boundary or refusal predicate has a constructible adjacent case | near boundary fails for the declared reason |
| collateral | a public action can produce a forbidden unrelated effect | target may succeed; collateral predicate rejects |
| process violation | process/order/reload is explicitly load-bearing | final state alone cannot hide missing process |
| truth/replay agreement | qualified TaskSemantics evaluates the same logical Task across two fresh/reloaded instances | disagreement blocks seal |
| alternative valid path | a distinct public route is actually discovered | same outcome is accepted without trace equality |

The product does not require every member mutation, every ordering, every
parameter or every possible route. Optional robustness experiments may sample
more challenges after TaskPack truth is sealed.

S2 does not create another native truth reader. It relies on S1's qualification
receipt for each atomic Capability and requires task-level agreement across
fresh/reloaded instances. A proposed composed predicate that cannot reduce to
qualified TaskSemantics operations is rejected rather than licensed by new
unreviewed decoder code.

A V0 process predicate is legal only when it references an S1 obligation whose
kind is `process`. Graph state-enablement may guide proposal/witness search, but
cannot make one observed route mandatory. For each process predicate,
AdmissionEvidence records:

```text
milestone_id
process_obligation_id
semantic trace-predicate digest       # no fixed tool name/order unless obligated
real witness trace/result digest
missing-milestone trace-ablation result
physical omission episode result, when constructible
known alternative-route results[]
```

The missing-milestone check reuses real after-state facts but removes the
milestone evidence; V0 must reject. If a distinct physical omission episode can
be constructed, run it as well. A different route satisfying the same public
process semantic remains valid. If there is no S1 process obligation, S2 cannot
freeze a witness step as required process.

## 10. TaskPack sealing and cold read

TaskPack identity binds exact release and frozen sections:

```text
release_id
TaskSpecification digest
StartRecipe digest
VerifierBundle digest
instruction/answer-schema digest
AdmissionEvidence digest
```

AdmissionEvidence contains two fresh public witnesses, provenance, reload facts,
coverage decision and applicable challenge results. TaskAssessment and corpus
policy are excluded.

A strict cold reader accepts only current formats, recomputes every digest and
returns two projections:

- trusted host projection: StartRecipe + verifier + identities;
- PublicTaskView: instruction + final-answer schema only. Reset observation and
  ToolSpecs are obtained freshly from the selected EnvironmentRelease.

No compatibility reader or Task format fallback is added.

## 11. Assessment and corpus

Assessment runs after admission on fresh materializations. A trial checker
failure or `NoPublicWitness` is recorded as policy-relative failure;
Environment/Task/Verifier/Infrastructure defects remain typed upstream errors.

At least two policy lineages or checkpoints are required for paper calibration.
One policy with 100% success proves neither useful difficulty nor discrimination.

Corpus selection operates on exact TaskPack/Assessment pairs and reports:

```text
sampler proposal and admission yield
unique semantic/execution structures
Goal/capability/state/constraint/information-dependency distribution
redundancy
per-policy success/failure classes
tool calls, tokens and latency
```

Fixed budgets make samplers comparable. Counts and distributions do not weaken
individual Task gates.

## 12. Failure ownership

```text
RejectedProposal        sampler output cannot form an anchored specification
CoverageDefect          applicable obligation missing or predicate unanchored
StartDefect             qualified reset cannot reproduce the required regime
InstructionDefect       public closure, ambiguity, opacity or process wording wrong
NoPublicWitness         bounded public policy cannot solve a valid frozen Task
VerifierDefect          V0/check implementation contradicts frozen specification
TaskChallengeFailure    a physical counterexample defeats Task validity
EnvironmentDefect       actor or sealed S1 semantics are wrong
InfrastructureFailure  provider/dependency/process unavailable
RejectedForCorpus       valid Task excluded by declared corpus policy
```

Fix the first owner. Never add a downstream compatibility adapter or a
domain-specific exception to make the batch green.

## 13. Current code disposition

### Retain

- v2 release verification/preparation and isolated processes;
- public ToolSpec/ToolObservation and Agent loop;
- qualified TaskSemantics and S1 native audit boundary;
- fresh materialization and logical binding resolution;
- argument provenance;
- bounded Atom/If/ForEach representations already implemented; All remains a
  planned bounded composition only when licensed by an explicit CompositionRule;
- TaskPack, Assessment and Corpus identity separation.

### Rework

- current Capability-only candidate enumeration into the direct baseline;
- concrete checker into TaskSpecification/V0 compilation;
- admission into applicability-planned Good Task challenges;
- in-process “persistence” into physical close/reopen;
- batch target stopping into fixed-budget sampler reporting;
- TaskPack serialization into strict cold read and PublicTaskView.

### Keep deleted

- v1/legacy Task ABI and compatibility paths;
- TaskIntent/WitnessSet and witness-derived truth;
- persistent GraphTask/ProgrammaticTask types;
- universal State IR/ontology and generic native snapshots;
- unrestricted per-Task verifier code;
- fake result mutation and exhaustive challenge Cartesian products;
- domain-specific Framework logic, repository templates and hidden setup.

## 14. Anti-overdesign test

Before adding any node, field, Agent role or package, answer:

```text
Which Good Task or S2->S3 claim cannot be physically proved by an existing
component, and what real counterexample demonstrates that gap?
```

No counterexample means no new component. A concept described in this document
does not require its own class, file, service or model call unless the vertical
implementation needs an identity or an executable boundary.

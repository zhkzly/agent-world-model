# S2 Goal-First Task Foundry

## Goal

Build the paper-grade production path:

```text
natural-language Need
-> real executable actor environment
-> independently qualified EnvironmentRelease v2
-> deterministic Goal-first Task definitions and frozen checkers
-> two fresh public-only Agent solutions of the exact final instruction
-> physical challenges and checker mutations
-> TaskPack
-> separate TaskAssessment and CorpusManifest
```

Semantic completion is the criterion. A demo, MVP, mock, dictionary world,
hand-written Task, fixture receipt, green unit suite or one successful trace is
never completion evidence.

There is no backward compatibility with EnvironmentRelease v1 or the deleted
Qualification/publication/loader path.

## Stage boundary

S1 owns executable worlds, reusable taskable semantics and release admission.
S2 consumes only a sealed, qualified EnvironmentRelease v2. S2 never reads a
Builder workspace, model conversation, unsealed project or qualification-only
verifier.

S2 produces TaskPacks, assessments and a corpus. S3 later executes training
episodes and maps checker truth to reward/abstention. S2 does not invent a scalar
reward or redefine environment truth.

## Author and Host ownership

### Three isolated code-authoring lineages

1. **Environment Builder** writes the actor uv project.
2. **TaskSemantics Author** writes the protected runtime used by S2 checkers.
3. **Qualification Verifier Author** writes one audit-only native verifier uv
   project.

All use fresh workspaces/threads. The Semantics Author and Verifier Author see
the same frozen expected semantics and read-only actor view, but never each
other's source, output, tests or repair history. The verifier is archived for
cold audit and is not available to S2 or Consumers.

### Deterministic Host

Framework Python owns:

- schemas, canonical serialization, identities and manifests;
- project checks, locked installation and process isolation;
- public actor dispatch and trace journals;
- execution of TaskSemantics and the independent verifier;
- physical positive/negative cases and axis-by-axis agreement;
- Qualification receipt and final release verdict;
- Blueprint enumeration, checker compilation/execution and instruction rendering;
- fresh logical rebinding and public provenance;
- witness/challenge/admission, identities, assessment and corpus selection.

Generated code and model prose are proposals. They never write digests,
manifests, receipts, verdicts, TaskPacks or rewards.

## S1 v2 qualification and release requirements

### Frozen expected semantics

Before either semantic author sees actor source/native details, a fresh typed
turn dispositions every accepted Requirement as `Taskable`, `NotTaskable` or
`Unsupported` and freezes capability, workflow, composition, condition and
answer expectations. Silent omission is invalid.

### Core identity

The Host derives one pre-publication `core_id` from canonical frozen inputs:

```text
expected-semantics digest
actor project digest + factory
TaskSemantics project digest + factory
Qualification Verifier project digest + factory
start/reset schemas
public documentation digest
```

`core_id` is a derived hash, not a new package format or public lifecycle state.
It excludes Qualification evidence, receipt and final Release ID.

### Independent verifier

The qualification-only verifier reads the real before/after instance state and
evaluates one capability transition without importing/calling the actor or
TaskSemantics package. It receives only Host-frozen case input, public trace and
final answer. It returns the same outcome axes required from TaskSemantics:

```text
initially_satisfied
satisfied
required_effects_ok
collateral_ok
answer_ok
process_ok
report_values
failure_codes
```

The Host compares every axis and report value. Agreement alone is insufficient:
real success, no-op, wrong/near-miss target, answer, collateral, process and
fresh-replay cases must produce the expected discriminating outcomes. Executable
inspector/evaluator/verifier mutants must be killed; syntax/import/crash mutants
do not count.

If the verifier cannot identify the intended native referent from the public
descriptor/trace without TaskSemantics protected data, that capability is
`Unsupported`; Qualification may not inject a hidden identifier.

### Strict Qualification receipt

A passed receipt binds exactly:

```text
format = environment-qualification/2
verdict = passed
core_id
expected_semantics_digest
actor_project_digest
semantics_project_digest
verifier_project_digest
public_surface_manifest_digest
qualified_catalog_digest
requirement_coverage_digest
qualified_start_cases_digest
evidence_manifest_digest
```

The evidence manifest binds public traces, native/semantic results, negatives,
fresh replay, no-mutation/import checks and mutant results. An arbitrary
canonical JSON document or mechanical fixture cannot pass admission.

The bound documents have fixed consumers:

- `public-surface.json` binds public schemas/docs and the canonical ToolSpec
  catalog; every live `tools()` result must match it;
- `qualified-catalog.json` binds the exact qualified capability/condition/
  composition catalog; every live `capabilities()` result must match it;
- `requirement-coverage.json` binds every Brief Requirement disposition and its
  capability/case evidence;
- `qualified-start-cases.json` lists the exact reset inputs/regimes S2 may use.
  The live generator must reproduce them, and unlisted StartCases are not
  admissible merely because code can generate them.

### Final release identity

Publication copies frozen bytes exactly, adds Host evidence and receipt, then
computes payload/receipt digests and the final descriptor. The final Release ID
is the descriptor digest. Qualification binds `core_id`, never the not-yet-known
Release ID; therefore no hash fixed point or provisional public release exists.

Cold verification reopens archived bytes, reinstalls exact projects, replays
Qualification evidence and only then admits the release for S2.

## Required S2 input

A sealed release provides:

```python
reset(start: JSONObject | None) -> JSONValue
tools() -> tuple[ToolSpec, ...]
invoke(tool_name: str, arguments: JSONObject) -> ToolObservation
close() -> None
```

and protected TaskSemantics:

```python
start_cases(seed: int, limit: int) -> tuple[StartCase, ...]
inspect(instance_directory: Path) -> JSONValue
capabilities() -> tuple[CapabilitySpec, ...]
enumerate_bindings(capability_id: str, facts: JSONValue) -> tuple[BindingCandidate, ...]
evaluate_atom(request: AtomCheckRequest) -> AtomCheckResult
evaluate_condition(request: ConditionCheckRequest) -> ConditionCheckResult
```

StartCases are deterministic, schema-valid and reset-only. There are no hidden
setup calls, native writes or snapshot restore.

S2 receives an `AdmittedReleaseView`, not the raw package/audit tree. It exposes
the release identity, public-surface manifest, qualified catalog/start cases and
prepared actor/TaskSemantics sessions. Qualification verifier bytes, native
evidence and reference traces are available only to a separate cold-audit API.

## Good Task contract

Every admitted Task is:

1. **Publicly solvable:** two distinct fresh materializations solve the exact
   frozen instruction using public tools and observations only.
2. **Reliably verifiable:** the checker rejects no-op, wrong target, near miss,
   partial completion, collateral damage and wrong/stale answers where applicable,
   while accepting valid alternative routes.
3. **Well-posed:** every material constraint is explicit without native fields,
   protected IDs, tool names, reference order or answer leakage.
4. **Non-trivial:** the checker is false before acting.
5. **Reproducible:** the same release/StartCase recreates business predicates
   even when incidental native IDs differ.
6. **Need-anchored:** atoms, conditions and compositions map to accepted
   Requirements/workflows.
7. **Path-open:** outcome truth, not reference-trace equality, determines success.
8. **Training-targeted:** model difficulty/cost is separate assessment evidence.

## Fresh logical binding

TaskDefinition stores a logical binding plan:

```text
binding slot
capability_id
stable semantic_key
stable public selection constraints
public source declarations
```

It never embeds one instance's protected binding as cross-run truth. After every
fresh reset, the Host re-runs `inspect` and `enumerate_bindings`, resolves the
logical referent, and stores that run-local protected resolution only in witness
or challenge evidence. Failure to rebind is `SemanticsDefect` or
`RejectedBlueprint`, never a guessed ID.

For `AllGoal` and `ForEachGoal`, TaskDefinition additionally freezes a
`LogicalSelection`: the exact semantic-key set, selector/cardinality rule,
CompositionRule or ForEach identity, and stable member ordering. Every fresh run
must re-resolve the complete same logical set; missing, extra or ambiguous
members reject the run.

## Public value provenance

Every load-bearing public value has one exact source:

```text
TaskLiteral(value)
ResetObservation(json_pointer)
ToolObservation(tool_name, json_pointer)
ToolSchemaConstant(tool_name, input_pointer, value)
```

Binding descriptor/facet fields and answer fields declare their sources.
Prose/error scraping, protected guesses and unqualified object descendants are
invalid. Free Agent choices are allowed only when not a target, fixed constraint
or answer operand.

At runtime a declaration becomes an exact occurrence: task-instruction slot,
reset observation pointer for that materialization, or `(trace_event_seq,
json_pointer)` for a successful tool result. A tool name/pointer without the
event occurrence is not provenance when a tool is called more than once.

## Goal and checker contract

The bounded GoalProgram has four nodes only:

```text
AtomGoal
AllGoal
IfGoal
ForEachGoal
```

Selection/reporting are Blueprint attributes. `AllGoal` requires an explicit
qualified CompositionRule. `IfGoal` requires a qualified public condition.

For composed/batched evaluation, the Host passes a bounded evaluation context:

```text
current logical binding
all selected run-local bindings
composition_rule_id or foreach selector_id
permitted sibling capabilities/bindings
```

This prevents a legitimate sibling effect from being mislabeled collateral
without introducing a generic scope algebra.

Required order:

```text
qualified release + StartCase + logical bindings
-> TaskBlueprint
-> compile/digest-freeze checker template
-> render/audit/digest-freeze final instruction
-> persist TaskDefinition
-> allow Responses model call
```

The checker and instruction never depend on a witness trace.

## Witness, challenge and admission

The Host-owned Responses loop receives only the exact instruction, public reset
context, documentation, ToolSpecs/ToolObservations and answer schema. It never
receives GoalProgram, checker, protected bindings, native state or verifier.

Each TaskPack requires:

- two successful fresh runs with independent run-local rebinding;
- complete load-bearing argument provenance;
- applicable no-op, wrong/near-miss target, partial All/ForEach, collateral,
  wrong/stale answer, process and alternative-route challenges;
- every applicable live checker mutation killed;
- immutable evidence binding the exact TaskDefinition/checker/witnesses.

Before any witness call, the Host derives and freezes an `AdmissionPlan` listing
every challenge and checker mutation as applicable or not-applicable with a
contract-derived reason. Admission must account for that exact plan; it cannot
select easy challenges after observing witness behavior.

Every qualification, witness and assessment episode has a fresh episode identity
and empty model conversation state. Prior response IDs/items, tool results and
repair context cannot cross materializations or policy trials.

Bounded policy failure is `NoPublicWitness`, not proof that a Task is impossible.

## Assessment and corpus

TaskAssessment uses an independently configured acting model/policy and records
reliability, failure attribution and cost. It never changes TaskPack truth or ID.

Corpus selection first deduplicates TaskDefinition/checker semantics, then
balances capability/workflow, Goal shape, selector operators, StartCase regimes,
answer/process requirements and separate assessment evidence. Parameter changes
and paraphrases do not count as new structures.

## Acceptance criteria

### Code/trust gates

- [ ] No v1 symbol, reader, adapter, conversion or fallback is live.
- [ ] Core ID, strict receipt and final Release ID form an acyclic identity DAG.
- [ ] Actor, TaskSemantics and verifier authors are isolated and mutually blind as specified.
- [ ] Qualification uses real public transitions, native reads, physical negatives and executable mutants.
- [ ] Sealed releases are cold-replayable and only passed receipts reach S2.
- [ ] Fresh witnesses rebind logical referents; no protected ID crosses materializations.
- [ ] Every load-bearing public value has an exact qualified source.
- [ ] Checker is frozen before instruction exposure and model calls.
- [ ] Two fresh witnesses plus applicable challenges/mutations are required for every TaskPack.

### Real anti-demo floors

For each contrasting SQLite and filesystem/Git release:

- [ ] at least 20 admitted TaskPacks after semantic deduplication;
- [ ] at least 4 canonical Goal/selector structures;
- [ ] at least 2 qualified StartCase regimes;
- [ ] every core Taskable capability represented or newly Unsupported with evidence;
- [ ] exact released bytes pass S3-shaped cold recreation.

After framework/contracts/prompts freeze, one independently selected held-out
Need must produce without framework domain edits:

- [ ] at least 10 admitted TaskPacks;
- [ ] at least 3 canonical structures;
- [ ] at least 2 taskable capabilities or an explicit method-falsifying result;
- [ ] complete release, solvability, checker, leakage and cold evidence.

Matched-budget baselines and downstream evaluation must report Task yield,
fresh success, hidden-operand rejection, mutation kill/false acceptance,
alternative false rejection, structural redundancy, cost and training utility.

## Typed non-success outcomes

```text
InfrastructureFailure
EnvironmentDefect
SemanticsDefect
VerifierDefect
UnsupportedCapability
RejectedBlueprint
CheckerDefect
InstructionDefect
NoPublicWitness
RejectedTaskPack
RejectedForCorpus
```

No model consensus, fixture, mock, compatibility path or relaxed gate converts a
failure into admission.

## Out of scope

- EnvironmentRelease v1 compatibility or migration;
- Registry, service, HTTP or MCP product semantics;
- custom sandbox/controller/workflow engine;
- universal State IR, SQL/effect DSL or per-Task unrestricted verifier Python;
- hidden setup/native patch/snapshot restore;
- Graph/Programmatic as mandatory Task truth sources;
- S3 trajectory/reward mapping and S4 optimization implementation.

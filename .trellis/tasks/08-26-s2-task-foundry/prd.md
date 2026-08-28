# S2 Goal-First Task Foundry

## Goal

Build the complete S2 stage that consumes a qualified executable world and
produces release-bound Agent Tasks that are publicly solvable, deterministically
verifiable, well-posed, non-trivial, reproducible and useful for SFT/RL. S2 also
selects a structurally diverse, low-redundancy corpus from the admitted Tasks.

The old design is superseded. Graph random walks and Programmatic generation are
not required Task sources, and compatibility with the previous S1/S2 proposal is
not a product requirement.

## Product outcome

```text
natural-language Need
-> S1 builds and independently qualifies an executable world
-> EnvironmentRelease v2 includes qualified taskable capability contracts
-> S2 compiles parameterized TaskBlueprints from those contracts
-> S2 freezes a deterministic TaskChecker before solving
-> a public-only planner constructs and freshly replays one witness
-> S2 renders and audits the user instruction
-> adversarial challenges and independent actor trials run
-> admitted TaskPack + corpus metadata
```

A successful command, green unit suite, isolated happy path, canned Task, demo,
mock or manually tailored domain branch is not S2 completion.

## Feasibility boundary

The design is intentionally narrower than claiming post-hoc Task discovery from
an arbitrary opaque program. Automatic high-quality Task synthesis is supported
only when S1 can publish and qualify all of the following:

1. deterministic isolated resettable starts;
2. structured public tools and observations;
3. a protected read-only semantic state inspector;
4. parameterized taskable capability contracts anchored to the accepted Brief;
5. deterministic success, collateral and answer evaluators for those
   capabilities;
6. a start-space generator that yields reproducible valid reset inputs.

A Need whose world cannot expose deterministic task truth under this contract is
`Unsupported`; S2 must not substitute an LLM Judge or fabricate a weaker Task.

## Good Task contract

### Single Task qualities

Every admitted Task must satisfy all of these properties.

1. **Publicly solvable.** At least one constructive solution uses only the Task
   instruction, actor-visible reset context, public tool schemas, successful
   public observations and deterministic local computation over those values.
2. **Reliably verifiable.** The frozen checker distinguishes success from no-op,
   wrong target, boundary near miss, partial completion, collateral damage and
   wrong/stale final answer. A valid alternative route is accepted when one is
   available.
3. **Well-posed.** The instruction states every material constraint without
   exposing protected IDs, native fields, tool names or the reference route.
4. **Non-trivial.** The goal is false at the start. A mutation Task requires a
   real transition; a query Task requires information not already supplied as
   its answer in the Task or reset observation.
5. **Reproducible.** The same release and StartRecipe recreate the same business
   predicates on fresh isolated instances, even when incidental IDs or bytes
   differ.
6. **Need-anchored and natural.** The goal traces to one or more accepted Brief
   requirements and a qualified user-facing capability, not an accidental tool
   chain.
7. **Training-useful.** The Task names the capability it exercises and records
   observed interaction cost and empirical difficulty from independent actor
   trials.

### Corpus qualities

An admitted corpus must additionally be:

- structurally diverse across goal, selector, composition, state regime,
  binding depth, answer type and empirical difficulty;
- deduplicated at Blueprint/checker semantics rather than only by text;
- balanced for its declared SFT or RL use;
- evaluated by downstream held-out performance rather than claiming universal
  coverage from an internally defined taxonomy.

## Required S1 v2 handoff

S1 may be changed. The new release is a clean contract; no migration path from
previous research releases is required.

### Public actor surface

The actor-facing environment remains transport-neutral:

```python
reset(start) -> JSONValue
tools() -> tuple[ToolSpec, ...]
invoke(tool_name, arguments) -> ToolObservation
close() -> None
```

### Protected semantics surface

The exact release additionally binds an independently qualified
`SemanticsBundle` unavailable to the acting Agent:

```python
start_cases(seed, limit) -> tuple[JSONObject, ...]
inspect(instance_directory) -> JSONValue
capabilities() -> tuple[CapabilitySpec, ...]
enumerate_bindings(capability_id, facts) -> tuple[BindingCandidate, ...]
evaluate_atom(capability_id, before, after, binding, trace, answer)
    -> AtomEvaluation
```

The interfaces may be implemented by release-local Python code, but S1
Qualification must derive their expected semantics from the Need/Brief, read
native SQLite/files/Git independently, and physically challenge each taskable
capability. Candidate business functions and self-reported state are never the
qualification oracle.

### CapabilitySpec minimum semantics

Each taskable capability provides:

- stable capability and Requirement IDs;
- actor role, user-facing intent phrase and Task kind;
- parameter/binding schemas;
- public descriptor facets and the operators allowed on each facet;
- initial eligibility and terminal outcome semantics;
- deterministic answer contract when reporting is required;
- protected read/write scopes, required effects and forbidden collateral;
- supported GoalProgram node types;
- public labels needed for deterministic instruction rendering.

### BindingCandidate separation

A binding contains two strictly separated projections:

```text
protected binding
  native identity and evaluator-only facts

public descriptor
  values safe to state in the Task or rediscover through public tools
  plus typed selector facets
```

A protected value may select and verify a Task. It can never be injected into a
public witness argument.

### Start-space requirements

Every release supplies a deterministic start-case generator bound to the
release. S2 Task starts are reset-only:

```text
StartRecipe = exact release ID + canonical reset input
```

S2 performs no hidden setup calls and never writes native state directly. If the
start space cannot instantiate a capability or boundary regime, that candidate
is unsupported rather than repaired through private mutation.

### Prepared release runtime

S1 provides a public `prepare_release/open` runtime that installs exact locked
bytes and opens each release in an isolated interpreter/process. S2 and S3 must
not depend on a development checkout, Python import-cache luck or duplicated
private cold-start code.

## S2 inputs and outputs

### Input

```text
exact EnvironmentRelease v2
+ prepared isolated runtime
+ public actor surface
+ protected qualified SemanticsBundle
+ synthesis budget and corpus policy
```

### Output

```text
Admitted(TaskPack)
RejectedCandidate(reason, evidence)
ReleaseDefect(reproducible evidence)
InfrastructureFailure(identity-preserving diagnostics)
```

Candidates that fail admission may remain audit records, but there is no
persistent `QuarantinedCandidate` product lifecycle.

## Requirements

### R1. Exact identity and trust separation

- Every candidate, checker, witness, challenge, trial and TaskPack binds one
  exact release and semantics-bundle digest.
- Acting projections never contain the inspector, protected binding, checker,
  witness, challenge evidence or native state.
- Generated or model-authored code never receives release source, instance
  roots or protected semantics unless its named role is trusted and read-only.
- Changing release semantics, capability contracts, start, Blueprint,
  instruction, checker or answer schema creates a new identity.

### R2. Qualified capability semantics are the only Task truth source

- S2 admits only goals expressible as a `GoalProgram` over qualified
  CapabilitySpecs.
- Tool names, graph connectivity, successful traces and model consensus may
  guide planning but cannot create a new Task meaning.
- A capability without a Need/Brief anchor or discriminating S1 qualification
  cannot enter Task synthesis.
- New unsupported semantics return to S1 and require a newly qualified release;
  S2 cannot patch its own truth.

### R3. Deterministic TaskBlueprint generation

S2 compiles bounded GoalPrograms from the qualified capability algebra:

```text
Atom          achieve or query one capability binding
Select        filter/rank publicly describable candidates, then evaluate a child
If            choose a branch from a start-state public/qualified condition
All           require compatible child goals
ForEach       apply a child goal to every selected binding
Report        return a deterministic structured result
```

- Every node has a named compiler, checker rule, renderer and fingerprint.
- Composition uses qualified read/write scopes and fresh execution; it never
  concatenates unrelated capabilities merely to increase length.
- Unsupported operator/capability combinations are rejected explicitly.
- LLMs may rank or propose typed candidates, but host validation and compilation
  are deterministic.

### R4. Native-backed parameterized instantiation

For every sampled StartRecipe:

1. reset a fresh isolated instance;
2. capture the public reset observation and protected semantic facts;
3. enumerate qualified BindingCandidates;
4. instantiate Blueprint slots and selector rules;
5. prove the initial TaskChecker is false and the target is unambiguous under
   the Blueprint semantics;
6. freeze start facts, protected bindings and checker identity before witness
   planning.

A TaskBlueprint is parameterized and may yield multiple TaskPacks across starts
and bindings. Instance count is not treated as semantic diversity.

### R5. Checker-before-witness independence

- `TaskChecker` is compiled only from the exact GoalProgram, pre-execution facts,
  protected bindings, capability evaluators, answer schema and declared process
  rules.
- Its bytes/configuration and digest are frozen before the witness planner runs.
- The reference trace, planner reasoning and returned answer are never inputs to
  checker construction.
- The checker evaluates protected before/after facts, the host-owned public
  trace and the parsed final answer; it never requires reference-path equality.
- S2 uses no LLM Judge for final Task satisfaction.

### R6. Public-only constructive witness

- A host-controlled tool-calling planner receives only the same public surface
  and Task projection available to a later actor.
- Its successful execution is compiled into a restricted `WitnessRecipe` whose
  values are references to Task slots, reset-observation fields, public constants
  or prior successful tool outputs, plus deterministic local selectors.
- Every argument carries machine-checkable provenance. A literal with no public
  origin rejects the candidate.
- The WitnessRecipe is replayed on at least one fresh equivalent start and must
  satisfy the already-frozen checker.
- Redundant calls, distractors and accidental refusals do not become required
  Task steps. Tool count is not a difficulty label.

Graph search, beam search, random walk or generated programs may later optimize
this planner, but none is part of the Task semantics or a mandatory lane.

### R7. Instruction generation and semantic integrity

- S2 renders the instruction only after Blueprint, start, checker and witness are
  established.
- Canonical rendering uses qualified public labels and bounded GoalProgram
  templates. An optional LLM paraphrase is admitted only when it round-trips to
  the same structured instruction frame.
- Mechanical audits reject protected values, native field names, undeclared
  constraints, tool names, answer leakage and reference-order hints.
- Independent actor trials must not expose a repeatable alternate interpretation
  accepted by the wording but rejected by the checker.

### R8. Adversarial admission

Admission executes, where applicable:

- positive witness and fresh witness replay;
- no-op;
- wrong target/binding;
- boundary near miss;
- partial `All`/`ForEach` completion;
- correct goal plus collateral action;
- wrong or stale structured answer;
- same outcome through an alternative public path;
- process-rule violation reaching the same terminal outcome.

S1 physical negatives establish atomic inspector/evaluator sensitivity. S2
challenges establish Blueprint composition, selection, answer and instruction
sensitivity. Syntax failures, crashes and unreachable mutations do not count as
semantic evidence.

### R9. Independent actor trials and utility evidence

- At least one acting model/policy lineage is independent of the capability
  author, instruction renderer and witness planner.
- Trials run through the same public actor surface and frozen TaskChecker.
- Results measure wording recoverability, practical feasibility, tool/token
  cost, reliability and empirical difficulty; they do not replace constructive
  solvability.
- A logically solved Task with systematic independent-agent failure is rejected
  for the current corpus until its wording, observability or target policy is
  causally corrected.
- The trial runner is a shared actor-loop component later reused by S3 rather
  than independently reimplemented.

### R10. Structural corpus selection

Each admitted Task receives a deterministic fingerprint including:

```text
capability IDs and effect signature
GoalProgram AST shape
selector/facet operators
entity/relation count
public binding depth
state regime and refusal role
answer/process requirements
witness control-flow and cost
empirical difficulty band
```

- Deduplication happens first at Blueprint/checker equivalence, then at public
  text similarity.
- Corpus policies declare target distributions and budgets explicitly.
- Selection may use stratification, novelty search or quality-diversity
  algorithms, but no internal coverage score is called complete Task-space
  coverage.
- Final value is established by matched-budget held-out SFT/RL evaluation.

### R11. TaskPack and S3 handoff

The public projection contains only:

```text
TaskPack ID and exact release ID
natural-language instruction
actor-visible reset context
public process constraints
structured final-answer schema
public limitations
```

The protected projection contains only material required by S3:

```text
StartRecipe and protected start facts/bindings
GoalProgram and frozen TaskChecker
WitnessRecipe and solvability evidence
challenge and independent-trial evidence
semantics-bundle references/digests
fingerprint and quality report
```

S2 does not define optimizer batches, SFT token masks, RL advantages or a model-
specific tool-call envelope.

### R12. Fail closed without hidden fallback

- Provider, dependency, timeout and runner defects retain exact identities and
  return `InfrastructureFailure`.
- Reproducible release/runtime/semantics defects return `ReleaseDefect` with
  public calls and protected evidence sufficient for S1 requalification.
- Candidate defects return a typed rejection reason; they are not relabeled as
  high difficulty.
- No fallback LLM Judge, hard-coded domain evaluator, compatibility reader,
  native setup patch or canned Task may turn a failure into admission.

## Acceptance criteria

- [ ] `EnvironmentRelease v2` binds a protected SemanticsBundle, start-case
  generator and public preparation/open runtime, all cold-verifiable by digest.
- [ ] The same frozen S1 framework produces and qualifies taskable capability
  contracts for the existing SQLite-backed environment and filesystem/Git
  environment without domain branches.
- [ ] Every declared taskable capability either yields an admitted atomic
  TaskPack or an evidence-backed unsupported reason; silent omission is invalid.
- [ ] Every GoalProgram node declared supported by the conformance releases has
  at least one full real execution through instantiation, checker freeze,
  public witness, fresh replay, instruction audit and adversarial admission.
- [ ] No admitted witness argument originates from protected state.
- [ ] Every admitted mutation Task starts with a false goal and performs a real
  qualified state transition; query answers are derived from public execution.
- [ ] Checker challenges kill no-op, wrong-target, near-miss, partial,
  collateral and wrong-answer cases applicable to the Blueprint, and accept a
  genuinely different valid route when one exists.
- [ ] An S3-shaped consumer recreates and verifies admitted TaskPacks solely from
  their frozen public/protected projections.
- [ ] After generic code, prompts and contracts are frozen, a held-out Need
  produces a release and admitted Tasks without adding framework domain fields,
  evaluator branches or Task templates.
- [ ] Matched-budget experiments compare the new system with LLM-only Task
  generation, execution-filtered trajectory abstraction and the previous
  Graph/Programmatic proposal, reporting yield, replay, verifier sensitivity,
  structural diversity, cost and downstream generalization.
- [ ] Ruff, mypy, unit/integration tests and all real cold cross-domain trials
  pass; fixture-only tests never authorize product completion.

## Fatal rejection criteria

The method must be reconsidered rather than cosmetically patched if any of these
persist after causal debugging:

- held-out releases require framework code containing domain names or native
  field rules;
- qualified capability contracts cannot achieve high physical-negative
  sensitivity without human task-specific repair;
- public witness replay succeeds only by leaking protected bindings;
- checker false acceptance remains material under wrong-target or collateral
  challenges;
- Task yield collapses for releases whose actor surface is otherwise complete;
- structural diversity does not improve matched-budget held-out training or
  evaluation relative to simpler baselines;
- the same model-authored semantics repeatedly cause correlated environment,
  checker and Task errors that independent Qualification cannot detect.

## Out of scope

- compatibility with `environment-package/1` or the previous S2 documents;
- subjective creative-writing or other Tasks whose success cannot be reduced to
  qualified deterministic state/answer/process evidence;
- MCP, HTTP or provider-specific tool-call envelopes as environment semantics;
- S3 trajectory persistence and scalar reward mapping;
- S4 optimizer/training implementation;
- claims of universal Task-space coverage.

## Planning status

This task remains `planning`. The PRD, design, implementation plan and worker
context manifests must be reviewed as one coherent proposal. Product code and
`task.py start` require a later explicit user approval of that final summary.

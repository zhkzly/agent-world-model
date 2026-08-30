# S2 Good-Task Sampling Foundry

## Status and authority

This PRD supersedes the deletion-first interpretation that treated a small
Capability-to-Task vertical as complete S2. Commit `189be1b` is retained as a
real executable checkpoint, not as paper-grade S2 completion.

S2 begins with an immutable qualified `EnvironmentRelease` and ends with a
quality-controlled Task corpus suitable for later tool-calling Agentic RL
rollouts. S2 does not generate reward, trajectories, token masks or training
updates; those belong to S3/S4.

There is no compatibility requirement for pre-clean-break releases or Task
formats.

## Product goal

```text
EnvironmentRelease
-> grounded Candidate Task sampling
-> frozen Task semantics and concrete public binding
-> public-only solving on real tools
-> deterministic truth and adversarial verification
-> admitted TaskPack
-> model-relative TaskAssessment
-> structurally selected CorpusManifest
```

The output must be useful as the Task/reward-truth input to a future Agentic RL
episode runner. A real environment, a successful trace, three admitted Tasks,
green tests, or an identity-bearing ZIP is evidence for a slice, never evidence
that S2 sampling is complete.

## Inputs from S1

S2 consumes only sealed S1 authority:

- exact EnvironmentRelease identity and cold preparation;
- public `reset/tools/invoke/close`, schemas and structured observations;
- accepted Need/Requirement anchors and qualified CapabilitySpecs;
- deterministic StartCases and public binding candidates;
- protected, read-only release-local TaskSemantics.

S2 may request a narrowly demonstrated S1 fix, such as a missing public operand
or reloadable truth route. It must not demand a universal ontology, State IR,
generic snapshot importer, persistent graph, reward field or S2-specific
domain schema from S1.

## Candidate Task sampling

S2 requires at least two complementary proposal mechanisms:

1. **Graph sampler** — explores real public tool dependencies and propagates
   values from actual ToolObservations into later calls.
2. **Programmatic sampler** — proposes a bounded parameterized public solution
   program, executes and repairs it on a disposable instance, and derives a
   Candidate Task only from the successful public execution and Need anchors.

The existing deterministic Capability/Goal compiler remains a grounded direct
baseline. Graph, Programmatic and direct proposals all emit one ephemeral
`CandidateTaskProposal`; they are not separate product ABIs, Task truth sources
or persistent Task types.

Execution proves reachability, not meaning. Candidate meaning must remain
anchored to accepted S1 Requirements rather than being invented from a trace.

## Good Task hard gates

Every admitted TaskPack must satisfy all six intrinsic properties.

### 1. Bidirectionally anchored and well-posed

- every checker predicate and process constraint has a public Requirement,
  instruction or public-schema entailment;
- every publicly applicable Requirement obligation is included or has a frozen,
  reviewable reason why it is irrelevant to this Task;
- the instruction states every load-bearing constraint without exposing hidden
  fields, a reference route or an answer key.

### 2. Publicly closed and solvable

- the acting policy sees only the final instruction, public reset observation,
  ToolSpecs and ToolObservations;
- every target, argument, condition operand and answer operand has exact public
  provenance;
- the exact frozen Task succeeds on at least two fresh materializations.

### 3. Reliably verifiable and path-open

- the checker evaluates frozen outcome/effect/answer and declared process truth,
  not reference-trace equality;
- applicable no-op, wrong-entity, near-miss, partial, omitted-obligation,
  collateral, wrong-answer and process violations are rejected;
- a known constructible alternative valid route is accepted. Absence of a
  second discovered route is reported, not treated as proof of path closure.

### 4. Non-vacuous and answer-opaque

- mutation/process Tasks are false at Start and after no-op;
- query Tasks reject blank, stale, unsupported or ungrounded answers;
- reset, instruction and descriptors do not reveal expected dynamic answers.

### 5. Replayable and isolated

- Start, logical binding, public operands and checker truth agree across fresh
  instances;
- dynamic IDs may change but are rediscoverable from the public surface;
- when persistence is claimed, the acting process is closed and the same native
  instance is reopened before final protected verification;
- one episode cannot inherit another episode's business state.

### 6. Minimally purposeful

- the Task expresses one coherent Need-anchored business objective;
- declared tools/process milestones are causally necessary for binding,
  branching, required effects or required evidence;
- arbitrary tool stitching is excluded, and retained constructive witness
  evidence is pruned to its causal support. A checker still accepts harmless
  exploratory calls on another otherwise valid route.

## Verification ownership

Framework freezes the parameterized semantic section of one
`TaskSpecification` before Start materialization: objective, quantifiers, public
slot constraints, required/allowed/forbidden effects, answer semantics and
genuinely required process milestones. After Start, a binding section may fill
those slots only with public-provenance values; it cannot change predicates or
answer meaning. The complete bound TaskSpecification freezes before witness
search.

A bounded task-local `VerifierBundle` is compiled from that specification and
the already-qualified S1 TaskSemantics. It is an evaluation plan, not
unrestricted model-authored Python and not a universal verifier DSL. Witness
state may instantiate dynamic values but cannot add, remove or weaken
predicates.

If candidate semantics change, restart from TaskSpecification. If verifier
implementation changes, rerun all applicable challenges.

## Task corpus quality

Task validity and corpus selection are separate.

`TaskAssessment` records fresh model-relative trials, success/failure classes,
tool calls, tokens and latency without changing TaskPack truth.

`CorpusManifest` selects exact TaskPack/Assessment pairs using:

- semantic and execution structure rather than paraphrase similarity;
- Goal, capability, state regime, information-dependency and constraint shape;
- redundancy control;
- difficulty gradient and policy discrimination;
- declared SFT/RL purpose and rollout budget.

Corpus targets are preregistered experiment/reporting expectations, not a way
to waive an individual Good Task gate. S2 may return typed low-yield or
unsupported outcomes rather than manufacture Tasks.

## S2 to S3 handoff

S2 publishes a strict cold-readable TaskPack and a minimal `PublicTaskView`.

The S3 host sees TaskPack identity, StartRecipe and VerifierBundle. The acting
policy sees only:

```text
canonical instruction
public reset observation
ToolSpecs
ToolObservations
final-answer schema
```

S2 does not expose semantic keys, expected branches, protected bindings,
checker data, witness traces or answers to the acting policy.

## Current checkpoint evidence

The current branch has real reusable foundations:

- Git and SQLite cold releases;
- public Agent tool execution and structured observations;
- checker-before-instruction ordering;
- Atom/ForEach/If compilation;
- two fresh public witnesses and basic negative checks;
- argument provenance;
- TaskPack/TaskAssessment/Corpus identity separation.

It is not complete because Candidate sampling, bidirectional coverage,
task-local verification challenges, physical reload, strict TaskPack cold read,
held-out transfer and corpus-quality evidence remain incomplete. The observed
SQLite Task that said “reopen” but only queried in the same process is the gold
failure case this correction must reject.

## Acceptance criteria

- Graph and Programmatic samplers execute real public tools and feed one common
  CandidateTaskProposal boundary; direct compilation remains a baseline.
- Candidate semantics freeze before concrete witness search and cannot be
  repaired from witness/verifier outcomes in place.
- bidirectional Requirement coverage is explicit and fail-closed;
- every admitted Task passes public solvability, provenance, non-vacuity,
  replay/isolation and all applicable physical challenges;
- persistence claims include real close/reopen evidence;
- strict TaskPack cold read recomputes identities and produces a non-leaking
  PublicTaskView;
- Git, SQLite and one post-freeze held-out release run without Framework domain
  branches;
- sampler proposal/yield/rejection, unique structure, redundancy, difficulty and
  cost are reported under fixed budgets;
- at least two acting policies or checkpoints provide model-relative assessment;
- deterministic tests, mutation licenses, Ruff, formatting, Mypy, lock and diff
  checks pass, and real run artifacts are retained outside source authority.

## Forbidden

- restoring old TaskIntent/WitnessSet, dual readers, feature flags or v1 ABI;
- GraphTask and ProgrammaticTask as persistent product types;
- a universal world ontology, State IR, unrestricted verifier code or large
  generic DSL;
- native writes, hidden setup calls or protected operands during public solving;
- learning Task meaning, allowed effects or answer truth from witness diffs;
- mandatory Cartesian challenge matrices, every-parameter perturbation, fake
  boolean mutation or exhaustive route replay;
- domain-specific Framework branches or hard-coded booking/Git/SQLite Tasks;
- claiming corpus quality from Task count, text variety, tool count or one model;
- implementing S3 reward, training trajectories or veRL integration inside S2.

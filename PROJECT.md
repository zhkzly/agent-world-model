# Canonical Agent Environment and Task Foundry

## Product intent

Build a paper-grade system that turns a natural-language business Need into a
real executable Agent environment, samples high-quality training Tasks from
that environment, and supplies verified Episodes to later SFT/RL consumers.

Semantic completion is the product criterion. A demo, MVP, mock, dictionary
world, canned Task, one successful trace, green unit suite or package-shaped
artifact is never sufficient evidence.

## Product lifecycle

```text
natural-language Need
-> S1 Environment Foundry
-> qualified immutable EnvironmentRelease
-> S2 execution-first Good-Task Sampling Foundry
-> verified TaskPacks + TaskAssessments + CorpusManifest
-> S3 acting-Agent Episodes + deterministic Reward/abstention
-> S4 SFT/RL
```

## S1 owns the executable environment

S1 researches the Need, builds one real uv-managed actor project, executes real
public tools against real persistent state, qualifies environment behavior and
publishes immutable bytes.

The Release exposes two mechanically separated surfaces:

```text
public actor
  reset / tools / invoke / close

protected trusted surface
  task-neutral read_state over real persistent facts
```

S1 validates actor build/lock identity, ToolSpec and observation schema
conformance, reset/replay, persistence, isolation, protected readback,
packaging, relocation and cold preparation. It does not publish TaskSpace,
CapabilitySpecs, Goal programs, answers, concrete Tasks, sampling traces,
Task-specific checkers, rewards or training trajectories.

Before publication, one fresh semantic reviewer receives the frozen
Need-derived BuilderProjection, public ToolSpecs and complete Host-executed
diagnostic observations with protected before/after state. It judges every
frozen Requirement exactly once and cites only Host-assigned evidence
references. Missing evidence fails. Framework derives coverage, identities and
the release verdict; Builder tests and self-report cannot establish acceptance.

Qualification evidence proves that the Release is usable. It is not a complete
TaskSpace and S2 must not repackage it as the Task corpus.

## S2 owns sampling Good Tasks

The sole S2 production path is:

```text
Need + Development Brief + required coverage target
-> generic Sampling Agent acts through public tools on a fresh instance
-> TaskDraft selects a coherent Goal from actual public events
-> Host resolves public provenance, AnswerProjection and protected effects
-> Host derives a type-only final-answer schema
-> fresh public reference replay through one common evaluator
-> freeze Candidate Goal/evidence/instruction
-> five fresh public-only Agent runs, at least two passing
-> TaskPack
-> separate TaskAssessment
-> CorpusManifest
```

The Sampling Agent owns environment-specific semantic exploration. It may
inspect, branch, iterate and mutate only through public tools. It cannot read
protected state, author an answer schema, provide expected native facts, write a
Checker or decide admission.

Framework owns SamplingTarget scheduling, public dispatch, trace capture,
argument provenance, AnswerProjection resolution, protected before/after
capture, Goal materialization, fresh replay, common evaluation, identity,
admission and corpus selection.

S2 uses no Tool Graph, random walk, generated TaskSemantics, solution/verifier
program or per-Task Checker. Adding a new Release may add artifacts and
measurements but cannot add Framework domain branches or generated evaluator
code.

### Goal and answer boundary

Tasks use typed `AtomGoal`, `AllGoal`, `IfGoal` and `ForEachGoal` data.
Unsupported shapes remain typed outcomes and are never fabricated.

Every load-bearing operand comes from an exact Task literal, reset observation
or prior ToolObservation. An unnamed target must be uniquely determined by
public evidence; ForEach uses a complete initial public member set. If uses a
public scalar observed before its branch action.

AnswerProjection copies or assembles public JSON values. Framework derives its
type-only transport schema from the referenced public schemas. Constants and
expected values remain trusted evaluator data and are not leaked through
schema `const` fields.

### Good Task intrinsic gates

Every admitted Task must be:

- **publicly solvable:** sampling produced one public solution and at least two
  of five fresh public runs also pass;
- **reliably verifiable:** one domain-free common evaluator checks real
  state, public outcome and grounded final answer without sampling-trace
  equality;
- **well-posed:** every load-bearing constraint is public and deterministic for
  the frozen reset, while the answer and solution route are hidden;
- **non-trivial:** no-op, unsupported claims and already-satisfied mutation
  goals fail;
- **replayable and isolated:** fresh instances reconstruct the Start and Goal
  without shared episode state;
- **purposeful:** objective events form one Need-related user intent without
  arbitrary tool stitching or decorative required calls.

### Task corpus quality

Task validity and corpus selection are separate. A corpus additionally needs:

- semantic/execution structure diversity rather than paraphrase diversity;
- redundancy control;
- balanced Goal shape, public tool, outcome, binding and condition/member
  coverage under a declared sampling budget;
- model-relative difficulty/cost evidence;
- later held-out training utility evidence.

Simple coverage counters select required shape/tool/outcome targets. They never
prescribe a tool chain. Counts and floors are experiment targets, never
permission to weaken a Task.

## S3 owns verified policy Episodes

S3 consumes exact current Release/TaskPack/Corpus authority:

```text
cold Release + TaskPack
-> freeze EpisodeRequest and public projection
-> target policy calls real public tools
-> preserve complete success or failure trajectory
-> close and reopen the same native instance
-> run the frozen common Goal evaluator
-> map truth to binary Reward or typed abstention
-> persist EpisodeRecord / TrainingEpisodeView / EpisodeBatchManifest
```

S3 does not generate or re-admit Tasks, alter Goal truth, choose another corpus
or train a model. The acting policy sees only instruction, fresh reset
observation, ToolSpecs, prior ToolObservations and the type-only answer schema.
It never sees S2 sampling/filter evidence, protected Goal data, expected
branch/member sets, native facts or evaluator internals.

The initial reward contract is:

```text
verified success                         -> 1.0
valid policy episode but Task not met    -> 0.0
untrustworthy infrastructure/truth path  -> null / abstain
```

## Execution ownership

### Framework Python

Owns environment conformance/publication, release preparation, identities,
SamplingTarget scheduling, public execution capture, Goal/evidence freeze,
AnswerProjection/schema materialization, common evaluation, admission,
structural deduplication, TaskPack persistence, assessment/corpus recording,
Episode lifecycle, Reward/abstention and cold artifact projections.

### Python Codex SDK

Authors the S1 executable actor environment, including task-neutral protected
state readback. S2 does not ask Codex SDK to author Task-specific code.

### OpenAI Responses tool-calling policy

Performs S2 execution-first Task sampling, five independent recoverability
runs, model-relative assessment and S3 target-policy Episodes. Filtering and S3
policies never see protected Goal data, sampling solutions or answer keys.

## Non-negotiable constraints

1. Public tools execute real project code and real persistent transitions.
2. Protected state verifies sampled Tasks but never supplies acting operands.
3. A Candidate requires successful objective execution and a passing fresh
   reference replay before it exists.
4. Goal evidence and final instruction freeze before filter/S3 policy runs.
5. All five filter outcomes must be valid; at least two must pass.
6. Serial versus concurrent execution is scheduling only and cannot change
   Task identity or admission.
7. LLM agreement cannot override deterministic execution/state failure.
8. Acting starts are reset-only; no hidden setup calls or native writes.
9. Framework contains no booking/SQLite/Git/domain branches.
10. Sampling execution proves one public solution, never the only valid path.
11. TaskPack identity excludes assessment, difficulty, corpus policy and Episodes.
12. Episode reward cannot change Task truth or use TaskAssessment reliability.
13. Provider/trust defects abstain rather than become model reward zero.
14. Unsupported semantics and low yield do not revoke a valid Release.
15. Only current clean-break formats are supported; no compatibility switch.
16. Intermediate checkpoints, candidate counts and successful demos are never
    stage completion.

## S2 completion evidence

S2 completes only when the frozen production implementation:

- samples, freshly replays, deduplicates and admits Tasks through one batch API;
- cold-consumes all 20 exact S1 Release/3 artifacts without domain edits;
- produces real Atom/All/If/ForEach query, transition and refusal Tasks only
  where public execution and Host evidence support them;
- completes five valid fresh runs and at least two passes for every admitted
  TaskPack;
- cold-reads relocated TaskPacks into a non-leaking PublicTaskView and trusted
  Goal/evaluator view;
- reports honest yield, rejection attribution, tool/Goal distribution,
  redundancy and model-relative cost/difficulty;
- provides the exact Task/truth handoff needed by S3 while leaving Reward and
  training implementation to S3/S4.

## S3 completion evidence

S3 completes only when one frozen runtime:

- consumes relocated Release, TaskPack and Corpus artifacts;
- preserves complete trajectories for verified success and policy failure;
- evaluates Atom, All, ForEach and If after real close/reopen without
  sampling-trace matching;
- produces physical `1.0`, `0.0` and typed `null`/abstain outcomes with
  correct causal ownership;
- cold-reads immutable EpisodeRecord and non-leaking TrainingEpisodeView;
- supports current Responses and one later S4 policy adapter through the same
  restricted Host path;
- hands S4 public trajectories and reward labels without implementing trainer,
  tokenization, logprob or optimizer code.

# Canonical Agent Environment and Task Foundry

## Product intent

Build a paper-grade system that turns a natural-language business Need into a
real executable Agent environment and samples high-quality training Tasks from
that environment.

Semantic completion is the product criterion. A demo, MVP, mock, dictionary
world, canned Task, one successful trace, green unit suite or package-shaped
artifact is never sufficient evidence.

## Product lifecycle

```text
natural-language Need
-> S1 Environment Foundry
-> qualified immutable EnvironmentRelease
-> S2 Direct Good-Task Sampling Foundry
-> verified TaskPacks + TaskAssessments + CorpusManifest
-> S3 acting-Agent Episodes + deterministic Reward/abstention
-> S4 SFT/RL
```

## S1 owns the executable environment

S1 researches the Need, builds one real uv-managed actor project, executes real
public tools against real persistent state, qualifies environment behavior and
publishes immutable bytes.

The release exposes two mechanically separated surfaces:

```text
public actor
  reset / tools / invoke / close

protected trusted runtime
  task-neutral read_state over real persistent facts
```

S1 validates actor build/lock identity, ToolSpec and observed schema
conformance, reset/replay, persistence, isolation, protected readback,
packaging, relocation and cold preparation. It does not publish CapabilitySpecs,
conditions, qualification goals, answer fields, positive/noop Task cases,
TaskSemantics, task-specific auditors, concrete Tasks, reference traces, Task
checkers, corpus cells, rewards or trajectories.

Physical conformance is necessary but not sufficient. Before publication, one
fresh semantic reviewer receives the frozen Need-derived BuilderProjection,
public ToolSpecs and complete Host-executed diagnostic observations with
protected before/after state. It must judge every frozen Requirement exactly
once and cite only Host-assigned evidence references. Missing evidence is a
failure. Framework derives coverage, identities and the release verdict; the
Builder's tests, scenario expectations and self-report cannot establish
semantic acceptance. The accepted projection, physical evidence and review are
bound into the Release evidence without creating Tasks, answers or rewards.

The protected state projection is environment-specific but Task-neutral. It
allows S2 checkers to read real before/after facts after close/reopen; it never
defines success and is never visible to an acting policy.

## S2 owns sampling good Tasks

The required S2 path is Direct proposal and physical admission over one exact
release:

```text
Need + Development Brief + public ToolSpecs + fresh execution
-> Candidate Task proposal
-> one sealed TaskContract and task-specific checker
-> freeze checker and final instruction
-> two fresh public-only Agent executions
-> real before/after state, answer and applicable physical challenges
-> TaskPack
-> separate TaskAssessment
-> CorpusManifest
```

The proposal Agent can suggest a Task but cannot seal truth. One checker project
is the sole semantic authority for one candidate Task. It consumes real
before/after state, public trace and final answer; independent Agents may
challenge and reject it but cannot create a second peer truth program or mutate
an admitted contract. A failed Task candidate never invalidates its
EnvironmentRelease.

Graph and Programmatic are optional sampler/search experiments. They may be
evaluated only after the Direct path demonstrates a concrete coverage gap, and
must be removable when matched-budget evidence shows no useful non-redundant
Task gain. They are never required product nodes or Task semantic authority.

### Good Task intrinsic gates

Every admitted Task must be:

- **publicly solvable** using only instruction, reset context, ToolSpecs and
  ToolObservations;
- **reliably verifiable** by deterministic outcome/answer/collateral checks that
  do not require witness-trace equality;
- **well-posed**: all load-bearing constraints are public, but the solution path
  and answer key are not leaked;
- **non-trivial**: no-op, unsupported claims and already-satisfied mutation
  goals fail;
- **replayable and isolated** across fresh instances, with dynamic references
  rediscovered publicly and declared persistence checked after real reopen;
- **purposeful**: one natural Need-anchored objective, without arbitrary tool
  stitching or decorative witness calls.

### Task corpus quality

Task validity and corpus selection are separate. A corpus additionally needs:

- semantic/execution structure diversity rather than paraphrase diversity;
- redundancy control;
- balanced capability, Goal, Start and condition coverage under a declared
  sampling budget;
- model-relative difficulty/cost evidence;
- later held-out training utility evidence.

Counts and floors are experiment targets, never permission to weaken a Task.

## S3 owns verified policy Episodes

S3 consumes exact current Release/TaskPack/Corpus authority and records what a
target acting policy actually does. Its required order is:

```text
cold Release + TaskPack
-> freeze EpisodeRequest and public projection
-> target policy calls real public tools
-> preserve complete success or failure trajectory
-> close and reopen the same native instance
-> execute the frozen Task checker
-> map truth to binary Reward or typed abstention
-> persist EpisodeRecord / TrainingEpisodeView / EpisodeBatchManifest
```

S3 does not generate or re-admit Tasks, alter a checker, choose another corpus or
train a model. It must retain policy failures rather than only successful
witnesses and must distinguish model/policy failure from provider,
environment, semantics, verifier and evidence defects.

The initial base reward contract is:

```text
verified success                         -> 1.0
valid policy episode but Task not met    -> 0.0
untrustworthy infrastructure/truth path  -> null / abstain
```

The acting policy sees only the canonical instruction, fresh reset observation,
ToolSpecs, prior ToolObservations and final-answer schema. It never sees S2
witnesses/admission, Start input as a hint, semantic keys, protected bindings,
expected branch, native facts or checker internals.

S3 owns one small public PolicyDriver boundary and one shared Host execution
path. The current Responses driver and a later S4 rollout driver must use that
same path; there is no second Agent loop, service or Registry.

## Execution ownership

### Framework Python

Owns environment conformance/publication, release preparation, identities,
TaskContract/checker freeze and execution, instruction rendering, provenance,
admission, structural deduplication, TaskPack persistence, assessment
recording, corpus selection, Episode lifecycle, deterministic
Reward/abstention and cold artifact projections.

### Python Codex SDK

Authors only isolated semantic code projects:

1. the S1 executable actor environment, including task-neutral protected state
   readback;
2. one S2 task-specific checker for each candidate Task that reaches checker
   authoring.

Generated code never decides release admission, Task admission, identity or
reward.

### OpenAI Responses tool-calling policy

Runs the exact frozen public Task for S2 solvability witnesses, S2 model-relative
assessment and S3 target-policy Episodes. It never sees protected bindings,
native facts, checker internals, a reference path or answer key. S3 may also be
driven by a later S4 policy adapter through the same restricted public
interface.

## Non-negotiable constraints

1. Public tools execute real project code and real persistent transitions.
2. Protected state may propose and verify a Task but never supply acting operands.
3. Checker and final instruction freeze before the witness or target policy executes.
4. The policy solves exactly the instruction exposed by the TaskPack.
5. LLM agreement cannot override deterministic execution/state failure.
6. Acting starts are reset-only; no hidden setup calls or native writes.
7. Framework contains no booking/SQLite/Git/domain branches.
8. Witness proves existence of a public solution, never the only valid path.
9. TaskPack identity excludes assessment, difficulty, corpus policy and Episodes.
10. Episode reward cannot change Task truth or use TaskAssessment reliability.
11. Provider/trust defects abstain rather than become model reward zero.
12. Unsupported semantics and low Task yield remain typed outcomes; they do not revoke a valid Release.
13. Only current clean-break formats are supported; no compatibility switch.
14. Intermediate checkpoints, candidate counts and successful demos are never stage completion.

## S2 completion evidence

S2 completes only when the frozen Direct Framework:

- samples, deduplicates and admits Tasks through the production batch API;
- cold-consumes contrasting filesystem/Git and SQLite releases;
- produces real query, state-change, refusal, collection/condition and composed
  Tasks only where executed environment evidence supports them;
- proves fresh public solvability, reload/isolation and applicable negative
  discrimination for every admitted TaskPack;
- cold-reads relocated TaskPacks into a non-leaking PublicTaskView;
- reports honest yield, rejection attribution, redundancy, distribution and
  model-relative cost/difficulty;
- transfers to a post-freeze held-out Need without domain edits;
- provides the exact Task/truth handoff needed by S3 while leaving scalar reward
  and training implementation to S3/S4.

Optional Graph/Programmatic experiments are not completion gates.

## S3 completion evidence

S3 completes only when one frozen runtime:

- consumes relocated Release, TaskPack and Corpus artifacts;
- preserves complete public trajectories for verified success and policy
  failure;
- evaluates Atom, ForEach and If after real close/reopen without witness-trace
  matching;
- produces physical `1.0`, `0.0` and typed `null`/abstain outcomes with correct
  causal ownership;
- cold-reads immutable EpisodeRecord and non-leaking TrainingEpisodeView
  artifacts;
- runs Git, SQLite and the post-freeze held-out release without domain edits;
- supports the current Responses policy and one second policy/driver identity
  through the same restricted Host path;
- hands S4 public trajectories and reward labels without implementing trainer,
  tokenization, logprob or optimizer code.

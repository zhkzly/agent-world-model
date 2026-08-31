# Canonical Agent Environment and Task Foundry

## Product intent

Build a paper-grade system that turns a natural-language business Need into a
real executable Agent environment, samples high-quality training Tasks, records
trustworthy Episodes and proves whether the resulting data can improve an Agent.

Semantic completion is the product criterion. A demo, MVP, mock, dictionary
world, canned Task, one successful trace, green unit suite, falling loss or
package-shaped artifact is never sufficient evidence.

## Product lifecycle

```text
natural-language Need
-> S1 Environment Foundry
-> qualified immutable EnvironmentRelease
-> S2 Direct Good-Task Sampling Foundry
-> verified TaskPacks + TaskAssessments + CorpusManifest
-> S3 acting-Agent Episodes + deterministic Reward/abstention
-> S4 verified SFT/GRPO + checkpoints + held-out learning utility
```

## S1 owns the executable environment

S1 researches the Need, builds a real uv-managed actor project, executes real
public tools against real persistent state, independently qualifies reusable
environment semantics and publishes immutable bytes.

The release exposes two mechanically separated surfaces:

```text
public actor
  reset / tools / invoke / close

protected trusted runtime
  deterministic StartCases
  read-only native facts
  qualified CapabilitySpecs and Conditions
  binding enumeration
  atomic outcome/answer/process evaluation
```

S1 does not publish concrete Tasks, reference traces, Task checkers, corpus
cells, rewards or trajectories. It may expose environment-specific reusable
truth operations, but it must not preselect the S2 Task distribution.

## S2 owns sampling good Tasks

The required S2 path is Direct Goal-first sampling over one exact release:

```text
qualified Capability / StartCase / Binding / Condition
-> deterministic Candidate Task enumeration
-> semantic-structure deduplication and selection
-> freeze checker and final instruction
-> two fresh public-only Agent executions
-> real state/answer verification and applicable physical challenges
-> TaskPack
-> separate TaskAssessment
-> CorpusManifest
```

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
train a model. It retains policy failures and distinguishes them from provider,
environment, semantics, verifier and evidence defects.

The base reward contract is terminal and Task-level:

```text
verified success                         -> 1.0
valid policy episode but Task not met    -> 0.0
untrustworthy infrastructure/truth path  -> null / abstain
```

Individual tool calls receive Host parsing, schema, dispatch and observation
checks; they do not receive Task reward. The frozen checker evaluates the actual
post-reopen state, final answer and genuinely required process trace only after
the whole policy rollout terminates.

The acting policy sees only the canonical instruction, fresh reset observation,
ToolSpecs, prior ToolObservations and final-answer schema. It never sees S2
witnesses/admission, Start input as a hint, semantic keys, protected bindings,
expected branch, native facts or checker internals.

S3 owns one shared Host execution path. The current Responses driver and the S4
veRL rollout adapter must use the same tool-validation, trace, close/reopen,
checker and Reward path; there is no second environment/verifier runtime.

## S4 owns verified Agent learning

S4 consumes exact public Episode views and the same S3 online runtime. It must
answer whether the automatically generated environments, Tasks and Episodes
produce held-out learning gains.

The required order is:

```text
learning/data readiness
-> freeze one model/tokenizer/tool template and one exact veRL revision
-> verified-success SFT dataset
-> SFT checkpoint + S3 evaluation
-> veRL model-owned multi-turn rollout through the shared S3 Host
-> terminal S3 reward transported to GRPO
-> optimizer update + reloadable checkpoint
-> newly selected release-held-out evaluation
```

S4 does not reward individual tool calls in the initial path. It transports one
terminal `1.0` or `0.0` per trustworthy rollout after S3 verification; an S3
`abstain` is non-numeric and cannot enter optimization.

S4 owns model-side concerns only:

```text
target tokenizer/chat template
model-generated token IDs
response/tool-observation masks
log probabilities and GRPO groups
optimizer state and checkpoints
learning splits and matched evaluation
```

It cannot regenerate Tasks, change checker truth, use S2 witnesses as hidden
gold trajectories, expose protected state, or let a model judge override S3.

The initial product supports one target model family, one verified-success SFT
path, one pinned veRL Agent Loop integration and one SFT->GRPO path. Additional
algorithms, model families, shaping, curriculum and services require later
measured needs.

## Execution ownership

### Framework Python

Owns release preparation, identities, Direct candidate enumeration, checker
freeze/execution, instruction rendering, provenance, admission, structural
deduplication, TaskPack persistence, assessment recording, corpus selection,
Episode lifecycle, deterministic Reward/abstention, cold artifact projections,
learning splits and trainer-neutral dataset/run/checkpoint/evaluation manifests.

### Python Codex SDK

Authors only the three isolated S1 release-local projects:

1. executable actor environment;
2. protected TaskSemantics;
3. mutually blind qualification-only Native Auditor.

Generated code never decides release admission, Task admission, identity, reward
or learning evaluation.

### OpenAI Responses tool-calling policy

Runs the exact frozen public Task for S2 solvability witnesses, S2 model-relative
assessment and S3 target-policy Episodes. It never sees protected bindings,
native facts, checker internals, a reference path or answer key.

### Pinned veRL integration

veRL owns model rollout infrastructure, token/logprob collection, GRPO advantage,
optimization and checkpointing for S4. Foundry integration is an overlay against
one exact tested upstream revision. It drives the same S3 public Host runtime and
transports S3 terminal reward; veRL is not a second Task/verifier authority.

## Non-negotiable constraints

1. Public tools execute real project code and real persistent transitions.
2. Protected facts may select and verify a Task but never supply acting operands.
3. Checker and final instruction freeze before the witness or target policy executes.
4. The policy solves exactly the instruction exposed by the TaskPack.
5. LLM agreement cannot override deterministic execution/state failure.
6. Starts are reset-only; no hidden setup calls or native writes.
7. Framework contains no booking/SQLite/Git/domain branches.
8. Witness proves existence of a public solution, never the only valid path.
9. TaskPack identity excludes assessment, difficulty, corpus policy and Episodes.
10. Episode reward cannot change Task truth or use TaskAssessment reliability.
11. Provider/trust defects abstain rather than become model reward zero.
12. S4 cannot turn tool-call validity or final text alone into Task success.
13. S4 cannot coerce `abstain` to numeric reward or silently replace it.
14. Model-generated tokens must be preserved exactly; tool-observation tokens are
    masked out of policy loss.
15. Only current clean-break formats and one frozen veRL revision are supported;
    no compatibility switch or moving-main dependency.
16. Intermediate checkpoints, candidate counts, falling loss and successful
    demos are never stage completion.

## S2 completion evidence

S2 completes only when the frozen Direct Framework:

- samples, deduplicates and admits Tasks through the production batch API;
- cold-consumes contrasting filesystem/Git and SQLite releases;
- produces real query, state-change, refusal, collection/condition and composed
  Tasks only where the release supports them;
- proves fresh public solvability, reload/isolation and applicable negative
  discrimination for every admitted TaskPack;
- cold-reads relocated TaskPacks into a non-leaking PublicTaskView;
- reports honest yield, rejection attribution, redundancy, distribution and
  model-relative cost/difficulty;
- transfers to a post-freeze held-out Need without domain edits;
- provides the exact Task/truth handoff needed by S3.

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

## S4 completion evidence

S4 completes only when one frozen learning path:

- reports sufficient data, split integrity and GRPO reward variance before
  training;
- pins one exact upstream veRL revision and one target model/tokenizer/template;
- deterministically produces a non-leaking assistant-only SFT dataset from
  verified-success Episodes;
- trains, saves, cold-loads and evaluates a real SFT checkpoint through S3;
- lets the veRL model itself generate exact multi-turn tool-call tokens while
  the shared S3 Host executes tools and terminal verification;
- proves model tokens use mask 1 and environment observation tokens use mask 0;
- binds every trainable rollout to one cold-valid Episode and matching terminal
  S3 reward;
- excludes `abstain` from optimization without turning it into zero;
- performs a nonzero-signal GRPO optimizer update and checkpoint resume;
- compares base, SFT and SFT->GRPO under one matched S3 evaluation budget;
- evaluates a newly selected release-held-out Need after code/config freeze;
- reports supported or unsupported learning utility without altering S1–S3
  truth.

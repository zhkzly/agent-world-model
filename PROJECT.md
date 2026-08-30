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

## Execution ownership

### Framework Python

Owns release preparation, identities, Direct candidate enumeration, checker
freeze/execution, instruction rendering, provenance, admission, structural
deduplication, TaskPack persistence, assessment recording and corpus selection.

### Python Codex SDK

Authors only the three isolated S1 release-local projects:

1. executable actor environment;
2. protected TaskSemantics;
3. mutually blind qualification-only Native Auditor.

Generated code never decides release admission, Task admission, identity or
reward.

### OpenAI Responses tool-calling policy

Runs the exact frozen public Task for solvability witnesses and independent
model-relative assessment. It never sees protected bindings, native facts,
checker internals, a reference path or answer key.

## Non-negotiable constraints

1. Public tools execute real project code and real persistent transitions.
2. Protected facts may select and verify a Task but never supply acting operands.
3. Checker and final instruction freeze before the witness Agent executes.
4. The witness solves exactly the instruction later exposed to S3.
5. LLM agreement cannot override deterministic execution/state failure.
6. Starts are reset-only; no hidden setup calls or native writes.
7. Framework contains no booking/SQLite/Git/domain branches.
8. Witness proves existence of a public solution, never the only valid path.
9. TaskPack identity excludes assessment, difficulty and corpus policy.
10. Unsupported semantics and low sampling yield remain typed outcomes.
11. Only current clean-break formats are supported; no compatibility switch.
12. Intermediate checkpoints and candidate counts are never S2 completion.

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
- provides the exact Task/truth handoff needed by S3 while leaving scalar reward
  and training implementation to S3/S4.

Optional Graph/Programmatic experiments are not completion gates.

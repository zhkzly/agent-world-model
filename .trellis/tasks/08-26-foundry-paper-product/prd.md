# Paper-grade Environment and Task Foundry

## Goal

Deliver a publishable system that converts a natural-language Need into a real
executable Agent environment, samples good training Tasks, verifies real Agent
episodes and produces SFT/RL evidence. Product completion means semantic
completion of the causal chain, never a demo, mock, canned Task or green suite.

## Product stages

```text
S1 Environment Foundry
  -> qualified immutable EnvironmentRelease

S2 Direct Good-Task Sampling Foundry
  -> admitted TaskPacks
  -> separate TaskAssessments and CorpusManifest

S3 Episode Runtime and Evaluator
  -> real public tool trajectory
  -> frozen Task verification and Reward/abstention

S4 SFT/RL
  -> datasets, optimizer runs, checkpoints and held-out evidence
```

The parent owns the cross-stage causal claim only; it is not another runtime
layer.

## Stage boundaries

### S1

S1 owns Research, the Development Brief, Codex-authored executable actor,
release-local protected semantics, independent native Qualification, process
isolation and immutable publication.

S1 may publish qualified atomic capabilities, conditions, StartCases, bindings
and reusable read-only evaluators. It does not publish Tasks, reference traces,
Task distributions, Task checkers, rewards or trajectories.

### S2

S2 samples good Tasks from one exact release through the Direct production path:

```text
Direct Goal/Start/Binding candidate enumeration
-> structural deduplication and selection
-> checker/instruction freeze
-> two fresh public solves
-> deterministic verification and physical challenges
-> TaskPack
-> TaskAssessment
-> CorpusManifest
```

Graph and Programmatic are optional experiments after a demonstrated coverage
gap. They are not required nodes and cannot define Task truth.

### S3

S3 recreates a TaskPack, gives only the public projection to the acting policy,
records real actions/observations/final answer and executes the frozen verifier.

### S4

S4 consumes exact Release/TaskPack/Episode identities. It cannot redefine
environment or Task truth.

## Trust boundary

```text
acting policy
  instruction + reset context + ToolSpecs + ToolObservations

trusted runtime
  reset recipe + protected binding + native facts + checker
```

Protected state may select and verify a Task but never provide an acting-time
operand. Model consensus cannot override deterministic failure.

## Current S2 scope

The active child owns completion of the existing Direct sampling, admission,
batch, assessment and corpus path plus minimum demonstrated S1 corrections.
Backward compatibility, mandatory Graph/Programmatic, Registry, S3 reward and
S4 training are outside the active implementation.

## Product acceptance

- [ ] S1 cold-publishes real actor and protected semantics projects with
  independent native Qualification.
- [ ] The production S2 API directly samples and structurally deduplicates
  candidates from exact Release capabilities/Starts/bindings/conditions.
- [ ] Every admitted Task is public-only solvable twice, non-trivial,
  reproducible and deterministically verifiable.
- [ ] Applicable no-op, wrong-target, partial, collateral and wrong-answer cases
  fail without enforcing one witness path.
- [ ] Declared persistence is verified after close/reopen of the same instance.
- [ ] TaskPack identity excludes model assessment and corpus selection.
- [ ] Git, SQLite and a post-freeze held-out Need run without Framework domain
  edits or weakened Task gates.
- [ ] Strict cold TaskPack read produces a non-leaking S3 PublicTaskView.
- [ ] Assessment/corpus reports difficulty, cost, redundancy and distribution
  separately from Task validity.
- [ ] Optional sampler experiments are retained only when matched-budget evidence
  shows additional useful non-redundant admitted Tasks.
- [ ] Exact artifacts reproduce the complete S1 -> S2 -> S3-shaped handoff.

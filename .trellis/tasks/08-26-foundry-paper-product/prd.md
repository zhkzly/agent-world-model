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

S3 Verified Episode Runtime
  -> complete public target-policy trajectory
  -> post-reopen frozen Task verification
  -> deterministic Reward/abstention
  -> EpisodeRecord and EpisodeBatchManifest

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

S3 runs an admitted TaskPack under a target policy. It freezes the Episode
request and public projection before acting, records the complete public tool
trajectory, closes and reopens the same native instance, executes the frozen
Task checker and maps the result to:

```text
verified success -> 1.0
valid policy failure -> 0.0
untrustworthy infrastructure/truth path -> null / abstain
```

S3 preserves failed policy trajectories and distinguishes them from provider,
Environment, Task artifact, Semantics, Verifier and evidence defects. It cannot
regenerate/re-admit Tasks, change checker truth, choose another corpus or train a
model.

The target policy receives only instruction, fresh reset context, ToolSpecs,
ToolObservations and final-answer schema. S3 may expose one restricted
PolicyDriver boundary for the current Responses adapter and a future S4 rollout
adapter, but no service, registry or second Agent loop.

### S4

S4 consumes exact Release/TaskPack/Episode identities and public trajectory
views. It may construct SFT/RL batches, but cannot redefine environment behavior,
Task truth or turn abstained evidence into a policy reward. The active S4 child
task, once explicitly accepted, owns its concrete learning experiment.

## Trust boundary

```text
acting policy
  instruction + reset context + ToolSpecs + ToolObservations

trusted runtime
  reset recipe + protected binding + native facts + frozen checker

S4 data consumer
  public trajectory + verified status/reward label
```

Protected state may select and verify a Task but never provide an acting-time
operand. Model consensus cannot override deterministic failure.

## Product acceptance

### S1/S2

- [x] S1 cold-publishes real actor and protected semantics projects with
  independent native Qualification.
- [x] The production S2 API directly samples and structurally deduplicates
  candidates from exact Release capabilities/Starts/bindings/conditions.
- [x] Every admitted Task is public-only solvable twice, non-trivial,
  reproducible and deterministically verifiable.
- [x] Applicable no-op, wrong-target, partial, collateral and wrong-answer cases
  fail without enforcing one witness path.
- [x] Declared persistence is verified after close/reopen of the same instance.
- [x] TaskPack identity excludes model assessment and corpus selection.
- [x] Git, SQLite and a post-freeze held-out Need run without Framework domain
  edits or weakened Task gates.
- [x] Strict cold TaskPack read produces a non-leaking S3 PublicTaskView.
- [x] Assessment/corpus reports difficulty, cost, redundancy and distribution
  separately from Task validity.

### S3

- [x] S3 preserves complete public trajectories for policy success and failure.
- [x] S3 evaluates every valid attempt only after closing/reopening the same
  native instance.
- [x] S3 produces physical `1.0`, `0.0` and typed `null` outcomes without causal
  conflation.
- [x] EpisodeRecord and TrainingEpisodeView cold-read after relocation and have
  exact trusted/public projections.
- [x] One direct batch API executes exact CorpusManifest entries and retains one
  honest success, failure, abstention or blocked result for every rollout slot.
- [x] Git, SQLite and held-out TaskPacks run through one target-policy runtime
  without domain edits.
- [x] S4 can consume public trajectories/reward labels without protected data or
  trainer code in S3.

### S4

- [ ] S4 produces real SFT/RL checkpoints and held-out evidence from public
  verified Episodes without changing S1–S3 truth.
- [ ] Exact artifacts and matched evaluation support or reject the bounded
  learning-utility claim.

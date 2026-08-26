# Paper-grade Foundry product

## Goal

Deliver a publishable system that converts an arbitrary natural-language need
into real executable agent environments, grounded Tasks, verified episodes and
real SFT/RL inputs. Product completion is semantic completion of the whole
causal chain, never a demo, mock, template, green unit suite or package-shaped
file.

## Product stages

```text
S1 Environment Foundry
  -> immutable qualified EnvironmentRelease
S2 Task Foundry
  -> release-bound, solvable and verifier-backed sealed TaskPack
S3 Episode Runtime and Evaluator
  -> grounded EpisodeRecord and attributable Reward
S4 SFT/RL Integrations
  -> real datasets, optimizer runs, checkpoints and evaluation evidence
```

Each stage is planned, implemented and independently accepted as its own child
task. The parent owns only the cross-stage causal chain and final integrated
claim; it is not an extra runtime stage.

## Stage boundaries

- S1 owns world generation, native execution, qualification and publication.
  Its output is a real generated uv project with meaningful initial state,
  `reset/tools/invoke/close`, ToolSpecs, uniform ToolObservations, public
  documentation, exact identity and qualification summary. It contains no
  Task/reward fields.
- S2 consumes an exact S1 release. It synthesizes Graph-based and Programmatic
  Task candidates, materializes their starting states, proves solvability by
  public execution, derives task truth and admits only Tasks with a tested
  task-local verifier.
- S3 recreates an admitted Task, runs the acting Agent's tool loop, preserves
  public and protected evidence separately, executes the verifier and attributes
  reward or abstention.
- S4 consumes only admitted identities and verified episode facts. Training has
  no authority to redefine environment or Task truth.

The stage boundary is complete: S2 Task-generation algorithms consume only the
released environment, schemas, public observations/docs and trusted access to
their own episode instance. They cannot require S1 to add Graph, Programmatic,
Task, verifier, reward or trajectory-specific fields.

## Current scope

S1 and S2 semantics are being co-designed so their boundary is executable.
Only S1 has an implementation plan. S2 has PRD/design only and is revalidated
against a real S1 release before its implementation planning starts. S3-S4
children do not exist yet. S1 must not implement Task generation, reward,
trajectories or training.

## Product acceptance

- [ ] At least one exact S1 release is consumed by S2 without private state
  mutation or a compatibility adapter.
- [ ] Every admitted Task is bound to the exact release and a reproducible
  starting world, has a real public reference execution and a hidden verifier.
- [ ] S3 produces real tool-call trajectories and reward that remains grounded
  after cold recreation.
- [ ] S4 performs real SFT/RL work and records reproducible downstream evidence.
- [ ] An independent clean-machine reproduction validates the complete claim
  chain without generator-private context.

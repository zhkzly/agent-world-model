# Paper-grade Environment and Task Foundry

## Goal

Deliver a publishable system that converts a natural-language Need into a real
executable Agent world, qualified high-quality Tasks, verified Episodes and real
SFT/RL evidence. Product completion means semantic completion of the causal
chain, never a demo, MVP, mock, canned Task, one successful trace or green unit
suite.

## Product stages

```text
S1 Environment Foundry
  -> immutable EnvironmentRelease v2
     public actor project + independently qualified protected TaskSemantics

S2 Goal-First Task Foundry
  -> TaskDefinition / TaskPack
     separate TaskAssessment / CorpusManifest

S3 Episode Runtime and Evaluator
  -> real acting-Agent trajectory + frozen Task verification
     + attributable Reward/abstention

S4 SFT/RL Integrations
  -> real datasets, optimizer runs, checkpoints and held-out evidence
```

The parent owns the cross-stage causal claim only; it is not another runtime
layer.

## Stage boundaries

### S1

S1 owns:

- Need/evidence Research and the accepted Development Brief;
- Codex SDK generation of a real actor environment project;
- public `reset/tools/invoke/close` behavior and persistent native state;
- an independent Codex SDK TaskSemantics project authored after expected
  relations freeze;
- Host-owned public/native/physical-negative Qualification;
- exact prepare/open process isolation and immutable publication.

S1 publishes qualified capability atoms, workflow/condition metadata, start cases
and atomic evaluators. It does not publish concrete Tasks, reference traces,
Task checkers, corpus cells, rewards or trajectories.

### S2

S2 consumes one exact v2 release and follows this fixed order:

```text
CapabilitySpecs + StartCase + bindings
-> deterministic selector/GoalProgram TaskBlueprint
-> freeze deterministic TaskChecker
-> render/audit final canonical instruction
-> two fresh public Responses-Agent executions of that exact instruction
-> checker/instruction/provenance challenges
-> TaskPack
-> separate model-relative TaskAssessment
-> CorpusManifest
```

Graph/random-walk/program synthesis are optional future public-search
implementations only. They are not Task sources or truth.

Every admitted Task is publicly solvable, deterministically verifiable,
well-posed, non-trivial, reproducible, Need/workflow anchored and path-open.
Difficulty and training utility are empirical assessment/corpus properties, not
Task identity.

### S3

S3 recreates a TaskPack, exposes only its public projection to the acting policy,
records real actions/observations/final answer and executes the frozen checker.
The neutral public Responses episode runner used by S2 witness/assessment is
reused rather than reimplemented.

### S4

S4 consumes exact release/TaskPack identities and verified Episode facts. It
cannot redefine environment or Task truth.

## Implementation ownership

```text
Framework Python
  release/runtime/contracts/compiler/checker/instruction/runner dispatch/
  provenance/admission/identity/corpus verdicts

Python Codex SDK
  actor environment project
  independent protected TaskSemantics project

OpenAI Responses tool-calling policy
  public witness execution
  independent model-relative assessment
```

Prompts guide model work but cannot replace deterministic framework code or
physical evidence.

## Trust boundary

```text
acting policy
  canonical instruction + public reset context + ToolSpecs + ToolObservations

trusted runtime
  reset input + TaskSemantics + protected binding + checker + native facts
```

Protected state may select and verify a Task but never provide an acting-time
operand or reference route. LLM agreement cannot override deterministic failure.

## Current scope

The `s2-task-foundry` task owns the complete S2 implementation and minimum clean
S1 v2 changes. Compatibility with previous research releases/Task proposals is
out of scope. S3/S4 remain later children except for the minimal TaskPack and
shared public episode-runner contracts.

## Product acceptance

- [ ] S1 v2 cold-publishes exact actor and TaskSemantics projects with independent
  native/physical Qualification and process-isolated prepare/open.
- [ ] Every core Brief Requirement is explicitly Taskable, NotTaskable or
  Unsupported.
- [ ] Checker and final instruction freeze before any witness-model call.
- [ ] Each TaskPack has two fresh successful public executions of the exact final
  instruction and no load-bearing hidden operand.
- [ ] Applicable no-op, wrong-target, near-miss, partial, collateral,
  wrong-answer and process challenges fail; a valid alternative route passes.
- [ ] TaskPack identity excludes model trials/difficulty/corpus policy.
- [ ] Both conformance releases and a post-freeze held-out Need meet the
  preregistered Task-yield/structure/start floors without framework domain edits.
- [ ] Corpus diversity/redundancy/cost are reported separately from downstream
  matched-budget SFT/RL or Agent generalization.
- [ ] Exact cold artifacts reproduce the complete S1 -> S2 -> S3-shaped claim.

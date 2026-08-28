# Paper-grade Environment and Task Foundry

## Goal

Deliver a publishable system that converts a natural-language Need into a real
executable Agent world, qualified high-quality Tasks, verified Episodes and real
SFT/RL inputs. Product completion is semantic completion of the whole causal
chain, never a demo, MVP label, mock, template, canned Task, green unit suite or
package-shaped file.

## Product stages

```text
S1 Environment Foundry
  -> immutable qualified EnvironmentRelease with public actor surface
     and protected taskable semantics

S2 Goal-First Task Foundry
  -> parameterized, publicly solvable, checker-backed TaskPacks
     and structurally selected corpora

S3 Episode Runtime and Evaluator
  -> real acting-Agent trajectory, frozen Task verification
     and attributable Reward/abstention

S4 SFT/RL Integrations
  -> real datasets, optimizer runs, checkpoints and held-out evidence
```

Each stage has a direct coordinator and independently testable evidence. The
parent owns only the cross-stage causal claim; it is not an extra runtime layer.

## Stage boundaries

### S1

S1 owns:

- Need/evidence Research and the accepted Development Brief;
- generation of a real executable environment project;
- public `reset/tools/invoke/close` behavior and persistent native state;
- independent qualification of environment success/refusal relations;
- independent authoring and physical qualification of protected taskable
  capability semantics and deterministic start cases;
- exact release preparation/process isolation and immutable publication.

S1 does not publish Task instances, reference solutions, Task checkers, reward or
training trajectories. The protected semantics bundle defines qualified atomic
business capabilities, not a corpus.

The previously implemented S1 release format is prior engineering evidence, not
a compatibility requirement. The S2 redesign authorizes a clean S1 v2 release
contract when required for trustworthy Task generation.

### S2

S2 consumes one exact S1 v2 release and:

```text
qualified capability atoms
-> bounded GoalProgram / TaskBlueprint
-> deterministic start/binding instantiation
-> checker frozen before solving
-> public-only constructive witness and fresh replay
-> instruction rendering and leakage audit
-> adversarial challenges and independent actor trials
-> TaskPack and corpus selection
```

Graph traversal, random walks and generated programs are optional planner
techniques. They are not mandatory Task sources and do not define Task truth.

Every admitted Task must be publicly solvable, deterministically verifiable,
well-posed, non-trivial, reproducible, Need-anchored and useful for a named Agent
capability. A selected corpus must additionally be structurally diverse,
semantically deduplicated and evaluated for downstream utility.

### S3

S3 recreates an admitted Task from its exact release and protected StartRecipe,
shows only the public Task projection to the acting policy, records real public
actions/observations/final answer, executes the frozen checker and emits verified
facts plus Reward or abstention.

The actor-loop component used for bounded S2 trials is reused by S3; the product
does not maintain two incompatible rollout engines.

### S4

S4 consumes only exact release/TaskPack identities and verified Episode facts.
Training code has no authority to redefine environment or Task truth.

## Trust boundaries

```text
acting Agent
  sees Task instruction, public reset context, ToolSpecs and ToolObservations

trusted runtime
  sees protected semantics, binding/checker material and native facts required
  for verification
```

Protected state may select and verify a Task. It may never provide an acting-time
operand or leak a reference route.

A model may propose code, typed Blueprints, wording or search actions. Model
agreement and LLM Judges cannot override deterministic public/native evidence.

## Current scope

- The current `s2-task-foundry` planning task owns the complete S2 redesign and
  the minimum cross-environment S1 v2 changes required by it.
- Compatibility with previous research release/Task proposals is out of scope.
- S3 and S4 remain later children, except that S2 defines the minimal TaskPack
  handoff and a reusable public actor-loop contract.
- Planning artifacts must be reviewed and explicitly approved in a later user
  message before Trellis activation or product implementation.

## Product acceptance

- [ ] S1 v2 produces a cold-verifiable exact release whose public actor surface
  and protected semantics bundle are independently qualified.
- [ ] Each core user-facing Brief Requirement is explicitly Taskable,
  NotTaskable or Unsupported; no semantic capability disappears silently.
- [ ] Every admitted Task binds one exact release/start, starts unsatisfied,
  carries a checker frozen before witness planning, and has a fresh-replayed
  public-only solution with complete value provenance.
- [ ] Applicable no-op, wrong-target, near-miss, partial, collateral,
  wrong-answer and process challenges are rejected, while a different valid
  route is accepted.
- [ ] Task instructions expose all required constraints without hidden IDs,
  native fields, tools, answers or reference-order leakage.
- [ ] A corpus reports structural diversity, redundancy, empirical difficulty,
  reliability and cost without claiming universal coverage from an internal
  taxonomy.
- [ ] S3 recreates a TaskPack and verifies a real acting-Agent episode without
  generator-private context.
- [ ] S4 performs real matched-budget SFT/RL or downstream evaluation and records
  reproducible held-out evidence.
- [ ] After generic code/prompts/contracts freeze, an independently selected
  Need traverses S1 v2 and S2 without framework domain branches or handcrafted
  Task/evaluator additions.
- [ ] Independent clean-machine reproduction validates the complete published
  claim chain from exact artifacts.

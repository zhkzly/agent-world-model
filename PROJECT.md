# Canonical Agent Environment and Task Foundry

## Product intent

Build a paper-grade system that turns a natural-language business Need into a
real executable environment and then derives high-quality Agent Tasks from that
already-built world.

Semantic completion is the product criterion. A demo, MVP label, mock, canned
Task, dictionary world, green unit suite, single happy-path trace or
package-shaped artifact is never sufficient evidence of completion.

## Product lifecycle

```text
natural-language Need
-> S1 Environment Foundry
-> qualified immutable EnvironmentRelease
-> S2 Goal-First Task Foundry
-> verified release-bound TaskPacks and selected corpora
-> S3 acting-Agent Episodes + verified facts + Reward/abstention
-> S4 SFT/RL
```

### S1 owns the executable world

S1 researches the requested world, builds a real uv-managed project, executes
real public tools against real persistent state, independently qualifies
success and refusal semantics, and publishes an immutable EnvironmentRelease.

The release contract may evolve when a demonstrated cross-environment S2/S3
consumer need requires it. Compatibility with earlier research releases is not
a current product goal. Any S1 addition must remain environment-generic and may
not contain Task-instance-, sampler-, reward- or training-specific fields.

S1 must provide two trust-separated surfaces:

```text
public actor surface
  reset / tools / invoke / close

protected trusted surface
  isolated release preparation/opening
  qualified taskable capability semantics
  canonical read-only state inspection with a release-owned schema
```

The protected surface is never exposed to an acting Agent and must be
independently checked against native SQLite/files/Git or another authoritative
representation during S1 Qualification.

### S2 owns Task semantics and admission

S2 consumes an exact EnvironmentRelease and produces TaskPacks. Task generation
is goal-first:

```text
Need/Brief-anchored, independently qualified capability atoms
-> parameterized TaskBlueprint / bounded GoalProgram
-> reproducible reset-only StartRecipe
-> TaskChecker compiled and frozen before solving
-> public-only constructive solution and fresh replay
-> natural-language instruction
-> adversarial admission
-> TaskPack
```

Graph traversal, random walks, program synthesis, LLM agents and search
algorithms are optional implementation techniques. None is a mandatory Task
source or semantic authority.

Every admitted Task must be:

- publicly solvable from its actor-visible context;
- deterministically verifiable from trusted state, public trace and answer as
  required;
- well-posed without leaking hidden operands, tool names or a reference path;
- non-trivial at the initial state;
- reproducible across fresh materializations;
- anchored to a coherent user intent supported by the Brief;
- useful for a named Agent capability and assigned empirical difficulty/cost
  evidence.

A selected Task corpus must additionally be structurally diverse, low in
semantic redundancy and balanced for its declared SFT or RL use. Internal
coverage fingerprints guide selection; they are not evidence that the complete
Task space has been covered.

### S3 and S4 cannot redefine earlier truth

S3 receives a TaskPack public projection for the acting Agent and a protected
projection for trusted materialization and verification. It owns the acting
loop, trajectory, final answer, verifier execution and Reward/abstention.

S4 consumes verified Episodes. Training code cannot alter EnvironmentRelease
behavior, Task truth or admission evidence.

## Non-negotiable constraints

1. **Real execution.** Public tools execute real project code and mutate real
   persistent state. No response-map simulation or canned Task path is a normal
   success route.
2. **Public solvability.** A constructive solution may use only the same public
   information and tools available to the acting Agent. Protected state may
   select and verify a Task but may never supply an acting-time operand.
3. **Independent truth.** A TaskChecker is frozen before the reference solution
   is executed. The solution is evidence that the goal is reachable, not the
   source of the goal or verifier.
4. **Verifier sensitivity.** Admission must reject no-op, wrong-target,
   near-miss, partial, collateral-damage and wrong-answer outcomes, while
   accepting a valid alternative path when one is available.
5. **No semantic authority by consensus.** LLMs may propose intents, code,
   instructions and challenges. Model agreement never overrides deterministic
   execution or state evidence.
6. **Reset-only starts.** S2 chooses only S1-qualified `reset(start)` cases. It
   performs no hidden setup calls, direct native mutation or snapshot restore.
   Protected state inspection is read-only.
7. **No domain branches in the framework.** Booking, SQLite and Git are
   conformance cases, not framework categories or hard-coded schemas.
8. **No fake completion.** Intermediate slices are checkpoints. S2 is complete
   only after the full admission path works on contrasting real releases and a
   frozen implementation transfers to a held-out release without domain code
   changes.
9. **Causal changes only.** Do not add compatibility layers, fallbacks,
   abstractions, roles or fields without a named current consumer and observed
   need.

## Current planning boundary

The `s2-task-foundry` Trellis task owns the complete S2 redesign and the minimum
cross-environment S1 runtime/semantics changes required by that design. The
planning artifacts must be reviewed and explicitly approved before product code
or task activation.

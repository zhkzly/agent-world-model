# Canonical Agent Environment and Task Foundry

## Product intent

Build a paper-grade system that turns a natural-language business Need into a
real executable Agent environment and then derives high-quality training Tasks
from that world.

Semantic completion is the product criterion. A demo, MVP label, mock,
dictionary world, canned Task, one successful trace, green unit suite or
package-shaped artifact is never sufficient evidence of completion.

## Product lifecycle

```text
natural-language Need
-> S1 Environment Foundry
-> qualified immutable EnvironmentRelease
-> S2 Goal-First Task Foundry
-> verified TaskPacks + model-relative TaskAssessments + CorpusManifest
-> S3 acting-Agent Episodes + verified facts + Reward/abstention
-> S4 SFT/RL
```

## S1 owns the executable world and reusable task semantics

S1 researches the Need, builds a real uv-managed project, executes real public
tools against real persistent state, independently qualifies success/refusal
semantics and publishes an immutable release.

The S1 release exposes two mechanically separated surfaces.

```text
public actor surface
  reset / tools / invoke / close

protected trusted surface
  isolated prepare/open runtime
  deterministic start-case generator
  read-only semantic state inspection
  qualified taskable CapabilitySpecs
  binding enumeration and atomic evaluation
```

The protected surface is release-specific and hidden from acting Agents. It is
not a universal State IR. S1 Qualification must compare it with authoritative
native SQLite/files/Git or another independently readable representation and
must physically challenge every declared taskable capability.

That comparison is produced by one qualification-only verifier authored in an
independent clean context. It is archived for cold audit but is never exposed to
the actor, S2 compiler, witness Agent or Consumer. It cannot see TaskSemantics
source, outputs or repair history. The Host executes both lineages against the
same physical instances and owns every comparison and verdict.

S1 may change when a demonstrated cross-environment S2/S3 consumer requirement
requires it. Compatibility with earlier research releases is not a product
requirement. S1 must not publish concrete Tasks, reference traces, corpus cells,
rewards or training records.

## S2 owns Goal compilation, public solvability and Task admission

S2 is Goal-first. Its required order is:

```text
qualified CapabilitySpecs
-> deterministic StartCase and BindingCandidates
-> bounded TaskBlueprint / GoalProgram
-> compile and freeze TaskChecker
-> render and audit the final canonical public instruction
-> public-only Agent solves that exact instruction on real tools
-> repeat on a fresh equivalent start
-> challenge checker/instruction semantics
-> seal TaskPack
-> evaluate model-relative difficulty/cost separately
-> select a CorpusManifest
```

A successful trace is evidence that a frozen Task is reachable. It never creates
or weakens Task meaning. Graph traversal, random walk, program synthesis and
other search methods are optional planner implementations, not Task sources or
semantic authority.

## Execution ownership

### Deterministic framework code

Framework Python owns schemas, release preparation, process isolation, identity,
GoalProgram enumeration, checker compilation/execution, canonical instruction
rendering, public/protected projection separation, tool dispatch, trace capture,
argument-provenance validation, fresh-run admission, challenge verdicts,
deduplication and corpus selection.

These operations must not be implemented only as prompt instructions.

### Python Codex SDK code authoring

Codex SDK is used only to author three mutually isolated release-local code
artifacts:

1. the S1 Environment Builder writes the executable actor project;
2. an independent S1 Semantics Author writes the protected semantics package
   after Brief-derived expected relations are frozen;
3. an independent Qualification Verifier Author writes one audit-only native
   verifier package from the same frozen expectations and actor view, without
   access to the semantics project.

Codex never decides release admission, Task admission, identity, reward or final
checker verdict. Generated code passes deterministic Host checks, native reads
and physical negatives before publication.

### OpenAI Responses tool-calling Agent

A Host-owned Responses loop is used for public witness search and later
model-relative assessment. It sees the exact final instruction, public reset
context, ToolSpecs and ToolObservations only. It never sees GoalProgram,
TaskChecker, protected bindings, native state or an answer key.

The core implementation does not need an LLM paraphraser. A future paraphrase is
a new instruction variant and must repeat public solving and admission.

## Good Task contract

Every admitted Task must be:

- **publicly solvable:** at least two fresh real executions of the exact final
  instruction succeed using public information and tools only;
- **reliably verifiable:** deterministic checking rejects no-op, wrong target,
  near miss, partial completion, collateral damage and wrong/stale answers where
  applicable, while accepting a valid alternative route;
- **well-posed:** all material constraints are explicit without exposing hidden
  operands, native fields, tool names or a reference route;
- **non-trivial:** the checker is false at the initial state, and query answers
  are not already leaked by the instruction/reset context;
- **reproducible:** the same release and StartCase reproduce the same business
  predicates on isolated instances even when incidental IDs differ;
- **Need-anchored and natural:** the capability and every cross-capability
  composition are licensed by accepted Brief Requirements/workflows;
- **path-open:** outcome Tasks are judged by Goal truth, not reference-trace
  equality;
- **training-targeted:** the Task names a qualified Agent capability. Its actual
  difficulty and training value are empirical TaskAssessment/corpus properties,
  not Task identity.

A corpus must additionally be structurally diverse, low in semantic redundancy
and balanced for its declared SFT/RL use. Parameter changes and paraphrases do
not count as new Task structures. Internal coverage is accounting evidence, not
proof of complete Task-space coverage.

## Non-negotiable constraints

1. Public tools execute real project code and real persistent transitions.
2. Protected facts may select and verify a Task but never supply an acting-time
   operand.
3. TaskChecker is frozen before the final instruction is exposed to the witness
   Agent.
4. The witness Agent solves exactly the instruction later exposed to S3.
5. LLM consensus cannot override deterministic execution/state failure.
6. S2 starts are reset-only; no hidden setup calls, native writes or snapshot
   restoration are allowed.
7. Framework code contains no booking/SQLite/Git/domain field branches.
8. TaskPack semantic/admission identity is separate from model-relative
   TaskAssessment and CorpusManifest identity.
9. Unsupported semantics and bounded planner failure are explicit typed outcomes;
   gates are never weakened to increase Task count.
10. Intermediate implementation slices are checkpoints, never S2 completion.
11. Qualification binds a derived pre-publication Core ID; the final Release ID
    is computed only after the passed receipt is sealed, so no hash fixed point or
    provisional public release exists.
12. TaskDefinition stores stable logical binding plans. Every witness/challenge
    materialization resolves its own protected bindings after reset.
13. Every acting-time target, constraint and answer operand has an exact public
    source in the instruction, reset observation or schema-qualified tool output.

## Completion evidence

S2 is complete only when the same frozen framework:

- regenerates and consumes the contrasting SQLite and filesystem/Git releases;
- produces non-trivial Task yield and multiple canonical GoalProgram shapes for
  both without domain patches;
- passes public solvability, checker sensitivity, leakage and fresh-start gates;
- transfers to a held-out Need selected after framework/prompt freeze;
- reports matched-budget baselines and downstream utility rather than relying on
  internal diversity claims.

## Current task boundary

The `s2-task-foundry` branch and Trellis task own the complete S2 implementation
and the minimum clean S1 release/runtime/semantics changes required by it. The
old Graph/Programmatic-first proposal and backward compatibility are out of
scope.

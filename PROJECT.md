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
  sealed RequirementObligations with finite applicability handles
  binding enumeration and atomic evaluation
```

The protected surface is release-specific and hidden from acting Agents. It is
not a universal State IR. S1 Qualification must compare it with authoritative
native SQLite/files/Git or another independently readable representation and
must execute one real representative case for every declared taskable capability.

That comparison is produced by one qualification-only native auditor authored in an
independent clean context. It is archived with the release but is never exposed to
the actor, S2 compiler, witness Agent or Consumer. It cannot see TaskSemantics
source, outputs or repair history. The Host executes both lineages against the
same physical instances and compares only required native effects and collateral.
Public process, AnswerFields and final-answer truth remain TaskSemantics/Host
responsibilities rather than being duplicated by the auditor.

S1 may change when a demonstrated cross-environment S2/S3 consumer requirement
requires it. Compatibility with earlier research releases is not a product
requirement. S1 must not publish concrete Tasks, reference traces, corpus cells,
rewards or training records.

## S2 owns grounded Task sampling, Good Task admission and corpus selection

S2 is Good-Task-first. Direct compilation, Graph exploration and Programmatic
execution are complementary proposal mechanisms feeding one common boundary;
none is semantic authority or a separate Task ABI. Its required order is:

```text
exact EnvironmentRelease
-> disposable public discovery and CandidateTaskProposal
-> freeze bidirectionally anchored TaskSpecification
-> compile bounded task-local VerifierBundle V0
-> materialize/replay Start and bind public operands
-> freeze concrete checker, instruction and answer contract
-> public-only Agent solves that exact instruction twice on real tools
-> physical reload/truth extraction and applicable semantic challenges
-> seal TaskPack
-> evaluate model-relative difficulty/cost separately
-> select a CorpusManifest
```

A successful trace is evidence that a frozen Task is reachable. It never creates
or weakens Task meaning. Graph and Programmatic samplers are required conformance
proposal paths, but their graphs/programs remain disposable evidence rather than
persistent Task types. Task meaning comes from accepted Need/Requirement anchors
and the frozen TaskSpecification.

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
3. an independent Native Auditor Author writes one audit-only native
   effects/collateral package from the same frozen expectations and actor view, without
   access to the semantics project.

Codex never decides release admission, Task admission, identity, reward or final
checker verdict. Generated code passes deterministic Host checks and real
positive physical execution before publication.

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
- **reliably verifiable and path-open:** deterministic checking rejects every
  constructible applicable no-op, wrong-entity, near-miss, partial,
  omitted-obligation, collateral, wrong/stale-answer and required-process
  violation, while accepting a known valid alternative route when one exists;
- **bidirectionally anchored and well-posed:** every checker predicate is
  authorized by an S1-issued RequirementObligation/qualified semantic operation,
  and every obligation whose sealed S1 applicability handle evaluates true is
  included; instruction/schema sources prove disclosure only, without exposing
  hidden operands, native fields, tool names or a reference route;
- **non-trivial:** the checker is false at the initial state, and query answers
  are not already leaked by the instruction/reset context;
- **replayable and isolated:** the same release and StartRecipe reproduce the
  same business predicates on isolated instances even when incidental IDs
  differ; declared persistence is checked after a real close/reopen;
- **minimally purposeful:** the objective and every cross-capability composition
  are licensed by accepted Requirements/workflows, and no witness step is
  decorative tool stitching or padding;
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
14. Graph/Programmatic/direct sampler lineage may affect proposal evidence but
    never Task truth, verifier acceptance or S3 public projection.
15. S2 publishes a strict cold-readable TaskPack and non-leaking PublicTaskView;
    complete TaskPack bytes are never handed to the acting policy.
16. A required process predicate must cite an S1 obligation classified as
    process. An executed sampler route or state-enablement edge cannot make its
    own tool sequence semantically mandatory.

## Completion evidence

S2 is complete only when the same frozen framework:

- regenerates and consumes the contrasting SQLite and filesystem/Git releases;
- executes direct, Graph and Programmatic proposal paths under fixed budgets and
  reports honest proposal/yield/rejection evidence;
- produces non-trivial, structurally distinct Task yield without domain patches;
- passes bidirectional coverage, public solvability, physical reload,
  applicability-planned verifier challenges, leakage and fresh-start gates;
- transfers to a held-out Need selected after framework/prompt freeze;
- uses at least two policy lineages/checkpoints to report difficulty,
  discrimination, redundancy and cost; downstream learning utility remains an
  S3/S4 experiment rather than Task truth.

## Current task boundary

The `s2-task-foundry` branch and Trellis task own the complete S2 implementation
and the minimum clean S1 release/runtime/semantics changes required by it.
Graph and Programmatic proposal samplers on the common Good Task path are in
scope; their former separate product lanes and all backward compatibility are
out of scope.

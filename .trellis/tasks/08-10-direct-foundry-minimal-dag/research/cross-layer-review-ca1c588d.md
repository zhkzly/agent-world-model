# Research: cross-layer review ca1c588d

- Query: Fresh independent final R9-C2 child review of Direct plan digest
  `ca1c588d4e9e970431aa002832207709b55f35a085b3ed76ebf045816dcbe6db`,
  including the prior Direct block and parent C2 allow.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `ca1c588d4e9e970431aa002832207709b55f35a085b3ed76ebf045816dcbe6db`.
- Parent digest confirmed: `734a274a6b3092f0b526530fd264d105dd65bf068b1aee74fe67984219d7f117`.
- Plan revision: Direct R9-C2 difficulty closure, revision 2 in the Direct
  lineage after the R9-C1 block `baddd746...`; this is the second and final
  child review requested for that revision.
- Scope classification: larger Direct vertical slice across Controller,
  Designer, Builder, Judge, Registry, and Observe, with contract-only handoffs
  to Repair, Expand, and Consumer. It does not add any of those later control
  loops.
- Trigger: C1 was blocked for a missing finite framework-owned difficulty
  producer. This is a plan revision, not a response to a failed real execution
  proof; no Diagnosis Record or Observe failure scene is applicable.

## Digest And Reviewed Scope

The five raw SHA-256 values and their newline-terminated `sha256sum` aggregate
were recomputed in the plan-declared order and reproduce `ca1c588...`. The
sixteen-input parent aggregate was recomputed in its declared order and
reproduces `734a274a...`. Both reviews therefore apply to the current bytes.

Reviewed inputs include the cross-layer critic skill; `AGENTS.md`; canonical
product contract; derived execution map; Direct PRD, design, node contracts,
and implementation plan; parent PRD, design, and implementation plan; Repair,
Expand, and Consumer PRD/design/implementation plans; prior Direct block; and
the current parent allow. The current cleanroom code is only a pre-change
baseline, not proof for this plan: its sequential flow still calls Judge after
Integration without the planned graph-level pass guard
(`agent_world/foundry.py:170`), so the Direct plan correctly requires in-place
replacement rather than preserving a parallel path.

## Product Target And Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in
an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and
expose only safe facts through Observe. Expand must later create independently
judged packages through the same Design/Build/Judge/Release path; Consumer may
use exact released packages only through isolated public Episodes without
environment, reward, or release authority.

The C2 impact chain is now coherent:

```text
CurriculumPlanSourceDraft
  -> Designer framework DifficultySchema compiler
  -> TaskRequirement (direct CurriculumPlan dependency + schema digest)
  -> MaterializationRequest / exact MaterializerResult echo
  -> Builder Integration -> independent Judge
  -> curriculum/protocol/manifest package bytes -> Registry cold-read/ref
  -> rebuilt Expand Design or Consumer EpisodeRequest -> safe Observe facts
```

This is the exact missing producer chain identified by the predecessor block,
not a permissive mapping added at the candidate or Consumer boundary.

## Required C1 Actions Rechecked

- **Finite producer and canonical order:** `curriculum_plan` now proposes 1..6
  ordered dimensions and 2..5 ordered levels, while framework validates stable
  unique names, bounds, and order, then commits one per-family schema
  (`node-contracts.md:408`, `:430`). `DifficultySelection` requires every key
  exactly once in `key_order`; duplicate-aware parsing rejects missing, extra,
  reordered, duplicate, and out-of-domain values (`node-contracts.md:445`).
- **TaskRequirement model contract, dependency, and invalidation:** the
  TaskRequirement Direct-LLM card receives the frozen schema read-only and
  cannot redefine it (`node-contracts.md:454`). Its committed requirement
  embeds/refers to the exact schema and its semantic revision binds the schema
  digest; the direct `CurriculumPlanRef` dependency invalidates only the
  affected requirement, Modeling Gate, EnvironmentDesign, and CandidateGraph
  descendants (`node-contracts.md:472`, `:478`). This is consumable by the
  later Repair dependency-closure algorithm, which derives descendants from
  immutable `WorkRecord.dependency_refs` (`08-11-foundry-bounded-repair/design.md:60`).
- **Candidate exact echo:** framework validates an admitted selection before
  candidate launch and validates the returned ordered echo before using
  `public_goal` or `initial_config`; unordered semantic equivalence is
  insufficient (`node-contracts.md:650`, `:675`). Candidate code has no
  schema-authoring, coercion, defaulting, or selection authority.
- **Paired-level semantic behavior:** Integration and Judge require two valid
  selections differing in one declared level to change `public_goal` or
  `initial_config`, rather than only changing a label/instruction
  (`node-contracts.md:693`). The implementation plan includes that real
  materialization check and rejection of invalid/missing/extra/duplicate/
  reordered values before Judge or release (`implement.md:216`).
- **Package and Registry cold-read:** `tasks/curriculum.json` persists the
  exact schemas/digests used by TaskRequirement and protocol; Registry
  recompiles/revalidates agreement among curriculum, task, protocol, and
  manifest (`node-contracts.md:724`). This preserves immutable
  `EnvironmentPackageRef` compatibility without a second schema owner.
- **Expand and Consumer compatibility:** Expand rebuilds its own complete
  child curriculum/schema and cannot union or inherit parent levels
  (`08-11-foundry-expand-multiparent/design.md:87`). Consumer cold-reads the
  exact released schema, verifies the digest against TaskRequirement/protocol/
  manifest, and rejects malformed selections before Materializer invocation
  (`08-11-foundry-consumer-sft-rl/design.md:70`). It keeps `initial_config`
  private (`08-11-foundry-consumer-sft-rl/design.md:80`). The later-child
  proofs remain explicitly required; this Direct slice freezes their input,
  rather than falsely claiming they are implemented.

## Owners, Graph, And Authority

- The plan remains the two fixed lightweight graphs with one `NodeSpec`, one
  `EdgeSpec`, and a deterministic runner. It excludes dynamic graphs,
  schedulers, plugins, callback buses, and a third graph
  (`docs/direct-rewrite-execution-map.zh.md:30`).
- Execution kinds are explicit and framework-owned. `CandidateBuild` is an
  Agent work owned by Builder, while Integration/Judge use the untrusted
  candidate-process boundary without transferring validation or Artifact commit
  authority (`node-contracts.md:34`, `:71`).
- BuildPlan and VerifierIntent are read-only siblings. CandidateBuild consumes
  only frozen Design/ImplementationContract/BuildPlan; Integration depends on
  Design plus Candidate, and Judge alone joins passed Integration with the
  VerifierBundle (`docs/direct-rewrite-execution-map.zh.md:96`).
- Integration non-pass leaves Judge, Package, and Registry `not_run`
  (`implement.md:218`). Judge records independent hard-gate evidence but has no
  route or release decision; Controller's `package` is the only ReleaseKernel,
  and Registry only cold-reads/rejects or atomically publishes that closure
  (`node-contracts.md:89`; `implement.md:232`).
- Runtime Agent work has one explicit product Skill per work and no ambient
  hooks, MCP, project skills, or inherited workspace capability
  (`docs/direct-rewrite-execution-map.zh.md:102`). Direct LLM nodes receive no
  Skill, tool, or workspace.
- Direct uses empty parent lineage and the plan requires a legacy-reference
  firewall plus replacement of the current sequential cleanroom orchestration;
  it retains no `awm` CLI, ABI v1, replay, StateGraph, or compatibility success
  path (`implement.md:31`, `:41`).

## Smallest Allowed Implementation And Proof

Implement only the reviewed Direct contracts and two static graphs. Preserve
the inert Repair/Expand/Consumer handoffs, but do not implement their routing,
campaign, suite, trainer, or second authority.

Deterministic checks must prove closed-schema compilation; duplicate-aware
ordered selection rejection; Curriculum-to-TaskRequirement direct dependency
and invalidation closure; exact Materializer echo; paired-level semantic or
initial-state change; CandidateBuild/Verifier separation; Integration
fail-stop; package/Registry cold-read; and safe Observe projection.

The smallest true-boundary proof is a real generated CandidateBuild in a
temporary workspace that materializes two admitted selections for one family,
rejects an invalid selection before candidate/release use, completes isolated
Integration and independent Judge, then performs a fresh non-fixture Direct
request through Registry cold-read and terminal Observe (`implement.md:331`).
If a real proof terminal fails, the next action is Observe -> debugging ->
Diagnosis Record -> revised plan -> fresh critic, not a retry or patch.

## Non-Claims And Next Permitted Gate

This allow authorizes only implementation for the exact C2 digest. It does not
prove that implementation exists, an Agent/provider is available, Direct E2E
has released a package, Repair has repaired a failure, Expand has produced a
child, Consumer/SFT/RL has run, or complete-v1 is delivered. It does not
authorize a changed plan digest, changed trust boundary, or a new failed scene.

Next permitted gate: place this matching allow record in the active Direct
implementation and check manifests, then dispatch the bounded Direct
implementation. After implementation, run the declared deterministic checks
and the smallest real proof; read Observe after every real terminal before any
further repair planning.

## Caveats / Not Found

- No failed real execution scene was presented, so no Diagnosis Record was
  required or inferred.
- Consumer compatibility is a frozen Direct handoff plus an explicit later
  Consumer proof obligation, not evidence that Consumer is already runnable.
- This record expires if any of the five Direct digest inputs, the parent
  digest, the affected trust boundary, or the relevant real-proof scene changes.

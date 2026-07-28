# Task Curriculum E2E Diagnostic Fidelity

## Goal

Prove the next real semantic boundary, `design.task_curriculum`, against the
WorldRules commit produced by the prior isolated diagnostic run. The goal is a
truthful, observable single-node result—not a broad pipeline retry and not a
claim that Build, Judge, or release has passed.

## Confirmed facts

- The staged scope is `generate-job:ba03ff3dce4e303593c64e2d`.
- Its captured upstream closure contains committed Research, Architecture,
  SharedToolSemantics, two ToolSemantics batches, and a real diagnostic
  `world_rules` commit at
  `.agent-world-live/test-node-20260726T032437Z-bd4f1ff12f6e/`.
- `TaskCurriculumLeaf` consumes the committed `design.world_semantic_source`,
  `design.world_model`, Architecture, and EvidenceGraph; it emits exactly one
  `design.task_curriculum_source` artifact.
- The prior successful WorldRules run is diagnostic-only and non-releasable.
  It is valid frozen input for another isolated diagnostic proof, not evidence
  of a normal Direct completion or any downstream success.
- The captured original scope stopped at WorldRules, so it has no existing
  `task_curriculum` WorkControl head. Current `TestNodeRunner` appears to
  require a source target head before it can archive and rerun that target.
  This is an explicit, testable harness hypothesis—not yet a confirmed cause.

## Requirements

- R1. Treat every uncertain Agent/LLM result as a five-way ownership decision:
  project-execution Agent view; effective runtime instruction/input (rendered
  Prompt plus runtime input projection); owning Runtime Skill; deterministic
  code/execution (including resolved runtime capability profile); or
  feedback/observability. Record the evidence before changing any of them. A
  project-execution Agent view is a compact current-task/path map and never
  changes runtime authority. Runtime capability profiles remain
  deny-by-default; they are not a reason to grant broader tools or access
  merely to improve a sample.
- R2. Read the safe scene, validation report, frontier, and terminal state
  before acting on a real-node failure. If the result lacks stable code,
  source-facing path, violated condition, expected category, or a bounded
  terminal/heartbeat signal, repair feedback or test-harness observability
  before a semantic retry.
- R3. The first execution proof is a complete frozen input closure through the
  actual TaskCurriculum leaf/compiler/scheduler boundary. Ordinary pytest is a
  regression supplement, not evidence that the real provider path works.
- R4. If the diagnostic harness cannot dispatch the downstream node from the
  prior diagnostic commit, prove that exact limitation with a constructed
  regression and repair the smallest diagnostic-only scheduling contract. Do
  not bypass it by injecting a fake TaskCurriculum head or replaying output.
- R5. A real grok-4.5 invocation is permitted only after a causal change or a
  first-time unknown-node probe has been recorded. Never rerun unchanged input
  hoping for a different sample.
- R6. When an issue is confirmed at one owner/boundary, inventory all
  same-owner/same-boundary occurrences before the next live invocation.
- R7. Preserve compiler strictness, isolation, budgets, diagnostic-only
  marking, and non-releasability. Do not relax validators, increase retries,
  hand-author semantic output, use mock code generation, or use fixtures as a
  normal success path.
- R8. Keep model execution behind `InvocationBackend`; use the configured
  grok-4.5 route first, with the user-approved fallback order only if the
  primary route is genuinely unavailable.
- R9. Tests and diagnostic output must identify node/owner, valid fixture or
  committed-closure provenance, one poisoned condition, expected versus actual
  stable diagnostic, elapsed time, and last completed phase. Opaque assertions
  or stalls are feedback defects, not guidance for runtime
  instruction/input changes.

## Acceptance Criteria

- [ ] AC1: The TaskCurriculum effective runtime instruction/input, Engineer
  Skill, resolved runtime capability profile, project-execution Agent view,
  compiler/contract, feedback registry, and real diagnostic scheduler path are
  audited before any semantic repair.
- [ ] AC2: The existing WorldRules diagnostic commit is verified as the exact
  upstream input closure, and the feasibility of dispatching its unheaded
  TaskCurriculum successor is proven rather than assumed.
- [ ] AC3: Any discovered harness/contract problem has a constructed
  failing-to-passing regression that proves the actual scheduler/leaf boundary
  and preserves diagnostic-only/non-releasable authority.
- [ ] AC4: Any semantic diagnostic crossing the Agent boundary is safe,
  stable, source-addressable, and includes code/path/condition/category. A
  framework-owned mechanical fact is never delegated to Agent repair.
- [ ] AC5: The complete same-owner inventory for every confirmed defect is
  repaired and covered before another live invocation.
- [ ] AC6: Focused regression tests, type checking, lint, and format checks
  pass for every changed boundary.
- [ ] AC7: Exactly one fresh real isolated TaskCurriculum execution is run
  after the deterministic gate, and its safe scene is read and recorded. Its
  status may be committed, typed failed, or a bounded external blocker; no
  unsupported success claim is made.
- [ ] AC8: No secret, endpoint value, raw provider transcript, sealed datum,
  or replayed output appears in tracked task artifacts or source changes.

## Scope extension — 2026-07-26 user authorization

The user has authorized continuing the same frozen diagnostic lineage after a
real `TaskCurriculum` proof.  The work now proceeds one physical boundary at a
time through Modeling, VerifierPlan, final-epoch derivation, Build,
Integration, Challenger batches, and release gates.  This is still not a
license for a broad retry: each node must have its immediate committed parents,
be executed through its real Scheduler/leaf boundary, and have its scene read
before the next node starts.

TaskRequirement siblings are semantically independent only after the
CurriculumPlan commit, but the current Scheduler runs them in stable sequence.
They may not be changed to parallel execution until concurrent lease,
provider-capacity, deterministic-commit, and sibling-failure behavior have
their own real proof.  The deterministic tail remains strictly ordered:
`TaskCurriculum -> ModelingBoundary -> VerifierPlan`.

Still out of scope:

- Changing runtime instruction/input, Runtime Skill, or semantic contract solely to work around a
  missing diagnostic scheduling capability.
- Publishing or adopting a diagnostic artifact as a releasable WorkCommit.

## Remaining physical-node count

After WorldRules, the immediate next node is exactly TaskCurriculum. From that
point through publication there are 11–18 physical nodes: ten fixed nodes plus
one to eight real Challenger verifier batches selected only after the frozen
curriculum determines the partition. Only 3–10 of those nodes involve
uncertain Agent/LLM output (TaskCurriculum, Builder, and the 1–8 verifier
batches); the rest are still mandatory real deterministic execution gates.

# Task Curriculum E2E Diagnostic Fidelity — Implementation Plan

## 1. Audit before a live call

- Read the actual `TaskCurriculumLeaf`, rendered effective runtime
  instruction/input (active Prompt plus runtime input projection), legacy
  prompt path, Engineer Skill, resolved runtime capability profile,
  `compile_training_semantics`, feedback contract, and scheduler/test-node
  resolver.
- Treat a runtime input/capability modification as a least-privilege runtime
  change: prove the required frozen fact is absent/stale/contradictory or the
  profile is wrong, then test the necessary behavior and continued exclusion of
  unrelated runtime facts or tools.
- Treat a project-execution Agent-view modification separately: prove the Code
  Agent cannot choose the next needed project read from its current task/path
  map, then add only the smallest local navigation and test it with a fresh
  project-Agent exercise.
- Read the safe WorldRules diagnostic scene and its committed head; verify the
  frozen parent closure and exact TaskCurriculum coordinate.
- Record the five-way owner decision. A missing successor dispatch is a
  scheduler/observability question, not a TaskCurriculum runtime
  instruction/input defect.

## 2. Prove diagnostic-successor dispatch

- Execute the real resolver against the marked WorldRules diagnostic state
  without calling a model if the target lacks a head.
- Add a constructed regression for the observed outcome.
- If needed, implement the smallest diagnostic-only successor capability that
  dispatches exactly one already-frozen downstream definition from committed
  parents. Preserve immutable source state, diagnostic marker, budget bounds,
  safe terminal scene, and non-releasability.
- Audit all equivalent target-head assumptions in that same test harness
  boundary before moving to a live call.

## 3. Prove TaskCurriculum contract locally

- Construct a complete valid frozen WorldRules closure and execute the actual
  leaf/compiler path.
- Poison one source condition per regression and assert exact owner, code,
  path, condition, category, actionability, and expected terminal state.
- If evidence selects runtime instruction/input or Runtime Skill instead,
  audit every active/legacy projection of that same task authoring contract
  before one repair.

## 4. Deterministic quality gate

- Run only focused affected tests first, then relevant type/lint/format checks.
- Read every failed test as a feedback artifact. Do not use a bare assertion or
  unexplained stall as a reason to edit model guidance.
- Record the precise causal change that makes the real invocation different.

## 5. One real node execution

- Use the configured grok-4.5 InvocationBackend route.
- Run exactly one isolated TaskCurriculum target with the committed diagnostic
  WorldRules closure as input.
- Read safe `observe`/scene, validation, frontier, terminal status, duration,
  and last phase. Do not run a successor or full E2E in this task.

## 6. Validate and hand off

- Update the diagnostic report with the five-way decision, deterministic
  evidence, real-node result, and explicit remaining topology.
- Run focused tests, mypy, Ruff, format check, and `git diff --check` in
  proportion to changed files.
- Commit only after all claimed requirements are satisfied and user authority
  remains in scope; do not push without a separate request.

## 7. Replace the whole-curriculum transaction with a durable fan-out

- Add a small `CurriculumPlan` Agent boundary which emits only
  `CurriculumPlanSourceDraft` against the frozen WorldModel.
- After its committed plan fixes ordered task types, let framework code derive
  and freeze one `TaskRequirement` Agent WorkDefinition per task type. The
  initial scheduler path may dispatch them sequentially; each invocation must
  remain one durable child node with its own safe failure/reporting boundary.
- Add a deterministic `TaskCurriculum` join that accepts only the exact plan
  and every ordered task requirement, then runs the existing whole-curriculum
  compiler and persists the unchanged `design.task_curriculum_source` output.
- Introduce the smallest explicit intermediate graph epoch needed to retain
  the committed world-plus-plan closure before the dynamic task-family graph
  is frozen. Do not invent nodes, task ids, or task output: the committed plan
  is the only source of fan-out cardinality and identity.
- Prove constructed Scheduler dispatch, parent retention, one poisoned task
  family diagnostic, join ordering/closure, diagnostic-only authority, and
  source graph immutability before another real provider call.

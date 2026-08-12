# Repair plan — Curriculum actionable Feedback with strict progress

- Revision: 1
- Diagnosis:
  `diagnosis-curriculum-feedback-and-progress-budget.md`
- Scope: local Direct Curriculum proposal transaction; no Artifact or edge
  contract change

## Product target and observed gap

The target remains natural-language need -> evidence-backed Design ->
executable isolated Candidate -> independent Judge -> immutable Registry
`EnvironmentPackage` -> safe Observe. Public run
`run_fb7f87b4307346b3ae2e6843b27f650a` reached Curriculum after all earlier
Design nodes passed. Its first Feedback caused strict A-to-B progress, but the
second diagnostic merged task-family ID and actor-index failures and the runner
could not spend the canonical second strict-progress correction.

## Minimal implementation

1. In the existing Curriculum compiler, validate `task_family_id` and
   `actor_index` separately. Emit the exact field path and one actionable
   condition for each. Do not expose raw proposals or change accepted values.
2. Declare `curriculum_plan.local_corrections=2`.
3. Remove the runner's ToolSemantics-only identity restriction for the third
   proposal. Keep the existing declaration-driven conditions: only a Direct
   LLM node explicitly declaring two corrections may continue; proposal 1 and
   proposal 2 must both be parsed semantic rejections; both corrections must
   be non-format and have distinct
   `code+path+condition+expected_category`. Proposal 3 is final. Repeated,
   format, provider, framework, Agent, Candidate or validator-postcompile
   failures do not gain another call.
4. Keep the existing Feedback renderer unchanged. Once the validator emits an
   exact field condition, it already sends that correction as the next user
   message, asks for one complete replacement and asks for whole-object
   self-check.

## Compatibility and ownership

- Inputs remain the same frozen Architecture, WorldRules and EvidenceGraph
  projections; Direct remains no-Skill/no-tool/no-workspace.
- Output remains the same compiled `CurriculumPlan` and `DifficultySchema`.
  TaskRequirement, ModelingGate, Candidate, Expand and Consumer see no new
  field or meaning; they can consume only a passed committed Artifact.
- Framework retains validation, attempt budget, commit, Judge and release
  authority. Luna receives only semantic correction text and cannot choose a
  retry, route, target, Gate or release action.
- Graph nodes, edges, model/profile, Prompt body, response format and package
  schema remain unchanged.

## Regression checks

- Exact field diagnostics distinguish invalid `task_family_id` from invalid
  `actor_index`.
- Curriculum A -> distinct B -> pass uses exactly three proposals and persists
  two correction attempts plus one pass.
- Same issue repeated stops after proposal 2.
- Any format failure stops by proposal 2 and never reaches proposal 3.
- Proposal 3 failure stops with no fourth call.
- ToolSemantics retains its existing bounded behavior; every other unchanged
  node retains its declared correction count.
- Focused tests, full pytest, Ruff, mypy, compileall and legacy firewall pass.

## True proof and stop rule

Replay only `curriculum_plan` with the exact Architecture, WorldRules and
EvidenceGraph parents from the failed run. The falsifiable result is either one
strictly compiled Curriculum Artifact within at most three proposals, or an
honest leaf terminal with no fourth call and no release. Read Observe
immediately. Only a passed leaf permits one fresh public Direct E2E; its first
new terminal begins a new diagnosis.

## Explicit non-goals

No new retry subsystem, Feedback class, node split, schema engine, token cap,
model fallback, validation relaxation, raw-response persistence, downstream
repair, Expand or Consumer implementation belongs in this repair.

# Accepted Decisions

## 2026-08-28 — S2 Goal-First clean redesign

- The user authorized replacing the previous S2 proposal completely. Backward
  compatibility, the old release format and mandatory Graph/Programmatic lanes
  are not requirements.
- S1 may change when the change is environment-generic and required by S2/S3.
  The new immutable release is `EnvironmentRelease v2`.
- S1 v2 publishes two separated surfaces:
  - public actor `reset/tools/invoke/close`;
  - protected release-local `TaskSemantics` with start cases, read-only inspect,
    qualified capabilities, binding enumeration and atomic/condition checks.
- S1 TaskSemantics is written by a fresh Codex SDK thread/workspace independent
  of the Environment Builder. Existing independent Qualification machinery is
  extended; no new multi-Agent organization is introduced.
- Host code freezes Brief-derived expected capability/workflow relations before
  the Semantics Author receives decode-only source/native access.
- Host code owns schemas, manifests, identities, execution, native readers,
  physical negatives, repair ownership and final release verdict. Generated
  code and model consensus are never self-authorizing.
- Every core Brief Requirement is dispositioned `Taskable`, `NotTaskable` or
  `Unsupported`; silent omission is invalid.
- S2 is Goal-first. A graph, random walk, generated program or successful trace
  can guide public search but cannot create Task meaning.
- The S2 semantic order is fixed:

  ```text
  CapabilitySpecs + StartCase + bindings
  -> TaskBlueprint
  -> freeze TaskChecker
  -> render/audit final canonical instruction
  -> two fresh public witness executions of that exact instruction
  -> challenges
  -> TaskPack
  ```

- The bounded GoalProgram has four nodes only: `AtomGoal`, `AllGoal`, `IfGoal`
  and `ForEachGoal`. Selection and reporting are TaskBlueprint attributes, not
  standalone AST nodes.
- Cross-capability `AllGoal` requires a shared independently qualified workflow
  ID and compatible scopes. `IfGoal` may reference only a qualified publicly
  observable `ConditionSpec`.
- TaskChecker is canonical Host-interpreted data compiled from qualified atomic
  semantics. Arbitrary LLM-authored verifier Python is forbidden.
- The final canonical instruction is frozen before any witness-model call. The
  witness and later S3 actor receive exactly the same instruction string.
- Public witness search and independent assessments use a Host-owned OpenAI
  Responses tool-calling loop, not Codex SDK. Codex SDK is reserved for
  persistent environment/semantics code authoring.
- Each TaskPack requires two successful fresh public executions and per-argument
  public/protected provenance validation. Concrete traces are evidence; no
  custom `WitnessRecipe` or value-expression DSL is required.
- Protected state may select and verify a Task but can never supply an acting-time
  operand. S2 starts are reset-only; hidden setup calls, native writes and
  snapshot restoration are forbidden.
- S1 physical Qualification owns atomic evaluator sensitivity. S2 owns concrete
  selector/composition/instruction/answer challenges and checker mutation tests.
- LLM Judge cannot override deterministic state/answer/process failure.
- `TaskDefinition` and `TaskPack` are independent of model-relative trials.
  `TaskAssessment` stores model/policy reliability and cost; `CorpusManifest`
  selects TaskPacks using separate assessment evidence.
- Empirical difficulty/model identity are excluded from structural Task
  fingerprints.
- Parameter changes and paraphrases do not count as new Task structures.
- Persistent `QuarantinedCandidate`, universal tool/state graphs, per-Task
  unrestricted truth code, mutable Registry aliases, demo/MVP and canned Task
  paths are deleted.
- Completion requires the preregistered real SQLite/Git Task-yield and structure
  floors, cold S3-shaped recreation, a framework-frozen held-out Need and
  matched-budget baselines. Unit tests or one Task cannot authorize completion.
- The user explicitly waived `plan-document-write` Alignment Patrol for the
  current planning update. This does not weaken code review, deterministic tests
  or semantic evidence gates.

## Preserved stage boundaries

- S1 produces a qualified immutable `EnvironmentRelease`.
- S2 produces `TaskPack`, separate `TaskAssessment` records and `CorpusManifest`.
- S3 owns acting-Agent Episode execution, final verifier execution and
  Reward/abstention.
- S4 trains only from verified Episodes and cannot redefine environment or Task
  truth.
- MCP, HTTP, provider message envelopes and `tool_call_id` are adapters, not
  environment or Task semantics.
- S1 Research remains evidence-grounded and separate from the Python Codex SDK
  Builder. Candidate tests/model conversations never qualify their own release.

## Execution record

`s2-task-foundry|介入0|返工1|RED/GREEN+mutation-license+Claude BLOCK→ALLOW+full gate|红线违反0`

`s2-task-foundry-cp2|介入1|返工2|real uv/process+13 mutation licenses+Claude BLOCK→ALLOW|红线违反0`

`s2-task-foundry-cp3a-core|介入1|返工1|real Luna strict schema+8 mutation licenses+Claude ALLOW|红线违反0`

`s2-task-foundry-cp3a-wiring|介入2|返工2|real 20-relation Luna+Host journal staging+6 mutation licenses|红线违反1: initially introduced and deleted a duplicate staging subsystem`

`s2-task-foundry-cp3b|介入0|返工2|real Codex SDK+semantic source audit+7 Framework gates+11 mutation licenses|红线违反1: first green gate missed answer and StartCase semantics`

`s2-task-foundry-cp3c-framework|介入1|返工3|real CAP-005 causal trace+4 independent reviews+RED/GREEN+native reconciliation mutations|红线违反0`

`s2-task-foundry-cp3c-live1|介入0|返工1|real Need→Research→Builder→19/19 positive+legacy negative causal audit|红线违反0`

`s2-task-foundry-cp3c-causal-lifecycle|介入1|返工2|archived live trace+Host open/scope topology+19 mutation licenses+3 independent reviews|红线违反1: first mechanical-witness draft trusted global booleans before covers deletion`

`s2-task-foundry-cp3c-local-visibility|介入0|返工2|materialization-local reset/trace provenance+13 mutation licenses+3 model-family reviews|红线违反1: first post-only gate still injected concrete public-tool target values`

`s2-task-foundry-candidate-repair|介入0|返工3|exact resume+permission profile+fresh qualification lineage+24 mutation licenses+3 independent reviews|红线违反2: initial full-access repair could read hidden sibling probes; predicate reuse initially trusted path without digest join`

`s2-task-foundry-qualification-isolation|介入0|返工2|trusted coordinator+separate probe/Candidate sandboxes+opaque execution map+real attack regression|红线违反1: first process split still shared instance-write authority with model-authored probe`

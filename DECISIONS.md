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
  of the Environment Builder. The deleted v1 Qualification machinery is not
  restored or extended.
- One third, qualification-only Codex lineage writes a native verifier package.
  It sees frozen expected semantics and a read-only actor view, but never the
  TaskSemantics project, outputs or repair history. It is archived for cold
  audit and is not an actor, S2 or Consumer runtime.
- Host code freezes Brief-derived expected capability/workflow relations before
  the Semantics Author receives decode-only source/native access.
- Host code owns schemas, manifests, identities, execution of both semantic
  lineages, axis-by-axis comparison, physical negatives, repair ownership and
  final release verdict. Generated code and model consensus are never
  self-authorizing.
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
- Cross-capability `AllGoal` requires an explicit independently qualified
  CompositionRule and exact selected-sibling evaluation context. `IfGoal` may
  reference only a qualified publicly observable `ConditionSpec`.
- TaskChecker is canonical Host-interpreted data compiled from qualified atomic
  semantics. Arbitrary per-Task LLM-authored verifier Python is forbidden; the
  release-level qualification verifier is audit-only and mutually blind from
  TaskSemantics.
- The final canonical instruction is frozen before any witness-model call. The
  witness and later S3 actor receive exactly the same instruction string.
- Public witness search and independent assessments use a Host-owned OpenAI
  Responses tool-calling loop, not Codex SDK. Codex SDK is reserved for
  the three frozen release-local code artifacts and is never the witness loop.
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
- Qualification binds a derived Core ID over frozen actor, semantics, verifier,
  factory, schema and documentation inputs. Publication seals the passed receipt
  into the final descriptor; Qualification never depends on the final Release ID.
- Task definitions bind stable logical referents, not one materialization's
  protected IDs. Each witness/challenge run re-resolves the referent and records
  its own protected resolution evidence.
- Public binding and answer operands carry exact instruction/reset/tool-output
  source references. Composition evaluation receives the selected sibling set;
  no generic scope algebra or universal State IR is introduced.
- Completion requires the preregistered real SQLite/Git Task-yield and structure
  floors, cold S3-shaped recreation, a framework-frozen held-out Need and
  matched-budget baselines. Unit tests or one Task cannot authorize completion.

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

`s2-v2-clean-break|介入1|返工1|12k+ LOC deletion+277 tests+Ruff/Mypy/lock+zero-reference+tree-manifest mutation|红线违反0`

`s2-v2-contract-reclosure|介入1|返工2|3 independent ALLOW+277 tests+task/spec validation+stale S1 deletion|红线违反0`

`s2-checkpoint-b|介入2|返工5|real Builder+verifier+physical matrix+15 mutation licences+3 independent ALLOW|红线违反0`

`s2-checkpoint-c1|介入0|返工1|canonical project identity+real verifier materialization+6 mutation licences+BLOCK→2 ALLOW|红线违反0`

`s2-checkpoint-c2|介入0|返工3|real Semantics Author+attested Core+3 runtimes+10 mutation licences+2 ALLOW|红线违反0`

`s2-c3d-sqlite|介入2|返工3|11 physical cases+4 executable mutants+strict receipt+directory/ZIP relocation+cold audit|红线违反1: prematurely implemented and then deleted unconsumed TaskPack/CaseSpec contracts`

`s2-e-atom|介入0|返工1|admitted release→6 Atom checkers→12 fresh public witnesses|红线违反0`

`s2-f-atom-plan|介入0|返工1|pre-witness plan+real CAP-002 witnesses/challenges+3 mutation licences|红线违反0`

`s2-f-wrong-target|介入0|返工0|preplanned sibling Task+real target success/current rejection+3 mutation licences|红线违反0`

`s2-f-provenance|介入0|返工0|exact argument occurrences+real CAP-002 witnesses+3 mutation licences|红线违反0`

`s2-f-agent-choice|介入0|返工0|precommitted fresh physical perturbations+dynamic rebinding+3 mutation licences|红线违反0`

`s2-f-collateral|介入0|返工0|disjoint-workflow state change+isolated collateral axis+3 mutation licences|红线违反0`

`s2-f-alternative-route|介入0|返工0|fresh non-subsequence public route+same checker+3 mutation licences|红线违反0`

`s2-f-checker-mutations|介入0|返工0|preplanned live result-axis mutants+physical challenges+3 mutation licences|红线违反0`

`s2-f-first-taskpack|介入0|返工0|same-Plan aggregate+control evidence+canonical Atom TaskPack+3 mutation licences|红线违反0`

`s2-foreach-all-vertical|介入1|返工1|complete binding set+2 real public witnesses+4 mutation licences|红线违反1: proposed then fully removed unused Expected Semantics v2 authority fields before commit`

`s2-foreach-partials|介入0|返工0|pre-witness omit-each plan+2 physical partial runs+4 mutation licences|红线违反0`

`s2-foreach-agent-choice|介入0|返工0|shared replay+4 one-at-a-time physical perturbations+2 mutation licences|红线违反0`

`s2-foreach-route-mutations|介入0|返工0|fresh no-op+reverse member order+2/2 aggregate mutants+4 mutation licences|红线违反0`

`s2-foreach-taskpack|介入0|返工1|preselected physical collateral+same-Plan aggregate+8 mutation licences+one external TLS retry|红线违反0`

`s2-if-vertical|介入0|返工0|existing public branch goals+3 compiled referents+4 real witnesses+3 mutation licences|红线违反0`

`s2-if-branch-mutation|介入0|返工0|pre-witness flip-branch plan+4 selected-true/opposite-false runs+2 mutation licences|红线违反0`

`s2-if-taskpack|介入0|返工0|reuse full Atom branch admission+2 conditional witnesses+preimage mutation licence|红线违反0`

`s2-query-taskpack|介入1|返工4|non-leaking reset+13 physical Qualification cases+2 executable reader mutants+cold audit+2 fresh query witnesses+3 framework mutation licences|红线违反0`

`s2-multistart-simplification|介入1|返工2|StartCase-scoped If identity+selected-binding refusal isolation+delete mandatory Atom alternative route+3 refreshed real TaskPacks|红线违反0`

`s2-c-production-runner|介入0|返工1|production run_v2_qualification+18 physical cases+2 executable result mutants+strict publication/cold audit+mutation licence|红线违反0`

`s2-cd-git-repeat|介入0|返工4|18 Git physical cases+dual-reader repairs+strict release+directory-faithful ZIP relocation+5 mutation licences|红线违反0`

`s2-git-e-reclosure|介入0|返工8|all-Task answers+task-kind physics+strict schemas+shared condition bindings+22 cold candidates+6 mutation licences|红线违反0`

`s2-git-f-first-atoms|介入0|返工3|2 current-release TaskPacks+4 AgentChoice rebinds+physical collateral+8 checker mutants|红线违反0`

`s2-git-foreach-wrong-answer|介入1|返工2|v8 real two-witness replay+single-member answer mutation+full ForEach TaskPack+mutation licence|红线违反1: initially used an unnecessary stochastic Agent call for a deterministic checker challenge`

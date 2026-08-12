# Repair plan — minimal typed DesignGraph semantic closure

Revision 2 closes the two blockers in
`cross-layer-review-7731e2cc-design-semantic-closure.md`: an exact
multi-family/tool Verifier→Integration→Judge handoff and an executable
TaskRequirement materialization/reachability/evaluator path. All original
anti-overdesign constraints remain binding. It also closes the three exact
packaging/binding omissions in
`cross-layer-review-53b7b1d5-design-semantic-r1.md`; it adds no node, module or
runtime authority.

## 1. Scope and governing rule

This plan replaces the lossy Design path diagnosed in
`diagnosis-design-semantic-consumer-gap.md`. The canonical product document and
the active node contracts are binding; this plan implements their smallest
coherent semantic centre without restoring the old control plane.

The existing node families remain:

```text
research_plan -> research_acquire -> research_synthesis
-> world_architecture
-> optional shared_tool_semantics[group]
-> tool_semantics[tool]
-> world_rules -> curriculum_plan -> task_requirement[family]
-> modeling_gate -> existing CandidateGraph
```

Physical group/tool/family shards use the existing `shard_key` transaction.
No new graph, node kind, model route, Agent role, model turn category or
production module is added.

## 2. Universal node transaction rule

For every model/Agent node in scope, implementation and tests must bind these
five things together before a proposal can commit:

1. exact model-visible projection;
2. exact Prompt or singleton Runtime Skill;
3. closed output shape disclosed in that Prompt/Skill;
4. framework compiler with path/condition/category `CorrectionPacket`;
5. immutable compiled Artifact fields that at least one named downstream
   consumer reads.

Unknown output fields fail. Framework-only IDs, hashes, schemas, gates,
manifests, routing and release remain absent from model output. No normalizer or
compatibility adapter preserves the current lossy objects.

## 3. Evidence inputs — bounded correction, not a research subsystem

Keep the current one-pass Research topology and real Search/Fetch/Extract; do
not add a research loop or scheduler. Close only information currently lost:

- `ResearchPlan` outputs 1..6 `{query,purpose}` entries, 0..6 sanitized public
  `source_hints` and 1..12 `questions_to_resolve`;
- acquisition consumes only `query`, keeps raw text in memory, and persists
  safe source commitments/citation indexes;
- synthesis outputs typed citation-backed
  `{statement,kind,citation_indexes}` claims plus bounded conflicts and gaps;
  framework compiles a small CoverageMap;
- WorldArchitecture receives claims, conflicts, gaps and the exact citation
  catalog. Later nodes receive only the portions they use.

Use the existing `research-world-evidence` singleton Skill and update its one
bundle only if its disclosed contract is stale. Do not add a Skill to Direct
LLM nodes.

## 4. Compact compiled Design contracts

Use frozen dataclasses in `contracts.py`; do not add Pydantic or a second model
layer.

### 4.1 WorldArchitecture

The Direct LLM receives need/evidence/coverage and returns exactly:

- boundary: name, purpose, system of record, authority and 1..8 actors;
- 1..16 entities with purpose and 1..24 typed fields;
- 1..8 tools with purpose, actor names and typed argument/result fields;
- 0..16 cited known divergences.

`FieldDeclaration` supports only the binding kinds already in
`node-contracts.md`: text/integer/number/boolean/timestamp/identifier/enum/list,
presence, finite enum/list domains and optional entity reference. Framework
validates names, references, citations and closed shape, assigns catalog
indexes, and derives schemas and a conservative `ToolCouplingPlan`. To avoid a
new coupling algorithm, Direct v1 uses one ordered group containing all tools
when `T > 1`, and zero groups when `T == 1`; the model never chooses groups.
This may over-couple tools but cannot silently miss a cross-tool obligation.

Architecture, catalog and coupling plan are one immutable compiled payload.
They are consumed by every later Design node, Builder projection,
`world/world_spec.json`, Registry cold read and future Expand handoff.

### 4.2 SharedToolSemantics

Materialize one Direct shard per derived multi-tool group and no model call for
a zero-group plan. Each shard receives exact ordered tool indexes, their typed
surfaces, a compact shared-state summary and citations. It returns the exact
echo plus bounded typed domains for atomicity, concurrency, idempotency,
ordering and compensation, and a nonempty shared error policy.

Framework validates group-only references, citations and complete coverage:
atomicity/concurrency/idempotency each partition the frozen members exactly;
ordering/compensation are bounded optional domains; error policy covers every
member. It compiles `SharedToolContract` and digest. Each member ToolDraft binds
that digest; group closure fails on a missing/mismatched shard.

For zero groups, downstream declared optional `shared_tools` bindings are empty
and no fake Artifact/WorkRecord/model operation is created. Add only the
smallest runner support for a statically declared optional input port; empty
bindings remain forbidden everywhere else.

### 4.3 ToolSemantics and WorldRules

Keep the existing closed RuleDraft ADT and evaluator rather than creating a
new rule engine.

- Each tool shard receives its complete typed tool surface, framework binding
  catalog, deterministic public assurance probe, optional exact shared
  contract and citations.
- It returns local preconditions/transitions/postconditions/errors only.
- Framework compiles IDs/digest and records the shared-contract digest.
- Modeling Gate selects one applicable precondition and transition for **each
  tool**, not only the first. Integration and Judge later execute separate
  traces for every selected tool assurance.

The ToolSemantics model projection always contains the closed key
`shared_contract`: its value is the exact compiled contract for a group member
and JSON `null` for a singleton/no-group tool. This is distinct from the
graph's empty optional `shared_tools` binding. The ToolDraft digest includes
the contract digest or explicit null.

WorldRules receives the compiled architecture/catalog, shared/tool closure and
coverage. It returns typed `initial_rules` and `invariants`, both allowed to be
empty. Framework compiles them against a bounded architecture-level binding
catalog, rejects local duplicates/tautological empty effects and commits one
`WorldRuleSet` plus digest. Free strings are removed.

Shared prose clauses and unselected/global rules are required Builder/package
inputs but are not mislabeled as dynamically executed. Package fidelity lists
their assurance class explicitly.

### 4.4 Curriculum and executable TaskRequirement

CurriculumPlan returns 1..8 ordered task families while the Prompt asks for the
minimum sufficient set: name, objective, actor index, nonempty ordered tool
indexes, 1..6 ordered dimensions with 2..5 levels, sampling intent and
citations. Prompt and compiler expose the same bounds. Framework derives a
coordinate and exact DifficultySchema per family.

One TaskRequirement Direct shard per family receives only that frozen family,
schema, semantic catalog and compiled rule closure. It returns exact family
index, `public_goal_fields: 1..12` semantic catalog refs and typed
initial/success/failure/terminal rules, with success and terminal nonempty as
declared by the active node card. The Prompt discloses these exact bounds; the
compiler applies the same bounds. The model cannot redefine difficulty, seed,
task ID, reward, Gate or verifier case.

Framework compiles each TaskRequirement into one closed
`ExecutableTaskContract`:

- `public_goal_schema`: a closed object whose required leaves are exactly the
  selected catalog fields and declared JSON categories;
- `initial_config_schema`: the existing closed private Runtime snapshot
  projection for all declared tools/result fields, with no evaluator, reward,
  termination or release field;
- `EvaluatorGoalBinding`: one RFC-6901 identity binding from every required
  public-goal leaf to exactly one required evaluator-goal leaf, with no
  expression, implicit conversion, duplicate or unbound required leaf;
- `instruction_template`: framework-owned deterministic rendering of the
  frozen objective and canonical public goal; candidate text is never used;
- task Rule IR: initial/success/failure/terminal RuleDrafts compiled against
  exact public-goal and private-state bindings;
- `RewardSpec`: failure match gives `-1`, otherwise success match gives `+1`,
  otherwise `0`, independent of rule count;
- `TerminationSpec`: terminal or success/failure match terminates, otherwise
  execution continues within the finite recipe;
- `VerificationRequirements`: exact materialization and reachability coverage
  defined below.

These three framework-owned values have one small canonical JSON form; no
policy object or expression language is introduced:

- `RewardSpec` is exactly
  `{failure: -1, success: 1, otherwise: 0,
  precedence: [failure, success, otherwise]}`;
- `TerminationSpec` is exactly
  `{terminate_on: [terminal, success, failure], otherwise: continue}`;
- each family's `VerificationRequirements` is exactly
  `{task_family_index, require_materialization: true,
  required_recipe_digests: <ordered digests for every scoped tool>,
  required_gates: [task_materialization, task_reachability]}`.

Framework canonical-JSON hashes each value independently as `reward_digest`,
`termination_digest` and `verification_digest`; all three values and digests
are immutable fields of that `ExecutableTaskContract` and therefore of the
committed Design.

The private RuleDraft evaluator is factored only enough to evaluate a frozen
binding catalog and frozen rules. The local-tool evaluator delegates to it; a
task-scoped evaluator uses public goal, pre/final snapshots and tool-result
trace. This remains one closed ADT evaluator, not a generic expression or test
language.

`DesignContract` stores all ordered families/requirements and per-tool local
assurance plans. Delete the first-tool/first-task representations.

### 4.5 Finite assurance recipes and Verifier handoff

Framework derives one ordered `AssuranceRecipe` for every required
`(task_family_index, tool_index)` where the tool is in that family's frozen
tool scope. Models, Builder and candidate code do not choose recipe identity,
seed, concrete values or expected verdict.

Each recipe contains only framework-owned templates:

- family/tool indexes and exact Task/Difficulty/Tool digests;
- primary valid difficulty (first level of every dimension) and, once per
  family, an alternate selection changing the first dimension to level two;
- the family actor;
- a deterministic uint64 seed derived from run/family/tool/recipe ordinal;
- one action prefix that invokes the family's scoped tools once in frozen order
  through the covered tool. Each argument first binds an exact same-field
  public-goal leaf; otherwise framework supplies a deterministic type-valid
  value from FieldDeclaration (first enum value, bounded zero, empty
  text/list, or stable public identifier);
- no exact expected result, answer, witness, evaluator state or release
  threshold. Results are checked against compiled schemas and Rule IR.

TaskRequirement Prompt receives this fixed reachability policy and must author
rules reachable under the finite family tool order. This is a disclosed
compiler condition, not a hidden post-hoc validator.

`verifier_intent` receives the complete public family/tool/recipe catalog,
schemas and rule summaries, but no candidate source, private seed/value,
EvaluatorGoal or release threshold. Its existing closed output remains family
index, tool index, verifier family, optional argument index and risk. Framework
requires the referenced tool to belong to the family, validates argument
applicability, and resolves the one exact baseline `AssuranceRecipe` for that
family/tool pair. Each public `VerifierCommitment` records its commitment ID,
family/tool indexes, variation kind and baseline recipe digest. The matching
same-run `PrivateVerifierCase` repeats those four bindings before carrying the
one permitted private seed, alternate difficulty, idempotency key or
type-preserving argument variation. Before candidate launch, Judge requires
exactly one public commitment by ID, exact equality of family/tool/variation
and recipe digest, and that the digest names the frozen Design recipe for that
pair; missing, duplicate or mismatched bindings fail. Public VerifierBundle
Artifacts retain commitments/counts and safe recipe/coverage digests; concrete
seeds, keys, argument values and difficulty selections remain same-run Judge
memory only. This is one compact record check, not a test language.

Integration executes every baseline AssuranceRecipe without Verifier input.
It validates materializer echoes/schemas, deterministic instruction/goal
binding, difficulty semantic change, result schema, idempotency,
snapshot/restart/teardown and the per-tool local rule trace.

Judge freshly materializes every family, executes every baseline recipe and
compiled private case, then evaluates trusted final state/results against task
initial/success/failure/terminal Rule IR, EvaluatorGoalBinding, RewardSpec and
TerminationSpec. Ordered `task_materialization` and `task_reachability` gates
pass only when real transitions derive terminal success and reward `+1`.
Recipe exhaustion, inconclusive rules or missing family/tool coverage fail.

Safe evidence stores only family/tool/recipe IDs, contract digests, gate code
and status. It excludes public-goal values, initial config, snapshots, results,
private seeds/keys/mutations and EvaluatorGoal.

## 5. Modeling Gate and downstream closure

Modeling Gate is framework-only and fails before Builder unless all expected
evidence, architecture, optional group contracts, tool shards, typed world
rules, curriculum families and task shards are present with matching digests.
It commits the sole canonical EnvironmentDesign.

Update only existing consumers:

- BuildPlan/CandidateBuild receive the compact complete Design and one
  implementation contract; no verifier/Judge/sealed data is added;
- the codegen Skill states the exact typed world, task, shared obligations,
  five-operation Runtime and Materializer contracts, without asking the Agent
  for hashes/manifests/gates;
- Integration executes every public baseline family/tool recipe in fresh
  candidate processes and has no Verifier dependency; Judge executes fresh
  baseline recipes plus the public VerifierBundle/same-run private cases;
- `world_spec.json`, `rule_ir.json`, curriculum/materializer metadata,
  assurance/fidelity and semantic lineage carry the exact compiled values and
  digests;
- Registry cold read recomputes and exact-compares those structures;
- Observe remains read-only and exposes only refs/digests/gate summaries, never
  private state or rule values.

Any changed model-owned semantic field must change the Design semantic digest
and package metadata digest. A field with no named compiler and consumer is
removed rather than retained for possible future use.

The physical metadata map is fixed:

- `world/world_spec.json`: boundary, actors, entities/fields, tools/schemas,
  known divergences and framework coupling plan;
- `world/rule_ir.json`: shared contracts, every local ToolDraft, typed world
  rules, every task Rule IR, each task's exact `reward_spec`,
  `reward_digest`, `termination_spec`, `termination_digest`, and all other
  semantic digests; these values equal the corresponding immutable
  `ExecutableTaskContract` fields;
- `tasks/curriculum.json`: ordered families, actor/tool scopes and exact
  DifficultySchemas;
- `tasks/materializer_protocol.json`: public-goal/initial-config schemas,
  identity bindings, instruction revision, public AssuranceRecipe commitments,
  and each task's exact `verification_requirements` plus
  `verification_digest`; these equal the corresponding immutable
  `ExecutableTaskContract` fields;
- `evidence/assurance.json`: exact Integration/Judge family/tool gate coverage,
  public commitment-to-recipe bindings and contract refs; actual gate coverage
  must satisfy the packaged `verification_requirements` but cannot rewrite it;
- `evidence/fidelity.json`: coverage gaps, known divergences,
  builder-required-unverified classes and reality-equivalence non-claim.

Registry canonical-parses and recomputes every digest above. It exact-compares
`reward_spec`/`reward_digest`, `termination_spec`/`termination_digest` and
`verification_requirements`/`verification_digest` to each immutable
`ExecutableTaskContract`, and exact-compares assurance coverage and public
commitment-to-recipe bindings to Integration, Verifier and Judge Artifacts.
Missing, extra, reordered or altered values fail cold read. Package or Registry
cannot infer missing values from prose.

## 6. Assurance classes and release honesty

Package assurance uses only these fixed meanings:

- `compiled`: shape/index/reference/citation/coverage/digest closure passed;
- `locally_executed`: one selected precondition/transition per tool passed an
  Integration trace and a separate Judge trace;
- `task_executed`: every family materialized and every required family/tool
  recipe reached trusted terminal success with reward `+1` in Judge;
- `builder_required_unverified`: shared prose clauses, unselected local rules
  and global rules were required Builder inputs but are not proven by the
  current evaluator;
- `known_limit`: behavior not expressible or checked in Direct v1.

Do not claim reality equivalence, complete concurrency/compensation semantics,
unselected/global-rule execution or full evidence coverage. A future release profile
that requires one of those properties must fail closed; no model self-score can
upgrade an assurance class.

## 7. File and implementation slices

Replace old code in place; do not layer adapters around it.

1. **Contracts + graph:** `agent_world/contracts.py`, `agent_world/graph.py`,
   focused graph/contract tests. Add compact records and one declared optional
   port rule; delete lossy first-only contracts.
2. **Research + Design compiler:** `agent_world/design.py` and the existing
   Research Skill/tests. Replace simple dict/string compilers and fake shared
   call; no new module.
3. **Candidate/runtime consumers:** `agent_world/candidate.py`,
   `agent_world/runtime.py`, existing Build/Challenge/Codegen Skills and focused
   tests. Replace first-only projections and package verification.
4. **Composition/Observe only if required by changed typed values:**
   `agent_world/foundry.py` and `agent_world/observe.py`; no route or authority
   changes.

Every slice must delete its obsolete representation in the same diff. No
duplicate v1/v2 DTO, migration parser, compatibility branch or dormant future
interface is allowed. No new production file/dependency is allowed. Whole-diff
review must inspect net line growth and block helpers or configuration that do
not serve one exact compiler/consumer.

## 8. Deterministic acceptance

- backend spies prove each node's exact visible projection, disclosed closed
  output and exact correction packet;
- every model-produced field has a direct compiler assertion and a named
  downstream/package equality assertion;
- typed Architecture rejects unknown/schema/control fields, bad references and
  citations; changing a semantic field changes Design identity;
- one-tool Architecture performs zero SharedToolSemantics invocations; a
  multi-tool Architecture gets one exact group contract and rejects incomplete,
  extra or cross-group coverage;
- every tool shard binds its optional group digest; missing/mismatched group or
  tool closure blocks Modeling Gate;
- WorldRules rejects free strings, local duplicates and invalid bindings;
- two-family fixtures create distinct ordered schema-bound task artifacts;
  changed difficulty invalidates the affected task and downstream Design;
- Builder input has the full typed closure and no verifier/sealed material;
- every required family/tool pair has exactly one public baseline recipe;
  VerifierIntent rejects cross-family tools/bad argument indexes and its public
  Artifact excludes concrete private values;
- Judge rejects a private case whose commitment ID, family/tool indexes,
  variation kind or baseline recipe digest is absent, duplicated or differs
  from its public commitment or frozen Design recipe;
- public-goal/initial-config schemas reject missing, extra or wrong-category
  leaves; goal bindings reject missing, duplicate, unbound or non-identity
  leaves;
- Integration executes all baseline recipes without Verifier input; Judge
  executes fresh baseline/private cases and fails missing coverage,
  unreachable, inconclusive or non-terminal/reward results;
- one alternate difficulty changes public goal or initial config; invalid,
  missing, duplicate, reordered or unknown difficulty fails pre-process;
- evidence contains no goal/config/snapshot/result/seed/key/mutation/evaluator
  values;
- package/Registry cold read reject any omitted/altered architecture, group,
  rule, curriculum, task or assurance value, including independent mutations
  of reward, termination, verification requirements or any of their digests;
- fidelity distinguishes compiled, locally executed, task-executed and
  unverified semantics;
- pytest, Ruff format/check, `mypy agent_world tests`, compileall, diff check and
  legacy firewall pass.

## 9. Real proof order

Only after a fresh independent whole-diff check allows:

1. one real Luna WorldArchitecture call with the exact new projection/compiler;
2. if it has multiple tools, one real Luna SharedToolSemantics group and one
   ToolSemantics shard; otherwise prove no shared model call occurred;
3. finish fresh DesignGraph and inspect exact Artifacts/WorkRecords;
4. real CandidateBuild/offline install, all-family Integration and independent
   Judge; read Observe after the terminal;
5. one fresh unfixed natural-language Direct request to Registry and terminal
   Observe.

Any real failure starts a new Observe-based diagnosis. Static check failures
remain static evidence and never get an invented Observe scene.

## 10. Explicit non-goals

No third graph, scheduler, generic workflow/schema/rule platform, callback,
plugin/profile DSL, permission manager, configurable sandbox, second Builder,
LLM Judge/router, automatic Repair, Expand campaign, parent reuse,
Consumer/SFT/RL, full telemetry system, prompt transcript persistence or old
awm/StateGraph/replay/ABI compatibility.

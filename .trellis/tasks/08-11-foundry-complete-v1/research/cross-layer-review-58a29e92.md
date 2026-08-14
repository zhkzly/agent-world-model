# Cross-Layer Review — plan-index-space-reconcile R2 (58a29e92)

Decision: **allow**

## Identity

- Plan digest (sha256): 58a29e920e4b3d8f (short 58a29e92).
- Plan revision: R2 of the plan-index-space-reconcile lineage (diagnosis-6-index-space-divergence).
- Revision count: 2. R1 (digest 8b1ce4bc) was blocked; this R2 is the second and
  final permitted revision for this lineage.
- Reviewed file: research/plan-index-space-reconcile-r2.md.

## Trigger

Real failed Direct/E2E run, run_386e4f07c70d4f61be9cafbf82edcc55 (pure resume),
terminal materializer_public_goal_invalid (families 2 and 4). Diagnosis Record 6
(diagnosis-6-index-space-divergence.md) attributes it to a divergent semantic
index space: the frozen architecture catalog is 4-source (47 bindings) while the
always-recomputed _catalog_categories/_task_bindings are 5-source (60 bindings,
adding reset_state). Two prior blocks: 8436e69e (plan-goal-leaf-mapping) and
8b1ce4bc (plan-index-space-reconcile R1).

## Affected trust boundary

The goal-leaf semantics are a Judge-visible trust boundary: a materializer that
resolves leaf name/source/category by guessed path suffix poisons the
public_goal value and reward/termination reachability. This plan reconciles the
architecture.catalog semantics with the goal-schema category space and makes
the index -> name/source/category correspondence explicit at the codegen
agent's input boundary.

## Repeated product target

Natural-language EnvironmentRequest -> evidence-grounded design -> real isolated
runtime -> independent Judge (all required hard claims) -> immutable Registry
EnvironmentPackage -> safe Observe. This plan advances the Direct first-package
path only; it does not touch Expand or Consumer.

## Essential verification (independent, read-only, this review)

1. Prompt bump kept: Change 1 bumps world-architecture @1 -> @2. Confirmed
   current graph.py:305 declares NodeSpec(..., prompt_id "world-architecture@1");
   graph.py semantic_revision folds prompt_identity into the revision digest, so
   the bump re-invalidates world-architecture on pure resume and recompiles the
   architecture with the current 5-source catalog. R2 KEEPS this (both blocks
   verified fix 1 correct).
2. Mapping relocated to _builder_task: Change 2 adds "public_goal_leaf_map" in
   _builder_task (candidate.py:418), the function called at candidate.py:1086
   inside _projection. R2 drops the _materializer_tasks change entirely.
3. No materializer_protocol.json / Registry key-set change: _materializer_tasks
   (candidate.py:2410) is NOT named in any R2 change. Its output feeds
   tasks/materializer_protocol.json -> _registry exact-key validation
   (candidate.py:3008-3026). Because R2 no longer augments _materializer_tasks,
   the exact-key set {task_family_index, public_goal_schema,
   initial_config_schema, evaluator_goal_bindings, instruction_template_digest,
   assurance_recipes, verification_requirements, verification_digest} is
   byte-stable. Both prior blocks' secondary blocker is addressed.
4. Same catalog as the judge: _projection reads
   bindings = design.architecture.catalog.bindings (candidate.py:1047) and hands
   them to _builder_task (1086). After the @1->@2 bump regenerates the
   architecture, this is the single 60-binding 5-source catalog that also feeds
   _catalog_categories (goal-schema categories) and runtime _task_bindings. The
   leaf map and the judge resolve from one space. Requirement 4 holds.
5. Agent-facing free-form key: _builder_task already emits free-form
   public_goal_fields (NAMES, candidate.py:423-426) and public_goal_schema
   (json_value of the (path, category) tuples, line 432) in design.json. The
   added public_goal_leaf_map is a new free-form field in the agent's input
   projection, not a Registry exact-key artifact; grep confirms
   public_goal_leaf_map appears nowhere today and _registry validates
   materializer_protocol.json / task entries, not design.json. No Registry
   exact-key consumer of design.json task entries exists.

## Impact chain (producer -> consumer)

world_architecture (bump -> regenerate frozen SemanticCatalog, 60-binding
5-source) -> modeling_gate public_goal_schema categories (_catalog_categories)
-> _projection -> _builder_task -> new public_goal_leaf_map in
inputs/design.json -> codegen agent (_candidate_build reads inputs/design.json,
candidate.py:1233) -> candidate materializer.py -> runtime.materialize ->
_validate_materialization -> Judge -> package/Registry -> Observe. The SKILL.md
instruction (Change 3) constrains the agent to resolve leaves through the map,
never via path suffix; its text change re-invalidates candidate_build on resume
via semantic_revision agent_skill_digest (verified in prior blocks).

## Owners

- Producer of the mapping: Designer framework (design.py) + CandidateProjection
  (_builder_task/_projection). Resolution is deterministic (bindings + goal
  schema), held by the framework, not the LLM.
- Single authoritative index space post-bump: architecture.catalog.bindings
  (60, 5-source).
- _materializer_tasks / Registry exact-key owner unchanged (no coordination
  needed in R2 because the protocol is untouched).

## Compatibility facts

- materializer_protocol.json (Registry exact-key artifact) untouched.
- _materializer_tasks (candidate.py:2410) untouched.
- Task Materializer v3 response shape unchanged.
- _validate_materialization / _category / _validate_schema (runtime.py) correct
  and unchanged.
- SKILL.md digest change re-invalidates candidate_build on pure resume (intended).
- Non-blocking type note (carried from 8b1ce4bc): SemanticBinding.source Literal
  (contracts.py:540) omits reset_state, so the 5-source mapping's source field
  legitimately carries reset_state via cast; the type contract should be widened
  at implementation. Not a block reason.

## Unproved consumers

The regenerated materializer/judge passing is NOT claimed; further terminals are
new observations. Expand/Consumer/auto-capture remain unimplemented.

## Smallest allowed implementation and proof plan

1. graph.py: world-architecture @1 -> @2.
2. candidate.py _builder_task: add public_goal_leaf_map resolved from
   architecture catalog bindings + public_goal_schema categories.
3. Widen SemanticBinding.source Literal to include reset_state (explicitly
   coordinate this non-blocking type fact now that the mapping is implemented).
4. SKILL.md engineer-environment-codegen: map every public_goal leaf through
   design.json task.public_goal_leaf_map; never via path suffix.
5. Tests: _builder_task leaf-map test asserting mapping.category ==
   public_goal_schema category at every leaf; full pytest suite green.

No change to _materializer_tasks, materializer_protocol.json, Registry exact-key
set, _validate_materialization, _category, _validate_schema, Task Materializer
v3 response shape, Judge gates, or package manifest.

## Deterministic checks

- Every public_goal leaf's mapping equals (index, name, source, category) AND
  mapping.category == schema category at that leaf; /tmp/validate_mapping.py
  passes on the regenerated architecture. Offline, no LLM calls.
- materializer_protocol.json byte-stable and _registry exact-key check passes
  (unchanged).
- Full pytest suite green.

## True-boundary proof (smallest real)

Offline re-check validate_mapping.py after the @1->@2 regeneration; then the real
pure-resume run run_386e4f07c70d4f61be9cafbf82edcc55 and Observe the terminal.
A regenerated materializer that still fails is a new observation, not proof.

## Explicit non-claims

- Regenerated materializer/judge passing is not claimed.
- The map does not fix the already-frozen candidate; it constrains regeneration.
- Expand/Consumer/auto-capture remain unimplemented.

## Next permitted gate

Dispatch implementation only after the main planner adds this allow record
(digest 58a29e920e4b3d8f) to implement.jsonl and check.jsonl. Then smallest real
proof -> Observe. No further revision remains for this lineage under the skill
(two-revision cap); a new failure opens a new diagnosis and lineage.

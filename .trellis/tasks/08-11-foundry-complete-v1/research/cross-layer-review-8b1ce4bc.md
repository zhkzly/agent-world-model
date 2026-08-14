# Cross-Layer Review: 8b1ce4bc (index-space reconciliation + goal-leaf mapping)

## Decision

**block** — the plan's fix (1) (the world-architecture prompt-id bump) is
correct and genuinely reconciles the divergent index spaces, but fixes (2)-(3)
still misattribute the producer/consumer boundary (the explicit mapping lands
in a Registry artifact the codegen agent never reads) and would break Registry
exact-key validation (the unprescribed `public_goal_fields` key). The plan
writer must revise: keep (1), relocate the mapping to the agent-facing
projection, and coordinate the `_registry` key set in the same plan.

## Identity

- Plan digest (sha256, re-verified): 8b1ce4bc9b62e68da12f9daf4e4a320e08ed0bfbc0d269b10806c7e2416376d9 (short 8b1ce4bc).
- Plan revision: R1 of a NEW lineage (diagnosis-6-index-space-divergence.md; supersedes plan-goal-leaf-mapping.md and the 8436e69e block).
- Revision count: 1 (fresh lineage; skill permits at most 2 revisions per lineage). No prior review under this digest.
- Reviewed file: research/plan-index-space-reconcile.md.

## Scope classification

Claimed Coordinated cross-node, Direct only. The real scope is Coordinated
cross-node and is CORRECTLY classified — the producer
(world_architecture/SemanticCatalog) and consumers (task-rule/task shards,
judge task bindings, materializer contract) do span multiple nodes. The
classification itself is honest; the defect is in fix (2)'s chosen recipient.

## Trigger

Real e2e run_386e4f07c70d4f61be9cafbf82edcc55 (need=用户预订宾馆,
config/agent-world.example.toml), pure resume, terminal rejected /
materializer_public_goal_invalid (families 2 and 4). Prior block 8436e69e
exposed that the goal-leaf name-to-index and index-to-category spaces diverged.

## Diagnosis / Observe evidence (independently verified this review)

- Frozen design catalog (config/.agent-world-runs/runs/run_386e4f07c70d4f61be9cafbf82edcc55/heads.json,
  design:modeling_gate compiled_json) has 47 catalog.bindings rows with sources
  {argument:8, tool_result:13, pre_state:13, post_state:13} — 4-source, no reset_state.
- Current code produces the 5-source layout: agent_world/design.py _catalog()
  and _catalog_categories() both iterate (argument, tool_result, pre_state,
  post_state, reset_state) over result_fields → 60 rows; agent_world/runtime.py
  _task_bindings() emits the same 5-source layout (reset_state at runtime.py:689).
- Measured (uv run python this review): frozen catalog.bindings = 47;
  current _catalog(arch) = 60; current _catalog_categories = 60. Frozen
  sources lack reset_state; current sources add reset_state:13.
- modeling_gate (design.py:2583) builds public_goal_schema categories from
  _catalog_categories (60-space), while public_goal_fields names resolve via
  _name_to_index over the frozen 47-space catalog.bindings (design.py:2341).
  This is the divergence; family 2 /goal/24 carries the wrong category.

## Root cause (confirmed)

architecture.catalog is compiled once per run and persisted frozen.
world-architecture was skipped on resume (prompt_id + inputs unchanged), so
the F4 reset_state change split the frozen 47-binding design catalog from the
always-recomputed 60-binding _catalog_categories space.

## Bump = correct invalidation lever (verified)

- graph.py:305 declares NodeSpec("world_architecture", ..., "world-architecture@1").
- graph.py semantic_revision (graph.py:593-610) folds prompt_identity:
  node.prompt_id into the revision digest, so bumping @1 → @2 changes the
  semantic_revision and forces regeneration on a pure resume.
- Regeneration re-runs design.py:1494 return replace(provisional,
  catalog=SemanticCatalog(_catalog(provisional))), compiling a fresh 60-binding
  5-source catalog into architecture.catalog.bindings, reconciling it with
  _catalog_categories and runtime _task_bindings in one space.
- Requirement 4 holds: _catalog_categories ordering matches _catalog ordering
  (both 60, identical 5-source iteration over result_fields), so a 5-source
  catalog re-derives goal-schema categories consistently.

## Producers/consumers (verified)

- Producer: world_architecture (frozen SemanticCatalog) + modeling_gate schema
  build (design.py). Consumer: implementation-contract projection → the codegen
  agent, then the materializer, Judge, package/Registry.
- The codegen agent (_candidate_build, candidate.py:1205-1234) reads ONLY
  inputs/design.json (= _projection → _builder_task, candidate.py:1041-1089)
  and inputs/implementation-contract.json (= compile_implementation_contract).
- _materializer_tasks (candidate.py:2410-2434) feeds ONLY
  tasks/materializer_protocol.json (package metadata, candidate.py:2515) and
  Registry validation (_registry, candidate.py:3016). It is NOT read by the
  codegen agent.
- Therefore fix (2) — adding public_goal_fields: [{index, name, source,
  category}] to _materializer_tasks — lands in a Registry artifact the agent
  never reads, and fix (3)'s "that explicit mapping" is not actually available
  to the agent from design.json/implementation-contract.json.

## Secondary blocker (verified, repeats 8436e69e)

_registry (candidate.py:3016-3026) asserts each materializer entry has the
EXACT key set {task_family_index, public_goal_schema, initial_config_schema,
evaluator_goal_bindings, instruction_template_digest, assurance_recipes,
verification_requirements, verification_digest}. Adding public_goal_fields to
_materializer_tasks raises registry_task_contract_invalid unless the exact-key
set is coordinated in the SAME plan. The plan does not mention it.

## Compatibility facts (verified, not assumed)

- Task Materializer v3 response shape (the candidate materializer.py output)
  is genuinely unchanged by a correct fix; the plan is right to keep it.
- _validate_materialization / _category / _validate_schema (runtime.py) are
  correct and reject the swapped candidate exactly as designed; unchanged.
- The prompt bump alone reconciles the index spaces (requirement 3 confirmed).
- Type note (non-blocking): SemanticBinding.source Literal (contracts.py:538)
  is {"argument","tool_result","pre_state","post_state"} and omits reset_state;
  the 5-source catalog relies on cast/type-ignore, so the mapping's source
  field will legitimately carry reset_state. The plan should not be blocked on
  this alone, but the type contract should be widened when implemented.

## Repeated product target

Natural-language EnvironmentRequest → evidence-grounded design → real isolated
runtime → independent Judge (all required hard claims) → immutable Registry
EnvironmentPackage → safe Observe. The goal-leaf semantics are a Judge-visible
trust boundary: a materializer that maps goal leaves by guess fails the
category gate or, worse, passes with swapped meaning and poisons
reward/termination reachability.

## Impact chain (producer → consumer)

task_requirement LLM names → _name_to_index over catalog.bindings →
TaskRequirement.public_goal_fields → modeling_gate _catalog_categories →
ExecutableTaskContract.public_goal_schema → _projection/_builder_task →
inputs/design.json (names + paths, no name↔category map) → codegen agent
materializer.py → runtime.materialize() → _validate_materialization → Judge →
package/Registry. Fix (2) must insert the explicit {index,name,source,category}
map on the agent-facing link (design.json projection), not on the package link.

## Owners

- True owner: Designer framework (design.py) + CandidateProjection
  (_builder_task/_projection, design.json path). After the bump the single
  authoritative space is architecture.catalog.bindings (60, 5-source).
- NOT _materializer_tasks as the primary lever for the agent-facing map.
- Registry owner (_registry exact-key) must be coordinated only if the
  materializer protocol is augmented.

## Review questions

1. Advances the Direct first-package path only via fix (1), which is correct;
   fixes (2)-(3) as written advance nothing (map lands in an unread Registry
   artifact and breaks Registry validation).
2. Producer/consumer still partially misattributed in fix (2); no compatibility
   evidence that the agent receives the explicit map.
3. The map would be structurally valid but unreadable by the stated consumer;
   not consumable as designed.
4. Owner ambiguity persists: the plan does not name architecture.catalog.bindings
   (post-bump) as the single authority the agent-facing map is resolved from.
5. revision/digest/secrecy/authority preserved; no credential/sealed data in the
   plan. The skill-digest re-invalidation claim is plausible and orthogonal.
6. Scope classification is honest (Coordinated); the defect is recipient/key-set,
   not scope inflation.
7. No test in the plan asserts the agent-facing projection carries the explicit
   per-leaf {index,name,source,category} map, nor that mapping.category ==
   schema category at each leaf, nor that _registry passes the augmented key set.

## Smallest allowed implementation and proof plan

1. Keep fix (1): bump world-architecture @1 → @2 (graph.py) — this is the
   correct, minimal invalidation lever and reconciles the index spaces.
2. Relocate fix (2): emit the explicit per-goal-leaf {index, name, source,
   category} map (resolved from the now-single 60-binding architecture catalog
   + the public_goal_schema category) in _builder_task/_projection (the
   design.json path) and/or compile_implementation_contract — the artifact the
   codegen agent actually reads — NOT _materializer_tasks.
3. If _materializer_tasks is also augmented for symmetry, coordinate the
   _registry exact-key set (candidate.py:3016-3026) in the SAME plan.
4. Keep fix (3) (SKILL.md instruction) and fix (4) (tests); add a deterministic
   test asserting mapping.category == schema category at every leaf and that
   _registry accepts the (coordinated) protocol.
5. No change to _validate_materialization, _category, _validate_schema, Task
   Materializer v3 response shape, Judge gates, or package manifest.

## Deterministic checks

- Every public_goal leaf's mapping equals (name, source, category) AND
  mapping.category == schema category at that leaf (regression that catches any
  two-space divergence). Offline — no LLM calls.
- _registry exact-key check passes the augmented _materializer_tasks output
  (or the augmentation is dropped).
- Full pytest suite green.

## True-boundary proof (smallest real)

Offline re-check: re-run /tmp/validate_mapping.py on the regenerated
architecture (after bump); then the real pure-resume run
run_386e4f07c70d4f61be9cafbf82edcc55 and Observe the terminal. A regenerated
materializer that still fails is a new observation, not proof of this plan.

## Explicit non-claims

- Regenerated materializer/judge passing is NOT claimed; further terminals are
  new observations.
- The skill-line alone does not fix the current candidate; it only constrains
  future candidates.
- Expand/Consumer/auto-capture remain unimplemented.

## Next permitted gate

Revise the plan (one revision remains this lineage): keep the prompt bump;
place the explicit per-leaf map on the agent-facing design.json projection;
coordinate the _registry exact-key set if _materializer_tasks is augmented.
Resubmit; a fresh allow record then gates implementation → smallest real proof
→ Observe.

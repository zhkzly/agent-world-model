# Repair Plan (R2): reconcile semantic index spaces + agent-facing goal-leaf map

Lineage: plan-index-space-reconcile.md R2 (block of 8b1ce4bc addressed).
The two blocks agreed fix (1) is correct and rejected the mapping's home:
_materializer_tasks feeds Registry-exact-key materializer_protocol.json; the
codegen agent reads inputs/design.json (via _projection/_builder_task). This
revision relocates the mapping to _builder_task and drops the
_materializer_tasks change entirely.

## Scope classification

Coordinated cross-node, Direct only. Producer: world_architecture (frozen
SemanticCatalog) + design.json projection (_builder_task). Consumers:
design shards, judge task bindings, the codegen agent.

## Changes

1. agent_world/graph.py: bump world-architecture prompt id @1 -> @2. Forces
   the architecture to regenerate with the current 5-source catalog
   (argument/tool_result/pre_state/post_state/reset_state); the frozen
   catalog, goal-schema categories, and runtime _task_bindings become one
   index space. (Verified correct by both reviews.)
2. agent_world/candidate.py _builder_task (design.json projection ONLY):
   add "public_goal_leaf_map": [{index, name, source, category}] per goal
   leaf, resolved from the architecture catalog bindings + goal schema.
   The existing "public_goal_fields" (names) stays unchanged; no
   materializer_protocol.json key changes; no Registry key-set change.
3. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md:
   instruct the agent to map every public_goal leaf through
   design.json's task.public_goal_leaf_map (index -> name/source/category)
   and to derive each leaf value from the mapped field semantics + schema
   category — never from the path suffix.
4. tests: _builder_task leaf-map test (test_direct_release) + suite green.

## Compatibility

- materializer_protocol.json (Registry exact-key artifact) untouched.
- Task Materializer v3 response shape unchanged.
- Skill digest change re-invalidates candidate_build on pure resume.
- world_architecture regeneration re-runs downstream design shards with the
  consistent catalog (tool shards recompile to identical content).

## Checks and proofs

- pytest full suite green.
- Offline after regeneration: /tmp/validate_mapping.py must show every goal
  leaf resolving with a category matching its schema row.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim the regenerated materializer/judge passes; further
  terminals are new observations.

# Repair Plan: reconcile semantic index spaces + goal-leaf mapping

Lineage: diagnosis-6-index-space-divergence.md (block of 8436e69e revealed
the divergence; this is a new lineage). Supersedes plan-goal-leaf-mapping.md.

## Scope classification

Coordinated cross-node, Direct only. Producer: world_architecture (frozen
SemanticCatalog) + implementation-contract projection; consumers:
tool/rules/task shards, judge task bindings, materializer contract. One
prompt-id bump + one contract projection + one skill line + tests.

## Changes

1. agent_world/graph.py: bump world-architecture prompt id @1 -> @2. This
   forces the architecture to regenerate with the CURRENT 5-source catalog
   (argument/tool_result/pre_state/post_state/reset_state), making the
   frozen catalog, the goal-schema categories (_catalog_categories), and
   runtime _task_bindings one consistent index space.
2. agent_world/candidate.py _materializer_tasks: add "public_goal_fields":
   [{index, name, source, category}] resolved from the (now consistent)
   architecture catalog + goal schema.
3. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md: instruct
   the agent to map every public_goal leaf through that explicit mapping and
   to derive values from the mapped field semantics + schema category; never
   from the path suffix.
4. tests: mapping test (test_direct_release) + existing suite green.

## Compatibility

- Task Materializer v3 response shape unchanged.
- world_architecture regeneration re-runs downstream design shards (tool
  shards produce identical content; rules/tasks/curriculum recompile against
  the consistent catalog). research evidence is reused.
- The skill digest change re-invalidates candidate_build on pure resume.

## Checks and proofs

- pytest full suite green.
- Offline: after the real architecture regeneration, re-run
  /tmp/validate_mapping.py — every goal leaf must resolve with a category
  matching its schema row.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  (pure resume) and observe the terminal.

## Non-claims

- We do not claim the regenerated materializer/judge passes; further
  terminals are new observations.

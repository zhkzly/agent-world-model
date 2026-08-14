# Repair Plan: goal-leaf mapping in the Task Materializer contract

Lineage: diagnosis-5-goal-leaf-mapping.md. Continues the direct-completion
lineage (fe33df95, 0ff3ae1d allows are spent; this is a new scene).

## Scope classification

Local. Producer: implementation-contract projection (_materializer_tasks in
candidate.py); consumer: the candidate codegen Agent via inputs/
implementation-contract.json; backstop: _validate_materialization (unchanged,
correctly rejects the current candidate). No schema, artifact-envelope,
package, or Registry change.

## Changes

1. agent_world/candidate.py _materializer_tasks: add "public_goal_fields":
   [{"index", "name", "source", "category"}] for every public_goal leaf —
   resolved from task.public_goal_fields (semantic indexes) against
   design.architecture.catalog.bindings (name/source) and the goal schema
   path (category).
2. agent_world/runtime_skills/engineer-environment-codegen/SKILL.md: instruct
   the agent to map each public_goal leaf to its declared field through that
   explicit mapping and to derive its value from the mapped name/category —
   never from the path suffix.
3. Deterministic test: _materializer_tasks output carries the mapping with
   correct name/source/category for a known design (reuse the _design fixture
   in test_direct_release.py).

## Compatibility

- Task Materializer v3 response shape unchanged (the mapping is input
  context, not output).
- The skill digest change intentionally re-invalidates candidate_build; a
  pure resume re-dispatches the codegen agent with the corrected contract.
- Judge/package/Registry untouched.

## Checks and proofs

- pytest full suite green including the new mapping test.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  (pure resume) -> candidate_build re-dispatches; integration/judge then run
  against the regenerated materializer. Observe the terminal.

## Non-claims

- We do not claim the regenerated materializer passes; a further failure is
  a new observation.

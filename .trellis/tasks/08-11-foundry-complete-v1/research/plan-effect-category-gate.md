# Repair Plan: effect-category consistency gate at the modeling gate

Lineage: diagnosis-12-effect-category-gate.md (block of 24da00b3 addressed:
the producer is the design tool_semantics, not the materializer). Continues
the direct-completion lineage after fe33df95 / 0ff3ae1d / 58a29e92 / 3fd31254
/ c0fe624d / 4ec3cd93 / 5ea84b4d allows (all spent).

## Scope classification

Local. Producer: tool_semantics compile gate (design.py); consumer: the
Direct LLM via the node's local_corrections=2 loop. No schema,
artifact-envelope, package, or Registry change.

## Changes

1. agent_world/design.py tool_semantics compile: after compiling
   transitions and postconditions, verify every effect against the target
   field's declared category (from the tool surface):
   - set: scalar value for scalar categories; list for list fields; enum
     membership for enum fields;
   - increment/decrement: target integer/number with numeric value;
   - add/remove: target list;
   - preserve/reject: no value (already enforced).
   Violation -> DesignError("tool_semantics_invalid",
   path=$.transitions[i].effects[j] / $.postconditions[i].effects[j],
   violated_condition naming field, declared category, and the offending
   value: e.g. "field rate_options is declared list but set receives the
   scalar string 'returned_rate_options'; use add with a scalar item or set
   with a list"). The existing local-correction loop re-prompts the model.
2. graph.py: bump tool-semantics prompt id @3 -> @4 so the frozen shards
   recompile under the gate on pure resume.
3. tests: compile-gate test (set scalar into list field rejected with the
   actionable message; category-correct effects accepted).

## Compatibility

- RuleDraft schema unchanged; runtime/checker unchanged.
- Regeneration re-runs tool shards + downstream design nodes.

## Checks and proofs

- pytest full suite green including the gate test.
- Offline bench: after regeneration, integrate() must pass all recipes.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim judge/package/registry pass; further terminals are new
  observations.

# Repair Plan: static guard-conflict gate + guard language clarification

Lineage: diagnosis-7-unsatisfiable-guards.md. Continues the direct-completion
lineage after fe33df95, 0ff3ae1d, 58a29e92 allows (all spent).

## Scope classification

Local. Producer: tool_semantics compile gate (design.py); consumer: the
Direct LLM (correction feedback) and integration (which then sees only
satisfiable contracts). No schema, artifact-envelope, package, or Registry
change.

## Changes

1. agent_world/design.py tool_semantics compile: after compiling
   preconditions, reject any pair of precondition rules that carry eq
   predicates on the same semantic field with DIFFERENT constant values
   (tool_semantics_invalid at $.preconditions, violated_condition:
   "precondition guards are AND-ed and must be jointly satisfiable; express
   alternatives as transitions, not as multiple eq guards on one field").
   The local correction loop re-prompts the model with this message.
2. tool_semantics prompt: state that guards are AND-ed and must hold
   together; alternatives/variants belong in transitions (named anti-pattern:
   multiple eq guards on the same field with different values).
3. graph.py: bump tool-semantics prompt id @2 -> @3 (forces regeneration of
   the frozen shards under the corrected language).
4. tests: compile-gate test (two conflicting eq guards rejected with the
   actionable message; satisfiable guards accepted).

## Compatibility

- RuleDraft schema unchanged; only the design gate tightens.
- Downstream (transitions/checker) unchanged; no runtime change.
- Regeneration re-runs tool shards + their downstream design nodes.

## Checks and proofs

- pytest full suite green including the new gate test.
- Real: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal.

## Non-claims

- We do not claim the regenerated shards pass integration; further
  terminals are new observations.

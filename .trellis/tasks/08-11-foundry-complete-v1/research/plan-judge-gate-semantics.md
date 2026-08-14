# Repair Plan: Judge-gate semantic consistency (diagnosis 14)

Scope: coordinated cross-node, designer + builder lanes, deterministic
framework code only — agent_world/design.py (tool_semantics +
task_requirement compiles and prompts), agent_world/runtime.py (no behavior
change; helper reuse), agent_world/candidate.py (verifier case arguments),
graph prompt ids. Judge authority, release policy, and Registry untouched.

## Change 1 — deterministic reset-value contract (design.py + prompt)

- Module helper `_reset_default(category, values)` in design.py mirroring
  the rendered scaffold's `_default` EXACTLY (boolean False; integer 0;
  number 0.0; list []; enum values[0] else ""; timestamp
  "1970-01-01T00:00:00Z"; else ""). Unit test asserts parity with the
  template's literal for every category (two embeddings, one behavior;
  the standalone candidate runtime cannot import agent_world).
- task_requirement projection: every reset_state row in
  semantic_catalog.fields gains `reset_value` = world_rules.initial_rules
  effect for that (tool, field) if declared, else `_reset_default`.
- task_requirement compile gate: every initial rule must have EMPTY when
  and every effect must be `set` with value == the computed reset value
  of its target binding; violation -> task_requirement_invalid
  correction naming the field, the expected value, and the rejected value
  (within the 280-char CorrectionPacket budget; reuse the budget pattern
  from the goal-field repair).
- Prompt text updated (bumps task-requirement@2 -> @3): initial_rules are
  the verbatim disclosed reset_value rows; when MUST be [].

## Change 2 — transition non-degeneracy gates (design.py tool_semantics)

In the tool_semantics compile (per shard, after rules compile):
- duplicate-when gate: two transitions of the same tool with IDENTICAL
  when predicate sets (same operator/field/value tuples, order-independent)
  -> tool_semantics_invalid correction: "transitions with identical when
  conditions are ambiguous; merge them or differentiate the conditions".
- immutable-when-field gate: a transition when that predicates a
  pre_state/tool_result field of the same tool which NO transition effect
  ever sets -> tool_semantics_invalid correction naming the field
  ("field X is referenced in a when but never changed by any transition;
  the condition can never vary").
- Prompt text updated (bumps tool-semantics@3 -> @4) stating both rules
  and that outcomes must be distinguishable by conditions.
Both shards re-roll on resume (prompt identities changed); family 3's
degenerate submit_reservation and family 1's self-referential
information_ready transitions are re-generated under the gates with 2
correction attempts each.

## Change 3 — design-time recipe outcome simulation (design.py
task_requirement compile, reusing runtime helpers)

At task_requirement compile time, for the frozen family: deterministically
simulate the recipe baseline (primary difficulty, guard-satisfying
arguments via runtime._guard_arguments — import direction design->runtime
is cycle-safe): state = reset defaults; for each tool in
family.tool_indexes in order, apply every transition whose when holds
(effect application identical to the runtime composition checker: set/
increment/decrement/add/remove/preserve; reject -> failure) ; build the
synthetic trace and evaluate the COMPILED success/failure/terminal rules
via runtime._predicates over the trace (task bindings via
runtime._task_bindings). Gate: after the simulated sequence, at least one
success pattern must hold and no failure pattern (the Judge's
terminal_success_reward_plus_one condition). Violation ->
task_requirement_invalid correction stating the simulated post_state
outcome and why success cannot fire ("simulated outcome after the action
sequence: status=failed, reservation_id unset; your success rules cannot
fire; align the task rules with the tool transitions or the design is
unreachable"). The simulation is a Designer structured-correction aid
only — it never grants release authority; the Judge remains the release
gate.

## Change 4 — verifier private cases use guard-satisfying arguments
(candidate.py)

_private_verifier_cases (candidate.py 1598-1649): build the case arguments
from raw defaults first, then run them through runtime._guard_arguments
with the case's tool BEFORE applying variation_kind argument_variation
(variant applied on top of the guard-satisfying value). alternate_difficulty
and unknown_seed cases keep the guard-satisfying arguments unchanged. This
makes the success-trace precondition valid; the composition checker's
precondition_guards requirement is then satisfiable by construction.

## Change 5 — Judge gate evidence carries failure detail

candidate.py _judge_node: persist outcome["detail"] (already produced by
runtime errors in some paths) into the judge.gate_evidence artifact, and
have judge() attach detail for task_outcome failures (which initial rule
mismatched / which outcome patterns held). Bounded, secret-safe (detail is
framework-rendered). This removes the offline-reproduction requirement for
future Judge attributions.

## Explicitly not changed

- No Judge logic, no gate set, no release policy change.
- No design-time reachability as a separate node; no new control authority.
- world_rules node contract stays (empty initial rules remain legal; reset
  falls back to the disclosed deterministic defaults).
- The goal-field name contract repair from the previous slice stays.

## Verification

1. Deterministic: unit tests for _reset_default parity with the template
   literal; initial-rule gate (accept matching, reject each mismatch kind,
   correction <= 280 chars); duplicate-when and immutable-when gates;
   simulation gate against a synthetic family fixture (reachable design
   passes, unreachable design rejected with actionable correction);
   verifier-case guard arguments; gate evidence detail presence. Existing
   293 tests stay green.
2. Real boundary (mandated): pure `uv run agent-world generate --config
   config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55` — observe the re-rolled design
   shards compile, the design graph completes, and the Judge's 20 gates;
   stop at the first new terminal and re-attribute. Registry receipt is
   the only release verdict.

## Product Alignment Checkpoint

pac-judge-node-family.md in the same research dir: canonical goal restated;
trust boundary = designer compile/validator + prompt disclosure + verifier
case construction; Judge/release authority unchanged; unproven = model
convergence under the new gates, the Registry release itself.

# Cross-Layer Review: plan-effect-category-gate (2283a04e)

## Decision

**allow** (with one non-blocking factual correction to the prompt-id bump).

## Identity

- Plan digest: `2283a04e1a18e29e`
- Plan revision under review: the single current revision at
  `research/plan-effect-category-gate.md` (48 lines), which revises the
  lineage after the block of `24da00b3` (diagnosis-11 was superseded by
  diagnosis-12, which correctly re-attributes the producer to the design
  tool_semantics layer, not the materializer).
- Scope classification: **Local**. Producer `tool_semantics` compile gate
  (agent_world/design.py); consumer the Direct LLM via the node's
  `local_corrections=2` loop. No schema, artifact-envelope, package, Registry,
  or control-plane change.
- Revision count for this Diagnosis Record (diagnosis-12): **1**. The prior
  block `24da00b3` was on diagnosis-11/materializer-prefight, a *different*
  diagnosis record; the six listed spent allows (fe33df95 … 5ea84b4d) are
  earlier direct-completion lineage digests, not revisions of diagnosis-12.

## Trigger

Observe -> diagnosis-12-effect-category-gate.md, following the
cross-layer-review-24da00b3 block that re-attributed the defect from the
materializer to the design tool_semantics projection.

## Product target (restated)

Turn an arbitrary natural-language EnvironmentRequest into an
evidence-grounded executable environment, independently verify it in a real
isolated boundary, publish an immutable Registry EnvironmentPackage, and expose
only safe facts through Observe.

## Evidence facts verified (read-only; no live e2e, no model calls)

1. **True producer confirmed in frozen artifacts.** The frozen
   `design.tool_semantics` artifact for `search_rate_options` (tool_index 2)
   at
   `config/.agent-world-runs/runs/run_386e4f07c70d4f61be9cafbf82edcc55/artifacts/…`
   declares `result_fields: rate_options {category:"list", values:["available_rate_option"]}`
   and `availability_status {category:"enum"}`, and its
   `transitions[0].effects[0]` is
   `{"operation":"set","target_semantic_index":45,"value":"returned_rate_options"}`
   — a **scalar string** set into a **list** field (target index 45 =
   `post_state.2.rate_options`). The same scalar `set` reappears in
   `postconditions[0]` and `postconditions[1]`. This is exactly the
   design-layer defect the diagnosis and plan name.

2. **The compile gate has the needed surface.** `_tool_semantics` (design.py
   ~1780-1959) compiles each `ToolSurface` in a closure over `surface`
   (carrying `result_fields` with `category`/`values`) and
   `tool.tool_index`, after `_compile_rules` has produced
   `trans`/`post` (tuple[RuleDraft,...]) with per-effect
   `EffectDraft(target_semantic_index, operation, value)`. The gate provably
   has access to (a) the declared field categories/value sets and (b) the
   compiled transitions and postconditions. The plan's check rules
   (set/increment/decrement/add/remove/preserve/reject) are direct,
   solver-free, deterministic category checks — no solver needed.

3. **Correction consumer is real and correctly wired.** graph.py
   `tool_semantics` NodeSpec declares `local_corrections=2` (line 327).
   `GraphRunner` loops `range(1, local_corrections+2)` and feeds a
   `CorrectionPacket` back to the operation on an eligible
   `NodeExecutionError`; `DesignError("tool_semantics_invalid", path,
   violated_condition, expected_category)` is that error shape. The
   local-correction loop is the correct consumer and will re-prompt the Direct
   LLM.

4. **Sanity / no ABI change.** RuleDraft schema unchanged; runtime/checker
   unchanged; no schema/artifact-envelope/package/Registry change. The gate is
   a pure compile-time validator.

## Affected trust boundary

design tool_semantics compile gate -> Direct LLM (via the node's
local_corrections=2 loop). It tightens the design-layer invariant that an
effect's value must conform to its target field's declared category, closing
the gap the frozen run exposed. Downstream consumers (world_rules,
task_requirement, modeling_gate, candidate_build, runtime rendering) are
unchanged in contract; the gate only rejects previously-accepted invalid
semantics at compile time.

## Impact chain

Direct LLM emits tool_semantics draft -> `_tool_semantics.compile`
`_compile_rules` -> new category gate (set/increment/decrement/add/remove vs
declared category; enum membership) -> on violation
`DesignError("tool_semantics_invalid", …)` -> local-correction loop re-prompts
-> corrected ToolDraft -> (unchanged) downstream design nodes and rendered
runtime. Prompt-id bump invalidates frozen shards so they recompile under the
gate on resume.

## Owners

- Effect category conformance at design: designer / design tool_semantics
  compile gate (new owner for the category check).
- result_field category conformance at invoke: framework runtime (unchanged).
- Correction loop: Direct LLM via graph `local_corrections=2` (unchanged).

## Compatibility facts

- RuleDraft / EffectDraft / ToolDraft wire schema unchanged; byte-identical
  commit path preserved for category-correct effects.
- `local_corrections=2` budget unchanged.
- No new correction field/format introduced beyond the existing
  `CorrectionPacket(code, path, violated_condition, expected_category)`.

## Unproved / correction flags (non-blocking)

- **Prompt-id bump is mis-stated.** The plan says "bump tool-semantics prompt
  id @3 -> @4", but the current graph.py declares `tool-semantics@2` (line
  325); there is no `@3`. The correct bump is **@2 -> @3**. The *intent*
  (invalidate the frozen shard key so it recompiles under the gate) is correct
  and preserved; only the literal version numbers in the plan text are wrong
  and must be corrected at implementation time.
- The gate must resolve `field_name` -> declared category from
  `surface.result_fields` / `surface.argument_fields` (per target semantic
  index), since `_compile_rules` currently reduces names to indices without
  threading category. The plan's intent covers this; implementation must be
  careful not to cross-bind duplicate field names across tools (the existing
  tool_bindings comment already guards this).

## Smallest allowed implementation and proof plan

1. In `_tool_semantics.compile`, after `trans`/`post` are compiled, walk
   each non-`preserve`/`reject` effect; resolve its target to a declared
   field; verify value-vs-category (set: scalar for scalar, list for list, enum
   membership for enum; increment/decrement: integer/number numeric;
   add/remove: list target). Raise `DesignError("tool_semantics_invalid",
   path="$.transitions[i].effects[j]"/"$.postconditions[i].effects[j]",
   violated_condition, expected_category)` naming field, declared category,
   and offending value.
2. Bump the `tool-semantics` prompt id **@2 -> @3** (not @3 -> @4) in
   graph.py so frozen shards recompile under the gate.
3. Add a deterministic compile-gate unit test (scalar set into list field
   rejected with an actionable message; category-correct effects accepted).

## Deterministic checks

- Unit: set-scalar-into-list-field and set-with-wrong-type-for-enum rejected
  with the actionable `violated_condition`; category-correct set/add/increment
  accepted.
- Offline bench: after regeneration, `integrate()` passes all recipes and
  `rate_options` is a list at invoke.

## True-boundary proof

Re-run `agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55`;
observe the recompiled `search_rate_options` tool_semantics commit either
reject the scalar `set` at compile (and correct through the local loop) or
carry a list-valued `rate_options` into the rendered runtime. Terminal is a
new observation.

## Non-claims

- No claim of judge/package/registry pass; those terminals are new
  observations.
- No claim that the gate itself makes the runtime category-correct — the
  runtime's `candidate_property_mismatch` guard remains the authoritative
  boundary at invoke.

## Next permitted gate

Implementation -> deterministic unit + offline bench (integrate) ->
agent-world-real-execution-proof (resume + Observe on the frozen run).

## Omissions (skill requirement)

No Prompt bodies, credentials, sealed data, or runtime control fields recorded.

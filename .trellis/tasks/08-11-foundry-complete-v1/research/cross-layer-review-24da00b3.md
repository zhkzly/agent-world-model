# Cross-Layer Review: plan-materializer-prefight (24da00b3)

## Decision

**block**

## Identity

- Plan digest: `24da00b3f6043e5a`
- Plan revision under review: the single current revision at
  `research/plan-materializer-prefight.md` (45 lines).
- Scope classification: the plan is *claimed* Local (producer
  candidate_build::compile_candidate, consumer codegen agent, one
  local_corrections=1 dispatch). The reviewer classifies the real defect
  boundary as a **coordinated design/framework-runtime semantics issue**, not a
  node-local materializer defect.
- Revision count for this Diagnosis Record (diagnosis-11): 1 (this is the
  first plan revision for diagnosis-11). Prior lineage digests referenced by
  the plan (fe33df95, 0ff3ae1d, 58a29e92, 3fd31254, c0fe624d, 4ec3cd93,
  5ea84b4d) are all separately spent allows on *different* diagnosis records.

## Trigger

Observe -> diagnosis-11-materializer-prefight.md, following a failed offline
integration bench against the frozen design.

## Product target (restated)

Turn an arbitrary natural-language EnvironmentRequest into an
evidence-grounded executable environment, independently verify it in a real
isolated boundary, publish an immutable Registry EnvironmentPackage, and
expose only safe facts through Observe.

## Evidence facts verified (read-only, no live e2e / no model calls)

1. **The frozen materializer is NOT the source of the string.** The frozen
   candidate materializer at
   `config/.agent-world-runs/runs/run_386e4f07c70d4f61be9cafbf82edcc55/candidate_source/materializer.py`
   contains no `semantic_value` and no `conditional_rate` hardcode. Its
   `_value()` returns `["rate-option-" + suffix]` (a list) for
   `category == "list"`, which satisfies `_category`. This contradicts the
   diagnosis's core claim: "semantic_value hard-coded rate_options ->
   'conditional_rate' (string)".

2. **The materializer never produces `rate_options`.** The materializer's
   response is `{seed, task_type, actor, difficulty, public_goal,
   initial_config}` (runtime.py `materialize()`). `rate_options` is a tool
   **result_field**, not a public_goal/initial_config schema entry. Therefore
   `materialize() + _validate_materialization()` (which raises
   `materializer_public_goal_invalid` / `materializer_initial_config_invalid`)
   **cannot** detect a `rate_options` category mismatch. The plan's chosen
   pre-flight targets the wrong producer.

3. **The string value lives in the design-driven runtime, projected by the
   framework.** The frozen candidate `candidate_source/runtime.py` embeds
   `_DESIGN` (rendered by `compile_candidate` via
   `_render_design_driven_runtime`) where `search_rate_options` declares
   `rate_options` category `list`, but its transition is
   `{"field":"rate_options","operation":"set","value":"returned_rate_options"}`
   — a string literal set into a list field. This is a **design-layer tool
   semantics defect** (a `set` effect whose scalar value violates the target
   field's list category), faithfully reproduced by the framework runtime, not
   an agent codegen error. The codegen agent does not implement runtime.py.

4. **The frozen run's actual failures do not contain the claimed code.** The
   run's artifact store failure codes are:
   `materializer_public_goal_invalid`, `local_tool_semantics_mismatch`,
   `candidate_idempotency_failed`, `candidate_protocol_timeout`,
   `candidate_teardown_failed`, `candidate_dependency_metadata_missing`.
   There is **no** `candidate_property_mismatch` and **no**
   `rate_options` "got str" record anywhere in the store. The diagnosis's
   "expected category list, got str ... candidate_property_mismatch" claim is
   not backed by any frozen artifact.

5. **Graph/correction machinery the plan relies on is real.** `candidate_build`
   declares `local_corrections=1` (graph.py). `GraphRunner.execute()` loops
   `range(1, local_corrections+2)` and `_eligible_local_correction` feeds a
   `CorrectionPacket` back to the operation on an eligible
   `NodeExecutionError`. `CorrectionPacket` (contracts.py) requires `code,
   path, violated_condition, expected_category` with bounded formats. The
   dispatch mechanism the plan would reuse is genuine, but the plan directs it
   at the wrong failure.

## Affected trust boundary

The real defect sits at the **design tool-semantics -> framework-projected
runtime** boundary (a `set` transition writing a scalar into a list-category
result field), which is a design/framework contract concern. The plan instead
touches the **candidate_build compile -> codegen agent** boundary (materializer
pre-flight), leaving the true source untouched.

## Impact chain

- Claimed (plan): compile_candidate materialize pre-flight -> correction packet
  -> codegen agent once -> corrected materializer -> integration passes.
- Actual: materializer is already category-correct; the string is emitted by
  the framework-rendered runtime from a design transition. The plan's
  pre-flight would pass silently (or raise the wrong code) and would **not**
  repair the failing value, hiding the failure without advancing the product
  target.

## Owners

- Materializer correctness: builder (codegen agent).
- result_field category conformance at invoke: framework runtime
  (`_result` -> `candidate_property_mismatch`).
- Transition semantic (`set` value must match target field category):
  designer / design tool-semantics output, projected by framework
  `_design_runtime_data`.

## Compatibility facts

- No schema, artifact-envelope, package, or Registry change (plan correctly
  avoids these).
- Correction budget unchanged (1 local correction) — genuine.
- Pre-flight offline + read-only + deterministic (materialize with
  sys.executable) — genuine as a mechanism, but applied to the wrong producer.

## Unproved / contradictory facts

- The "rate_options expected list got str" causal chain is unproved against the
  frozen artifacts and directly contradicted by the frozen materializer and
  runtime sources.
- No compatibility evidence that a materializer pre-flight reaches the actual
  failing string (it cannot, by the materializer's fixed response shape).

## Smallest allowed implementation and proof plan

Do **not** implement the materializer pre-flight as written. Return to
debugging/design: the correct smallest fix is at the design tool-semantics
layer (or its framework projection), correcting the `set` effect that writes
a scalar into a `list` field (e.g. change to an `add`/list-valued effect or
fix the declared transition). A new Diagnosis Record + repair plan targeting
that boundary is required before this critic can allow. If the goal is to catch
category-violating transitions early, a deterministic design-level
transition/effect category check would be the honest scope, but that is a
different plan and boundary than the one submitted.

## Deterministic checks

- Unit: assert `_render_design_driven_runtime` / `_design_runtime_data`
  rejects or normalizes a `set` scalar into a list-category field (or the
  transition validator the new plan chooses).
- Offline bench: after the *design-side* fix, re-run integrate() for all
  recipes; `rate_options` must be a list at invoke.

## True-boundary proof

Re-run the offline integration bench with the frozen design; observe the
`rate_options` result field carry a list at invoke (not a string), tracked as
the actual `local_tool_semantics_mismatch` / category evidence.

## Non-claims

- This review claims no materializer correctness and no integration pass.
- It claims no codegen-agent responsibility for the string-valued
  `rate_options`.

## Next permitted gate

Return to Observe -> agent-world-debugging -> a new Diagnosis Record that names
the *design/runtime transition category* defect and its true producer; then a
new repair-plan revision -> this critic. The materializer pre-flight plan is
blocked as submitted.

## Omissions (skill requirement)

No Prompt bodies, credentials, sealed data, or runtime control fields recorded.

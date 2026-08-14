# Cross-Layer Review — composition view missing reset_state source

- Decision: **allow**
- Plan digest: 4ec3cd9311989413
- Plan revision: 1 (new lineage; prior direct-completion allows fe33df95 / 0ff3ae1d /
  58a29e92 / 3fd31254 / c0fe624d are all spent)
- Scope classification: **Local**
- Revision count: 1 / 2 permitted
- Trigger: failed real Direct/E2E run run_386e4f07c70d4f61be9cafbf82edcc55 (resume
  after idempotency fix), terminal local_tool_semantics_mismatch / composition /
  tool preview_lodging, expected status "" vs actual "not_ready".
- Diagnosis: diagnosis-9-composition-view-reset-state.md.
- Reviewer model: fresh read-only trellis-research critic (independent subagent),
  per trust-boundary trigger (following a failed real Direct/E2E run).

## Product target (repeated)

Turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded
executable environment, independently verify it in a real isolated boundary,
publish an immutable Registry EnvironmentPackage, and expose only safe facts
through Observe.

## Affected trust boundary

Direct composition verification inside candidate runtime evaluation
(agent_world/runtime.py _run_recipe): the reference evaluation of transition
rules must resolve the same binding sources the live runtime sees. This is a
single producer (composition view) -> single consumer (transition predicate
resolution) boundary inside the judge/integration path; no design, schema,
artifact, package, Registry, or Observe surface changes.

## Evidence (verified)

- _run_recipe builds its transition evaluation view with only
  argument/tool_result/pre_state/post_state keys (runtime.py lines 782-787).
- task_trace["reset_state"] is populated immediately after reset
  (runtime.py lines 728-731) as {str(tool_index): snapshot}, so
  task_trace["reset_state"][index] exists at composition time; the precondition
  guard (line 769) already uses task_trace and is unaffected.
- The regenerated frozen preview_lodging tool_semantics is 5-source per field;
  "last binding wins" maps information_ready -> reset_state (idx 26) and
  status -> reset_state (idx 27). Transition [1] is
  when=[{left_semantic_index:26, eq, false}] -> set {target_semantic_index:27,
  "not_ready"} (artifacts 0f87d39979c614… and 8cdb013e2075b3…, both tool_index 1).
- _resolve (runtime.py lines 420-426) walks binding.path
  ("reset_state","1","information_ready") against the view; both keys absent ->
  _MISSING; _predicates line 442-443 returns False for eq on _MISSING, so
  transition [1] never fires in reference eval (expected status ""). The live
  runtime evaluates against actual reset state (information_ready=false) and
  fires it (actual status "not_ready").
- Failure artifact d06431889fd638c9… records exactly
  expected_post_state.status="" vs actual_post_state.status="not_ready",
  failed=composition, tool=preview_lodging.
- run.json final terminal: local_tool_semantics_mismatch / stage run /
  status rejected.

## Impact chain (producer -> consumer)

runtime _run_recipe composition view (producer) -> transition predicate/effect
resolution (consumer) -> expected_post_state composition -> post_state equality
check -> integration/judge terminal. Only the view gains reset_state; composed
field names and the equality check are unchanged.

## Owners

- Composition-view construction and transition resolution: agent_world/runtime.py,
  framework-owned. No prompt/runtime-control field, no new owner, no model
  discretion introduced.

## Compatibility facts

- Trace shape unchanged: task_trace keys (argument/tool_result/pre_state/
  post_state/reset_state) already exist; only the per-transition view is extended.
- Judge task evaluation unchanged.
- SemanticBinding.source Literal in contracts.py omits "reset_state" (a
  pre-existing type-annotation gap); _catalog (design.py) and _task_bindings
  (runtime.py) already emit reset_state bindings via cast/ignore. The plan does
  not widen this and does not need to for correctness.
- No schema, artifact, package, Registry, or Observe change.

## Smallest allowed implementation

One-line change in _run_recipe composition block: add
"reset_state": {index: task_trace["reset_state"][index]} to the view dict
(runtime.py lines 782-787), so reset_state references resolve identically in
reference and runtime. Plus one deterministic test (test_direct_release.py
rendered-runtime test driven through integrate()) covering a tool whose
transition references a reset_state binding.

## Proof plan

- Deterministic check: pytest full suite green, plus the new reset_state-
  referencing rule test.
- Offline bench: integrate() against the frozen regenerated design passes
  (expected post_state status not_ready).
- True-boundary proof: agent-world generate --resume run_386e4f07c70d4f61be9cafbf82edcc55
  and observe the terminal; read Observe after.

## Non-claims

No claim of judge/package/registry pass or release. This fixes reference/runtime
resolution parity only; downstream terminals are new observations requiring a
fresh Observe after the proof.

## Next permitted gate

Implement the one-line fix + test, then agent-world-real-execution-proof, then
Observe. A Product Alignment Checkpoint is required at the proof boundary.

# Product Alignment Checkpoint — task_requirement node family exit

Run: run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆)
Trigger: entry/exit of the design task_requirement node family after the
`task_requirement_invalid` terminal (diagnosis 13).

## Canonical goal restated

Natural-language need -> evidence-grounded design -> real isolated runtime
executing state transitions -> independent Judge (all required hard claims) ->
immutable Registry EnvironmentPackage -> safe Observe. Graph/test progress
alone is not product completion.

## Affected trust boundary and evidence

- Designer compiler/validator boundary (design.py _direct_tasks.compile):
  the goal_lookup rejects the qualified `tool.field` names the rendered
  prompt mandates — evidence: prompt design.py:2599, validator design.py:2452
  + _name_to_index 407-412, failing shard attempts
  control.attempt:318453608ca5eab8/b8d4f03fc8884954/46bda59c1e36b343.
- Direct LLM correction loop: correction packets lack a valid-name set and
  the _object violation omits the offending keys — oscillation across the 3
  attempts (evidence above).
- The plan restores prompt/validator contract coherence with NO prompt bump:
  sibling shard heads stay frozen, only the headless shard re-runs.

## Proof result (real boundary, 2026-08-14 04:01-04:02 +8)

- Pure --resume re-ran exactly the one headless shard
  (track_reservation_status) through the real Direct LLM; the 4 sibling
  shard heads were reused unchanged.
- Attempt 1: extra top-level keys — rejected with the NEW enriched _object
  correction naming the offenders; attempt 2: PASSED. The qualified-name
  rejection observed before is gone; the oscillation died after one
  correction.
- Committed family-4 public_goal_fields = [75, 76, 77] = post_state rows of
  tool 4 (status, confirmation_reference, status_message) — exactly the
  declared tier preference, replacing the old bare-name reset_state
  misresolution [68, 78, 79, 80].
- Design graph completed (modeling_gate passed, design.environment_design
  committed at 04:01:46); candidate graph is running.

## Still unproven

- Attempt-1 acceptance was not achieved (2 attempts); the contract repair is
  proven, single-shot acceptance is not guaranteed.
- Every downstream boundary: modeling_gate closure, candidate build,
  integration, Judge gates, Registry release — the Registry receipt remains
  the only release verdict.
- The earlier builder-side findings (candidate_idempotency_failed,
  materializer_public_goal_invalid, local_tool_semantics_mismatch) are
  separate open evidence, not covered by this repair.

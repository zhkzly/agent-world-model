# T1 / BC-44 minimum report — provider rejection is terminal

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Classification and owner

- Classification from the plan's bad-case table: **provider ↔ infrastructure
  misclassification**. A provider contract rejection must not be promoted to a
  retryable infrastructure failure merely because an adapter supplied a generic
  retryable flag.
- Owner: Scheduler structured-Agent boundary in
  `agent_world/designer/one_shot.py`, with terminal settlement in
  `SchedulerLeafExecutor` / `WorkControlRuntime`.
- Historical source check: commit `6816ea8` already introduced the narrow
  `turn_failed_provider_rejected` non-retryable mapping and its leaf-boundary
  regression. Thus this T1 unit did not invent a product fix or claim a
  pre-existing behavior as newly repaired.

## Deterministic regression evidence

- Added `test_bc44_provider_rejection_cannot_authorize_a_scheduler_retry` to
  `tests/agent_world/test_scheduler_structured_one_shot.py`.
- The test uses the normal `invoke_structured_once` →
  `SchedulerLeafExecutor` → `WorkScheduler` chain, not a replay and not a
  mock success. Its fake backend emits the normal terminal
  `turn_failed_provider_rejected` result with `retryable=True`.
- The WorkDefinition deliberately allows one infrastructure retry and has
  budget for two Agent turns. The observed outcome is nevertheless exactly:
  one backend request, `blocked` head, no `RepairAction`, no ledger entry, and
  a validation report with `infrastructure_retryable=false`.
- The existing leaf-boundary regression separately proves the same terminal
  code becomes `LeafExecutionFailure(retryable=False)`. Together they close
  the mapping from adapter result through durable Scheduler state.

## Verification

- `tests/agent_world/test_scheduler_structured_one_shot.py` plus
  `tests/agent_world/test_scheduler_leaf_executor.py`: `31 passed`.
- Target-file Ruff and format checks passed; `git diff --check` passed.
- No live model turn was required or started: the plan explicitly identifies
  BC-44 as pure deterministic evidence. No test-node output, Registry path,
  release artifact, credential value, base-URL value, raw prompt, or transcript
  was created.

## Outcome and next boundary

BC-44 is verified green. It does not make any semantic proposal valid and does
not authorize recovery of a failed Direct request as release evidence. The next
ordered unit is BC-14 (diagnostic causal-path fidelity); BC-17, BC-47, T2, and
T3 remain blocked behind it.

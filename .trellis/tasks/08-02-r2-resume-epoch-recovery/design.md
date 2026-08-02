# Design — R2 dead-plumbing removal + orphaned running-head recovery

## Part A: remove dead design-checkpoint plumbing

Pure deletion; no behavior change. The live resume path
(`_execute_scheduler_direct_locked`) already ignores `recovered_design`.

Deletions:
- `_recover_direct_design_checkpoint` (`controller.py:4250-4400`).
- `_RecoveredDesignCheckpoint` (`controller.py:487-491`).
- In `resume_generation` (`controller.py:865-948`): drop the
  `recovered_design = self._recover_direct_design_checkpoint(...)` computation
  (921-927) and simplify the telemetry event to use `head.job_ref` as
  `subject_ref` directly (928-936), then drop `recovered_design=recovered_design`
  from the `_execute_direct_locked(...)` call (946).
- `_execute_direct_locked` signature (`controller.py:1013`): remove the
  `recovered_design` parameter; remove `recovered_design=None` at its other
  call site (998).

Verification of `_run_design` (4402): grep shows zero callers. Removing it is
in-scope IF it doesn't drag live helpers; the implementer must confirm its body
references nothing still needed and that removing it keeps the module importing.
If removal widens surface unexpectedly, leave `_run_design` in place and note it
— Part A's mandatory deletions are the checkpoint closure + plumbing only.

LIVE — do not touch: `_run_direct_design_revision` (4718, called at 4973),
`DesignBundle` type, all expansion/revision paths.

## Part B: orphaned running-head recovery

### Root cause (code-verified)
`begin` (scheduler, `work_scheduler.py:540`) durably writes `status="running",
active_operation_ref=None`. The leaf sets `active_operation_ref` only later at
`start_operation` (`leaf_executor.py:995`). A SIGKILL in that window persists a
never-commenced running head (zero model spend). Recovery then can't move it:
`_reconcile_abandoned_operations` skips `active_operation_ref is None`
(`direct_runner.py:1085`); the scheduler pins `running → state="running"`
(`work_scheduler.py:326-331`), never re-dispatched. Outcome:
`scheduler_direct_blocked: unknown scheduler coordinate`.

### Why not just reuse `supersede_stale`
`supersede_stale` DOES handle `running & active_operation_ref is None`
(`work_runtime.py:2111-2131`, marks prior attempt `interrupted /
superseded_stale_execution`, opens ordinal+1). But it FIRST requires
`definition_digest` OR `input_fingerprint` to differ
(`work_runtime.py:2104-2108`, else raises "unchanged terminal work cannot
bypass repair authority"). The orphan is the SAME definition/inputs, so
`supersede_stale` would raise. Weakening that guard would let genuinely
unchanged terminal work bypass repair authority — unacceptable. Hence a
distinct primitive whose justification is "never commenced", not "inputs
changed".

### New runtime primitive
`WorkControlRuntime.resume_uncommenced_running(lock, *, definition, input_refs)`
(work_runtime.py, near `supersede_stale`):
- Read the head via the lock; require `status=="running"` and
  `active_operation_ref is None` (else raise — this primitive is ONLY for
  never-commenced orphans).
- Require `definition_digest == definition.definition_digest` and
  `input_fingerprint == heads.input_fingerprint(input_refs)` (this is the
  same-definition reset; a changed definition is `supersede_stale`'s job).
- Mark the prior attempt `interrupted` with a distinct failure_code
  (e.g. `orphaned_uncommenced_execution`) mirroring the 2116-2131 block; open a
  fresh `running` attempt at `ordinal+1` with the same definition/inputs
  (mirror the attempt-construction at 2144-2167, `repair_mode` e.g.
  `uncommenced_resume`). Return the new head.
- No OperationRun is created here — the leaf's normal dispatch will open it.

### Reconciliation wiring (B2)
`_reconcile_abandoned_operations` (`direct_runner.py:1082-1098`): change the
skip condition. Today: `if head is None or head.status != "running" or
head.active_operation_ref is None: continue`. Split into:
- `active_operation_ref is not None` → existing `reconcile_abandoned_operation`
  path (unchanged).
- `active_operation_ref is None` (and running) → call
  `resume_uncommenced_running(lock, definition=recovery_definition,
  input_refs=…)`. The input_refs come from the same resolution the scheduler
  uses; if not readily available here, resolve via the graph's input closure
  for that coordinate (mirror how `dispatch_one` resolves
  `resolved.all_input_refs`). Confirm the input closure is resolvable at
  reconcile time — a never-commenced node's parents were committed (it was
  `ready`), so its inputs are available.

### Scheduler classification (B3)
Reconciliation runs BEFORE the first scheduler snapshot
(`direct_runner.py:1023` calls `_reconcile_abandoned_operations`, then
`_run_graph` schedules). After B2 resets the orphan, its head is a fresh
`running` attempt — BUT still `status=="running"` at snapshot time, which would
again pin it to `state="running"`. So B2 alone is insufficient UNLESS the reset
also makes it `ready`/dispatchable.

Decision: the primitive opens a fresh `running` attempt (not `ready`), so the
scheduler must recognize it. Cleanest: after B2 resets the prior attempt to
`interrupted`, the head should transition such that the scheduler sees it as
re-dispatchable. Two options:
  (i) B2 resets to a state the scheduler already dispatches (e.g. delete/roll
      the head back to `None` so `dispatch_one`'s `head is None → begin` path
      at `work_scheduler.py:539` re-opens it cleanly). This is the SIMPLEST and
      avoids a new scheduler state: reconciliation rolls the never-commenced
      running head back to absent (prior attempt archived `interrupted`), and
      the normal `ready → begin` flow re-runs it.
  (ii) add `running & active_operation_ref is None → state="stale"` at
      `work_scheduler.py:326-331` and let `dispatch_one`'s `supersede_stale`
      branch handle it — but that re-hits the change-required guard, so it
      would need the new primitive in the `stale` branch too.

FINAL CHOICE (implemented): option (ii) — a fresh `running` attempt + scheduler
reclassification.

Why not (i): rolling the head back to absent would force the scheduler's
`head is None → begin` path, but `begin` hard-codes `ordinal=1` and
`attempt_id="…:1"` and asserts `read_head(...) is None`. The orphan already
persisted attempt-1 artifacts under that exact id, so a re-`begin` would either
collide with the existing attempt-1 revision or silently rewrite it — it cannot
open a clean successor. The head store also has no "roll to absent" transition;
`_validate_transition` only advances revision/ordinal forward. So (i) is not
representable without weakening the store's forward-only invariant.

Option (ii) as implemented:
- `resume_uncommenced_running` archives the orphan attempt as `interrupted`
  (`failure_code="orphaned_uncommenced_execution"`), then opens a fresh
  `running` attempt at `ordinal+1` (via `_next_unused_attempt_ordinal`, so it
  skips any crash-window ids) with the SAME definition/inputs, and commits it
  through the store's ordinary `compare_and_swap` (the `running→running`
  transition is already permitted by `_validate_transition`; unlike
  `supersede_stale` it needs no `changed`/`invalidated_by_refs`, which is
  exactly why a distinct primitive is required for the unchanged-definition
  case).
- Scheduler classification (`work_scheduler.py`): a `running` head with
  `active_operation_ref is None` is classified `ready` (not the un-actionable
  `running`). `dispatch_one`'s ready branch (`work_scheduler.py:546`) already
  tolerates an existing `running & active_operation_ref is None` head, so it
  turns the fresh attempt into real proposal/validation work rather than
  opening a second attempt. This makes the fresh attempt re-dispatchable and
  also means the orphan is no longer a permanent `scheduler_direct_blocked`
  even before reconciliation runs.
- `_reconcile_abandoned_operations` runs first (`direct_runner.py:1023`) and
  archives the prior attempt for a clean audit trail; it resolves `input_refs`
  through the scheduler's `resolve_inputs` (the never-commenced node's parents
  were committed for it to have been dispatched, so its input closure is
  available). It only resets when the frozen head's `work_id`/`definition_digest`
  match the current graph definition; a differing definition is
  changed-definition (supersede) territory and is left untouched.

## Boundaries / invariants preserved
- Orphan reset is gated strictly on `active_operation_ref is None`
  (never-commenced, zero spend). A head with an active operation ALWAYS goes
  through `reconcile_abandoned_operation` (real settlement).
- `supersede_stale`'s change-required guard is untouched.
- No change to committed-head short-circuit (`work_scheduler.py:250-293`) or
  context reuse (`controller.py:1416-1434`).

## Test strategy
- AC-A: grep + existing resume tests.
- AC-B1: runtime unit — orphan head reset vs active-op head routing.
- AC-B2: direct_runner integration — orphan node re-dispatched to committed,
  not stuck at `unknown scheduler coordinate`.
- AC-C: work_runtime + work_scheduler + direct_runner suites green; ruff+mypy.

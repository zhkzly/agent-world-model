# R2 resume recovery — remove dead design-checkpoint plumbing + fix orphaned running-head recovery

## Scope correction (verified 2026-08-02, supersedes stale memory)

The original R2 premise ("resume reader scans flat `design.*` refs, misses the
epoch-stored artifacts, so resume re-runs from Research") is REFUTED by direct
code tracing:

- Normal scheduler-direct resume ALREADY works. It reuses the same
  `scope_id == job.job_id` and the same context root
  (`controller.py:1106`, `1416-1434`), the WorkHead store is durable and shared
  (`controller.py:633/645`), and the scheduler reads each committed head and
  marks it `state="committed"` so it is never re-dispatched
  (`work_scheduler.py:250-293`). A run that died at build resumes at build with
  zero re-run of research/design.
- `_recover_direct_design_checkpoint` (`controller.py:4250-4400`) is DEAD CODE:
  its `recovered_design` result is ignored by `_execute_direct_locked`, which
  unconditionally delegates to `_execute_scheduler_direct_locked`
  (`controller.py:1016-1027`). It survives only as a telemetry
  `resume_subject_ref` cosmetic (`controller.py:928-936`).

So R2 becomes two concrete, evidence-backed deliverables.

## Deliverable A — remove the dead design-checkpoint plumbing

Delete the misleading dead closure so future readers/agents aren't sent down
the flat-`design.*` path again:
- `_recover_direct_design_checkpoint` (`controller.py:4250-4400`).
- `_RecoveredDesignCheckpoint` dataclass (`controller.py:487-491`).
- The `recovered_design` plumbing: its computation + telemetry use in
  `resume_generation` (`controller.py:921-936`), the parameter on
  `_execute_direct_locked` (`controller.py:1013`) and the `recovered_design=…`
  call sites (`controller.py:946`, `controller.py:998`).
- KEEP (verify, do not delete): `_run_design` (4402) — confirm zero callers
  before removing; if removing widens surface, defer to a separate cleanup and
  note it. `_run_direct_design_revision` (4718) is LIVE (called at 4973,
  evolve/expand path). `DesignBundle` is a LIVE type (expansion/revision).

## Deliverable B — fix orphaned "running" head recovery (the real resume gap)

### Confirmed stuck state (all code-verified)
A hard kill (SIGKILL) landing in the window between the scheduler's `begin`
(which durably writes `status="running"`, `active_operation_ref=None` —
`work_scheduler.py:537-545`, `work_runtime.py:2084-2089`, `work_store.py:107/1302-1319`)
and the leaf's `start_operation` (which sets `active_operation_ref` —
`leaf_executor.py:980-999`) leaves a durable WorkControlHead at
`status=="running", active_operation_ref==None`. This node NEVER crossed the
dispatch fence, so it consumed ZERO model/tool work.

On the next `generate` with the same `request_id` (running heads are rejected
by `resume_generation` at `controller.py:879-882`, but reach recovery via
`generate` → `_load_or_recover_direct_result` → `controller.py:9432-9439` →
`_recover_abandoned_scheduler_direct_locked`):
- `_reconcile_abandoned_operations` SKIPS it because `active_operation_ref is
  None` (`direct_runner.py:1085`) — no OperationRun to settle.
- the scheduler classifies `status=="running"` unconditionally as
  `state="running"` (`work_scheduler.py:326-331`), which `run_until_stalled`
  never dispatches. It is never committed, never stale, never blocked.
- outcome projects as `failed` / `scheduler_direct_blocked` with an EMPTY
  `blocked_coordinates` → `failure_summary="Scheduler Direct stopped at:
  unknown scheduler coordinate"` (`controller.py:1381/1391`). Permanent
  non-progression. This is the true mechanism behind
  [[kill-generate-orphan-head-poison]] (the old "TelemetryError" claim is
  refuted).

### Safety
Because the orphan never crossed the dispatch fence, resetting it to
re-runnable cannot double-spend real work. `supersede_stale` already handles
`previous.status=="running" & active_operation_ref is None`
(`work_runtime.py:2111-2131`) BUT guards `definition_digest`/`input_fingerprint`
must have CHANGED (`work_runtime.py:2104-2108`) — which is false for a same-def
orphan. So a dedicated same-definition reset primitive is required; do NOT
weaken the `supersede_stale` change guard.

## Requirements

- R2.A1 — Remove the dead design-checkpoint closure (A above) with zero change
  to live resume/generate control flow; the telemetry `resume_subject_ref`
  becomes `head.job_ref` unconditionally (its only non-None fallback today).
- R2.B1 — Add a runtime primitive (e.g.
  `WorkControlRuntime.resume_uncommenced_running(lock, *, definition,
  input_refs)`) that, for a head with `status=="running" &
  active_operation_ref is None` whose `definition_digest`/`input_fingerprint`
  MATCH the current definition, marks the prior attempt `interrupted`
  (reuse the `superseded_stale_execution`-style path) and opens a fresh
  `running` attempt with the SAME definition/inputs — bypassing the
  change-required guard because the justification is "never commenced", not
  "inputs changed".
- R2.B2 — `_reconcile_abandoned_operations` (`direct_runner.py:1082-1098`):
  extend so a `running & active_operation_ref is None` head is reset via
  R2.B1 (currently it `continue`s past it). Keep the existing
  active-operation reconciliation path unchanged.
- R2.B3 — Scheduler snapshot (`work_scheduler.py:326-331`): a
  `running & active_operation_ref is None` head must NOT be classified as an
  un-actionable `running`. Either rely on B2 having reset it before snapshot
  (preferred — reconciliation runs first at `direct_runner.py:1023`), or add a
  `stale` classification so `dispatch_one`'s `supersede_stale` branch
  re-dispatches it. Choose one and document why in design.md.

## Acceptance Criteria

- [ ] AC-A (unit/grep): `_recover_direct_design_checkpoint`,
  `_RecoveredDesignCheckpoint`, and the `recovered_design` param are gone;
  `grep` finds no references; `resume_generation` and `_execute_direct_locked`
  still compile and their live behavior is unchanged (existing resume tests
  green).
- [ ] AC-B1 (unit): construct a WorkControlHead at
  `running & active_operation_ref=None` with a matching definition; the new
  primitive resets it to a fresh running attempt (ordinal+1, prior marked
  interrupted); a head WITH an active_operation_ref still routes to the
  existing reconcile path (not the new one).
- [ ] AC-B2 (integration): simulate the orphan (running head, no active op) in
  a graph, run `_recover_abandoned_scheduler_direct_locked`/`_run_graph`, and
  assert the node is re-dispatched and can reach committed — NOT stuck at
  `scheduler_direct_blocked: unknown scheduler coordinate`.
- [ ] AC-C: `pytest tests/agent_world/test_work_runtime.py
  tests/agent_world/test_work_scheduler.py` (and direct_runner suite) stay
  green (baseline: the 2 pre-existing work_runtime.py:713 workspace-authority
  fails are independent); ruff + mypy clean on changed files.

## Constraints

- Do NOT `git commit`.
- Do NOT weaken `supersede_stale`'s change-required guard
  (`work_runtime.py:2104-2108`) — add a distinct primitive instead.
- Classify: this is a code defect in recovery classification, not prompt, not
  model. The orphan reset is safe ONLY for `active_operation_ref is None`
  (never-commenced); a head WITH an active operation must still go through
  `reconcile_abandoned_operation` (real-work settlement).
- Independent of R3; may land in parallel.

## Notes

- Related: [[resume-recovery-epoch-flat-ref-mismatch]] (corrected),
  [[kill-generate-orphan-head-poison]], [[task-runtime-resume-topology-recovery-plan]].

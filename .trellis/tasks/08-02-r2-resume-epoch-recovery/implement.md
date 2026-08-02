# Implement — R2 dead-plumbing removal + orphaned running-head recovery

Ordering: Part A (dead-code removal, low risk) → Part B primitive → B wiring →
B scheduler decision → tests → gate. A and B are independent; do A first to
shrink the file and remove the misleading path.

## Part A — remove dead design-checkpoint plumbing

- [ ] A1. Read `controller.py:865-1030` and `controller.py:4250-4470` first to
  confirm current line positions (large file; lines may have shifted).
- [ ] A2. In `resume_generation` (`controller.py:865-948`): delete the
  `recovered_design = self._recover_direct_design_checkpoint(...)` block
  (~921-927). Change the `record_event` (~931-936) to use
  `subject_ref=head.job_ref` directly (drop the `resume_subject_ref` conditional
  at ~928-930). Drop `recovered_design=recovered_design` from the
  `_execute_direct_locked(...)` call (~946).
- [ ] A3. `_execute_direct_locked` (`controller.py:~1002-1030`): remove the
  `recovered_design: _RecoveredDesignCheckpoint | None` parameter (~1013).
  Find its OTHER call site (~998) and remove `recovered_design=None` there.
- [ ] A4. Delete `_recover_direct_design_checkpoint` (~4250-4400) and the
  `_RecoveredDesignCheckpoint` dataclass (~487-491).
- [ ] A5. `_run_design` (~4402): grep for callers
  (`grep -rn "_run_design\b" agent_world/`). If ZERO callers AND its body pulls
  in nothing else live, delete it too. If deletion cascades into live helpers,
  LEAVE it and add a one-line note here. (Mandatory Part A deletions are the
  checkpoint closure + plumbing; `_run_design` is opportunistic.)
- [ ] A6. Remove now-unused imports (e.g. if `_RecoveredDesignCheckpoint` was
  the only user of some symbol). Run mypy/ruff to surface dead imports.
- [ ] A7. Confirm `grep -rn "_recover_direct_design_checkpoint\|_RecoveredDesignCheckpoint\|recovered_design" agent_world/`
  returns nothing.

## Part B — orphaned running-head recovery

- [ ] B1. Read `work_runtime.py:2091-2200` (`supersede_stale`) and
  `work_runtime.py:907-940` (`reconcile_abandoned_operation`,
  `_require_running`) to mirror their exact attempt-construction and head-CAS
  patterns.
- [ ] B2. Add `WorkControlRuntime.resume_uncommenced_running` (near
  `supersede_stale`). Contract per design.md Part B: require `status=="running"
  & active_operation_ref is None`, require matching
  `definition_digest`/`input_fingerprint` (same-definition reset), archive the
  prior attempt as `interrupted` (distinct failure_code e.g.
  `orphaned_uncommenced_execution`), and EITHER roll the head back to absent
  (design option i, preferred) so the scheduler's `head is None → begin`
  re-dispatches, OR open a fresh running attempt (option ii). Pick based on
  what the head store's CAS/rollback permits; if a head cannot go back to
  absent, use option ii + the scheduler stale classification in B4.
- [ ] B3. Wire `_reconcile_abandoned_operations` (`direct_runner.py:1082-1098`):
  replace the single skip with a branch — `active_operation_ref is not None`
  keeps `reconcile_abandoned_operation`; `active_operation_ref is None` (running)
  calls `resume_uncommenced_running`. Resolve the node's `input_refs` the same
  way dispatch does (the never-commenced node's parents were committed, so
  inputs resolve). Read how `dispatch_one` builds `resolved.all_input_refs`
  (`work_scheduler.py` near 529/543) and reuse the resolver.
- [ ] B4. Scheduler (`work_scheduler.py:326-331`): if design option (i) was
  chosen (head rolled to absent), NO scheduler change is needed — verify the
  `head is None` path re-dispatches. If option (ii), add
  `running & active_operation_ref is None → state="stale"` and ensure
  `dispatch_one`'s stale branch (`work_scheduler.py:521-532`) uses the new
  primitive (not `supersede_stale`, which would raise on unchanged def).
- [ ] B5. Update design.md Part B with the final option (i/ii) chosen and why.

## Tests

- [ ] T1. AC-A: a test (or extend existing resume test) asserting
  `resume_generation` still executes and the removed symbols are gone
  (import-level + grep in CI is fine; a focused behavior test that resume still
  reaches `_execute_scheduler_direct_locked` is better).
- [ ] T2. AC-B1 (work_runtime unit): build a head at `running &
  active_operation_ref=None`; assert `resume_uncommenced_running` archives prior
  attempt interrupted and yields a re-dispatchable state; assert a head WITH
  active_operation_ref raises / routes elsewhere; assert a CHANGED-definition
  head is rejected by this primitive (that's supersede_stale's job).
- [ ] T3. AC-B2 (direct_runner integration): construct a graph with one node
  forced to `running & active_operation_ref=None`, run recovery, assert the
  node re-dispatches and the run does NOT terminate as
  `scheduler_direct_blocked` with empty blocked_coordinates.

## Gate

- [ ] G1. `cd /home/kelong/pycodes/agent-world-model && .venv/bin/python -m
  pytest tests/agent_world/test_work_runtime.py
  tests/agent_world/test_work_scheduler.py -q` plus the direct_runner suite.
  Report exact pass/fail; baseline has 2 pre-existing work_runtime.py:713
  workspace-authority fails (independent — do not count as regression).
- [ ] G2. ruff + mypy on controller.py, work_runtime.py, direct_runner.py,
  work_scheduler.py. Clean.

## Constraints
- Do NOT `git commit`.
- Do NOT weaken `supersede_stale`'s change-required guard (2104-2108).
- Orphan reset gated strictly on `active_operation_ref is None`.
- Never delete live evolve/expand paths (`_run_direct_design_revision`,
  `DesignBundle`).

## Rollback
- Part A and Part B are independent reverts. Part A restores the dead closure;
  Part B removes the primitive + reconcile branch (+ scheduler clause if ii).

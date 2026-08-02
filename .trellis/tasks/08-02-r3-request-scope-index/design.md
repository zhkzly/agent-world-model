# Design — R3 scope_id on the direct-job head

## Mechanism (ground truth)

The direct-generation head is the only durable record keyed by `request_id`.
Everything downstream (work-control heads, scope-budget coordinator) is keyed
by `scope_id`, which equals `EnvironmentJob.job_id`. The head stores
`job_ref` but not the derived `job_id`, so any `request_id → scope_id`
resolution today must load the `EnvironmentJob` artifact behind
`snapshot.job_ref` (`app.py:336-339`). We make `scope_id` a first-class,
persisted, immutable head field and stop paying the deref on the hot read path
while remaining backward compatible with heads written before this change.

## Change set

### Write side
1. `DirectJobHead` (`direct_store.py:58-77`): add
   `scope_id: Identifier | None = None`. Nullable so old head JSON validates.
2. `new_direct_job_head` (`direct_store.py:296-323`): add a `scope_id:
   Identifier | None = None` keyword param, pass it into the constructed head.
3. `_RunState` (`controller.py:363-392`): add `scope_id: Identifier`
   (populated at run setup from `job.job_id`, which is already computed at
   `controller.py:798-802`). Prefer threading it into `_RunState` once over
   re-loading the job at each checkpoint.
4. Both construction sites — terminal head (`controller.py:9790-9801`) and
   `_checkpoint_direct_head` (`controller.py:9842-9858`) — pass
   `scope_id=run.scope_id`. New heads therefore always carry a non-null
   scope_id.

### Immutability invariant
5. `immutable_fields` (`direct_store.py:226-233`): add `scope_id`, but with a
   None→concrete promotion allowance. The current invariant compares field
   equality between prior and next head; extend it so that when the prior
   value is `None` and the next is concrete, that is accepted (first
   checkpoint after upgrade), while concrete→different is rejected. Mirror in
   the restart/reconciliation checks (`direct_store.py:190-225`) if they
   independently enforce field stability.

### Read side
6. `DirectRunReader.inspect` (`app.py:230-235`): add
   `"scope_id": head.scope_id or job.job_id`. The `job` (EnvironmentJob) is
   already loaded at `app.py:336` for `_scheduler_budget`; lift that load
   earlier (or reuse it) so the fallback costs nothing extra. For a head that
   predates the field (`scope_id is None`), the fallback reproduces today's
   behavior exactly.

## Boundaries / invariants preserved

- No change to on-disk key derivation (`_key`/`_head_path`): heads stay keyed
  by `request_id`. This adds a stored value, not a new index file.
- No migration of existing head files. Old heads read back with
  `scope_id=None` and resolve via the job-deref fallback.
- scope_id is never invented; it is exactly `job.job_id`. No new identity
  source is introduced.

## Tradeoffs / risks

- Risk: a checkpoint sequence where an early head has `scope_id=None` and a
  later one sets it must be allowed (None→concrete). Covered by the invariant
  allowance (R3.3 / AC3). Concrete→different stays rejected (drift guard).
- Risk: adding a required field would break old-head validation — avoided by
  the nullable default (R3.1).

## Test strategy

- AC1 unit (direct_store test): construct head with scope_id, round-trip JSON;
  load a hand-authored legacy JSON with no scope_id key → `scope_id is None`.
- AC2 unit (app reader test): inspect surfaces head.scope_id when set;
  falls back to job.job_id when None.
- AC3 unit: invariant rejects concrete→different, accepts None→concrete.
- AC4: pytest for direct_store + app reader suites green; ruff + mypy clean.

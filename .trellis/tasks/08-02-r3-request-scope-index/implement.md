# Implement — R3 scope_id on the direct-job head

Ordering: write-side field + factory → run-state threading + both construct
sites → immutability invariant → read-side surface → unit tests → full gate.

## Steps

- [ ] 1. `direct_store.py:58-77` — add `scope_id: Identifier | None = None` to
  `DirectJobHead` (place after `request_ref`/`job_ref` group; keep field order
  stable). Confirm `Identifier` is already imported in this module.

- [ ] 2. `direct_store.py:296-323` — add `scope_id: Identifier | None = None`
  keyword param to `new_direct_job_head`; pass it through to the constructed
  head. Do not reorder existing params.

- [ ] 3. `controller.py:363-392` — add `scope_id: Identifier` to `_RunState`
  (required, not optional — a live run always knows its job). Populate it at
  run setup from the same `job.job_id` computed near `controller.py:798-802`.
  Find where `_RunState` is instantiated and pass `scope_id=job.job_id`.

- [ ] 4. `controller.py:9790-9801` (terminal head) and
  `controller.py:9842-9858` (`_checkpoint_direct_head`) — pass
  `scope_id=run.scope_id` (or the local `_RunState`'s scope_id) into
  `new_direct_job_head`. Every newly written head is now non-null.

- [ ] 5. `direct_store.py:226-233` — add `scope_id` to the `immutable_fields`
  tuple, then adjust the comparison so a `None → concrete` transition is
  allowed while `concrete → different` is rejected. If the invariant is a
  simple equality loop, special-case: `if prior_val is None: accept; elif
  prior_val != next_val: raise`. Mirror in `direct_store.py:190-225`
  (restart/reconciliation) only if those independently enforce field
  stability — read them first.

- [ ] 6. `app.py:230-235` — add `"scope_id": head.scope_id or job.job_id` to
  the `inspect` output dict. Ensure `job` (EnvironmentJob loaded from
  `snapshot.job_ref`) is available at that point; the load already happens at
  `app.py:336` for `_scheduler_budget` — lift/reuse it so `inspect` does one
  job load, not two. Do not change any other returned key.

- [ ] 7. AC1/AC2/AC3 unit tests. Find the existing direct_store + app reader
  test files (likely `tests/agent_world/test_direct_store.py` and an app/reader
  test). If none exists for a given surface, add a focused test:
  - AC1: `new_direct_job_head(..., scope_id="scope-x")` → `stable_json_bytes`
    → `model_validate_json` round-trips scope_id; a dict without the key
    validates with `scope_id is None`.
  - AC2: `inspect` returns `scope_id == head.scope_id` when set, and
    `== job.job_id` when the head's scope_id is None.
  - AC3: the store's checkpoint/put path rejects a next head whose scope_id
    differs from a concrete prior; accepts None→concrete.

- [ ] 8. Gate: `cd /home/kelong/pycodes/agent-world-model &&
  .venv/bin/python -m pytest tests/agent_world/test_direct_store.py -q` plus
  the app-reader suite; ruff + mypy on `direct_store.py`, `controller.py`,
  `app.py`. Report exact pass/fail counts. No regression allowed.

## Constraints
- Do NOT `git commit`.
- Additive + backward-compatible only; no migration of existing head files.
- scope_id is derived from `job.job_id`, never invented.
- Do NOT change `_key`/`_head_path` on-disk keying.

## Rollback
- Revertible unit: the field + factory param + two construct-site args +
  invariant clause + one inspect key. Reverting restores request_id-only heads.

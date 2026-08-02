# R3 request_id → scope_id first-class

## Goal

Persist `scope_id` on the direct-job head so a run can be located from its
`request_id` without prying open the job artifact. Today the direct layer is
keyed solely by `request_id`; the work-control + scope-budget layers are keyed
by `scope_id`; the only bridge is the runtime convention `scope_id ==
job.job_id`, recoverable only by dereferencing `job_ref → EnvironmentJob`. This
missing reverse index is a core reason resume/restart is hard (see memory
[[resume-id-topology-missing-index]]).

## Ground truth (verified 2026-08-02, current tree)

- `DirectJobHead` (`agent_world/control/direct_store.py:58-77`) has NO
  `scope_id`. Head is keyed on disk by `sha256(request_id)`
  (`_head_path`/`_key`, lines 278-283).
- Factory `new_direct_job_head` (`direct_store.py:296-323`) takes no scope_id.
- Two construction sites, both in `controller.py`, neither carries scope_id:
  terminal head (`controller.py:9790-9801`) and `_checkpoint_direct_head`
  (`controller.py:9842-9858`). Both build from `_RunState`
  (`controller.py:363-392`), which has `job_ref` but no `scope_id`/`job_id`.
- `scope_id` is deterministically `job.job_id`
  (`EnvironmentJob.job_id`, `contracts/jobs.py:90`, minted at
  `controller.py:798-802`). The reader already derives it that way at
  `app.py:336-339` (`get_json(snapshot.job_ref, EnvironmentJob).job_id`).
- `DirectRunReader.inspect` (`app.py:198-238`) does not surface scope_id.
- No `request_id → scope_id` reverse index exists anywhere.
- Old heads on disk have no scope_id key → a REQUIRED field would break
  `DirectJobHead.model_validate_json` (`direct_store.py:139-141`).

## Requirements

- R3.1 — Add `scope_id: Identifier | None = None` to `DirectJobHead`
  (nullable so pre-migration heads still validate).
- R3.2 — Populate `scope_id` at both construction sites from the job identity
  (`job.job_id`), threading it through `_RunState` or loading it from
  `run.job_ref`. New heads must always carry a non-null scope_id.
- R3.3 — Add `scope_id` to the head's `immutable_fields` invariant
  (`direct_store.py:226-233`) and the restart/reconciliation checks
  (`direct_store.py:190-225`) so identity cannot drift across checkpoints
  (only allow None → concrete once, never concrete → different).
- R3.4 — `DirectRunReader.inspect` (`app.py:230-235`) surfaces `scope_id`,
  using `head.scope_id` with a fallback to the already-loaded
  `job.job_id` for pre-migration heads (no behavior change for old runs).

## Acceptance Criteria

- [ ] AC1 (unit): a freshly written head via `new_direct_job_head(...,
  scope_id=X)` round-trips scope_id through `model_validate_json`; a legacy
  head JSON with no scope_id key still validates with `scope_id is None`.
- [ ] AC2 (unit): `inspect` returns `scope_id == head.scope_id` when set, and
  `== job.job_id` (fallback) when the head predates the field.
- [ ] AC3 (unit): the immutable-fields invariant rejects a checkpoint that
  changes an already-set scope_id, and accepts None → concrete promotion.
- [ ] AC4: `pytest tests/agent_world/` for the direct_store + app reader
  suites stays green (no regression); ruff + mypy clean on changed files.

## Constraints

- Do NOT `git commit`.
- Additive + backward-compatible only; no migration of existing head files.
- scope_id is derived, never invented — it is exactly `job.job_id`.

## Notes

- Independent of R2; can land in parallel. R4 (DiagnosticClonePipeline) may
  consume the surfaced scope_id but does not block this.

# Design

## Authority and scope

The active task PRD defines the current slice. `PROJECT.md` supplies stable
product intent but does not authorize assumptions about future product code.
Accepted decisions may specialize, never contradict, those documents.

## Components

1. `.trellis/agents/alignment-patrol.md`: project-local, fresh, read-only,
   no-spawn Patrol with the fixed five checks and verdict schema.
2. `.trellis/scripts/run_alignment_patrol.py`: one stdlib CLI for hook/check,
   request collection, hashes, Trellis dispatch, parsing, and runtime state.
3. Platform registrations: Claude compact/resume/fork and Codex
   compact/resume emit a deterministic reminder without spawning Patrol.
4. `.trellis/workflow.md`: post-worker and pre-transition checks.
5. `.trellis/config.yaml`: no session auto-commit or native Codex auto-dispatch.

## Patrol request

For explicit supported operations, the runner resolves canonical active-task
authority from Trellis `task.json`; caller `--task` is only a matching assertion.
For `plan-document-write`, `--candidate-task` must name a planning-status task
under `.trellis/tasks`; its core documents are a separate proposal snapshot,
while stable `PROJECT.md` and `DECISIONS.md` remain authority.
It writes a request below `.trellis/.runtime/alignment/` containing:
trigger and transition; authority content/hashes; staged/unstaged diffs;
untracked snapshots within a byte bound; controller-supplied output/evidence;
and explicit `observed` / `unavailable` lists. The worker cannot select inputs.

## Verdict

Each check is `PASS|FAIL|N/A|UNDETERMINED`.

- `ALLOW`: all applicable checks pass and no material item is undetermined.
- `BLOCK`: a failure exists or required evidence is absent inside the observed boundary.
- `ASK`: no failure, but authority conflicts or required evidence lies outside
  the declared observation boundary.

One request digest covers the task authority, input, repo-visible change set,
and exact transition. Stored verdicts are never consumed as authority. `ALLOW`
certifies one current transition, never global completion.

## Failure behavior

Malformed output, provider error, timeout, missing authority, or missing active
task yields `ASK` and prevents only the requested supported operation.
SessionStart does no semantic review; it always permits discussion and injects
only the deterministic reminder.
Explicit state-changing commands must be in the same shell condition as a fresh
Patrol check, whose nonzero exit prevents the command. Runtime requests,
and verdicts are diagnostic only and never authorize a later action.
`TRELLIS_ALIGNMENT_PATROL=1` prevents recursive startup.

## Reviewer evolution

The role document is the intended tuning surface. It changes independently only
after fixed bad/benign cases show a measured gap. No sixth check category may be
added without user approval.

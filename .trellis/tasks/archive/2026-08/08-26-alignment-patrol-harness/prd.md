# Project Agent Alignment Patrol Harness

## Goal

Add a Trellis-managed, fresh, read-only Alignment Patrol for supported
plan/write/transition boundaries, plus a deterministic compact/resume reminder
that cannot block or steer ordinary discussion.

## Requirements

- Keep `PROJECT.md` as long-term product intent; this task designs harness only.
- Use current task goal, deliverable, non-goals, accepted decisions, attempted
  transition, complete observed change set, and declared unavailable evidence.
- Check exactly five classes: fake implementation, fake completion, causal-free
  patching, overdesign, and guidance/context drift.
- Public semantic checks accept only `plan-document-write`, `worker-turn`, and
  `transition`; new trigger categories require an explicit contract change.
- Each check returns `PASS`, `FAIL`, `N/A`, or `UNDETERMINED` with evidence.
- Patrol returns `ALLOW`, `BLOCK`, or `ASK`; it cannot edit or spawn.
- `ALLOW` is bound to current task/input/diff and allows only one transition.
- A user may explicitly override one exact non-`ALLOW` action, recorded as an
  override rather than relabeled as approval.
- Compact/resume must inject a deterministic reminder on Claude and Codex; it
  must not invoke a model verdict or gate discussion.
- Pure discussion and read-only research never require Patrol.
- Plan-document writes use a scoped review that does not demand future execution evidence.
- Canonical task authority comes from the active Trellis `task.json`; `--task`
  can assert but cannot select it.
- A planning-status task uses `--candidate-task` and remains a proposal judged
  against stable project intent; it cannot become its own authority.
- Patrol requirements live in a separately versioned agent document so they can
  be improved without rewriting the runner.
- Trellis-managed upstream files remain updateable; project-local files use
  unique names and generated-file modifications remain visible to `trellis update`.

## Non-goals

- No product runtime, node, package, Consumer, Registry, or future code design.
- No global product-completion certification.
- No event DSL, daemon, scoring matrix, or promise of complete logs.
- No automatic code repair by Patrol.
- No claim of intercepting arbitrary host, shell, ignored-file, or external writes.

## Acceptance Criteria

- [x] A compact/resume hook emits the shared deterministic reminder and never
      dispatches Patrol.
- [x] The runner collects authority, staged/unstaged/untracked state, transition,
      observed scope, and unavailable evidence without worker selection.
- [x] Patrol is physically read-only and its output schema is fail-closed.
- [x] Old `ALLOW` becomes invalid when task/input/diff/transition changes.
- [x] Context-reset, candidate-plan, and active implementation/lifecycle paths
      are represented in workflow/runner integration.
- [x] Chat-only, plan-document-write, and implementation/lifecycle boundaries
      remain distinct.
- [x] One adversarial case rejects all five failure classes, and one legitimate
      candidate plan is allowed without a completion overclaim.
- [x] Claude/Codex hook JSON and their shared command are validated by direct
      smoke execution; host-driven compact events remain an operational check.
- [x] `trellis update --dry-run` exposes, rather than silently overwrites, local changes.
- [x] A fresh read-only reviewer checks the finished diff against this PRD.

## Optimization Contract

Future improvements should normally edit only
`.trellis/agents/alignment-patrol.md`. Every prompt change must rerun the fixed
bad/benign cases. Runner or trigger changes require their own implementation
task because they change enforcement rather than reviewer judgment.

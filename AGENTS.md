## Project Agent Contract

`PROJECT.md` is stable product intent. The current Trellis task defines the
active harness slice and may not assume a future product implementation shape.
Accepted decisions may specialize, never contradict, those sources.

Discussion-only turns are not state transitions. When the latest user message
asks only for discussion, explanation, design exploration, or read-only
research, answer it directly: do not resume implementation, do not dispatch a
worker, do not edit files, and do not require a Patrol `ALLOW`. An active task
or injected workflow phase does not override the latest user intent.

After compact/resume, inject only the deterministic alignment reminder; do not
run semantic Patrol or gate discussion. Run the fresh, read-only
`alignment-patrol` for persisted plan-document changes, after controlled
write-worker turns, and immediately before supported implementation/lifecycle
actions. Put each supported state-changing action in the same shell condition
as its fresh Patrol check. A non-`ALLOW` result blocks only that attempted
action; stored runtime verdicts are diagnostic and cannot authorize later work.

This is a cooperative, auditable protocol for supported operations, not a claim
that arbitrary host, shell, ignored-file, or external writes are intercepted.

A not-yet-active task produced by discussion is reviewed as a candidate
proposal against `PROJECT.md` and accepted decisions. It is not the current
task and cannot authorize itself. Once explicitly activated, it becomes the
canonical task authority for implementation checks.

On `BLOCK` or `ASK`, surface the verdict instead of silently retrying around it.
An explicit user instruction naming that exact action may override it once;
record this as `OVERRIDDEN(BLOCK)` or `OVERRIDDEN(ASK)`, never as `ALLOW`. A
changed action, diff, task, or scope requires a fresh review.

Patrol checks exactly five failures: fake implementation, fake completion,
causal-free patching, overdesign, and stale guidance/context drift. It may not
edit files or spawn agents. `ALLOW` means only that the current task slice and
transition have no detected violation; it never certifies global completion.

Do not add product nodes, interfaces, packages, Consumers, Registry behavior,
or other future implementation details while the active task is harness design.

<!-- TRELLIS:START -->
# Trellis Instructions

These instructions are for AI assistants working in this project.

This project is managed by Trellis. The working knowledge you need lives under `.trellis/`:

- `.trellis/workflow.md` — development phases, when to create tasks, skill routing
- `.trellis/spec/` — package- and layer-scoped coding guidelines (read before writing code in a given layer)
- `.trellis/workspace/` — per-developer journals and session traces
- `.trellis/tasks/` — active and archived tasks (PRDs, research, jsonl context)

If a Trellis command is available on your platform (e.g. `/trellis:finish-work`, `/trellis:continue`), prefer it over manual steps. Not every platform exposes every command.

If you're using Codex or another agent-capable tool, additional project-scoped helpers may live in:
- `.agents/skills/` — reusable Trellis skills
- `.codex/agents/` — optional custom subagents

Managed by Trellis. Edits outside this block are preserved; edits inside may be overwritten by a future `trellis update`.

<!-- TRELLIS:END -->

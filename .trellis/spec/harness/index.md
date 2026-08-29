# Agent Harness Contract

## Automatic review gates

Alignment Patrol is disabled for this project. Claude Code and Codex must not
register its runner in project hooks, and agents must not invoke it manually as
an implementation, planning, commit, merge, or release gate.

Keep the ordinary Trellis integration surfaces enabled:

- SessionStart injects deterministic task/workflow context;
- UserPromptSubmit injects the current workflow-state breadcrumb;
- sub-agent startup injects the active task context;
- implementation quality is established by deterministic tests and independent
  code review.

The dormant runner and agent card may remain as historical tooling, but neither
is an active project authority.

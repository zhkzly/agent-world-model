# Accepted Decisions

- 2026-08-26: Current work is project-level Agent harness design and
  implementation only; future product code shape is undecided.
- 2026-08-26: Alignment Patrol uses three triggers and exactly five historical
  failure checks; it is fresh, read-only, no-spawn, and transition-scoped.
- 2026-08-26: Patrol judgment is independently tunable in
  `.trellis/agents/alignment-patrol.md`; enforcement changes require a separate
  reviewed task and must not be smuggled into prompt tuning.
- 2026-08-26: Patrol runtime files are diagnostic, never reusable authority;
  every state-changing transition is directly conditioned on a fresh check.
- 2026-08-26: Discussion and read-only diagnosis are never gated by Patrol.
  Compact/resume injects a deterministic neutral reminder, not a model verdict.
- 2026-08-26: Patrol is an auditable protocol for supported operations, not
  universal host-write enforcement. A controller is deferred until a measured
  bypass justifies it.
- 2026-08-26: Canonical task authority comes from Trellis active-task metadata
  (`task.json`); `--task` may only assert, never choose, that authority.
- 2026-08-26: A planning-status task is a candidate proposal, not active
  authority. `plan-document-write` reviews it against stable project intent via
  explicit `--candidate-task`; activation is a later user-authorized boundary.

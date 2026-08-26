# Accepted Decisions

- 2026-08-26: Superseded by the explicit user authorization below: the prior
  harness-only work boundary ended after the harness task was completed.
- 2026-08-26: Current authorized scope is clean-room co-design of S1 Environment
  Foundry and S2 Task Foundry semantics. Only S1 may have an implementation
  plan. Product implementation remains prohibited until the cross-layer
  S1/S2 design passes independent review, the user approves the final planning
  summary in a later turn, and Trellis activates S1 for implementation.
- 2026-08-26: S1 is implemented and physically released before S2 receives an
  implementation plan. The S2 semantic design is then revalidated against the
  real S1 package before S2 implementation planning starts.
- 2026-08-26: S1 planning and later implementation may use only the current
  clean-break branch, current task authority, live user decisions and current
  primary external sources. Product code, tests, fixtures, prompts, Skills and
  plans from old branches or commits are excluded inputs.
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
- 2026-08-26: Product handoffs are context contracts: S1 produces a qualified
  `EnvironmentRelease`; S2 consumes it and produces a sealed `TaskPack`; S3 consumes
  both and produces a verified Episode/Reward; S4 consumes verified Episodes.
- 2026-08-26: The canonical S1 environment surface is transport-neutral
  `reset/tools/invoke/close`. `reset` returns the structured initial public
  observation; every invoke result is the uniform `ToolObservation{ok,data,error}`
  with schema-described success data. MCP, HTTP, provider messages and
  correlation IDs are caller adapters only.
- 2026-08-26: Graph-based and Programmatic generation remain S2 mechanisms.
  They consume the same released environment, schemas, public documentation and
  real observations and may not impose sampler-specific fields or interfaces on
  S1.
- 2026-08-26: Independent S1 Qualification may inspect candidate source to
  understand arbitrary native formats, but derives expected behavior from the
  Need/Brief and uses independent native readers rather than candidate business
  functions. Mutation is an optional test-sensitivity technique, not a product
  role or public contract.

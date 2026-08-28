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
  explicit `--candidate-task`; it is not treated as active authority.
- 2026-08-26: Product handoffs are context contracts: S1 produces a qualified
  `EnvironmentRelease`; S2 consumes it and produces a sealed `TaskPack`; S3 consumes
  both and produces a verified Episode/Reward; S4 consumes verified Episodes.
- 2026-08-26: The canonical S1 environment surface is transport-neutral
  `reset/tools/invoke/close`. `reset` returns the structured initial public
  observation; every invoke result is the uniform `ToolObservation{ok,data,error}`
  with schema-described success data. MCP, HTTP, provider messages and
  correlation IDs are caller adapters only.
- 2026-08-26: Superseded on 2026-08-28: Graph-based and Programmatic generation
  were previously required as S2 mechanisms consuming the released public
  environment surface.
- 2026-08-26: Independent S1 Qualification may inspect candidate source to
  understand arbitrary native formats, but derives expected behavior from the
  Need/Brief and uses independent native readers rather than candidate business
  functions. Mutation is an optional test-sensitivity technique, not a product
  role or public contract.
- 2026-08-26: S1 Research is one OpenAI Responses SDK Agent with one method
  Skill and exactly two Agent-visible capabilities: `search_sources` for
  discovery-only candidates and `read_sources` for Agent-selected retrieval,
  immutable source capture and Crawl4AI extraction. The Python Codex SDK remains
  the separate coding-focused Builder transport. Research does not use raw
  app-server JSON-RPC, MCP, a shell imitation or a fixed framework search loop.
- s1-environment-foundry|介入2|返工2|Need 换行等价、standalone uv workspace、cold publication|红线违反0

## 2026-08-28 S2 clean redesign

- The user explicitly authorized a complete S2 redesign. Preserving the old S2
  proposal, maintaining backward compatibility and retaining the old release
  format are not requirements. S1 may be changed where the new S2 requires a
  cross-environment contract.
- S2 is goal-first. A sampled graph, random walk, successful trace or generated
  program is not the source of Task meaning. Graph search and program synthesis
  may be later planner optimizations, but neither is a mandatory Task lane or
  semantic authority.
- High-quality automatic Task synthesis is supported only for releases that
  publish independently qualified taskable capability semantics. S1 v2 binds a
  protected release-local `SemanticsBundle` containing deterministic start
  cases, read-only state inspection, parameterized CapabilitySpecs, binding
  enumeration and atomic evaluation. It remains hidden from acting Agents.
- The S1 Semantic Author is independent of the Environment Builder thread. It
  freezes Brief-derived expected relations before decode-only source/native
  inspection. The Host owns manifests, execution, physical near misses, evidence
  aggregation and the final semantic-qualification verdict.
- S2 compiles a bounded GoalProgram from qualified capability atoms. The core
  node set is `Atom`, `Select`, `If`, `All`, `ForEach` and `Report`. It is not a
  universal state or business-rule language and does not execute arbitrary
  generated Python as Task truth.
- A TaskChecker is compiled and digest-frozen from GoalProgram, start facts,
  protected bindings and qualified atomic evaluators before any reference
  planner executes. The reference witness can prove reachability but cannot
  author or modify the checker.
- The public witness planner receives only actor-visible Task/reset/docs/tools
  and observations. Every persisted argument is reduced to a public provenance
  expression and freshly replayed. Protected state may select and verify a Task
  but may never supply an acting-time operand.
- S2 creates starts only through S1-qualified `reset(start)` cases. Hidden setup
  programs, direct SQLite/file/Git mutation and generic snapshot restoration are
  removed from the design.
- Final Task satisfaction is deterministic over protected facts, public trace
  and structured answer. An LLM Judge cannot turn a deterministic failure into
  success. Optional LLM paraphrasing is surface-only and must round-trip to the
  same public instruction frame.
- Atomic native-reader/evaluator sensitivity belongs to S1 physical
  Qualification. S2 challenges GoalProgram composition, selectors, sets,
  answers, wording and declared process rules. Admission must cover applicable
  positive, fresh replay, no-op, wrong-target, near-miss, partial, collateral,
  wrong-answer and valid-alternative cases.
- Persistent `QuarantinedCandidate`, mandatory Graph/Programmatic lanes,
  per-Task unrestricted TruthExtractor/OutcomeVerifier generation, hidden setup,
  universal State IR, mutable Registry aliases and demo/MVP success paths are
  deleted from the product design.
- The previous S1 releases remain useful engineering evidence, but the new
  contract is a clean `EnvironmentRelease v2`. A public preparation/open API and
  per-release interpreter/process isolation are part of S1 v2 because S2, S3 and
  third-party consumers share that need.
- The current `s2-task-foundry` Trellis task owns the S2 implementation plan and
  the minimum S1 v2 changes it requires. It remains `planning`; plan persistence
  is not implementation authority. A fresh plan-document Patrol and a later
  explicit user approval are required before `task.py start` or product-code
  work.

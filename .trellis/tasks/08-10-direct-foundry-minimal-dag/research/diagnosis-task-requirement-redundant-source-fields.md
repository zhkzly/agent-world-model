# Diagnosis — TaskRequirement asks the model to emit framework-owned null data

## Observed event

- Public run: `run_a4cc77f4344e4aeba96ad081223bca70`.
- Safe terminal: `rejected`, code `task_requirement_invalid`, release
  `not_published`.
- The run passed Research, WorldArchitecture, SharedToolSemantics, all seven
  ToolSemantics shards, WorldRules, and CurriculumPlan. It stopped at the
  first `task_requirement[member_registration]`; Candidate, Integration,
  Judge, Package, and Registry did not start.
- Proposal one was rejected at `$.failure_rules[0].error_kind` because a
  non-error task rule must use `null`. The same frozen node received the
  precise correction. Proposal two still failed the same safe condition.
- The two Direct operations used Luna and reported 10,876/11,828 input tokens.
  Raw provider output is intentionally not persisted, so the model's private
  rationale and exact rejected bodies remain unknown.
- The frozen first-family projection contains a roughly 10.9 KB
  `semantic_catalog.bindings` array and embeds the same roughly 10.9 KB array
  again under its one relevant compiled ToolDraft. The DifficultySchema is
  likewise present inside `family` and again as a top-level field.
- Re-projecting the same frozen semantics once, without framework metadata,
  reduces canonical input JSON from roughly 37 KB to 25 KB; no rule, field,
  citation, actor/tool scope, or difficulty meaning is removed.

## Expected behavior sheet

The natural-language request should progress through evidence-grounded Design,
an isolated executable Candidate, independent Judge, and immutable Registry
EnvironmentPackage. At this node, Luna should supply only open business
semantics for one frozen task family. Framework code should own deterministic
representation facts, compile the proposal into the unchanged `RuleDraft` and
`TaskRequirement`, and fail closed only on a real semantic/contract violation.
One bounded actionable Feedback turn may request a complete replacement; it
does not transfer validation or release authority to the model.

## Chronological trace and first deviation

1. Framework selected the first frozen curriculum family and supplied its
   family data, the same DifficultySchema both inside `family` and again as a
   top-level field, the SemanticCatalog, relevant ToolSemantics containing a
   second complete copy of the same catalog bindings, WorldRules, and
   CitationCatalog. It also exposed framework-computed digests that the model
   neither chooses nor consumes.
2. The disclosed output shape reused the generic `RuleDraft` source shape for
   four task-rule sections. Every rule therefore had to emit
   `error_kind:null`, even though all four sections are definitionally
   non-error and the model has no choice to make.
3. Luna emitted a non-null value in one failure rule. The strict compiler
   correctly rejected it and GraphRunner delivered an exact next-user
   correction requesting `null`.
4. Luna's complete replacement still violated that same condition, so the
   bounded transaction failed and the graph stopped.

The first causal deviation is step 2: a deterministic, framework-owned null
was exposed as repeated model-authored output. The validator and Feedback
correctly described the declared contract; they cannot make that ownership
choice useful.

## Five-lens attribution

1. **Project Agent view — supported.** Observe names the exact graph/node/shard,
   attempts, safe condition, committed parents, and non-release terminal.
2. **Effective Direct Prompt/input — weakened.** It requires redundant
   `error_kind:null` on every non-error task rule and duplicates the exact
   DifficultySchema, duplicates the complete SemanticCatalog inside each
   relevant ToolDraft, and exposes model-irrelevant digests.
3. **Direct no-Skill invariant — supported.** Both operations are recorded as
   `direct_llm`, model `gpt-5.6-luna`, with no Skill digest, tools, or workspace.
4. **Code/execution boundary — supported but owns the wrong source field.** The
   compiler rejects strictly and no Python exception leaks; the committed
   `RuleDraft.error_kind` should remain, but its fixed `None` value belongs to
   the framework at this task-only source boundary.
5. **Feedback/observability — supported.** The recipient received the exact
   path and required condition. The second failure is visible and safely
   terminal. Raw output absence prevents claims about private model reasoning
   but does not obscure the ownership defect.

## Alternatives considered

- More retries or a generic retry platform: rejected; the field has no model
  choice and the existing two-proposal bound worked as declared.
- Weaken parsing or accept arbitrary non-null `error_kind`: rejected; strict
  compilation remains required.
- Split TaskRequirement into more graph nodes: rejected; there is no new
  independent consumer or repair owner.
- Redesign all RuleDraft nodes or remove semantic predicates/effects: rejected;
  this run proves only the task-only redundant field and exact duplicate or
  deterministic projection data.
- Blame model capacity or Luna compatibility: weakened. The provider and
  structured transport worked, all preceding Direct nodes passed, and the
  observed condition is a needless deterministic field. Input size may affect
  reliability, but only the exact duplicate is currently evidenced for safe
  removal.

## Causal hypothesis and smallest next proof

If the TaskRequirement source shape omits `error_kind`, the task-only compiler
injects `None`, and its input explicitly projects each upstream semantic once
without repeated bindings, schema, artifacts, or digests, Luna can spend its
context and output only on business rule semantics while the committed
`TaskRequirement` and all downstream consumers remain shape compatible.

First prove deterministic omission/injection, strict rejection of other extra
or invalid fields, unchanged committed `RuleDraft`, one DifficultySchema and
one SemanticCatalog copy with no framework metadata, and semantic revision
change. Then invoke only the exact frozen
`member_registration` TaskRequirement boundary and read Observe. This does not
prove the remaining task shards, Candidate, Judge, Registry, E2E, Repair,
Expand, or Consumer.

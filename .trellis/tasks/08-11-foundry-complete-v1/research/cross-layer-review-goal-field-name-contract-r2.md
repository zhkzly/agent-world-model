# Cross-Layer Review — goal-field name contract (diagnosis 13), revision 2

Date: 2026-08-14 (session)
Reviewer: independent read-only cross-layer critic (delegated)
Lineage: diagnosis-13-goal-field-name-contract.md -> plan-goal-field-name-contract.md
Revision 1 digest e9bbe389 was **blocked**; this is revision 2 of 2.

## Decision

**allow**

All three revision-1 feedback items are verifiably addressed, and the unchanged
core of the plan remains correct against the frozen code. The plan is the
smallest coherent scope and makes the downstream compatibility/proof explicit.

## Plan digest

- sha256 of complete plan file content: `bc6988c59e65db49caf873446f4faf7487540aeebb304165ad8429ccfca6c3a2`
- plan digest (first 8 hex): `bc6988c5`
- plan revision: 2
- revision count: 2 of 2 for this lineage (this is the last permitted revision)
- plan file: `.trellis/tasks/08-11-foundry-complete-v1/research/plan-goal-field-name-contract.md`

## Scope classification

**Local.** The external meaning of `public_goal_fields` (a tuple of integer
semantic indexes) is unchanged; only the compile-time *name form* the model may
emit, the deterministic source-preference tie-break, and the correction text
change. Every downstream consumer (modeling_gate, runtime materializer/evaluator,
Judge, idempotency equality) consumes the resolved integer `binding.index`,
never the name string. No producer/consumer schema, semantic meaning, ownership,
evidence, or lifecycle changes.

## Trigger

e2e resume terminal `task_requirement_invalid` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆), design graph node
`task_requirement`, shard `track_reservation_status` (task_family_index 4),
recorded as diagnosis 13.

## Diagnosis evidence (verified against code)

The diagnosis's root cause is re-confirmed: `_name_to_index` (design.py:407-412)
builds bare-only last-wins `{binding.name: binding.index}`; prompt design.py:2599
mandates qualified `tool.field` for shared names; qualified names are rejected
at 2462-2468. `_section_lookup` (2482-2497) already implements
qualified-always + bare-only-if-unique — the goal section lacks the equivalent.
All locators match the current source.

## Affected trust boundary

Designer compiler/validator lane only: `agent_world/design.py _direct_tasks.compile`
(goal_lookup + public_goal_fields resolution at 2452-2477) and its CorrectionPacket
emission. The Direct LLM keeps receiving only the authorized CorrectionPacket; the
runtime Agent boundary, Judge, Registry, and Observe are untouched.

## Repeated product target

Turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded
executable environment, independently verify it in a real isolated boundary,
publish an immutable Registry EnvironmentPackage, and expose only safe facts
through Observe. This plan advances only the Design -> WorldSpec -> Task/Verifier
segment (prompt/validator contract coherence); it does not by itself complete the
target. The PAC correctly holds the Registry receipt open.

## Impact chain (traced both directions)

Producer: `_catalog` (816-835) -> SemanticBinding tuple. Changed handoff:
compile-time name->index resolution for `public_goal_fields`. Immediate consumer:
`TaskRequirement.public_goal_fields` (resolved integer tuple). Later consumers:
`_modeling_gate` public schema `(/goal/{index}, categories[index-1])` (2697);
ExecutableTaskContract construction (2713-2728); runtime `_validate_materialization`
evaluator/path equality (348-356); Judge reachability via the same paths. Upstream
assumption: rendered prompt (2594-2604) and catalog projection (2570-2574) already
provide the qualified form the validator must accept.

## Owners

- goal-name resolution / qualified lookups: framework compiler/validator
  (design.py). The resolution result is an integer index consumed by deterministic
  framework code; no model can falsely claim downstream completion. The only
  model-facing change is the correction text (Change 2).
- Correction text content: framework, bounded by CorrectionPacket's hard 280-char
  limit and non-empty constraints (contracts.py:166-173).

## Compatibility facts (verified)

- Downstream consumers are index/category based, NOT name based. Once resolved to
  `fields` (integer tuple), nothing downstream reads the emitted string; bare ->
  qualified acceptance changes no consumer semantics.
- `_section_lookup` (2482-2497) already implements qualified-always +
  bare-only-if-unique; Change 1 mirrors existing sibling behavior, not a novel
  semantic.
- Category alignment: both `_catalog` (816-835) and `_catalog_categories`
  (838-850) emit the argument column from argument_fields and the other four
  columns (tool_result/pre_state/post_state/reset_state) from result_fields in the
  SAME order, so `categories[index-1]` aligns 1:1 with each binding index by
  construction. The plan no longer assumes category invariance across sources; it
  declares tier-determined category and records the frozen-architecture fact.

## Feedback item verification (revision 1 -> 2)

1. **Correction-text budget (was under-specified) — RESOLVED.** Change 2 now bounds
   by CHARACTER BUDGET (whole `violated_condition` <= 280 chars and non-empty,
   per contracts.py:166-173), with a construction invariant (lead with rejected
   name, then fill with shortest valid names until the budget is exhausted; never
   emit empty), plus a worst-case synthetic-family unit test asserting <= 280 chars
   and the invariants. `_object` offender enrichment (extra/missing keys, each
   list capped at 3 keys + overflow suffix, truncated to the same budget) is
   implementable.
2. **Category determinism (was unproved) — RESOLVED.** The plan no longer claims
   source-independence; it declares the resolved leaf category IS the chosen tier's
   projected category (`tier -> index -> categories[index-1]`), matches the
   `_catalog`/`_catalog_categories` column order, and records a verified frozen
   regression fact: the only name shared across argument/result kinds is
   `reservation_id` with category `identifier` on both sides (checked against
   design.world_architecture:42ac5bd4a54e7328), so no goal leaf category shifts for
   this run. Unit tests encode the per-tier category mapping.
3. **reset_state cast (was omitted) — RESOLVED.** Change 1 now explicitly states
   `SemanticBinding.source` is typed `Literal["argument","tool_result","pre_state","post_state"]`
   (contracts.py:540), that reset_state enters only via `cast(Any, ...)` at
   design.py:824/830, and that the helper consumes the cast-bypassed rows explicitly
   ranked LAST in the tie-break.

Also re-checked and confirmed correct: qualified-name lookup mirrors
`_section_lookup` (2482-2497); NO prompt bump; pure `--resume` re-runs only the
headless shard because `semantic_revision` (graph.py:592-611) hashes prompt_id +
projection digests etc. (unchanged) and `should_skip` (155-193) reuses the 4
committed sibling heads.

## Unproved consumers

- The re-rolled `track_reservation_status` shard compiling on attempt 1 and the
  design graph completing (requires the mandated real proof).
- All downstream boundaries (modeling_gate closure, candidate build, integration,
  Judge gates, Registry release) — correctly held open.
- The frozen-architecture category fact is asserted for this run only; other
  architectures are covered by the tier-determined construction rule, not by a
  blanket invariance claim.

## Smallest allowed implementation and proof plan

Implementation (agent_world/design.py only):
1. Add `_goal_name_lookup(architecture)` mirroring `_section_lookup` qualified
   construction with the fixed preference post_state > tool_result > argument >
   pre_state > reset_state, bare names accepted only when globally unique.
2. Change 2 correction content (unknown/ambiguous field valid-name set; `_object`
   extra/missing keys), both bounded to <= 280 chars non-empty.

Proof plan (mandated, real boundary): `uv run agent-world generate --config
config/agent-world.example.toml --need "用户预订宾馆" --resume
run_386e4f07c70d4f61be9cafbf82edcc55` — observe (a) exactly one shard re-runs and
passes on attempt 1, (b) design graph completes, (c) next terminal is a fresh honest
node failure or Registry release; stop and re-attribute at the first new terminal.

## Deterministic checks

- Unit: `_goal_name_lookup` qualified resolution, source-preference ordering
  (including cast-bypassed reset_state ranked last), per-tier category mapping,
  bare-unique acceptance, bare-ambiguous rejection, correction valid-name list
  invariants (<= 280 chars, non-empty, contains rejected name), `_object`
  extra/missing-keys text <= 280 chars; existing 285-test suite stays green.

## True-boundary proof

The real `--resume` run above: it exercises the actual prompt -> Direct LLM ->
validator -> correction loop against frozen inputs and observes the shard pass on
attempt 1 (the failure mode was oscillation). A unit test of `_goal_name_lookup`
alone does NOT satisfy this.

## Explicit non-claims

- Does not claim design-graph completion, downstream gates, or Registry release.
- Does not change prompt text, prompt_identity, topology, local_corrections,
  runtime, or tool_semantics.
- Does not resolve the separate open builder-side findings
  (candidate_idempotency_failed, materializer_public_goal_invalid,
  local_tool_semantics_mismatch).

## Next permitted gate

Dispatch implementation (agent_world/design.py only, exactly as planned); then
agent-world-real-execution-proof on the true boundary; then Observe; then append a
fresh Product Alignment Checkpoint at the design node-family exit. The main planner
must add this matching allow record to both implement.jsonl and check.jsonl before
dispatching implement/check.

## Review questions (summary)

1. Advances Design -> WorldSpec -> Task/Verifier contract coherence, an enabling
   segment of the Direct path.
2. Producer `_catalog` binding tuple and validator resolution change; all
   downstream consumers (index/category-based) proven unchanged compatibility.
3. New output (integer index tuples) is identical in meaning to today; correction
   text is now actionable and bounded.
4. Single framework owner (design.py compiler/validator + CorrectionPacket text); a
   model cannot falsely claim downstream completion because resolution is
   deterministic framework code.
5. Request/revision/dependency/evidence/secrecy/authority preserved; no prompt or
   identity bump.
6. Scope is honest and local; future Repair/Expand/Consumer handoffs preserved
   without being implemented.
7. Deterministic regression checks and true-boundary proof specified above; the
   Registry receipt remains the explicit non-claim.

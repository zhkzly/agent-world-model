# Cross-Layer Review — goal-field name contract (diagnosis 13)

Date: 2026-08-14 (session)
Reviewer: independent read-only cross-layer critic (delegated)

## Decision

**block** (revision 1 of at most 2 for this plan lineage)

The diagnosis is correct and the root-cause fix (Change 1) is sound in
direction, but the plan is not implementable as written and under-specifies
two downstream safety facts. See "Actionable plan feedback" for the exact
required changes.

## Plan digest

- sha256 of plan file content: `e9bbe3899eb3dcc048fa537ced303023ee2b193f8150eb016a745633d8ecfeb4`
- plan digest (first 8 hex): `e9bbe389`
- plan revision: 1 (no prior revision of plan-goal-field-name-contract.md exists)
- plan file: `.trellis/tasks/08-11-foundry-complete-v1/research/plan-goal-field-name-contract.md`

## Scope classification

**Local.** The external meaning of `public_goal_fields` does not change: it
remains a tuple of integer semantic indexes; only the compile-time *name form*
the model may emit and the *rejection text* change. Every downstream consumer
(modeling_gate, runtime materializer/evaluator, Judge, idempotency equality)
consumes the resolved integer `binding.index`, never the name string. No
producer/consumer schema, semantic meaning, ownership, evidence, or lifecycle
changes. The reviewer verified this directly (see "Compatibility facts").

## Repeated product target

Turn an arbitrary natural-language EnvironmentRequest into an
evidence-grounded executable environment, independently verify it in a real
isolated boundary, publish an immutable Registry EnvironmentPackage, and
expose only safe facts through Observe. This plan advances only the
Design -> WorldSpec -> Task/Verifier segment: it restores prompt/validator
contract coherence so the task_requirement node family can compile a shared
goal field it had no valid representation for. It does NOT by itself complete
the target; the Registry receipt remains the only release verdict (correctly
held open by the PAC).

## Trigger

e2e resume terminal `task_requirement_invalid` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆), design graph node
`task_requirement`, shard `track_reservation_status` (task_family_index 4).
Failing work finding `design.task_requirement.failure:841b88a4a85e5789`.

## Diagnosis evidence (verified against code)

All four review claims were checked against the actual source:

- (a) prompt mandates qualified, goal_lookup accepts bare only — **CONFIRMED**.
  Prompt at design.py:2599 mandates `tool_name.field` for shared names; the
  catalog projection `_binding_fields_for_llm` (728-747) emits the precise
  copyable name as `{tool, field}` rows; the validator `goal_lookup =
  _name_to_index(architecture.catalog.bindings)` at 2452, and
  `_name_to_index` (407-412) builds `{binding.name: binding.index}` = bare
  only, last-wins. Qualified names are rejected at 2462-2468.
- (b) _object omission of actual extra/missing keys — **CONFIRMED**. `_object`
  (170-180) reports only the expected key set, never the actual value's keys;
  its sibling `_array` (183-196) does report the actual count.
- (c) no prompt change -> only headless shard re-runs on pure --resume —
  **CONFIRMED**. `semantic_revision` (graph.py:592-611) hashes prompt_id +
  projection digests etc.; the prompt text and projection are unchanged, so the
  4 committed sibling heads keep matching digests and `should_skip`
  (155-193) reuses them while the headless failed shard re-runs.
- (d) source-preference order post_state > tool_result > argument > pre_state >
  reset_state — **PARTIALLY SUPPORTED, plan is imprecise and one literal is
  wrong**. `_catalog` (816-835) emits per tool the five sources in order
  argument, tool_result, pre_state, post_state, reset_state. The plan's claimed
  preference is a valid *choice*, but note `SemanticBinding.source` is typed
  `Literal["argument","tool_result","pre_state","post_state"]` (contracts.py:536-548);
  `reset_state` enters only via `cast(Any, ...)` at design.py:824/830. The
  plan must state this ordering explicitly as a deterministic tie-break over
  the cast-bypassed reset_state source, and must address the category-invariance
  claim separately (below).

## Affected trust boundary

Designer compiler/validator lane only: `agent_world/design.py _direct_tasks.compile`
(goal_lookup + public_goal_fields resolution at 2452-2477) and its
CorrectionPacket emission. The Direct LLM keeps receiving only the authorized
CorrectionPacket; the runtime Agent boundary, Judge, Registry, and Observe are
untouched.

## Impact chain (traced both directions)

Producer: `_catalog` (816) -> SemanticBinding tuple. Changed handoff:
compile-time name->index resolution for `public_goal_fields`. Immediate
consumer: `TaskRequirement.public_goal_fields` (resolved integer tuple).
Later consumers: `_modeling_gate` public schema `(/goal/{index},
categories[index-1])` (2697); ExecutableTaskContract construction (2713-2728);
runtime `_validate_materialization` evaluator/path equality (348-356); Judge
reachability via the same paths. Upstream assumption: the rendered prompt
(2594-2604) and the catalog projection (2570-2574) already provide the
qualified form the validator must accept.

## Owners

- goal-name resolution / qualified lookups: framework compiler/validator
  (design.py). No model can falsely claim downstream completion, because the
  resolution result is an integer index consumed by deterministic framework
  code; the only model-facing change is the correction text (Change 2).
- Correction text content: framework, bounded by CorrectionPacket's hard
  280-char limit and non-empty constraints (contracts.py:158-175).

## Compatibility facts (verified)

- Downstream consumers are index/category based, NOT name based. The name form
  exists only inside `compile`; once resolved to `fields` (integer tuple),
  nothing downstream reads the emitted string. Therefore bare->qualified
  acceptance changes no consumer semantics.
- `_section_lookup` (2482-2497) already implements qualified-always +
  bare-only-if-unique (collision -> -1 -> excluded). The plan's Change 1
  "bare-unique accept, bare-ambiguous reject" is an exact mirror of existing
  sibling behavior, not a novel semantic — good evidence the plan is local.
- Category invariance: `_catalog_categories` (838-850) flattens per tool
  argument_fields + result_fields x4 in the SAME order `_catalog` builds
  indexes, so `categories[index-1]` aligns 1:1. BUT the plan's claim
  "category is source-independent" is only true when a shared field name has an
  identical category in argument_fields vs result_fields. That is not a
  framework invariant here — argument and result FieldDeclaration categories
  can differ for the same name. The source-preference tie-break can therefore
  change which *category* a shared goal leaf resolves to (e.g. argument "status"
  category vs post_state "status" category). This must be made explicit and
  either proven identical for shared names or bounded.

## Unproved consumers

- The re-rolled shard compiling on attempt 1 and the design graph completing
  (requires the mandated real proof).
- Whether the source-preference tie-break changes a shared goal leaf's
  resolved category for any shared field name (a deterministic check is
  missing).
- All downstream boundaries (modeling_gate closure, candidate build,
  integration, Judge gates, Registry release) — correctly held open.

## Smallest allowed implementation and proof plan

Implementation (agent_world/design.py only):
1. Add `_goal_name_lookup(architecture)` mirroring `_section_lookup`
   qualified construction, using the stated deterministic source preference,
   with bare names accepted only when globally unique.
2. Make the unknown/ambiguous-field correction text list valid names bounded
   within the 280-char CorrectionPacket limit (see feedback — the 24-entry cap
   as written overflows).
3. `_object` offender enrichment bounded to the same correction limit.

Proof plan (mandated, real boundary): `uv run agent-world generate --config
config/agent-world.example.toml --need "用户预订宾馆" --resume
run_386e4f07c70d4f61be9cafbf82edcc55`, observing (a) exactly one shard
re-runs and passes on attempt 1, (b) design graph completes, (c) next terminal
is a fresh honest node failure or Registry release; stop and re-attribute at
the first new terminal.

## Deterministic checks

- Unit: `_goal_name_lookup` qualified resolution, source-preference ordering,
  bare-unique acceptance, bare-ambiguous rejection, correction valid-name list
  (and its 280-char bound), `_object` extra/missing-keys text; the existing
  285-test suite stays green.
- NEW (required): a determininstic check that for every shared field name
  across the frozen architecture, the source-preference tie-break resolves to a
  category identical to what `_catalog_categories` would assign at the chosen
  index — or an explicit bounded statement of the alternative.

## True-boundary proof

The real `--resume` run above is the true boundary: it exercises the actual
prompt -> Direct LLM -> validator -> correction loop against frozen inputs and
observes the shard pass on attempt 1 (the failure mode was oscillation). It is
NOT satisfied by a unit test of `_goal_name_lookup` alone.

## Explicit non-claims

- Does not claim design-graph completion, downstream gates, or Registry
  release.
- Does not change prompt text, prompt_identity, topology, local_corrections,
  runtime, or tool_semantics.
- Does not resolve the separate open builder-side findings
  (candidate_idempotency_failed, materializer_public_goal_invalid,
  local_tool_semantics_mismatch).

## Next permitted gate

After (and only after) this plan is revised to address the feedback below and
re-submitted (revision 2) and allowed, dispatch implementation; then
agent-world-real-execution-proof on the true boundary; then Observe; then append
a fresh Product Alignment Checkpoint at the design node-family exit.

## Actionable plan feedback (verbatim, for the plan writer)

1. Failed criterion: Change 2 (actionable correction content) is not
   implementable as specified. `CorrectionPacket.violated_condition` has a
   hard 280-character limit (`correction_packet_invalid` in
   contracts.py:158-175), and the full `_direct_feedback` sentence wraps the
   condition. A "capped at 24 qualified names" list plus surrounding text
   exceeds 280 chars (24 `tool_i.status` entries alone are ~385 chars),
   producing `correction_packet_invalid` instead of an actionable packet.
   Affected chain: DesignError -> CorrectionPacket -> _direct_feedback -> Direct
   LLM. Smallest change: bound the valid-name list by character budget (not only
   entry count) sufficient to stay under 280 chars total including the sentence
   prefix, and state the resulting guarantee (e.g. always include the rejected
   name, then fill with shortest names until the budget is reached). Add a unit
   test asserting every emitted condition for this node is <= 280 chars and
   non-empty.

2. Missing fact: the plan asserts "category is source-independent" but does not
   prove it. `_catalog_categories` (838-850) takes `field.category` from
   argument_fields for the argument column and result_fields for the other four;
   for a shared field name the argument category can differ from the result
   category. Because the source-preference tie-break selects which source's
   binding (and thus which index, hence which category) a shared goal leaf
   resolves to, the preference can change the leaf's resolved category vs.
   today's bare last-wins behavior. Smallest change: add an explicit statement
   and a deterministic check — either prove shared-name categories are identical
   across argument/result, or declare the chosen category for each preference
   tier and encode it in a test.

3. Contradictory/omitted fact: the plan's source-preference list includes
   `reset_state`, but `SemanticBinding.source` is declared
   `Literal["argument","tool_result","pre_state","post_state"]` (contracts.py:540);
   reset_state enters only through `cast(Any, ...)` at design.py:824/830. State
   that the preference ranks the cast-bypassed reset_state source and that
   `_goal_name_lookup` must handle it explicitly (not rely on the Literal).

Nothing above requires a scope change; the plan remains local once revised.
Forbidden shortcut: do not resolve the correction-text overflow by silently
truncating into an invalid packet or by weakening the resolution to keep last-
wins — the point of the repair is deterministic qualified resolution.

## Authorisation note

This review is read-only. It did not modify any project file; the only file
created is this review record.

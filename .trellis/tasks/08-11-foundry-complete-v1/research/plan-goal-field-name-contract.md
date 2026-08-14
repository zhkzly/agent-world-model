# Repair Plan (revision 2): goal-field name contract alignment (diagnosis 13)

Plan lineage: diagnosis-13-goal-field-name-contract.md.
Revision 1 digest e9bbe389 was blocked by the cross-layer critic
(cross-layer-review-goal-field-name-contract.md). Revision 2 addresses all
three feedback items; the scope remains local.

Scope: agent_world/design.py only. No prompt text change, no prompt_identity
bump, no graph/topology change, no local_corrections change, no runtime/
tool_semantics change.

## Change 1 — qualified-aware goal lookup (root cause)

In `_direct_tasks.compile` (design.py ~2452) replace

    goal_lookup = _name_to_index(architecture.catalog.bindings)

with a new module-level helper `_goal_name_lookup(architecture)` mirroring
the existing `_section_lookup` convention:

- Qualified names: for every binding in `_catalog(architecture)` (design.py
  816-835) — which includes the five columns argument, tool_result, pre_state,
  post_state, AND reset_state (note: `SemanticBinding.source` is typed
  `Literal["argument","tool_result","pre_state","post_state"]` in
  contracts.py; reset_state enters only via `cast(Any, ...)` at design.py
  824/830 — the helper consumes the cast-bypassed rows explicitly, ranked
  LAST) — key `f"{tool_name}.{field}`" where tool_name comes from
  architecture.tools (tool_index -> name).
- Deterministic tie-break when several sources share one qualified name,
  fixed preference order: post_state > tool_result > argument > pre_state >
  reset_state. Rationale: a public goal field is the achieved/observable
  world state — post_state is what success rules evaluate, tool_result is
  what the Training Agent observes; reset_state/pre_state are internal
  mechanics and must not win the tie.
- Bare names: included only when the bare name belongs to exactly one binding
  across the whole catalog (unambiguous); ambiguous bare names are invalid
  and must be corrected to the qualified form. This removes the silent
  last-wins misresolution (bare "status" -> reset_state of tool 4) while
  keeping previously valid unambiguous bare names accepted.

### Category determinism — declared, not assumed (critic item 2)

The plan does NOT claim category invariance across sources. The declared
rule: the resolved goal leaf's category IS the chosen tier's projected
category — resolution is tier -> index -> `categories[index-1]`, where
`_catalog_categories` (838-850) assigns the argument column's category from
argument_fields and the other four columns' from result_fields. So the
category follows the tier deterministically by construction; the model-facing
`semantic_catalog.fields` rows already disclose each source's category, and
the correction message (Change 2) may name the resolved tier's category when
rejecting a name. Unit tests encode the per-tier category mapping; for the
frozen architecture of run_386e4f07c70d4f61be9cafbf82edcc55 the plan records
a verified regression fact: the only name shared across argument/result
kinds is `reservation_id` and its category is `identifier` on both sides
(checked against design.world_architecture:42ac5bd4a54e7328), so for this run
no goal leaf's category shifts relative to the frozen rows.

## Change 2 — actionable correction content (oscillation), within the
CorrectionPacket budget (critic item 1)

- Unknown/ambiguous public_goal_field: violated_condition names the rejected
  field and lists valid names, family-scoped (qualified names for the frozen
  family's tool_indexes plus the globally-unique bare names among them).
  Bounded by CHARACTER BUDGET, not entry count: the whole violated_condition
  must stay <= 280 chars and non-empty (CorrectionPacket hard limit,
  contracts.py:166-173). Construction invariant: lead with the rejected name,
  then fill with the shortest valid names until the budget is exhausted;
  never emit an empty list. A unit test asserts <= 280 chars and the
  invariants for a worst-case synthetic family (max tools/fields).
- `_object` helper (design.py:170-180): append the actual offenders —
  "rejected object had extra keys: [...]; missing keys: [...]" — each list
  capped at 3 keys with a "…(+n)" overflow suffix, and truncated so the
  complete violated_condition stays <= 280 chars (all `_object` callers
  route through CorrectionPacket). This only changes violation text and
  improves every correction loop that uses `_object`; `_array` already
  reports the actual count and stays as is.

## Explicitly not changed

- Prompt text: the prompt already mandates the qualified form and the input
  catalog already provides tool+field rows; re-rolling all 5 shards via a
  prompt_identity bump would re-introduce model nondeterminism for zero
  contract gain.
- The 4 sibling task_requirement heads stay reused on pure --resume (their
  semantic_revision is unchanged, graph.py:592-611 + should_skip 155-193);
  only the headless `track_reservation_status` shard re-runs.

## Verification

1. Unit tests (deterministic): _goal_name_lookup qualified resolution;
   source-preference ordering including the cast-bypassed reset_state ranked
   last; per-tier category mapping; bare-unique acceptance; bare-ambiguous
   rejection; correction valid-name list invariants (<= 280 chars, non-empty,
   contains rejected name); _object extra/missing-keys text <= 280 chars.
   Existing 285-test suite stays green.
2. Real boundary proof (mandated): pure `uv run agent-world generate
   --config config/agent-world.example.toml --need "用户预订宾馆" --resume
   run_386e4f07c70d4f61be9cafbf82edcc55` — observe (a) exactly the one
   failed shard re-runs and passes on attempt 1, (b) design graph completes,
   (c) next terminal is a fresh honest node failure or Registry release; stop
   at the first new terminal and re-attribute.

## Product Alignment Checkpoint

Written as pac-task-requirement-name-contract.md in the same research dir:
canonical goal restated, trust boundary = designer compiler/validator +
Direct LLM correction loop, evidence = diagnosis 13 locators, unproven =
downstream candidate/Judge gates and the Registry receipt.

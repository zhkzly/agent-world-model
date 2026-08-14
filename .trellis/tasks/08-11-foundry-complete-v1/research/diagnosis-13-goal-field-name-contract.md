# Diagnosis Record 13: goal_lookup rejects the qualified field names the prompt mandates

Date: 2026-08-14 (session)
Trigger: e2e resume terminal `task_requirement_invalid` on
run_386e4f07c70d4f61be9cafbf82edcc55 (need: 用户预订宾馆).

## Evidence (verified)

- Observe scene: terminal_code `task_requirement_invalid`, run status
  rejected, release not_published; failing work = design graph node
  `task_requirement`, shard `track_reservation_status` (task_family_index 4),
  finding_3f0d20331fbde6bf.
- Attempt chronology for the failing shard (artifacts dir, mtimes +8):
  - inv1 correction_requested — path "$", "object must contain exactly these
    fields and no others: failure_rules, initial_rules, public_goal_fields,
    success_rules, terminal_rules" (message does NOT name the actual extra
    keys).
  - inv2 correction_requested — path "$.public_goal_fields[0]", "field must
    name a declared field; unknown field 'get_reservation_status.status'".
  - inv3 failed — same extra-keys violation as inv1.
    -> design.task_requirement.failure:841b88a4a85e5789.
- Same shard at the previous invocation batch (02:55) passed only after the
  same correction class ('unknown field get_reservation_status.reservation_id')
  by switching to bare names that happen to exist.
- Frozen inputs: design.world_architecture:42ac5bd4a54e7328 declares tools
  1 preview_lodging / 2 search_rate_options / 3 submit_reservation /
  4 get_reservation_status; its catalog holds per-source binding rows for
  every tool/field. 'status' exists on tools 1/3/4; 'reservation_id' on 3/4.
- Prompt (agent_world/design.py:2594, 2599): public_goal_fields are "field
  NAME strings from input.semantic_catalog.fields"; "When several tools share
  a field name, write tool_name.field (e.g. submit_reservation.status)".
- Input projection semantic_catalog.fields (design.py:728-747
  _binding_fields_for_llm) exposes rows {source, tool, field, category} — the
  only precise copyable name is the qualified `tool.field`.
- Validator (design.py:2452): `goal_lookup = _name_to_index(
  architecture.catalog.bindings)`; _name_to_index (design.py:407-412) builds
  `{binding.name: binding.index}` — BARE names only, last binding wins on
  collision. Every qualified name is rejected as unknown.
- The sibling mechanism already exists: _section_lookup (design.py:2482-2497)
  builds qualified `tool.field` names for the rule sections; only the goal
  section lacks it.

## Root cause

Contract contradiction inside the compiler/validator sub-lane: the rendered
prompt mandates the qualified name form for shared field names, and the input
catalog presents tool+field rows, but goal_lookup only accepts bare names.
The Direct LLM has NO valid representation for a shared goal field; its only
escape is ambiguous bare names resolved last-wins (e.g. bare "status" resolves
to reset_state of tool 4), which is why family 4 goals previously contained
reset_state rows.

Contributing: the correction packet for the unknown field repeats only the
rejected name and offers no valid-name set; the _object extra-keys violation
(design.py:170-180) does not name the offending keys (its sibling _array does
report the actual count). The model oscillates across the 3 attempts.

## Five-lens status

1. Project Agent view — not implicated; scene/artifact locators navigable.
2. Effective Prompt/input — SUPPORTED as the norm source (prompt mandates
   qualified names; catalog provides tool+field rows). No deficiency.
3. Runtime Skill / Direct no-Skill — not implicated (Direct LLM node, no
   mounted skill in the node spec).
4. Code/execution boundary — SUPPORTED ROOT CAUSE. Compiler/validator
   sub-lane: design.py:2599 (prompt) contradicts design.py:2452 +
   407-412 (goal_lookup); _section_lookup already implements the convention
   goal_lookup lacks.
5. Feedback/observability — SUPPORTED CONTRIBUTING. Unknown-field correction
   has no valid-name set; _object violation omits actual extra/missing keys;
   recipient cannot act without searching → oscillation.

## Alternatives rejected

- Model-capability failure: the same model passes the sibling shards and
  passed this shard at 02:55 via the bare-name escape; failures concentrate
  exactly where shared names occur — the prompt's own trigger for qualified
  names.
- Tool-semantics category-gate edit as cause: 4/4 tool_semantics shards passed
  at 03:29-03:31 under the new prompt; frozen architecture bindings unchanged;
  only downstream re-roll resulted.
- Rewording the prompt to ban qualified names: cannot name shared goal fields
  precisely; contradicts the doc's goal-leaf binding requirement; would bump
  prompt_identity and re-roll all 5 shards.
- Raising local_corrections: masks the contradiction.

## Owner / boundary

Framework compiler/validator (design.py _direct_tasks.compile) + correction
feedback (DesignError text). The Direct LLM keeps receiving only the
authorized CorrectionPacket; the runtime Agent boundary is untouched.

## Smallest next proof

With the validator fixed and NO prompt change: re-run the exact
track_reservation_status shard through the real Direct LLM (pure `--resume`
re-runs only the headless failed shard; the 4 sibling heads are reused) and
require first-attempt compile acceptance; then observe the design graph
completing and the downstream deterministic cascade (modeling_gate) passing.

## What remains unknown

- Whether the re-rolled shard's new goal indexes keep every downstream
  candidate node contract valid (modeling_gate, integration, Judge gates).
- Prior builder-side findings (idempotency, materializer) are downstream and
  untouched by this repair; they remain open evidence for later attribution.

# Diagnosis Record 6: divergent semantic index spaces (catalog 4-source vs code 5-source)

Date: 2026-08-14 (session)
Trigger: cross-layer-review-8436e69e block + direct catalog inspection.

## Evidence

- Frozen design (00cd3bdf) architecture.catalog.bindings has 47 rows = the
  4-source layout (argument/tool_result/pre_state/post_state). Example:
  index 19 = search_room_offers argument request_id; 24 = post_state offers;
  25 = post_state result_status.
- Current code has the 5-source layout (reset_state appended):
  design._catalog and runtime._task_bindings produce 60 rows for the same
  four tools. Runtime resolution of index 24 = tool2 argument request_id.
- The modeling gate at 01:49 used the 5-source _catalog_categories against
  the 4-source frozen indexes, so goal-schema categories are desynced:
  family 2 /goal/24 (binding offers) carries category "identifier".
- Consequence: judge's _task_outcome resolves frozen task-rule indexes with
  the 5-source _task_bindings — every index beyond tool 1 points at the
  wrong binding. The reset-view initial rules never had reset_state rows to
  compile against (the frozen catalog lacks them).

## Root cause

The architecture artifact (its SemanticCatalog) is compiled once per run;
world-architecture was skipped on resume (prompt id + inputs unchanged), so
the F4 catalog change (reset_state source) split the design-side frozen
catalog from the runtime-side rebuilt bindings.

## Fix direction

- Bump world-architecture prompt id (@1 -> @2) in graph.py: forces the
  architecture to regenerate with the 5-source catalog; all downstream
  design shards recompile against it (tool shards keep per-tool layouts and
  produce identical content; rules/tasks/curriculum recompile consistently),
  and the goal-schema categories re-derive from the matching 5-source
  _catalog_categories.
- Keep the goal-leaf mapping plan (8436e69e direction) ON TOP: with the
  catalog consistent, the mapping resolves correctly.

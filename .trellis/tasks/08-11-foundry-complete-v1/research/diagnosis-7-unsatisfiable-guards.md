# Diagnosis Record 7: unsatisfiable precondition guard sets

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, pure resume after the
index-space reconciliation. Terminal: rejected /
local_tool_semantics_mismatch, failed=precondition_guards, tool
preview_lodging, rationale "Google Maps is a supported preview channel when
supplied."

## Evidence

Regenerated preview_lodging preconditions:
  [0] when=[lodging_id exists, search_id exists]  (required inputs, fine)
  [1] when=[google_channel eq google_search]
  [2] when=[google_channel eq google_maps]
  [3] when=[google_channel eq youtube]
Guards are AND-ed (all must hold on the success trace), so [1..3] can never
hold together: the contract is unsatisfiable for any argument value. The
checker honestly rejects it. The model expressed an ALTERNATIVE (any of three
channels) as three separate guards — the language has no OR and the prompt
never said guards must be jointly satisfiable.

## Root cause

Design-language gap: no static gate rejects mutually exclusive precondition
sets, and the prompt never explains that alternatives belong in transitions.

## Fix direction (framework-owned)

- design.py modeling gate: static conflict check — two preconditions with eq
  predicates on the SAME semantic field but different constant values ->
  tool_semantics_invalid with an actionable violated_condition (guards must
  be jointly satisfiable; express alternatives in transitions).
- tool_semantics prompt: state that guards are AND-ed and must be jointly
  satisfiable; alternatives/variants belong in transitions (with the named
  anti-pattern: multiple eq guards on one field).
- Bump tool-semantics prompt id (@2 -> @3) to regenerate the shard.

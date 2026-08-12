# Minimal repair plan — disclose the existing WorldArchitecture field contract

- Plan lineage: `world-architecture-visible-field-contract`, revision 2/2
- Diagnosis: `diagnosis-world-architecture-visible-field-contract.md`
- Scope: one existing Direct `output_shape` literal and focused recipient-view
  regressions

## Exact change

1. In `agent_world/design.py::DesignExecutor._direct_architecture`, replace the
   terse shape with one compact symbolic `Field` definition and use it for
   entity fields `[1..24]`, tool arguments `[0..24]` and tool results
   `[1..24]`. Disclose the exact current rules: snake field name, closed
   category values, Boolean `required`, unique nonempty `values[1..16]`
   exactly for enum/list and empty otherwise, and `entity_ref` as snake name or
   null. State separately that entity-field references must name a declared
   entity; do not claim that existing tool-field references have that closure.
   Also disclose owner-local unique field names, unique one-based actor indexes
   bounded by the frozen actor count, and frozen citation indexes/kinds.
2. Close only the matching raw-exception holes inside the existing compiler:
   make `_field` reject nonempty `values` for non-enum/list through its existing
   path-addressed `DesignError`; use one local field-array compiler to preserve
   the existing collection bounds and reject duplicate entity/tool field names
   before dataclass construction; reject duplicate actor indexes in the
   existing actor-index check. Do not add a generic exception catch or schema
   layer. These checks turn already-invalid proposals into the existing
   `world_architecture_invalid` transaction and change no accepted artifact.
3. Preserve the input projection, correction packet, one-correction limit,
   model/routes/timeouts, NodeSpec, graph edges and all downstream artifacts.
   Because `output_shape` already participates in semantic identity, add no
   provenance mechanism.
4. In `tests/test_design_semantics.py`, inspect the actual captured
   `world_architecture` user JSON and prove the compact shape reaches all three
   field collections with the entity/tool reference distinction. Prove
   nonempty non-enum values, duplicate owner-local entity/tool fields and
   duplicate actor indexes produce path-addressed `DesignError` with
   `world_architecture_invalid`, never raw exceptions. Add one
   first-invalid/second-valid fake Direct sequence matching the observed empty
   finite-domain failure and prove the existing correction is actionable.

At most one local field-array function may replace the three current repeated
tuple comprehensions; it is not a public helper or schema layer. No new type,
module, node, Skill, config, retry, generic catch or compatibility path. Keep
production Python at or below 10,299 lines; prefer net deletion through the
local deduplication.

## Verification

- Focused and full pytest, Ruff format/check, full mypy, compileall, diff check
  and legacy firewall.
- Fresh independent check of rendered Prompt/input/output-shape compatibility
  and downstream non-change.
- Rerun one fresh real `world_architecture` node with the same need/evidence
  class on Luna, then inspect its WorkRecord and Observe scene.

Any different real terminal starts a new diagnosis; do not spend another turn
under this hypothesis. This plan does not claim Agent, Candidate, Integration,
Judge, Registry, Repair, Expand, Consumer or E2E behavior.

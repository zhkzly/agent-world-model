# Research: cross-layer review — WorldArchitecture visible Field contract

- Query: Is plan `9c95eb3f8cc49adf703f65547eae61aa3216ef7cd6b3d96c903e33928d3e144c` sufficient for the Luna Field failures, or must it also close a concrete typed compiler failure?
- Scope: internal
- Date: 2026-08-11

## Findings

**Decision: block**

- Plan digest: `9c95eb3f8cc49adf703f65547eae61aa3216ef7cd6b3d96c903e33928d3e144c` (verified).
- Plan revision: `world-architecture-visible-field-contract`, revision 1/2. Scope is a local Direct producer/compiler boundary, not a graph or downstream-ABI change.
- Trigger: real `run_5c648fca95e64bc08107b70a48127854` reached the Designer compiler twice. Its safe artifacts record the first missing finite-domain cardinality at `$.entities[0].fields[0].values`, the terminal duplicate-domain condition at `$.entities[1].fields[3].values`, two Luna operation records, and failed `world_architecture` work with no output. Finding `finding_a5b1003e8e5a8fc8` blocks release.

The product target remains natural-language need -> evidence-grounded executable environment -> independent isolated verification -> immutable Registry `EnvironmentPackage` -> safe Observe. This repair advances only the first Direct semantic proposal boundary.

The proposed compact `output_shape` is the smallest causal remedy for the two observed Luna failures, but it is not sufficient as written for all current Field uses:

1. `_field` delegates the non-enum/list empty-values invariant to `FieldDeclaration.__post_init__` (`agent_world/design.py:228-255`, `agent_world/contracts.py:522-528`). A proposal such as a `text` Field with nonempty `values` passes `_field`'s array/uniqueness checks then raises raw `ValueError("field_values_invalid")`. `GraphRunner.execute` catches only `NodeExecutionError` (`agent_world/graph.py:487-535`), so that violation bypasses the safe attempt/validation/failure-WorkRecord path. The plan must close this concrete typed compiler failure; output disclosure alone cannot make it safe.
2. The same raw-exception hole exists for the plan's explicitly promised owner-local uniqueness: duplicate entity fields are rejected only by `EntityDeclaration.__post_init__`, and duplicate tool field names or actor indexes only by `ToolSurface.__post_init__` (`agent_world/contracts.py:604-635`). These are reached after `_direct_architecture` has accepted the nested arrays (`agent_world/design.py:1003-1125`).
3. One shared symbolic `Field` must not overstate reference closure. Current compilation checks declared-entity closure only for entity fields (`agent_world/design.py:1036-1046`); tool argument/result `entity_ref` is currently constrained only to `null` or a valid snake-name by `_field`. Applying “declared entity name or null” globally would be a new semantic restriction, not disclosure of an existing rule.

Impact chain: Direct `output_shape` -> Luna proposal -> `_field` / existing constructors -> `GraphRunner` typed failure-or-commit -> `WorldArchitecture` Artifact -> unchanged WorldRules/Curriculum/Task/Modeling consumers. Designer owns the producer/compiler boundary. NodeSpec, edges, correction limit, persisted success Artifact shape, and later consumers remain compatible if the compiler additions only turn already-invalid proposals into the existing `world_architecture_invalid` safe terminal.

## Required plan revision

Keep the repair local and revise the plan before implementation to require:

1. One exact compact Field mini-schema in the existing literal for entity fields, `argument_fields`, and `result_fields`, including their actual collection bounds (`1..24`, `0..24`, `1..24`), snake field name, closed category set, Boolean `required`, finite-domain rules, and actor indexes that are unique one-based indexes within the frozen actor count. State entity-reference closure separately: declared entities for entity fields; `null` or a snake name for tool fields unless a separate plan changes that compiler rule.
2. In the existing architecture compiler, prevalidate or translate every Field/owner invariant above into path-addressed `DesignError`; in particular enforce empty `values` for non-enum/list before `FieldDeclaration`, and detect duplicate entity/tool field names plus duplicate actor indexes before their dataclass constructors. Do not add a generic schema layer or a broad exception catch.
3. Focused deterministic tests that capture the exact rendered `output_shape`, prove the same Field contract reaches all three collections, and prove nonempty non-enum values, duplicate owner-local fields, and duplicate actor indexes produce safe `world_architecture_invalid` diagnostics rather than raw exceptions. Retain the observed empty/duplicate finite-domain correction sequence as a separate actionable-correction regression.

Smallest true-boundary proof after an allowed revision: one fresh Luna `world_architecture` transaction with the same need/evidence class, then immediate Observe and WorkRecord inspection. No live provider was run in this review.

## Caveats / Not Found

- This block does not authorize retries, model/route changes, Skill/tool/workspace access, schema machinery, graph/edge changes, artifact migration, or any downstream implementation.
- It does not claim Research, later Design nodes, Modeling, Candidate, Integration, Judge, Registry, Repair, Expand, Consumer, or end-to-end completion.
- Next permitted gate: revise this plan only, addressing the typed compiler closure and the entity-versus-tool reference distinction; then submit revision 2/2 to a fresh independent critic.

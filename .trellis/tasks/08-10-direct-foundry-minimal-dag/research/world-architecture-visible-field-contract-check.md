# Independent implementation check — WorldArchitecture visible Field contract

## Decision

`block`

The revision-2 plan digest matches the current allow:
`322bfa3a31ed44a281045469aff9daa9a1a4df6fe27ba6afaa388b32b0642eec`.

## Concrete blocker

- **The required regression for non-enum/non-list `values` is missing.**
  `agent_world/design.py` now correctly rejects nonempty `values` for a
  non-`enum`/`list` field with a path-addressed
  `DesignError("world_architecture_invalid")`. The focused test file covers
  duplicate entity/tool field names, duplicate actor indexes, and the observed
  empty finite-domain correction, but has no test that sends a nonempty
  `values` array for (for example) an `identifier` or `text` field through the
  Direct WorldArchitecture transaction. This is an explicit revision-2
  acceptance requirement: prove the precheck reaches the existing correction
  and failed-WorkRecord path rather than a raw exception.

  Required scoped follow-up: add that one focused regression in
  `tests/test_design_semantics.py`, asserting the exact `.values` correction
  path, `world_architecture_invalid`, and persisted failed WorkRecord after the
  existing one correction. No product-contract change is needed.

## Checked

- The rendered field contract is compact and covers entity fields `[1..24]`,
  tool arguments `[0..24]`, and results `[1..24]`; it preserves the entity
  declared-reference versus tool snake-or-null distinction.
- The compiler includes the allowed non-enum-values, owner-local duplicate
  field, and duplicate actor-index prechecks before dataclass construction.
- The changed `output_shape` remains part of Direct semantic material; the
  WorldArchitecture NodeSpec, edges, route, correction budget, and downstream
  artifact contract are unchanged. No overdesign was found in the scoped path.
- Focused offline verification passed:
  `uv run --no-sync pytest -p no:cacheprovider tests/test_design_semantics.py -k 'world_architecture'`
  — 6 passed.
- An additional offline direct compiler probe confirmed that nonempty values on
  an `identifier` argument field raise `world_architecture_invalid` at the
  exact `.values` path; it does not replace the missing committed regression.

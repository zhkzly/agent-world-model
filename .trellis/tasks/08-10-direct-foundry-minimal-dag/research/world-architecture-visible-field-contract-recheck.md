# Independent scoped re-check — WorldArchitecture visible Field contract

## Decision

`allow`

The revision-2 allow remains the matching authority:
`322bfa3a31ed44a281045469aff9daa9a1a4df6fe27ba6afaa388b32b0642eec`.

## Scope checked

The sole blocker in
`research/world-architecture-visible-field-contract-check.md` is closed by
`test_world_architecture_nonfinite_domain_values_are_typed_and_persisted` in
`tests/test_design_semantics.py`.

- It supplies nonempty `values` for an `identifier` field (a non-`enum`/`list`
  category).
- It asserts the single corrective packet has the exact path
  `$.entities[0].fields[0].values`, code `world_architecture_invalid`, the
  required violated condition, and category `array`.
- Its helper repeats the invalid proposal after that correction, exhausting the
  existing correction budget; the test asserts the raised
  `world_architecture_invalid` error and the persisted failed WorkRecord with
  the same safe code.

The actual compiler path is unchanged and raises the same typed `DesignError`
before `FieldDeclaration` construction. `GraphRunner.execute` catches that
typed node error, records the first correction request, and persists the failed
WorkRecord on the second invalid response. This is within the revision-2
recipient/compiler and existing correction-persistence scope; no product code,
provider invocation, or contract expansion was performed.

## Verification

- `uv run --no-sync pytest -p no:cacheprovider tests/test_design_semantics.py -k 'world_architecture'` — 7 passed
- `uv run --no-sync ruff format --check agent_world/design.py tests/test_design_semantics.py` — pass
- `uv run --no-sync ruff check agent_world/design.py tests/test_design_semantics.py` — pass
- `uv run --no-sync mypy agent_world/design.py` — pass

## Non-claims

This is a static regression re-check only. It does not claim a live Direct LLM
turn, downstream Design/Candidate work, integration, Judge, Registry release,
or product completion.

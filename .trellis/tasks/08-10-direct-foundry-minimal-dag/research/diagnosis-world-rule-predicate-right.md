# Static diagnosis — RuleDraft predicate right accepts non-object values

The final whole-diff report `direct-final-whole-diff-check.md` found a static
validator defect; no real run or Observe scene exists.

In `agent_world/design.py`, `_rules` currently accepts a predicate when
`not isinstance(right, dict)`, then later calls `dict(right)`. An empty list can
be committed as an empty object and a string can raise raw `ValueError` outside
the intended `DesignError -> GraphRunner failed WorkRecord` path. The closed
PredicateDraft contract requires exactly a literal object or semantic-ref
object.

The condition is simply inverted. The smallest repair removes `not` so only a
dict matching one of the two existing closed shapes passes. All invalid values
then use the existing exact-path `DesignError`; no schema, Prompt, node,
feedback system, retry or generic validator is needed.

This diagnosis is static and proves no live Direct/E2E behavior.

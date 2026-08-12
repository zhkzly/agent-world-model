# Direct final whole-diff check R3

## Decision

`allow`

## Bounded scope

This read-only recheck covers only the prior `WorldRules` predicate-right
shape blocker: `_compile_rules`, its focused regressions, the existing typed
correction/failure transaction, and the existing `world_rules` graph edges.
No optional architecture, Repair, Expand, Consumer, or new proof scope was
reviewed.

## Closure evidence

- `agent_world/design.py::_compile_rules` now establishes
  `isinstance(right, dict)` before every object-only operation.  It accepts
  only the unchanged closed literal shape (`kind` plus `value`) or bounded
  semantic-reference shape (`kind` plus `semantic_index`), and every other
  value takes the existing `DesignError("world_rules_invalid")` path.  Thus
  `dict(right)` is reached only after the value is known to be a dictionary.
- `DesignError` is a rejected, non-retryable `NodeExecutionError` with the
  typed `CorrectionPacket`.  `world_rules` remains a one-local-correction
  Direct LLM node.  On the second rejection, `GraphRunner.execute` calls its
  existing `fail` path, which persists the validation and route-free Finding
  and writes a failed `WorkRecord` with no outputs.
- The focused regression accepts both closed right shapes and rejects `{}`,
  an unknown-kind object, `None`, and a list as `DesignError`.  Its two-invalid-
  proposal case proves the exact typed correction, `world_rules_invalid`
  validation/Finding/safe code, route-free Finding, failed WorkRecord, and
  empty `output_refs`.
- `world_rules.rules` remains the required source for `curriculum_plan`,
  `task_requirement`, and `modeling_gate`.  Those edges require a passed
  `world_rules` envelope; the failed record has no output, so the rejected
  proposal cannot flow into those downstream inputs.

## Deterministic verification

```text
UV_CACHE_DIR=/tmp/foundry-direct-r3-uv-cache PYTHONDONTWRITEBYTECODE=1 \
uv run --no-sync pytest -p no:cacheprovider tests/test_design_semantics.py \
  -k 'world_rule_predicate_right or world_rules_two_invalid_proposals_persist_failure_without_output'

2 passed, 5 deselected
```

## Product alignment and authorization

The check establishes only honest rejection before a malformed Direct
WorldRules artifact can reach the downstream Design/Builder/Judge/Registry
chain; it does not establish an executable, independently verified, published
`EnvironmentPackage`.

Because this sole blocker is closed, the already-defined ordered live proofs
are authorized to proceed in their existing order.  No live proof was run or
claimed by this check.


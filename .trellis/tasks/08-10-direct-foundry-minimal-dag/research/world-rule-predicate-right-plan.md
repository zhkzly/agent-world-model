# Minimal plan — close RuleDraft predicate right

- Plan lineage: `world-rule-predicate-right`, revision 2/2
- Diagnosis: `diagnosis-world-rule-predicate-right.md`
- Scope: one existing Design validator condition and focused regression

## Exact change

1. In `agent_world/design.py::_compile_rules`, replace the inverted branch with
   one local `valid_right` boolean: `right` must be a dict and must match either
   the exact existing literal shape or the exact existing semantic-ref shape.
   Only `valid_right` passes; every other value enters the one existing
   exact-path DesignError block. Never call `set`, `.get`, indexing or `dict`
   conversion on a non-dict.
2. Keep the two existing accepted meanings, exact DesignError path/condition,
   local correction limit, Prompt/output contract, GraphRunner and
   PredicateDraft unchanged. Do not add a helper or another validator layer.
3. In `tests/test_design_semantics.py`, prove both exact allowed shapes still
   compile; malformed dicts such as `{}`/unknown kind and representative
   non-objects including `None` and `["kind", "value"]` produce DesignError,
   never raw ValueError/TypeError/AttributeError. Through the existing Direct
   WorldRules transaction, two invalid proposals consume the one local
   correction then persist validation, route-free Finding and failed WorkRecord
   with safe code `world_rules_invalid`, with no WorldRules output.

No production LOC increase, new type/helper/node/schema/config/retry or other
validator refactor; prefer a net deletion. Run focused and full pytest, Ruff, mypy, compileall, diff
and firewall, then repeat independent whole-diff before any live proof.

This plan does not claim or implement live Direct, Repair, Expand, Consumer or
training behavior.

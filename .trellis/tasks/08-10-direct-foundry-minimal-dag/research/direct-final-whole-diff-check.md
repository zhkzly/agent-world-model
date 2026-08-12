# Direct final whole-diff check

## Decision

`block`

The Direct release has one concrete release-blocking producer/validator failure.

## Findings (fixed)

- None. No production, test, plan, or spec file was changed; the only write was this mandated review record.

## Findings (not fixed)

- **WorldRules accepts a non-closed predicate right-hand side and can bypass the safe node-failure path.** In `agent_world/design.py:345-351`, the condition begins with `not isinstance(right, dict)`, so every non-object `right` is accepted instead of being rejected as a closed `{kind, ...}` object. At `agent_world/design.py:378`, `dict(right)` then accepts inputs such as `[]` as `{}`, allowing an invalid predicate to be committed into the compiled rule; a scalar such as a string instead raises raw `ValueError`. `PredicateDraft` has no subsequent shape validator (`agent_world/contracts.py:488-494`). `GraphRunner.execute` persists rejected work only for `NodeExecutionError` (`agent_world/graph.py:491-496`), so the raw `ValueError` route can escape without the required Validation/Finding/failed WorkRecord terminal.

  This is a Direct LLM output-contract and validation-boundary failure that can contaminate the downstream Builder/Judge/Registry chain, not a mechanical formatting repair. It must be addressed by a revised, bounded validation plan and a fresh matching critic allow before release; it was intentionally not self-fixed.

## Verification

- Targeted code-path confirmation: complete for the finding above.
- Fresh pytest, Ruff, mypy, compileall, diff, and firewall reruns: not performed in this finalization after the explicit instruction to stop expanding the scan. This `block` does not rely on historical green results.
- Live API/E2E: not run.

## Nonclaims

- This report makes no claim that the physical package-reference equality/ZIP failure path is broken, and it does not add a second finding about it.
- It does not treat unimplemented Repair, Expand, or Consumer work as a Direct block.
- It does not propose a generic framework, future child work, or any live/non-target execution.
- It does not claim a full green release gate while the blocking validation path remains open.

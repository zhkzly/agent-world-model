# T1 / BC-14 minimum report — Rule diagnostic causal fidelity

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Classification and owner

- Classification from the plan's bad-case table: **diagnostic / input
  representation loss**. The prohibited failure is a Rule compiler error
  collapsing into `framework_diagnostic_incomplete` or losing its causal path
  and repair facts.
- Owners: frozen ToolSemantics binding materialization,
  `EnvironmentDesigner._compile_rule_sequence`, canonical Rule source
  validation, and the safe diagnostic projection boundary.
- No prompt/skill change is indicated: the defect class is structural
  diagnostics, not an under-specified Engineer instruction.

## Deterministic regression evidence

- Extended
  `test_compact_tool_rule_protocol_parses_and_compiles_only_frozen_bindings`.
  It starts with a fully frozen, valid ToolSemantics binding document, then
  introduces only a canonical Rule arithmetic division-by-zero condition.
- The diagnostic preserves the exact causal location:
  `tools.0.state_transition.transition.0.clauses.0.right.right`, with stable
  code `rule_arithmetic_zero_divisor`, `retryable=true`, a safe violated
  condition, and a safe expected category.
- The input passes the compact protocol schema, so this proves the canonical
  executable Rule compiler rather than a superficial provider-schema failure.
  The result is explicitly not `framework_diagnostic_incomplete`.
- Existing companion tests cover non-absolute pointer diagnostics through a
  Rule clause/left term and retain their retryability/condition/expectation.

## Verification and boundary

- Relevant deterministic modules passed: batched transactions `27`, designer
  structured rework `42`, Scheduler structured one-shot `16`.
- Target-file Ruff and format checks passed; `git diff --check` passed.
- No real model request was made. This unit tests code-owned diagnostic
  fidelity, so a fresh model request would add cost without discriminating the
  claimed boundary. No Registry path, release evidence, credential/base-URL
  value, raw prompt, transcript, or sealed case was produced.
- BC-14 is green as a deterministic regression. This does not claim that a
  semantic node has produced a legal commit; the T1 live-commit acceptance
  remains blocked behind BC-17 and BC-47.

## Next boundary

The next ordered unit is BC-17: classify the observed bounded-progress / batch
size behavior, keep Scheduler retry limits unchanged, and examine physical
batch sizing plus frozen context before any role-specific skill change.

# Diagnosis — Observe rejects the new Judge evidence

## Expected

After R2, a released package whose Judge report contains the required
`local_tool_semantics` gate should survive Registry cold-read and Observe's
independent release recheck.

## Observed

The full deterministic suite reports `101 passed, 2 failed`. Both failures are
otherwise-valid releases downgraded by Observe to `not_published`. Focused R2
tests, Ruff, mypy, compileall and diff checking pass.

## Attribution

Judge now safely persists `local_rule_assurance` only for the
`local_tool_semantics` gate. Registry already requires and rechecks that exact
field. `observe.py` still compares every gate's evidence to the pre-R2 fixed
four-field object, so the additional required field can never pass Observe.

This is a downstream consumer drift introduced by the R2 implementation. It is
not a Luna instruction-following failure, a Skill-loading failure, a candidate
ABI failure, or evidence that the Judge gate should be weakened.

## Repair boundary

Observe must expect the exact Design-owned assurance value for that one gate
and preserve the existing exact shape for every other gate. Missing, altered,
extra or misplaced assurance must still fail closed. No new schema, helper
framework, compatibility path, retry or model call is required.

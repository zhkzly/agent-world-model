# Minimal R2 addendum — close Observe gate evidence

## Change

Extend the already-allowed R2 consumer closure by one existing product file and
one existing focused test file:

- in `agent_world/observe.py`, keep the exact expected Judge evidence object;
  conditionally add `local_rule_assurance` only when
  `gate_id == "local_tool_semantics"`, using the exact value already read from
  the immutable Design artifact;
- use exact object equality as today, so a missing, altered, extra or misplaced
  field still yields `not_published`;
- use the existing release fixture in `tests/test_artifacts_observe.py` to prove
  a valid R2 release is visible;
- add one compact parameterized Observe regression. After creating that valid
  fixture, intercept only the cold read of a `judge.gate_evidence` artifact and
  return one of four modified payloads: remove assurance from the local gate,
  alter one local assurance value, add assurance to a non-local gate, or add an
  unrelated extra field to the local gate. Every case must project exactly
  `{"status":"not_published"}`. This exercises Observe's content comparison
  directly rather than passing earlier because artifact bytes no longer match
  their digest.

## Non-goals

Do not add a schema registry, evidence polymorphism, compatibility branch,
normalizer, model retry, graph node, public Runtime field, Repair, Expand or
Consumer behavior. Do not weaken Judge, Registry or Observe checks.

## Acceptance

Run the valid-release test and the four direct evidence-negative cases, then
the full pytest, Ruff, mypy, compileall and diff checks. Existing package,
verifier and lineage tamper tests remain unchanged. The real proof order
remains the R2 order: Luna ToolSemantics shard,
Candidate/Integration/Judge, then fresh Direct E2E with terminal Observe.
Deterministic green is not an E2E claim.

# Research: cross-layer review — Observe gate evidence addendum

- Query: Independent read-only review of whether plan `9ee47ea96ac0568a538c6db04f854e08336c63450dc2203af1457c156abed63b` can close the R2 `Judge -> Registry -> Observe` evidence handoff without weakening release validation or expanding the Direct slice.
- Scope: internal
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`

## Decision

Decision: block

- Plan digest (independently recomputed): `9ee47ea96ac0568a538c6db04f854e08336c63450dc2203af1457c156abed63b`.
- Plan revision: `Minimal R2 addendum — close Observe gate evidence`.
- Revision count: 0 for the new `diagnosis-r2-observe-gate-evidence.md` repair lineage.
- Scope classification: coordinated, one-consumer release-evidence repair. The code change itself is local to Observe, but it consumes a Judge/Registry evidence contract and must prove exact compatibility rather than merely restore the happy path.
- Trigger: a persisted deterministic failure reports two otherwise valid R2 releases as `not_published`. The diagnosis attributes it to Observe retaining the pre-R2 universal four-field gate-evidence expectation after Judge/Registry added Design-derived `local_rule_assurance` for exactly one required gate. No new real execution scene is claimed or required for this review.

## Product target and impact chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

```text
compiled immutable Design.local_rule_assurance
  -> independent Judge local_tool_semantics gate evidence
  -> Controller package / ReleaseDossier
  -> Registry cold verification and atomic receipt
  -> Observe cold re-read and safe released/not_published projection
```

This addendum advances only the last read-only projection. It must not make a Judge result, package, receipt, or run status sufficient by itself. The canonical source and execution map require Registry to publish only after independent hard evidence and require Observe to expose safe durable facts without judging, mutating, retrying, or publishing.

## Owner and consumer compatibility

- Designer/framework owns the compiled `LocalRuleAssurancePlan`; `agent_world/design.py:1760` persists it in the immutable Design artifact.
- Judge owns the gate evidence and emits `local_rule_assurance` only when `gate_id == "local_tool_semantics"` (`agent_world/candidate.py:1239-1257`).
- Registry remains the cold-read/release owner and already requires the same exact conditional object from the Design-owned assurance value (`agent_world/candidate.py:2492-2580`, especially `2560-2577`). It must remain unchanged.
- Observe is only the downstream read-only consumer. Its current loop still expects the four-field evidence object for every gate (`agent_world/observe.py:257-266`), so it rejects a Registry-valid R2 release.
- Repair, Expand, and Consumer retain their existing package/lineage seams. This change neither alters a package ABI nor gives any later path release authority.

The plan's proposed one-site conditional expected-object comparison is the smallest coherent implementation shape: derive the assurance only from the already re-read immutable Design artifact; add it only for the named gate; preserve exact object equality for all gates. It adds no schema registry, normalizer, compatibility route, runtime field, retry, model call, graph node, or second release authority.

## Blocking criterion and actionable plan revision

The proposed implementation constraint is sound, but the specified deterministic acceptance does not prove the changed fail-closed contract. The cited existing tamper checks alter package/verifier/lineage closure, not the four new evidence cases: missing assurance, altered assurance, extra assurance, or assurance attached to a non-`local_tool_semantics` gate. Therefore a future implementation could make valid R2 releases visible while accidentally accepting a misplaced or widened evidence field, contradicting the plan's own safety claim.

Revise the plan only as follows:

1. In the already named `tests/test_artifacts_observe.py`, add a compact parameterized regression that begins with the existing valid R2 release fixture and mutates the persisted Judge gate-evidence artifact for each of: remove the assurance, alter one assurance value, add an extra assurance field to a non-local gate, and add an unrelated extra field to the local gate. Each mutation must make `observe_run(...)["release"]` exactly `{"status": "not_published"}`.
2. Keep the existing valid-fixture assertion, now explicitly proving that the exact Design-derived assurance on the sole local gate remains visible as `released`.
3. Keep the product edit limited to `agent_world/observe.py`; do not alter `agent_world/candidate.py`, Registry behavior, Judge output, package metadata, release policy, or any later child contract.

Forbidden shortcut: accepting a superset, normalizing evidence, defaulting absent assurance, or testing only Registry/package/lineage tampering as a proxy for Observe's gate-evidence consumer contract.

## Smallest tests and proof after revision

- Deterministic regression: the valid R2 release is `released`; the four direct gate-evidence mutations above are each `not_published`; retain the existing package, verifier, and lineage tamper downgrades. This proves Observe has the same conditional exact-equality rule as Registry without weakening its cold-read checks.
- Deterministic quality gate: the two previously failing Observe tests, then the declared full pytest, Ruff, mypy, compileall, and diff checks.
- True-boundary proof: unchanged R2 order only—Luna ToolSemantics shard, Candidate/Integration/Judge, then a fresh Direct E2E ending in Observe. This review ran no model or network action. A terminal failure still requires Observe -> diagnosis -> revised plan -> fresh critic before any repair.

## Non-claims

This decision does not claim implementation, a passing focused test, Registry publication, a live Direct E2E, dynamic assurance of error/reject behavior, Repair, Expand, Consumer/SFT/RL, or product completion. It also does not authorize a broader review or edit of the unrelated current worktree diff.

## Next permitted gate

Revise only `r2-observe-gate-evidence-plan.md` to add the direct evidence-tamper regression matrix above, preserve the exact one-site Observe implementation boundary, and submit its new digest for a fresh independent cross-layer review. No implementation is permitted under this decision.

## Caveats / Not Found

- The diagnosis says the full deterministic suite has two Observe failures. This review inspected the persisted diagnosis and current code/tests but deliberately did not rerun the suite or any real proof.
- The task context's prior R2 allow (`cross-layer-review-c69de83b-tool-semantics-r2.md`) covered the upstream Design/Judge/package/Registry closure; this new downstream consumer drift is a distinct repair lineage.

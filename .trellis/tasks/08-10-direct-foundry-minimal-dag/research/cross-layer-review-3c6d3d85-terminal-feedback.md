# Research: cross-layer review — terminal feedback

- Query: Independently review `diagnosis-direct-proof-4-terminal-feedback.md` and `direct-terminal-feedback-plan.md` for safe exhausted-local-correction evidence persistence.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: block

- Plan digest: `3c6d3d85dbaf4fd54f3741b007cfa9294814b19c7a8c23d0ba8cdb72f649ef47`, independently recomputed as the raw-byte SHA-256 of `direct-terminal-feedback-plan.md`.
- Plan revision and count: initial terminal-feedback repair plan for Diagnosis Record `diagnosis-direct-proof-4-terminal-feedback.md`; this is revision 0 of this diagnosis/plan lineage, so up to two plan revisions remain.
- Scope classification: local, coordinated inside the existing `GraphRunner.execute` terminal transaction and its existing failure Artifact/WorkRecord/Finding evidence closure. No graph topology, public ABI, Repair behavior, or later-child implementation is needed.
- Trigger: PAC-32's real Spark/Luna terminal evidence gap. The diagnosis correctly records that both frozen-contract runs used one correction and then failed without release; it does not claim an E2E success.

## Product Target and Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This repair advances only honest failed-node attribution. Its impact chain is:

```text
framework compiler / DesignError
  -> existing safe CorrectionPacket on terminal NodeExecutionError
  -> GraphRunner terminal failure Artifact
  -> failed WorkRecord.assurance_refs + route-free Finding.evidence_refs
  -> future Repair provenance re-verification / current safe Observe evidence IDs
```

`GraphRunner` remains the sole owner of local-correction eligibility and physical invocation count (`agent_world/graph.py:465-508,635-643`). `DesignError` remains a framework producer of the closed four-field packet (`agent_world/design.py:58-84`). The model, Agent, failure Artifact, Finding, Observe, and future Repair receive no retry, route, budget, invalidation, target, Judge, or release authority.

## Findings

### Semantics and compatibility

The requested value choice is semantically honest if and only if it is exactly:

```python
failure_evidence = exc.evidence if exc.evidence is not None else exc.correction
```

at the already-terminal branch. It preserves explicit supplied evidence, and when none was supplied, persists the *terminal exception's* existing safe packet as evidence of the terminal output-contract condition. It does not reinterpret the packet as a correction authorization. Eligibility is still decided before that branch, and the second attempt cannot be eligible (`agent_world/graph.py:480-508,635-643`).

The packet is compatible with the existing failure closure: a failed WorkRecord requires validation and a Finding (`agent_world/contracts.py:181-211`); `GraphRunner.fail` places the failure Artifact in both the WorkRecord assurance closure and Finding evidence closure (`agent_world/graph.py:494-508,662-729`). The existing bounded-Repair handoff re-derives owner and target from the Finding subject/provenance rather than from evidence content (`.trellis/tasks/08-11-foundry-bounded-repair/prd.md:21-39`, `design.md:43-64`). Thus this adds diagnostic fidelity without changing Repair routing.

Artifact persistence remains safe only for the existing closed `CorrectionPacket` facts: code, exact output path, short safe condition, and expected category. Its contract bounds code/path/condition (`agent_world/contracts.py:82-101`), and ArtifactStore rejects forbidden secret/prompt/sealed/raw-response fields and secret-like values (`agent_world/artifacts.py:15-100`). Current Observe projects only Work safe codes and Finding evidence IDs, not failure payloads (`agent_world/observe.py:301-418`). No raw model output or control field is introduced.

PAC-32 and the diagnosis are consistent: Spark and Luna prove a repeatable terminal evidence loss, not a model-specific cause; both rejected runs remain immutable and unreleased. A fresh Luna proof may disclose the new safe failure Artifact to the internal diagnosis path if it rejects again, while Observe remains its existing safe projection.

### Blocking proof gap

The written implementation rule and acceptance text state explicit-evidence precedence, but the sole specified regression does not prove it. It also says only that both allowed attempts fail "with a packet". If that test uses the same packet twice, it can pass while accidentally persisting the first-attempt packet rather than the terminal packet—the exact attribution PAC-32 says is currently lost.

This is a deterministic contract gap, not a reason to broaden the implementation. The proposed code is otherwise the smallest coherent change, but an allow would not establish the requested evidence precedence or exact terminal attribution.

## Required Plan Revision and Smallest Proof

Revise only the focused regression requirement; do not change the planned implementation scope.

1. In one parameterized focused runner regression, make attempt one raise packet A and terminal attempt two raise a distinct packet B with no explicit evidence. Assert calls are exactly `[None, packet_A]`, the terminal attempt has status `failed`, no third invocation occurs, and the failure Artifact persisted through the failed WorkRecord assurance/Finding evidence closure contains packet B.
2. Add the explicit-precedence case: terminal attempt two carries the same safe packet B *and* a distinct safe explicit evidence value. Assert that exact explicit value, including an explicitly supplied empty JSON value if that is part of the supported contract, is persisted rather than packet B.
3. Keep the existing deterministic quality gate. Only after implementation/check passes, run one fresh exact Luna `world_architecture` node proof and read Observe; if it rejects, inspect only the referenced safe failure Artifact as diagnosis evidence.

The forbidden shortcut is using the prior correction variable, an `or` truthiness fallback, a third call, a model/route rotation, a new feedback schema/Artifact family, a public Observe payload, or any Repair control decision.

## Non-Claims and Next Permitted Gate

- This record does not authorize implementation, another provider call, a retry, a Prompt/compiler/tool-contract change, raw-output retention, Repair, Expand, Consumer, Judge, Registry, or release-policy work.
- It does not prove the failed runs' underlying tool-contract cause, a passing Luna node, any Agent/Candidate/Runtime behavior, or end-to-end publication.
- The current plan allow is absent. The next permitted gate is a revision of `direct-terminal-feedback-plan.md` that makes terminal-packet identity and explicit-evidence precedence deterministic, followed by a fresh critic review with a new digest. This block expires if the plan bytes, terminal trust boundary, or relevant real scene changes.

## Files Found

- `research/diagnosis-direct-proof-4-terminal-feedback.md` — persisted Spark/Luna chronology, causal diagnosis, and rejected alternatives.
- `research/direct-terminal-feedback-plan.md` — reviewed minimal persistence and proof proposal.
- `research/product-alignment-checkpoints.md` (PAC-32) — real-terminal alignment checkpoint and next gate.
- `agent_world/graph.py` — NodeExecutionError, local-correction eligibility, terminal failure Artifact, WorkRecord, and Finding persistence.
- `agent_world/design.py` and `agent_world/contracts.py` — framework-built CorrectionPacket/DesignError and immutable work/finding contracts.
- `agent_world/artifacts.py` and `agent_world/observe.py` — artifact-safety checks and safe read-only projections.
- `tests/test_graph_contracts.py` and `tests/test_artifacts_observe.py` — current correction, terminal, WorkRecord/Finding, and Observe regression patterns.
- `.trellis/tasks/08-11-foundry-bounded-repair/{prd,design}.md` — future route-free Finding and provenance re-verification handoff.

## Related Specs

- `docs/agent-world-environment-generation.zh.md` — canonical evidence-owned framework, failed-claim, repair, release, and safe-observation requirements.
- `docs/direct-rewrite-execution-map.zh.md` — fixed deterministic runner, framework-owned Repair routing, and safe Observe boundary.
- `.trellis/spec/guides/foundry-product-alignment.md` — PAC requirements and prohibition on treating a local/test result as product completion.

## External References

None. This is a repository-contract review.

## Caveats / Not Found

- No provider, SDK, candidate process, tests, or git operation was run; the Spark/Luna facts are evaluated only from the persisted diagnosis/PAC evidence.
- Per role isolation, no task implementation/check context manifests were read or modified.

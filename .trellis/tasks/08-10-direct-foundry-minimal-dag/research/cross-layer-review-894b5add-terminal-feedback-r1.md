# Research: cross-layer review — terminal feedback R1

- Query: Fresh independent re-review of `direct-terminal-feedback-plan.md` R1 after predecessor block, including the terminal `GraphRunner` transaction, `NodeExecutionError`, WorkRecord/Finding closures, PAC-32, and focused test surface.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `894b5addfba25e5f4dade7d72c9bf70ad00b9dee2236880e7645fc88eb343025`, independently recomputed as the raw-byte SHA-256 of `research/direct-terminal-feedback-plan.md`.
- Plan revision and count: R1; revision 1 of the PAC-32 diagnosis/plan lineage, following the predecessor's revision-0 block. One further revision remains if the approved scope must change.
- Scope classification: local, coordinated only within the existing terminal `GraphRunner.execute` transaction and its existing failure Artifact -> failed WorkRecord assurance -> route-free Finding evidence closure.
- Trigger and evidence: PAC-32 and `diagnosis-direct-proof-4-terminal-feedback.md` establish a real, two-attempt Spark/Luna terminal-evidence loss after one authorized correction. Both immutable runs were rejected with no release. The predecessor block required deterministic proof of terminal-packet identity and explicit-evidence precedence; R1 supplies both.

## Product Target and Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This advances only safe attribution of a failed model-validation node; it does not claim a Design commit, later-child execution, or package progress:

```text
framework compiler / DesignError
  -> existing terminal NodeExecutionError.evidence or CorrectionPacket
  -> existing failure Artifact (`<output_kind>.failure`)
  -> failed WorkRecord.assurance_refs and Finding.evidence_refs
  -> current safe evidence IDs / future framework-owned Repair provenance check
```

`GraphRunner` remains the sole owner of correction eligibility and invocation count. Its existing eligibility predicate permits only ordinal 1, one configured local correction, a Direct/Agent rejected non-retryable terminal, and a non-null correction (`agent_world/graph.py:635-643`). The terminal second attempt therefore cannot schedule a third call. `DesignError` remains the framework producer of the closed `CorrectionPacket` (`agent_world/design.py:58-86`); neither model nor packet gains routing, budget, repair, Judge, or release authority.

## Findings

### Deterministic R1 proof closure

R1 explicitly requires attempt 1 packet A and a distinct terminal attempt 2 packet B, with calls exactly `[None, packet_A]`, terminal attempt status `failed`, and no third invocation. This distinguishes the terminal exception from the retained first-attempt correction and directly closes the predecessor's attribution gap.

It also requires the resulting failure Artifact to be located through both existing closures: the failed WorkRecord's `assurance_refs` and the Finding's `evidence_refs`. That is the actual persistence chain: `GraphRunner.execute` passes the same failure Artifact into `fail` (`agent_world/graph.py:494-511`); `fail` stores those refs in the Finding and failed WorkRecord (`agent_world/graph.py:712-741`). Failed WorkRecords require validation and a Finding (`agent_world/contracts.py:196-210`), while Findings require nonempty evidence (`agent_world/contracts.py:213-233`). The focused test may extend the existing correction-runner pattern at `tests/test_graph_contracts.py:415-469` without inventing a new test seam.

R1 also explicitly parameterizes a distinct explicit evidence value, including `{}`, and requires that exact value rather than packet B. The only compatible implementation is the one existing value choice:

```python
failure_evidence = exc.evidence if exc.evidence is not None else exc.correction
```

then existing `json_value` serialization in the existing failure Artifact. `is not None` preserves `{}`; `exc.evidence or exc.correction` would fail the required empty-value case. This choice preserves explicit evidence precedence and uses only the terminal exception's packet when explicit evidence is absent.

### Compatibility and unchanged boundaries

- Artifact safety remains intact: a `CorrectionPacket` is bounded to code, path, safe condition, and expected category (`agent_world/contracts.py:82-97`), and persisted artifacts reject prompts, raw responses, sealed/evaluator fields, credentials, and secret-like values (`agent_world/artifacts.py:15-100`).
- Observe remains unchanged and projects only work/finding-safe fields and evidence IDs, not the failure payload (`agent_world/observe.py:301-415`).
- The plan changes no `NodeExecutionError` or Artifact schema, retry/budget state, model route, Prompt/compiler/tool contract, graph topology, Skill, stale-run behavior, or Candidate/Repair/Expand/Consumer handoff. Existing future Repair continues to derive any route decision from Finding subject/provenance, rather than evidence payload content.
- The canonical contract retains framework ownership of Artifact, Gate, directed repair, and release decisions; a failed terminal remains release-blocking and does not become a model-controlled completion claim (`docs/agent-world-environment-generation.zh.md:1-37,797-873,1026-1088`).

## Smallest Allowed Implementation and Proof

1. Change only the current terminal failure Artifact evidence argument in `GraphRunner.execute` to the exact `is not None` precedence rule above.
2. Add the two focused deterministic terminal tests specified in R1: packet A/B identity with exact two-call/failed-terminal/no-third-call and WorkRecord/Finding closure assertions; explicit-evidence precedence parameterized to include `{}`.
3. Run the existing deterministic quality gate. Only after it passes, run one fresh exact Luna `world_architecture` proof, read Observe, and, if the node rejects, inspect the referenced existing safe failure Artifact for a new diagnosis.

## Non-Claims and Next Permitted Gate

- This allow does not prove a passing Luna node, Agent/Candidate/Runtime behavior, Judge, Registry, Repair, Expand, Consumer, or end-to-end publication. Unit proof establishes only the bounded failure-evidence contract; the fresh node proof is still not E2E proof.
- It does not authorize a third invocation, route rotation, retry/budget change, Prompt/compiler/tool-contract change, raw-output retention, new schema/Artifact family, public Observe payload, or any later-child implementation.
- This allow expires if the plan bytes/digest, terminal evidence trust boundary, or latest relevant real scene changes.
- Next permitted gate: implement exactly this local R1 plan, run its deterministic checks, then conduct the stipulated fresh Luna proof and read Observe at its terminal.

## Files Found

- `research/direct-terminal-feedback-plan.md` — R1 repair scope and deterministic acceptance.
- `research/diagnosis-direct-proof-4-terminal-feedback.md` — persisted Spark/Luna chronology and causal failure-evidence diagnosis.
- `research/product-alignment-checkpoints.md` (PAC-32) — terminal evidence boundary and required critic gate.
- `research/cross-layer-review-3c6d3d85-terminal-feedback.md` — predecessor block and exact proof requirements addressed by R1.
- `agent_world/graph.py` — `NodeExecutionError`, correction eligibility, terminal failure persistence, WorkRecord, and Finding closure.
- `agent_world/contracts.py`, `agent_world/design.py`, `agent_world/artifacts.py`, and `agent_world/observe.py` — closed packet, framework error producer, safety, and safe projection contracts.
- `tests/test_graph_contracts.py` — existing focused runner-correction regression pattern.

## Related Specs

- `docs/agent-world-environment-generation.zh.md` — canonical framework-owned evidence, failure, repair, and release boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — deterministic runner, framework-owned repair routing, and safe Observe boundary.
- `.trellis/spec/guides/foundry-product-alignment.md` — PAC requirements and non-completion rule.

## Caveats / Not Found

- No implementation, deterministic test suite, provider proof, Observe call, or git operation was run by this read-only reviewer.
- Per research-role isolation, `implement.jsonl` and `check.jsonl` were neither read nor modified.

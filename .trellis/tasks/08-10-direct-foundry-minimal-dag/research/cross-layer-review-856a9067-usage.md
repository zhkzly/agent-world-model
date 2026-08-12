# Research: cross-layer review — 856a9067 Direct usage safety

- Query: Independent read-only cross-layer critic review of the real-failure repair plan for Direct usage-evidence persistence and the stale `world_architecture` proof run.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: block

- Plan digest (SHA-256): `856a906764978c8a6f3806a01d55d50dad4208bae4658522c80296b799ed4a62`, independently recomputed from the complete current `research/direct-live-usage-repair-plan.md`; it matches the expected digest.
- Plan revision: usage-safety repair v1; revision count 1 for Diagnosis Record `diagnosis-direct-proof-2-usage-safety.md`.
- Scope classification: coordinated cross-node telemetry/provenance repair. The changed value crosses `DirectChatBackend -> InvocationResult -> OperationEvidence -> GraphRunner persistence -> WorkRecord assurance refs -> telemetry/package/Registry -> Observe`; it is not a new graph, product path, or release policy.
- Trigger: the real Direct proof recorded in the Diagnosis Record and PAC-30. The fresh Observe read of `run_0fe1d0215d644837a43cfe7fc9994abe` confirms `status=running`, one intake event, zero WorkRecords, no findings, and `release=not_published`.

## Product target and expected-vs-actual chronology

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. A parsed model response is only a proposal; it cannot advance this chain until framework validation and its provenance evidence commit.

Expected frozen-node chronology was:

```text
Direct provider result -> canonical secret-safe OperationEvidence
-> assurance.operation Artifact -> compiler/validation
-> WorldArchitecture envelope + passed WorkRecord -> safe Observe facts
```

Actual chronology is supported by the Diagnosis Record and current code:

```text
provider parsed result (diagnosed) -> DirectChatBackend emits prompt_tokens
-> OperationEvidence accepts alias -> GraphRunner persists assurance.operation
-> ArtifactStore rejects key containing "prompt" -> no compiler/no WorkRecord
-> narrow harness exits -> stale running DirectRun
```

The code establishes the first deterministic deviation: `DirectChatBackend` projects `prompt_tokens`, `completion_tokens`, and `total_tokens` (`agent_world/invocation.py:144-158`); `OperationEvidence` permits those aliases (`agent_world/contracts.py:121-139`); and `ArtifactStore` rejects any key containing `prompt` (`agent_world/artifacts.py:77-90`) when `GraphRunner` persists the evidence before compilation (`agent_world/graph.py:465-471,646-660`). The observed run has no persisted operation/failure artifact or WorkRecord, consistent with the failure occurring at that boundary.

## Five-lens attribution

1. **Project-execution view:** supported only for the safe diagnosis and Observe facts. It proves the run is incomplete; it does not supply a runtime provenance Artifact for the original exception.
2. **Direct runtime instruction/input:** not causal. The diagnosed call used the frozen approved projection; no Prompt change is authorized.
3. **Runtime Skill:** absent by Direct contract and not causal. No Skill, tool, workspace, or Agent route may be introduced.
4. **Code/execution boundary:** causal. Provider naming and the shared evidence contract disagree with the Artifact safety invariant before compiler execution.
5. **Feedback/observability:** the current safe scene correctly exposes `running`/zero-work state, but it cannot itself attest `artifact_forbidden_field`; the narrow proof harness, rather than the public composition root, failed to terminalize the run.

## What is coherent and remains permitted after revision

Normalizing valid Direct-provider `prompt_tokens -> input_tokens` and `completion_tokens -> output_tokens` at the Direct adapter, preserving valid `total_tokens`, and removing both aliases from `OperationEvidence` is the smallest safe closure for the naming defect. It preserves the generic safety filter, does not retain provider payloads, and aligns Direct with the already canonical Codex normalization (`agent_world/invocation.py:343-357`). `candidate._compile_telemetry` rehydrates `OperationEvidence` before packaging (`agent_world/candidate.py:1688-1758`), so the single canonical contract is semantically consumable by later package/Registry consumers.

C8 provenance remains compatible: operation evidence remains an `assurance.operation` ref in the same immutable WorkRecord closure (`agent_world/graph.py:553-565`), and its direct Artifact/port bindings, lineage, telemetry, Registry cold-read, and safe Observe schema do not change. Future Repair still receives the unchanged route-free Finding/WorkRecord handoff; future Expand still consumes exact released lineage; future Consumer still consumes only exact released package facts. None is implemented or newly claimed here.

## Blocking finding: stale-run terminalization is not yet an honest action

The plan says to mark the exact stale run `error` with `artifact_forbidden_field`, but it does not identify a framework-owned reconciliation operation, its admissible evidence, or its safe terminal-code mapping. The only durable run facts currently cold-readable are intake plus the preseed request/evidence Artifacts; current Observe has no operation/failure Artifact and no WorkRecord. Moreover, the normal public composition root catches a raw `ValueError` and maps it to `foundry_internal_error` (`agent_world/foundry.py:53-60,96-98`), whereas the proposed historical run was created by a narrower node harness. Directly editing or independently finishing `run.json` with the more specific raw Artifact code would therefore manufacture a new control-plane fact without the normal root's evidence/normalization path.

This is not a request for a recovery framework. It is a plan-completeness failure at the DirectRun/Observe truth boundary. The plan cannot both claim a framework-owned honest terminal and leave the producer, evidence source, and code mapping unspecified.

## Required plan revision (actionable)

Revise the written plan only, preserving the two-field normalizer and alias removal, with exactly one of these minimal, explicit alternatives:

1. **No historical mutation:** retain the existing run as an observed interrupted harness record, do not label it terminal, and record the new post-fix proof as a separate run. Its non-claim must say the stale run remains unreconciled; or
2. **Narrow reconciliation:** name an existing framework-owned operation that cold-reads the exact run, name the persisted safe evidence external to the absent WorkRecord that authorizes the reconciliation, use the code it is allowed to expose, and write the terminal event through `ArtifactStore`/`DirectRun` rather than editing bytes. Add a focused regression proving that this one historical-state action cannot create a WorkRecord, release, Finding route, or altered artifact provenance.

Do not add a generic graph-error/recovery subsystem, weaken `ArtifactStore`, add alias exceptions, modify Prompt/Skill/route/retry behavior, or rerun the model before the revised plan is allowed. If no admissible durable evidence for option 2 exists, option 1 is the only honest closure.

The revised plan must also make the deterministic checks exact:

- mocked Direct provider response normalizes only valid non-negative integer usage to canonical keys;
- provider aliases are rejected by `OperationEvidence` before persistence;
- canonical Direct `OperationEvidence` persists as `assurance.operation` and is present in the resulting WorkRecord assurance closure; and
- existing Codex canonical usage, Artifact safety rejection of real Prompt-shaped keys, C8 port/provenance closure, and telemetry cold-read remain unchanged.

The smallest true-boundary proof after implementation is one fresh invocation of the same frozen `world_architecture` node, followed by Observe of that run. It either commits one passing WorkRecord after compiler validation or is terminalized by the actual proof entrypoint with a newly observed safe failure; it does not prove Candidate, Integration, Judge, Registry, Repair, Expand, Consumer, or E2E release.

## Non-claims and next permitted gate

This review does not claim the diagnosed model JSON compiled, that any model output is a Design Artifact, or that the package/release path works. It does not authorize a new telemetry schema, Artifact safety exception, Prompt/compiler/route/fallback/retry change, Skill change, candidate change, or any Repair/Expand/Consumer implementation.

Next permitted gate: the plan writer must publish a revised usage-repair plan that resolves the stale-run truth boundary above, then obtain a fresh independent critic review. No implementation, state cleanup, or proof rerun is permitted under this blocked revision.

## Files found

- `research/diagnosis-direct-proof-2-usage-safety.md` — persisted chronology, attribution, and rejected alternatives for the real proof failure.
- `research/direct-live-usage-repair-plan.md` — reviewed v1 repair plan and digest input.
- `research/product-alignment-checkpoints.md` (PAC-30) — product alignment and explicit non-claims for this failure.
- `research/direct-live-route-r1-check.md` — confirms the preceding route repair and its non-claims.
- `agent_world/contracts.py` — shared `OperationEvidence` contract and DirectRun terminal model.
- `agent_world/invocation.py` — Direct provider parsing and canonical Codex usage normalization.
- `agent_world/artifacts.py` — generic secret/Prompt-key safety rule.
- `agent_world/graph.py` — operation-evidence persistence before compiler and WorkRecord assurance closure.
- `agent_world/foundry.py` — public terminal catch mapping for raw `ValueError`.
- `agent_world/candidate.py` — telemetry consumer that cold-reads `OperationEvidence`.
- `tests/test_artifacts_observe.py`, `tests/test_graph_contracts.py`, `tests/test_direct_release.py` — existing safety, WorkRecord, and telemetry regression coverage.

## Caveats / Not Found

- The live provider result and raw exception are described in the persisted Diagnosis Record; the current run state itself contains no persisted operation/failure evidence, only its safe incomplete scene.
- Per role isolation, `implement.jsonl` and `check.jsonl` were not read or modified.

# Research: cross-layer review — 91640dda usage R1

- Query: Fresh independent read-only cross-layer review of the revised Direct usage-safety repair plan after the predecessor block.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest (SHA-256): `91640dda2714099ed6e8c34fb68dc77d6baae58085f9f208ca7fe7b53736bece`, independently recomputed from the complete current `research/direct-live-usage-repair-plan.md`; it matches the required digest.
- Plan revision: usage-safety repair R1; revision count 2 (and final permitted revision) for Diagnosis Record `research/diagnosis-direct-proof-2-usage-safety.md`.
- Scope classification: coordinated cross-node telemetry/provenance repair. It changes one safe value across `DirectChatBackend -> InvocationResult -> OperationEvidence -> GraphRunner assurance persistence -> WorkRecord -> package telemetry/Registry cold-read -> Observe`; it does not alter graph topology, release policy, or a later child.
- Trigger and evidence: the diagnosed real Spark `world_architecture` attempt reached parsed JSON but failed before compiler execution when `assurance.operation` persisted provider-named `prompt_tokens`. PAC-30 and the Diagnosis Record establish the stale run as `running`, zero-WorkRecord, `not_published` diagnostic evidence; this review does not turn that fact into a runtime Artifact or terminal result.

## Product target, impact chain, and owners

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. A provider response remains merely a proposal until framework validation and immutable evidence commit.

The approved impact chain is:

```text
Direct provider usage
  -> DirectChatBackend canonical projection
  -> OperationEvidence closed safe contract
  -> GraphRunner assurance.operation Artifact
  -> WorkRecord.assurance_refs
  -> Candidate telemetry cold-read / Package / Registry
  -> safe Observe facts
```

Framework ownership does not move. `DirectChatBackend` owns only provider-to-`InvocationResult` projection; `OperationEvidence` closes the shared evidence schema; `ArtifactStore` remains the sole secret/Prompt-like-field persistence guard; `GraphRunner` writes immutable assurance and WorkRecord facts; Controller remains the only ReleaseKernel; Registry remains the only re-verifier/publisher. No model, Agent, proof harness, Package, Registry, or Observe projection receives error, retry, release, adoption, or reconciliation authority.

## Revision acceptance and compatibility

R1 fully accepts predecessor option 1, no historical mutation. It expressly leaves `run_0fe1d0215d644837a43cfe7fc9994abe` unchanged, incomplete, unreconciled, and ineligible as a resume or release input. It adds neither a reconciliation operation nor a recovery framework. The fresh proof is a separate run, so it cannot manufacture a WorkRecord, Finding, terminal code, provenance, or release history for the stale harness scope.

The two-key normalizer is exact and minimal: valid non-negative provider `prompt_tokens` becomes `input_tokens`, and `completion_tokens` becomes `output_tokens`; valid `total_tokens` remains unchanged. It neither retains raw provider payloads nor invents missing counters. Removing both aliases from `OperationEvidence` makes the shared contract persistable before `ArtifactStore` sees it, while retaining the canonical keys already emitted by Codex (`cached_input_tokens`, `input_tokens`, `output_tokens`, `reasoning_output_tokens`, `total_tokens`). This preserves the generic key safety rule rather than special-casing telemetry.

The existing downstream consumer is compatible: `candidate._compile_telemetry` cold-reads every `assurance.operation` and reconstructs `OperationEvidence` before Package/Registry evidence is emitted (`agent_world/candidate.py:1688-1723`). It therefore consumes the same closed canonical schema, not provider aliases. C8 provenance is also unchanged: `GraphRunner` continues to persist operation evidence as a WorkRecord assurance ref before compilation (`agent_world/graph.py:452-472,646-660`); no `ArtifactEnvelope` port declaration, Edge binding, direct input ref, telemetry binding, Registry cold-read, lineage, or Observe schema changes.

Future-child compatibility is concrete and unchanged. Bounded Repair keeps the same immutable WorkRecord and route-free Finding handoff; Expand keeps exact released package/lineage inputs; Consumer receives only exact released package facts. This repair implements none of their behavior and changes none of their declared shapes or authorities.

## Smallest allowed implementation and proof

Only the following is permitted:

1. Normalize the two valid Direct-provider keys in `agent_world/invocation.py`, preserve valid `total_tokens`, and retain no provider payload.
2. Remove only `prompt_tokens` and `completion_tokens` from the accepted `OperationEvidence` usage-key set in `agent_world/contracts.py`.
3. Add deterministic tests for: mocked Direct normalization of only non-negative integer usage; rejection of both aliases at `OperationEvidence` construction; and canonical Direct evidence persisted under `assurance.operation` and present in the committed WorkRecord assurance closure. Keep the existing Codex canonical-usage, Artifact Prompt-field safety, C8 port/provenance, and telemetry cold-read checks green; no new framework or cross-child test surface is justified.
4. Run the established deterministic quality gate. Then invoke the exact frozen `world_architecture` proof through the existing public composition-root mapping and read Observe after termination. `DirectFoundry.generate` already maps raw `OSError`, `ValueError`, and `TypeError` to the safe terminal `foundry_internal_error` (`agent_world/foundry.py:59-60,96-98`); the fresh harness must use that existing boundary rather than add a competing mapping.

The true-boundary proof is limited: the fresh run either commits one passing `world_architecture` WorkRecord after compiler validation, or produces a newly observed safe terminal failure. It is not a Candidate, Integration, Judge, Registry, or end-to-end release proof.

## Non-claims and next permitted gate

- This allow does not claim that the stale run's model JSON compiled, that the stale run is terminal, or that it may be adopted.
- It does not authorize an Artifact safety exception, a telemetry schema, graph/node/error/recovery framework, Prompt/compiler/route/fallback/retry/Skill change, or Candidate/Repair/Expand/Consumer implementation.
- It does not prove real Agent execution, generated candidate behavior, isolated Judge success, Registry publication, or product completion.

Next permitted gate: implementation strictly limited to the four items above. Before dispatch, the coordinating session must add this matching allow record to the task implementation and check context. After deterministic verification, run the one fresh frozen-node proof and read Observe; any new terminal scene requires a new diagnosis before a further repair decision.

## Caveats / Not Found

- No implementation, test, provider call, proof, state mutation, or git operation was performed during this review.
- The stale run's safe incomplete state is established by the persisted Diagnosis/PAC evidence; it is intentionally not re-opened, reconciled, or used as a source of new runtime facts.

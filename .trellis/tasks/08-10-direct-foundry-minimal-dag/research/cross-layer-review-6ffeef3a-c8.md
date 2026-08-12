# Research: cross-layer review — Direct C8 port provenance

- Query: Independently review the exact Direct R9-C8 port-provenance plan against the current clean worktree and decide whether it is the smallest coherent implementation scope.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: allow

- Plan digest: `6ffeef3a778a5dacafca58bc5d70e4ad5d015905191d37502a790a86825680d0` (recomputed from the eleven declared raw-byte inputs).
- Parent digest: `7c3d0bafc67f28abe5eb713849e3c99076e2d44c0bf403f28f4746dcd4207b2f` (recomputed from the declared twenty-two raw-byte inputs).
- Plan revision and count: Direct R9-C8, second and final bounded revision in the C6 closure lineage.
- Scope classification: coordinated cross-node, static Direct provenance closure across the shared `ArtifactEnvelope`/`GraphRunner` boundary and the five named Direct executor boundaries. It does not change product behavior or require a larger Direct/Repair/Expand/Consumer slice.
- Trigger: the static C7 whole-diff block, not a real execution terminal. No Observe scene or Diagnosis Record is required or inferred.

## Product Target and Affected Boundary

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This plan advances only the evidence/provenance leg of that target. It makes the fixed graph prove which declared logical producer port and which exact direct Artifacts an executor consumed; it does not claim that a graph test, a package-shaped byte stream, or this review proves a real Direct release.

Affected trust boundary and impact chain:

```text
producer NodeSpec.output_ports
  -> immutable ArtifactEnvelope.output_ports
  -> EdgeSpec(source, source_port) validation in GraphRunner
  -> exact WorkRecord input/dependency refs at corrected executor
  -> Package telemetry/dossier/physical closure
  -> Registry cold-read/publication evidence
  -> safe Observe provenance projection
```

Owners remain unchanged: Designer owns `research_synthesis`, `task_requirement`, and `modeling_gate`; Controller's sole ReleaseKernel owns `package`; Registry owns physical re-verification and atomic publication. No Agent, Judge, package writer, Registry, or model gains routing, retry, invalidation, budget, or release authority.

## Findings

### One-envelope/multi-port contract

Adding only `ArtifactEnvelope.output_ports` and requiring every edge-bound input to match both the exact producer node and `EdgeSpec.source_port` is sufficient for the already-approved C6 representation. The fixed `NodeSpec` remains the only port vocabulary; the immutable envelope attests that its producer committed the exact closed ordered port tuple; and each binding selects an attested source port while the flattened dependency list stores the single envelope once. A `PortRef` or split envelopes would duplicate an already fixed static graph capability without adding a required consumer.

The current defect is real: `GraphRunner._resolve_inputs` verifies only `producer["node_id"]` against permitted source nodes and discards `EdgeSpec.source_port` (`agent_world/graph.py:538-585`). The runner currently writes envelopes without any output-port declaration (`agent_world/graph.py:515-535`; `agent_world/contracts.py:155-173`; `agent_world/artifacts.py:301-354`). C8's exact declaration equality check and hostile wrong/missing-source-port regression close that gap without a new abstraction.

### Complete direct-causal binding

The plan names every direct Artifact currently consumed at the five affected boundaries and has a coherent binding form for each:

- `research_synthesis`: bind both `research_acquire.sources` and `.citations`; the one acquisition envelope legally carries both ports, while source text remains ephemeral and its content digests are committed (`agent_world/design.py:515-606`).
- `task_requirement`: add architecture and all tool-semantics bindings to the current curriculum/rules bindings, matching the actual model projection and compiler use (`agent_world/design.py:1056-1189`; `agent_world/graph.py:194-202,300-301`).
- `modeling_gate`: add evidence and all tool-semantics bindings to its existing compiled Design inputs, matching the payload it deterministically compiles (`agent_world/design.py:1209-1253`; `agent_world/graph.py:204-210,302-305`).
- `package`: bind `VerifierBundle`, semantic/implementation lineage, and the exact Design/Candidate `WorkRecord` collections from which telemetry is compiled (`agent_world/candidate.py:1278-1380,1674-1715`). The Design and Candidate records are framework-produced external/committed inputs, so they need not be invented as a new graph producer edge.
- `registry`: bind exact Design, Candidate, VerifierBundle, physical package bytes, actual dossier, actual telemetry, semantic/implementation lineage, and the same WorkRecords as direct inputs beside existing Package/Integration/Judge inputs. This matches the values read by `_registry` and `_cold_verify` (`agent_world/candidate.py:1389-1470,2320-2370`). JSON Artifacts and the already-supported physical package bytes are sufficient media; extending the resolver to cold-read exactly those two existing forms is a local compatibility correction, not a media registry.

Values only reached through a bound envelope remain transitive. The plan correctly does not add duplicate inputs merely to restate package manifest members, source closure files, or model projections.

### Dossier edge and compatibility

Removing the false `package.dossier -> registry.dossier` edge while retaining the Package envelope edge and the existing cold checks is coherent. Current code passes the package envelope as the `dossier` binding despite `_registry` consuming the separately produced dossier (`agent_world/candidate.py:1405-1457`). C8 replaces that false causal claim with the actual dossier Artifact, preserves Package as the graph-produced carrier, and retains the package payload check plus cold package/closure verification. This strengthens rather than bypasses Registry evidence.

Repair, Expand, and Consumer are unaffected compatibility consumers: their frozen future handoffs are `WorkRecord`, `Finding`, `EnvironmentPackageRef`, semantic lineage, implementation lineage, Registry receipt, and package-owned difficulty schema. C8 neither changes those shapes nor introduces their control behavior. `EnvironmentPackageRef` still receives the same exact lineage and release facts (`agent_world/contracts.py:326-359`); later children only gain a more complete provenance closure behind those unchanged values.

### Scope/authority pressure test

The written C8 scope does not broaden model prompts, Runtime Skills, model projections, Judge/Release authority, public ABI, Repair, Expand, Consumer, public Observe, retry, permissions, profiles, or compatibility behavior. It explicitly reuses `ArtifactEnvelope`, `NodeSpec`, `EdgeSpec`, `GraphRunner`, and fixed executors, and forbids `PortRef`, split output envelopes, a graph/media/plugin framework, scheduler, or later-child path. This is the smallest coherent correction.

## Smallest Permitted Implementation and Proof

Only the following implementation is permitted by this allow:

1. Add closed nonempty unique `output_ports` to `ArtifactEnvelope` persistence/cold-read; have `GraphRunner` commit exactly the fixed producer `NodeSpec.output_ports`.
2. Make `_resolve_inputs` cold-read JSON envelopes or the existing zip package bytes as appropriate; for every edge-bound envelope require the exact graph/node and exact declared `source_port`, with the envelope's ordered port declaration equal to the producer `NodeSpec` declaration.
3. Update only the fixed node declarations, edges, and executor bindings needed for the five C8 direct-causal closures, including actual dossier/telemetry/lineage/package-byte/WorkRecord values and removal of the fake dossier edge.
4. Add only focused regressions: hostile source-port substitution; valid one-envelope/two-port fan-out without duplicate dependency refs; full corrected `WorkRecord` direct input closure; absence of the fake dossier binding; JSON/physical-package cold reads and malformed/unsupported closed failure.

Run the existing deterministic gate and then a fresh independent Terra whole-diff check. The next permitted gate after this review is implementation limited to the four items above; the coordinating session must attach this current allow record to both task manifests before dispatching implementation/check.

## Non-Claims

- This static allow is not a real Direct LLM, Codex Agent, candidate-process, Judge, Registry, or E2E proof.
- It does not prove that provider routes, isolated Runtime execution, real research, package publication, or Observe release projection work.
- It does not authorize a repair, campaign, multi-parent, consumer, training, prompt, Skill, release-policy, or public-ABI change.
- Any plan-byte, affected-trust-boundary, or relevant real-scene change expires this allow.

## Files Found

- `AGENTS.md` — project authority, clean-worktree, and development-gate rules.
- `docs/agent-world-environment-generation.zh.md` — canonical Foundry product, Artifact DAG, independent verification, release, and downstream-path contract.
- `docs/direct-rewrite-execution-map.zh.md` — derived Direct node/execution taxonomy and fixed two-graph constraint.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,node-contracts,implement}.md` — Direct C6 contract, fixed node/edge semantics, and C8 implementation boundary.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c7-final-whole-diff-check-block.md` — static source-port and direct-causal-input blocking evidence.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-c8-port-provenance-plan.md` — reviewed C8 correction plan.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/plan-digest-r9-c8-port-provenance.md` — declared Direct digest inputs and lineage.
- `.trellis/tasks/08-11-foundry-complete-v1/{prd,design,implement}.md` and `research/plan-digest-port-provenance-c8.md` — parent owner boundaries, child compatibility, and declared aggregate inputs.
- `agent_world/contracts.py`, `artifacts.py`, `graph.py`, `design.py`, `candidate.py` — current envelope, graph, executor, telemetry, package, and Registry behavior.
- `tests/test_graph_contracts.py` and `tests/test_direct_release.py` — focused existing graph/provenance and package cold-read coverage.

## Related Specs

- `.trellis/spec/guides/foundry-product-alignment.md` — graph progress is not product completion; release/proof boundaries retain explicit non-claims.
- `.trellis/spec/agent_world/backend/index.md` — artifact-driven success paths, framework-owned release, and real live proof distinction.

## External References

None. This is a static repository-contract review.

## Caveats / Not Found

- Per role-isolated research policy, `implement.jsonl` and `check.jsonl` were not read or modified. They are not digest inputs; the coordinating session must add this exact allow record to both before implementation/check dispatch.
- No tests, providers, Agent SDK session, candidate process, real execution proof, Observe scene, or git operation was run during this read-only review.

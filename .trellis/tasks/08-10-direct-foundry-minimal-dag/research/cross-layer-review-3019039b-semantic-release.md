# Research: cross-layer review 3019039b semantic release

- Query: 对 revision 1/2 的 `semantic-identity-release-closure` 计划做独立、只读的 Direct 跨层/发布闭环审查；只保留当前 Direct 的 release-blocking finding。
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `sha256:3019039b02ce8803d5e2dcbf53a596345d7632b736f70ac780d586a3ff733438`
- Plan revision: `1/2`; one plan-only revision remains permitted.
- Scope classification: coordinated existing-node repair across DesignGraph, CandidateGraph, GraphRunner semantic provenance, and the Registry publication boundary.
- Trigger: static whole-diff block in `research/direct-design-provenance-whole-diff-final-check.md`; its persisted diagnosis is `research/diagnosis-semantic-identity-release-closure.md`.
- Observe/Diagnosis status: this is a static contract finding, not a real proof terminal. No Observe scene exists or is inferred.

## Product target, scope, and impact chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in a
real isolated boundary, publish an immutable Registry `EnvironmentPackage`,
and expose only safe facts through Observe. A graph commit, static check, or
package-shaped ZIP is not that product result.

The complete current Direct downstream chain is:

```text
EnvironmentRequest
-> ResearchPlan -> Search/Fetch/Extract -> Evidence/Coverage
-> World/Tool/Rule/Curriculum/Task semantics -> ModelingGate -> EnvironmentDesign
-> BuildPlan + VerifierIntent -> CandidateBuild -> Integration
-> independent Judge -> Package/ReleaseDossier -> Registry publication -> Observe
```

Owners remain compatible with the task contracts: Designer owns DesignGraph and
VerifierIntent; Builder owns BuildPlan/CandidateBuild/Integration; Judge owns
independent evidence; Controller owns the sole Package/ReleaseKernel decision;
Registry only cold-verifies and atomically publishes. Repair, Expand, Consumer,
and any live proof are non-targets here and are not blockers.

The plan correctly follows the changed values through that chain:

- G1 binds the ResearchSynthesis `questions_to_resolve` value actually written
  to the Agent workspace (`agent_world/design.py:798-809`) rather than relying
  on its parent WorkRecord alone.
- G2 binds ModelingGate's directly compiled Evidence and ordered ToolSemantics
  inputs (`agent_world/design.py:2017-2122`), which feed the Design consumed by
  both CandidateGraph branches.
- TaskRequirement narrows its physical input/dependency closure to the
  ordered family-selected tools while leaving its already-complete Direct
  projection unchanged. The unselected shared-tool analogue is not omitted:
  current `WorldArchitecture` permits either no group or exactly one group of
  all tools (`agent_world/contracts.py:679-681`).
- CandidateBuild's written `inputs/design.json`, Package/Registry telemetry's
  ordered WorkRecords, and Registry's direct Design/Candidate/physical-package
  inputs are the same-mode current values identified in
  `agent_world/candidate.py:859-900`, `1558-1584`, and `1611-1683`.
- The Package physical ref equality closes the otherwise unguarded handoff
  `Package.physical_package_ref -> Registry physical_package -> RegistryReceipt
  -> EnvironmentPackageRef -> Observe`; `_ref` compares the full physical
  ArtifactRef shape (`agent_world/candidate.py:120-128`).
- Removing `local_corrections` from semantic identity is correct: it is attempt
  policy, not frozen answer/acceptance semantics (`agent_world/graph.py:442-461,
  673-681`). Existing correction evidence and bounded behavior stay intact.

No further release-blocking current Direct model/projection or physical-input
omission was found in the already inspected execution sites. BuildPlan already
binds its projection; Integration/Judge bind their exact Design/Candidate/
Integration/Verifier closure; private verifier cases are deterministically
derived and validated rather than a missing Artifact input. This does not
claim a real Provider, candidate process, Judge, Registry, or E2E proof.

## Single release-blocking gap

`GraphRunner.semantic_revision` hashes static node declarations plus supplied
semantic material (`agent_world/graph.py:442-461`). The plan adds a new
Registry acceptance predicate—Package's committed `physical_package_ref` must
equal the supplied publishable physical package—but its Step 6 leaves the
Registry validator/executable identity unversioned. `prompt_id`,
`output_contract`, and mounted Runtime-Skill digest are sufficient explicit
identities for their existing Prompt/output/Skill surfaces in this narrow plan;
none is an explicit identity for this new framework-owned Registry equality
predicate. Merely adding `physical_package.digest` as an input is not a
substitute for versioning what the Registry accepts.

This violates the source contract's requirement that acceptance identity bind
the explicit validator executable revision. It is release-blocking because the
changed predicate sits immediately before atomic publication; it is not a
reason to add a new release owner, graph, or general identity system.

## Required plan revision — one field only

Revise only Step 6 of the plan to add this one field to the existing Registry
`semantic_material` mapping in `agent_world/candidate.py`:

```python
"registry_acceptance_revision": "physical-package-ref-equality@1"
```

`GraphRunner` already hashes that mapping, so no `NodeSpec` change, reflection,
new abstraction, config field, or generic identity framework is permitted. The
literal is non-secret and must be bumped only when this Registry
physical-ref-equality/cold-publish acceptance behavior changes. Add one focused
deterministic assertion that changing only this field changes the Registry
semantic revision, alongside the plan's existing rejection test for a valid but
different ZIP. Do not add model name, base URL, credential, correction packet,
workspace/cache path, retry, or source hashing.

This is the unique required revision. The plan's rejection of base URL,
credential, transport/retry mechanics, `CorrectionPacket`, source reflection,
and generic framework machinery is correct: they are respectively secret or
execution/attempt policy, and would either widen authority or make unrelated
work identities churn. The resolved runtime model remains operation provenance
under the current Direct fallback contract, not a new acceptance input.

## Proof, compatibility, and next permitted gate

After that plan-only revision, the smallest deterministic proof is the plan's
field-variation regression plus its G1/G2, selected-ref, Candidate projection,
WorkRecord, and physical-ZIP equality regressions. The required next gate is a
fresh independent cross-layer review of revision 2/2; implementation and the
existing ordered real-boundary proofs remain forbidden until an `allow`.

The stated `+24` production-LOC ceiling is an upper bound, not a budget to
spend. The listed map/equality edits plus the one required field should fit in
roughly `+18` net production lines; no expansion beyond that is justified.

## Caveats / Not Found

- This record is static and read-only. It makes no live-proof claim and does
  not block on Repair, Expand, Consumer, training, or their proofs.
- Per the role-isolation rule, `implement.jsonl` and `check.jsonl` were not
  read; the reviewed task authority was `prd.md`, `design.md`, `implement.md`,
  `node-contracts.md`, the named diagnosis/audits/plan, current code, and the
  governing source documents.
- No external references, code, test, plan, task context, or existing document
  was modified.

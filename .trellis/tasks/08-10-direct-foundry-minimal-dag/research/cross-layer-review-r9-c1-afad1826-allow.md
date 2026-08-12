# Cross-layer review — R9 closure lineage C1 revision 1

- Decision: `allow`
- Reviewer: fresh independent read-only `trellis-research` Codex worker
- Model: `gpt-5.6-terra`
- Plan digest:
  `afad182665188ec1e7e9e5c1f2192851ddaa5a903d8f5be3d5411e0a54198016`
- Digest inputs, in order: `prd.md`, `design.md`, `node-contracts.md`,
  `implement.md`, `docs/direct-rewrite-execution-map.zh.md`
- Plan revision: R9-C1 revision 1
- Scope: larger Direct vertical slice across Controller, Designer, Builder,
  Judge, Registry and Observe
- Trigger: human-authorized new lineage after the prior R9 lineage ended
  `needs_human`

## Product target

Turn an arbitrary natural-language `EnvironmentRequest` into an
evidence-grounded executable environment, run it in a real isolated boundary,
independently judge it, atomically publish an immutable Registry
`EnvironmentPackage`, and expose only safe facts through Observe.

## Decision basis

The four C1 corrections are coherent, executable and bounded:

1. `FieldDeclarationDraft`, `VerifierValueDraft` and
   `ArgumentStrategyDraft` now have finite variants, explicit bounds,
   cross-field conditions and compiler-owned validation. Implementation must
   enforce them as strict closed schemas, not infer omitted structure.
2. Ownership is singular: Designer owns DesignGraph and verifier intent;
   Builder owns build plan, candidate build and Integration; Judge owns
   evidence-only judging; Controller owns the sole Package/ReleaseKernel
   decision; Registry only cold-reads and atomically publishes.
3. The `uv 0.11.29` argv/environment, pre-install rejection matrix, trusted
   locked-wheel store, post-sync rehash and hostile-package regressions close
   build-hook, index, direct-source and sdist bypasses. A stdlib-only first live
   proof is an explicit non-claim, not a downloader/dependency subsystem.
4. The locked `openai-codex==0.144.4` SDK can support the required real
   singleton-Skill proof. Because the client begins from a copy of the ambient
   environment, a config/filesystem spy alone is insufficient; the real proof
   must verify the initial Skill surface/nonce, physical bundle digest before
   and after, non-ambient `CODEX_HOME`, SDK close, cleanup and fail-closed
   mismatch. This does not justify a permission/profile/capability framework.

The reviewer independently reproduced the declared digest. The old `3b20...`
value remains only as quoted historical evidence in the prior `needs_human`
record; its stale request file is absent and it is not an active approval
candidate.

## Impact chain and compatibility

```text
WorldArchitecture / VerifierIntent closed schema
  -> compiled EnvironmentDesign / VerifierBundle
  -> CandidateBuild + independent Integration
  -> evidence-only Judge
  -> Controller Package/ReleaseKernel
  -> Registry re-verification/publication
  -> read-only Observe
```

CandidateBuild/Verifier separation, poisoned-Verifier branch survival,
Finding-only current behavior, outer deferred Expand, read-only Observe and
downstream-only Training remain unchanged.

## Smallest allowed implementation

Implement only in the clean `/home/kelong/pycodes/foundry-direct-graph`
worktree. Use the two declared domain graphs and existing thin SDK/config/
Invocation result boundaries. Implement the strict schemas, owner matrix,
offline installer, real Skill proof, canonical candidate contracts,
Integration/Judge/release closure and Observe described by this exact digest.

Forbidden shortcuts: generic graph platform, legacy/compatibility path,
profile/capability/permission layer, configurable sandbox, SDK worker protocol,
wheel downloader/index client, hidden retry, LLM Router, second ReleaseKernel,
weakened validator or inherited parent verdict.

## Required checks and proofs

- Deterministic: strict schema/owner checks, graph-port closure, no verifier
  leakage, poisoned-Verifier survival, hostile installer cases, immutable
  provenance/package cold-read and safe Observe.
- True boundary: one real Direct LLM node; one real singleton-Skill Codex SDK
  preflight; one real CandidateBuild plus exact offline Integration; then one
  fresh natural-language need-to-Registry E2E followed by Observe.

## Explicit non-claims and next gate

This allow does not prove a successful live E2E, automatic repair,
Expand/Campaigns, parent reuse, Consumer/SFT/RL or universal model reliability.
It approves only the written plan. The main planner must place this record in
both task manifests and obtain explicit user approval of the latest final
planning summary before `task.py start`. Any semantic-plan digest,
trust-boundary or relevant real-scene change expires this allow.

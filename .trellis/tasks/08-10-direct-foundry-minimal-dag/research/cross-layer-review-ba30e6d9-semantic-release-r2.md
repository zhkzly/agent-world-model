# Research: cross-layer review ba30e6d9 semantic release r2

- Query: Perform the final independent, read-only cross-layer critic review of revision 2/2 for `semantic-identity-release-closure`; verify only resolution of the prior Registry acceptance-identity block and preservation of the bounded plan.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `sha256:ba30e6d969cdc66f4c848a743f50e7aade191440a4cafcd28a3923322a65c3a5` (independently reproduced from the complete plan file).
- Plan revision: `2/2`, the final permitted revision for this diagnosis/plan lineage.
- Scope classification: coordinated, bounded existing-node repair across DesignGraph/CandidateGraph semantic provenance and the Registry publication boundary.
- Trigger: the static whole-diff block recorded in `research/direct-design-provenance-whole-diff-final-check.md`; diagnosis is `research/diagnosis-semantic-identity-release-closure.md`.
- Observe status: this is a static contract finding, not a real proof terminal. No Observe scene exists or is inferred.

## Revision-2 resolution

Revision 1 had one release-blocking omission: its new framework-owned Registry
predicate—Package's committed physical package ref must equal the supplied
publishable ref—had no explicit acceptance-executable identity. The previous
critic required exactly one field and one field-variation regression
(`research/cross-layer-review-3019039b-semantic-release.md:73-107`).

Revision 2 resolves precisely that omission:

- Step 6 adds exactly
  `"registry_acceptance_revision": "physical-package-ref-equality@1"` to the
  existing Registry semantic material, with a bump only when that
  equality/cold-publish predicate changes
  (`research/direct-semantic-identity-release-closure-plan.md:39-46`).
- Its deterministic acceptance explicitly varies only that field and requires a
  changed Registry semantic revision with unchanged graph structure and runtime
  authority (`research/direct-semantic-identity-release-closure-plan.md:73-79`), alongside the valid-but-different-ZIP
  rejection regression.
- `GraphRunner.semantic_revision` canonical-hashes supplied semantic material
  into `effective_projection_digest` (`agent_world/graph.py:442-461`), so this
  existing mapping is the correct narrow identity hook. No NodeSpec field,
  reflection, configuration surface, or generic identity mechanism is needed.

## Product target, impact chain, and compatibility

The target remains: turn an arbitrary natural-language `EnvironmentRequest`
into an evidence-grounded executable environment, independently verify it in a
real isolated boundary, publish an immutable Registry `EnvironmentPackage`,
and expose only safe facts through Observe. A plan allow, graph commit, or
deterministic regression is not a product-completion claim.

The affected Direct suffix is:

```text
Package physical_package_ref
-> Registry supplied physical_package
-> framework equality predicate + cold read
-> atomic Registry receipt / EnvironmentPackageRef
-> Observe
```

Compatibility is concrete and bounded:

- Package already persists the full physical ref through `_ref(...)`
  (`agent_world/candidate.py:120-127, 1546-1555`); Registry already reads the
  Package envelope before cold-reading the supplied bytes
  (`agent_world/candidate.py:1611-1621`). The planned equality compares the
  same complete ref shape rather than introducing a parallel identity.
- Controller remains the sole Package/ReleaseKernel owner; Registry remains
  only the cold-verifying, atomic publisher. No model, candidate, Judge, or
  new Gate gains authority. This matches the current node contract
  (`node-contracts.md:58-85, 777-810`).
- The source contract requires acceptance identity to include an explicit
  validator executable revision and requires Registry to independently bind
  physical/package closure before publication
  (`docs/agent-world-environment-generation.zh.md:111, 1005`). The versioned
  literal is the smallest explicit identity for this one new predicate.

## Boundaries, tests, and next gate

The revision retains the exact listed files, rejects new production files,
dependencies, types, nodes, graphs, config fields, and compatibility paths, and
preserves the `+18` physical-production-LOC ceiling
(`research/direct-semantic-identity-release-closure-plan.md:48-60`). It also
retains the prior rejected categories: source/prompt hashing, model/profile or
transport values, credentials, correction packets, and generic identity
machinery.

Smallest required deterministic evidence is the focused acceptance-revision
field-variation assertion plus the already specified different-physical-ZIP
rejection, exact-physical-ref revision, and existing bounded semantic-closure
regressions. The later true-boundary sequence remains unchanged: after scoped
implementation and a fresh independent whole-diff allow, run the existing
Direct-node, singleton-Skill Agent, CandidateBuild/Integration/Judge, then
fresh natural-language Direct-to-Registry/Observe proofs
(`research/direct-semantic-identity-release-closure-plan.md:83-91`).

Next permitted gate: the main planner may add this matching allow record to the
task's implementation/check context and dispatch only the reviewed scoped
implementation. Any change to this plan digest, this Registry trust boundary,
or a later real proof scene expires this allow.

## Files Found

- `docs/agent-world-environment-generation.zh.md` — authoritative acceptance,
  Registry, and publication contract.
- `docs/direct-rewrite-execution-map.zh.md` — derived Direct owner/executor
  map; Registry is framework publication only.
- `prd.md`, `design.md`, `implement.md`, `node-contracts.md` — current Direct
  task architecture, owner, package, and Registry handoff contracts.
- `research/diagnosis-semantic-identity-release-closure.md` — static causal
  diagnosis and deliberate non-scope.
- `research/direct-semantic-identity-release-closure-plan.md` — reviewed
  revision-2 plan and digest source.
- `research/cross-layer-review-3019039b-semantic-release.md` — prior block and
  its unique required revision.
- `agent_world/graph.py` and `agent_world/candidate.py` — current semantic
  hashing and Package/Registry handoff evidence.

## Related specs and external references

- `.trellis/spec/agent_world/backend/index.md:570-592` — acceptance identity
  must include explicit validator executable revision while transport/retry
  remains outside semantic identity.
- `.trellis/spec/guides/foundry-product-alignment.md` — plan/test progress is
  not Direct product completion.
- External references: none; this is an internal static plan review.

## Caveats / Not Found

- This allow approves only the reviewed plan. No code, test, task context,
  product specification, or existing record was modified by this review.
- The acceptance field and regression are planned, not yet implemented or run;
  no real Provider, candidate process, Judge, Registry, E2E, Repair, Expand,
  Consumer/SFT/RL, or training claim is made.
- Per role isolation, `implement.jsonl` and `check.jsonl` were not read.
- No additional defect, future child, schema, owner, or scope expansion was
  introduced during this final revision review.

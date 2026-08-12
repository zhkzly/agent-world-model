# Research: complete Direct R9-C3 cross-layer review

- Query: Fresh independent review of the entire written Direct R9-C3 plan,
  correcting the prior C3 review's wheel-only scope.
- Scope: internal
- Date: 2026-08-11
- Reviewer: independent read-only `trellis-research`, model `gpt-5.6-terra`

## Decision

Decision: allow

- Plan digest: `dec00ffe10140fb81258182347f658a0370dfdb5155f8344ed8fbc0b8751e372`.
- Parent digest: `d39632e88ff13a1b447e490beb379540fe22dcb839690cfdbf6138f114d1efe5`.
- Plan revision: Direct R9-C3. This is a scope-complete re-review of the same
  digest, not another plan revision.
- Scope classification: larger Direct vertical slice across Controller,
  Designer, Builder, Judge, Registry and Observe.
- Trigger: the prior C3 allow covered only the trusted-wheel delta. No real
  failure, Observe scene or Diagnosis Record applies.

The reviewer independently recomputed the declared five-file aggregate and
obtained the exact plan digest. This record explicitly authorizes
implementation and check of the complete written R9-C3 plan at those bytes.

## Product Target And Impact Chain

The target remains natural-language `EnvironmentRequest` -> evidence-grounded
executable environment -> isolated candidate execution -> independent Judge ->
immutable Registry `EnvironmentPackage` -> safe read-only Observe. Direct is
the required seed path; Repair, Expand and Consumer consume frozen handoffs in
later children and are not implemented by this child.

```text
Research/evidence -> compiled DesignGraph
  -> BuildPlan + CandidateBuild / sibling VerifierBundle
  -> trusted install + isolated Integration
  -> independent Judge
  -> framework Package/ReleaseKernel
  -> Registry cold-read and atomic receipt
  -> Observe
```

## Complete Boundary Review

- The two fixed domain graphs, one `NodeSpec`/`EdgeSpec` vocabulary and
  deterministic runner are product-specific and bounded. They do not create a
  generic scheduler, DSL, plugin system, callback bus or compatibility path.
- `GraphRunner` owns each transaction: resolve committed inputs, execute one
  operation, framework-compile/validate it, commit `ArtifactEnvelope`, then
  terminal `WorkRecord`. Raw model or Agent output cannot cross an edge.
- Semantic revision binds the effective model-facing projection/output shape,
  prompt identity, route and exact Agent Skill digest without persisting prompt
  bodies, credentials or provider payloads. Direct LLM has no Skill/tool/
  workspace; each Agent work mounts exactly one named product Skill.
- Curriculum is the sole semantic producer of finite ordered difficulty and
  framework the sole compiler. TaskRequirement, Materializer exact echo,
  Integration, Judge, package and future consumers share the same digest.
- CandidateBuild and VerifierIntent are siblings. CandidateBuild receives no
  verifier/Judge/sealed/release material; Judge alone joins passed Integration
  with the compiled VerifierBundle.
- Framework alone admits dependencies and uses the fixed C3 offline
  `--no-index --find-links` wheel boundary. Candidate code gains no source,
  build, index, network or release authority.
- Integration non-pass records evidence and leaves Judge/Package/Registry
  `not_run`. Findings are evidence-bound and route-free. Judge evaluates in
  fresh untrusted processes but cannot route or release.
- Controller is the sole Package/ReleaseKernel. Registry cold-parses,
  recompiles and rehashes the complete physical closure before atomic publish.
  Observe rechecks durable Work/receipt/package facts and remains read-only.

Repair compatibility is frozen through immutable Work/dependency/Finding
provenance and `invalidated_by=null`; Expand compatibility is frozen through
empty Direct parent lineage and the reusable complete Design/Candidate path;
Consumer compatibility is frozen through exact package/runtime/difficulty
contracts. None of those later behaviors is pulled into this child.

## Smallest Allowed Checks And Proofs

Deterministic checks must cover graph owner/port/transaction/provenance closure;
exact model projection and singleton Skill identity; candidate/verifier
separation; difficulty compilation/echo/rejection; hostile and valid-wheel
installation; Integration fail-stop; independent verifier-consuming Judge;
route-free Findings; package/Registry/Observe cold-read and tamper rejection;
and legacy/generic-framework firewalls.

True-boundary proofs run in this order:

1. one real Direct LLM node;
2. one real singleton-Skill Codex SDK preflight;
3. real CandidateBuild, offline install and isolated Integration, including two
   admitted difficulty selections and one rejected invalid selection;
4. one fresh non-fixture Direct request through Registry cold-read and Observe.

Any real terminal is followed by Observe. A failure starts
Observe -> debugging -> Diagnosis Record -> revised repair plan -> fresh critic
before another implementation or proof.

## Non-Claims And Next Gate

This allow does not claim implementation, provider availability, live release,
Repair, Expand/Campaign, parent reuse, Consumer/SFT/RL or complete-v1. It
authorizes only the exact written Direct implementation/check scope; changed
plan bytes, trust boundaries or real scenes expire it.

Next permitted gate: add this scope-complete allow and the matching parent
scope-complete allow to implementation/check context, dispatch Terra-pinned
Direct implementation, then deterministic check and the ordered true-boundary
proofs.

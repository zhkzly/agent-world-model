# Research: cross-layer review baddd746

- Query: Fresh independent cross-layer review of Direct R9-C1 child plan digest `baddd746193dc09758ad338543f41c0f3ae827addaba135c667f238ab27c8950`, against the current complete-v1 parent allow, clean baseline, canonical product contract, execution map, relevant specs, current product code/tests, historical R9-C1 evidence, and later Repair/Expand/Consumer consumers.
- Scope: internal
- Date: 2026-08-11

## Decision

Decision: block

- Plan digest: `baddd746193dc09758ad338543f41c0f3ae827addaba135c667f238ab27c8950`.
- Plan revision: R9-C1, fresh child-specific review; revision count 1 for this digest lineage.
- Parent allow: `bdb327dae0d0d6da59a9bf73224f1503363b4f44991a199c396b564df722ab2b`, reviewed as current development-dispatch evidence only.
- Scope classification: larger Direct vertical slice across Controller, Designer, Builder, Judge, Registry, and Observe, with frozen handoffs to later Repair, Expand, and Consumer. No failed real proof or Observe scene is being repaired.
- Digest check: hashing the five declared raw inputs in the required order reproduced the stated digest. The historical R9-C1 `afad1826...` allow was read only as non-current evidence and cannot authorize this digest.

## Product Target And Boundary

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. Expand must later produce independently judged children through the same Design/Build/Judge/Release path; Consumer may later use only exact released packages through an isolated public Episode surface.

The affected trust boundary is the Designer-owned task contract flowing through Builder's untrusted Materializer and Runtime into framework-owned Integration/Judge, portable package metadata, and Consumer's private materialization-to-reset handoff. This is a semantic producer/consumer contract, not a field-shape detail.

## Findings

### Blocker: Difficulty Contract Has No Producer

The plan requires a closed, exact difficulty value at several downstream boundaries but does not define a producer for it.

- `CurriculumPlanSourceDraft` supplies only `difficulty_dimensions: 1..6 str`; it contains neither levels nor a typed domain for each dimension: `node-contracts.md:387-395`.
- `MaterializationRequest` nevertheless requires `difficulty: closed bounded mapping from compiled difficulty schema`, and `MaterializerResult` must exact-echo it: `node-contracts.md:617-633`.
- The canonical source requires `TaskRequirement` to include both difficulty dimensions **and levels**, and requires Judge to verify an exact dimensions/levels match: `docs/agent-world-environment-generation.zh.md:657-668`, `:697-703`.
- The Direct plan promises unknown-difficulty Integration/Judge checks and a later Consumer accepts `EpisodeRequest.difficulty`; neither can determine admissible keys, values, bounds, or canonical representation from the proposed R9 artifacts: `implement.md:167-191`; `.trellis/tasks/08-11-foundry-consumer-sft-rl/design.md:20-49`.

This violates the plan's node-first requirement: `curriculum_plan` has no complete closed output sufficient for the later `task_requirement` compiler, `BuildPlanInput.materializer_contract`, CandidateBuild, Integration, Judge, package `tasks/curriculum.json`, Expand's complete-child Design, or Consumer. A permissive `dict`, a fixed example difficulty, or candidate-selected values would incorrectly transfer framework-owned task/evaluator authority to the candidate and would recreate the prohibited fixed-task success route.

### Reviewed Compatible Boundaries

- The two static graphs, one NodeSpec/EdgeSpec runner, fixed loops, no generic graph platform, and no dormant Expand control loop are a proportionate Direct scope: `design.md:34-57`, `:99-141`.
- Owner and execution-kind separation is coherent: Designer owns Design plus verifier intent; Builder owns BuildPlan/CandidateBuild/Integration; Judge is evidence-only; Controller has the sole Package/ReleaseKernel decision; Registry cold-reads and atomically publishes: `node-contracts.md:57-93`, `design.md:301-341`.
- CandidateBuild/VerifierIntent are correctly sibling branches: CandidateBuild has no verifier, sealed, Judge, or release input; Integration depends only on Design and Candidate; Judge joins exact passed Integration with VerifierBundle: `design.md:82-98`, `node-contracts.md:466-499`.
- Artifact/Work provenance, route-free Findings, Integration fail-stop, registry re-verification, and read-only Observe are correctly assigned as framework responsibilities. The current baseline instead remains a sequential monolith where Integration reaches Judge without a pass guard and CandidateBuild reads `.foundry-challenge.json`: `agent_world/foundry.py:150-172`, `:72-91`; the written plan correctly requires replacement rather than a parallel path.
- The offline installer is concrete and locally valid for the pinned `uv 0.11.29`: its required flags are present in the installed command help, and the plan retains fail-closed no-build/no-network/no-root-install behavior: `node-contracts.md:548-610`.
- The five-operation Runtime, private snapshot, independent Judge, sole ReleaseKernel, Registry cold-read, and safe Observe direction align with the canonical contract: `docs/agent-world-environment-generation.zh.md:715-733`, `:967-1025`; `node-contracts.md:639-685`.

## Required Plan Revision

Revise the plan only, then obtain a new aggregate digest and fresh critic review. The smallest coherent change is:

1. Add a framework-owned, closed difficulty contract to the `curriculum_plan` output and its compiler input: each declared dimension needs a stable name, finite allowed levels/value schema, bounds, and canonical ordering; reject duplicate/unknown dimensions and out-of-domain values.
2. Make `task_requirement` consume the frozen per-family difficulty contract and commit the exact `TaskRequirement` difficulty schema that the Materializer, Integration, Judge, package `tasks/curriculum.json`, and future `EpisodeRequest` all re-use. State whether every declared dimension is required and define the canonical mapping/echo representation.
3. Add the missing Model Contract Card details: the curriculum model-visible projection/output, compiler validation and local correction packet; TaskRequirement's explicit dependency on the compiled difficulty contract; the exact ArtifactRef/WorkRecord dependencies and semantic-revision invalidation edge.
4. Add deterministic regressions for valid and invalid levels, missing/extra/reordered difficulty keys, exact Materializer echo, paired-difficulty semantic/initial-state change, package cold-read, and Consumer compatibility. The smallest true-boundary proof must materialize at least two admitted difficulty values from a fresh candidate and show the framework, not candidate text, validates and carries them privately into `reset`.

Forbidden shortcut: do not use an unconstrained mapping, a fixed difficulty fixture, candidate-defined level set, or a Consumer-only schema. Do not implement Repair, Expand, Consumer, a second ReleaseKernel, or a generic graph framework to resolve this Direct producer omission.

## Impact Chain And Compatibility

```text
curriculum_plan (missing levels/schema)
  -> task_requirement / EnvironmentDesign
  -> BuildPlan + CandidateBuild Materializer contract
  -> Integration exact echo and unknown-difficulty checks
  -> Judge task_materialization / reachability
  -> Package curriculum/protocol + Registry cold-read
  -> Repair provenance, Expand complete child Design, Consumer EpisodeRequest
```

Repair can consume the proposed immutable WorkRecord/Finding closures once the producer is defined; it must still re-derive owner and invalidation. Expand can pass a SemanticDelta into the same DesignGraph only when the rebuilt Design contains the same complete difficulty contract. Consumer can keep `initial_config` private only when its selected `difficulty` has the exact framework-owned schema carried through the released package. These are compatibility requirements, not authorization to implement later children now.

## Smallest Tests And Proof

- Deterministic: graph-port/dependency closure from CurriculumPlan through TaskRequirement and Materializer; strict difficulty schema/echo rejection; candidate/verifier separation; Integration failure leaves Judge/Package/Registry `not_run`; package/Registry/Observe cold-read safety.
- True boundary after the revised plan receives allow: real CandidateBuild creates a Materializer and Runtime; framework materializes two valid unknown seed/actor/difficulty cases, rejects an invalid difficulty before release, performs the exact offline Integration, then proceeds through the planned increasing-cost Direct proof sequence.

## Non-Claims And Next Permitted Gate

This block makes no claim that the baseline fails a live proof, that the proposed graph is otherwise invalid, or that Direct, automatic Repair, Expand, parent reuse, Consumer/SFT/RL, provider capability, or product completion has been proved. No code, manifest, plan, spec, or product state was changed by this review.

Next permitted gate: the plan writer updates the five planning inputs to close the difficulty producer/consumer contract, recomputes the aggregate digest, links this feedback, and dispatches a fresh independent cross-layer review. Implementation and check dispatch remain forbidden for this digest.

## Caveats / Not Found

- The historical R9-C1 allow did not identify this omission; it is stale and non-current evidence by the task's own lineage rule.
- The current clean product baseline has no `EnvironmentDesign`/Materializer difficulty implementation to supply the missing semantics; that confirms the contract cannot be inferred from existing code.

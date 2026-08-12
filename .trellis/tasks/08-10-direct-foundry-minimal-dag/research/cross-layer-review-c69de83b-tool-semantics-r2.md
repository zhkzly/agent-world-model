# Research: cross-layer review — ToolSemantics R2 final closure

- Query: Final fresh independent read-only review of R2 plan `direct-tool-semantics-closure-plan-r2.md` against the four gaps blocked in R1, with no broader project re-audit.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `c69de83b54e3f849e39653b8227b3772314411fe5dc2141abb3d558eaa1c7a26` (recomputed from the complete R2 file).
- Plan revision: R2, final permitted revision after predecessor `8dbbac0d` and R1 block `573b78e1`.
- Scope classification: coordinated Direct DesignGraph-to-CandidateGraph/Judge/package contract correction, confined to the existing ToolSemantics transaction and declared consumers.
- Trigger and evidence: the relevant real Direct terminal remains `run_b644e7e8c9134f099351a80ebd43ded7`, rejected at `tool_semantics_invalid` before Candidate, Judge, Package, or Registry. This is not a retry authorization.

## Findings

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This plan advances the previously missing semantic handoff on the Direct path; it does not claim the Direct product path is now proven.

R2 closes all four R1 blocking gaps.

1. **Closed snapshot projection:** `SemanticBinding` now fixes every argument/result/pre-state/post-state path, JSON value category, required path set, and lifecycle `reset -> snapshot(pre) -> invoke -> result -> snapshot(post) -> close`. Paths are framework-derived from frozen tool surface facts. CandidateBuild receives only this fixed schema/required-path contract. Private snapshot values are excluded from model prompts, package metadata, Observe, SFT, and public Episode APIs.
2. **Narrow evaluator:** the framework-owned Judge evaluator has only the frozen selected `ToolDraft`, a framework-created trace, and frozen assurance IDs. It has closed binding, predicate, and effect semantics; it returns only rule IDs, safe code, and commitments. It has no model invocation, mutation, routing, repair, or release authority.
3. **Deterministic coverage:** Modeling Gate derives the lowest applicable precondition and transition from the frozen public step and fails closed when either cannot be observed. Integration and Judge run separate traces, and Judge checks exactly those frozen IDs and digest. This replaces generic verifier variants with a compiler-owned, reproducible assurance requirement.
4. **Errors/reject without ABI drift:** R2 explicitly retains `errors` and `reject` in compiled/package semantics but excludes them from the Direct-v1 successful-invoke dynamic-assurance claim. The fidelity record states that limit. It adds no error response/exception envelope and leaves the five-operation, success-only Runtime ABI unchanged.

The compatible impact chain is:

`WorldArchitecture + evidence -> ToolSemantics source/compiled ToolDraft -> WorldRules and TaskRequirement separation -> Modeling Gate/DesignContract -> existing Builder and Verifier projections -> isolated Integration -> independent Judge local_tool_semantics gate -> Rule IR/package -> Registry cold-read -> safe Observe`.

Designer/framework remains the sole semantic compiler and artifact owner; Builder implements the frozen private projection but receives no sealed/Judge authority; Judge owns only its gate; ReleaseKernel and Registry keep their existing distinct release/cold-read roles. Future Expand may compare the retained compiled local-rule value/digest only and must still rebuild a complete child Design. Consumer remains package-only, receives no snapshot values, and has no new public Runtime/Consumer ABI.

## Smallest Allowed Implementation and Proof

Implement only the R2 additions together with the already-inherited R1 producer/consumer closure: closed bindings/rules, private snapshot projection validation, `LocalRuleAssurancePlan`, the narrow evaluator/gate, Rule IR and Registry closure, fidelity non-claim, the existing Runtime Skill update, and the three named focused test files. Do not add a graph, node, model turn, Rule engine, state-schema turn, repair route, Expand/Consumer code, or public Runtime response.

Deterministic checks must prove the exact path/type/lifecycle contract; closed evaluator operations and fail-closed cases; deterministic selected rule IDs; separate Integration/Judge traces; safe evidence with no private values; Rule IR/assurance/fidelity tamper rejection in Registry; and all inherited R1 producer, separation, closure, and cold-read checks.

Only after those checks and the independent whole-diff check, the permitted true-boundary proof sequence is: one fresh ToolSemantics shard; one CandidateBuild/offline-install Integration followed by a separate Judge trace for the frozen precondition and transition; then one fresh Direct-to-Registry run with Observe read after each terminal.

## Non-claims and Next Permitted Gate

This allow does not claim a passing model shard, CandidateBuild, Integration, Judge, Registry publication, or Direct E2E; it does not dynamically assure error/reject behavior; and it does not authorize Retry, model switching, public ABI expansion, generic rules, Repair, Expand, or Consumer implementation.

This allow expires if the plan digest, affected private snapshot/assurance boundary, or relevant real Observe scene changes. The next permitted gate is implementation of this exact R2 plan, followed by the independent check and the stated proofs. Any new failed real terminal begins a new diagnosis lineage.

## Files Found

- `research/cross-layer-review-8dbbac0d-tool-semantics.md` — predecessor producer/consumer closure block.
- `research/direct-tool-semantics-closure-plan-r1.md` — inherited semantic handoff plan.
- `research/cross-layer-review-573b78e1-tool-semantics-r1.md` — four precise R2 closure requirements.
- `research/direct-tool-semantics-closure-plan-r2.md` — reviewed final plan and verified digest.
- `config/.agent-world-runs/runs/run_b644e7e8c9134f099351a80ebd43ded7/run.json` — rejected real terminal evidence.
- `agent_world/{contracts.py,design.py,candidate.py,runtime.py,observe.py}` — current thin ToolDraft, private snapshot envelope, existing package Rule IR, Judge boundary, and safe Observe projection.
- `node-contracts.md`, `docs/agent-world-environment-generation.zh.md`, and `docs/direct-rewrite-execution-map.zh.md` — binding ToolSemantics, private snapshot, Consumer, and authority contracts.

## Caveats / Not Found

- This final review is intentionally limited to the four R1 gaps and is not a full-project audit.
- No code, plan, task manifest, or external state was changed; only this decision record was written.

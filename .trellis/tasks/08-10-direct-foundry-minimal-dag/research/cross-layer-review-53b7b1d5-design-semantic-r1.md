# Research: cross-layer review — Design semantic closure r1

- Query: Fresh independent read-only review of revision 1, restricted to closure of the predecessor's Design-to-Candidate semantic blockers.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `53b7b1d5072999e9a14d865e6ee495460b9872f4ac0cdd3f0771026ceab1ab84` (verified from the complete submitted plan)
- Plan revision: 1
- Scope classification: coordinated cross-node repair across Designer, Builder, Judge, package, and Registry
- Revision count: 1 of at most 2
- Trigger / evidence: static lossy-consumer Diagnosis Record `diagnosis-design-semantic-consumer-gap.md`; no new real Observe scene exists or is needed.

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
This review authorizes neither implementation nor real execution.

## Findings

### Predecessor blockers now materially closed

- The plan now derives one framework-owned `AssuranceRecipe` for every frozen
  `(task_family_index, tool_index)` and gives it a disclosed materialization,
  action, deterministic seed, and Rule-IR check path
  ([direct-design-semantic-closure-plan.md:187-211](direct-design-semantic-closure-plan.md:187)).
  Integration has no Verifier input and covers every baseline recipe; Judge
  reruns baseline and compiled private cases, then requires terminal trusted
  success and `+1` reward ([direct-design-semantic-closure-plan.md:223-237](direct-design-semantic-closure-plan.md:223)).
- `ExecutableTaskContract` now explicitly includes closed goal/config schemas,
  exact RFC-6901 identity bindings, framework instruction rendering, task Rule
  IR, RewardSpec, TerminationSpec, and verification requirements
  ([direct-design-semantic-closure-plan.md:156-182](direct-design-semantic-closure-plan.md:156)).
  This matches the task card's framework-owned evaluator path
  ([node-contracts.md:708-727](../node-contracts.md:708)) and canonical
  materialization/reachability boundary.
- The revised plan fixes the previously ambiguous representation: an empty
  graph `shared_tools` binding exists only for the statically declared
  zero-group port, whereas every ToolSemantics model projection has the closed
  `shared_contract` key with a compiled contract or JSON `null`
  ([direct-design-semantic-closure-plan.md:92-130](direct-design-semantic-closure-plan.md:92)).
  It also aligns the formerly inconsistent Research and Curriculum bounds with
  the active cards ([direct-design-semantic-closure-plan.md:39-58](direct-design-semantic-closure-plan.md:39),
  [direct-design-semantic-closure-plan.md:142-148](direct-design-semantic-closure-plan.md:142)).
- It keeps the scope bounded: the two existing graphs, existing roles, one
  Builder/Judge/Registry, no generic rule/test/graph/control platform, and no
  Repair/Expand/Consumer implementation.

### Remaining blocker — the fixed metadata map still drops framework-derived task semantics

`ExecutableTaskContract` makes `RewardSpec`, `TerminationSpec`, and
`VerificationRequirements` required semantics ([direct-design-semantic-closure-plan.md:171-176](direct-design-semantic-closure-plan.md:171)).
But the declared physical metadata map names task Rule IR, schemas, identity
bindings, instruction revision, recipe commitments, and gate coverage, while
omitting all three values and their digests
([direct-design-semantic-closure-plan.md:267-285](direct-design-semantic-closure-plan.md:267)).
The accompanying “exact-compares every value/digest above” therefore gives
Registry no named package field or cold-read equality rule for those semantics.

This is a direct remaining instance of the predecessor's required
semantic-field/metadata/Registry closure, not a request for a new package
format: the canonical package already reserves `world/rule_ir.json` for the
framework-owned portable evaluator spec and `tasks/materializer_protocol.json`
for task protocol ([docs/agent-world-environment-generation.zh.md:971-997](../../../../../docs/agent-world-environment-generation.zh.md:971)).
Without the exact placement and cold comparison, a package can retain task
rules yet silently omit or alter the failure precedence, termination condition,
or required coverage used to claim `task_executed`.

### Required revision, still minimal

Revise only the written plan to:

1. Name the exact closed package fields and digests for `RewardSpec`,
   `TerminationSpec`, and `VerificationRequirements` (for example, the first
   two in the portable task Rule-IR evaluator projection and the last in the
   task protocol/assurance projection), state which immutable Design Artifact
   each equals, and require Registry cold reparse/equality for each. Do not
   introduce another metadata file, evaluator, Registry authority, or runtime
   control object.
2. Make the private Verifier-case handoff mechanically unambiguous for the new
   multi-family input: an in-memory case must bind its public commitment ID and
   the selected family/tool `AssuranceRecipe` digest before it varies only the
   permitted seed/difficulty/key/argument value. Require Judge to reject a
   missing or mismatched binding. This is a compact record/validation rule,
   not a generic test language or persisted sealed data.
3. Add deterministic mutation tests for all three task semantics and the
   private-case recipe binding, alongside the already-planned package/Registry
   omission tests. The Prompt must enumerate the active card's remaining
   changed cardinalities (including TaskRequirement's `public_goal_fields:
   1..12`) wherever the implementation replaces the current shape, so no
   compiler-only cardinality becomes an undisclosed validator.

## Impact chain and ownership

```text
TaskRequirement source -> ExecutableTaskContract -> EnvironmentDesign
-> BuildPlan/CandidateBuild -> Integration (baseline recipes only)
-> VerifierIntent -> private same-run cases -> Judge
-> rule/task/protocol/assurance package metadata -> Registry cold read -> Observe
```

Designer owns compilation of source semantics and `EnvironmentDesign`; Builder
owns candidate and verifier-independent Integration; Judge owns fresh
candidate-process execution and evidence; Controller owns the sole package
release decision; Registry only cold-revalidates and publishes. CandidateBuild
remains unable to consume verifier, sealed, Judge, or release input. Future
Expand/Consumer consume only the released package handoff and remain untouched.

## Smallest tests and proof after a revised allow

- Deterministic: per-family/tool recipe coverage; verifier family/tool/argument
  rejection; private case -> commitment/recipe digest mismatch rejection;
  task rule/identity/reward/termination/verification metadata mutation rejection
  by package and Registry cold read; and no leaked private values.
- True boundary: only after an allowed whole-diff review, run the plan's fresh
  Design -> CandidateBuild -> all-family Integration -> independent Judge ->
  Registry proof sequence, then read Observe after its terminal.

## Non-claims

- The revised design text does not prove a live Direct release, real-world
  fidelity, full shared concurrency/compensation behavior, global/unselected
  rule execution, Repair, Expand, or Consumer/SFT/RL.
- `task_executed` may not be claimed until the Judge has the exact passed
  all-family/all-tool gate evidence; static schema or package closure alone is
  insufficient.
- No model/network/live calls, code/test/plan/JSONL/spec edits, or git actions
  occurred in this review.

## Next permitted gate

Revise only `direct-design-semantic-closure-plan.md` to address the three
bounded points above, recompute its digest, and submit the one remaining fresh
independent critic review. Do not dispatch implementation or proof while this
record is `block`.

## Files found

- `docs/agent-world-environment-generation.zh.md` — canonical task,
  Integration/Judge, package, Registry, and release contracts.
- `docs/direct-rewrite-execution-map.zh.md` — two-graph authority and
  CandidateBuild/Verifier separation.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` —
  executable task, verifier, materializer, evaluator, and Registry handoffs.
- `research/diagnosis-design-semantic-consumer-gap.md` — persisted static
  diagnosis for this repair lineage.
- `research/cross-layer-review-7731e2cc-design-semantic-closure.md` — exact
  predecessor block criteria.
- `research/direct-design-semantic-closure-plan.md` — reviewed revision 1.
- `agent_world/contracts.py`, `agent_world/candidate.py`, `agent_world/runtime.py`,
  and `agent_world/graph.py` — current first-only projections, verifier case,
  evaluator, and nonempty-port implementation evidence.

## Related specs

- `.trellis/spec/guides/foundry-product-alignment.md` — product-target and
  non-claim discipline.

## Caveats / Not Found

- No external references were used; network/model/live execution was
  prohibited.
- The missing metadata closure is a plan-level issue. This review makes no
  implementation judgment and did not inspect or modify task JSONL manifests.

# Research: cross-layer review — ToolSemantics R1

- Query: Fresh independent read-only review of `direct-tool-semantics-closure-plan-r1.md` against the Direct producer-to-Judge/package closure and frozen Repair/Expand/Consumer handoffs.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `573b78e1dc39e366fb583b8e6ba5584b12f63240995c92b60f1dd5b1b091ffa2`.
- Plan revision: R1, addressing predecessor block `8dbbac0d`; revision count 1. One final R2 plan revision is permitted for this diagnosis lineage.
- Scope classification: coordinated Direct DesignGraph -> CandidateGraph contract correction. No Repair, Expand, Consumer, third graph, generic rule platform, or automated routing is authorized.
- Trigger/evidence: the real Direct run `run_b644e7e8c9134f099351a80ebd43ded7` ended `rejected/tool_semantics_invalid`; Observe contains no Candidate, Judge, package, or Registry result. The Diagnosis and predecessor block correctly establish the producer defect, not a retry/provider failure.

## Product target and impact chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. Future Expand must re-enter the same Design/Build/Judge/Release path from exact parent/evidence facts; Consumer must use only an exact released package through its public/private Episode split.

R1 correctly advances the necessary chain:

`WorldArchitecture + evidence -> ToolSemantics RuleDraft producer -> ToolDraft -> WorldRules / TaskRequirement separation -> ModelingGate -> Builder + Verifier projection -> Judge -> Rule IR/package -> Registry cold-read -> later Expand semantic comparison / Consumer package read`.

It correctly makes framework-owned bindings and compiled rules available to Builder, Verifier, Judge, package, and Registry; preserves WorldRules as additional cross-tool/entity semantics; preserves TaskRequirement as reset/success/failure/terminal owner; and leaves later children unimplemented. This is the required smallest *handoff* scope, not overdesign.

## Blocking executable gap — exact R2 difference

R1 must revise only the state-binding/evaluator contract before implementation:

1. Keep the proposed per-tool `RuleDraft` closure, framework-derived binding catalog, package Rule IR, digest, and existing consumer list. But make the catalog's `pre_state`/`post_state` entries an explicit **closed snapshot projection contract**, not an inference from a result-field name. For every derived state binding, R2 must state the exact required snapshot path, accepted JSON value category, absence rule, and lifecycle: `reset -> pre-snapshot -> invoke -> result -> post-snapshot`. `state.tools[tool_name][result_field]` is feasible as that one closed private projection; it is not a new WorldArchitecture turn or a package-private-state payload. CandidateBuild receives only its schema/required paths, while package and Observe retain only rules/digests, never snapshot values.
2. Define the one narrow, framework-owned `local_tool_semantics` Judge evaluator completely: its inputs are the frozen `ToolDraft`, one framework-created invocation trace, result, and the two private snapshots; it resolves bindings and returns only passed/failed rule IDs/code/evidence commitment. It neither executes model prose, routes, repairs, mutates the candidate, nor emits a release decision.
3. Define a deterministic coverage rule for that one trace. The current verifier generator only makes generic scalar variants (`agent_world/candidate.py:1121-1131`) and the current Judge only receives `PublicStep` plus those cases (`agent_world/runtime.py:364-418`); neither can presently guarantee the R1 requirement to exercise a transition and a precondition/error. R2 must specify the compiler-derived trace recipe and fail closed at Design/Judge when the declared rule subset cannot be observed by that recipe. It must identify which predicate/effect is asserted and whether an error rule is optional when no observable error outcome exists.
4. Reconcile `errors`/`reject` with the fixed ABI instead of silently treating them as passed. The ABI currently admits only `invoke -> {status: "ok", result: ...}` (`node-contracts.md:663-668`; `agent_world/runtime.py:212-217`). R2 must either (a) define the closed, observable successful-result/snapshot representation through which an error/reject rule is checked, or (b) restrict this R1 evaluator to transitions/preconditions and defer observable error-result semantics with an explicit non-claim. It must not broaden the Runtime public ABI, because that changes the frozen Consumer handoff.

These are a specification of one evaluator/trace projection, not a general Rule engine, arbitrary expression language, new state-schema model turn, new node, verifier authority, or automatic Repair.

## Owner and consumer compatibility

- Designer/its compiler remains the only source-semantics producer and binding/rule validator; the model cannot choose surface names, state paths, Gate status, or release facts.
- Builder consumes the frozen implementation contract and implements the required private snapshot projection; it still receives no Verifier/Judge/sealed data.
- Judge alone runs the narrow evaluator against an isolated candidate trace and owns its gate; VerifierIntent remains advisory and sealed-case compilation remains framework-owned.
- ReleaseKernel packages canonical rules/digests; Registry cold-parses/recomputes them and may reject, but cannot interpret semantics or become a second Judge.
- Repair remains route-free for this task. Expand may later compare the retained compiled local-rule value/digest as ToolSemantics genotype and must compile a complete child Design. Consumer stays package-only; it receives no snapshot values or new runtime ABI.

## Required deterministic checks and proof

- Assert the R2 snapshot-path/type/absence contract and reject a result-field-derived binding without its required pre/post path.
- Assert the narrow evaluator fails on a mismatched pre/result/post value, missing path, unobservable declared predicate/effect, and unsupported error/reject representation; assert it passes a compiler-derived transition and a defined precondition/error case.
- Retain R1's producer, WorldRules/TaskRequirement separation, Builder/Verifier projection, package Rule IR, and Registry tamper/cold-read tests.
- Only after deterministic checks: run one fresh `tool_semantics` shard; then one isolated CandidateBuild/Judge trace that proves the defined evaluator coverage; then one fresh full Direct-to-Registry run. Read Observe after each terminal. None of these proofs is authorized by this block.

## Non-claims and next permitted gate

This review does not authorize implementation, a retry, a model switch, Runtime public-ABI expansion, generic rules/state schemas, a third graph, automatic Repair, current Expand, or current Consumer. It does not claim Candidate, Judge, Registry, or E2E success.

Next permitted gate: submit an R2 plan with a new complete digest that makes only the four differences above and cites this record. If that R2 is coherent, it may be independently reviewed; do not dispatch implementation for R1.

## Files found

- `agent_world/design.py:860-912` — current ToolSemantics accepts an architecture echo and discards its only result sample.
- `agent_world/contracts.py:460-464` — current ToolDraft has surface fields only.
- `agent_world/candidate.py:141-250,1121-1166,1841-1852,2246-2272` — current Builder contract, generic verifier variants/Judge invocation, Rule IR package, and cold-read metadata boundary.
- `agent_world/runtime.py:212-223,364-418` — fixed successful invoke/snapshot validation and existing Judge gates.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:287-308,383-417,663-723,729-785` — binding RuleDraft/ToolSemantics, WorldRules separation, fixed ABI, evaluator chain, and package closure.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/cross-layer-review-8dbbac0d-tool-semantics.md` — predecessor block and required producer/consumer closure.
- `.trellis/tasks/08-11-foundry-{bounded-repair,expand-multiparent,consumer-sft-rl}/` — unchanged future handoffs.
- `docs/agent-world-environment-generation.zh.md` and `docs/direct-rewrite-execution-map.zh.md:71-100,164-180` — canonical authority/consumer boundaries.
- `config/.agent-world-runs/runs/run_b644e7e8c9134f099351a80ebd43ded7/run.json` — actual rejected Observe terminal.

## Caveats / Not Found

- No external reference was needed.
- The block is only about the missing closed state-observation and trace-coverage semantics. It does not reopen R1's otherwise necessary producer, consumer, package, or future-genotype closure.

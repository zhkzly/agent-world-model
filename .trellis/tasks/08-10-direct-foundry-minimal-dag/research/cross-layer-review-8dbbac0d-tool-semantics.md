# Research: cross-layer review — ToolSemantics contract

- Query: Independently review diagnosis `diagnosis-direct-e2e-tool-semantics-contract.md` and exact plan `direct-tool-semantics-contract-plan.md` (digest `8dbbac0d79e7f96f08421261971eee69aae2bcaff59a371c16f75e9983c41a4b`) against the Direct, Parent, Repair, Expand, and Consumer handoffs.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `8dbbac0d79e7f96f08421261971eee69aae2bcaff59a371c16f75e9983c41a4b`
- Plan revision: initial revision submitted for this diagnosis; revision count 0 of at most 2 follow-up revisions.
- Scope classification: coordinated cross-node contract correction, limited to the Direct DesignGraph and its already-declared consumers. Repair, Expand, and Consumer must remain unimplemented and compatible rather than being pulled into this repair.
- Trigger: a failed real Direct run changes no product truth, but exposed a hidden model-output constraint on a semantic-node boundary.

## Product target and evidence

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. Expand must later take exact released parents plus evidence through the same Design/Build/Judge/Release path; Consumer must later consume exact released packages through isolated public Episodes without release or environment authority.

The actual Observe data for `run_b644e7e8c9134f099351a80ebd43ded7` supports the diagnosis. It records a real `gpt-5.6-luna` `tool_semantics[manage_parts]` attempt, one framework correction, the same `$.arguments[3]` bounded-text violation on the second attempt, a blocking Designer Finding, and terminal `rejected` with no release (`config/.agent-world-runs/runs/run_b644e7e8c9134f099351a80ebd43ded7/run.json`, failure artifact `artifacts/d16d444a1118259c0570bb44b4b484f2b9d048e967b47ea6ffe5b4567f1cddcc.json`). No Candidate, Judge, Registry, route, credential, or research failure occurred. The failure is therefore correctly attributed as an undisclosed output contract, not a reason to retry or switch a provider.

## Impact chain and compatibility facts

The current chain is:

`WorldArchitecture tool surface -> tool_semantics -> ToolDraft -> WorldRules / Curriculum / TaskRequirement / ModelingGate -> EnvironmentDesign -> CandidateBuild + VerifierIntent -> Integration -> Judge -> Package -> Registry -> future Expand/Consumer`.

`agent_world/design.py:860-912` accepts a four-key model object, validates that `arguments` and `result_fields` echo the frozen architecture, validates `success_result`, then constructs `ToolDraft` without `success_result`. `contracts.ToolDraft` has only `name`, `description`, `arguments`, and `result_fields` (`agent_world/contracts.py:460-464`). Thus the currently committed ToolSemantics artifact is an echo of the architecture boundary plus a description; it has no retained precondition, transition, postcondition, error, evidence, or fidelity semantics.

The downstream nodes receive the artifact but cannot make it semantically meaningful under the submitted plan:

- `world_rules` receives serialized `ToolDraft`s but compiles only free-form invariant strings (`agent_world/design.py:931-962`).
- `task_requirement` selects the first tool and only checks its frozen argument/result keys (`agent_world/design.py:1110-1168`); it does not consume per-tool transition/error semantics.
- `CandidateBuild` receives the same thin tools projection and its implementation contract derives only the public step's JSON types (`agent_world/candidate.py:141-148`, `698-705`).
- the packaged `rule_ir.json` contains only `DesignContract.invariants`, not tool semantics (`agent_world/candidate.py:1844-1852`); Registry consequently can cold-read a package whose rule digest has no local tool behavior.
- the declared Direct contract instead requires `ToolSemanticsSourceDraft { tool_index, preconditions, transitions (nonempty), postconditions, errors }`, all expressed as compiler-validated `RuleDraft`s (`.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:299-308,383-401`). WorldRules is explicitly restricted to additional cross-tool/entity rules, and TaskRequirement owns reset/success/failure/terminal rules (`node-contracts.md:403-416,473-484`).
- future Expand identifies `ToolSemantics` as genotype and requires an authoritative non-empty semantic delta followed by a complete fresh child Design; future Consumer relies on the resulting exact package/task/rule contracts, not on Builder-authored meanings (`docs/agent-world-environment-generation.zh.md:2.1/15.2`; `.trellis/tasks/08-11-foundry-expand-multiparent/{prd.md,design.md}`; `.trellis/tasks/08-11-foundry-consumer-sft-rl/{prd.md,design.md}`).

Therefore the plan's assertion that every downstream contract can remain unchanged is contradicted by both the current code and the binding task contracts. Making the shape visible would make the failed prompt easier to satisfy, but it would still permit an echo-only ToolDraft to pass Modeling, guide CandidateBuild only by surface types, and be absent from independently checked Rule IR. That is structural validity, not semantically consumable environment behavior.

## Smallest permitted plan revision

Do not add a general Rule engine, a new graph, a new Judge, automatic Repair, or any Expand/Consumer implementation. Revise the plan to make this one Direct handoff a semantic producer and to prove the existing consumers preserve it:

1. In `agent_world/contracts.py` and `agent_world/design.py`, replace the model-facing echo object with the already-declared bounded `ToolSemanticsSourceDraft` fields: `tool_index` (exact frozen echo), `preconditions`, nonempty `transitions`, `postconditions`, and `errors`. Each member must use the declared closed `RuleDraft` fields: `when`, nonempty `effects`, `error_kind`, `rationale`, and `citation_indexes`; `PredicateDraft` and `EffectDraft` use the exact operator/value alternatives in `node-contracts.md:287-305`. The framework, not the model, derives the frozen name, arguments, and result fields from WorldArchitecture.
2. The same narrow compiler must validate catalog references, allowed operators/value categories, exact tool ownership, evidence citation indexes, and preserve the compiled per-tool rules in `ToolDraft` (or a narrowly named immutable child value). This is a compiler for this existing source contract, not a reusable rule framework. If the present WorldArchitecture projection lacks the required semantic catalog, the revised plan must add only the catalog data that these exact fields reference; it may not substitute prose strings or silently treat a no-op/echo as a transition.
3. Update the actual declared consumers in the same revision: `world_rules` must receive the retained local rules solely to reject duplication and add cross-tool rules; `task_requirement` must consume the frozen compiled closure without redefining local transition meaning; `CandidateBuild`/`compile_implementation_contract` must receive the semantic tool contract; the verifier/Judge inputs and package `world/rule_ir.json` must bind the local rules as well as global invariants. The direct graph output-contract revision in `agent_world/graph.py` and focused construction fixtures in `tests/test_direct_release.py` must change with the data contract.
4. The future compatibility claim is limited and testable: a ToolSemantics operator must compare the preserved compiled local-rule portion, not architecture echo fields; Expand still re-enters a complete child Design and Consumer still consumes only released package/task data. No current Campaign or Consumer code is required.

## Smallest tests and proof

- Deterministic Design tests: capture the actual Direct payload; assert all semantic fields and every bound are disclosed; reject absent/empty transitions, a wrong `tool_index`, unresolved catalog/citation refs, invalid predicate/effect operators, and an architecture echo masquerading as semantic output.
- Deterministic consumer-closure tests: prove the compiled local rules survive `ToolDraft -> WorldRules/TaskRequirement/ModelingGate -> CandidateBuild projection -> verifier/Judge input -> package rule IR`, and that the package cold-read/Registry closure rejects a missing or mismatched local-rule digest.
- Deterministic separation tests: WorldRules cannot repeat a local rule; TaskRequirement cannot redefine a tool transition; an Expand-delta comparison changes when a local ToolSemantics rule changes but not when a derived boundary echo is merely reformatted.
- True-boundary proof, after deterministic checks: run one fresh real `tool_semantics` shard through the revised compiler, then a fresh unknown-seed CandidateBuild/isolated Judge proof whose trace exercises one retained transition and one retained error or precondition. Read Observe after each real terminal. A shard pass alone is not Candidate, Judge, Registry, or E2E proof.

## Owner and authority assessment

Designer remains the sole producer of source semantics and its framework compiler remains the sole owner of catalog/rule validation and artifact commit. Builder only consumes the frozen Design; the candidate remains untrusted. Judge independently evaluates candidate behavior and cannot repair, route, or release. Controller retains the ReleaseKernel; Registry only cold-revalidates and publishes; Repair, Expand, Consumer, and Observe gain no authority from this change.

## Non-claims and next permitted gate

This review does not claim that the proposed semantic compiler, CandidateBuild, Judge, package, Registry, Repair, Expand, or Consumer is implemented or proven. It does not require a full Direct E2E rerun before the revised plan is reviewed, and it does not permit retrying the failed run.

The next permitted gate is a plan-only revision that addresses the four numbered requirements above and cites this block record. It must have a new complete digest and receive a fresh independent critic review. Do not dispatch implementation for digest `8dbbac0d79e7f96f08421261971eee69aae2bcaff59a371c16f75e9983c41a4b`.

## Files found

- `AGENTS.md` — product authority, real-failure gate, and product-alignment requirements.
- `docs/agent-world-environment-generation.zh.md` — canonical product and ToolContract/Expand/Consumer contracts.
- `docs/direct-rewrite-execution-map.zh.md` — binding node execution and Direct/child handoff map.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd.md,design.md,implement.md,node-contracts.md}` — Direct task context and declared node contracts.
- `.trellis/tasks/08-11-foundry-complete-v1/{prd.md,design.md,implement.md}` — parent shared-contract and child ordering.
- `.trellis/tasks/08-11-foundry-bounded-repair/{prd.md,design.md,implement.md}` — future Finding/repair consumer boundary.
- `.trellis/tasks/08-11-foundry-expand-multiparent/{prd.md,design.md,implement.md}` — future ToolSemantics delta and fresh child Design boundary.
- `.trellis/tasks/08-11-foundry-consumer-sft-rl/{prd.md,design.md,implement.md}` — exact released package and private Episode consumer boundary.
- `agent_world/{design.py,contracts.py,candidate.py,graph.py}` — current producer, contract, candidate/package, and graph implementation.
- `config/.agent-world-runs/runs/run_b644e7e8c9134f099351a80ebd43ded7/` — real Observe/run evidence.

## Caveats / Not Found

- This is an independent read-only development review; it neither modifies the diagnosis/plan nor authorizes code changes.
- The requested diagnosis/plan are revision-zero materials. A resubmission with the same digest is not progress; at most two revised-plan reviews are permitted for this diagnosis lineage.
- No external references were needed; the canonical source and local run evidence are sufficient.

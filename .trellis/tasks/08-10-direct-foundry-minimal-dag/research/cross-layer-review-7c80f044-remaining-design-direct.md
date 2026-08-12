# Research: cross-layer review — remaining Design Direct contract closure

- Query: Independent read-only cross-layer review of the repair plan for Direct/E2E failure `run_1bec958e41ae4207beb4a7b40149f9c0`.
- Scope: internal; coordinated remaining-Design Direct source/validator closure only.
- Date: 2026-08-12
- Decision: block
- Plan digest verified: `sha256:7c80f044a8bfeaeef59ffbdeb445b646b0abd82de34dccb3a86b6ff5e8dd2af8`
- Plan revision: `remaining-design-direct-contract-closure`, revision 1/2.
- Critic revision count: 1 of the maximum 2 revisions for this diagnosis/plan lineage.

## Product Target

The required product remains: an arbitrary natural-language need becomes an evidence-grounded executable environment; an isolated, independently verified untrusted candidate is then packaged as an immutable Registry `EnvironmentPackage`; Observe exposes only safe facts about that closure. The failed Direct prefix, a static contract check, or a partial suffix is not that product completion.

## Trigger and Evidence

The real Direct run reached Architecture, Evidence, and SharedTool work, then rejected `tool_semantics[register_member]` after its bounded correction. Its safe validation Finding identifies a missing precise RuleDraft object shape at `$.preconditions[0]`. No Tool artifact committed, and no Candidate, Judge, Package, Registry, or released EnvironmentPackage was reached. The persisted Diagnosis Record attributes this to the hidden RuleDraft source contract and also audits unexecuted WorldRules, Curriculum, and TaskRequirement source contracts. This is a valid post-real-failure critic trigger.

## Verified Plan Digest and Scope Judgment

The requested SHA-256 matches the plan bytes. The plan is a coordinated cross-node repair, not a local ToolSemantics-only change: one RuleDraft source grammar is consumed by ToolSemantics, WorldRules, and TaskRequirement; the SharedTool source contract and cold typed contract need the same partition invariant; Curriculum and TaskRequirement have remaining Direct source echoes and unsafe validation paths.

That coordinated scope is the smallest coherent response to the observed hidden RuleDraft contract and the audit of still-unexecuted siblings. It does not add graph nodes, routes, retries, Agents, generic schema machinery, a DSL, or a new persistence/release surface. It must remain limited to the named Design compiler/source cards, their direct tests, and the existing typed contract checks. The current production-Python count is 10,296 lines, so the stated ceiling of 10,320 requires a net increase of at most 24 lines; obsolete echo checks/string duplication must be removed if needed.

## Owner and Trust-Boundary Classification

| Boundary | Owner and allowed responsibility |
| --- | --- |
| Framework / hardcoded control plane | Owns frozen coordinates, exact source grammar, validation, Rule IR, IDs, hashes/digests, size limits, attempts, correction routing, Findings, ModelingGate, Judge, reward, Package, Registry, release, and safe Observe. |
| Direct LLM | Supplies only semantic RuleDraft content, curriculum meanings/scopes, and public-goal selections through the existing five Direct source nodes. It must not own frozen IDs/indexes, hashes, validation, retry policy, routing, Judge, reward, Registry, or release. |
| Tool-enabled Agent | Existing Research/Builder Agent work remains unchanged; this plan must not turn any Design source node into an Agent or add skills/workspace authority to Direct calls. |
| Untrusted candidate process | Remains downstream of a complete typed Design through Candidate build/integration/Judge; it neither validates nor authorizes Design semantics, package publication, or Observe. |

This ownership split agrees with the canonical environment-generation document, the Direct execution map, and the static graph: the five affected source nodes are `direct_llm`, while ModelingGate is framework-owned (`agent_world/graph.py:161-229`).

## RuleDraft and Exact Source-Contract Audit

The proposed common RuleDraft object is otherwise the right minimal closure: the compiler requires the exact Rule object, predicate, and effect keys; closed operators; frozen binding indexes; finite literals or frozen semantic references; literal-null existence/preserve/reject cases; 0..6 predicates; 1..6 effects; 0..8 citations; and rationale text at most 300 (`agent_world/design.py:299-475`). It also correctly keeps WorldRules non-error and citation-free, permits empty invariants, and preserves current TaskRequirement section bounds.

However, the plan calls its declaration "exact" while omitting a real error-name bound: an error RuleDraft currently accepts `[a-z][a-z0-9_]{0,63}` (one through 64 characters), not an unbounded generic "snake name" (`agent_world/design.py:71,442-451`). The shared ADT and its recipient tests must state that exact accepted grammar.

More importantly, the Curriculum card is not exact as written. It calls dimension and level names "snake", but the cold runtime dataclasses accept `[a-z][a-z0-9_-]{0,39}`: a one-through-40-character lower-case identifier that also permits hyphens (`agent_world/contracts.py:249-269`). The live parser supplies those names to these dataclasses after the same 40-character text bound (`agent_world/design.py:1698-1735`). In contrast, the plan is right about the actual field names and cardinalities: `families` is 1..8, `task_family_id` is `_NAME` at 1..64, dimensions are 1..6, and levels per dimension are 2..5 (`agent_world/design.py:1624-1653`; `agent_world/contracts.py:275-285`).

An underscore-only tightening would be a new semantic type-contract change and is outside this declared minimal closure unless explicitly planned, traced, and re-reviewed. The smallest revision is to disclose and test the runtime grammar actually accepted today, rather than silently tightening it.

## Frozen Echo Removal, Shared Partitions, and Typed ABI

The planned source-only removal of `tool_indexes`, ordered `error_policy[].tool_index`, `tool_index`, `shared_contract`, and `task_family_index` is compatible with the compiled downstream ABI if, and only if, framework code injects the frozen values before constructing the same dataclasses and digest payloads. Existing Tool compilation already builds its typed `ToolDraft` from the frozen surface and selected compiled contract, and TaskRequirement already receives the frozen family index in framework code (`agent_world/design.py:1832-1939`). Thus the model loses redundant authority, not a downstream field.

The strict SharedTool change is necessary rather than overdesign. The canonical contract requires atomicity, concurrency, and idempotency domains to partition the frozen ordered member set exactly, and ordered error-policy coordinates to remain framework-bound. Current `SharedToolContract` only checks flattened set coverage and error-policy set coverage, so duplicate/overlap/order/type cases can evade cold typed enforcement (`agent_world/contracts.py:685-707`). The compiler and `SharedToolContract` must reject non-integers before any `set(...)`, require every frozen member exactly once per partition dimension, and bind error policies to the frozen member order. This preserves the dataclass/artifact ABI while deliberately rotating the compiled shared digest.

The proposed localized TypeError/ValueError hardening is also appropriate: check the listed index arrays before `set(...)`, and translate only the named Curriculum typed constructor/schema `ValueError`s to `curriculum_plan_invalid` at the exact family/dimension path. It must not add a blanket exception handler, coercion, or generic validator.

## Impact Chain and Consumer Compatibility

The compatible handoff chain is `frozen Architecture + Evidence` -> `Direct source JSON` -> `framework compiler and typed Design values` -> `ModelingGate` -> `Candidate projection` -> `Package metadata` -> `Registry cold read` -> `safe Observe`.

- ModelingGate consumes the same typed shared contracts, tools, world rules, curriculum, and tasks; its ports do not change (`agent_world/graph.py:213-229`).
- Candidate projections serialize compiled `DesignContract` fields rather than any Direct source echo (`agent_world/candidate.py:304-321,753-763`).
- Package metadata emits typed shared contracts/tools/world-rule IR and typed curriculum fields unchanged (`agent_world/candidate.py:2086-2121`).
- Registry cold-read validation expects those compiled fields and validates the shared digest/typed curriculum shape, not Direct request objects (`agent_world/candidate.py:2490-2600`).
- Observe verifies a complete package/receipt/artifact closure only after publication (`agent_world/observe.py:76-144`).

Accordingly, the plan correctly leaves Candidate, Package, Registry, and Observe code unchanged. What remains unproved is that a revised Direct source contract will produce valid semantic output at the provider boundary and then allow all later Design children, Candidate, Judge, Package, Registry, and Observe to complete in one fresh public run.

## Deterministic Checks Required by the Revision

The revised plan must retain the stated focused/full checks and make these exact ones explicit:

1. All three RuleDraft recipients receive byte-identical shared grammar plus their section-specific constraints, including the 1..64 error-name grammar.
2. Curriculum visible grammar and source card use actual runtime field names, 1..8 families, 1..64 `task_family_id`, 1..6 dimensions, 2..5 levels, and the accepted `[a-z][a-z0-9_-]{0,39}` dimension/level grammar.
3. No Direct source output contains frozen coordinate/shared-contract/digest echoes; compilers inject them and retain compiled `SharedToolContract`, `ToolDraft`, `WorldRuleSet`, `CurriculumPlan`, and `TaskRequirement` ABI.
4. Both compiler and direct `SharedToolContract` construction reject duplicate, overlap, unknown, and non-integer partition members and unordered/misaligned policy coordinates; an exact split succeeds.
5. Rule citations, Curriculum tool/citation indexes, and Task public-goal indexes reject malformed unhashable/non-integer values through typed node errors, never a raw `TypeError`; the narrowly named Curriculum `ValueError` cases become the correct typed error/path.
6. Changed effective Direct source contracts rotate only their semantic identities; node IDs, ports, edges, routes, groups, call count, and two-attempt correction topology remain fixed. Full Design/ModelingGate and package projection tests, full pytest, Ruff, mypy, compileall, firewall, and production-line ceiling must pass.

## True-Boundary Proof and Required Plan Revision

The proposed proof order is sound in principle: first an exact-parent suffix for strict SharedTool then only `tool_semantics[register_member]`, then one fresh public Direct request only if that narrow proof passes. The revision must make the first step explicitly a diagnostic partial-node proof using immutable Architecture/Evidence references from the failed run. It must not resume, adopt, publish, or infer a release from that partial run; Work/Artifact/operation facts and safe Observe are its only permitted evidence. Only the subsequent fresh public request may test natural execution of WorldRules, Curriculum, and TaskRequirement toward a terminal Observe result.

Before any implementation, revise the same plan lineage (revision 2/2) to:

1. replace the inaccurate "snake" claims with the exact current accepted Curriculum grammar and add the omitted 1..64 RuleDraft error-name bound;
2. state the partial-proof non-release/non-resume boundary above; and
3. keep all other scope, ownership, graph, retry, and release constraints unchanged.

No implementation write scope is permitted by this record. The next permitted gate is a fresh independent critic review of that revised plan and its new digest. A changed digest, trust boundary, or real scene invalidates this review.

## Explicit Non-Claims

- No code, tests, plan, task JSONL, checkpoint, or production artifact was changed by this review.
- No provider invocation, exact-parent suffix proof, full Direct E2E proof, Candidate build, Judge result, package, Registry publication, or released EnvironmentPackage is claimed.
- No model prompt, credentials, sealed data, or model transcript is recorded here.
- This review does not authorize a third correction, blind retry, output edit, model/response-mode change, node split, Agent conversion, or broader Runtime/Expand/Consumer work.

## Files Found

- `docs/agent-world-environment-generation.zh.md` — canonical product and authority contract, including the Direct design sequence and shared-domain partition requirement.
- `docs/direct-rewrite-execution-map.zh.md` — derived execution/owner map for framework, Direct LLM, Agent, and untrusted candidate boundaries.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/remaining-design-direct-contract-closure-plan.md` — reviewed revision-1 plan whose digest is verified above.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-e2e-remaining-direct-contract-closure.md` — persisted diagnosis for the real failed Direct scene.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — source-card and closed-owner contract reference.
- `agent_world/design.py` — Direct source compilers, RuleDraft grammar, and typed handoff construction.
- `agent_world/contracts.py` — cold typed contract invariants and actual Curriculum name grammar.
- `agent_world/graph.py` — immutable node/owner/route topology.
- `agent_world/candidate.py` and `agent_world/observe.py` — downstream typed projection, package/Registry closure, and safe Observe consumer path.
- `tests/test_design_semantics.py`, `tests/test_graph_contracts.py`, and `tests/test_direct_release.py` — affected deterministic consumer/projection coverage surfaces.

## Related Specs

- `.trellis/spec/guides/foundry-product-alignment.md`
- `.trellis/spec/guides/agent-llm-node-debugging.md`
- `.trellis/spec/agent_world/backend/index.md`

## Caveats / Not Found

The review intentionally relies on safe persisted run facts and compiled code; it does not expose or rely on raw Direct prompts, model transcripts, credentials, or sealed data. The prior narrow SharedTool proof is not a terminal/release proof, and the failed run never reached Candidate/Registry, so provider behavior and downstream release closure remain unproved.

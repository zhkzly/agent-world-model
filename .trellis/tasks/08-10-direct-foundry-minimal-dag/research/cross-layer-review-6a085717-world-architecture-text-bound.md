# Research: cross-layer review — WorldArchitecture text bound

- Query: Is plan `6a08571752cf0bb34de5a574d19836af01706e01495027f039df01e31e6661c2` the smallest causal repair for `run_d825291601a741da8d854a94400e2d01`, including complete current-limit disclosure, sparse SourceDraft preservation, correction safety, downstream compatibility, and the 10,299-line cap?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `6a08571752cf0bb34de5a574d19836af01706e01495027f039df01e31e6661c2` (SHA-256 rechecked; match).
- Plan lineage / revision: `world-architecture-text-bound`, revision **1/2**.
- Scope classification: the `world_architecture` shape disclosure is a local Direct producer/compiler repair. As written, the shared `_text` feedback edit is instead a coordinated cross-node correction-projection change, so the combined plan is not yet the smallest coherent scope.
- Trigger: Observe-driven diagnosis `diagnosis-e2e-world-architecture-text-bound.md` records that real run `run_d825291601a741da8d854a94400e2d01` passed Research plan/acquisition/synthesis, then used both authorized WorldArchitecture attempts at `$.boundary.purpose`. The compiler's existing 160 bound was absent from both the rendered shape and the correction, producing the Designer-owned failed WorkRecord, blocking Finding, and `not_published` terminal.
- Affected trust boundary: `Direct WorldArchitecture output_shape + authorized correction -> Luna proposal -> Designer compiler -> GraphRunner attempt/validation/WorkRecord -> compiled WorldArchitecture Artifact`.

## Product Target and Impact Chain

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The local repair advances only this prefix:

```text
EnvironmentRequest -> Research evidence -> WorldArchitecture Direct proposal
-> Designer compiler -> WorldArchitecture Artifact
-> SharedToolSemantics / ToolSemantics / WorldRules / Curriculum / TaskRequirement
-> Modeling -> Builder -> Judge -> Package -> Registry -> Observe
```

Designer owns the model-facing WorldArchitecture proposal, deterministic compilation, and the one existing local correction. `GraphRunner` owns the two-attempt transaction and persistence. The downstream nodes consume the compiled `WorldArchitecture`, not the raw source proposal or its correction packet.

If limited to the shape literal and an architecture-local safe diagnostic, the compiled `WorldArchitecture` value, Artifact kind, output port, NodeSpec, edges, route, correction count, and every later consumer remain compatible. The changed `shape` is already included in WorldArchitecture semantic material (`agent_world/design.py:607-623`), so that node receives a new semantic revision without an Artifact ABI migration.

## Current-Limit Audit

The plan identifies the actual WorldArchitecture character limits, with the following precision corrections required in revision 2:

| Source field(s) | Current compiler fact | Plan status |
| --- | --- | --- |
| `boundary.name`, `purpose`, `system_of_record`, `authority` | Each is `_text(..., 160)` after stripping; nonempty stripped text, maximum 160 Python characters (`agent_world/design.py:994-1017`). | Correct limit; say “after trimming” rather than a raw-string limit. |
| `boundary.actors[]` | 1..8 items; each is stripped, nonempty text of at most 80 characters; uniqueness is checked **after** stripping (`agent_world/design.py:975-993`). | Correct limit/count; state normalized uniqueness. |
| `entities[].name`, `entities[].purpose` | Stripped nonempty text at most 64 and 300 respectively; entity names are unique within the `entities` list (`agent_world/design.py:1025-1063`). | Correct limits; name the collection explicitly rather than “owner collection.” |
| `tools[].name`, `tools[].purpose` | Stripped nonempty text at most 64 and 300 respectively; tool names are unique within the `tools` list (`agent_world/design.py:1065-1128`). | Correct limits; name the collection explicitly. |
| Field `name` and optional `entity_ref` | Field `name` is stripped text at most 64 then must match the snake-name regex; `entity_ref` must itself match that regex, whose maximum is 64, and is not trimmed (`agent_world/design.py:213-265`). | Preserve the existing sparse/relationship rule and distinguish it from ordinary stripped text. |
| `known_divergences[].statement` | Stripped nonempty text at most 500 (`agent_world/design.py:1129-1141`). | Correct limit. |

No additional character limit is currently enforced for enum/list `values`; they remain the existing unique, nonempty 1..16 collection (`agent_world/design.py:239-256`). The revision must not invent one. Existing cardinality, actor-name resolution, field-key sparsity, field category, entity-only relation closure, divergence kind, and frozen-citation rules must likewise stay verbatim. In particular, a tool field's `entity_ref` is only snake-form at this boundary; only entity-field references are checked against declared entities (`agent_world/design.py:1053-1063`).

## Blocking Finding: Shared `_text` Changes More Than WorldArchitecture

The plan says a generic `_text` edit changes only safe correction evidence and does not change other Prompts. That is not accurate:

- `_text` is called by `research_plan` (240), `research_synthesis` (500/300), WorldArchitecture, SharedToolSemantics (280/160), RuleDraft rationale compilation (300, used by ToolSemantics, WorldRules, and TaskRequirement), and CurriculumPlan (64/40/300/500) (`agent_world/design.py:213-265, 474, 653-669, 854-880, 1308-1361, 1647-1801`).
- An Agent's correction is physically appended to its instruction (`agent_world/design.py:522-537`); a Direct node's correction is physically included in its JSON user input (`agent_world/design.py:543-565`). It is therefore a model-visible prompt/input change on the second invocation, not merely an internal error-message change.
- `GraphRunner` persists that packet in the attempt and failure evidence visible to later safe projections (`agent_world/graph.py:487-539`).
- Feedback is part of the model-node contract in the current task design (`.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:218-220, 284-300`) and source-of-truth Direct input includes authorized correction feedback (`docs/agent-world-environment-generation.zh.md:504-513`).

The generic numeric text would be safe to disclose only if it accurately says that the **stripped** value is nonempty and bounded. However, its cross-node behavioral and observable impact has not been inventoried or proved. Further, the non-WorldArchitecture semantic material does not explicitly include this dynamic correction text, while the WorldArchitecture shape does include its static shape (`agent_world/design.py:607-623`; `agent_world/graph.py:441-460`). The plan cannot both claim a local repair and silently change correction behavior for every affected Direct/Agent node.

## Required Plan Revision

Revise the plan only, to revision 2/2, before implementation. It must choose one bounded alternative:

1. **Recommended smallest scope:** make the new numeric correction condition WorldArchitecture-local and leave generic `_text` behavior unchanged for all other callers. The new condition must say that stripped text is nonempty and has the exact bound; it must not alter accepted values, codes, paths, categories, correction count, route, or Artifact output.
2. **If retaining the shared helper:** reclassify the plan as a coordinated correction-projection change. List every affected Design node and its correction recipient, state why its same semantic identity is valid, and add focused Direct and Agent correction-delivery regressions. Do not call this a no-Prompt/no-contract change.

For either alternative, make the WorldArchitecture literal exact: separate entity and tool uniqueness, normalized actor uniqueness, 64-character snake field/reference constraints, and the absence of a `values` character cap. Retain the present sparse grammar: scalar `values` omitted, absent relations omitted rather than rendered as `null`, `actor_names` rather than numeric `actor_indexes`, and no model-visible framework/Schema authority.

Do not solve this with a global prompt/schema/feedback framework, extra retry, looser validator, route/model change, new node, new Artifact, or a compatibility form. Production Python is already exactly **10,299** lines, so the revised plan must retain the before/after count and replace text in place rather than add a helper/module.

## Smallest Tests and Proof

The revised plan must require:

1. One captured, exact WorldArchitecture recipient-shape assertion covering every table entry above while retaining the existing sparse-field assertions (`values ... otherwise=>omit`, relation omission, no `[]`/`null` placeholders, and no `actor_indexes`).
2. One transaction-level fake Direct regression: a 161-character `$.boundary.purpose` first response, exact safe correction containing `160`, unchanged frozen shape/projection on the second call, and a valid second response that commits the existing compiled architecture/WorkRecord.
3. If the helper remains shared, at least one affected Agent caller and one affected non-WorldArchitecture Direct caller must prove the revised safe packet arrives only as the authorized correction and leaves their accepted artifact contracts and one-correction behavior unchanged.
4. Focused/full pytest, Ruff format/check, mypy, compileall, diff check, and the exact post-edit `agent_world` production-line count of at most 10,299.

The smallest real-boundary proof after an allow is first one fresh WorldArchitecture Direct invocation using the same need/evidence class, followed immediately by its WorkRecord and Observe scene. Only then should the planned fresh full CLI natural-language run proceed; any different terminal starts a new diagnosis rather than being attributed to this repair.

## Non-Claims and Next Permitted Gate

This review authorizes no code edit, test execution, provider call, retry, model/route change, or task-manifest update. It does not claim a successful WorldArchitecture turn, full Design, Candidate, Integration, Judge, Package, Registry, Repair, Expand, Consumer, or end-to-end product outcome.

It also does not authorize aligning this local compact compiler with the broader target `WorldArchitectureSourceDraft` described in `node-contracts.md`; that would be a separate contract plan, not an incidental text-bound repair.

**Next permitted gate:** revise this plan only to revision 2/2, address the shared-helper scope and exact wording/testing facts above, recompute its digest, and submit that new digest to a fresh independent cross-layer critic. No implementation may start under this blocked digest.

## Files Found

- `docs/agent-world-environment-generation.zh.md` — source-of-truth product, Direct input, World modeling, evidence, and release boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — derived owner/execution map for Direct LLM, Designer compiler, and downstream handoffs.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` — active Direct task contracts and feedback/consumer requirements.
- `research/diagnosis-e2e-world-architecture-text-bound.md` — persisted Observe-driven causal diagnosis for the triggering run.
- `research/world-architecture-text-bound-plan.md` — reviewed revision-1 repair plan.
- `research/product-alignment-checkpoints.md` — PAC-86 records the same real terminal and next critic gate.
- `agent_world/design.py` — `_text`, Direct/Agent correction delivery, WorldArchitecture shape, compiler, and all shared-helper call sites.
- `agent_world/graph.py` — semantic revision construction and two-attempt correction/WorkRecord persistence.
- `tests/test_design_semantics.py` — focused WorldArchitecture recipient-shape and correction regression surface.

## Related Specs and External References

- `.trellis/spec/guides/foundry-product-alignment.md` — local node progress is not product completion.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — prove the local true boundary before broader E2E progression.
- `.trellis/spec/agent_world/backend/index.md:325-371, 1620-1702` — compact semantic proposals, framework-owned compiler boundaries, and safe actionable diagnostics.
- `agent-world-cross-layer-critic` skill — required independent development gate and bounded allow/block decision process.
- External references: none. No provider was contacted.

## Caveats / Not Found

- The review found no evidence that a downstream consumer reads raw WorldArchitecture source text or a correction packet as its Artifact ABI; the unproved risk is the shared model-facing correction behavior and its persisted attempt evidence.
- The assessment is deliberately limited to the current compiler, real scene, and exact plan digest. A changed digest, trust boundary, or new Observe terminal invalidates this decision.

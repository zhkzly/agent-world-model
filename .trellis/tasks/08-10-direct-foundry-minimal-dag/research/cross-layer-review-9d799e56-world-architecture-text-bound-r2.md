# Research: cross-layer review — WorldArchitecture text bound revision 2

- Query: Does revision 2/2 of `world-architecture-text-bound-plan.md` close every revision-1 blocker for real run `run_d825291601a741da8d854a94400e2d01` without widening the Direct trust boundary?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `9d799e5635ef9debe187032deefc1138a89982e533ad07640c53dd9a05cb1d30` (SHA-256 independently recomputed; exact match).
- Plan lineage / revision: `world-architecture-text-bound`, revision **2/2**.
- Scope classification: **local Direct producer/compiler repair**. The approved change is limited to the `world_architecture` recipient shape, its `boundary.purpose` compiler precheck, and focused tests.
- Trigger and causal evidence: the persisted diagnosis records that Research completed, then both authorized WorldArchitecture attempts failed at `$.boundary.purpose` because the existing 160-character bound was absent from the recipient shape and generic correction (`research/diagnosis-e2e-world-architecture-text-bound.md:12-29,38-51`).
- Affected trust boundary: `WorldArchitecture output_shape + one authorized correction -> Direct proposal -> Designer compiler -> GraphRunner attempt/validation/WorkRecord -> compiled WorldArchitecture Artifact`.

## Product Target and Impact Chain

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

```text
EnvironmentRequest -> Research evidence -> WorldArchitecture Direct proposal
-> Designer compiler -> WorldArchitecture Artifact
-> SharedToolSemantics / ToolSemantics / WorldRules / Curriculum / TaskRequirement
-> Modeling -> Builder -> Judge -> Package -> Registry -> Observe
```

This repair advances only the WorldArchitecture prefix. It neither declares a successful Design nor changes Builder, Judge, release, Registry, Repair, Expand, or Consumer behavior.

## Revision-1 Blocker Closure

1. **No shared-helper change.** The revised plan leaves `_text` untouched and replaces only the `boundary.purpose` call (`research/world-architecture-text-bound-plan.md:28-35`). This closes the prior cross-node correction-projection issue: all other `_text` callers, their model-facing correction packets, and their persisted attempt evidence remain unchanged.
2. **Equivalent local acceptance and exact safe feedback.** Existing `_text` accepts `isinstance(value, str)`, returns `value.strip()`, and rejects empty/out-of-limit stripped text (`agent_world/design.py:110-118`). The plan preserves that normalization/output, code, path, and `string` category while changing only the local safe condition to `stripped value must be nonempty text of at most 160 characters` (`research/world-architecture-text-bound-plan.md:28-35`). That condition fits the closed `CorrectionPacket` contract and is delivered only as the second Direct input (`agent_world/design.py:543-565`; `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:125-148`).
3. **Accurate compact shape.** The plan now states stripped bounds for all boundary fields, normalized actor uniqueness, separate entity/tool name uniqueness, 64-character stripped snake field names, untrimmed 64-character snake `entity_ref` values, entity-field-only reference closure, and 500-character divergence statements (`research/world-architecture-text-bound-plan.md:8-27`). These match the compiler (`agent_world/design.py:213-265,975-1186`). It explicitly retains sparse fields/relations, `actor_names` rather than `actor_indexes`, and a 1..16 unique nonempty enum/list collection with **no value-character cap**.
4. **Compatibility and ownership stay coherent.** Designer remains the sole owner of the Direct proposal/compiler; GraphRunner retains the fixed two-attempt transaction and one-local-correction rule (`agent_world/graph.py:33-72,481-557`). All later nodes consume the compiled `WorldArchitecture`, not raw proposal text or a correction packet; for example, shared-tool projection is built from compiled architecture values (`agent_world/design.py:1230-1387`). NodeSpec, edges, route, Artifact kind/output port, input projection, dataclasses, configuration, and correction budget are unchanged.
5. **Semantic identity is correctly bounded.** The revised static `output_shape` is part of WorldArchitecture semantic material (`agent_world/design.py:607-623`), so its own semantic revision will intentionally rotate, as required for a model-output-contract change (`agent_world/graph.py:441-460`; `.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:218-221`). This is not an Artifact ABI change. Existing immutable provenance will also re-materialize downstream dependency-linked envelopes; notably, the unchanged Modeling Gate includes `architecture_ref.digest` in its existing semantic material (`agent_world/design.py:2100-2125`). That is expected causal lineage, not a changed downstream model contract. No other node's Prompt/output contract, route, correction behavior, or framework owner changes; later consumers receive the same compiled meaning for an accepted proposal.
6. **Tests and line cap are executable.** Existing focused tests already capture sparse grammar, relation distinction, absence of `actor_indexes`, and typed one-correction delivery (`tests/test_design_semantics.py:441-665`). The plan adds the exact shape and first-invalid/second-valid transaction assertions on that surface (`research/world-architecture-text-bound-plan.md:36-48`). The project declares pytest, Ruff, and mypy (`pyproject.toml:9-40`). Current production Python is exactly **10,299** lines; the approved plan requires an in-place edit and exact post-edit cap, so no new production helper/module is permitted.
7. **Proof order is safe.** The plan requires a fresh real WorldArchitecture Direct proof, immediate WorkRecord/Observe inspection, then—and only after it passes—a fresh full CLI natural-language proof followed by Observe (`research/world-architecture-text-bound-plan.md:50-59`). A different terminal starts a new diagnosis.

## Smallest Allowed Implementation and Proof

- Edit only the existing WorldArchitecture shape literal and the existing `boundary.purpose` call site in `agent_world/design.py`, plus focused assertions in `tests/test_design_semantics.py`.
- The regression must assert the exact local correction tuple: `world_architecture_invalid`, `$.boundary.purpose`, the stated 160-character condition, and `string`; it must also show unchanged frozen `input` and `output_shape` between attempts and a committed existing Artifact/WorkRecord after the valid second proposal.
- Run focused then full pytest, Ruff format/check, mypy, compileall, diff review, and the exact production line-count check. These are deterministic guards, not the real-boundary proof.
- Before each real proof terminal, record the required Product Alignment Checkpoint; after each terminal, inspect Observe. No provider call was made by this review.

## Files Found

- `research/diagnosis-e2e-world-architecture-text-bound.md` — Observe-driven causal diagnosis for the triggering run.
- `research/cross-layer-review-6a085717-world-architecture-text-bound.md` — revision-1 block and exact required closure.
- `research/world-architecture-text-bound-plan.md` — reviewed revision-2 plan.
- `agent_world/design.py` — shared text helper, Direct recipient construction, WorldArchitecture compiler, and downstream compiled-value consumers.
- `agent_world/graph.py` — semantic revision, two-attempt correction, WorkRecord, and Artifact persistence.
- `tests/test_design_semantics.py` — focused fake-Direct contract and correction regression surface.
- `docs/agent-world-environment-generation.zh.md` — source-of-truth product, Direct node, framework compiler, and proof boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — derived component/execution and downstream ownership map.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` — active Direct contracts, correction rule, and proof order.

## Related Specs and External References

- `docs/agent-world-environment-generation.zh.md:109-113,596-643` — model-facing contract changes receive a new semantic identity; framework retains compiler/release authority.
- `docs/direct-rewrite-execution-map.zh.md:1-110,183-200` — Direct WorldArchitecture is a bounded Direct LLM transaction and downstream artifacts, not raw model output, cross edges.
- `.trellis/spec/agent_world/backend/index.md:325-371,570-706,1190-1246` — compact semantic source, Direct no-Skill boundary, semantic identity, and actionable safe diagnostics.
- `.trellis/spec/guides/foundry-product-alignment.md` — a local successful node is not product completion.
- External references: none. No provider or web call was made.

## Non-Claims and Next Permitted Gate

This allow does not claim a successful WorldArchitecture invocation, full Design, Candidate, Integration, Judge, Package, Registry release, Repair, Expand, Consumer, or end-to-end product result. It does not authorize a schema/prompt framework, retry-budget change, route/model change, extra node/Artifact, validator relaxation, or any modification outside the approved files.

**Next permitted gate:** implement exactly plan digest `9d799e5635ef9debe187032deefc1138a89982e533ad07640c53dd9a05cb1d30`, then obtain the independent implementation/check evidence before the ordered real proofs. The allow expires if this digest, the stated trust boundary, or the relevant Observe scene changes.

## Caveats / Not Found

- Deterministic checks and real proofs were not run by this read-only pre-implementation critic; their required order is part of the approved plan.
- No downstream consumer was found to read raw WorldArchitecture source text or a correction packet as an Artifact ABI. The local WorldArchitecture semantic revision will change because its recipient shape changes; dependency-linked Work/Artifact identities can then re-materialize under the existing immutable-provenance code. That is intentional lineage propagation, not a wider model-contract change.

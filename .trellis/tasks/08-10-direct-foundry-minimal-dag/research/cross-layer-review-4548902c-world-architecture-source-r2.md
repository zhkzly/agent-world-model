# Research: cross-layer review — WorldArchitecture SourceDraft minimal plan, revision 2

- Query: Does exact plan digest `4548902cbc2faede2d12b2e94dc1f87b4c3e6913ccb57ac5aaf39b165e94831f` close the four revision-1 blockers while preserving the compiled WorldArchitecture contract, graph topology, and typed correction/failure path without overdesign?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `4548902cbc2faede2d12b2e94dc1f87b4c3e6913ccb57ac5aaf39b165e94831f` (SHA-256 reverified from the complete revised plan).
- Plan lineage / revision: `world-architecture-source-draft-minimal`, revision 2/2.
- Scope classification: local Direct-LLM proposal/compiler boundary. The compiled `WorldArchitecture` projection, `NodeSpec`, graph edges, route, correction limit, and later consumer contracts stay unchanged.
- Trigger and diagnosis: real terminal `run_5c648fca95e64bc08107b70a48127854`, diagnosed in `research/diagnosis-world-architecture-source-draft-overexposed.md` as an overexposed SourceDraft contract rather than a route, provider, retry, or node-size failure. No provider was called for this review.

The plan now explicitly supplies all four facts the revision-1 block required: closed sparse-source grammar with rejection of the old placeholder protocol; a semantic-presence Boolean distinct from JSON Schema mechanics and an honest schema non-claim; frozen actor-name resolution with a two-actor ordering proof; and an executable production LOC ceiling measured from the actual 10,297-line baseline. It stays within the existing Designer boundary and does not add a type, module, node, edge, Skill, retry, schema package, configuration, compatibility mode, or downstream redesign.

## Product target and affected trust boundary

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This plan advances only the first Direct modeling handoff:

```text
Direct LLM WorldArchitectureSourceDraft
  -> Designer local parser / deterministic normalization
  -> FieldDeclaration + ToolSurface
  -> WorldArchitecture Artifact
  -> later Design nodes / ModelingGate / Builder / package / Registry / Observe
```

The Direct LLM remains a prompt-only semantic producer with no Skill, tools, workspace, Gate, release, schema, or numeric binding authority. Designer remains the sole owner of source validation, sparse-default normalization, actor-name-to-index conversion, compiled Artifact commit, and the existing one-correction transaction. This matches the source-of-truth World modeling split: the model supplies compact business semantics while framework code owns schema mechanics, IDs, references, required/closed-shape assembly, and root assembly (`docs/agent-world-environment-generation.zh.md:601-603,615-621`; `docs/direct-rewrite-execution-map.zh.md:71-76,114-124`).

## Revision-1 blocker closure

1. **Exact sparse grammar and old-placeholder rejection — closed.** The plan fixes the mandatory base keys to `name`, `category`, and semantic `required`; limits `values` to nonempty, unique finite enum/list domains; and limits `entity_ref` to real non-null relations. It requires the local compiler to reject missing enum/list values, every scalar `values` key including `[]`, explicit `entity_ref: null`, unknown keys, malformed names/categories/Booleans, and malformed references as a path-addressed `world_architecture_invalid` `DesignError`. It also preserves the existing distinct closure rules for entity and tool fields. This eliminates the old full-key source protocol rather than accepting it as a compatibility spelling.

2. **Semantic presence versus framework JSON Schema authority — closed.** The plan explicitly treats the Boolean as LLM-proposed business presence retained in `FieldDeclaration.required`, not as a model-authored JSON Schema `required` array. It assigns all future schema-keyword assembly to framework code and expressly does not claim to add or prove a Draft 2020-12 artifact. The focused checks require both `required=True` and `required=False` to survive the compiled projection. This is the correct local distinction: `FieldDeclaration` already has the Boolean field and durable defaults (`agent_world/contracts.py:513-528`), while the current cleanroom has no WorldArchitecture Draft-2020-12 assembler to claim.

3. **Deterministic actor-name conversion — closed.** The plan replaces only the model-facing `actor_indexes` key with a nonempty, unique, ordered `actor_names` list. After the boundary actors have been normalized and uniqueness-checked, Designer deterministically maps exact names in frozen boundary order to the existing one-based `ToolSurface.actor_indexes`. It requires rejection of numeric old keys, unknown names, and duplicate names through the same correction/failure transaction, and requires a two-actor proposal whose source order differs from index order. The compiled Artifact therefore continues to expose only numeric indexes to all consumers.

4. **Executable production LOC cap — closed.** The plan records the precise production baseline, requires the exact before/after `find agent_world -type f -name '*.py' -exec wc -l {} +` measurement, and caps the replacement at 10,299 lines. The reviewed worktree command reports `10297 total`; the plan permits at most two net production lines and expressly disallows a new helper/module/type/node. Test lines cannot satisfy the cap.

## Impact chain, owners, and compatibility

| Boundary | Owner and change | Compatibility fact |
| --- | --- | --- |
| Direct recipient | Direct LLM produces only sparse business source semantics and `actor_names`. | The rendered `output_shape` must omit numeric actor-index instructions and mandatory empty/null source placeholders. |
| Local compilation | Designer validates the source grammar, applies defaults, resolves actor names, and constructs durable dataclasses. | It still emits `FieldDeclaration(name, category, required, values, entity_ref)` and `ToolSurface.actor_indexes`; no raw source-only key crosses this boundary. |
| Artifact commit | Designer/GraphRunner commits `WorldArchitecture` under the existing node. | `SemanticCatalog`, `ToolCouplingPlan`, Artifact kind, port, and correction/WorkRecord mechanism remain unchanged. The changed rendered shape intentionally changes the node semantic revision (`agent_world/design.py:605-621`; `agent_world/graph.py:442-460`), not the downstream Artifact schema. |
| Immediate/later consumers | SharedToolSemantics, ToolSemantics, WorldRules, Curriculum, TaskRequirement, ModelingGate, Builder, package writer, Registry, Observe, and future Expand/Consumer consume compiled architecture facts. | Existing graph edges remain `world_architecture:architecture` edges (`agent_world/graph.py:329-358`); later projections continue to receive `actor_indexes` and compiled fields, never raw `actor_names`. Package serialization reads `json_value(design.architecture)` (`agent_world/candidate.py:2085-2090`). |

The current implementation validates the boundary before tool parsing (`agent_world/design.py:967-1022`) and currently produces numeric `ToolSurface.actor_indexes` (`agent_world/design.py:1063-1118`). `WorldArchitecture` independently requires one-based in-range indexes (`agent_world/contracts.py:659-681`). The plan's source-only transformation is therefore compatible with the durable owner and consumer contract. `_catalog` derives later semantic bindings from compiled tool indexes and field names, not raw Direct proposal keys (`agent_world/design.py:479-511`).

“Unchanged downstream artifact” means unchanged compiled type/key contract and graph topology, not reuse of the old Artifact identity: a revised Direct output shape necessarily gives the node a new semantic revision. It also does not mean compiled defaults disappear. The model must not send `values: []` or `entity_ref: null`; after a valid sparse source is accepted, framework normalization intentionally retains the existing `values=()` / `entity_ref=None` dataclass defaults, which serialize downstream as the unchanged compiled JSON shape. The focused assertions must distinguish those two boundaries.

## Typed correction/failure and smallest proof

The plan retains the existing typed path. `DesignError` is a rejected `NodeExecutionError` carrying only the safe code, path, condition, and expected category (`agent_world/design.py:75-96`); `GraphRunner.execute` grants the single eligible local correction and then persists a failed WorkRecord/Finding on terminal failure (`agent_world/graph.py:462-539,671-784`). The plan specifically forbids a `KeyError`, dataclass `ValueError`, or generic schema/helper detour, and requires the old key, unknown/duplicate actor, malformed source, and invalid reference cases to reach that same transaction after its correction budget.

Smallest deterministic checks permitted by this allow:

- Update the actual recipient-shape assertion to the sparse conditional grammar and the absence of numeric actor instructions/mandatory source placeholders.
- Verify scalar fields with both Boolean presence values normalize to `()`/`None` and preserve `FieldDeclaration.required`; verify enum/list finite domains and one entity relation preserve existing reference closure.
- Use two boundary actors and deliberately non-index source order; assert the committed/serialized `ToolSurface.actor_indexes` follow frozen boundary order and no `actor_names` occurs downstream.
- Drive missing enum/list domains, scalar `values` including `[]`, explicit null references, invalid relations, numeric old actor keys, unknown actor names, and duplicate actor names through the existing one correction and terminal failed WorkRecord path.
- Run focused and full pytest, Ruff format/check, mypy, compileall, the exact LOC measurement, and an independent implementation check.

The smallest true-boundary proof after deterministic checks is one fresh Luna `world_architecture` transaction through the normal Direct composition root, followed by its WorkRecord and Observe scene. A different terminal starts a new diagnosis; it does not authorize a prompt-only retry or a broader repair.

## Non-claims and next permitted gate

This allow does not claim a new Draft-2020-12 schema assembler or closed-schema artifact, a passing real provider invocation, a committed WorldArchitecture, later ToolSemantics/WorldRules/Curriculum success, ModelingGate, Candidate, Integration, Judge, Registry release, Repair, Expand, Consumer, or Direct E2E completion. It does not permit a legacy/full-key compatibility path, compiler relaxation, retry/model/route/configuration change, schema subsystem, topology change, or modification of historical runs.

Next permitted gate: implement only this exact revision-2 plan in the local `agent_world/design.py` proposal/compiler seam and focused tests; preserve compiled Artifact/edge contracts and enforce the 10,299 production-line cap. Then obtain the independent implementation check and run the stated real Luna node proof, reading Observe at its terminal. Any change to this plan digest, trust boundary, or relevant real scene expires this allow.

## Files found

- `research/world-architecture-source-draft-minimal-plan.md` — reviewed revision-2 plan; SHA-256 matched exactly.
- `research/diagnosis-world-architecture-source-draft-overexposed.md` — real-scene causal diagnosis and local repair boundary.
- `research/cross-layer-review-619d2853-world-architecture-source.md` — revision-1 block defining the four required closures.
- `docs/agent-world-environment-generation.zh.md` — source-of-truth World modeling ownership.
- `docs/direct-rewrite-execution-map.zh.md` — derived WorldArchitecture owner/executor map.
- `agent_world/design.py` — Direct recipient shape, local compiler, semantic revision material, and compiled consumer projections.
- `agent_world/contracts.py` — durable FieldDeclaration, ToolSurface, and WorldArchitecture invariants.
- `agent_world/graph.py` — unchanged node/edge declaration and typed correction/failure persistence.
- `agent_world/candidate.py` — package serialization of compiled architecture.
- `tests/test_design_semantics.py` — focused recipient-shape and typed-terminal regression surface.

## Code patterns

- Existing complete-key parsing is local to `_field` at `agent_world/design.py:213-263`; the allowed sparse replacement belongs there, not in a new abstraction.
- Boundary actors are normalized before tool compilation at `agent_world/design.py:967-1022`; the current compiled numeric index contract is at `agent_world/design.py:1063-1118` and `agent_world/contracts.py:617-678`.
- Entity-field reference closure is separate from tool-field name validation at `agent_world/design.py:1051-1062`.
- The effective output shape participates in semantic identity at `agent_world/design.py:605-621` and `agent_world/graph.py:442-460`; raw proposals do not become edge payloads.
- Existing graph edges and downstream package serialization are at `agent_world/graph.py:329-358` and `agent_world/candidate.py:2085-2090`.

## Related specs and external references

- `docs/agent-world-environment-generation.zh.md:601-603,615-621` — WorldArchitecture is one compact prompt-only semantic transaction; framework owns Schema/ID/reference/required/closed-shape compilation.
- `docs/direct-rewrite-execution-map.zh.md:16-24,53-60,62-88,114-124` — Direct LLM and framework ownership boundary; WorldArchitecture may not author JSON Schema or release mechanics.
- `.trellis/spec/agent_world/backend/index.md:325-371` — compact architecture source semantics and framework-owned schema mechanics.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — real terminal -> diagnosis -> reviewed repair -> proof sequence.
- `.trellis/spec/guides/foundry-product-alignment.md` — local graph/test success is not product completion.
- External references: none. No live provider was invoked.

## Caveats / Not Found

- This review is role-isolated and did not read `implement.jsonl` or `check.jsonl`; it makes no claim that the main session has recorded this allow in either manifest.
- No current WorldArchitecture Draft-2020-12 assembler/artifact was found in the reviewed cleanroom. The plan correctly treats that as an explicit non-claim, not authorization to add one here.
- The task's broader aspirational node-contract document is not a substitute for the source-of-truth document or the current compiled contract. This allow covers only the specified existing SourceDraft repair.
- This is the second and final permitted revision for this diagnosis/plan lineage. Any material scope expansion or a new real terminal requires a new diagnosis and plan lineage rather than another revision of this plan.

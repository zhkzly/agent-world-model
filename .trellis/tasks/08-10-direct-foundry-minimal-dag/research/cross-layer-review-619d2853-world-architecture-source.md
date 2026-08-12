# Research: cross-layer review — WorldArchitecture SourceDraft minimal plan

- Query: Does plan `619d28535a9849321ddb4742d4edb04a4e1dd41ea3dbffbf1c004f1a09f67c12` minimally restore LLM-owned business semantics and framework-owned mechanics without changing the committed WorldArchitecture/graph contract or overdesigning the repair?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `619d28535a9849321ddb4742d4edb04a4e1dd41ea3dbffbf1c004f1a09f67c12` (reverified immediately before this record).
- Plan lineage / revision: `world-architecture-source-draft-minimal`, revision 1/2.
- Scope classification: local Direct-LLM proposal/compiler boundary. The intended compiled Artifact, NodeSpec, graph edges, route, correction limit, and later consumers stay unchanged.

The proposed implementation is appropriately small, but the written plan does not yet make four boundary facts/proofs explicit: the exact sparse-key rejection policy, preservation of semantic presence (`required`), a nontrivial actor-name-to-index mapping, and how a 10,299-line cap can be met from a 10,297-line baseline. Per the critic gate, those are missing owner/consumer/evidence facts, so implementation is not yet authorized.

## Product target, trigger, and trust boundary

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

The triggering real scene is `run_5c648fca95e64bc08107b70a48127854`. Its persisted diagnosis attributes the failure to an overexposed WorldArchitecture wire contract, not to route, provider, retry, or node size. The affected trust boundary is:

```text
Direct LLM WorldArchitectureSourceDraft
  -> Designer local compiler/normalizer
  -> committed FieldDeclaration + ToolSurface
  -> WorldArchitecture Artifact
  -> later Design nodes / ModelingGate / Builder / package WorldSpec
```

The LLM may choose business field presence, category, finite domain values, real relationships, and actor access scope. It must not submit JSON Schema mechanics, numeric binding indexes, IDs, closed-root assembly, Gate, reward, or release facts. The Designer framework owns the sparse-protocol validator, defaults, closed category set, actor-name resolver, compiled `ToolSurface.actor_indexes`, Artifact commit, and one existing correction transaction.

## Blocking plan revision requirements

1. State the `required` split precisely. A per-field Boolean is an LLM-owned **presence semantic**; it is not a model-authored JSON Schema `required` array. The framework must preserve that Boolean in `FieldDeclaration.required` and, where a schema assembler exists, derive the JSON Schema `required` list itself. This repair must not add a schema library or a new schema compiler. The plan must explicitly non-claim that it proves a currently absent Draft-2020-12 schema artifact.

2. Define the sparse source grammar and rejection behavior, not only its happy path:

   - `name`, `category`, and semantic `required` are always present.
   - `values` is required and nonempty only for `enum`/`list`; it is absent for every scalar category. An explicit scalar `values: []` must be rejected rather than silently accepted as the prior overexposed protocol.
   - `entity_ref` is absent when there is no relation; when present it is a non-null valid name. An explicit `entity_ref: null` must be rejected rather than treated as a compatibility spelling.
   - Preserve the existing closure distinction: entity-field relations must resolve to declared entities, while tool-field references retain the current snake-name-only rule unless a separately reviewed plan changes it.
   - Missing finite values, forbidden placeholders, malformed/unknown references, and unknown old keys must reach the existing path-addressed `world_architecture_invalid` `DesignError`; do not allow a `KeyError`/dataclass `ValueError` or a second protocol.

3. Specify actor resolution as one local deterministic transformation after boundary actors have been normalized and uniqueness-checked: `actor_names` is a nonempty, unique ordered list of exact declared actor names, and framework maps each name by the frozen boundary order to the existing one-based `ToolSurface.actor_indexes`. Numeric `actor_indexes`, duplicate names, and unknown names must be rejected through the same single correction/failure path. The plan must include a two-actor, non-index-order regression so a one-actor fixture cannot falsely prove the mapping.

4. Make the code-volume cap executable. The reviewed production-Python baseline is 10,297 lines, leaving only two lines below the stated 10,299 cap. The revised plan must require a before/after `find agent_world -type f -name '*.py' -exec wc -l {} +` total and say that the parser/prompt replacement is net at most two production lines (or deletes enough existing lines). Tests do not substitute for this cap; no new helper/module/type/node is permitted.

These four additions keep the repair local. They do not authorize a graph revision, compatibility mode, retry, Skill, route change, JSON Schema subsystem, or a downstream redesign.

## Impact chain, owners, and compatibility

| Boundary | Owner / consumer fact | Compatibility requirement |
| --- | --- | --- |
| Direct proposal | Direct LLM proposes source business semantics only. | Its rendered `output_shape` names `actor_names`, not numeric indexes or required empty/null placeholders. |
| Local compile | Designer framework validates and normalizes. | It produces the existing `FieldDeclaration(name, category, required, values, entity_ref)` and `ToolSurface.actor_indexes`, not source-only alternate types. |
| Committed Artifact | Designer / GraphRunner commit the existing WorldArchitecture output port. | `SemanticCatalog`, `ToolCouplingPlan`, Artifact kind, edges, and WorkRecord/correction semantics remain unchanged; the changed rendered shape naturally changes the node semantic revision. |
| Immediate/later consumers | SharedToolSemantics, ToolSemantics, WorldRules, Curriculum, TaskRequirement, ModelingGate, Builder, package writer, Registry, Observe, and future Expand consume compiled architecture facts. | They must continue to receive `actor_indexes` and the same dataclass/JSON artifact shape, never `actor_names` or sparse proposal placeholders. |

The current code supports this narrow translation boundary: `_field` currently insists on all five wire keys (`agent_world/design.py:213-263`); the compiler builds `ToolSurface` from numeric indexes (`agent_world/design.py:1063-1118`); and the durable contracts retain `required`, default `values`, optional `entity_ref`, and numeric `actor_indexes` (`agent_world/contracts.py:513-528`, `617-678`). `json_value` serializes the compiled dataclasses, and package writing persists that compiled architecture in `world/world_spec.json` (`agent_world/contracts.py:60-69`, `agent_world/candidate.py:2085-2090`).

The source-of-truth distinction permits semantic presence to remain model-owned: the model chooses the field's business presence, while framework alone assembles JSON Schema mechanics. In the reviewed cleanroom, no current consumer of `FieldDeclaration.required` beyond parse/store/serialization was found; therefore this repair must preserve that value and explicitly not claim that it proves complete schema assembly.

## Smallest deterministic checks and true-boundary proof

After revision 2/2 is allowed, implementation may add only focused `tests/test_design_semantics.py` coverage plus the smallest local `agent_world/design.py` replacement.

Required deterministic checks:

- Capture the actual recipient shape and assert the sparse conditional grammar, no numeric actor instruction, and no mandatory empty/null placeholders.
- Compile scalar fields with omitted `values`/`entity_ref` and both `required=True` and `required=False`; assert compiled defaults are `()`/`None` and the Boolean survives in the committed architecture projection.
- Compile enum and list fields with finite values, plus one actual entity relation; retain the entity-field versus tool-field reference-closure distinction.
- Reject omitted enum/list values, scalar `values` including `[]`, `entity_ref: null`, invalid relations, old `actor_indexes`, unknown actor names, and duplicate actor names. Each must carry the exact path/category through the existing one correction and terminal failed WorkRecord, rather than a raw exception.
- Use at least two actors in a deliberately non-index order and assert the committed/serialized `ToolSurface.actor_indexes` matches the frozen actor order while no `actor_names` appears downstream.
- Keep the existing graph declarations and one-correction behavior intact (`agent_world/graph.py:151-160`, `462-558`, `672-680`), then run focused pytest, full pytest, Ruff format/check, mypy, compileall, and the explicit production-line count.

The smallest true-boundary proof remains one fresh Luna `world_architecture` transaction with the repaired recipient contract, followed by its WorkRecord and Observe scene. It is a later implementation/proof gate; this review did not call a provider.

## Non-claims and next permitted gate

This review does not authorize or claim a new JSON Schema implementation, full WorldModel closure, Research, ToolSemantics, Candidate, Integration, Judge, Registry, Repair, Expand, Consumer, or Direct E2E success. It also does not permit accepting the old expanded source shape as a compatibility path.

Next permitted gate: revise this plan only to revision 2/2, directly address the four blocking facts above, recompute its digest, and submit that new digest to a fresh independent cross-layer critic. No implementation or live retry is permitted under this blocked digest.

## Files found

- `research/world-architecture-source-draft-minimal-plan.md` — reviewed plan; supplied SHA-256 matched.
- `research/diagnosis-world-architecture-source-draft-overexposed.md` — real-scene causal diagnosis and stated local repair boundary.
- `docs/agent-world-environment-generation.zh.md` — source of truth for WorldArchitecture source semantics versus framework schema mechanics.
- `docs/direct-rewrite-execution-map.zh.md` — derived owner/consumer map for Direct LLM, Designer framework, and candidate boundaries.
- `agent_world/design.py` — current proposal shape, field parser, actor-index compiler, and ModelingGate consumers.
- `agent_world/contracts.py` — durable FieldDeclaration, ToolSurface, and WorldArchitecture contracts.
- `agent_world/graph.py` — existing WorldArchitecture node identity and correction/WorkRecord transaction.
- `agent_world/candidate.py` — Builder/package projection that consumes compiled architecture.
- `tests/test_design_semantics.py` — focused fixture and correction regression surface.

## Code patterns

- The old wire contract requires `values` and `entity_ref` for every field at `agent_world/design.py:213-263`; its sparse replacement must remain a local compiler rule.
- Actors are normalized before tools compile at `agent_world/design.py:967-1022`, while tool indexes are currently checked and stored at `agent_world/design.py:1063-1118`.
- Entity-only reference closure is at `agent_world/design.py:1051-1062`.
- The source shape is semantic material for the committed node at `agent_world/design.py:1196-1215`; GraphRunner binds effective projection/output shape into semantic revision and retains the one-correction transaction at `agent_world/graph.py:442-460` and `462-558`.
- ModelingGate consumes field categories into executable task projections at `agent_world/design.py:2044-2075`; the package serializes the compiled architecture, not raw proposal data, at `agent_world/candidate.py:2085-2090`.

## Related specs and external references

- `docs/agent-world-environment-generation.zh.md:601-619` — WorldArchitecture is a bounded prompt-only semantic transaction; framework compiles schema, IDs, references, required/closed shape, and root assembly.
- `docs/direct-rewrite-execution-map.zh.md:16-24, 62-116` — Direct LLM owns source semantics only; Designer framework owns compilation and commit.
- `.trellis/spec/agent_world/backend/index.md` — artifact-driven success paths, framework-owned release, and opt-in live tests.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — a real terminal requires diagnosis before a repair/proof sequence.
- `.trellis/spec/guides/foundry-product-alignment.md` — local graph/test progress is not product completion.
- External references: none. No live provider was invoked.

## Caveats / Not Found

- Role-isolation instructions prohibit this research critic from loading `implement.jsonl` or `check.jsonl`; this record therefore makes no claim about manifest curation or an already-recorded allow.
- No current Draft-2020-12 schema artifact/assembler or runtime consumer of `FieldDeclaration.required` was found in the reviewed cleanroom slice. That is an explicit non-claim for this local repair, not permission to add one here.
- The plan digest is blocked; it expires for implementation purposes and must be replaced rather than reused after revision.

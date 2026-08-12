# Research: cross-layer review — WorldArchitecture whole-object check

- Query: Independently review plan `world-architecture-whole-object-check-plan.md` at SHA-256 `ef4dae8464d07fb3eb43ff3d6783f0012a3701c5df77db90a9006df09d232ba1` after real Direct E2E `run_fac8d0b2961842c996837d2f035e3102` terminated `world_architecture_invalid` and Registry remained `not_published`.
- Scope: internal, read-only cross-layer plan review
- Date: 2026-08-12

## Decision

**Decision: block**

The plan correctly identifies the observed whole-object regression and keeps the right broad boundary: a complete replacement Direct proposal repaired an entity-field reference, then regressed `$.tools` below the already-disclosed `1..8` cardinality. The existing compiler, one authorized local correction, failed WorkRecord/Finding, non-publication, Judge, Registry, and Observe behavior are not the defect and must not be changed.

However, the proposed new global `entity_ref` instruction is not the actual compiler contract. It says that every intended `entity_ref` must copy an `entities[*].name` from the same object. The compiler closes references only for `entities[*].fields[*]`; it deliberately permits a tool argument/result field to carry an external relation. The plan therefore both claims to retain the current sparse grammar/compiler and silently narrows a valid Direct semantic output space. That is an unreviewed contract change, not a minimal wording repair.

- Plan digest: revision 1/2 proposes a local `WorldArchitecture` model-visible shape clarification, a matching human-readable node-contract update, focused tests, and then a real Direct proof; it explicitly preserves the existing compiler, two-attempt transaction, graph, and consumers.
- Required revision: revision 2 must qualify the reference rule by field location and prove preservation of the existing tool-field relation case before it can be allowed.
- Scope classification: the corrected repair can remain a **local Direct producer-contract/documentation/test** change. It does not require a graph, Candidate, Judge, Registry, or Observe change.

## Trigger and diagnosis reviewed

`diagnosis-e2e-world-architecture-whole-object-regression.md` and PAC-96 establish the causal chronology: the first Luna proposal was rejected for an undeclared entity-field reference; the framework sent its one safe correction; the second complete proposal passed that earlier point but supplied an invalid `$.tools` value; the Designer produced a blocking failure with no Architecture Artifact and Registry was `not_published`. This was not a provider, credential, timeout, JSON-decoding, Skill, token, or route failure.

This supports a model-visible complete-object reminder and does **not** authorize accepting a partial object, truncating tools, selecting a prior partial proposal, splitting the architecture into shards, adding another correction, routing to another model, or retrying the run.

## Files and contracts reviewed

- `agent_world/design.py` — Direct projection, invocation, WorldArchitecture compiler, sparse `Field` grammar, and deterministic compilation.
- `agent_world/graph.py` — Direct node contract, semantic identity, immutable Artifact/Work/Finding transaction, and one-correction limit.
- `agent_world/contracts.py` — typed Architecture, CorrectionPacket, Artifact, WorkRecord, Finding, and package-ref contracts.
- `agent_world/foundry.py`, `agent_world/candidate.py`, `agent_world/observe.py`, `agent_world/invocation.py` — downstream handoff, untrusted candidate boundary, Registry/Observe behavior, and Direct-versus-Agent invocation separation.
- `tests/test_design_semantics.py`, `tests/test_graph_contracts.py` — current sparse-contract and correction-transaction coverage.
- `docs/agent-world-environment-generation.zh.md` — canonical source of truth for framework-owned deterministic compilation and bounded Direct semantics.
- `docs/direct-rewrite-execution-map.zh.md`, `.trellis/spec/agent_world/backend/index.md`, `.trellis/spec/guides/agent-llm-node-debugging.md`, `.trellis/spec/guides/foundry-product-alignment.md` — Direct/Agent/candidate boundaries, semantic identity, debugging order, and product alignment.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{task.json,prd.md,design.md,implement.md}` and `research/product-alignment-checkpoints.md` — active task context and PAC-96/PAC-97 evidence.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — stale human-readable WorldArchitecture source draft that must be aligned only after the reference distinction is made exact.

No external reference was used. Task `implement.jsonl` and `check.jsonl` were intentionally not read under research-role isolation.

## Exact contract conflict

The current model-visible shape makes a generic `Field.entity_ref` an optional actual-relation string, then applies declared-entity closure only inside the `entities` collection:

- `agent_world/design.py:1201-1206` defines the generic Field shape, qualifies `entities[*].fields[*]` with `entity_ref=declared_entity_when_present`, and does **not** apply that suffix to tool argument/result fields.
- `agent_world/design.py:1056-1067` checks the declared-name closure solely by iterating entity fields.
- `agent_world/design.py:1113-1122` parses tool argument/result fields through the same sparse Field parser without that closure check.
- `tests/test_design_semantics.py:522-552` deliberately accepts `entities[0].fields[*].entity_ref == "handoff"` and `tools[0].argument_fields[0].entity_ref == "external_relation"` in the same compiled Architecture.

In contrast, plan lines 33-34 say, without a location qualification, to omit `entity_ref` or copy exactly one `entities[*].name`. Its planned `node-contracts.md` update likewise calls for the “same exact-name reference” rule. Applying that wording to all three Field collections would prohibit the accepted `external_relation` tool-field proposal even though the compiler and compiled `WorldArchitecture` still accept it. It changes the Direct model's bounded semantic choice without a corresponding compiler or consumer-contract decision.

## Product target and authority check

The target remains: a natural-language need becomes an executable, independently verified, publishable `EnvironmentPackage`; a passed graph fragment or a better-looking Architecture response is not product completion.

| Boundary | Verified owner | Review result |
| --- | --- | --- |
| Graph, routes, contracts, cardinalities, references, compiler, derived IDs/indexes/hashes, validation, correction cap, Findings, Judge, Registry, and Observe | Framework/hardcoded code | Preserved by the intended repair. `GraphRunner` owns the two-attempt transaction and immutable evidence (`agent_world/graph.py:462-595`); the compiler owns closure/cardinality checks (`agent_world/design.py:928-1207`). |
| Boundary, entities, sparse field meanings/categories/domains/references, coherent tool surface, and cited divergences | Direct LLM only | Correct owner, provided the prompt states the existing location-specific reference contract rather than inventing a global one. Direct receives only the rendered projection, shape, and safe correction (`agent_world/design.py:543-624`; `agent_world/invocation.py:90-162`). |
| Tool/Skill-enabled research and code proposals | Agents only | Unchanged. Research and Candidate Builder/Verifier work are Agent boundaries, not sources of WorldArchitecture control-plane decisions. |
| Generated candidate process | Untrusted candidate | Unchanged. It receives compiled Design data after Architecture commits; it cannot create gates, hashes, Findings, packages, Registry publication, or Observe results. |

## Impact chain and compatibility

The actual causal path is:

`output_shape` and frozen evidence projection -> Direct complete JSON proposal/correction -> `_direct_architecture` compiler -> GraphRunner Artifact or failed WorkRecord/Finding -> typed `WorldArchitecture` -> SharedToolSemantics / ToolSemantics / WorldRules / Curriculum / Task / ModelingGate -> Candidate DesignContract and package -> framework Judge -> Registry cold verification/publication -> read-only Observe.

`_direct_commit` includes the output shape in semantic material, so a corrected wording properly rotates the WorldArchitecture semantic revision and prevents silent reuse (`agent_world/design.py:581-624`; `agent_world/graph.py:442-460`). No inspected downstream edge consumes the raw proposal, prompt shape, or correction packet; downstream consumers receive the compiled typed Architecture. Candidate packaging serializes that compiled object, and Registry/Observe cold-read the package rather than the Direct response (`agent_world/candidate.py:753-763,2085-2149`; `agent_world/observe.py:498-537`).

Thus the plan does not overdesign the whole-object fix and does not hide a retry **if revised as below**. The existing second call is a single framework-authorized correction of a complete replacement object; no third invocation may be introduced. But the current global reference wording would change the producer-to-compiler semantic contract and can alter tool semantics that later consumers legitimately receive, so compatibility is not yet demonstrated.

## Required plan revision and smallest permitted tests

Revise only the plan; do not implement while blocked. Replace the ambiguous rule with the existing location-specific contract:

1. For every Field collection, retain the sparse base grammar and omit `entity_ref` when no relation is intended.
2. For `entities[*].fields[*]` only, an emitted `entity_ref` must exactly equal one `entities[*].name` emitted in the same complete object.
3. For `tools[*].argument_fields[*]` and `tools[*].result_fields[*]`, preserve the current optional actual-relation form; do not add declared-entity closure unless a separately diagnosed semantic/compiler/consumer change is proposed and reviewed.
4. Make `node-contracts.md` describe the same three-location distinction, including actual `argument_fields`/`result_fields`, rather than using a global exact-name reference rule.

The revised plan's smallest deterministic evidence should be:

- Capture the initial and corrected Direct recipient payloads and prove they contain the same updated complete-object rule and the same frozen output shape, with only the safe correction tuple differing.
- Preserve the observed transaction: an invalid **entity-field** reference gets the existing path-addressed correction; a second invalid `tools` value fails with no third Direct invocation, no Architecture Artifact, and the existing failed Work/Finding route.
- Prove a valid eight-tool proposal commits and a nine-tool proposal is rejected under the unchanged compiler.
- Retain the accepted external tool-field reference regression from `tests/test_design_semantics.py:535,552`, so the clarified prose cannot silently narrow it.
- Prove the wording rotates WorldArchitecture semantic identity while graph topology, correction limit, compiled output type, and downstream edge declarations remain unchanged.

After deterministic checks and a fresh `allow` review, the true-boundary proof may remain the plan's narrow sequence: first one frozen-evidence WorldArchitecture Direct proof with Work/Artifact/operation/Observe inspection; only if that passes, one fresh public Direct request through Registry and Observe. A different terminal requires a new Diagnosis Record. No blind retry, output editing, model fallback, extra correction, or later-child execution is permitted.

## Non-claims and next permitted gate

This review does not claim that prompt wording guarantees every model proposal is valid, that an Architecture node pass releases an EnvironmentPackage, or that Candidate/Judge/Registry/Observe have passed. It does not run tests, invoke a model, modify code, or treat the prior real run as a reusable success. It also does not authorize a compiler change, an additional retry, or a new global reference policy.

**Next permitted gate:** the plan writer may produce revision 2 with the location-qualified `entity_ref` rule and preservation test above, then request a new independent cross-layer review. Only a matching `allow` record permits implementation and the specified proof sequence.

## Caveats / Not Found

- The terminal evidence was reviewed through the persisted Diagnosis Record, PACs, task materials, and code paths; this review did not mutate or rerun the real Direct E2E.
- The stale node-contract text is documentation drift, not runtime input. Its repair must follow the compiler's existing location-specific behavior exactly.

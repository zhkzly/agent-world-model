# Research: cross-layer review — WorldArchitecture whole-object R2

- Query: Independently review revision 2 of `world-architecture-whole-object-check-plan.md` (SHA-256 `9e2c17c8ca5979d1493b22c405d20dbe034717e21b8d373110e3f1e866cfa8be`) after real Direct E2E `run_fac8d0b2961842c996837d2f035e3102` and revision-1 block `ef4dae84...`.
- Scope: internal, read-only cross-layer plan review
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `sha256:9e2c17c8ca5979d1493b22c405d20dbe034717e21b8d373110e3f1e866cfa8be`
- Plan revision: 2/2; this is the final permitted revision for this Diagnosis lineage.
- Scope classification: **local Direct producer-contract / task-contract documentation / focused-test change**. The model-visible source contract changes, but the compiler, compiled `WorldArchitecture` type, graph topology, correction limit, Artifact kind, and downstream interfaces do not.
- Trigger: failed real Direct E2E `run_fac8d0b2961842c996837d2f035e3102`, its persisted Diagnosis Record, PAC-96, and the revision-1 block.
- Affected trust boundary: frozen Research evidence and the Direct LLM's complete `WorldArchitecture` source proposal, through Designer-owned compilation and one safe local correction, into the committed Architecture handoff.

Revision 2 resolves the sole revision-1 contract conflict. It explicitly keeps the generic optional snake-name relation form for `tools[*].argument_fields[*]` and `tools[*].result_fields[*]`, while limiting declared-entity closure to `entities[*].fields[*]`. That is the current compiler behavior, so the clarified model-visible instruction does not narrow valid tool semantics or create a new producer/consumer contract.

## Product target and scope

The target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

This allowed repair advances only the Research-to-WorldArchitecture handoff. It does not claim Candidate, Judge, Registry, Repair, Expand, multi-parent evolution, Consumer/SFT/RL, or a released package. A passed Architecture transaction is necessary input to those paths, not product completion.

## Files found

- `research/world-architecture-whole-object-check-plan.md` — pinned revision-2 repair plan; checksum matches the supplied digest.
- `research/diagnosis-e2e-world-architecture-whole-object-regression.md` — records the first entity-reference failure, one correction, and later `$.tools` failure.
- `research/cross-layer-review-ef4dae84-world-architecture-whole-object.md` — revision-1 block requiring the location-qualified reference contract.
- `research/product-alignment-checkpoints.md` — PAC-96 through PAC-98 preserve the observed terminal, non-release, and revision-2 boundary.
- `agent_world/design.py` — actual Direct projection, shape, parser, compiler, and semantic-material construction.
- `agent_world/graph.py` — fixed node/edge declarations, semantic identity, bounded correction transaction, WorkRecord, and Finding ownership.
- `agent_world/contracts.py` — unchanged `FieldDeclaration`, `ToolSurface`, `WorldArchitecture`, correction, WorkRecord, and Finding contracts.
- `agent_world/candidate.py`, `agent_world/foundry.py`, `agent_world/observe.py` — compiled Architecture consumers, package/Registry handoff, terminal non-release, and safe Observe projection.
- `tests/test_design_semantics.py`, `tests/test_graph_contracts.py` — existing source-shape, sparse-field, correction-limit, and semantic-revision regressions.
- `node-contracts.md` — stale human-readable WorldArchitecture source draft that the plan correctly confines to a documentation alignment.

## Findings

### Actual model-visible shape and compiler

The Direct call receives only a system role statement plus a canonical user object containing `node`, frozen `input`, `output_shape`, and an optional safe correction; it has no Skill, tools, or workspace (`agent_world/design.py:543-565`). `_direct_commit` keeps the frozen visible projection and the same `shape` for both attempts (`agent_world/design.py:581-624`).

The current shape defines a generic sparse `Field` with optional snake-name `entity_ref`, applies `entity_ref=declared_entity_when_present` only within `entities[*].fields[*]`, and leaves tool argument/result fields as generic `Field` collections (`agent_world/design.py:1201-1207`). The compiler exactly matches that layout:

- `_field` validates the shared sparse grammar and optional syntactic relation name (`agent_world/design.py:213-265`);
- after all entities are parsed, only entity-owned fields are checked against emitted entity names (`agent_world/design.py:1028-1067`);
- tool arguments and results both reuse `field_array` with no declared-entity closure (`agent_world/design.py:1068-1124`).

Revision 2's three location-specific rules accurately restate this behavior. It does not add a global declared-name rule, relax entity-field closure, or substitute a business-specific entity/tool list.

### Correction transaction and authority

`world_architecture` is a Designer-owned `direct_llm` node with one local correction and the existing direct route (`agent_world/graph.py:151-160`; `agent_world/graph.py:38-77`). `GraphRunner` permits a correction only on the first rejected, non-retryable model attempt with a safe packet; its fixed loop permits only ordinals one and two (`agent_world/graph.py:462-557`; `agent_world/graph.py:672-680`). A second invalid proposal writes the failure evidence, blocking Finding, and failed WorkRecord rather than a third invocation (`agent_world/graph.py:516-539`, `agent_world/graph.py:699-784`).

The plan retains that ownership and transaction unchanged. The requested whole-object recheck is an instruction to the semantic proposer, while the compiler remains the only acceptance authority. The pre-existing transport-only primary/fallback behavior is outside this repair (`agent_world/invocation.py:90-103`); the allowed real proof must record the selected operation model and must not deliberately invoke a fallback, blind retry, output edit, or extra correction.

### Downstream compatibility and semantic identity

The impact chain remains:

`frozen evidence + request -> Direct complete JSON proposal/correction -> WorldArchitecture compiler -> committed Architecture Artifact or failed Work/Finding -> SharedToolSemantics / ToolSemantics / WorldRules / Curriculum / TaskRequirement / ModelingGate -> DesignContract -> Candidate -> Package -> Registry -> Observe`.

The graph's Architecture edges are unchanged (`agent_world/graph.py:329-358`). Downstream semantic nodes consume the compiled `WorldArchitecture`, not the raw Direct proposal or output-shape text: its tool fields drive the catalog and later typed projections (`agent_world/design.py:481-513`, `agent_world/design.py:1364-1379`, `agent_world/design.py:1403-1450`, `agent_world/design.py:2020-2094`). Candidate generation receives the compiled architecture, and the package carries that same typed value in `world/world_spec.json` (`agent_world/candidate.py:753-763`, `agent_world/candidate.py:2085-2149`). Registry and Observe retain their existing cold-read/non-release behavior (`agent_world/foundry.py:37-89`; `agent_world/observe.py:498-537`).

The compatible tool-field relation is not merely structural: the generic `FieldDeclaration` value is retained on both `ToolSurface.argument_fields` and `ToolSurface.result_fields` (`agent_world/contracts.py:512-635`), is serialized with the compiled Architecture, and is not later re-closed to entity names. The existing regression already demonstrates an entity-field relation to an emitted entity and an external tool-argument relation in one valid Architecture (`tests/test_design_semantics.py:514-556`). Revision 2 correctly extends the focused evidence requirement to argument **and** result locations.

Changing the disclosed shape rotates semantic identity because `_direct_commit` includes it in semantic material (`agent_world/design.py:615-619`) and `GraphRunner.semantic_revision` hashes that material with the node declaration/route (`agent_world/graph.py:442-460`). No raw prompt body is persisted. The existing recipient test already verifies this identity behavior (`tests/test_design_semantics.py:447-511`).

### Role boundaries and minimality

The Direct LLM continues to choose only world/business semantics; framework code owns sparse grammar, cardinalities, entity closure, actor resolution, IDs, schema compilation, artifact/work persistence, Finding, Judge, Registry, and Observe. This remains consistent with the source-of-truth Direct flow and Direct-versus-Agent boundary (`docs/agent-world-environment-generation.zh.md:596-645`; `docs/direct-rewrite-execution-map.zh.md:66-93`).

The plan is bounded to the existing WorldArchitecture shape constant, the WorldArchitecture prose section in `node-contracts.md`, and focused tests. It adds no model-facing parameter, prompt builder/framework, configuration, helper layer, node, graph edge, route, retry/progress system, candidate path, or business-specific semantic shortcut. Current production Python is 10,296 lines, matching the plan's ceiling; the proposed wording replacement is compatible with that limit.

## Smallest allowed implementation and proof

1. Amend only the existing WorldArchitecture output-shape wording with the revision-2 complete-object, 1..8-tool, and three-location `entity_ref` rules; retain the compiler and its data types.
2. Align only the WorldArchitecture section of `node-contracts.md` to the actual sparse draft, using `argument_fields`/`result_fields` and the same location-qualified reference meaning. Do not treat the task document as runtime input.
3. Add focused deterministic coverage that:
   - asserts the same updated complete-object shape is visible on initial and correction calls;
   - preserves sparse grammar, entity closure, tool cardinality, and the two-call/no-third-call transaction;
   - proves eight tools can commit and nine are rejected by unchanged framework validation;
   - proves an undeclared entity-field relation is rejected while separately proving external snake-name relations are accepted in **both** tool `argument_fields` and `result_fields`;
   - proves the output-shape change rotates only WorldArchitecture semantic identity and leaves node/edge/route/correction topology unchanged.
4. Run the plan's focused/full deterministic checks and independent code review before live work.
5. Run one real WorldArchitecture transaction against the frozen evidence Artifact from the failed E2E, inspect its WorkRecord/Artifact/operation evidence/Observe facts, then run one fresh public Direct request only if that node passes. Any different terminal begins a new Observe-driven Diagnosis; it is not authorization for a retry, fallback, output editing, or downstream shortcut.

## Deterministic checks, true-boundary proof, and non-claims

Deterministic tests prove contract preservation and regression resistance; they do not prove model compliance. The one frozen-evidence Direct invocation proves only the changed model-facing boundary. A fresh public request can then test the full Direct path, but only Registry publication and terminal Observe can support an E2E claim.

This allow does not claim that revised wording guarantees valid model output, that the named real run is repaired, that a WorldArchitecture pass releases a package, or that Candidate/Judge/Registry/Repair/Expand/Consumer behavior has passed. It does not authorize hardcoded business entities/tools, accepting/truncating invalid output, a prompt framework, extra model calls, model switching, hidden retries, new nodes, or work on later children.

## Related specs

- `docs/agent-world-environment-generation.zh.md` — canonical Direct semantic transaction, framework-owned compilation, release, and non-claim requirements.
- `docs/direct-rewrite-execution-map.zh.md` — Direct LLM / Agent / framework / candidate-process authority split.
- `.trellis/spec/guides/agent-llm-node-debugging.md` — Direct receives only rendered prompt/input plus authorized feedback; focused real proof remains required.
- `.trellis/spec/guides/foundry-product-alignment.md` — product alignment checkpoint and proof/non-claim requirements.
- `.trellis/spec/agent_world/backend/index.md` — compact architecture, semantic identity, and Direct prompt-only guardrails.

## External references

No external source was required or consulted. This decision relies on the canonical project document, the persisted real-run diagnosis/PACs, and the current target-worktree code and tests.

## Next permitted gate

The main planner may add this exact current allow record to the task's implementation and check context, then dispatch bounded implementation. Implementation must stop and return to a new plan/review if it discovers a changed compiler meaning, a new consumer, a new retry/fallback behavior, or any expansion beyond the listed files and proof sequence.

## Caveats / Not Found

- The live run's raw state/artifacts were not present in this worktree; the terminal evidence was reviewed through the persisted Diagnosis Record and PAC-96 through PAC-98. The real-proof step must use the actual frozen evidence Artifact rather than reconstructing or editing a model output.
- `_field` currently uses a generic diagnostic phrase about declared entities even when rejecting a malformed tool-field relation (`agent_world/design.py:257-264`). Valid external snake-name tool relations are already accepted, so this pre-existing diagnostic wording is not part of the diagnosed regression or this allowed scope. If it causes a later real failure, diagnose it separately rather than broadening this repair.

# Research: cross-layer review — SharedTool JSON contract revision 2

- Query: Independently review revision 2 of `shared-tool-json-contract-plan.md` at SHA-256 `74fb7af2f3efec6e479c2befece2ac83e0a9ffe6704b104bd0c63e5498e563b7`, following the failed Direct E2E `run_4528cf8a411a4d8a82b6390465c6d138` and prior block `cross-layer-review-7c47c057-shared-tool-json.md`.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `74fb7af2f3efec6e479c2befece2ac83e0a9ffe6704b104bd0c63e5498e563b7`
- Plan revision: `shared-tool-json-contract`, revision `2/2`
- Scope classification: local, single-SharedTool Direct recipient-contract clarification with bounded downstream compatibility proof.
- Revision count: second and final permitted revision for the persisted diagnosis/plan lineage.

## Trigger, evidence, and product target

The trigger is the persisted real Direct terminal: the completed `shared_tool_semantics[1-2-3-4-5-6]` call in `run_4528cf8a411a4d8a82b6390465c6d138` failed as `direct_response_not_json`, produced no SharedTool Artifact, a failed WorkRecord, a blocking Finding, and a non-published Registry state. The diagnosis establishes a material recipient-contract omission but preserves the raw provider response as non-persisted.

The product target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe. This allow advances only the committed WorldArchitecture-to-SharedToolSemantics handoff. It proves neither later Design nodes, candidate isolation, Judge, package/Registry release, Repair, Expand, nor Consumer/SFT/RL completion.

The affected trust boundary is:

`frozen Architecture/Evidence -> SharedTool model-visible grammar -> unchanged Direct parser -> unchanged SharedTool compiler -> compiled SharedToolContract -> ToolSemantics -> Modeling -> later package/Registry consumers`.

## Findings

### Revision 2 resolves the prior block without broadening the parser or correction boundary

The plan explicitly selects the first, minimal route required by the prior block: leave `direct_response_not_json` terminal and disclose the existing SharedTool grammar/objective only. It does not route parser failures into local semantic correction, change the common Direct adapter, add observability/provenance machinery, or alter GraphRunner correction policy.

This matches the active behavior. `_json_object` rejects non-object/non-JSON content as `direct_response_not_json` at `agent_world/invocation.py:49-59`; `DirectChatBackend` raises that error after parsing the provider envelope at `agent_world/invocation.py:138-162`; and `_direct_json` converts every invocation failure into a non-correctable `DesignError` at `agent_world/design.py:543-569`. `GraphRunner` only grants its existing one correction when a rejected node error carries a safe correction packet (`agent_world/graph.py:481-539`, `agent_world/graph.py:671-680`). Thus the plan's requested terminal test is both necessary and compatible with the framework-owned boundary.

The binding common node contract says provider, transport, and JSON-parsing failures never enter local correction (`node-contracts.md:125-148`). Keeping this policy unchanged resolves the source-of-truth/root-output-error and task-contract conflict identified in the prior block; no generic Direct policy reconciliation is needed for this local revision.

### The disclosed grammar matches the current compiler, without a stronger partition claim

The current SharedTool compiler requires exactly the seven top-level fields; exact ordered group echo; 1..group-size outer and inner domain arrays; only group members with full set coverage; 0..8 bounded ordering/compensation text entries; and exactly one ordered error-policy object per frozen member (`agent_world/design.py:1245-1361`). The proposed grammar exposes those material constraints and the concise whole-object recheck objective while leaving framework ownership of group derivation, validation, compilation, digest, attempts, Findings, Judge, and release intact.

The compiler's current domain check verifies membership and set coverage, but does not prove disjoint or unique occurrences within each domain (`agent_world/design.py:1275-1303`; `agent_world/contracts.py:696-707`). Revision 2 correctly does not claim a stronger uniqueness/disjointness partition than that compiler implements. This is a compatibility fact, not authorization to weaken validation or introduce business-specific domain content. A future strict-partition semantic change requires its own diagnosis, plan, critic gate, implementation, and proof.

The existing model-visible value is only the seven field names (`agent_world/design.py:1364-1379`), while the task's SharedTool card still describes a different obsolete `ordered_tool_indexes/domains` shape (`node-contracts.md:357-380`). Replacing only that shape and card is therefore a coherent recipient-contract repair. It does not add a Skill, tool, workspace, profile instruction, fixed environment, business rule, group split, parser tolerance, or alternative execution path.

### Producer, consumer, and semantic-identity compatibility is explicit

The only producer semantic revision that changes is `shared_tool_semantics`: `_direct_commit` binds its exact effective projection and `output_shape` into semantic material (`agent_world/design.py:581-624`), and `GraphRunner.semantic_revision` hashes that material with the unchanged node declaration, output contract, prompt id, and route (`agent_world/graph.py:442-460`). Replacing the SharedTool shape therefore invalidates stale SharedTool work while leaving node identity, ports, edges, route, group derivation, and correction topology fixed.

The immediate consumer is each `tool_semantics` shard. It receives the compiled `SharedToolContract`, checks that the model echoes that frozen contract, and binds the same contract digest to each ToolDraft (`agent_world/design.py:1386-1535`). Crucially, the model projection excludes framework `artifact`/`work_refs` identities (`agent_world/design.py:150-162`), so a valid unchanged compiled contract has the same downstream semantic input even though the changed SharedTool producer has a fresh Artifact/Work provenance record. `DesignContract` then verifies group order and ToolDraft-to-SharedTool digest binding (`agent_world/contracts.py:958-1015`).

Later consumers preserve the same typed representation: candidate projections expose `shared_tool_contracts` unchanged (`agent_world/candidate.py:304-307`, `agent_world/candidate.py:753-763`); the package writes them unchanged into `world/rule_ir.json` (`agent_world/candidate.py:2085-2100`); and Registry cold-read requires the same fields and recomputes the same digest (`agent_world/candidate.py:2536-2564`). No Schema, Artifact kind, graph port, package ABI, Registry input, Agent path, or candidate-process capability changes under this allow.

### Native response format remains an unresolved, bounded non-claim

The actual Direct request contains model/messages/temperature/max-tokens only (`agent_world/invocation.py:113-122`), while the backend guidance describes native strict JSON Schema and a profile-matched safe probe as a separate request-transport fact (`.trellis/spec/agent_world/backend/index.md:1813-1890`). Revision 2 does not falsely rule that hypothesis out, and it does not add `response_format`, alter route/model/token/timeout/fallback behavior, or retry the old scene.

The plan correctly requires a new diagnosis and a safe profile/request-shape probe only if the same terminal recurs after this disclosed-shape change. That preserves the terminal parser policy for this lineage and prevents an unproven transport change from being smuggled into a recipient-contract repair.

## Owners and impact chain

| Boundary role | Owner / status under this allow |
| --- | --- |
| Frozen group, exact membership, bounds, parse, compiler, digest, Work/Finding, gate, Judge, and release | Framework-owned; unchanged |
| Shared atomicity/concurrency/idempotency/ordering/compensation/error-policy business meaning | Direct LLM proposal only; clarified grammar/objective |
| Parsed invalid SharedTool object | Existing one safe compiler correction remains available; unchanged |
| Non-JSON response | Existing terminal `direct_response_not_json`; unchanged |
| ToolSemantics and later Design consumers | Same compiled SharedToolContract; compatibility proof required |
| Agent and candidate-process paths | Unchanged and outside this repair |

The affected graph is the Direct Design graph only. `shared_tool_semantics` retains its declared Direct node, input ports, output port, and route (`agent_world/graph.py:162-180`); its direct successor remains ToolSemantics, with ModelingGate also receiving the compiled SharedTool artifacts. Expand and Consumer are not affected because no shared handoff representation or release behavior changes.

## Smallest allowed implementation and proof

1. Replace only the SharedTool `output_shape`/objective passed at `agent_world/design.py:1369-1379`, align only `node-contracts.md`'s `shared_tool_semantics[group]` section, and add focused tests. Do not edit `_direct_json`, `_json_object`, `DirectChatBackend`, GraphRunner, the typed compiler, NodeSpec declarations/edges, other Direct prompts, Agent code, candidate code, package/Registry code, or response transport.
2. Pin the exact SharedTool grammar/objective and frozen-group projection in focused tests; prove a current valid payload compiles to the same contract/digest and reaches the same ToolSemantics consumer contract.
3. Pin terminal parser behavior with a non-JSON completion: one physical call, original `direct_response_not_json` code, no output Artifact, failed WorkRecord, and blocking Finding. Separately retain existing parsed-object compiler correction behavior: at most one safe correction and no third call after a second invalid object.
4. Verify semantic identity: changing only the SharedTool output-shape material rotates only that node's semantic revision; Direct node declarations, edge/route/group/correction topology, generic parser/fallback paths, Agent paths, and candidate paths remain unchanged. Use a focused static/behavioral regression plus the required whole-diff scope check; do not add an abstraction to enforce it.
5. After implementation/check, append the required Product Alignment Checkpoint before and after the real proof. First invoke only the frozen failed-run SharedTool shard using its exact committed Architecture/Evidence inputs and inspect safe attempt/model/compiled-Artifact/WorkRecord/Observe facts. Then, only if it passes, run one fresh public Direct request to terminal Observe. A changed or repeated terminal starts a new diagnosis; no blind retry, output editing, model fallback, group split, or later-child work is permitted.

## Deterministic checks and true-boundary proof

- Focused pytest coverage for the exact SharedTool recipient grammar, valid current compilation, terminal non-JSON behavior, existing parsed-object correction limit, semantic revision isolation, and ToolSemantics contract compatibility.
- Existing graph regressions remain relevant: one safe correction is bounded and persisted, while provider/framework/candidate terminals receive no correction (`tests/test_graph_contracts.py:768-930`); Direct helper payloads preserve the shared system/user boundary (`tests/test_graph_contracts.py:1082-1094`).
- Run the plan's focused/full pytest, Ruff format/check, mypy, compileall, and a whole-diff scope check. Deterministic success is not a provider or product-release claim.
- The true-boundary proof is the single fresh SharedTool invocation with the exact committed failed-run parents, followed by a fresh public Direct run only after that narrow proof succeeds. Observe must be read after each terminal.

## Non-claims

- This allow does not prove that the disclosed grammar will make Luna produce JSON, that the endpoint supports native `response_format`, or that any provider limit is non-causal.
- It does not authorize changing parser classification, local-correction policy, raw-output retention, provenance storage, response transport, model, route, timeout, tokens, fallback, group topology, compiler semantics, or package/Registry behavior.
- It does not claim the current compiler enforces unique/disjoint domain membership; revision 2 deliberately describes no stronger partition property than the current compiler validates.
- It does not prove ToolSemantics, Modeling, Candidate, Integration, Judge, Package, Registry, Repair, Expand, or Consumer completion.

## Next permitted gate

The matching critic allow may be added to the task's implementation/check context by the main session. The next permitted action is the narrowly scoped implementation above, then independent checking and the specified real-execution proof. Stop and create a new Diagnosis Record before any response-mode/probe change or if a new terminal, producer/consumer effect, or scope expansion appears.

## Files Found

- `research/shared-tool-json-contract-plan.md` — revision 2 plan; supplied SHA-256 matches.
- `research/diagnosis-e2e-shared-tool-json-boundary.md` — persisted failed E2E chronology and causal boundary.
- `research/cross-layer-review-7c47c057-shared-tool-json.md` — prior block and its five required revision items.
- `agent_world/design.py` — model projection, common Direct adapter, SharedTool compiler, and immediate ToolSemantics consumer.
- `agent_world/invocation.py` — Direct request shape, JSON parser, terminal taxonomy, and retryable fallback boundary.
- `agent_world/graph.py` — node declaration, semantic revision, bounded correction transaction, Artifact/Work/Finding persistence.
- `agent_world/contracts.py` and `agent_world/candidate.py` — typed and package/Registry consumers of the compiled contract.
- `node-contracts.md` — binding common terminal rule and stale SharedTool prose.

## Related Specs

- `docs/agent-world-environment-generation.zh.md:421-445,601-635` — framework-owned output-contract/correction policy, SharedTool role, and downstream closure.
- `docs/direct-rewrite-execution-map.zh.md:72` — SharedToolSemantics is a Direct LLM Engineer transaction.
- `.trellis/spec/agent_world/backend/index.md:593-705,1466-1525,1813-1890` — Direct prompt-only boundary, SharedTool completion guidance, and native-structured-output probe requirement.
- `.trellis/spec/guides/foundry-product-alignment.md:1-70` — required checkpoint discipline; the real failure is already recorded in `research/product-alignment-checkpoints.md:2265-2270`.

## Caveats / Not Found

- The raw provider response remains intentionally unavailable; no conclusion about truncation, exact model behavior, or response-format capability can be drawn from this review.
- Current implementation checks member coverage, not duplicate/disjoint partition membership. This review does not convert that known implementation/property gap into a SharedTool prompt claim or a compiler change.
- No live call, retry, implementation edit, test/doc/product edit, or git operation was performed by this independent read-only critic.

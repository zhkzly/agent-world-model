# Research: cross-layer review — remaining Design Direct contract closure, revision 2

- Query: Fresh independent read-only final critic review of revision 2/2 after the real Direct/E2E terminal `run_1bec958e41ae4207beb4a7b40149f9c0`.
- Scope: internal; coordinated Design-source and local-validator closure. No Candidate, Judge, Registry, Repair, Expand, or Consumer implementation is in scope.
- Date: 2026-08-12
- Decision: allow
- Plan digest verified: `sha256:df78d60dce150753a8251e5f809321dc303f6fe0417fd02ae47ed7d6b7e13650`
- Plan revision: `remaining-design-direct-contract-closure`, revision 2/2.
- Critic revision count: 2 of the maximum 2 for this Diagnosis Record / plan lineage.

## Decision and Product Target

Allow the exact pinned revision only. It advances the Design portion of the required path: an arbitrary natural-language EnvironmentRequest must become evidence-grounded compiled Design semantics, then an independently exercised untrusted candidate, an immutable Registry EnvironmentPackage, and safe Observe facts. A repaired Direct source transaction, deterministic tests, or the diagnostic suffix alone is not product completion.

The observed terminal is a valid real-failure trigger: Architecture, Evidence, and SharedTool work committed, while `tool_semantics[register_member]` rejected the same incomplete RuleDraft root contract on both bounded calls. The persisted diagnosis establishes a causal hypothesis without claiming Candidate, Judge, Package, Registry, or release success.

## Prior Block Closure

Revision 2 completely addresses every item in `cross-layer-review-7c80f044-remaining-design-direct.md`:

1. **RuleDraft error kind.** The shared source ADT now explicitly states the exact errors-only grammar `[a-z][a-z0-9_]{0,63}` and its 1..64-code-point bound; non-error sections require null. This matches the current compiler’s `_NAME` rule and error-only branch (`agent_world/design.py:71`, `agent_world/design.py:442-458`). The plan requires the identical ADT for ToolSemantics, WorldRules, and TaskRequirement and a regression covering all three recipients.
2. **Curriculum names.** The plan states the exact `task_family_id` grammar `[a-z][a-z0-9_]{0,63}` (1..64), while dimensions and levels retain the currently accepted `[a-z][a-z0-9_-]{0,39}` grammar (1..40), including hyphens. It explicitly says this is disclosure, not tightening or normalization. That agrees with the current source compiler (`agent_world/design.py:1644-1654`) and cold `DifficultyLevel` / `DifficultyDimension` invariants (`agent_world/contracts.py:249-269`).
3. **Diagnostic partial suffix.** The real-proof section now confines the suffix to immutable Architecture and Evidence Artifact references from the failed public run, strict SharedTool regeneration, then only `tool_semantics[register_member]`. It expressly prohibits resume, adoption, publication, release inference, and Registry evidence. That boundary is compatible with the graph: Registry is reachable only through complete Design/Candidate/Judge/package handoffs, not a standalone Design shard (`agent_world/graph.py:203-229`, `agent_world/candidate.py:2865-2945`).

No unresolved substantive block remains. Because this is revision 2/2, this allow must not be read as authorization to broaden the plan; a changed digest, affected trust boundary, or later real terminal expires it.

## Scope, Owners, and Impact Chain

This is a **coordinated cross-node** repair, not a ToolSemantics-local patch. One hidden source IR is consumed by ToolSemantics, WorldRules, and TaskRequirement; SharedTool source echoes and its cold typed invariant cross the Design compiler boundary; Curriculum and TaskRequirement use the same frozen-index / typed-correction discipline. It remains the smallest coherent scope because compiled dataclasses, graph ports, node identities, routes, correction topology, candidate interfaces, and release protocol do not change.

| Boundary | Compatibility / owner fact |
| --- | --- |
| Direct LLM | Continues to propose only bounded business RuleDrafts, curriculum meanings/scopes, and public-goal selections. The five affected Design nodes remain `direct_llm`, direct route, no Skill (`agent_world/graph.py:151-210`). |
| Framework | Solely binds frozen group/tool/family coordinates, validates grammar and indexes, compiles Rule IR and typed contracts, derives digests, writes Work/Findings, runs ModelingGate, and owns release. Removing source echoes removes model authority rather than a compiled field. |
| Tool-enabled Agent | Research, build-plan, verifier, and candidate-build ownership is unchanged. No Design source node becomes an Agent or gains a Skill/workspace. |
| Candidate process | Remains downstream of a complete typed Design; it neither validates Design semantics nor gains package, Registry, or Observe authority. |

The impacted handoff remains:

`frozen Architecture + Evidence` -> `Direct source JSON` -> `framework compiler / typed DesignContract` -> `ModelingGate` -> `Candidate projection` -> `Package metadata` -> `Registry cold read` -> `safe Observe`.

The plan correctly keeps the downstream ABI intact. `ToolDraft`, `SharedToolContract`, `WorldRuleSet`, `CurriculumPlan`, and `TaskRequirement` remain compiled typed values (`agent_world/contracts.py:685-795`, `agent_world/contracts.py:958-989`). ModelingGate consumes the same ports (`agent_world/graph.py:213-229`); Candidate projections and package metadata serialize those typed values (`agent_world/candidate.py:753-763`, `agent_world/candidate.py:2086-2121`); Registry rechecks typed shared-contract digests and curriculum order (`agent_world/candidate.py:2476-2610`); Observe only reports a cold-read released closure (`agent_world/observe.py:76-144`).

## Contract and Validator Judgment

The plan’s echo removal is correct and bounded:

- SharedToolSemantics no longer has the model echo `tool_indexes` or policy coordinates. Framework binds the frozen ordered group, zips it to the ordered policy strings, and includes the injected coordinates in the compiled `SharedToolContract` and digest.
- ToolSemantics no longer emits `tool_index` or the frozen shared contract; framework already has the selected surface and shared contract when constructing the unchanged `ToolDraft` (`agent_world/design.py:1386-1506`).
- TaskRequirement no longer emits `task_family_index`; framework injects the frozen family index when constructing the unchanged typed requirement (`agent_world/design.py:1832-1939`).

The exact-partition repair is necessary, not a new framework: today the compiler and `SharedToolContract` use coverage sets that can admit duplicates/overlap, and cold typed validation does not require ordered policy coordinates (`agent_world/design.py:1275-1334`, `agent_world/contracts.py:685-707`). Revision 2 narrows this to the existing compiler and dataclass: integer frozen members exactly once in each partition, frozen ordered group binding, and ordered policy binding. The registry’s existing digest reconstruction remains compatible only if the compiler digests that same framework-injected typed representation; revision 2 states this explicitly and requires a package-projection regression.

The proposed type-first checks and narrow Curriculum `ValueError` translation are also locally correct. They prevent malformed RuleDraft citation, Curriculum tool/citation, Task public-goal, and Shared-domain values from reaching `set(...)` and leaking raw Python errors. The plan forbids coercion, a blanket exception wrapper, a schema engine, or a validator DSL.

## Exact Allowed Write Scope

This allow permits only the following bounded implementation slice:

- `agent_world/design.py`: one shared RuleDraft source declaration; the five named Design source-shape/compile paths; framework injection and digest binding for removed echoes; listed type-first validators; narrowly scoped Curriculum typed-error translation.
- `agent_world/contracts.py`: only the existing `SharedToolContract` invariant necessary for exact partitions and ordered policy coordinates.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md`: only the common RuleDraft declaration and the SharedToolSemantics, ToolSemantics, WorldRules, CurriculumPlan, and TaskRequirement source cards.
- Focused deterministic coverage in the existing Design/graph/release test surfaces needed to prove the listed contracts.

`agent_world/graph.py`, `agent_world/candidate.py`, and `agent_world/observe.py` are compatibility consumers, not approved implementation targets. No new node, graph, route, retry mode, Agent Skill, candidate path, generic schema component, persistence surface, Registry artifact, or release mechanism is allowed. Production Python is currently 10,296 lines, leaving at most 24 net lines under the plan’s 10,320 ceiling; obsolete echo checks/string duplication must be removed if needed.

## Required Deterministic Checks and Proof Order

The implementation/check gate must prove, at minimum:

1. Byte-identical shared RuleDraft grammar at all three recipients, including section-specific error/citation constraints and the exact error-name bound.
2. Current Curriculum field/card grammar, including valid hyphenated dimension/level names without normalization or tightening.
3. Absence of frozen-coordinate/shared-contract/digest echoes from source outputs, with exact framework-injected compiled values and semantic-revision rotation only.
4. Compiler and cold typed SharedTool rejection of duplicate, overlap, unknown, and non-integer members, with frozen-order policy binding and an exact split accepted.
5. Typed, path-bearing Design errors rather than raw `TypeError`/named Curriculum `ValueError` for the listed malformed values.
6. Unchanged graph/node/edge/route/group topology, one local correction (two calls maximum), full Design/ModelingGate typed closure, and package/Registry projection compatibility.

Run the focused tests, then full pytest, Ruff format/check, mypy, compileall, legacy-reference firewall, diff review, and the production-line ceiling before any provider call.

Only after that independent implementation check passes, perform the prescribed real-proof sequence:

1. The diagnostic immutable-parent partial suffix described above; inspect only Work/Artifact/operation facts and safe Observe. It is non-resume, non-adopt, non-publish, and non-Registry evidence.
2. If that suffix passes inside existing correction bounds, run one fresh public Direct request to terminal Observe so WorldRules, CurriculumPlan, and TaskRequirement execute naturally.
3. Any new terminal requires a new Observe-driven Diagnosis Record; no blind retry, output editing, model/response-mode change, node split, or later-child work follows from this allow.

## Non-Claims and Next Permitted Gate

- This review changed no code, tests, plan, JSONL, checkpoints, or product artifact.
- It does not claim a provider success, full Direct E2E success, Candidate build, independent Judge result, package, Registry publication, or released EnvironmentPackage.
- It does not record credentials, prompt bodies, sealed content, or model transcripts.
- It does not authorize a third plan revision, a runtime Critic component, a second Judge/Release owner, or scope expansion into Repair, Expand, or Consumer.

The next permitted gate is for the main coordinator to add this exact current allow record to the required implementation/check context, then dispatch the bounded implementation. The allow expires on any plan-byte, relevant trust-boundary, or real-scene change.

## Files Found

- `AGENTS.md` — project product target, pre-change gate, and Direct/Agent/Framework authority boundaries.
- `docs/agent-world-environment-generation.zh.md` — canonical Direct source/Rule/Curriculum/Shared/release contract.
- `docs/direct-rewrite-execution-map.zh.md` — derived execution-kind and owner map.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-e2e-remaining-direct-contract-closure.md` — persisted real-failure diagnosis.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/cross-layer-review-7c80f044-remaining-design-direct.md` — prior block and exact revision requirements.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/remaining-design-direct-contract-closure-plan.md` — pinned revision-2 plan reviewed here.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — current Direct source-card ABI.
- `agent_world/design.py` and `agent_world/contracts.py` — source compiler and cold typed-contract evidence.
- `agent_world/graph.py`, `agent_world/candidate.py`, and `agent_world/observe.py` — unchanged consumer-chain evidence.
- `tests/test_design_semantics.py`, `tests/test_graph_contracts.py`, and `tests/test_direct_release.py` — focused deterministic regression surfaces.

## External References

None. This decision is based on the repository’s canonical product document, current source, task records, and safe persisted run facts.

## Related Specs

- `.trellis/spec/guides/foundry-product-alignment.md`
- `.trellis/spec/guides/agent-llm-node-debugging.md`
- `.trellis/spec/agent_world/backend/index.md`

## Caveats / Not Found

The review deliberately does not treat the partial suffix as a recovery or release path. The failed run did not reach Candidate, Judge, Package, Registry, or released Observe; those remain unproved until the stated fresh public Direct proof reaches its own terminal scene.

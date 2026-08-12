# Research: cross-layer review — WorldArchitecture Field contract, revision 2

- Query: Does plan digest `322bfa3a31ed44a281045469aff9daa9a1a4df6fe27ba6afaa388b32b0642eec` exactly close revision-1's Field disclosure and three typed compiler gaps without expanding scope?
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `322bfa3a31ed44a281045469aff9daa9a1a4df6fe27ba6afaa388b32b0642eec`.
- Plan lineage / revision: `world-architecture-visible-field-contract`, revision 2/2.
- Scope classification: local Direct producer/compiler boundary. The output-shape text and pre-constructor validation change; NodeSpec, graph edges, correction policy, route, Artifact ABI, and downstream consumer contracts do not.

## Trigger and evidence

The applicable real scene is `run_5c648fca95e64bc08107b70a48127854`: the prompt-visible shape omitted the Field rules, the first real Luna proposal reached the compiler, and the second exhausted the one already-authorized local correction. The persisted diagnosis identifies an incomplete Direct output-contract disclosure, not a provider, route, or retry defect.

Revision 1 correctly blocked because `_field` can reach `FieldDeclaration` with non-enum/list values (`agent_world/design.py:213-256`; `agent_world/contracts.py:522-528`), and owner uniqueness can reach the `EntityDeclaration` and `ToolSurface` constructors (`agent_world/contracts.py:604-635`). `GraphRunner` only persists the safe failure transaction for `NodeExecutionError` subclasses (`agent_world/graph.py:487-539`, `716-783`).

## Review findings

Revision 2 closes exactly those gaps:

1. It replaces the terse architecture literal (`agent_world/design.py:1203-1208`) with one compact actual Field contract used for entity fields, tool arguments, and tool results. It preserves the current bounds at their three compiler call sites: entity `1..24`, argument `0..24`, and result `1..24` (`agent_world/design.py:1003-1018`, `1093-1124`). The stated snake-name, closed category, Boolean required, conditional finite-domain, and owner-local uniqueness rules match the current compiler/dataclass contract.
2. It preserves the necessary reference distinction: entity fields must close over declared entity names after entity compilation (`agent_world/design.py:1036-1047`), while existing tool fields accept only `null` or a snake-form reference at their Field boundary (`agent_world/design.py:244-255`). It therefore does not add an unimplemented tool-reference closure rule.
3. It requires typed, path-addressed `DesignError` prechecks before dataclass construction for all three revision-1 holes: nonempty values on non-enum/list fields; duplicate entity/tool owner-local field names; and duplicate one-based actor indexes. This makes those proposal errors enter the existing `world_architecture_invalid` correction/failure path without a broad catch.
4. One local field-array compiler is sufficient to retain each existing collection bound and perform duplicate-name checks. The plan explicitly prohibits a public helper, schema framework, generic exception catch, new type/module/node, retry, model/route switch, or compatibility path.

## Impact chain and compatibility

`Direct output_shape` -> Luna complete proposal -> Designer `_field` / local collection prechecks -> existing `GraphRunner` typed correction-or-failure transaction -> unchanged `WorldArchitecture` Artifact -> existing SharedToolSemantics, ToolSemantics, WorldRules, Curriculum, Task, Modeling, Builder, Judge, Package, Registry, and Observe consumers.

Designer remains the sole owner of both the model-facing semantic proposal boundary and its deterministic compiler. The accepted `WorldArchitecture` value and its downstream schema/Artifact shape remain unchanged. Updating the output shape does intentionally produce a new semantic input identity through `_direct_commit` semantic material (`agent_world/design.py:598-613`; `agent_world/graph.py:442-460`); that is required provenance for a changed Direct recipient contract, not an Artifact ABI or downstream semantic change.

## Smallest allowed implementation and proof

- Implement only the literal disclosure and the three prechecks described in revision 2, with at most one local field-array helper.
- Add focused deterministic tests that inspect the captured recipient `output_shape`, cover all three Field collections and the entity/tool reference distinction, and show each new precheck yields a path-addressed `world_architecture_invalid` `DesignError` through the existing transaction rather than a raw exception. Retain the separate observed empty-domain first-invalid/second-valid correction regression.
- Then run the planned deterministic quality checks. After those pass, the smallest true-boundary proof is one fresh `world_architecture` Luna transaction using the same need/evidence class, followed immediately by WorkRecord and Observe inspection.

## Product target, non-claims, and next gate

The product target remains: an arbitrary natural-language EnvironmentRequest becomes an evidence-grounded executable environment, is independently verified in an isolated boundary, and is published as an immutable Registry EnvironmentPackage with only safe Observe facts. This approval advances only the Direct Architecture proposal/compiler handoff; it does not claim a successful architecture turn, subsequent Design nodes, Candidate, Integration, Judge, Package, Registry, Repair, Expand, Consumer, or end-to-end product completion.

Next permitted gate: implementation confined to this matching revision-2 plan, followed by deterministic checking and the separately authorized fresh true-boundary proof. This allow expires if the plan digest, affected boundary, or relevant real scene changes.

## Files found

- `research/diagnosis-world-architecture-visible-field-contract.md` — real failure chronology and causal attribution.
- `research/cross-layer-review-9c95eb3f-world-architecture-field.md` — revision-1 block and exact required closure.
- `research/world-architecture-visible-field-contract-plan.md` — reviewed revision-2 plan.
- `agent_world/design.py` — Direct prompt projection and WorldArchitecture compiler.
- `agent_world/contracts.py` — Field and owner dataclass invariants.
- `agent_world/graph.py` — typed correction/failure persistence path.
- `tests/test_design_semantics.py` — focused Direct recipient/correction regression pattern.

## Related specs and external references

- `docs/agent-world-environment-generation.zh.md:596-646` — Direct WorldArchitecture is one bounded prompt-only semantic transaction; framework owns schema/reference/closed-shape compilation.
- `docs/direct-rewrite-execution-map.zh.md:62-116` — WorldArchitecture is a Direct LLM node with no Skill, tools, workspace, or release authority.
- `.trellis/spec/agent_world/backend/index.md:325-379,899-937` — compact source semantics and model-visible structural choices; cross-object closure belongs in typed compiler preflight.
- `.agents/skills/agent-world-cross-layer-critic/SKILL.md` — this is a development gate, not runtime authority.
- External references: none. No live provider, retry, or implementation action was run in this review.

## Caveats / Not Found

- This review does not approve changing tool-field reference semantics, relaxing Field invariants, accepting invalid proposals, or broadening error handling.
- The planned fresh live proof remains required and any different terminal begins a new diagnosis rather than another revision of this lineage.

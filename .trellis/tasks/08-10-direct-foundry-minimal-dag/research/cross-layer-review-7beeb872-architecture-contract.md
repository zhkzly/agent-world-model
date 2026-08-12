# Research: cross-layer review — WorldArchitecture contract disclosure

- Query: Review plan digest `7beeb872f2cd53c4e8eb6c180973ca9438d002ba263f2c49b793d98d69a6ec04` after Direct run `run_66a0ba4ecc274c20a112e4ed8cf268be`.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: block**

- Plan digest: `7beeb872f2cd53c4e8eb6c180973ca9438d002ba263f2c49b793d98d69a6ec04`
- Plan revision: unlabelled initial repair plan; first critic review in this lineage.
- Scope classification: local Direct producer-instruction repair, pending the correction below.
- Trigger and evidence: the persisted Diagnosis Record and PAC-33 establish a real terminal: first correction at `$.name`, then rejection at `$.tools[0].name`; one failed Direct WorkRecord, no output, and `not_published` release. The compiler and one-correction boundary behaved correctly.

The plan correctly preserves the product target: arbitrary natural-language request -> compiled Design -> Candidate -> independent Judge -> Registry package -> safe Observe. Its intended changed handoff is only the pre-invocation `world_architecture` instruction; the compiled architecture Artifact, ports, WorkRecord, owner, CandidateGraph, Package, Registry, Repair/Expand parent seam, and Consumer seam remain unchanged.

## Findings

### Blocked criterion: the stated disclosure is not yet the complete existing compiler contract

`_direct_architecture` enforces more than the plan's enumerated kebab/snake names, tool count, and field-list bounds: closed authority-free root and tool objects; nonempty bounded `name`, `summary`, and `description`; name maxima and exact identifier patterns; unique tool names; `arguments` may be empty but `result_fields` may not; and each field list has unique nonempty items with its existing item bound. See `agent_world/design.py:692-780` and helpers at `agent_world/design.py:102-139`.

The proposed focused test only says it will look for identifier and collection constraints plus compile one valid proposal. That does not prove the entire model-facing string covers these remaining enforced rules, so a subsequent one-correction failure could still be caused by the same undisclosed-contract defect.

### Required plan revision

Keep the repair local. Revise only the written plan to require one canonical bounded `output_shape` string that explicitly represents every current compiler condition above, including the empty/nonempty distinction, uniqueness, and text/item limits. The capturing-stub regression must assert that exact full model-facing contract, then submit a valid proposal and assert the committed Artifact remains the existing shape. Do not change compiler logic, output Artifact fields, correction policy, topology, or any later node.

After the plan revision, rerun this critic before implementation. The smallest proof remains deterministic checks, then the same frozen Luna `world_architecture` proof and an immediate Observe read.

### Later Direct nodes

`tool_semantics`, `curriculum_plan`, and `task_requirement` also have terse shapes beside stricter compiler checks (notably frozen-key/scalar and bounded/unique collection semantics) in `agent_world/design.py:829-1208`. This is the same *risk class*, but not an affected consumer of the architecture instruction: their compiled inputs, Artifacts, ports, owners, and later Candidate/Repair/Expand/Consumer handoffs are unchanged by this plan. No real failure evidence identifies them in this diagnosis. They therefore do not justify broadening this repair into a coordinated multi-node change. They remain an explicit non-claim and require their own evidence-backed diagnosis/plan if a later proof reaches a matching terminal.

## Compatibility and ownership

- Producer: `DesignExecutor._direct_architecture` supplies the Direct model instruction.
- Owner/compiler: EnvironmentDesigner/framework retains closed-shape validation and Artifact commit.
- Immediate consumers: `shared_tool_semantics`, `tool_semantics`, `world_rules`, `curriculum_plan`, `task_requirement`, and `modeling_gate` consume only the unchanged compiled `architecture` Artifact through the declared DesignGraph edges (`agent_world/graph.py:144-211`, `agent_world/graph.py:316-334`).
- Later consumers: CandidateGraph, Package, Registry, Expand, and Consumer receive no changed field or authority. This review authorizes none of them.

## Files found

- `research/diagnosis-direct-proof-5-undisclosed-architecture-contract.md` — causal diagnosis and rejected shortcuts.
- `research/direct-world-architecture-contract-plan.md` — reviewed local repair plan.
- `research/product-alignment-checkpoints.md` (PAC-33) — product alignment and real-scene facts.
- `agent_world/design.py` — Direct projections and framework compilers.
- `agent_world/graph.py` — fixed DesignGraph ownership and handoffs.
- `docs/agent-world-environment-generation.zh.md` and `docs/direct-rewrite-execution-map.zh.md` — product and Direct authority contracts.

## Non-claims and next permitted gate

This block does not claim a WorldArchitecture commit, valid later Design node, Candidate, Judge, Registry release, Repair, Expand, Consumer, or E2E success. No external references were needed. The next permitted gate is a revised local plan that addresses the exact disclosure/test gap, followed by a fresh independent critic review; implementation and a new live call are not yet permitted.

## Caveats / Not Found

The later terse Direct shapes are static compatibility risks, not proof that those nodes have failed in this run. The block is limited to complete disclosure of the already observed WorldArchitecture compiler contract.

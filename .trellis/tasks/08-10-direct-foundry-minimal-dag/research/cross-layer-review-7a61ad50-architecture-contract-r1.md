# Research: cross-layer review — WorldArchitecture contract disclosure R1

- Query: Independently review R1 plan digest `7a61ad505b522b50ab51c5ce35e384fc6b9a82c9b426d2b6b9938b07fa1bb0cc` after Direct terminal `run_66a0ba4ecc274c20a112e4ed8cf268be`.
- Scope: internal
- Date: 2026-08-11

## Decision

**Decision: allow**

- Plan digest: `7a61ad505b522b50ab51c5ce35e384fc6b9a82c9b426d2b6b9938b07fa1bb0cc` (verified as the SHA-256 of the complete R1 plan file).
- Plan revision: R1 of `direct-world-architecture-contract-plan.md`.
- Scope classification: local Direct producer-instruction repair.
- Revision count: one written revision after the predecessor block; this is the final permitted revision/review in this Diagnosis Record lineage.
- Trigger and evidence: Diagnosis Record `diagnosis-direct-proof-5-undisclosed-architecture-contract.md` and PAC-33 record the real Luna terminal: the first proposal was corrected at `$.name`, the corrected proposal then failed at `$.tools[0].name`, and the run has one failed Direct-LLM WorkRecord, no output, and `not_published` release. The compiler, correction cap, failure evidence, and non-release behavior remain correct.

The product target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe. This plan advances only the first Direct semantic proposal boundary; it neither claims nor changes any later Design, Candidate, Judge, Registry, Expand, or Consumer outcome.

## Findings

### R1 closes the predecessor disclosure gap

The exact canonical `output_shape` in R1 covers every existing proposal-owned condition in `DesignExecutor._direct_architecture` and its `_text`/`_list` helpers:

- one closed, authority-free root object with exactly `name`, `summary`, and `tools`;
- nonempty bounded root name and summary, including the exact 2--80-character kebab-name pattern;
- a nonempty 1--4-item tools array;
- one closed tool object with exactly `name`, `description`, `arguments`, and `result_fields` for each item;
- nonempty bounded tool name and description, including the exact 1--60-character snake-name pattern;
- unique tool names;
- `arguments` as a 0--6-item (empty permitted) unique nonempty string array with 60-character items; and
- `result_fields` as a 1--6-item (nonempty required) unique nonempty string array with 60-character items.

The compiler's existing trimming/canonicalization is retained rather than introduced: `_text` strips accepted text before it is committed, and `_list` applies the same helper before uniqueness checks. The R1 string correctly instructs the model to supply the stricter canonical text values; this does not change the output Artifact or add normalization. The listed authority names are already excluded by the closed-root shape, so their explicit prohibition is compatible, defense-in-depth disclosure rather than a new authority rule. Evidence: `agent_world/design.py:102-139`, `agent_world/design.py:692-793`, and plan R1 `direct-world-architecture-contract-plan.md:15-31`.

### Exact regression and one-call commit are sufficient for this local contract change

The capturing-stub regression is required to assert equality of the full canonical string delivered through the real `_direct_architecture` transaction, not partial keyword presence. It then returns a valid first proposal and asserts exactly one invocation plus the unchanged compiled Artifact payload. Together, these facts prove the changed producer handoff is exact, all previously hidden compiler conditions are disclosed before the initial model proposal, and the framework compiler/commit boundary still produces the same architecture Artifact. A separate matrix of invalid compiler inputs is not required for this repair: the compiler is intentionally unchanged and the predecessor block specified this exact string-plus-valid-commit proof as the smallest sufficient deterministic regression.

The real boundary proof remains distinct: after deterministic checks, rerun the frozen Luna `world_architecture` proof and immediately read Observe. A successful node WorkRecord proves only this model-facing transaction; any new safe terminal requires a new Observe -> Diagnosis Record -> repair-plan lineage.

## Impact chain and compatibility

```text
Direct LLM producer: _direct_architecture output_shape
  -> unchanged Designer compiler and committed architecture Artifact
  -> unchanged shared_tool_semantics / tool_semantics / world_rules /
     curriculum_plan / task_requirement / modeling_gate consumers
  -> unchanged CandidateGraph -> Judge -> Package -> Registry -> Observe
```

- Owner: EnvironmentDesigner/framework remains the sole owner of closed-shape validation and Artifact commit. The Direct LLM receives no routing, gate, repair, budget, or release authority.
- Producer change: only the pre-invocation `output_shape` argument at `agent_world/design.py:783-792`.
- Immediate-consumer compatibility: every existing downstream Design edge consumes the same compiled `architecture` output port (`agent_world/graph.py:318-334`); no compiled field, identifier form, Artifact envelope, WorkRecord, port, owner, or dependency changes.
- Later-consumer compatibility: CandidateGraph, Package, Registry, safe Observe, future Repair, Expand parent handoff, and Consumer package handoff receive no new Artifact or meaning. No coordination with them is needed.

## Smallest allowed implementation and proof

1. Replace only the existing `_direct_architecture` `output_shape` literal with R1's exact canonical string; do not alter `_direct_commit` or compiler logic.
2. Add one focused capturing-stub test that asserts exact shape equality, a valid single direct invocation, and the exact existing compiled Artifact payload.
3. Run deterministic checks, then the same frozen real Luna node proof, followed immediately by Observe.

No external references are required.

## Non-claims and next permitted gate

This allow does not claim a committed WorldArchitecture from a real provider, a successful later Direct node, modeling pass, Candidate, Integration, Judge, package, Registry publication, Repair, Expand, Consumer, or end-to-end completion. It does not authorize a generic schema system, retries, model/route changes, compiler relaxation, output normalization, topology changes, historical-run mutation, or a broader patch to later terse model contracts.

The next permitted gate is the narrowly scoped implementation of this exact R1 plan. Before any claim beyond the deterministic regression, the implementer must run the specified real Luna node proof and read Observe. Any material change to this plan digest, the architecture trust boundary, or the relevant real scene expires this allow.

## Files found

- `research/diagnosis-direct-proof-5-undisclosed-architecture-contract.md` — persisted causal diagnosis and rejected shortcuts.
- `research/direct-world-architecture-contract-plan.md` — exact R1 plan and digest.
- `research/cross-layer-review-7beeb872-architecture-contract.md` — predecessor block and required revision criteria.
- `research/product-alignment-checkpoints.md` — PAC-33 real-scene and product-alignment evidence.
- `agent_world/design.py` — current producer, compiler, and helper conditions.
- `agent_world/graph.py` — unchanged DesignGraph consumers and transaction/commit boundary.
- `tests/test_graph_contracts.py` — existing transaction and correction regression patterns.

## Caveats / Not Found

Later `shared_tool_semantics`, `tool_semantics`, `curriculum_plan`, and `task_requirement` shapes remain a static risk class only. They are not changed consumers and no real failure evidence in this lineage identifies them; they remain explicit non-claims rather than grounds for a broader patch.

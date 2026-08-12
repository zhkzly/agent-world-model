# Research: cross-layer review — WorldArchitecture purpose normalization

- Query: Is plan `5bf0e4ba8d74dccaf225aba2cd1aa19b3cfe83e2f8f281492c8e3a9700391b0b` the smallest correct framework-vs-LLM ownership repair after Luna ignored the disclosed `boundary.purpose` 160-character bound twice?
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: block**

- Plan digest: `5bf0e4ba8d74dccaf225aba2cd1aa19b3cfe83e2f8f281492c8e3a9700391b0b` (independently recomputed; exact match).
- Plan lineage / revision: `world-architecture-purpose-normalization`, revision **1/2**.
- Revision count: first critic review; one plan-only revision remains in this lineage.
- Scope classification: **coordinated Direct semantic-projection change**, not an Artifact-shape or control-plane change. The producer code may remain local, but accepting a longer source value while storing a lossy prefix changes the committed `WorldArchitecture` supplied to later Design work, Builder, package metadata, and Registry cold-read.
- Trigger: real proof `run_1b81e19380194e13a406f10dfcf3d0df` made two complete Luna proposals from the same real 28-claim/6-citation evidence class. Both failed only at `$.boundary.purpose`; the second had the exact disclosed 160-character condition and exhausted the one correction. The failed WorkRecord has no architecture output, blocks release, and Observe reports `not_published`.
- Diagnosis evidence: `diagnosis-world-architecture-purpose-policy-mismatch.md` correctly rules out transport, JSON parsing, token ceiling, and the sparse-source contract. It establishes that making the model own the current storage limit is a bad fit. It does **not** establish that discarding text after character 160 preserves the business meaning later consumers receive.
- Affected trust boundary: `WorldArchitecture Direct proposal -> Designer compiler/storage transform -> immutable WorldArchitecture Artifact -> WorldRules/Curriculum/Builder/package consumers -> Registry/Observe provenance`.

## Product Target, Owners, and Impact Chain

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe.

```text
EnvironmentRequest -> Research evidence -> WorldArchitecture proposal
-> Designer compiler / committed architecture
-> WorldRules + Curriculum + ModelingGate -> EnvironmentDesign
-> BuildPlan + CandidateBuild -> Integration/Judge -> Package -> Registry -> Observe
```

- The Direct LLM owns the boundary's business description; the Designer owns closed shape, deterministic compilation, Artifact commit, and only an authorized correction. `GraphRunner` owns the two-attempt transaction and semantic-revision persistence.
- The source-of-truth defines `WorldSpec`, including `WorldBoundary`, as the typed semantic center (`docs/agent-world-environment-generation.zh.md:165-181`). Its package-identity criteria name role/authority, system of record, resource graph, state-transition authority, tool namespace, and invariants—not free-form purpose prose (`docs/agent-world-environment-generation.zh.md:183-193`). That supports keeping identity/execution fields strict, but does not by itself authorize loss of a purpose that later models receive.
- The plan correctly leaves `boundary.name`, `system_of_record`, `authority`, actors, entities, tools, rules, routes, correction budget, and release authority untouched. No new node, retry, schema platform, or control plane is warranted.

## Blocking Findings

### 1. The plan asserts, but does not prove, that a lossy prefix is a safe storage projection

Current code rejects a stripped purpose over 160 (`agent_world/design.py:1000-1010`). The proposed transform accepts every nonempty string and maps it to `purpose.strip()[:160]`. That is a new acceptance transform, not merely formatting: different proposals with a common 160-character prefix collapse to the same immutable Artifact, and a qualifier after that prefix is not available to any consumer.

The plan calls this field "only descriptive," but the current task contract does not establish that classification. `node-contracts.md` makes it part of `WorldArchitectureSourceDraft` and says text is capped at 4096 UTF-8 characters (`.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md:333-355`); neither that contract nor the source-of-truth states a 160-character lossy-storage policy. Existing implementation behavior is not sufficient authority to overwrite that unresolved meaning.

This is not a reason to normalize identity/execution data. It is a reason to distinguish two alternatives honestly:

1. **Recommended smallest revision:** use a non-lossy, task-contract-aligned bound after resolving its exact unit, so all accepted trimmed purpose text is retained. This still removes the failed 160-character policy and needs only the same local compiler/shape/test scope.
2. If a 160-character prefix is intentionally a display/storage policy, obtain an explicit product decision that `boundary.purpose` may lose trailing business context, then treat the change as a coordinated semantic-projection policy rather than claiming unchanged downstream semantics. Without that decision, a revised plan should not seek `allow` for lossy truncation.

### 2. Character-unit and shape contracts are ambiguous

`str.strip()`, `len()`, and slicing in Python use Python `str` code-point behavior; they do not count UTF-8 bytes or user-visible grapheme clusters. The plan says "first 160 Python characters," while the task contract says "4096 UTF-8 characters." It must resolve this discrepancy instead of assuming the existing ASCII regression defines the public contract.

If the 160 policy remains, the revised plan must explicitly say: trim first; require a `str` whose trimmed value is nonempty; store the first 160 Python Unicode code points; a combining sequence or ZWJ grapheme may be split; no byte or grapheme counting is performed. If that visible-text behavior is unacceptable, it is a product decision, not a hidden helper requirement.

The proposed shape wording `purpose:concise_business_text;framework_storage<=160` is also too imprecise for a closed Direct output contract. It must unambiguously distinguish the model's accepted input (`str`, trimmed nonempty) from the framework's stored representation and must not imply that a 161-character proposal remains invalid. The shape must continue to state the unchanged 160 limits only for `name`, `system_of_record`, and `authority`.

### 3. Empty correction and semantic identity need exact proof

The new only-rejectable purpose case is whitespace-only/non-string input. Its correction must no longer say "at most 160 characters," because length is no longer the violation. The plan names the path/code/category but not the exact safe condition or assertion that the second Direct call receives that new condition.

The existing identity mechanism is sufficient and should be reused: WorldArchitecture includes its rendered `output_shape` in semantic material (`agent_world/design.py:607-623`), and `GraphRunner.semantic_revision` hashes it into the effective projection identity (`agent_world/graph.py:442-460`). No `NodeSpec` field, Artifact kind, or compatibility path is needed. But the plan must require a regression proving that the changed shape yields a new WorldArchitecture semantic revision and that no historical accepted Architecture is silently treated as accepted under the new transform.

### 4. Downstream compatibility is not unchanged merely because the Artifact schema is unchanged

The Artifact's field shape remains `WorldBoundary.purpose: str`, but its content and digest change. Consumers include:

- `world_rules` and `curriculum_plan`, which receive the full `json_value(architecture)` in Direct inputs (`agent_world/design.py:1599-1608`, `1813-1832`);
- Candidate build, which receives the full architecture projection (`agent_world/candidate.py:752-763`);
- package generation, which persists that architecture in `world/world_spec.json` (`agent_world/candidate.py:2085-2091`);
- ModelingGate and all dependency-linked Artifacts, which bind the Architecture Artifact digest (`agent_world/design.py:2098-2125`).

`SharedToolSemantics`, `ToolSemantics`, and task-rule compilation use more limited projections where appropriate, and no deterministic execution field was found to branch directly on `boundary.purpose`. That is useful compatibility evidence, but it does not prove that Direct/Agent model consumers can treat a truncated business description as semantically equivalent. The plan's generic "downstream compiled-artifact assertions" is not enough to cover this chain.

## Required Plan Revision

Revise the plan only to revision 2/2. It must:

1. Choose and cite the authoritative non-lossy-or-lossy storage policy. Resolve the current 4096-versus-160 and UTF-8-versus-Python-code-point discrepancy. Do not make a new arbitrary 160 policy appear as an implementation detail.
2. If retaining first-160 truncation, record the explicit product decision described above; inventory the four consumer classes above and state that they deliberately receive the normalized committed value. Do not claim their semantic input is unchanged. If that decision is unavailable, take the non-lossy local alternative instead.
3. State an exact `world_architecture` shape literal: it must preserve all non-purpose limits and sparse grammar, disclose trimmed nonempty purpose input, and describe any framework projection without reintroducing a model-facing numeric rejection.
4. State the exact empty/non-string correction tuple and preserve one correction only for that true proposal defect. A 161+ nonempty proposal must make one call and no correction only if the selected policy accepts it.
5. Add focused deterministic checks for:
   - whitespace-only purpose -> the exact new correction and failed WorkRecord;
   - ASCII over-limit input and a multi-byte/combining-Unicode case -> the chosen unit, trim order, and exact persisted value;
   - a changed WorldArchitecture semantic revision due to the changed shape/acceptance transform, with the unchanged NodeSpec/edge/route/correction policy;
   - Artifact payload plus representative direct, Builder, and package projections receiving the same committed normalized value, rather than raw proposal text;
   - unchanged rejection of all identity/execution fields and unchanged sparse-field contract.
6. Retain the bounded in-place implementation budget: no shared `_text` change, helper/type/module, new Artifact, new node, new retry, route/model switch, compatibility form, or schema/prompt framework. Keep the stated production-Python cap at 10,299 lines; the current count is 10,298.

## Smallest Proof Plan

- Deterministic guards after a revised allow: focused and full pytest, Ruff format/check, mypy, compileall, diff check, and line count. These prove the local transform and dependency identities, not the product outcome.
- True-boundary proof: one fresh WorldArchitecture invocation with the same real 28-claim/6-citation evidence class, followed immediately by WorkRecord and Observe inspection. It must show the selected storage policy, not merely that the node passes.
- Only after that local proof passes, run the planned fresh full CLI request and inspect Observe. A different terminal begins a new diagnosis; it must not be explained away as purpose normalization success.

## Non-Claims and Next Permitted Gate

This review authorizes no code/test edits, provider call, retry, manifest update, or implementation dispatch. It does not claim WorldArchitecture success, complete Design, Candidate, Integration, Judge, Registry, Repair, Expand, Consumer, or E2E success.

**Next permitted gate:** revise only `world-architecture-purpose-normalization-plan.md` to revision 2/2, address every blocker above, recompute its digest, and submit that new digest to a fresh independent cross-layer critic. If the revised plan still requires lossy 160-character storage without a product decision, the next gate is `needs_human`, not implementation.

## Files Found

- `docs/agent-world-environment-generation.zh.md` — source-of-truth for WorldSpec, ownership, identity, Direct semantics, and proof boundaries.
- `docs/direct-rewrite-execution-map.zh.md` — Direct node owners, consumer flow, and no-Skill Direct contract.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd.md,design.md,implement.md,node-contracts.md}` — active Direct contracts, especially the binding WorldArchitecture output and current text-cap statement.
- `research/world-architecture-text-bound-live-proof.md` — durable real proof failure.
- `research/diagnosis-world-architecture-purpose-policy-mismatch.md` — causal diagnosis used by this review.
- `research/world-architecture-purpose-normalization-plan.md` — reviewed plan revision and digest.
- `agent_world/design.py` — local compiler, output shape, model projections, ModelingGate inputs, and semantic-material construction.
- `agent_world/graph.py` — semantic-revision, correction, Artifact, and WorkRecord persistence.
- `agent_world/candidate.py` — Builder projection and packaged WorldSpec consumer paths.
- `agent_world/contracts.py` — dataclass JSON serialization and content-addressed digest behavior.
- `tests/test_design_semantics.py` — focused WorldArchitecture shape/correction regression surface.

## Related Specs and External References

- `.trellis/spec/agent_world/backend/index.md:325-371,570-585,593-705,809-897,1190-1243` — compact business semantics, acceptance identity, Direct Prompt ownership, and safe feedback.
- `.trellis/spec/guides/agent-llm-node-debugging.md:33-52,115-149` — diagnosis/proof separation.
- `.trellis/spec/guides/foundry-product-alignment.md:12-55` — local node progress is not package completion.
- `agent-world-cross-layer-critic` Skill — independent pre-implementation development gate.
- External references: none; no web search or provider call was used.

## Caveats / Not Found

- No deterministic runtime/Judge branch was found that directly executes `boundary.purpose`; the unproved consumer risk is model-facing interpretation in WorldRules, Curriculum, and Builder plus the released package's persisted description.
- The source-of-truth identifies purpose as outside the listed identity determinants, but it does not declare it safely lossy. That gap is material only if the plan retains truncation.
- The decision expires if the plan digest, purpose-storage policy, affected consumer projection, or relevant real Observe scene changes.

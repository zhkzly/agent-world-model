# Research: cross-layer review — WorldArchitecture purpose normalization r2

- Query: Independently review plan `world-architecture-purpose-normalization` revision 2/2 (`a3ed41405a5597299fcc7f7e669489304541ebfff5042f0ab45885afb562e0a8`) after real Direct run `run_1b81e19380194e13a406f10dfcf3d0df` rejected Luna twice at `$.boundary.purpose`; determine whether the non-lossy 4096-Python-Unicode-code-point policy, downstream closure, and identity proof are the smallest coherent repair.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan digest: `a3ed41405a5597299fcc7f7e669489304541ebfff5042f0ab45885afb562e0a8` (independently recomputed; exact match).
- Plan lineage / revision: `world-architecture-purpose-normalization`, revision **2/2**; this is the final permitted plan revision for the cited Diagnosis Record.
- Scope classification: **coordinated Direct semantic-projection acceptance change with local implementation**. The only production transform is in the `world_architecture` producer, but it changes the complete committed prose that Direct model consumers, Builder, package bytes, and Registry cold-read consume. The revision correctly coordinates those existing consumers through exact compatibility and identity proof rather than modifying them.
- Trigger and Diagnosis/Observe evidence: the real, same-class 28-claim/6-citation Luna proof made two complete proposals, both rejected solely at `$.boundary.purpose`; the second saw the exact 160-character condition and exhausted the one correction. Its durable result is failed/no architecture output/one blocking Finding/`not_published` (`research/world-architecture-text-bound-live-proof.md:7-21`; `research/diagnosis-world-architecture-purpose-policy-mismatch.md:11-31`). This is a proposal-versus-storage-policy mismatch, not a transport, JSON, token-ceiling, route, Skill, or retry failure.
- Affected trust boundary: `Direct LLM WorldArchitecture proposal -> Designer compiler and immutable Architecture Artifact -> later Design/Builder/package consumers -> Registry cold-read -> safe Observe facts`.
- This allow expires if the plan digest, the 4096-code-point policy, any changed consumer projection, or the relevant real Observe scene changes.

## Product Target and Impact Chain

The product target remains: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This repair advances only the first Direct semantic handoff; it does not make a Design, Candidate, Judge, Registry, Expand, Consumer, or E2E success claim.

```text
EnvironmentRequest -> Research evidence -> WorldArchitecture Direct proposal
  -> Designer validates/strips/commits complete purpose
  -> WorldRules + Curriculum + Task/Modeling inputs -> EnvironmentDesign
  -> Builder projection -> untrusted Candidate process -> Integration/Judge
  -> package world_spec bytes -> Registry cold-read -> Observe
```

The source contract makes `WorldSpec`/`WorldBoundary` the typed semantic center while listing identity determinants separately from free-form purpose prose (`docs/agent-world-environment-generation.zh.md:165-193`). Direct WorldArchitecture is a bounded no-tool Direct LLM transaction; framework compiles schema mechanics and retains Gate/release authority (`docs/agent-world-environment-generation.zh.md:601-621`, `docs/direct-rewrite-execution-map.zh.md:71-88`). That supports a framework-owned storage/validation correction without adding a node, Agent capability, Gate, or release path.

## Owners and Consumer Compatibility

- **Direct LLM:** retains only the business meaning of `boundary.purpose`; it has no Skill, tools, workspace, Gate, route, retry, or release authority (`docs/direct-rewrite-execution-map.zh.md:22-24,71-76`; `agent_world/design.py:543-565`).
- **Designer framework:** remains the sole owner of closed shape, `str.strip()`, the finite accepted-value bound, compilation, Artifact commit, and safe one-correction diagnostic. The current local 160 rejection is exactly the producer defect being replaced (`agent_world/design.py:969-1029`). The new policy is non-lossy: accept only a `str` whose stripped value is nonempty and has at most 4096 Python Unicode code points; persist that complete stripped string. It leaves name, system-of-record, authority, actor, entity, tool, schema, ID, and rule validation strict.
- **GraphRunner:** remains the sole owner of the two-attempt transaction, correction visibility, WorkRecord, and semantic revision. The changed rendered shape is part of semantic material, and `semantic_revision` binds that material, node declaration, output contract, and route (`agent_world/design.py:581-624`; `agent_world/graph.py:442-460,481-595`). No NodeSpec, Edge, route, model, correction budget, Artifact kind, or compatibility form changes.
- **Immediate Direct consumers:** `world_rules` and `curriculum_plan` receive `json_value(architecture)` (`agent_world/design.py:1599-1608,1813-1832`); task work and ModelingGate bind the Architecture ref/digest (`agent_world/design.py:1952-1971,2098-2125`). They will receive the full committed value, not raw whitespace or a 160-character prefix.
- **Builder / candidate boundary:** BuildPlan and CandidateBuild receive the complete architecture projection (`agent_world/candidate.py:752-763,800-846,848-904`), while the candidate remains an untrusted process and gains no Gate or release authority.
- **Package / Registry:** package metadata writes `json_value(design.architecture)` to `world/world_spec.json` (`agent_world/candidate.py:2035-2091`), and Registry recomputes expected metadata and rejects a mismatch (`agent_world/candidate.py:2878-2979`). Thus the persisted package and cold-read consumer retain the same full committed purpose.
- **Runtime/Judge compatibility:** no deterministic Runtime or Judge branch directly reads `boundary.purpose` in the inspected codebase; its remaining significance is model-facing business interpretation and the released description. This is compatibility evidence, not a claim that later Direct, Candidate, Judge, or Registry behavior has been proven live.

## Smallest Allowed Change and Deterministic Checks

The plan is the smallest coherent repair because it changes only the local `DesignExecutor._direct_architecture` purpose check and its disclosed shape, clarifies the ambiguous task-contract unit, and adds focused tests. It does not change shared `_text`, dataclasses, Artifact schemas, NodeSpec/Edge topology, retries, routes/models, Skill/profile systems, validators for other fields, or legacy/compatibility paths.

Required deterministic evidence remains distinct from a live proof:

1. The exact WorldArchitecture shape separates `purpose:stripped_text[1..4096_unicode_code_points]` from the unchanged 160-code-point identity fields and preserves the current sparse field grammar.
2. Non-string and whitespace-only purpose produce the exact safe correction tuple; an unchanged invalid second proposal persists the existing failed WorkRecord. A 161-code-point nonempty value commits in one call with no correction.
3. Multibyte and combining-code-point cases prove Python `len(stripped)` semantics, strip order, complete persistence at 4096 code points, and the exact over-4096 correction without slicing. No byte or grapheme counting is introduced.
4. The changed shape/acceptance transform produces a new WorldArchitecture semantic revision while NodeSpec, edges, route, and one-correction policy stay unchanged. This prevents reuse from silently crossing the changed acceptance boundary.
5. The committed Artifact, representative WorldRules/Curriculum Direct inputs, Builder projection, package metadata, and Registry comparison all carry the identical full stripped value; existing strict rejection of identity/execution fields and sparse-source regressions stays green.
6. Focused and full pytest, Ruff format/check, mypy, compileall, diff inspection, and the stated production-Python line budget remain regression guards only.

## True-Boundary Proof and Next Permitted Gate

After implementation and an independent implementation check, run one fresh `world_architecture` Direct invocation using the same real 28-claim/6-citation evidence class. Inspect its exact WorkRecord, committed Architecture Artifact, and Observe scene. For this proof to establish the changed live policy rather than merely a passing route, the accepted stripped purpose must be recorded by safe length/digest as **more than 160 and at most 4096 code points**, with no correction or truncation; do not persist prompt or raw provider text. If the fresh proposal is 160 code points or shorter, it is only a Direct-route proof and does not by itself demonstrate live acceptance of the changed threshold.

Only after that condition and the deterministic closure pass may the main coordinator run the one planned fresh public Direct CLI request, then immediately inspect its terminal Observe scene. A different terminal starts a new Observe-driven Diagnosis Record; it is not attributable to this repair by default.

**Next permitted gate:** the main coordinator may add this exact current allow record to the task manifests and dispatch the bounded `trellis-implement` work for this plan. The implementation/check sequence may not broaden scope; provider execution remains prohibited until the deterministic and independent implementation gates pass.

## Files Found

- `AGENTS.md` — project authority, source-of-truth, real-failure, and no-legacy rules.
- `docs/agent-world-environment-generation.zh.md` — canonical product, Direct ownership, Artifact, identity, runtime/Judge, package, Registry, and proof contracts.
- `docs/direct-rewrite-execution-map.zh.md` — binding Direct LLM/Agent/framework/candidate-process distinction and Direct graph consumers.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd.md,design.md,implement.md,node-contracts.md,task.json}` — active Direct scope, node contracts, task state, and the ambiguous 4096 text statement.
- `research/diagnosis-world-architecture-purpose-policy-mismatch.md` — causal Diagnosis Record for the failed proof.
- `research/cross-layer-review-5bf0e4ba-purpose-normalization.md` — revision-1 block and required revision-2 closure.
- `research/world-architecture-purpose-normalization-plan.md` — exact reviewed revision-2 plan.
- `research/world-architecture-text-bound-live-proof.md` — real 28-claim/6-citation failed Direct evidence.
- `agent_world/design.py` — Direct proposal, compiler, projected Direct consumers, and ModelingGate producer.
- `agent_world/graph.py` — fixed node authority, correction transaction, immutable Artifact/WorkRecord, and semantic-revision identity.
- `agent_world/candidate.py` — Builder projection, package metadata, Registry cold-read, and candidate-process boundary.
- `agent_world/contracts.py` — `WorldBoundary`/`WorldArchitecture` representation and canonical JSON/digest behavior.
- `tests/test_design_semantics.py`, `tests/test_graph_contracts.py`, and `tests/test_direct_release.py` — focused current regression seams for the shape, correction, identity, projection, package, and cold-read checks.

## Related Specs and External References

- `.trellis/spec/agent_world/backend/index.md:325-371,570-585,593-705,1190-1243,1312-1387` — compact architecture ownership, acceptance identity, Direct no-Skill contract, actionable correction, and least-privilege consumer disclosure.
- `.trellis/spec/guides/agent-llm-node-debugging.md:19-26,33-52,128-149` — Direct-versus-Agent separation and proof order.
- `.trellis/spec/guides/foundry-product-alignment.md:12-55` — local proof is not EnvironmentPackage completion.
- `agent-world-cross-layer-critic` Skill — pre-implementation review and bounded allow record requirements.
- External references: none. No web search, code edit, test execution, provider call, or live proof was performed.

## Caveats / Not Found

- The 4096 unit is a task-contract clarification, not a claim about UTF-8 bytes or user-visible grapheme clusters; Python code-point behavior is the approved bound.
- No new live evidence proves WorldRules, Curriculum, Builder, Candidate, Integration, Judge, Registry, Expand, Consumer, or E2E behavior under this policy.
- No deterministic Runtime/Judge use of `boundary.purpose` was found; model-facing downstream interpretation remains the reason to retain complete accepted text and test the exact handoff.
- This read-only critic did not modify the plan, production code, tests, specs, JSONL manifests, or any file outside this one research record.

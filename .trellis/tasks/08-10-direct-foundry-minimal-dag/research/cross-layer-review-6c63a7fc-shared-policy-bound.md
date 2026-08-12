# Research: cross-layer review — SharedTool shared-policy bound

- Query: Independently review exact plan `sha256:6c63a7fce61fb85312e79f05e4438afaf6d9a46a4e9530e059bbe05ff38a0cb5`, revision 1/2, for widening only SharedTool `error_policy` from 280 to 500 code points.
- Scope: internal, read-only; latest `run_d9fe` Observe evidence, the named diagnosis and plan, canonical task digest, and SharedTool/downstream design only.
- Date: 2026-08-12

## Decision

- Decision: block
- Plan digest: `sha256:6c63a7fce61fb85312e79f05e4438afaf6d9a46a4e9530e059bbe05ff38a0cb5` (verified against the complete plan file).
- Plan revision: 1/2; this is revision 1 of the two-revision lineage.
- Scope classification: local bounded source/validator change with a shared-contract handoff; no downstream implementation change is justified, but downstream value/digest propagation must be described accurately.
- Trigger: real Direct failure at `shared_tool_semantics[1-2-3-4-5-6]`.
- Affected trust boundary: Designer-owned Direct LLM source draft and framework-owned compiler/validation bind one shared policy to six tool members before `tool_semantics`, ModelingGate, Candidate packaging, Registry validation, and safe Observe facts.

## Product Target and Plan Digest

The product target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in an isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe. This repair advances only the blocked Direct Design suffix; it is not a release or product-completion claim.

The proposed implementation is one scalar change in `agent_world/design.py`: align the SharedTool `error_policy` rendered source limit and compiler limit from 280 to 500, while retaining ordering at 500, compensation at 160, the group partition/cardinality rules, Direct route/role, and the existing two-call correction policy.

## Findings

### Diagnosis / Observe evidence

- `run_d9fe033caff941c1a7bc385f019efaf3` records a failed Designer Direct LLM Work at `shared_tool_semantics`, shard `1-2-3-4-5-6`, with one blocking Finding and no release.
- Its first primary Luna call received the exact correction `$.error_policy: value must use at most 280 code points`; its second primary Luna call then failed with the same `shared_tool_semantics_invalid` terminal. The failure artifact preserves that same exact field and bound. This is sufficient evidence that the 280 source/validator bound, rather than parsing, route, Skill, or a hidden type bound, caused the terminal.
- The evidence proves only `>280`, not a raw response length or that 500 will pass. The proposed fresh real suffix is therefore required to establish the 500 hypothesis; it must not be presented as already proven.
- The exact architecture parent contains one six-member coupling group `[1,2,3,4,5,6]`, so a single shared policy is deliberately bound to all six tools.

### Bound and retained behavior

- The current compiler applies 280 only to `error_policy`; it independently applies 500 to each ordering item and 160 to each compensation item ([design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:1315), [design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:1325)). Updating only the two error-policy occurrences keeps ordering and compensation unchanged.
- A fixed 500 maximum is bounded and reuses the existing maximum semantic-text scale. It is not a new retry, normalization, schema, routing, or framework mechanism.
- The plan's phrase that the cap "adds at most 220 code points per shared group" is exact only for the one model-source string. The framework deliberately expands that string into a per-member policy tuple ([design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:1321)); serialized shared-contract and `rule-ir` payloads can therefore fan out the extra content once per bounded member. This remains bounded, but the plan must not use the 220 figure as a persisted-artifact-size claim.

### Impact chain, owners, and consumer compatibility

`exact Architecture + Evidence parents` -> `Designer / shared_tool_semantics[group]` -> `SharedToolContract.error_policy` per-member tuple and digest -> `Designer / tool_semantics[tool]` -> framework `modeling_gate` -> `EnvironmentDesign@1` -> Candidate `rule-ir@1` -> package `envpkg@1` -> Registry digest validation -> safe Observe.

- The Direct LLM source draft is compiled into the same `SharedToolContract` fields and per-member tuple/digest ([design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:1341)); each `ToolDraft` receives the selected shared-contract digest ([design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:1386)). ModelingGate accepts the same shared-tools port and emits `EnvironmentDesign@1` ([graph.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/graph.py:219)).
- Candidate packaging keeps the same `rule-ir@1` field set and serializes `shared_tool_contracts`; Registry recomputes the same shared-contract digest from those fields ([candidate.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/candidate.py:2092), [candidate.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/candidate.py:2536)). Thus a longer-but-bounded policy is semantically consumable without a new package ABI.
- `DesignGraph` is explicitly reused by Direct and Expand; Expand supplies parents/evidence but requires a complete child Design rather than a source patch ([design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:85), [design.md](/home/kelong/pycodes/foundry-direct-graph/.trellis/tasks/08-10-direct-foundry-minimal-dag/design.md:108)). The current compiled seam is compatible because its field shape stays fixed; no Expand implementation is in scope.
- The owning role remains Designer Direct LLM with no Skill/tool/workspace. Framework remains owner of compilation, validation, Work/Artifact, Finding, release, Registry, and Observe. `GraphRunner` still has exactly two invocations and one local correction opportunity ([graph.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/graph.py:479)).

### Required revision before implementation

The plan currently says that the "compiled per-member policy tuple/digest" and `ToolDraft` remain unchanged. That is not a safe literal claim. A fresh successful proposal may contain a different policy string; the `SharedToolContract.digest`, every affected `ToolDraft.shared_contract_digest`/local digest, the ModelingGate design artifact, and any eventual package content can consequently be recomputed and differ.

Revision 2 must distinguish these two facts without broadening implementation scope:

1. **Changes/recomputed values:** the SharedTool source shape and semantic revision change; a fresh successful policy value and all digest values derived from it may change.
2. **Unchanged interfaces:** `SharedToolSemanticsSourceDraft@1`, `SharedToolContract` field shape, `EnvironmentDesign@1`, `rule-ir@1`, `envpkg@1`, graph topology/ports, owner/route, and the future Expand compiled handoff remain unchanged.

It must also narrow the 220-code-point claim to the source string or state the bounded per-member serialization fan-out. These are plan-precision corrections, not code/test expansion.

## Smallest Tests and Proof

- Deterministic checks after revision: 500 code points is accepted; 501 yields the exact `$.error_policy` correction; ordering remains 500 and compensation remains 160; source and package ABI labels/field sets remain unchanged; semantic revision differs because the rendered output shape contributes to semantic material ([design.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/design.py:599), [graph.py](/home/kelong/pycodes/foundry-direct-graph/agent_world/graph.py:442)). Tests must not assert that fresh value-level digests remain equal.
- True-boundary proof after an allow: execute the exact same-parent suffix below, then read Observe. A pass proves the new SharedTool bound and one real immediate `tool_semantics` consumer can cross the handoff; it does not prove the remaining five tool calls or a full package.

## Exact Same-Parent Suffix

Use fresh Work only, with exactly these parents (the same two parents used by `run_d9fe`):

`Evidence sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`
`+ Architecture sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`
`-> fresh Luna shared_tool_semantics[1-2-3-4-5-6]`
`-> only tool_semantics[register_member]`
`-> stop -> Observe`.

No old Work is adopted, no retry count changes, and no package/Registry/Expand/Consumer step is implied by this suffix.

## Non-claims and Next Permitted Gate

- Non-claims: no Candidate, Integration, Judge, Registry publication, public E2E, Repair, Expand, Consumer, training, or reality-equivalence proof; no proof that 500 is sufficient until the fresh suffix succeeds.
- Next permitted gate: the plan writer may produce revision 2 addressing only the value-versus-ABI/digest distinction and the bounded fan-out wording, then request a fresh independent cross-layer review. Implementation, tests, and proof execution are not permitted on this blocked revision.

## Files Reviewed

- `config/.agent-world-runs/runs/run_d9fe033caff941c1a7bc385f019efaf3/run.json` — latest Observe run state and failed node event.
- `.../artifacts/fea1650d3114c52372b1dc3cf6793ca63b8d8e5340548216b2c5a30451b32c0f.json` — failed Work Record with exact inputs, attempts, Finding, and validation references.
- `.../artifacts/0d3b8432c1137a63657df2e3f769e4cbff1bafbff2a200c0e55759cc667e2121.json` — exact final error-policy violation.
- `.../artifacts/e210813291238aabc14570b71e76464ede4812d65093519689e4fc5bb5c198b1.json` and `.../acd4124d5f9a580adf7c5fd8d89089fe247c48f67895df900aee69f662627512.json` — first correction and second terminal attempt.
- `research/diagnosis-shared-tool-policy-bound-too-small.md` — causal diagnosis.
- `research/shared-tool-policy-bound-plan.md` — reviewed plan revision and digest.
- `research/canonical-contract-digest.md` and `design.md` — canonical task target and Direct/Expand/downstream design.
- `agent_world/design.py`, `graph.py`, `contracts.py`, and `candidate.py` — SharedTool compiler, semantic revision/two-call mechanism, typed handoff, and package/Registry consumers.

## External References

None. This deliberately narrow review used only the specified repository evidence.

## Caveats / Not Found

- Raw model proposals are intentionally absent from safe Observe evidence, so no exact character count above 280 is available.
- No old task history, implementation/check JSONL, tests, or external material was read.

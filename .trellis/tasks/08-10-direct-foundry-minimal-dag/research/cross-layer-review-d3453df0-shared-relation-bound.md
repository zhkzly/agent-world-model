# Research: cross-layer-review-d3453df0-shared-relation-bound

- Query: Independent cross-layer review of exact plan `sha256:d3453df0a0c73c9f2a77a9c9b0a57cd09f44eb2a1384c4e137c293c068ac787c`, revision 1/2, for the SharedTool relation-text bound repair.
- Scope: internal
- Date: 2026-08-12

## Decision

Decision: block

- Plan digest: `sha256:d3453df0a0c73c9f2a77a9c9b0a57cd09f44eb2a1384c4e137c293c068ac787c` (verified against the complete plan file).
- Plan revision: 1/2. One plan-only revision remains; no implementation, provider retry, or test change is permitted from this record.
- Scope classification: coordinated cross-node contract widening. The allowed code surface can remain local to the SharedTool source/card/tests, but the widened producer value domain reaches ToolSemantics, ModelingGate, Candidate packaging, Registry verification, and the shared DesignGraph used by future Expand.
- Trigger: the latest public Observe terminal, `run_358570ae622f423f9a7d0607717bfc3e`, rejected both authorized Luna attempts at `$.ordering` over the disclosed 160-code-point bound; no SharedTool artifact or downstream work committed.

## Product Target and Affected Boundary

The target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe. This plan only tries to reopen the Direct SharedTool handoff; a green unit test or a successful suffix is not product completion.

The affected boundary is the Direct LLM `SharedToolSemanticsSourceDraft` recipient contract and its framework compiler. The Direct LLM owns ordering/compensation meaning; the framework owns the disclosed bound, exact validation, semantic identity, Work/Artifact commit, package validation, and release. No Agent, Skill, retry budget, route, candidate process, Judge, or Registry authority may change.

## Findings

### Evidence and exact latest-parent suffix

- The diagnosis records two healthy primary calls and the same field-specific failure: `$.ordering` exceeded 160 both before and after the exact correction. It does **not** record a `$.compensation` overlimit or the rejected string length beyond `>160` (`diagnosis-shared-tool-ordering-bound-too-small.md:10-24`).
- The exact permitted proof suffix, if a revised plan is later allowed, must be written literally as:

  `run_358570ae622f423f9a7d0607717bfc3e` immutable parents — Evidence `sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`, Architecture `sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506` — fresh Luna `shared_tool_semantics[1-2-3-4-5-6]` — only `tool_semantics[register_member]` — stop and read Observe.

  The submitted plan says only “first ToolSemantics suffix” and omits the exact work coordinate and parent digests (`shared-tool-relation-bound-plan.md:24-28`); the diagnosis supplies the required exact suffix (`diagnosis-shared-tool-ordering-bound-too-small.md:45-53`).

### Is a symmetric 500 bound supported?

- Raising **ordering** is causally supported: the real terminal is field-specific, and the current compiler and Direct output shape each enforce 160 at `agent_world/design.py:1324-1335` and `agent_world/design.py:1370-1373`.
- Raising **compensation** is not yet causally supported by the cited run. The source card merely presents `ordering | compensation` on one line (`node-contracts.md:360-368`); the canonical product contract lists them as distinct SharedTool semantics (`docs/agent-world-environment-generation.zh.md:601-603`). Shared presentation is not evidence that the compensation cap failed.
- Five hundred is still a real bound, not an unbounded or generic framework change: each list remains `0..8`, hence no more than 4,000 code points per relation list and 8,000 across ordering plus compensation for the current one-group implementation. The current coupling plan is one full multi-tool group, while the canonical future design permits at most four groups (`agent_world/contracts.py:671-682`; `docs/agent-world-environment-generation.zh.md:605`). It is therefore mechanically controlled and not an architectural expansion.
- It is nevertheless an unsupported **choice of magnitude** in revision 1: the evidence establishes only `>160`, not that 500 is the smallest adequate cap or that it is needed for compensation. The plan must either narrow to ordering only, or state a field-specific semantic/policy reason for keeping both fields at the same 500 cap and prove the exact boundary independently for each selected field. This is a plan clarification, not permission to infer or truncate model text.

### Semantic revision, ABI, and Expand seam

- Changing the rendered output shape does rotate the actual SharedTool semantic revision: `_direct_commit` places `output_shape` in semantic material (`agent_world/design.py:625-637`), and `GraphRunner.semantic_revision` hashes that material (`agent_world/graph.py:442-460`). This satisfies the source-of-truth requirement that effective prompt/input and output model changes cannot reuse an old semantic commit (`docs/agent-world-environment-generation.zh.md:109-113`).
- The plan fails to distinguish that semantic-revision rotation from an ABI version bump. The structural node contract, ports, owner, route, and one-correction policy remain `SharedToolSemanticsSourceDraft@1` / `shared-tool-semantics@1` (`agent_world/graph.py:161-180`); `SharedToolContract` remains the same tuple/string/digest shape (`agent_world/contracts.py:685-734`); package `rule-ir@1` and Registry key/digest checks likewise remain structurally unchanged (`agent_world/candidate.py:2481-2564`). A revised plan must say explicitly: semantic identity rotates because its accepted source domain/output shape changes; no source, package, or Registry ABI version changes; old successful work is not adopted as a result of the new semantic identity.
- ToolSemantics consumes the committed SharedTool projection and embeds its digest into every selected `ToolDraft` (`agent_world/design.py:1398-1515`); ModelingGate has a direct `shared_tools` edge (`agent_world/graph.py:339,353`); Candidate projects the same contracts and Registry recomputes their digest. This supports compatibility only if the revised plan preserves the exact fields, tuple ordering, digest recipe, ports, and package schema versions.
- Expand does not need implementation in this repair, but its seam must be named. Direct and Expand share DesignGraph/CandidateGraph; an Expand campaign creates a new DesignRequest and invokes those same graphs, while its parents are frozen package facts (`docs/direct-rewrite-execution-map.zh.md:30-47,164-178`). The revised plan must explicitly state that this source-bound widening neither changes a released package ABI nor adopts an old SharedTool Work; any future Expand request executes the current revision through the same compiler. “No later-child code” alone is insufficient compatibility evidence.

## Required Plan Revision (Actionable Block Feedback)

1. Choose and justify the field scope. Prefer `ordering` only unless the plan records a concrete semantic policy that makes the compensation cap inseparable; if it retains both, it must name the independent rationale and require symmetric boundary tests for both fields. Do not add retries, truncation, normalization, a generic text-bound facility, or a weakened validator.
2. State why 500 is the chosen bounded policy rather than merely repeating that it is bounded: retain `0..8`, enumerate the current 8,000-code-point combined maximum, preserve the existing two-call correction limit, and state that a new `>500` terminal begins a new diagnosis rather than widening again implicitly.
3. Make the revision/ABI distinction explicit: the actual `output_shape` change must rotate `semantic_revision_digest`; `SharedToolSemanticsSourceDraft@1`, node ports/edges, `SharedToolContract` fields/digest recipe, `rule-ir@1`, and `envpkg@1` remain unchanged. No old success may be reused as if it matched the new semantic revision.
4. Add the Expand compatibility/non-claim above, and spell out the exact latest-parent suffix rather than “first ToolSemantics suffix.”

## Smallest Checks and Proof After a Future Allow

- Deterministic source check: for every field chosen by the revised plan, accept exactly 500 code points and reject 501 with `shared_tool_semantics_invalid`, the exact field path, and the exact bounded correction; preserve empty/`0..8` list behavior and all partition/error-policy checks.
- Deterministic identity/ABI check: assert the concrete 160-to-500 output-shape change produces a different SharedTool semantic revision, while NodeSpec contract/version, route, ports, local-correction count, `SharedToolContract` field order, ToolDraft shared digest, ModelingGate dependency, Candidate projection, `rule-ir@1`, and Registry digest verification remain unchanged.
- Required static gate: focused tests plus the existing full test/static/package/Registry checks named by the revised plan; these are regression evidence, not live proof.
- Smallest true-boundary proof: run exactly the latest-parent suffix recorded above, stop after `tool_semantics[register_member]`, and read Observe. A suffix pass permits one fresh public Direct E2E only; any terminal starts a new Observe-to-diagnosis lineage.

## Files Found

- `AGENTS.md` — product target, authority rules, and mandatory cross-layer/Observe gate.
- `docs/agent-world-environment-generation.zh.md` — canonical SharedTool semantics, semantic-identity, and bounded Direct transaction rules.
- `docs/direct-rewrite-execution-map.zh.md` — Direct/Expand shared-graph and child-boundary contract.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-shared-tool-ordering-bound-too-small.md` — latest real terminal, immutable parents, and intended suffix.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/shared-tool-relation-bound-plan.md` — reviewed exact revision-1 plan.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — current closed SharedTool source card.
- `agent_world/design.py` — source compiler, Direct output shape, semantic material, and ToolSemantics consumer.
- `agent_world/graph.py` — semantic revision computation and graph ports/edges.
- `agent_world/contracts.py` — stable SharedTool/ToolDraft/DesignContract shapes.
- `agent_world/candidate.py` — Candidate projection, package Rule IR, and Registry digest verification.
- `tests/test_design_semantics.py` — existing exact 161-ordering correction and semantic revision coverage.

## Related Specs

- `.trellis/spec/agent_world/backend/index.md` — Shared-tool semantic transaction completion: prompt is an aid; deterministic compiler remains authoritative and correction stays bounded.
- `docs/agent-world-environment-generation.zh.md:601-607` — canonical Direct/SharedTool ownership and no hidden arbitrary truncation rule.

## External References

None. This was an internal, read-only review.

## Caveats / Not Found

- No raw model proposal or exact rejected length was needed or read; the persisted safe diagnosis is sufficient to establish only `ordering >160`.
- No old review history, implementation/check JSONL, code changes, plan edits, product changes, test changes, provider retry, or git operation was performed.
- This block is not a claim that 500 is unsafe or that the downstream ABI is broken; it requires the final revision to make the field scope, bound policy, semantic-revision/ABI distinction, Expand seam, and exact proof suffix explicit before implementation can be permitted.

## Next Permitted Gate

Plan revision 2/2 only, followed by a fresh independent read-only cross-layer review of its new complete digest. Do not dispatch implementation or run the provider suffix unless that review returns `allow`.

# Research: cross-layer-review-377db0d1-shared-ordering-bound-r2

- Query: Independent final cross-layer review of exact plan `sha256:377db0d17fe74c459112f40a749fe702e5a24766d777296ba99647c25cc977d7`, revision 2/2, for the SharedTool ordering-bound repair.
- Scope: internal
- Date: 2026-08-12

## Decision

Decision: allow

- Plan digest: `sha256:377db0d17fe74c459112f40a749fe702e5a24766d777296ba99647c25cc977d7`, verified against the complete `shared-tool-relation-bound-plan.md` file.
- Plan revision: 2/2; this is the final permitted revision in this diagnosis/plan lineage.
- Scope classification: local implementation surface with explicitly closed cross-node compatibility. Only the Direct SharedTool source/compiler/card/test bound changes; the semantic revision rotates, while structural consumer contracts and package ABI stay fixed.
- Trigger: public Direct run `run_358570ae622f423f9a7d0607717bfc3e` terminated at `design/shared_tool_semantics[1-2-3-4-5-6]` after two healthy Luna attempts exceeded only `$.ordering`'s disclosed 160-code-point bound; no SharedTool artifact or downstream work committed (`diagnosis-shared-tool-ordering-bound-too-small.md:4-16`).

## Product Target and Trust Boundary

The product target remains: turn an arbitrary natural-language EnvironmentRequest into an evidence-grounded executable environment, independently verify it in a real isolated boundary, publish an immutable Registry EnvironmentPackage, and expose only safe facts through Observe. This allow reopens only the Direct SharedTool handoff; deterministic checks or a suffix pass are not package publication or product completion.

The affected boundary is the `SharedToolSemanticsSourceDraft` Direct-LLM output shape and its framework compiler. Direct LLM retains authorship of ordering/compensation meaning. The framework retains the bound, exact correction/validation, semantic identity, Work/Artifact commit, graph gates, package validation, Registry publication, and Observe facts. Tool-enabled Agents and the untrusted candidate process do not gain work, authority, retries, Skills, routes, or release decisions (`AGENTS.md:20-38`; `docs/direct-rewrite-execution-map.zh.md:15-28`).

## Findings

### Revision-1 block closure

1. **Field scope is now causal and narrow.** The plan changes only `ordering` from 160 to 500, retains `compensation` at 160 and both arrays at `0..8`, and requires the rendered shape and source card to say so (`shared-tool-relation-bound-plan.md:9-16`). This matches the field-specific terminal and avoids the unsupported compensation widening rejected in the prior block (`cross-layer-review-d3453df0-shared-relation-bound.md:35-38`). Current code independently confirms the two limits are separate compiler calls and the current shared shape joins them only as presentation (`agent_world/design.py:1325-1339,1370-1379`; `node-contracts.md:360-368`).

2. **500 is a bounded, explicit policy.** The plan keeps the existing one-correction/two-call limit, caps a group at `8 × 500 = 4,000` ordering code points, and requires any real `>500` terminal to start a new diagnosis rather than silently widening again (`shared-tool-relation-bound-plan.md:18-21`). Its focused checks retain the 161 compensation rejection and exact 501 ordering correction (`shared-tool-relation-bound-plan.md:13-16`). This is not a generic text-bound facility, truncation, normalization, retry, or validator weakening (`shared-tool-relation-bound-plan.md:35-38`).

3. **Semantic revision is distinguished from ABI.** The plan expressly rotates `semantic_revision_digest` and forbids adoption of prior SharedTool Work, while retaining `SharedToolSemanticsSourceDraft@1`, node ports/edges, `SharedToolContract` field order/digest recipe, `rule-ir@1`, and `envpkg@1` (`shared-tool-relation-bound-plan.md:23-28`). That is mechanically supported: the Direct commit includes the rendered `output_shape` in semantic material (`agent_world/design.py:625-640`) and the graph hashes it into the semantic revision (`agent_world/graph.py:442-460`); the source NodeSpec remains Direct LLM with the same input/output ports and contract version (`agent_world/graph.py:161-180`).

4. **Downstream compatibility is concrete, not inferred from types alone.** `ToolSemantics` receives the committed shared projection, uses its digest in each `ToolDraft`, and has the same `shared_tools` input edge into both ToolSemantics and ModelingGate (`agent_world/design.py:1398-1515`; `agent_world/graph.py:329-354`). `SharedToolContract` keeps the same tuple/string fields (`agent_world/contracts.py:685-746`), Candidate projects those contracts without reshaping them (`agent_world/candidate.py:753-763`), and package/Registry retain `rule-ir@1`, its exact keys and recomputed shared digest, plus `envpkg@1` verification (`agent_world/candidate.py:2092-2099,2150-2164,2476-2564,2818-2836`). The planned tests name these consumers and their tuple/digest/shape invariants (`shared-tool-relation-bound-plan.md:13-16`).

5. **The Expand seam and real-proof suffix are explicit.** The plan correctly confines Expand to a compatibility/non-claim: frozen released parents feed a future campaign, which executes the current shared DesignGraph/CandidateGraph revision; this repair neither adopts old SharedTool Work nor implements/proves Expand (`shared-tool-relation-bound-plan.md:30-33`). That matches the canonical child boundary (`docs/direct-rewrite-execution-map.zh.md:30-47,164-178`). The exact proof is now literal: run `run_358570ae622f423f9a7d0607717bfc3e`, Evidence `sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`, Architecture `sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`, fresh Luna `shared_tool_semantics[1-2-3-4-5-6]`, then only `tool_semantics[register_member]`, followed by Observe (`shared-tool-relation-bound-plan.md:44-51`). The concrete shard construction is `"-".join(map(str, group))`, and the ToolSemantics shard is the surface name, so the stated coordinates are aligned with the Direct executor (`agent_world/design.py:1364-1381,1495-1516`).

## Impact Chain, Owners, and Consumer Compatibility

`Direct LLM SharedTool source shape -> framework compiler/SharedToolContract -> Direct LLM ToolSemantics/ToolDraft shared digest -> framework ModelingGate -> DesignContract -> Candidate Agent projection and untrusted candidate Runtime -> framework Package/Registry -> Observe`.

- The changed producer is only the Direct SharedTool source bound/shape. The framework compiler still owns acceptance and correction; neither becomes an Agent action.
- The immediate Direct consumer is ToolSemantics; later consumers are ModelingGate, Candidate projection, package Rule IR, Registry verification, and Observe. The plan preserves their field order, values, digest recipe, ports, ABI versions, and authority boundaries.
- Future Expand is a shared-graph consumer, not an implementation target. Canonical architecture requires it to create a new request through the same graphs; it is not allowed to adopt a prior SharedTool Work under the new semantic revision.

## Smallest Allowed Implementation and Proof

- Change exactly the two `ordering` declarations in the SharedTool compiler/rendered output shape and the matching source-card wording; leave the compensation declaration at 160 and all other code surfaces unchanged.
- Add focused regression evidence for ordering 500 acceptance, ordering 501's exact `$.ordering` correction, compensation 161 rejection, semantic-revision rotation, and unchanged consumer ABI/shape; then run the stated full deterministic/static/package gates and independent check.
- Only after those gates, run the exact latest-parent suffix above, stop after `tool_semantics[register_member]`, read Observe, and record the required Product Alignment Checkpoints at the proof boundary. A suffix pass permits one fresh public Direct E2E; any terminal starts a new Observe-to-diagnosis lineage.

## Non-Claims

- This does not prove a complete Direct run, Candidate, Judge, Registry publication, Repair, Expand, Consumer/SFT/RL, or the adequacy of 500 for all future requests.
- It does not add an Expand implementation, an Agent or Skill to the Direct node, a candidate-process authority, retries, normalization, truncation, a generic bound mechanism, or any ABI version change.
- No raw model proposal, exact rejected string length, implementation/check JSONL, unrelated review history, code/test/plan change, provider retry, test run, or git operation was read or performed for this review.

## Files Found

- `research/shared-tool-relation-bound-plan.md` — exact revision-2 plan and verified digest.
- `research/diagnosis-shared-tool-ordering-bound-too-small.md` — latest public terminal, ownership attribution, immutable parents, and suffix limit.
- `research/cross-layer-review-d3453df0-shared-relation-bound.md` — revision-1 block and its four required closures.
- `AGENTS.md` — canonical product target, authority distinctions, and critic/Observe gates.
- `docs/agent-world-environment-generation.zh.md` — source-of-truth Direct SharedTool transaction semantics.
- `docs/direct-rewrite-execution-map.zh.md` — Direct/Expand shared-graph and framework/Direct/Agent/candidate distinctions.
- `node-contracts.md` — current SharedTool source-card wording to align.
- `agent_world/design.py` — Direct compiler, rendered shape, semantic material, shard keys, and ToolSemantics consumer.
- `agent_world/graph.py` — unchanged NodeSpec/edges and semantic revision construction.
- `agent_world/contracts.py` — unchanged SharedToolContract, ToolDraft, and DesignContract structures.
- `agent_world/candidate.py` — Candidate projection, package Rule IR, Registry digest, and envpkg validation.
- `tests/test_design_semantics.py` — existing exact 161 correction and semantic/consumer regression pattern.

## Related Specs

- `AGENTS.md` identifies `docs/agent-world-environment-generation.zh.md` as the source of truth and binds the execution-map distinction.
- No additional `.trellis/spec/` file was read, per the requested review scope.

## External References

None. This was an internal, read-only review.

## Caveats / Not Found

- The diagnosis's earlier repair suggestion included compensation, but its actual observed evidence is only `ordering >160`; revision 2 correctly narrows to the field-specific evidence required by the revision-1 block.
- No `ExpandCampaign` implementation symbol is present in the reviewed `agent_world/` slice. The Expand statement is therefore a compatibility seam/non-claim grounded in the canonical architecture, not a live Expand proof.
- The allow expires if this plan digest, the affected trust boundary, or the latest relevant Observe scene changes.

## Next Permitted Gate

Implement only this exact revision, then complete its deterministic checks and independent check before the specified real suffix. Do not broaden the change. After the suffix, read Observe; a pass permits one fresh public Direct E2E, and any failure requires a new diagnosis before another repair plan.

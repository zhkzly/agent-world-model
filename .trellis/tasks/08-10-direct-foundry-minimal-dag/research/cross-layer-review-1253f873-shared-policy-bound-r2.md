# Research: cross-layer review — SharedTool shared-policy bound r2

- Query: Independently review final revision 2/2 of the SharedTool shared-policy-bound repair plan, exact `sha256:1253f873e087b5ab822d5d844718020926cd9d0b3e52615bb283d692c53e99f8`, and decide whether revision 1's block is closed.
- Scope: internal, read-only; the latest named diagnosis and plan, revision-1 block `cross-layer-review-6c63a7fc-shared-policy-bound.md`, canonical task digest, and the SharedTool/downstream implementation only.
- Date: 2026-08-12

## Decision

- Decision: allow
- Plan digest: `sha256:1253f873e087b5ab822d5d844718020926cd9d0b3e52615bb283d692c53e99f8` (verified against the complete current plan file).
- Plan revision: 2/2; second and final permitted revision for diagnosis `diagnosis-shared-tool-policy-bound-too-small.md`.
- Scope classification: local bounded SharedTool source/validator repair with an explicitly traced shared-contract handoff. No downstream implementation change is approved or needed.
- Trigger and diagnosis evidence: the real Direct terminal at `shared_tool_semantics[1-2-3-4-5-6]` established only that the previous 280-code-point source/validator bound rejected the two healthy primary proposals; it did not establish that 500 will pass.
- Affected trust boundary: Designer-owned Direct LLM source text is compiled and framework-bound into one per-member `SharedToolContract` before `tool_semantics`, ModelingGate, Candidate packaging, Registry recomputation, and safe Observe facts.

## Product Target

The target remains an arbitrary natural-language `EnvironmentRequest` to an evidence-grounded executable environment, independently verified in an isolated boundary, published as an immutable Registry `EnvironmentPackage`, with only safe facts exposed through Observe. This allow advances only the blocked Direct Design suffix; it is not release or product-completion evidence.

## Findings

### Revision-1 block closure

Revision 1 incorrectly described the compiled tuple/digest and `ToolDraft` as unchanged. Revision 2 closes that defect: it distinguishes unchanged structure and recipes from value-level recomputation. The plan now expressly permits a fresh model-authored policy, `SharedToolContract.digest`, affected `ToolDraft.shared_contract_digest` and `local_rules_digest`, the ModelingGate Design artifact, and eventual package content to be recomputed and to differ; it prohibits equality assertions for those value-level digests (plan:31-34).

This matches the implementation. The compiler repeats the one accepted source policy for every member and calculates the shared-contract digest from that resulting payload (`agent_world/design.py:1315-1361`). Each selected contract digest is both projected to the downstream Direct LLM and included in the local ToolDraft digest recipe (`agent_world/design.py:1474-1500`; `agent_world/design.py:287-311`). The complete Design projection includes those values (`agent_world/design.py:180-196`), and package metadata serializes the contracts and carries the resulting Design and rule-IR digests (`agent_world/candidate.py:2092-2181`).

The only unchanged-interface claims are accurate: the `SharedToolContract` and `ToolDraft` field sets, their canonical digest recipes, `SharedToolSemanticsSourceDraft@1`, the existing graph ports/`EnvironmentDesign@1`, `rule-ir@1`, and `envpkg@1`. The plan does not claim their produced value-level digests are stable. `SharedToolContract` and Design reference invariants retain their current field/identity checks (`agent_world/contracts.py:685-754`, `agent_world/contracts.py:985-1042`); Registry still validates the same `rule-ir@1` field set and recomputes the same shared digest recipe (`agent_world/candidate.py:2476-2566`) and the same `envpkg@1` closure (`agent_world/candidate.py:2812-2836`).

### Bound, semantic revision, and scope

The approved code change is precisely the two related `error_policy` 280 literals in `agent_world/design.py`: the `_text` validator at :1315-1320 and the rendered Direct output shape at :1369-1374. Ordering remains 500 and compensation remains 160 (`agent_world/design.py:1325-1339`). No field, ABI/version, graph, route, model, Skill, correction count, helper/module, normalization, candidate, or later-child change is authorized.

The plan correctly states that 500 bounds one source string, while framework expansion stores that text once per group member. The expansion is explicit at `agent_world/design.py:1321`; architecture accepts at most eight tools and its multi-tool coupling group contains those ordered members (`agent_world/contracts.py:669-680`). Thus the preserved bound is at most `8 × 500 = 4,000` code points of compiled policy text per group, not merely a 220-code-point persisted-artifact claim.

Changing the rendered output shape changes the Direct node's semantic material (`agent_world/design.py:625-637`), so its semantic revision rotates under the unchanged graph contract (`agent_world/graph.py:442-460`). `SharedToolSemanticsSourceDraft@1` remains the declared output contract and the `shared_tools` handoff remains the same (`agent_world/graph.py:162-180`, `agent_world/graph.py:336-354`).

### Impact chain, owners, and compatibility

`exact Evidence + Architecture parents` -> `Designer / shared_tool_semantics[group]` -> framework compiler/validation -> per-member `SharedToolContract` and value-derived digest -> `tool_semantics[tool]` / `ToolDraft` -> framework ModelingGate / `EnvironmentDesign@1` -> Candidate `rule-ir@1` -> package `envpkg@1` -> Registry digest validation -> safe Observe.

The Direct LLM continues to own only policy meaning. Framework continues to own declared bounds, compilation, value/digest validation, Work/Artifact transitions, ModelingGate, package/Registry validation, release, and Observe. The plan preserves two-invocation/local-correction behavior and does not introduce truncation, a retry increase, or a validator relaxation. `tool_semantics` consumes the unchanged `shared_tools` port, and ModelingGate accepts the same port with the same output contract (`agent_world/graph.py:172-229`); Candidate and Registry consume longer-but-bounded values through existing serialization and recomputation rather than an ABI change (`agent_world/candidate.py:2092-2181`, `agent_world/candidate.py:2536-2566`). Future Expand's compiled seam remains structurally compatible but is not implemented or proven here.

## Smallest Allowed Implementation and Proof

- Make only the two `280 -> 500` policy-bound/source-shape substitutions in `agent_world/design.py` described above.
- Deterministic checks: 500 code points accepted; 501 yields the exact `$.error_policy` correction; ordering remains 500; compensation remains 160; semantic revision rotates; structural field sets, digest recipes, `SharedToolSemanticsSourceDraft@1`, `rule-ir@1`, and `envpkg@1` remain unchanged. Do not assert equal fresh SharedTool, ToolDraft, Design, rule-IR, or package digest values.
- True-boundary proof after implementation and deterministic checks: use fresh Work with only Evidence `sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa` and Architecture `sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`, run fresh Luna `shared_tool_semantics[1-2-3-4-5-6]`, then only `tool_semantics[register_member]`, stop, and read Observe. Five hundred remains a same-parent proof hypothesis until that suffix passes; a `>500` terminal starts a new diagnosis.

## Non-claims and Next Permitted Gate

- Non-claims: no proof that 500 is sufficient yet; no proof of the remaining five tool calls, full Design completion, Candidate, Integration, Judge, Registry publication, public E2E, Repair, Expand, Consumer, training, or reality equivalence. No old Work may be adopted.
- Next permitted gate: the main planner may attach this exact current allow record to implementation/check context and dispatch the narrowly bounded implementation. After implementation, perform the specified deterministic checks; only then run the exact real suffix and read Observe. This allow expires if this plan digest, the SharedTool/downstream trust boundary, or the relevant real scene changes.

## Files Reviewed

- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/diagnosis-shared-tool-policy-bound-too-small.md` — latest causal diagnosis and same-parent proof boundary.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/shared-tool-policy-bound-plan.md` — exact revision 2/2 plan.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/cross-layer-review-6c63a7fc-shared-policy-bound.md` — revision-1 block and required corrections.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/canonical-contract-digest.md` — canonical product target and Direct/Expand boundary.
- `agent_world/design.py`, `agent_world/contracts.py`, `agent_world/graph.py`, and `agent_world/candidate.py` — SharedTool compilation and downstream consumers.

## External References

None; this deliberately narrow review used only the requested repository evidence.

## Caveats / Not Found

- No code, plan, tests, or JSONL was modified. No old task history, live proof, or external material was read for this review.
- The diagnosis safely omits raw model policy text; this review relies on its recorded exact validation failure and does not infer an undisclosed response length.

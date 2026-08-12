# Plan — widen only SharedTool relation text

- Diagnosis: `diagnosis-shared-tool-ordering-bound-too-small.md`
- Revision: 2/2
- Scope: local SharedTool source/validator bound alignment

## Minimal implementation

1. In `agent_world/design.py`, change only SharedTool `ordering` item limits
   from 160 to 500 and disclose that exact limit in the existing output shape.
   Keep `compensation` at 160, both arrays at 0..8, and every other field/bound.
2. Align only the SharedTool source card in `node-contracts.md`.
3. Update focused tests to prove ordering 500 accepted, ordering 501 receives
   the exact bounded correction, compensation still rejects 161, source
   semantic revision rotates, and compiled/downstream tuple/digest/ToolDraft/
   ModelingGate/Candidate/Registry shapes remain intact.

Five hundred reuses the existing bounded semantic-text policy already used by
the Design compiler and permits at most 8 x 500 = 4,000 ordering code points per
shared group. It is not an implicit widening policy: any real `>500` terminal
starts a new diagnosis. The existing one-correction/two-call limit remains.

The rendered output-shape change rotates `semantic_revision_digest`; no prior
SharedTool Work may be adopted under it. This is not an ABI version change:
`SharedToolSemanticsSourceDraft@1`, node ports/edges, `SharedToolContract`
fields/order/digest recipe, `rule-ir@1` and `envpkg@1` remain unchanged.
ToolSemantics, ModelingGate, Candidate, Registry and Observe consume the same
compiled values.

Future Expand remains compatible at that compiled seam: each campaign uses its
frozen released parents as inputs but executes the current shared DesignGraph/
CandidateGraph revision. This repair neither adopts old SharedTool Work nor
implements or proves Expand.

No truncation, normalization, generic bound increase, field, helper/module,
node, Agent, Skill, route, response mode, retry, compatibility path or
later-child code is allowed. Direct LLM retains semantic authorship; framework
retains exact validation and release authority.

## Checks and real proof

Run focused/full pytest, firewall/package/Registry, Ruff, mypy, compileall,
diff check and the 10,320 production-line ceiling, then an independent check.
Run exactly this latest-parent suffix: from public run
`run_358570ae622f423f9a7d0607717bfc3e`, reuse Evidence
`sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`
and Architecture
`sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`;
invoke fresh Luna `shared_tool_semantics[1-2-3-4-5-6]`, then only
`tool_semantics[register_member]`; stop and read Observe. Pass permits one fresh
public Direct E2E; any failure starts a new diagnosis.

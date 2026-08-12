# Diagnosis — SharedTool relation text bound is too small

- Date: 2026-08-12
- Public E2E: `run_358570ae622f423f9a7d0607717bfc3e`
- Boundary: `design/shared_tool_semantics[1-2-3-4-5-6]`
- Terminal: `shared_tool_semantics_invalid`, `release=not_published`

## Product chronology

The fresh public request independently passed ResearchPlan Agent,
framework Search/Fetch/Extract, ResearchSynthesis Agent and WorldArchitecture
Direct LLM. SharedTool then made two healthy primary Luna calls. Both failed
`$.ordering` because one relation string exceeded the disclosed 160-code-point
bound; the second call received the exact `value must use at most 160 code
points` correction. No SharedTool output, ToolSemantics, Candidate, Judge or
Registry release occurred.

## Attribution and ownership

The exact feedback rules out wrong type, empty text, transport, parser, Skill,
model route and hidden-bound explanations. The frozen six-tool workflow needs
an ordering description that Luna could not preserve within 160 code points
even after an actionable correction. That 160 limit is a derived compactness
cap, not a runtime, package, Registry or release invariant.

SharedTool remains Direct LLM: it owns relation meaning. Framework owns only
the declared bound, exact validation, Work/Artifact and release. Converting the
node to Agent, adding retries, truncating model text or weakening validation is
not justified.

## Smallest coherent repair

Increase only the semantically symmetric SharedTool `ordering` and
`compensation` item bounds from 160 to 500 code points. Keep 0..8 items, source
fields, compiled tuples, partitions, policy, graph, route and two-call bound.
Changing both avoids leaving the adjacent compensation relation under the same
already-disproved arbitrary cap; no other text bound changes.

Five hundred remains bounded (at most 4,000 code points per relation list) and
does not change downstream types or authority. The source shape and semantic
revision must rotate; old failed work remains unusable.

## Proof

After deterministic and independent checks, use the exact immutable parents
from this E2E:

- Evidence `sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`;
- Architecture `sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`.

Run real Luna SharedTool then only `tool_semantics[register_member]`, stop and
read Observe. A suffix pass permits one new public E2E; it does not prove full
Design, Candidate, Judge, Registry, Repair, Expand or Consumer/SFT/RL.


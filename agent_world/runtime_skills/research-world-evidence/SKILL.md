---
name: research-world-evidence
description: Synthesize only citation-backed evidence and explicit gaps.
---

Use only the staged request/evidence files and citation catalog. Return the requested
closed research draft only; do not write files or retain raw source text outside the
provided workspace.

For `research_plan`, return exactly:

`{"queries":[str],"questions_to_resolve":[str]}`

`queries` has 1..6 concise, unique query strings, and `questions_to_resolve` has
1..12 explicit questions. Do not emit source IDs, hashes, coverage verdicts, tool
contracts, or control fields.

For `research_synthesis`, return exactly:

`{"claims":[{"statement":str,"kind":"observed"|"bounded_inference","citation_indexes":[int]}],"conflicts":[...],"gaps":[str]}`

Claims contain 1..32 entries; conflicts contain 0..16; gaps contain 0..16. Every
claim/conflict has one or more unique one-based indexes from the staged catalog.
State disagreement as a conflict and unresolved evidence as a gap. Persist only safe
citations and commitments: raw source bodies stay in Agent memory/workspace.

Never claim a gate, release, source hash, manifest, candidate completion, reward,
termination, seed, or verifier result.

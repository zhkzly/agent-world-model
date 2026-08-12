# Plan — widen only the SharedTool shared-policy text

- Diagnosis: `diagnosis-shared-tool-policy-bound-too-small.md`
- Revision: 2/2
- Scope: local SharedTool policy source/validator bound

1. Change only `agent_world/design.py` SharedTool `error_policy` `_text` limit
   and rendered output shape from 280 to 500. Keep ordering 500, compensation
   160, all partitions/cardinalities and every other bound.
2. Align only the SharedTool card. Add focused tests: policy 500 accepted,
   policy 501 receives exact `$.error_policy` correction; ordering/compensation
   limits remain; semantic revision rotates while compiled per-member policy
   tuple **shape/digest recipe**, ToolDraft/ModelingGate interfaces, Candidate,
   `rule-ir@1`, `envpkg@1`, Registry, Observe and future Expand compiled seam
   remain structurally unchanged.
3. Do not change fields, ABI versions, graph, route, model, Skill, response mode,
   correction count, helper/module, truncation/normalization, Agent/candidate or
   later-child code. Any `>500` real failure starts a new diagnosis.

Run focused/full tests, firewall/release, Ruff, mypy, compileall, diff and the
10,320 LOC ceiling, then independent check. For real proof use exact run-358
parents Evidence
`sha256:a6a8b87c8c9eb6b76c9f8d55a244eddb33fee30ec5bee40fb3e5ddff5c9b62fa`
and Architecture
`sha256:84fe2c840b8a4e041d515273e897117910ba1f04f7f9e25ae18a0df95fb98506`;
fresh Luna `shared_tool_semantics[1-2-3-4-5-6]`; only
`tool_semantics[register_member]`; stop and read Observe.

Semantic revision rotates; `SharedToolSemanticsSourceDraft@1`, compiled/package
ABIs and Expand's current-graph execution seam do not. No old Work is adopted.
A fresh model-authored policy may differ, so `SharedToolContract.digest`, each
affected ToolDraft shared/local digest, Design Artifact and eventual package
content are recomputed and may change; tests must verify the unchanged digest
formula and valid propagation, not equal value-level digests.

Five hundred is a live hypothesis, not a claimed proof. It bounds the one
source string at 500 code points and the framework-expanded compiled policy
text at at most 8 x 500 = 4,000 code points per group. The exact same-parent
suffix below must prove sufficiency; any `>500` terminal starts a new diagnosis.

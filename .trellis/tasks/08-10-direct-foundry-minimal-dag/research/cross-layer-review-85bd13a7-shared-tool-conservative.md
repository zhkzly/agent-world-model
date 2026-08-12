# Research: cross-layer review — SharedTool conservative partition

- Query: Review the latest SharedTool diagnosis and repair plan for authority, canonical semantics, and downstream compatibility.
- Scope: internal
- Date: 2026-08-12

## Decision

**Decision: allow**

- Plan SHA-256: `85bd13a73024d4accd7e7b2cdcb066c016b594a7807e815124a495b16d56c2a3` (recomputed).
- Revision: `1/2`; scope: local Direct recipient-contract repair.
- Trigger: real `run_13b48bda4cde4498a95c0a7e0d402f6a` failed at `design/shared_tool_semantics[1-2-3-4-5-6-7]` after two completed Direct calls; safe Observe shows a failed Direct work, blocking Designer Finding, no output, and `not_published`.

## Basis and impact chain

Canonical §601/603 requires the Direct SharedTool prompt to expose the exact frozen group, exact partitions, and the conservative whole-group domain when evidence does not warrant a finer split; the compiler remains authoritative (`docs/agent-world-environment-generation.zh.md:601-605`).

```text
Direct LLM recipient contract -> framework partition compiler -> SharedToolContract
-> ToolDraft -> ModelingGate -> Candidate/Package/Registry -> Observe
```

- **Framework** keeps group derivation, exact validation, correction bound, Artifact/Work and release ownership. It must not synthesize or normalize a partition (`agent_world/design.py:1245-1355`).
- **Direct LLM** keeps semantic grouping, ordering, compensation, and policy text; it has no Skill, tool, workspace, or release authority (`agent_world/design.py:546-568`).
- **Agent and candidate process** are unaffected; converting this node to Agent would violate the Direct boundary.
- The compiled fields/ABI are unchanged: ToolDraft consumes the committed contract digest (`agent_world/design.py:1391-1492`), ModelingGate consumes `shared_tools` refs (`agent_world/design.py:2085-2111`), Candidate/Registry serialize and revalidate the same contract (`agent_world/candidate.py:304-325`, `agent_world/candidate.py:2536-2564`), and Observe remains read-only (`agent_world/observe.py:498-536`). Future Expand reuses this DesignGraph contract, not a separate SharedTool ABI.

## Allow limits and proof

Implement only the existing output-shape sentence, safe partition-correction condition, matching node card, and focused tests. State the whole-group form as a permitted conservative construction—not a framework-generated default—and retain exact compiler rejection, one correction/two-call bound, fields, graph, route, retries, Candidate, Registry, and Observe.

The focused test must preserve the distinction between unchanged compiled-contract ABI and a **new semantic revision** for the changed output shape (`agent_world/design.py:584-627`; `agent_world/graph.py:441-460`; `tests/test_design_semantics.py:361-445`). Keep invalid-partition and Registry digest regressions (`tests/test_design_semantics.py:562-628`; `tests/test_direct_release.py:978-1005`), then run the planned full checks.

Smallest real proof: reuse the immutable parents and real Luna route; commit the repaired SharedTool shard within two calls, run only `tool_semantics[register_member]`, stop, and read Observe. A new failure starts a new diagnosis. A fresh public Direct E2E is permitted only after this suffix passes.

## Non-claims and next gate

This does not prove complete Design, Candidate, Judge, Package, Registry, Direct E2E, Repair, Expand, or Consumer. The cited scene is a diagnostic suffix (`status=running`, `terminal_code=null`), not release evidence.

Next permitted gate: main session records this matching allow in both context manifests, then dispatches implementation and an independent check. The allow expires on a plan-digest, trust-boundary, or relevant-scene change.

## Files found

- `research/diagnosis-shared-tool-conservative-partition-undisclosed.md` — latest causal diagnosis.
- `research/shared-tool-conservative-partition-plan.md` — reviewed exact plan.
- `docs/agent-world-environment-generation.zh.md` — canonical §601/603 authority.
- `agent_world/design.py`, `graph.py`, `candidate.py`, `observe.py` — direct producer and downstream consumer evidence.

## External references

None; this decision is based only on repository evidence.

## Caveats / Not Found

Per research-role isolation, `implement.jsonl` and `check.jsonl` were not loaded; the main session must add this allow record before dispatch.

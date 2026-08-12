# Minimal repair plan revision 2 — Design input provenance closure

## Scope

Close only the three facts in
`diagnosis-design-input-provenance-gap.md` plus the same-pattern ModelingGate
dependency found by `direct-design-provenance-whole-diff-recheck.md`. Keep the existing two graphs, node
families, execution kinds, routes, compilers, Artifacts and downstream package
shape. No new production file, dependency, abstraction or retry is permitted.

## Exact changes

1. Replace `ResearchQuery` plus `ResearchPlan.source_hints` with
   `ResearchPlan.queries: tuple[str, ...]` and the already-consumed
   `questions_to_resolve`. The Research Agent Prompt and the one existing
   `research-world-evidence` Skill disclose exactly
   `{queries:[text] (1..6), questions_to_resolve:[text] (1..12)}`. Compiler
   rejects empty/duplicate/bounded-length violations. Acquisition uses each
   frozen query string; synthesis uses the frozen questions. No accepted field
   remains consumerless.
2. Add `evidence` to the existing SharedToolSemantics, CurriculumPlan and
   TaskRequirement NodeSpec input ports. Add exactly one
   `research_synthesis.evidence -> <node>.evidence` Edge for each. Bind the
   exact committed `evidence_ref` in each corresponding `graph.execute` input
   map. Do not add another port type or routing rule.
3. SharedToolSemantics and CurriculumPlan keep their current evidence-backed
   projections/compilers. TaskRequirement additionally receives the exact
   safe citation catalog already used by its compiler, so RuleDraft citation
   indexes are both disclosed and causally recorded. No raw source text enters
   these Direct nodes.
4. Update only the affected ResearchPlan section and the three input
   declarations in `node-contracts.md`. The canonical source remains unchanged.
5. `modeling_gate` already consumes the committed `shared` contracts when it
   builds `DesignContract`. Add the existing `shared_tools` input port, exact
   `shared_tool_semantics.shared_tools -> modeling_gate.shared_tools` Edge and
   exact `shared_refs` input/semantic binding. Declare this same existing port
   optional for ModelingGate so a one-tool world binds an empty tuple without a
   fake Artifact or WorkRecord. The optional-port allowlist remains closed to
   only ToolSemantics and ModelingGate `shared_tools`; no generic optional-port
   mechanism or new port type is added.

## Files

- `agent_world/contracts.py`
- `agent_world/graph.py`
- `agent_world/design.py`
- `agent_world/runtime_skills/research-world-evidence/SKILL.md`
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md`
- `tests/test_graph_contracts.py`
- `tests/test_design_semantics.py`

Delete replaced code in place. Production LOC must be net non-increasing for
this repair; no compatibility property, normalization adapter or dormant field
may remain.

## Deterministic acceptance

- no `ResearchQuery`, `source_hints` or query `purpose` remains in product
  contracts, Prompt, Skill, compiler, package projection or tests;
- backend spies prove the exact lighter ResearchPlan output and both consumers;
- all three nodes declare `evidence`, have the exact source Edge and commit the
  evidence Artifact digest in dependency closure;
- ModelingGate declares/binds every SharedToolSemantics Artifact and a
  shared-contract-only revision changes its dependency closure; a zero-group
  Design binds an empty optional `shared_tools` tuple without a fake Artifact;
- TaskRequirement's exact model projection contains the same citation catalog
  used by its compiler;
- changing only the Evidence Artifact changes each affected WorkRecord
  dependency/semantic identity and stale reuse cannot match;
- every other node port/route/Skill remains unchanged;
- full pytest, Ruff format/check, mypy source+tests, compileall, diff check and
  legacy firewall pass.

## Proof and non-goals

After implementation, repeat the independent whole-diff check. Only `allow`
permits the existing ordered live proof sequence. This repair adds no live
call, new provider behavior, Candidate/Runtime/package schema, Repair, Expand,
Consumer or training behavior.

# Direct Design provenance whole-diff recheck

- Date: 2026-08-11
- Worktree: `/home/kelong/pycodes/foundry-direct-graph`
- Decision: **block**
- Reviewed implementation allows:
  - `abbab652bfbd389bde56d4c9879948e0c6436faa4eb5ef2a72c8d1f220a3c219`
    — Direct semantic-closure implementation
  - `5df3243e47c0703e9e5ec64d79dbfeb7963f847a4ba9990497e180090d3cb2b9`
    — bounded ResearchPlan/Evidence-provenance repair
- Evidence class: static whole-diff inspection plus deterministic local checks.
  No model, Agent SDK, network, candidate-process, Judge, Registry, or live
  Direct proof was run.

## Scope and current-repair verification

The current tree remains within the two fixed Direct graphs and the existing
`agent_world/` slice.  No third graph, scheduler, dynamic graph/plugin/rule
platform, Repair, Expand, Consumer/SFT/RL path, compatibility route, second
Builder/Judge/Registry, or legacy control authority was found.  Production
Python is 10,267 LOC, down from the PAC-58 pre-repair count of 10,289.

The exact 5df repair is present and closed at its named boundaries:

1. `ResearchPlan` is only `queries: tuple[str, ...]` and
   `questions_to_resolve: tuple[str, ...]` (`agent_world/contracts.py`).
   The Researcher prompt and mounted Skill expose that same closed shape;
   acquisition consumes every bounded query string and synthesis consumes the
   frozen questions.  No active `ResearchQuery`, query `purpose`, or
   `source_hints` remains.
2. `shared_tool_semantics`, `curriculum_plan`, and `task_requirement` each
   declare `evidence` in `DESIGN_NODES`, receive the exact
   `research_synthesis.evidence` edge, and bind the committed `evidence_ref`
   in their `GraphRunner.execute` input map (`agent_world/graph.py`,
   `agent_world/design.py`).
3. Their effective Direct projections include only the safe citation catalog,
   never raw source text.  In particular, TaskRequirement now receives the
   same `EvidenceGraph.catalog` passed to its RuleDraft compiler.  Focused
   tests prove an Evidence-only change alters each named node's dependency
   closure and semantic identity.

The Design -> Candidate -> Judge -> package -> Registry -> Observe chain
otherwise retains the intended separation: CandidateBuild sees only Design,
ImplementationContract, and BuildPlan; verifier/private cases do not enter its
workspace; Integration is verifier-independent; Judge cold-reads the exact
passed Integration and verifier commitment; package metadata carries the typed
world/rule/task/protocol/provenance/assurance/fidelity closure; Registry
cold-verifies it; and Observe exposes only safe durable facts.  The audit found
no new private snapshot, sealed case, evaluator goal, prompt, credential,
candidate release claim, or first-family/first-tool consumer path.

## Finding (not fixed)

### ModelingGate accepts a SharedToolSemantics value without its declared exact Artifact input

`DesignExecutor._modeling_gate` receives the committed `shared` tuple and
places it directly in `DesignContract.shared_tool_contracts`
(`agent_world/design.py:1980-2125`).  That value is then consumed by the
Builder projection, package `world/rule_ir.json`, Registry cold-read, and the
future released-package semantic handoff.

However, the static `modeling_gate` NodeSpec declares only
`evidence, architecture, tool_semantics, curriculum, tasks, rules`, and
`DESIGN_EDGES` has no `shared_tool_semantics.shared_tools -> modeling_gate`
edge (`agent_world/graph.py:203-211`, `agent_world/graph.py:341-347`).  Its
`graph.execute` input map similarly omits `shared_refs`
(`agent_world/design.py:2087-2114`).  Therefore the ModelingGate WorkRecord and
ArtifactEnvelope direct dependency closure do not name the immutable
SharedToolSemantics Artifact even though the compiler accepts that artifact's
value and carries it to Design/package/Registry.

The ToolDrafts bind each shared-contract digest, so ordinary sequential Direct
execution will normally propagate a changed shared contract through changed
ToolSemantics refs.  That transitive relationship is not a substitute for the
binding node card and plan requirement that ModelingGate consume all exact
committed architecture/group/tool/world-rule/curriculum/task refs.  It also
does not record the exact group Artifact that the compiler directly accepts.

This is a semantic graph/provenance and persistence-contract correction, not a
mechanical fix.  The 5df allow permits only the bounded ResearchPlan deletion
and the three Evidence bindings; it does not authorize a ModelingGate port,
edge, dependency, semantic-identity, or test change.  I made no product code
change.

### Required next gate

Write a minimal revised plan and obtain a fresh cross-layer critic allow before
implementation.  The smallest coherent correction is to add the existing
`shared_tools` input port and exact
`shared_tool_semantics.shared_tools -> modeling_gate.shared_tools` edge, pass
the exact `shared_refs` tuple to ModelingGate, bind that input in its semantic
provenance, and add a regression that a shared-contract-only revision changes
the ModelingGate direct dependency closure and prevents stale reuse.  It must
not add a node, graph, owner, route, metadata format, or future-child behavior.

Because this defect is static, no Observe scene is invented.  No live proof is
permitted from this record; after the bounded repair and a fresh independent
whole-diff allow, resume the ordered real-proof sequence.

## Deterministic verification

- `uv run pytest`: pass — 159 passed.
- `uv run ruff format --check .`: pass — 22 files already formatted.
- `uv run ruff check .`: pass.
- `uv run mypy agent_world tests`: pass — no issues in 22 source files.
- `uv run python -m compileall -q agent_world`: pass.
- `git diff --check`: pass.
- `uv run pytest -q tests/test_legacy_firewall.py`: pass — 2 passed.

These checks are deterministic evidence only.  They do not prove a real
Researcher/Direct model call, CandidateBuild, isolated candidate execution,
Judge, Registry publication, or end-to-end EnvironmentPackage.

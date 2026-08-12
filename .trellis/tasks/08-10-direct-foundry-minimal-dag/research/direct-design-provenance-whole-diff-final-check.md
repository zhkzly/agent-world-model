# Direct Design provenance whole-diff final check

- Date: 2026-08-11
- Worktree: `/home/kelong/pycodes/foundry-direct-graph`
- Decision: **block**
- Reviewed current allow: `sha256:e9f664ba3e6e27fcf30cd3c60cb3c0981c58f49fb13210f2cd23b4fa15c66137`
- Evidence class: static whole-diff/code-path review plus deterministic checks.
  No live API, model, Agent SDK, candidate-process, Judge, Registry, or E2E
  invocation was run.

## Scope and positive evidence

The current tree remains at the intended two fixed graph boundary in the
inspected Direct surface.  `DESIGN_NODES` and `CANDIDATE_NODES` remain the two
static graphs; no third graph, dynamic graph/plugin registry, generic
scheduler, Repair, Expand, Consumer, legacy `awm`/StateGraph/replay/ABI route,
or second Builder/Judge/Registry authority was found in the reviewed path.

Production Python is exactly **10,281 LOC**, matching the required
provenance-repair baseline of 10,289 with net **-8**.  The e9f repair itself is
present: `modeling_gate.shared_tools` is in the closed optional-port allowlist,
declared on the NodeSpec, connected by the exact
`shared_tool_semantics.shared_tools -> modeling_gate.shared_tools` Edge, bound
in `graph.execute`, and represented by ordered digests in its semantic
material.  The zero-shared-group path passes an empty tuple without a synthetic
Artifact.

## Findings (fixed)

None.  This review was report-only by instruction.

## Findings (not fixed)

### 1. Semantic revisions do not bind every directly consumed immutable input

This is release-blocking provenance/persistence drift.  The `GraphRunner`
semantic revision is the only recorded identity used to distinguish an
effective model/framework transaction.  Its semantic material must therefore
cover every semantic Artifact value actually disclosed to an Agent or consumed
by a framework compiler, in addition to the WorkRecord dependency closure.

Two exact current-code examples show that the e9f shared-input correction is
incomplete:

1. `DesignExecutor._research_synthesis` writes
   `plan.questions_to_resolve` into the Agent-visible `evidence.json`, and
   binds `research_plan` as an exact graph input.  Its `graph.execute`
   semantic material contains only `request_digest`, the citation catalog, and
   output shape; it contains neither the plan ref/digest nor the disclosed
   questions.  Thus a changed frozen ResearchPlan question can change the
   actual Agent input while the semantic revision remains unchanged.
2. `DesignExecutor._modeling_gate` directly constructs `DesignContract` from
   `evidence`, `shared`, `tools`, rules, curriculum, and requirements.  Its
   input map correctly binds `evidence_ref`, `shared_refs`, and `tool_refs`,
   but its semantic material contains `architecture`, `shared_tools`, rules,
   curriculum, and tasks only.  In particular, it omits the direct
   `evidence_ref` and `tool_refs`.  A changed EvidenceGraph or ToolSemantics
   Artifact can therefore change the compiled/persisted EnvironmentDesign while
   the ModelingGate semantic revision remains unchanged.

`WorkRecord.dependency_refs` does retain these refs, but that is not a
substitute for the semantic-revision identity required for the actual
model/framework input.  The current focused regression proves only the new
shared-contract mutation; it does not cover the ResearchPlan-question,
ModelingGate-evidence, or ModelingGate-tool-semantics cases above.

This is a semantic persistence/validation-contract change, not a mechanical
formatting repair.  It is outside the final e9f plan scope and must not be
self-fixed here.  Required next gate: write a minimal revised plan that states
the exact semantic-material bindings and regressions for each direct input,
obtain a fresh cross-layer critic allow, implement only that bounded closure,
and repeat an independent whole-diff check before any ordered live proof.

## Verification

- `uv run pytest -p no:cacheprovider`: **pass** — 160 passed.
- `uv run ruff format --check .`: **pass** — 22 files already formatted.
- `uv run ruff check .`: **pass**.
- `uv run mypy --no-incremental --cache-dir /tmp/trellis-check-mypy-e9f664ba agent_world tests`: **pass** — no issues in 22 source files.
- `PYTHONPYCACHEPREFIX=/tmp/trellis-check-pycache-e9f664ba uv run python -m compileall -q agent_world`: **pass**.
- `git diff --check`: **pass**.
- `uv run pytest -p no:cacheprovider -q tests/test_legacy_firewall.py`: **pass** — 2 passed.

## Explicit non-claims

This static report does not claim a real Researcher or Direct LLM invocation,
Codex Skill visibility, candidate generation, isolated Integration, Judge
verdict, Registry publication, safe released Observe scene, or an end-to-end
EnvironmentPackage.  It also makes no blocking claim about future bounded
Repair, Expand/multi-parent evolution, Consumer/SFT/RL, or training paths;
those are not Direct completion criteria.  The requested stop point means no
additional non-blocking surface was expanded beyond the current code, context,
and deterministic checks listed above.

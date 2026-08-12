# Direct typed Design-to-Registry whole-diff check

- Decision: **block**
- Reviewed implementation allow: `abbab652bfbd389bde56d4c9879948e0c6436faa4eb5ef2a72c8d1f220a3c219`
- Basis: read `check.jsonl` in order, the Direct PRD/design/implement artifacts,
  `AGENTS.md`, the complete canonical product document and execution map, final
  allow, and PAC-55. This is a static whole-diff check; no model, network, or
  candidate live proof was run.

## Scope and authority check

The implementation stays in the two fixed Direct graphs and the approved
existing `agent_world` slice. I found no added production dependency, third
graph, node kind, scheduler, generic schema/rule/workflow platform, Repair,
Expand, Consumer, compatibility route, second Builder/Judge/Registry, or
legacy authority. Direct LLM nodes declare no Skill; every Agent node declares
its one mounted Runtime Skill; Candidate/Integration/Judge/Registry ownership
remains separated. The all-family/tool DesignContract, recipe, private-case,
runtime, package, Registry cold-read, and safe Observe paths are present and
the deterministic suite covers their principal tamper/closure cases.

The two findings below nevertheless violate the approved plan's universal
node-transaction rule: every visible input must have a typed recorded path and
every accepted model/Agent field must have a current consumer. They are
contract/provenance repairs, not mechanical cleanup, so this check does not
self-edit them.

## Findings (not fixed)

### 1. ResearchPlan accepts semantic fields that the Direct path discards

`research_plan` asks the Agent for `queries[{query,purpose}]` and
`source_hints` and compiles both into `ResearchPlan`
([design.py:636-697](../../../../agent_world/design.py)). The only acquisition
consumer iterates `plan.queries` and sends only `query.query` to Search
([design.py:754-785](../../../../agent_world/design.py)); repository-wide use
search finds no consumer of `ResearchQuery.purpose` or `ResearchPlan.source_hints`.
`questions_to_resolve` is consumed by ResearchSynthesis, but these other
accepted Agent fields affect only the stored DTO/digest.

This conflicts with the plan's requirement that every model-owned semantic
field have a compiler assertion and named downstream consumer. It also fails
the requested no-discard audit and PAC-55's minimality gate.

Smallest repair: revise the bounded plan and critic review, then either remove
the unused fields from the Agent Skill, Prompt, `ResearchPlan`, fixtures and
tests, or give them an explicit, safe, provenance-recorded current Direct
consumer. Do not merely retain them as audit metadata or infer behavior from
them later.

### 2. Evidence is visible to SharedToolSemantics and CurriculumPlan but absent from their graph ports and immutable dependencies

The fixed graph declares `shared_tool_semantics` with only `architecture` and
`curriculum_plan` with only `architecture,rules`
([graph.py:161-200](../../../../agent_world/graph.py)). Correspondingly,
`DESIGN_EDGES` has no Evidence edge to either node
([graph.py:320-345](../../../../agent_world/graph.py)).

Actual execution contradicts those declarations:

- SharedToolSemantics passes `evidence.catalog` as the Direct LLM's visible
  `citations` projection, but commits with only the architecture input
  ([design.py:1398-1413](../../../../agent_world/design.py)).
- CurriculumPlan passes `evidence.catalog` as visible `citation_catalog`, and
  its compiler validates Agent-selected citations against that catalog, but
  commits with only architecture and rules
  ([design.py:1844-1858](../../../../agent_world/design.py)).

Consequently those two Artifacts' recorded dependency closure and graph
semantic declaration omit an input that can change the Direct prompt, accepted
citations, and compiled output. This is precisely a hidden model input rather
than an exact visible input/closed provenance path; it also makes an
evidence-only change unable to invalidate those WorkRecords.

Smallest repair: revise the plan and obtain fresh critic approval for the
existing-node contract correction. Add the Evidence input port and exact
`research_synthesis.evidence` edge for both nodes, pass `evidence_ref` in both
`graph.execute` input maps, and add regression tests proving the port/dependency
closure and evidence-change semantic revision. This does not require a new
node, graph, or authority, but it is a graph-contract/persistence change and
is outside this reviewer's mechanical-fix permission.

## Verified closure that remains positive

- DesignContract rejects non-ordered/missing scoped family-tool recipes and
  binds every executable task's verification digests
  ([contracts.py:968-1045](../../../../agent_world/contracts.py)).
- Integration consumes every recipe without Verifier input; Judge separately
  consumes every baseline recipe plus same-run private cases and checks trusted
  reward/termination ([runtime.py:653-790](../../../../agent_world/runtime.py)).
- Public verifier commitments and private cases bind commitment id,
  family/tool, variation and exact baseline recipe; Judge re-derives and checks
  the binding before execution ([candidate.py:1177-1444](../../../../agent_world/candidate.py)).
- The Builder projection excludes Verifier/private/Judge/release material;
  package/Registry and Observe use canonical cold-read/safe projections. No
  private values were found in Observe's release projection.

## Code-size and minimality assessment

Current production Python is **10,289 LOC**, matching PAC-55's stated
8,809-to-10,289 (+1,480) closure budget. The inspected implementation adds no
future-only production module or authority, and removes the obsolete
first-tool/first-task consumers. Finding 1 is nevertheless dormant model
output/data and Finding 2 is untracked provenance, so the minimality gate is
not yet satisfied.

## Deterministic verification

- `uv run pytest` — pass, 156 tests
- `uv run ruff format --check .` — pass
- `uv run ruff check .` — pass
- `uv run mypy agent_world tests` — pass
- `uv run python -m compileall -q agent_world` — pass
- `git diff --check` — pass
- `uv run pytest -q tests/test_legacy_firewall.py` — pass, 2 tests

These are deterministic evidence only. They do not prove a real Direct model
call, Agent invocation, CandidateBuild, isolated candidate execution, Judge,
Registry publication, or end-to-end EnvironmentPackage.

## Exact next permitted gate

Return to the static diagnosis/plan revision path for the two findings above,
obtain a fresh cross-layer critic `allow`, implement only the bounded
ResearchPlan-consumer and Evidence-port/dependency corrections, and dispatch a
fresh independent whole-diff check. No live proof is permitted from this
record.

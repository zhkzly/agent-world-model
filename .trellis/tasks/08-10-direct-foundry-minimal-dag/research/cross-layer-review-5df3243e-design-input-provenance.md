# Cross-layer review: Design input provenance closure

- Decision: allow
- Date: 2026-08-11
- Plan digest: `sha256:5df3243e47c0703e9e5ec64d79dbfeb7963f847a4ba9990497e180090d3cb2b9`
- Plan revision: `direct-design-input-provenance-plan.md`, initial revision after static Diagnosis Record `diagnosis-design-input-provenance-gap.md`
- Revision count: 1
- Scope classification: coordinated cross-node, confined to the existing Direct DesignGraph

## Trigger, target, and trust boundary

The static whole-diff review found (a) `ResearchPlan` fields accepted from the
Researcher but without a present Direct consumer, and (b) Evidence consumed by
three Design nodes without being declared as an exact input/dependency. There is
no Observe scene or live terminal for this defect; the applicable evidence is
the static Diagnosis Record and code/graph inspection only.

The product target remains: turn an arbitrary natural-language
`EnvironmentRequest` into an evidence-grounded executable environment,
independently verify it in a real isolated boundary, publish an immutable
Registry `EnvironmentPackage`, and expose only safe facts through Observe.
This repair advances only the `Research -> Design/WorldSpec -> Task` provenance
portion. It does not claim Builder, Runtime, Judge, Package, Registry, Expand,
Consumer, or end-to-end Direct completion.

Affected trust boundary: framework-owned DesignGraph disclosure and immutable
provenance. A node's exact `NodeSpec` input ports, `EdgeSpec` bindings, and
`graph.execute` ArtifactRefs must cover every value that changes its Direct
Prompt, compiler verdict, or committed Artifact.

## Plan digest and exact impact chain

The supplied complete plan hashes to the stated SHA-256 digest. Its scope is the
smallest coherent correction:

```text
Researcher ResearchPlanDraft
  -> ResearchPlan -> acquisition(query strings) / synthesis(questions)
  -> EvidenceGraph
  -> SharedToolSemantics / CurriculumPlan / TaskRequirement
  -> ModelingGate -> EnvironmentDesign -> existing CandidateGraph
  -> Package -> Registry -> Observe
```

1. `ResearchQuery.purpose` and `ResearchPlan.source_hints` are consumerless:
   acquisition reads only `query.query` (`agent_world/design.py:754-785`) and
   synthesis reads only `questions_to_resolve` (`design.py:816-951`). Deleting
   the pair/type and retaining bounded query strings plus questions makes the
   Agent Prompt, Runtime Skill, compiler, typed contract, and consumers agree.
   It adds no research subsystem, new source policy, or later consumer.
2. `shared_tool_semantics` exposes `evidence.catalog` in its projection
   (`design.py:1398-1413`), but its NodeSpec has only `architecture` and its
   commit map omits Evidence (`graph.py:161-170`, `design.py:1403-1413`).
3. `curriculum_plan` exposes and validates the catalog
   (`design.py:1655-1729`, `1844-1858`) but declares/commits only architecture
   and rules (`graph.py:193-201`, `design.py:1854`).
4. `task_requirement` uses the catalog in all `RuleDraft` compilation
   (`design.py:1876-1965`) but neither exposes it to the Direct model nor
   declares/commits its Evidence input (`graph.py:203-211`,
   `design.py:1969-1995`).

Adding exactly the existing `research_synthesis.evidence` port/edge/input
binding to those three nodes makes Evidence-only changes change their input
closure and semantic identity. Giving TaskRequirement the same already-used
safe `CitationCatalog` closes both model disclosure and compiler provenance;
it does not disclose raw source text or introduce an Artifact type.

## Owners and compatibility

- Owner remains `designer` for ResearchPlan, EvidenceGraph, all three affected
  nodes, and ModelingGate. `GraphRunner` remains the single framework commit
  owner. No Agent, Direct LLM, Candidate, Builder, Judge, or Registry gains
  authority.
- `research_plan` remains the sole Agent output consumed by existing
  `research_acquire` and `research_synthesis`; only the dead fields disappear.
- The three changed Direct nodes retain their existing output ports, output
  contracts, route (`direct`), compiler ownership, shard identities, and later
  consumers. ModelingGate already declares Evidence and consumes the same
  final Architecture/Tool/Curriculum/Task outputs, so no CandidateGraph,
  package, Registry, Expand, or Consumer contract changes are required.
- Existing `world_architecture` already declares/binds Evidence
  (`graph.py:151-160`, `325-326`; `design.py:1243-1259`) and `tool_semantics`
  already does so (`graph.py:171-181`, `328-330`; `design.py:1548-1564`).
  `world_rules` consumes neither Evidence nor its citation catalog and passes
  an empty allowed-citation set to its compiler (`design.py:1571-1642`), so it
  is not a concrete instance of this hidden Evidence-input defect. No further
  node in this exact Design path is proven to require the same repair.

## Smallest allowed implementation and proof

Implementation may edit only the plan-listed production files, derived node
card, and focused tests. It must:

- remove `ResearchQuery`, `source_hints`, and query `purpose` everywhere in the
  active product contract/Prompt/Skill/compiler/fixtures;
- retain only bounded, nonempty, unique query strings and consumed questions;
- add one existing `evidence` port and one
  `research_synthesis.evidence -> <node>.evidence` edge for each named node;
- pass the exact `evidence_ref` to every corresponding `_direct_commit` input
  map, including every shard; and
- add TaskRequirement's existing safe citation catalog to its projection.

No new node, Artifact/type/module, route, schema, compatibility layer, retry,
or later child behavior is permitted. Production LOC must be demonstrated as
non-increasing for the completed patch; removal of the obsolete DTO/fields is
not permission to add compensating abstractions.

The smallest deterministic proof is the plan's focused graph and design
semantic tests: assert the lighter ResearchPlan exact output and both real
consumers; assert each of the three new ports/edges/bindings; assert
Evidence-only changes alter every affected WorkRecord's dependency/semantic
identity and prevent stale reuse; and assert the TaskRequirement projection
contains exactly the catalog accepted by its RuleDraft compiler. Then run the
specified repository quality suite and an independent static whole-diff check.

## Non-claims and next permitted gate

This allow is not real-provider, Agent, isolated candidate, Judge, Package,
Registry, release, Expand, or Consumer evidence. It does not approve a live
proof. It expires if the plan digest, these DesignGraph trust boundaries, or
the relevant scene changes.

Next permitted gate: dispatch implementation limited to this allowed plan;
after deterministic verification, perform the independent whole-diff check.
Only a later matching allow may permit the ordered live proof sequence.

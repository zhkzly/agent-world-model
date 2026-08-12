# Static diagnosis — Design input provenance and unused ResearchPlan fields

- Date: 2026-08-11
- Trigger: `direct-design-semantic-closure-whole-diff-check.md` returned
  `block` after 156 deterministic tests passed.
- Evidence class: static code/graph inspection only. No Observe scene or live
  terminal exists for this defect.

## Expected product behavior

Every model/Agent field must have one current Direct consumer, and every value
that can change a Prompt, compiler verdict or committed Artifact must be a
declared graph input with an immutable dependency. This protects the canonical
need -> executable, independently judged, publishable EnvironmentPackage path;
green graph tests alone are not product completion.

## Actual behavior and cause

1. ResearchPlan accepts query `purpose` and `source_hints`, but acquisition
   consumes only each query string and synthesis consumes only
   `questions_to_resolve`. The two fields affect a stored DTO/digest and
   nothing else. The derived node card introduced them without a present
   consumer; the canonical document does not require these exact fields.
2. SharedToolSemantics and CurriculumPlan include the Evidence citation
   catalog in their Direct projections, but their NodeSpecs, Edges and
   `graph.execute` input maps omit Evidence. Prompt/output can therefore change
   without the Artifact recording the causal dependency.
3. TaskRequirement uses the Evidence citation set in its compiler while its
   Prompt projection, NodeSpec, Edges and input map omit Evidence. A citation
   can affect acceptance without being visible to the model or recorded in
   provenance.

This is one producer/consumer-provenance defect, not a model, Skill, route,
feedback or retry failure.

## Smallest correction

- Delete ResearchQuery `purpose` and ResearchPlan `source_hints` from the
  Prompt, Skill, compiler, typed contract and fixtures; retain 1..6 bounded
  query strings and 1..12 consumed questions.
- Add the existing `evidence` input port, `research_synthesis.evidence` Edge and
  exact `evidence_ref` input binding to SharedToolSemantics, CurriculumPlan and
  TaskRequirement. Add the citation catalog to TaskRequirement's existing
  projection because its RuleDraft compiler already validates citation indexes.
- Update the derived node card and focused tests. Add no node, graph, module,
  adapter, metadata field or later-child behavior.

## Non-claims

This diagnosis does not prove the correction, any real Direct call,
CandidateBuild, Judge, Registry release, Repair, Expand or Consumer. Live proof
remains blocked pending an allowed plan, implementation and fresh whole-diff
check.

# Independent Direct checkpoint audit

- Reviewer: independent `trellis-research` worker, model `gpt-5.6-terra`
- Scope: uncommitted R9-C2 Direct implementation checkpoint
- Decision: implementation incomplete; do not dispatch final check or live proof
  yet

## Retain

- The two literal `DesignGraph` and `CandidateGraph` declarations and the
  single `NodeSpec`/`EdgeSpec` vocabulary are directionally correct.
- The CandidateBuild input projection omits VerifierIntent and challenge data.
- Candidate code remains out-of-process, the Runtime has the five advertised
  operations, difficulty selection has an ordered validator, and the narrow
  dependency firewall is useful deterministic groundwork.
- The thin Direct/Agent route configuration and product-owned Runtime Skill
  bundles remain aligned with the approved adapter boundary.

## Must replace before proof

- `agent_world/foundry.py` still owns a concentrated linear orchestration and
  creates graph records around already-completed work; the graph is not the
  execution boundary.
- One `_design` model call is copied into several fake semantic node records;
  each Direct semantic node needs its own minimum projection, prompt, closed
  proposal, framework compiler and committed Artifact.
- The raw Integration Artifact is used for release while the graph WorkRecord
  output is discarded. Package and Registry WorkRecords and exact cold-read
  closure are missing.
- The difficulty schema is defined in isolation but is not produced by
  CurriculumPlan, carried by TaskRequirement, exercised by Integration, or
  persisted and recompiled by Registry.
- Candidate installation only scans metadata; it does not execute the exact
  frozen offline `uv` policy or rehash after installation.
- Judge currently mirrors one Integration result across gates instead of
  producing independent evidence from fresh candidate processes.
- The package must bind passed Integration, VerifierBundle, Judge evidence,
  release dossier, telemetry and complete source/metadata closure; Observe
  must revalidate that exact Registry closure.

## Smallest coherent follow-up

1. Extract a compact Design transaction helper/module and make the bounded
   semantic node families perform real Direct calls with framework-owned
   compilation; persist exact ordered WorkRecord refs.
2. Extract Candidate/Integration/Judge/Package/Registry ownership into a
   compact candidate-core module. Pass only committed ArtifactRefs across the
   graph, run the exact stdlib-only offline install, and cold-read every package
   byte before publishing.
3. Add focused regression tests for the producer/consumer closure, then run
   the required real Direct, SDK Skill, Candidate/Integration and fresh E2E
   boundaries. No child Repair, Expand, or Consumer behavior is authorized by
   this audit.

## Product non-claim

The deterministic checkpoint advances the canonical need -> executable,
independently verified, publishable EnvironmentPackage path but does not prove
that path. No live model/Agent, CandidateBuild, installer, Judge, Registry
cold-read, release, Expand, Repair, or Consumer result is claimed.

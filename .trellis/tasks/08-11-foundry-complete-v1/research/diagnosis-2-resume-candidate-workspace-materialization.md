# Diagnosis Record 2: candidate_dependency_metadata_missing on resume (integration rerun)

Date: 2026-08-14 (session)
Real event: run_386e4f07c70d4f61be9cafbf82edcc55, resume --from integration AFTER the
C1/C2/C3' repair (cross-layer-review-c8d540d0). Terminal: rejected /
candidate_dependency_metadata_missing.

## Safe Observe facts

- Previous failure local_tool_semantics_mismatch is GONE: the repaired checker
  (preconditions predicates-only) passed on the frozen design + frozen
  candidate. The approved repair's core claim is proven.
- New integration failure: candidate_dependency_metadata_missing
  (supply_chain._read_candidate_metadata cannot read/parse pyproject.toml /
  uv.lock from the integration workspace).
- The new finding's subject is the same frozen candidate artifact
  build.environment_candidate:b7d139db7142fd72 (owner builder).

## Causal chain (deterministic, framework-owned)

1. CandidateExecutor.run() always creates a NEW empty temp root and populates
   it as a SIDE EFFECT of node execution: _candidate_build writes inputs/,
   templates pyproject.toml + uv.lock, rendered runtime.py; compile_candidate
   writes materializer/LICENSE via the agent + template files.
2. On resume --from integration, graph.execute SKIPS candidate_build, so
   compile_candidate (and the template copies) never run; root stays empty.
3. _integration -> prepare_candidate -> validate_candidate_dependencies ->
   _read_candidate_metadata(root) -> pyproject.toml missing ->
   candidate_dependency_metadata_missing.
4. The candidate artifact payload persists only the manifest (path/digest/size/
   mode); the source bytes are NOT stored anywhere durable (run-dir
   candidate_source/ keeps only *.py diagnosis copies). Therefore the workspace
   CANNOT be reconstructed from committed state; any resume that skips
   candidate_build cannot reach integration/judge/package.

## Five-lens status

- Lenses 1 (project view), 2 (prompt/input), 3 (skill), 5 (feedback): not
  causal — this is a persistence/materialization defect.
- Lens 4 code/execution: SUPPORTED — CandidateExecutor.run() workspace
  population is coupled to node execution; no source-closure artifact exists
  for resume materialization. Boundary: Builder/Controller resume lane.

## Rejected strategies

- Retrying --from integration again (deterministic empty-workspace failure).
- Copying candidate_source/*.py into the temp root (pyproject/uv.lock/LICENSE/
  inputs are missing; also a host-side patch, not a resume contract fix).

## Immediate next proof (no new code; exercises the APPROVED C1/C2/C3' plan)

- resume --from candidate_build: re-dispatches the codegen agent (new prompt
  context + fixed conditional runtime renderer), re-populates the workspace,
  then re-runs integration/judge/package/registry. This is the honest
  end-to-end proof of the approved repair given the persistence gap.

## Repair direction for the resume gap (new plan lineage, NOT yet written)

- Persist a content-addressed source closure (bytes) as part of the candidate
  artifact payload (or a sibling build.environment_candidate_source artifact),
  and materialize the workspace from the committed closure whenever
  candidate_build is skipped on resume. Requires a new repair plan + a fresh
  cross-layer critic round (persistence change).

# Design

## Problem

The repository now has a generic request-driven generated-environment path, but many older files still encode fixed legacy domain behavior. Some are only historical docs, while others are executable modules, public exports, test fixtures, or verifier dispatch branches. Keeping them in the active tree makes it easy for future work to accidentally satisfy a task by selecting a legacy registry or environment-id branch instead of running the pipeline.

## Target Shape

The active package should center on these generic boundaries:

- request/domain planning from raw input
- source discovery and extraction artifacts
- environment/task/surface/verifier artifact generation
- backend-neutral agent implementation and repair attempts
- generated bundle validation
- machine-readable replay contract
- framework-owned independent verification
- package-relative generated runtime release
- legacy `awm` CLI compatibility

Domain examples may exist only as request text inside tests. They must not be encoded as core registries, verifier branches, default tasks, or generated template helpers.

## Code Strategy

1. Delete active legacy modules and fixtures that are not needed by the generic request-driven path.
2. Remove public exports for legacy registries and fixture helpers.
3. Refactor `PipelineRunner` defaults to use `request_driven_node_registry()` and fail explicitly when deterministic implementation is requested for a generated environment.
4. Keep `run_request_driven_pipeline()` as the canonical high-level entry.
5. Make `verify_generated_bundle_independent()` contract-driven only. It should consume accepted tasks and their `framework_replay` contract without environment-id dispatch.
6. Keep `generated_bundle` package checks generic.
7. Rewrite tests around generic request-driven helper agents instead of legacy fixture registries.

## Documentation Strategy

- Rewrite the current task-source document to remove historical Goal 02-12 fixture narrative from the active architecture.
- Update the progress log to record that the old fixture lines were deleted/archived from active code.
- Remove stale goal docs if they conflict with the current project state.

## Risk

The largest risk is over-deleting code still used by the generic pipeline. Validation will be driven by import checks, the full `tests/agent_world` suite, and a legacy-term grep audit over executable code. If a legacy module is only used by tests that validate the deleted fixture itself, delete the test with the module.

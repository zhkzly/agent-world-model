# T2 normal semantic-prefix design

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Bad-case classification

T2 is blocked by **contract input incomplete / historical closure
unverifiable**.  It is not a Builder, Judge, Registry, model, quota, or
isolation failure.  No legal, current, non-diagnostic `ModelingBoundary +
VerifierPlan` closure was available for a downstream single-node test.

## Narrow mechanism

Add an explicit staged command that creates a **fresh normal state root** and
runs the existing `DirectWorkRunner` only through its existing bootstrap and
design epochs:

`Research -> Architecture -> ToolSemantics -> WorldRules -> Curriculum ->
ModelingBoundary -> VerifierPlan`.

The command must use the unchanged role profiles, `InvocationBackend`, leaf
executors, Scheduler, WorkControlRuntime, ArtifactStore, and active-commit
checks.  It must not copy a historical root, mark a diagnostic clone, replay a
target output, invoke Build/Judge/Registry, or claim a release.

The result is a persisted, non-release control record that names the exact
normal active ModelingBoundary and VerifierPlan commits.  Those commits are
inputs for the next T2 single-node work; they are not Registry evidence.

## Guardrails and regression evidence

- The production `generate` path remains the complete three-epoch route to
  Registry; it does not gain a shortened success status.
- The normal prefix result is explicitly `semantic_prefix_ready` or `blocked`,
  with `release_attempted=false`; it has no package or release reference.
- The fresh state root is not a `.test-node-diagnostic` root, so normal
  Scheduler resolution continues to require `require_active_commit`.
- Deterministic tests cover the new CLI contract, isolated-root selection,
  normal-vs-diagnostic state distinction, and the no-Registry/no-final-executor
  boundary.  One real Grok run is the phase acceptance evidence.

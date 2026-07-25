# T2 precondition report — no verifiable complete semantic closure is available

Plan authority: `docs/plans/staged-test-and-debug-plan.md`.

## Classification and required input

- Classification: **contract input incomplete / historical closure unverifiable**.
  This is not a Build, Judge, Registry, model, quota, or isolation failure: no T2
  target was dispatched.
- Current `complete_generation_work_graph` makes the required input explicit:
  the final graph needs one retained `modeling_boundary` and one retained
  `verifier_plan`; Build then consumes exactly one `design.environment_design`
  output from the ModelingBoundary.  A merely committed Architecture, shared
  semantics, or individual ToolSemantics batch is not a legal Build input.
- Normal Scheduler input resolution calls `require_active_commit`.  Its only
  diagnostic-ancestor escape hatch is restricted to a marked diagnostic runtime
  and the one fresh semantic successor path.  Therefore the T1 diagnostic
  commits cannot be promoted or reused as normal T2 Build input.

## Read-only candidate scan

- Git `HEAD`: `26ae43481c2226312a1f84028cf978f1563f01f1`.
- Plan digest:
  `sha256:eb47dec325822bbc8a7f7a57f73882ee5c73c3242fef0e019632213bac6a847f`.
- Gitignored configuration digest:
  `sha256:8f49adaaa55c69de0071444b0332f459b21f0b23054eae8d39f5c81dccb6cc1b`.
- The scan used only `WorkControlStore` head metadata and typed
  `ArtifactStore.get_json(..., WorkAttempt/WorkCommit)` reads.  It printed no
  artifact body, prompt, transcript, credential, or base-URL value.
- Seven non-diagnostic historical state roots were considered.  Two lack a
  `work-control` directory; one has an unreadable `WorkControlStore`; the
  remaining readable roots contain Research/Architecture/SharedToolSemantics
  prefixes and failed or running physical ToolSemantics nodes, but no usable
  ModelingBoundary closure.

## Sole apparent complete-design candidate

- The only discovered committed `design|modeling_boundary|environment_design`
  head is in `.agent-world-live/workgraph-hotel-v2/state`, scope
  `generate-job:7ee879135b5092e45b96d389`, at head revision `8`.
- Both its `control.work_attempt` and `control.work_commit` fail current typed
  parsing with `ValidationError`.  No raw historical value was inspected to
  infer or coerce an old schema.
- Its retained coordinate set also lacks the current required
  `verifier|verifier_plan` predecessor.  Thus it cannot form the current final
  graph even if its opaque historical bytes were otherwise accepted.
- This historical record is consequently not a verified, exact current
  `EnvironmentDesign` input and must not be injected into Build, migrated by
  ad-hoc compatibility code, or treated as a successful semantic commit.

## Execution, usage, and release result

- No model/backend invocation, Build process, Judge process, Registry action,
  consumer action, RepairAction, retry, or fallback model was started.
- Actual/unknown/reserved T2 execution usage: not applicable; no T2 lease was
  reserved or settled.
- No new artifact, trace, manifest, or package was written by this scan.

## Verification

- `git diff --check` passed after adding this report.
- `UV_CACHE_DIR=/tmp/agent-world-uv-cache uv run pytest -q tests/agent_world`
  completed with `684 passed, 2 skipped, 2 warnings in 914.05s`.  The two
  warnings are the existing Python multiprocessing `fork()` deprecation
  warning from the cross-process durable-operation-control test; they are not
  a T2 result.

## Stop reason and next boundary

T2 is honestly **blocked before dispatch**: the repository has no complete,
typed, non-diagnostic semantic closure that current code can verify and bind to
the required final topology.  Running Build from a partial/old/diagnostic
record would violate the plan's input-closure and no-replay redlines.

The next work must establish such a closure through a deliberately staged,
fresh normal semantic-prefix mechanism (or discover a current typed closure),
with its own plan-compatible single-node/closure evidence.  Build, Judge,
Registry, and T3 remain unstarted.

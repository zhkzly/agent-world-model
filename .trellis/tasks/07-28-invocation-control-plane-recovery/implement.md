# Invocation control-plane recovery redesign — implementation plan

## Preconditions

- Do not begin implementation until the user reviews/approves the final plan.
- Do not launch an already-terminal frozen semantic coordinate again.  The two
  real Codex liveness cases already admit this refactor.
- Before every mutation or retry, read the safe scene/control record.  If it
  cannot distinguish a concrete next read, repair feedback/observability before
  changing Prompt, Skill, or semantic code.

## Phase A — control-plane primitives

1. Add safe typed contracts under `agent_world/invocation/`:
   physical-attempt state, lifecycle event, terminal fact, ownership, and policy
   decision.  Contracts must reject prompt/response/session/path material.
2. Implement atomic, idempotent `InvocationControlStore` and compact current
   summary projection.  Persist a safe process-birth identity when available;
   reconcile legacy/no-identity active records fail-closed so a cross-namespace
   or reused numeric PID cannot leave them indefinitely `running`.
3. Implement `InvocationControlPlane` as the sole production wrapper around
   `RoutedInvocationBackend` while preserving the `InvocationBackend` interface.
4. Add owner settlement adapters:
   `WorkRuntime` owner and standalone audit/component owner.  A terminal fact
   may request a route, never authorize a retry by itself.
5. Add focused constructed-boundary tests for duplicate terminal/cancel races,
   redaction, ownerless-call rejection, and exactly-once settlement.

Expected files: `invocation/contracts.py`, new invocation control/store modules,
`invocation/routing.py`, `app.py`, telemetry/scene projection, focused tests.

## Phase B — adapter lifecycle and physical supervisor

1. Convert Direct local heartbeat callbacks to the common lifecycle sink without
   changing what qualifies as Provider progress.
2. Extend `_codex_worker.py` wire protocol with bounded safe lifecycle messages:
   parent worker-spawn/payload-dispatch plus worker SDK-session/thread/turn
   phases, local wait, worker exit, and cleanup result.
3. Replace overlapping timeout cleanup with one parent-side monotonic supervisor
   for the profile's declared physical wall and bounded process-group cleanup.
   Do not introduce a short no-progress death clock.
4. Run a **true parent-worker subprocess proof** against a controlled blocking
   worker fixture.  It must verify physical child cleanup, terminal
   `InvocationResult`, non-running control record, and absence of fake Provider
   progress.
5. Re-prove Direct's constructed liveness boundary only because the shared
   lifecycle mechanism changed; do not re-run unrelated semantic nodes.

Expected files: `invocation/codex_sdk.py`, `invocation/_codex_worker.py`,
`invocation/direct_llm.py`, telemetry, adapter lifecycle tests.

## Phase C — process-level cancellation settlement

1. Bind an active Scheduler `OperationRun` to ownership before invocation in
   `designer/one_shot.py` and the relevant Builder/Judge leaf paths.
   Bind the exact committed parent input closure at the same time, so every
   retry/fallback can prove it is re-executing only the affected current node.
2. Put shared `ensure_settled(owner)` at the Scheduler, Direct runner,
   diagnostic runners, and CLI command boundary.  Reuse existing
   `WorkRuntime.reconcile_abandoned_operation` accounting/replay rules, but make
   settlement immediate rather than next-run-only.
3. Migrate `invocation-audit` to an audit owner and a non-running
   `interrupted` report status.
4. Add a **true CLI subprocess regression**: start a diagnostic test-node/audit
   command using the blocking worker fixture, interrupt it, then independently
   read Work head/audit state.  Assert exactly one terminal
   operation/evaluation, no stale running head, no unauthorized retry,
   conservative unknown usage, and no private material.

Expected files: `control/work_runtime.py`, `work_scheduler.py`,
`direct_runner.py`, `test_node.py`, `cli.py`, `invocation/audit.py`,
scene code, subprocess tests.

## Phase D — central policy and caller migration

1. Implement the evidence-driven policy routes in design `3.5` as typed data.
   Policy selects an allowed route; WorkRuntime/ledger still authorize the next
   logical attempt.
2. Migrate call sites in order: Scheduler one-shot Designer leaves → Builder →
   Judge compiler → reachability solver → legacy Designer service → audit/doctor.
   For each migrated caller, remove duplicate physical timeout/retry/cancel/
   terminal-normalization behavior.
3. Keep semantic loops only when they consume authorized precise feedback.
   Invalid JSON/envelope stays an attribution question, not a forced hard-coded
   repair strategy.
4. Implement explicit, recorded model fallback definitions behind the approved
   policy: after one recorded same-model fresh-session retry of the same
   classified transient route failure, automatically dispatch the next
   compatible model's visible diagnostic definition.  Prove capability/
   transport compatibility, preserve the exact committed parent closure, never
   re-run upstream committed Work, and never reuse a failed node-local session.
5. Add CandidateBuild-only private workspace recovery as a distinct policy
   route under the existing first same-model infrastructure retry budget. Bind
   a private, verified-active workspace only after the normal terminal
   Proposal/Validation/Feedback/RepairAction chain authorizes it; start a new
   Provider thread, expose the draft only inside its isolated workspace, and
   require normal Candidate validation/commit. Never hand that draft to a
   fallback model or Integration.
6. Audit every `InvocationBackend.invoke` caller and prove no production service
   receives a raw adapter.

## Phase E — verification and E2E resumption

1. After each phase: formatter, lint, type check, focused regression.  Failure
   output must show boundary, owner, terminal fact, expected/actual and one
   permitted next action.
2. Run the process-level liveness and cancellation proofs from Phases B/C.
   These are required even if pytest is green.
3. Run one narrow real live InvocationBackend mechanism not already terminally
   captured, retaining its configured envelope and reading its safe scene first.
4. Only then make one exact frozen CandidateBuild attempt.  A classified
   transient failure may use the one same-model fresh-session retry and then
   the explicit compatible-model fallback for CandidateBuild itself; its
   committed upstream Design/plan closure must remain unchanged.  No
   Integration, release, or registry node starts before CandidateBuild commits.
   Where the first terminal occurs after verified Candidate file activity, prove
   the same-model recovery uses a fresh thread over an untrusted private draft
   rather than an old thread or direct workspace adoption.
5. Once CandidateBuild commits, continue only dependency-ready nodes.  Run
   nodes in parallel only if their profiles, budgets, state roots and artifact
   writes are genuinely independent; never parallelize just to fill a matrix.
6. Before commit: `trellis-check` plus spec/skill update only for a confirmed,
   recurring new pattern.

## Proof matrix

| Claim | Primary proof | Supplementary evidence |
| --- | --- | --- |
| declared Codex wall terminates stuck child | real parent-worker subprocess | adapter lifecycle pytest |
| external interruption settles Work exactly once | real CLI/test-node subprocess + durable read | in-process cancellation regression |
| audit cannot remain running after interruption | real audit subprocess + run record | audit serialization test |
| local lifecycle never fakes Provider progress | telemetry/scene from real adapter boundary | focused unit assertion |
| policy distinguishes routes and preserves workflow progress | constructed closed terminal facts through actual controller/runtime; verify retry/fallback retains parent closure and reruns only current node | policy table tests |
| Prompt/Skill/feedback mutation is warranted | frozen node only after controls pass | rendered Prompt/Skill/scene audit |
| E2E may resume | exact CandidateBuild commit then DAG | generic audit never substitutes |

## Rollback points

- Before Phase B, primitives can be removed without caller migration.
- During migration, a per-caller gate may be disabled only after active owned
  attempts settle.  Never delete control state or replay unknown consumption.
- No rollback changes semantic artifact contracts, release gates, capability
  profiles, or immutable input closure.

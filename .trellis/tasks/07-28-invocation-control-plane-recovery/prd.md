# Invocation control-plane recovery redesign

## Goal

Replace the currently scattered Agent/LLM invocation, retry, timeout,
continuation, and terminal-recovery mechanics with one evidence-driven
Invocation Control Plane.  The purpose is not to force uncertain Agents into
deterministic business contracts: it is to make every real invocation
observable, safely recoverable, and consistently routed so a Code Agent can
attribute a failure before changing a Prompt, Runtime Skill, code, feedback,
or project-execution Agent view.

## Confirmed bad cases

- A closed Codex `internalServerError` reached a real CandidateBuild attempt,
  but the originally implemented diagnostic path produced no local terminal
  excerpt for known enum values.  A feedback-only diagnostic established that
  the underlying condition was temporary Provider capacity, not a WorldSpec
  or semantic validation failure.
- A same-definition CandidateBuild infrastructure retry began normally but
  emitted its last safe telemetry event about 26 seconds after start.  The
  Worker and its Codex app-server remained alive for more than the frozen
  900-second physical wall budget, with no TCP connection, no workspace
  heartbeat, and no durable terminal state.  After graceful interruption the
  process tree exited, while the WorkControl head remained `running` with an
  active operation reference and no scene.
- A separate real, constructed `codex_challenger_solver` InvocationBackend
  probe reproduced the same Worker `ep_poll` / app-server wait / no-TCP
  pattern.  It was stopped once the shared mechanism was proved; its durable
  audit report also remained `running`.  This weakens the hypothesis that the
  CandidateBuild Prompt, Runtime Skill, or workspace task alone caused the
  stall.
- The frozen final graph already contains a terminal real Challenger
  VerifierIntentBatch for the same input closure.  The test guard correctly
  refused a duplicate call, so already-proven nodes must not be retested merely
  to fill a matrix.
- Earlier real boundaries also produced distinct, non-equivalent failures:
  malformed strict structured output on the Grok route, a physical
  `max_output_tokens` terminal after actual Candidate workspace activity, and
  explicit temporary Provider capacity failure.  They must not all be treated
  as generic retries.
- A later real `CandidateBuild` on `gpt-5.4-mini` wrote eleven private
  Candidate files (runtime, materializer, and public tests) before the closed
  `turn_failed_provider_unavailable` terminal at roughly 580 seconds.  It
  returned no `CandidateCompletion`, Candidate manifest, or commit.  The
  workspace is useful evidence of a possible continuation mechanism, but is
  not an Artifact and cannot enter Integration as-is.
- A sandboxed live-agent probe ended outside its PID namespace after creating
  a control record with `owner_pid=5`.  The prior reconciliation rule used
  only `kill(pid, 0)`, so a host process with the same numeric PID could keep
  that unrelated attempt `running` forever.  A later real Grok call proved the
  route itself was healthy (fourteen Provider progress events and a completed
  terminal), which isolates this as an owner-liveness/observation defect rather
  than a Prompt, Runtime Skill, or Provider failure.

## Requirements

- R1. Establish one explicit Invocation Control Plane module behind
  `InvocationBackend`.  Node leaves continue to own semantic Prompt/input,
  Runtime Skill selection, validators, and release decisions; they may not
  independently implement process lifecycle, retry, cancellation, terminal
  normalization, or continuation recovery.
- R2. Define a durable physical-attempt state machine shared by Direct and
  Codex routes: materialization, profile resolution, worker/app-server start,
  first progress, continued progress, response/validation, terminal, cancelled,
  expired, and reconciled.  Every non-terminal attempt has an owner and a
  recovery path; a dead process may never leave a public `running` head or
  invocation-audit record indefinitely.
  Owner liveness must bind a process-birth identity where the platform exposes
  one; a bare PID or a legacy record without that identity must never prove a
  still-running owner across a namespace or PID-reuse boundary.
- R3. Preserve safe, layered observation: compact project-execution Agent
  view/scene facts; durable structured telemetry and attempt history; and an
  opt-in, bounded, redacted local diagnostic sidecar when closed facts are
  insufficient.  Raw provider prompts, responses, endpoints, credentials,
  and private runtime state must not enter Git, artifacts, normal scenes, or
  scheduler feedback.
- R4. Centralize retry and fallback policy as data-driven, idempotency-aware
  policy rather than per-node exception handling.  The initial default policy
  is: a closed transient transport/capacity failure may authorize one
  same-definition, same-model retry only after a route-liveness check and
  recorded backoff. Normally it starts a fresh node-local session and empty
  candidate workspace. For CandidateBuild alone, a closed Provider/transport
  terminal after the leaf has verified real private workspace activity may use
  that same one retry as **fresh-session workspace recovery**: a new thread
  inspects/tests an untrusted draft in the exact isolated workspace and still
  has to return a complete replacement CandidateCompletion through the normal
  validator/commit boundary. It is neither thread resumption nor Artifact
  adoption. If that retry still has the same classified transient route
  failure, the controller must explicitly persist and dispatch the next
  compatible model definition rather than retry blindly. An output ceiling
  with a valid private continuation may authorize an explicit resumed physical
  turn; no-progress/expired attempts require reconciliation before any retry;
  malformed transport/schema output requires effective Prompt/Runtime
  Skill/adapter/feedback attribution; and parsed semantic violations may use a
  bounded repair turn only with precise feedback and repair authority.
- R5. Model fallback must be explicit, frozen, and observable—not a silent
  retry.  Retain the user-approved preference order (Grok where compatible,
  then `gpt-5.3-codex-spark`, then `gpt-5.4-mini`); a fallback is a new
  diagnostic definition once the preceding route has a classified failure.
  It restarts only the affected current node from its exact immutable input
  closure: committed upstream Work nodes and their Artifacts are reused and
  never regenerated.  A failed transient node-local session is never reused;
  cross-node continuity is the committed Artifact closure, not an ambient
  conversational session. The only non-Artifact private continuity modes are
  an explicitly authorized same-node output-ceiling thread continuation and a
  same-model CandidateBuild workspace recovery under R4. A model fallback
  never receives the failed workspace draft.
- R6. Make attribution explicit before mutation.  Every uncertain result must
  be classified among project-execution Agent view, effective runtime
  Prompt/input, Runtime Skill, deterministic code/provider/profile adapter,
  or feedback/observability.  A weak scene or ambiguous terminal is itself a
  feedback/observability defect, not permission to modify the Prompt or Skill.
- R7. Preserve Agent-native flexibility.  Do not introduce deterministic
  business schemas, ID rules, or output contracts merely because an Agent
  generated text.  Use deterministic code only for framework-owned identity,
  lifecycle, safety, budget, state, and release facts; let Prompt/Skill/
  feedback routes handle meaning where evidence selects them.
- R8. Build an invocation-mechanism evidence matrix from real isolated
  boundaries, not broad pytest alone.  It must deduplicate already-terminal
  coordinates, show prerequisite closure, route/profile/transport, physical
  state, safe result, and whether a test is a real semantic node or a
  constructed true InvocationBackend boundary.
- R9. Before refactoring, inventory all callers of Worker lifecycle, session
  continuation, cancellation, terminal diagnostics, and retry authority.
  Each implemented repair must address all same-mechanism occurrences or
  document why an exception is intentional.
- R10. Keep the current pipeline's immutable input closure, deny-by-default
  capabilities, budget ledgers, validator strictness, diagnostic-only marking,
  and release authority intact.  No mock code generation, fixture success
  path, broad retry loop, or hard-coded environment/task branch is allowed.

## Acceptance Criteria

- [ ] AC1: A design documents the Control Plane boundaries, state machine,
  policy ownership, data flow, and migration from current adapters/scheduler/
  diagnostic commands, including why each part is required by a confirmed bad
  case.
- [ ] AC2: A complete inventory maps every existing real invocation mechanism
  and caller to the new ownership boundary; already-proven nodes are marked as
  such and uncallable downstream nodes state their unmet parent closure.
- [ ] AC3: A constructed real Codex liveness regression proves that a Worker
  with no post-start safe progress and no usable transport is terminalized or
  reconciled within its declared lifecycle policy, and that both WorkControl
  and audit views become non-running with a stable safe diagnostic.
- [ ] AC4: A regression proves graceful parent cancellation and worker/app-
  server termination converge exactly once to durable terminal state without
  leaking private runtime material or creating an unauthorized retry.
- [ ] AC5: A regression proves closed temporary Provider failure takes the
  policy-authorized same-definition fresh-session retry path and, after the
  same classified transient failure recurs, creates one explicit next-compatible
  model definition for the affected node only. It must preserve exact
  committed parent closure and prove no upstream node reruns. A CandidateBuild
  interruption-after-file-write must additionally prove that the first retry
  opens a new Agent thread over an untrusted private draft, validates/commits
  only a complete replacement, and never exposes the draft to fallback or
  Integration. Invalid structured output, semantic validation failure, output
  ceiling, and ambiguous feedback still select their distinct routes rather
  than sharing a blind retry.
- [ ] AC6: Real isolated execution proves every newly changed invocation
  mechanism at its narrowest truthful boundary before any E2E chain is resumed.
  Pytest, typing, lint, format, and actionable scenes supplement—not replace—
  those proofs.
- [ ] AC7: Project-execution Agent view remains compact and on-demand; runtime
  Agent permissions, Prompt/input, and Runtime Skills are changed only when
  the evidence matrix explicitly selects them.
- [ ] AC8: No raw Provider data, credentials, endpoint, private session state,
  or runtime artifact is committed.

## Out of scope

- Rewriting the WorldSpec, task semantics, candidate implementation, or
  verifier content merely to make an invocation complete.
- Re-running already-terminal frozen coordinates.
- Restarting already committed upstream Work nodes when retrying or falling
  back an affected downstream node.
- Treating a generic audit success as E2E completion or release evidence.
- Starting Integration, release, or registry nodes before CandidateBuild has a
  committed candidate closure.

## Technical direction

Use a single centralized policy table with closed failure facts and explicit
evidence gates, not a new all-powerful deterministic contract.  The next design
pass must validate this against current adapter/scheduler code and the bad-case
matrix before implementation starts.

## Resolved routing and reuse policy

For a classified temporary capacity/transport failure, the controller performs
one recorded backoff retry of the same model with a fresh node-local session.
If the CandidateBuild leaf proved a real, safe private draft exists, that fresh
session may inspect/test the draft and complete it in place; it does not resume
the old Provider thread or adopt any uncommitted bytes. The normal Candidate
validator and immutable commit remain the only acceptance boundary.
If the same transient route failure recurs, it automatically creates and
dispatches the next compatible model's visible diagnostic definition in the
configured preference order.  The fallback retains the current node's exact
immutable parent closure and never restarts committed upstream nodes.  A
cross-node conversation/session is not reused: committed typed Artifacts carry
the required context. Fallback never inherits a private Candidate draft; only
the same-model retry may use the narrowly authorized workspace-recovery path,
and only a same-node, policy-authorized output-ceiling continuation retains the
private Provider session.

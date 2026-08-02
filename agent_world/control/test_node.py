"""Isolated, one-node diagnostic execution for a frozen WorkGraph scope.

The harness intentionally does not offer a replay shortcut.  It copies a
captured state root, verifies the target's committed ancestor closure against
the exact persisted WorkGraph manifest, removes *only* the copied target head
from scheduling, and lets :meth:`WorkScheduler.dispatch_one` invoke the real
leaf once.  The copied run has a fresh, target-sized budget and every new
control artifact is explicitly diagnostic-only and non-releasable.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import shutil
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from agent_world.artifact_store import ArtifactWriter
from agent_world.config import FoundryConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    EnvironmentCandidate,
    EnvironmentDesign,
    GenerationContext,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.designer.models import CurriculumPlanSourceDraft
from agent_world.diagnostic_state import is_marked_test_node_diagnostic_state_root
from agent_world.invocation.control_store import InvocationControlStore, InvocationControlStoreError
from agent_world.judge.models import VerifierBatchPlan
from agent_world.judge_budgeting import integration_budget_requirements

from .budget import LeaseBudgetLedger
from .continuation_store import NodeContinuationStore
from .leaf_executor import LocalTerminalDiagnostic, SchedulerLeafExecutor
from .work import (
    FeedbackEvaluation,
    OperationBudget,
    OperationRun,
    ParentRepairRoute,
    ProposalExecution,
    RepairAction,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkCoordinate,
    WorkDefinition,
)
from .work_epoch import WorkGraphEpochRuntime
from .work_graph import (
    CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS,
    GenerationWorkGraph,
    WorkGraphEpoch,
    WorkGraphError,
    WorkGraphManifest,
    WorkGraphMilestone,
    WorkGraphNodeBinding,
    WorkGroupDefinition,
    compile_design_work_graph,
    compile_world_work_graph,
    complete_generation_work_graph,
    current_runtime_revisions_for_definition,
    curriculum_plan_work_definition,
    derive_final_design_definitions,
    derive_task_requirement_design_definitions,
    verifier_plan_work_definition,
)
from .work_repair import WorkRepairDenied, WorkRepairLedger
from .work_runtime import WorkControlRuntime, WorkRuntimeError
from .work_scheduler import WorkDispatchResult, WorkExecutor, WorkScheduler
from .work_store import (
    WorkControlHead,
    WorkControlStore,
    WorkControlStoreError,
    WorkHeadConflictError,
    WorkResumeError,
)

if TYPE_CHECKING:
    from agent_world.app import FoundryApplication
    from agent_world.observability import DebugTranscriptWriter


# Only ``artifacts/`` and ``work-control/`` hold the frozen WorkGraph input
# closure. The other top-level stores are previous process workspaces,
# observability projections, consumer state, or Registry state; none may
# become an input to an isolated diagnostic dispatch. In particular, old agent
# runtime homes can hold transient tool symlinks or private auth material.
_NON_DURABLE_STATE_DIRECTORIES = frozenset(
    {
        "campaigns",
        "direct-jobs",
        "expansion-source-runs",
        "invocation-control",
        "observability",
        "registry",
        "runs",
        "telemetry",
    }
)

_TERMINAL_WORK_HEAD_STATUSES = frozenset({"committed", "failed", "needs_human", "interrupted"})


def _diagnostic_work_runtime(
    *,
    app: FoundryApplication,
    heads: WorkControlStore,
    budget: Budget,
    trace_id: str | None = None,
    run_id: str | None = None,
    repair_scope_id: str | None = None,
    continuation_workspace_root: Path | None = None,
    diagnostic_workspace_recovery_capture_root: Path | None = None,
) -> WorkControlRuntime:
    """Build every diagnostic runtime with the production recovery controls.

    A marked test-node clone changes release authority and state ownership, not
    configured model routing, liveness policy, or retry pacing.  Keeping this
    composition in one helper prevents a diagnostic command from silently
    proving a different recovery policy than ``DirectWorkRunner``.
    """

    observed = trace_id is not None
    private_workspace_roots = tuple(
        dict.fromkeys(
            root
            for root in (
                continuation_workspace_root,
                diagnostic_workspace_recovery_capture_root,
            )
            if root is not None
        )
    )
    for private_workspace_root in private_workspace_roots:
        try:
            private_workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_workspace_root.chmod(0o700)
        except OSError as exc:
            raise TestNodeError(
                "test_node_private_workspace_root_unavailable",
                "diagnostic private workspace root is unavailable",
            ) from exc
    return WorkControlRuntime(
        artifacts=app.controller.artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(budget),
        repairs=(
            WorkRepairLedger.restore(
                app.controller.artifacts,
                scope_id=repair_scope_id,
                diagnostic_only=True,
                active_repair_action_refs=tuple(
                    head.repair_action_ref
                    for head in heads.read_scope_heads(repair_scope_id)
                    if head.status == "repair_authorized" and head.repair_action_ref is not None
                ),
            )
            if repair_scope_id is not None
            else None
        ),
        telemetry=app.telemetry if observed else None,
        projector=app.controller.scene_projector if observed else None,
        trace_id=trace_id,
        run_id=run_id,
        diagnostic_only=True,
        repair_scope_id=repair_scope_id,
        continuations=(
            NodeContinuationStore(heads.root / "continuations")
            if continuation_workspace_root is not None
            else None
        ),
        continuation_workspace_root=continuation_workspace_root,
        model_routes=app.config.agent.model_routes,
        route_liveness_checker=app.controller.route_liveness_checker,
        require_route_liveness_gate=app.controller.route_liveness_checker is not None,
        infrastructure_retry_backoff_seconds=app.config.agent.infrastructure_retry_backoff_seconds,
    )


def _marked_diagnostic_runs_root(workspace: Path) -> Path:
    """Resolve the one marked diagnostic ``runs/`` root owning ``workspace``.

    A descendant clone deliberately excludes private Agent workspaces.  A
    repair continuation may nevertheless point back to one exact prior
    diagnostic workspace.  Recover that narrow authority from the
    commitment-bound path; never broaden it to all of ``.agent-world-live``.
    """

    requested = workspace.expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise TestNodeError(
            "test_descendant_continuation_workspace_missing",
            "the bound repair continuation workspace is no longer available",
        ) from exc
    if requested.is_symlink() or not resolved.is_dir():
        raise TestNodeError(
            "test_descendant_continuation_workspace_unsafe",
            "the bound repair continuation workspace is not one real directory",
        )
    candidates = tuple(
        parent
        for parent in resolved.parents
        if parent.name == "runs" and is_marked_test_node_diagnostic_state_root(parent.parent)
    )
    if len(candidates) != 1:
        raise TestNodeError(
            "test_descendant_continuation_workspace_authority_invalid",
            (
                "the bound repair continuation workspace does not belong to one "
                "exact marked diagnostic runs root"
            ),
        )
    runs_root = candidates[0]
    if runs_root.is_symlink() or not runs_root.is_dir():
        raise TestNodeError(
            "test_descendant_continuation_workspace_authority_invalid",
            "the bound diagnostic runs root is not one real directory",
        )
    return runs_root


def _authorized_semantic_continuation_workspace_root(
    *,
    app: FoundryApplication,
    definition: WorkDefinition,
    diagnostic_root: Path,
) -> Path:
    """Recover exact private workspace authority for an authorized repair.

    A committed snapshot repair intentionally starts a fresh Agent session in
    the new diagnostic root.  The successful seed attempt may still carry an
    Agent provenance commitment, but that is not authority to revive its old
    Provider thread or private workspace.  Only a repair action without a
    committed snapshot seed can require the continuation store below.
    """

    head = app.controller.work_control.read_head(definition.coordinate)
    if head is None or head.status != "repair_authorized" or head.repair_action_ref is None:
        raise TestNodeError(
            "test_descendant_semantic_repair_continuation_head_invalid",
            "semantic repair execution requires one exact authorized head",
        )
    action = app.controller.artifacts.get_json(head.repair_action_ref, RepairAction)
    if action.repair_seed_attempt_ref is not None:
        return diagnostic_root / "runs"

    attempt = app.controller.artifacts.get_json(head.attempt_ref, WorkAttempt)
    if attempt.continuation_commitment is None:
        # Direct structured repair carries a private parsed seed rather than a
        # Provider session/workspace.  Its fresh diagnostic run owns the only
        # workspace authority it may need.
        return diagnostic_root / "runs"
    store = NodeContinuationStore(app.controller.work_control.root / "continuations")
    record = store.inspect_commitment(attempt.continuation_commitment)
    if record is None:
        raise TestNodeError(
            "test_descendant_semantic_repair_continuation_missing",
            "the authorized repair continuation record is unavailable",
        )
    runs_root = _marked_diagnostic_runs_root(Path(record.workspace))
    # Metadata inspection above selects a candidate root only.  Re-run the
    # store's full path containment check before granting it to the runtime.
    if (
        store.load_commitment(
            attempt.continuation_commitment,
            workspace_root=runs_root,
        )
        != record
    ):
        raise TestNodeError(
            "test_descendant_semantic_repair_continuation_mismatch",
            "the authorized repair continuation changed during validation",
        )
    return runs_root


def _diagnostic_terminal_profile_config(
    *,
    app: FoundryApplication,
    retry_head: WorkControlHead,
    config: FoundryConfig,
) -> FoundryConfig:
    """Select the model proved by one failed physical Agent attempt.

    A same-model infrastructure retry is not a new profile experiment.  Its
    model identity comes from the terminal ProposalExecution, even when an
    older diagnostic harness accidentally retained a conflicting profile
    overlay in the frozen manifest.  This helper changes no endpoint,
    credential, Prompt, Skill, or semantic definition.
    """

    attempt = app.controller.artifacts.get_json(retry_head.attempt_ref, WorkAttempt)
    executions = TestNodeRunner._proposal_executions(app.controller.artifacts, attempt)
    terminal_models = tuple(
        dict.fromkeys(execution.model for execution in executions if execution.model is not None)
    )
    if not terminal_models:
        # Preflight and post-dispatch framework interruptions can truthfully
        # lack Provider/model provenance.  With no physical route fact, retain
        # the frozen configured profile rather than guessing one.
        return config
    if len(terminal_models) != 1:
        raise TestNodeError(
            "test_descendant_infrastructure_retry_model_ambiguous",
            (
                "the failed WorkAttempt records multiple Agent model identities; "
                "one same-model retry cannot choose between them"
            ),
        )
    terminal_model = terminal_models[0]
    if terminal_model == config.agent.model:
        return config
    try:
        terminal_index = config.agent.model_routes.index(terminal_model)
    except ValueError:
        # A historic diagnostic clone can retain a proved model profile after
        # the caller's current configuration has changed.  Preserve the exact
        # same-route retry in that narrow case, but do not invent any later
        # fallback route that the current configuration cannot prove.
        later_routes: tuple[str, ...] = ()
    else:
        later_routes = config.agent.model_routes[terminal_index + 1 :]
    return config.model_copy(
        update={
            "agent": config.agent.model_copy(
                update={
                    "model": terminal_model,
                    # The failed route becomes the primary profile for the
                    # immediate same-route retry, while only its already
                    # configured successors remain eligible for a later,
                    # explicitly recorded fallback.  Dropping this tail
                    # turned a second classified transient into a false
                    # terminal even though the frozen route policy named a
                    # compatible model.
                    "fallback_models": later_routes,
                }
            )
        }
    )


def _mirror_settled_retry_control_record(
    *,
    source_state_root: Path,
    app: FoundryApplication,
    retry_head: WorkControlHead,
) -> None:
    """Mirror only the prior settled invocation fact needed by one retry gate.

    Full ``invocation-control`` directories stay outside a diagnostic clone:
    they are execution state, not frozen WorkGraph input.  The one exception
    is a settled record tied by the prior ``ProposalExecution`` to the exact
    retry target.  It is already redacted by ``InvocationControlStore`` and
    allows the clone's normal liveness checker to verify the same route without
    reading or mutating the source state.
    """

    attempt = app.controller.artifacts.get_json(retry_head.attempt_ref, WorkAttempt)
    proposals = TestNodeRunner._proposal_executions(app.controller.artifacts, attempt)
    invocation_id = proposals[-1].invocation_id if proposals else None
    if invocation_id is None:
        # Constructed deterministic boundaries have no Provider provenance.
        # Their explicit test-only retry path remains observable without
        # inventing an Invocation Control record.
        return
    source_control_root = source_state_root / "invocation-control"
    if not source_control_root.exists():
        return
    try:
        source_store = InvocationControlStore(source_control_root)
        record = source_store.read_settled_snapshot(invocation_id)
        if record is not None:
            app.invocation_control.import_settled_snapshot(record)
    except InvocationControlStoreError as exc:
        raise TestNodeError(
            "test_descendant_route_liveness_snapshot_invalid",
            "the prior diagnostic invocation-control record cannot be safely mirrored",
        ) from exc


def _settle_cancelled_diagnostic_dispatch(
    *,
    runtime: WorkControlRuntime,
    definition: WorkDefinition,
) -> WorkControlHead | None:
    """Persist one externally cancelled diagnostic dispatch before returning.

    A signal can arrive after the Scheduler has crossed the durable dispatch
    fence but before the production leaf has translated cancellation into a
    terminal WorkAttempt.  The diagnostic command owns no retry authority, so
    it must turn that exact active operation into bounded failure evidence
    rather than re-raise and strand the copied head in ``running`` state.
    """

    with runtime.heads.exclusive(definition.coordinate) as lock:
        head = runtime.heads.read_head(definition.coordinate)
        if head is None or head.status in _TERMINAL_WORK_HEAD_STATUSES:
            return head
        if head.status != "running" or head.active_operation_ref is None:
            return head
        return runtime.reconcile_abandoned_operation(
            lock,
            definition=definition,
            interrupted_dispatch_code="process_interrupted_cancelled",
            allow_infrastructure_retry=False,
        )


class TestNodeError(RuntimeError):
    """One safe, machine-readable reason a node cannot be isolated."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


type DiagnosticTerminalFeedbackStatus = Literal[
    "not_requested",
    "no_excerpt",
    "rejected",
    "unavailable",
    "written",
]


@dataclass(slots=True)
class _DiagnosticTerminalFeedbackCollector:
    """Keep one redacted SDK terminal clue outside workflow authority.

    A test-node execution may explicitly opt in to a local debug sidecar after
    the ordinary safe scene has proven that its terminal feedback is too weak.
    This collector is intentionally process-local until its final best-effort
    write; it is never attached to a WorkAttempt, Artifact, telemetry event,
    Scene, or repair decision.
    """

    scope_id: str
    writer: DebugTranscriptWriter | None
    feedback: LocalTerminalDiagnostic | None = None

    def capture(self, feedback: LocalTerminalDiagnostic) -> None:
        if self.feedback is None:
            self.feedback = feedback

    def finalize(self) -> tuple[DiagnosticTerminalFeedbackStatus, str | None]:
        if self.writer is None:
            return "unavailable", None
        feedback = self.feedback
        if feedback is None:
            return "no_excerpt", None
        payload = json.dumps(
            {
                "diagnostic_only": True,
                "failure_code": feedback.code,
                "kind": "codex_terminal_feedback",
                "terminal_details": feedback.terminal_details,
                "terminal_error_excerpt": feedback.excerpt,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        outcome = self.writer.write(scope_id=self.scope_id, transcript=payload)
        return (
            cast(DiagnosticTerminalFeedbackStatus, outcome.status),
            str(outcome.path) if outcome.path is not None else None,
        )


def _diagnostic_terminal_feedback_collector(
    *,
    config: FoundryConfig,
    scope_id: str,
    requested: bool,
) -> _DiagnosticTerminalFeedbackCollector | None:
    """Open an explicit local-only sidecar without making it a test gate."""

    if not requested:
        return None
    try:
        # Keep the composition-root import lazy just like the real test-node
        # executor. The writer's enabled=True is an explicit CLI/API request,
        # not an ambient production default.
        from agent_world.app import open_debug_transcripts

        writer = open_debug_transcripts(config, enabled=True)
    except Exception:
        writer = None
    return _DiagnosticTerminalFeedbackCollector(scope_id=scope_id, writer=writer)


def _nonterminal_diagnostic_dispatch_error(
    *,
    app: FoundryApplication,
    definition: WorkDefinition,
    scope_id: str,
    run_id: str,
    error_code: str,
    exc: Exception,
) -> TestNodeError | None:
    """Refresh a fresh scene when a diagnostic Scheduler call escapes early.

    Observability is a rebuildable cache and never an input to a diagnostic
    copy. If a framework exception leaves a head nonterminal, materialize the
    current durable state before returning one safe harness error. The caller
    still preserves the original exception as its cause for local debugging.
    """

    scene_rebuilt = True
    try:
        app.controller.scene_projector.rebuild(scope_id, run_id=run_id)
    except Exception:
        scene_rebuilt = False
    head = app.controller.work_control.read_head(definition.coordinate)
    if head is not None and head.status in _TERMINAL_WORK_HEAD_STATUSES:
        return None
    state = head.status if head is not None else "missing"
    return TestNodeError(
        error_code,
        (
            f"real Scheduler raised {type(exc).__name__} and left the diagnostic "
            f"Work head {state}; "
            + (
                "the safe scene was rebuilt from durable state"
                if scene_rebuilt
                else "safe scene reconstruction also failed; inspect the durable Work head"
            )
        ),
    )


async def _dispatch_diagnostic_target(
    *,
    scheduler: WorkScheduler,
    coordinate: WorkCoordinate,
    executor: WorkExecutor,
    runtime: WorkControlRuntime,
    definition: WorkDefinition,
    app: FoundryApplication,
    scope_id: str,
    run_id: str,
    span: Any,
    dispatch_error_code: str,
    interrupt_code: str,
    cancel_code: str,
    nonterminal_code: str,
    settled_statuses: frozenset[str],
) -> WorkDispatchResult | None:
    """Dispatch one diagnostic target through the real scheduler, classifying errors.

    The three dispatching runners (TestNode, Descendant, Successor) repeat the
    same dispatch + KeyboardInterrupt/CancelledError/Exception classification
    (using the module-level ``_settle_cancelled_diagnostic_dispatch`` and
    ``_nonterminal_diagnostic_dispatch_error``).  Only the error-code strings,
    the settled-status set (Descendant adds ``repair_authorized``) and the
    ``span.finish`` calls differ.  This helper keeps that one dispatch path in
    one place; the caller still owns executor construction and post-dispatch
    span finish.
    """

    try:
        return await scheduler.dispatch_one(
            coordinate,
            executors={definition.work_id: executor},
        )
    except KeyboardInterrupt:
        interrupted_head = _settle_cancelled_diagnostic_dispatch(
            runtime=runtime,
            definition=definition,
        )
        if interrupted_head is None or interrupted_head.status not in settled_statuses:
            span.finish(status="cancelled", error_code=interrupt_code)
        else:
            span.finish(
                status="cancelled",
                output_refs=tuple(
                    ref
                    for ref in (interrupted_head.commit_ref, interrupted_head.evaluation_ref)
                    if ref is not None
                ),
            )
        app.telemetry.flush()
        raise
    except asyncio.CancelledError:
        interrupted_head = _settle_cancelled_diagnostic_dispatch(
            runtime=runtime,
            definition=definition,
        )
        if interrupted_head is None or interrupted_head.status not in settled_statuses:
            span.finish(status="cancelled", error_code=cancel_code)
            app.telemetry.flush()
            raise
        span.finish(
            status="cancelled",
            output_refs=tuple(
                ref
                for ref in (interrupted_head.commit_ref, interrupted_head.evaluation_ref)
                if ref is not None
            ),
        )
        app.telemetry.flush()
        return None
    except Exception as exc:
        span.finish(status="error", error_code=dispatch_error_code)
        app.telemetry.flush()
        nonterminal = _nonterminal_diagnostic_dispatch_error(
            app=app,
            definition=definition,
            scope_id=scope_id,
            run_id=run_id,
            error_code=nonterminal_code,
            exc=exc,
        )
        if nonterminal is not None:
            raise nonterminal from exc
        raise


class ProposalExecutionEnvelope(V2Contract):
    """Safe, explicit distinction between a physical turn and its session.

    A long-running Agent node may have a Provider-owned physical output or
    wall ceiling while retaining a larger framework-owned logical session.
    The fields are copied only from the frozen WorkDefinition; this is a
    project-execution view aid, never an additional runtime authority.
    """

    physical_turn_llm_tokens: int
    physical_turn_wall_seconds: float
    logical_session_token_limit: int | None = None
    logical_session_wall_seconds: float | None = None
    maximum_session_continuations: int = 0


class TestNodeResult(V2Contract):
    """Safe CLI projection of one genuinely rerun diagnostic node."""

    source_scope_id: str
    target_coordinate: WorkCoordinate
    source_state_root: str
    diagnostic_state_root: str
    source_head_revision: int
    source_attempt_ref: ArtifactRef
    archived_source_head_path: str
    source_proposal_llm_tokens: int
    proposal_llm_tokens: int
    source_proposal_wall_seconds: float
    proposal_wall_seconds: float
    # The historical proposal fields above are one physical Provider turn.
    # Keep them for compatibility, but make the logical session visible so a
    # Code Agent cannot mistake a 125K physical ceiling for a 5M Build budget.
    source_execution_envelope: ProposalExecutionEnvelope
    execution_envelope: ProposalExecutionEnvelope
    proposal_budget_override_ref: ArtifactRef | None = None
    runtime_implementation_override_ref: ArtifactRef | None = None
    runtime_profile_override_ref: ArtifactRef | None = None
    target_attempt_ref: ArtifactRef
    target_evaluation_ref: ArtifactRef
    target_commit_ref: ArtifactRef | None = None
    status: Literal["committed", "failed", "needs_human", "interrupted"]
    validation_report: ValidationReport
    proposal_executions: tuple[ProposalExecution, ...] = ()
    actual_usage: BudgetUsage
    unknown_usage: BudgetUsage
    conservative_usage: BudgetUsage
    reserved_budget: Budget
    scene: dict[str, object]
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticSuccessorNodeResult(V2Contract):
    """One fresh semantic node derived from a diagnostic Architecture commit.

    This is not a release result and is deliberately distinct from
    :class:`TestNodeResult`: the physical target did not exist in the captured
    pre-Architecture graph, so it cannot be replayed or archived as a former
    target head.  Its predecessor Architecture commit was nevertheless
    genuinely executed by ``test-node`` in the marked source copy, then used
    byte-for-byte as an input in a fresh diagnostic child copy.
    """

    source_scope_id: str
    target_coordinate: WorkCoordinate
    source_diagnostic_state_root: str
    diagnostic_state_root: str
    bootstrap_epoch_ref: ArtifactRef
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    architecture_attempt_ref: ArtifactRef
    architecture_commit_ref: ArtifactRef
    target_attempt_ref: ArtifactRef
    target_evaluation_ref: ArtifactRef
    target_commit_ref: ArtifactRef | None = None
    status: Literal["committed", "failed", "needs_human", "interrupted"]
    validation_report: ValidationReport
    proposal_executions: tuple[ProposalExecution, ...] = ()
    actual_usage: BudgetUsage
    unknown_usage: BudgetUsage
    conservative_usage: BudgetUsage
    reserved_budget: Budget
    scene: dict[str, object]
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


@dataclass(frozen=True, slots=True)
class TestNodeExecution:
    """All immutable context available to one test-node executor resolver."""

    app: FoundryApplication
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context: GenerationContext
    context_ref: ArtifactRef
    runtime: WorkControlRuntime
    workspace_root: Path
    run_id: str
    trace_id: str
    terminal_feedback: _DiagnosticTerminalFeedbackCollector | None = None


@dataclass(frozen=True, slots=True)
class _FrozenTarget:
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context: GenerationContext
    context_ref: ArtifactRef
    source_head: WorkControlHead


TestNodeExecutorFactory = Callable[[TestNodeExecution], WorkExecutor]


def _resolve_marked_diagnostic_root(
    diagnostic_state_root: Path,
    *,
    prefix: str,
) -> Path:
    """Resolve one marked diagnostic state root, with per-runner error codes.

    Seven runners repeat the same marked-root resolution; only the error-code
    prefix differs (``test_descendant`` / ``test_world_plan`` / ...).  Keeping
    the prefix parameterized preserves each runner's CLI audit granularity.
    """

    candidate = diagnostic_state_root.expanduser()
    if not is_marked_test_node_diagnostic_state_root(candidate):
        raise TestNodeError(
            f"{prefix}_state_not_marked",
            f"diagnostic {prefix.replace('test_', '').replace('_', ' ')} requires one marked "
            ".agent-world-live/test-node-* state root",
        )
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:  # pragma: no cover - marker checks the same path first
        raise TestNodeError(
            f"{prefix}_state_missing",
            f"diagnostic {prefix.replace('test_', '').replace('_', ' ')} state root is unavailable",
        ) from exc


def _prepare_diagnostic_clone(
    *,
    source_root: Path,
    diagnostic_parent: Path | None = None,
    marker_error_code: str,
    marker_message: str,
) -> Path:
    """Create one marked, isolated diagnostic copy of a captured state root.

    Shared by the six runners that copy+mark (TestNode, Descendant, WorldPlan,
    TaskRequirement, Final, Successor).  The source archive is copied
    byte-for-byte minus non-durable directories, then marked so diagnostic head
    archiving and non-releasable commits are legal.  Scope separation stays at
    the read boundary; this function never filters by scope (preserving the
    byte-for-byte completeness the ancestor-closure assertions depend on).

    ``marker_error_code`` / ``marker_message`` are the per-runner CLI error
    codes (test_node_* / test_descendant_* / test_world_plan_* / ...) so the
    unified helper preserves each runner's audit granularity.

    ``diagnostic_parent`` may be None (most CLI constructions omit it); the
    helper then mirrors ``TestNodeRunner._diagnostic_parent`` by preferring a
    ``.agent-world-live`` ancestor of the source root, falling back to the
    current working directory's ``.agent-world-live``.
    """

    parent = diagnostic_parent
    if parent is None:
        parent = next(
            (
                candidate
                for candidate in source_root.parents
                if candidate.name == ".agent-world-live"
            ),
            Path.cwd() / ".agent-world-live",
        )
    if parent.exists() and parent.is_symlink():
        raise TestNodeError(
            "test_node_diagnostic_parent_symlink",
            "diagnostic parent cannot be a link",
        )
    try:
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent.chmod(0o700)
    except OSError as exc:
        raise TestNodeError(
            "test_node_diagnostic_parent_unavailable",
            "diagnostic parent is unavailable",
        ) from exc
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    diagnostic_root = parent / f"test-node-{timestamp}-{uuid.uuid4().hex[:12]}"

    TestNodeRunner._assert_no_symlinks(source_root)

    def _ignore(directory: str, names: list[str]) -> set[str]:
        relative = Path(directory).resolve().relative_to(source_root)
        ignored: set[str] = set()
        if relative == Path("."):
            ignored.update(
                name for name in names if name in _NON_DURABLE_STATE_DIRECTORIES
            )
        if relative == Path("work-control"):
            ignored.update(name for name in names if name in {"scope-budgets", "locks", "tmp"})
        return ignored

    try:
        shutil.copytree(
            source_root,
            diagnostic_root,
            copy_function=shutil.copy2,
            ignore=_ignore,
        )
        diagnostic_root.chmod(0o700)
    except OSError as exc:
        raise TestNodeError(
            "test_node_state_copy_failed",
            "could not create an isolated diagnostic state copy",
        ) from exc

    try:
        WorkControlStore(diagnostic_root / "work-control").mark_test_node_diagnostic_clone()
    except WorkControlStoreError as exc:
        raise TestNodeError(
            marker_error_code,
            marker_message,
        ) from exc
    return diagnostic_root


class TestNodeRunner:
    """Copy one scope and dispatch exactly one target node in that copy."""

    def __init__(
        self,
        *,
        config: FoundryConfig,
        source_state_root: Path | None = None,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.source_state_root = source_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory or self._production_executor

    async def run(
        self,
        *,
        scope_id: str,
        target_coordinate: str,
        proposal_llm_tokens: int | None = None,
        proposal_wall_seconds: float | None = None,
        refresh_current_implementation: bool = False,
        diagnostic_model: str | None = None,
        diagnostic_source_model: str | None = None,
    ) -> TestNodeResult:
        profile_change = _diagnostic_runtime_profile_change(
            self.config,
            diagnostic_model=diagnostic_model,
            diagnostic_source_model=diagnostic_source_model,
        )
        if refresh_current_implementation and (
            proposal_llm_tokens is not None or proposal_wall_seconds is not None
        ):
            raise TestNodeError(
                "test_node_runtime_implementation_envelope_conflict",
                (
                    "refreshing the current runtime implementation and changing a proposal "
                    "budget are separate diagnostic experiments"
                ),
            )
        if profile_change.requested and (
            proposal_llm_tokens is not None
            or proposal_wall_seconds is not None
            or refresh_current_implementation
        ):
            raise TestNodeError(
                "test_node_runtime_profile_overlay_conflict",
                (
                    "a diagnostic runtime-profile change, proposal-envelope change, and "
                    "current implementation refresh are separate causal experiments"
                ),
            )
        diagnostic_config = profile_change.config
        source_root = self._resolve_source_root()
        diagnostic_root = _prepare_diagnostic_clone(
            source_root=source_root,
            diagnostic_parent=self.diagnostic_parent or self._diagnostic_parent(source_root),
            marker_error_code="test_node_diagnostic_marker_failed",
            marker_message="isolated diagnostic state could not be marked",
        )

        # Import here to keep the production composition root free of an
        # import cycle with ``agent_world.control``.
        from agent_world.app import build_application

        app = build_application(
            diagnostic_config.model_copy(update={"state_root": diagnostic_root})
        )
        heads = app.controller.work_control
        target = self._resolve_coordinate(
            heads.read_scope_heads(scope_id),
            target_coordinate,
        )
        frozen = self._load_frozen_target(
            app=app,
            scope_id=scope_id,
            target=target,
        )
        inherited_profile_config, inherited_profile_overrides = (
            _inherited_diagnostic_runtime_profile_config(
                app=app,
                manifest_ref=frozen.manifest_ref,
                definition=frozen.definition,
                config=diagnostic_config,
            )
        )
        if inherited_profile_overrides:
            if profile_change.requested:
                raise TestNodeError(
                    "test_node_runtime_profile_override_conflict",
                    (
                        "the selected frozen target already has a diagnostic model "
                        "profile; preserve it for a current-runtime refresh or start "
                        "one separate fresh profile experiment"
                    ),
                )
            if inherited_profile_config != diagnostic_config:
                diagnostic_config = inherited_profile_config
                # A test-node may refresh a Prompt, Runtime Skill, adapter, or
                # validator below an earlier model-only experiment.  Rebuild
                # before any Scheduler/runtime work so the refresh executes
                # with that frozen model instead of silently reverting to the
                # caller's current default.
                app = build_application(
                    diagnostic_config.model_copy(update={"state_root": diagnostic_root})
                )
                heads = app.controller.work_control
                target = self._resolve_coordinate(
                    heads.read_scope_heads(scope_id),
                    target_coordinate,
                )
                frozen = self._load_frozen_target(
                    app=app,
                    scope_id=scope_id,
                    target=target,
                )

        self._assert_complete_ancestor_closure(
            app=app,
            graph=frozen.graph,
            target=target,
        )
        scheduler = WorkScheduler(
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
        )
        try:
            resolved = scheduler.resolve_inputs(target)
        except WorkResumeError as exc:
            raise TestNodeError(
                "missing_ancestor_closure",
                "the copied scope does not retain one committed ancestor closure",
            ) from exc
        source_attempt = app.artifacts.get_json(frozen.source_head.attempt_ref, WorkAttempt)
        if resolved.all_input_refs != source_attempt.input_refs:
            raise TestNodeError(
                "test_node_input_closure_mismatch",
                "the persisted target input closure does not match its frozen graph",
            )
        source_proposal_llm_tokens = frozen.definition.proposal_policy.budget.llm_tokens
        source_proposal_wall_seconds = frozen.definition.proposal_policy.budget.wall_seconds
        source_execution_envelope = self._proposal_execution_envelope(frozen.definition)
        proposal_budget_override_ref: ArtifactRef | None = None
        runtime_implementation_override_ref: ArtifactRef | None = None
        runtime_profile_override_ref: ArtifactRef | None = None
        if proposal_llm_tokens is not None or proposal_wall_seconds is not None:
            overlay = _apply_diagnostic_proposal_envelope_overlay(
                app=app,
                config=self.config,
                source=_ProposalEnvelopeOverlaySource(
                    graph=frozen.graph,
                    manifest=frozen.manifest,
                    manifest_ref=frozen.manifest_ref,
                    definition=frozen.definition,
                    context_ref=frozen.context_ref,
                ),
                proposal_llm_tokens=proposal_llm_tokens,
                proposal_wall_seconds=proposal_wall_seconds,
            )
            frozen = replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            )
            proposal_budget_override_ref = overlay.override_ref
        elif refresh_current_implementation:
            overlay = _apply_diagnostic_runtime_implementation_overlay(
                app=app,
                source=_ProposalEnvelopeOverlaySource(
                    graph=frozen.graph,
                    manifest=frozen.manifest,
                    manifest_ref=frozen.manifest_ref,
                    definition=frozen.definition,
                    context_ref=frozen.context_ref,
                ),
            )
            frozen = replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            )
            runtime_implementation_override_ref = overlay.override_ref
        elif profile_change.requested:
            overlay = _apply_diagnostic_runtime_profile_overlay(
                app=app,
                source=_ProposalEnvelopeOverlaySource(
                    graph=frozen.graph,
                    manifest=frozen.manifest,
                    manifest_ref=frozen.manifest_ref,
                    definition=frozen.definition,
                    context_ref=frozen.context_ref,
                ),
                source_model=profile_change.source_model,
                model=profile_change.model,
            )
            frozen = replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            )
            runtime_profile_override_ref = overlay.override_ref

        # The only head mutation is an audit-preserving archive of the target
        # head inside the copied state root.  Ancestor heads remain readable
        # immutable inputs and none of the source state is opened for writing.
        with heads.exclusive(target) as lock:
            archived_head_path = heads.archive_terminal_head_for_diagnostic(
                lock,
                expected_head=frozen.source_head,
            )

        budget = self._single_attempt_budget(frozen.definition)
        run_token = uuid.uuid4().hex
        run_id = f"test-node:{run_token}"
        trace_id = run_id
        root_span = app.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="test_node.dispatch",
            run_id=run_id,
            node=frozen.definition.work_id,
            input_refs=resolved.all_input_refs,
            attributes={"diagnostic_only": True, "releasable": False},
        )
        app.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root_span.span_id,
        )
        runtime = _diagnostic_work_runtime(
            app=app,
            heads=heads,
            budget=budget,
            trace_id=trace_id,
            run_id=run_id,
            continuation_workspace_root=diagnostic_root / "runs",
        )
        workspace_root = diagnostic_root / "runs" / "test-node" / run_token
        workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        execution = TestNodeExecution(
            app=app,
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            definition=frozen.definition,
            context=frozen.context,
            context_ref=frozen.context_ref,
            runtime=runtime,
            workspace_root=workspace_root,
            run_id=run_id,
            trace_id=trace_id,
        )
        executor = self.executor_factory(execution)
        diagnostic_scheduler = WorkScheduler(
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
            runtime=runtime,
        )
        dispatch = await _dispatch_diagnostic_target(
            scheduler=diagnostic_scheduler,
            coordinate=target,
            executor=executor,
            runtime=runtime,
            definition=frozen.definition,
            app=app,
            scope_id=scope_id,
            run_id=run_id,
            span=root_span,
            dispatch_error_code="test_node_dispatch_error",
            interrupt_code="test_node_dispatch_interrupted",
            cancel_code="test_node_dispatch_cancelled",
            nonterminal_code="test_node_nonterminal_dispatch_failure",
            settled_statuses=_TERMINAL_WORK_HEAD_STATUSES,
        )
        if dispatch is not None:
            root_span.finish(
                status="passed" if dispatch.after_state == "committed" else "failed",
                output_refs=tuple(
                    ref for ref in (dispatch.commit_ref, dispatch.evaluation_ref) if ref is not None
                ),
            )
            app.telemetry.flush()

        head = heads.read_head(target)
        if head is None or head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_node_no_terminal_result",
                "the real target dispatch did not produce one terminal Work head",
            )
        attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.validation_report_ref is None or head.evaluation_ref is None:
            raise TestNodeError(
                "test_node_missing_validation_report",
                "the target dispatch did not persist its ValidationReport and evaluation",
            )
        report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = app.artifacts.get_json(head.evaluation_ref)
        commit = (
            app.artifacts.get_json(head.commit_ref, WorkCommit)
            if head.commit_ref is not None
            else None
        )
        if not (
            attempt.diagnostic_only
            and not attempt.releasable
            and report.diagnostic_only
            and not report.releasable
            and bool(evaluation.get("diagnostic_only"))
            and not bool(evaluation.get("releasable"))
            and (commit is None or (commit.diagnostic_only and not commit.releasable))
        ):
            raise TestNodeError(
                "test_node_diagnostic_marking_failed",
                "the target result was not fully marked diagnostic-only and non-releasable",
            )
        scene = self._scene_payload(app, scope_id=scope_id, run_id=run_id)
        return TestNodeResult(
            source_scope_id=scope_id,
            target_coordinate=target,
            source_state_root=str(source_root),
            diagnostic_state_root=str(diagnostic_root),
            source_head_revision=frozen.source_head.revision,
            source_attempt_ref=frozen.source_head.attempt_ref,
            archived_source_head_path=str(archived_head_path),
            source_proposal_llm_tokens=source_proposal_llm_tokens,
            proposal_llm_tokens=frozen.definition.proposal_policy.budget.llm_tokens,
            source_proposal_wall_seconds=source_proposal_wall_seconds,
            proposal_wall_seconds=frozen.definition.proposal_policy.budget.wall_seconds,
            source_execution_envelope=source_execution_envelope,
            execution_envelope=self._proposal_execution_envelope(frozen.definition),
            proposal_budget_override_ref=proposal_budget_override_ref,
            runtime_implementation_override_ref=runtime_implementation_override_ref,
            runtime_profile_override_ref=runtime_profile_override_ref,
            target_attempt_ref=head.attempt_ref,
            target_evaluation_ref=head.evaluation_ref,
            target_commit_ref=head.commit_ref,
            status=cast(
                Literal["committed", "failed", "needs_human", "interrupted"],
                head.status,
            ),
            validation_report=report,
            proposal_executions=self._proposal_executions(app.controller.artifacts, attempt),
            actual_usage=attempt.observed_actual,
            unknown_usage=attempt.unknown_upper_bound,
            conservative_usage=attempt.conservative_committed,
            reserved_budget=budget,
            scene=scene,
        )

    def _resolve_source_root(self) -> Path:
        selected = self.source_state_root or self.config.state_root
        candidate = selected.expanduser()
        if candidate.exists() and candidate.is_symlink():
            raise TestNodeError(
                "test_node_source_state_symlink",
                "source state root cannot be a link",
            )
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise TestNodeError(
                "test_node_source_state_missing",
                "source state root is unavailable",
            ) from exc
        if not resolved.is_dir():
            raise TestNodeError(
                "test_node_source_state_invalid",
                "source state root must be a real directory",
            )
        return resolved

    def _assert_no_symlinks(source_root: Path) -> None:
        for directory, directories, files in os.walk(source_root, followlinks=False):
            relative = Path(directory).resolve().relative_to(source_root)
            if relative == Path("."):
                # Match the copy policy exactly: transient execution
                # workspaces are outside the frozen WorkGraph input closure.
                directories[:] = [
                    name for name in directories if name not in _NON_DURABLE_STATE_DIRECTORIES
                ]
            for name in (*directories, *files):
                if (Path(directory) / name).is_symlink():
                    raise TestNodeError(
                        "test_node_source_state_symlink",
                        "source state root contains a symbolic link",
                    )

    @staticmethod
    def _resolve_coordinate(
        heads: tuple[WorkControlHead, ...],
        supplied: str,
    ) -> WorkCoordinate:
        if not heads:
            raise TestNodeError("test_node_scope_not_found", "scope has no durable Work heads")
        expected: WorkCoordinate | None = None
        if supplied.startswith("{"):
            try:
                expected = WorkCoordinate.model_validate(json.loads(supplied))
            except (ValueError, TypeError):
                raise TestNodeError(
                    "test_node_coordinate_invalid",
                    "target coordinate must be an exact coordinate key or JSON object",
                ) from None
        matches = tuple(
            head.coordinate
            for head in heads
            if (
                head.coordinate.coordinate_key == supplied
                or TestNodeRunner._coordinate_label(head.coordinate) == supplied
                or TestNodeRunner._coordinate_scene_label(head.coordinate) == supplied
                or (expected is not None and head.coordinate == expected)
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_coordinate_not_found",
                (
                    "target must resolve to one captured Work head; use its exact hash, "
                    "coordinate JSON, component|stage|artifact_slot|group_id|shard_id, or "
                    "the component.stage.artifact_slot label shown by observe"
                ),
            )
        return matches[0]

    @staticmethod
    def _coordinate_label(coordinate: WorkCoordinate) -> str:
        return "|".join(
            (
                coordinate.component,
                coordinate.stage,
                coordinate.artifact_slot,
                coordinate.group_id or "",
                coordinate.shard_id or "",
            )
        )

    @staticmethod
    def _coordinate_scene_label(coordinate: WorkCoordinate) -> str:
        """Return the compact label rendered by the observable coordinate scene.

        Exact hashes and pipe-delimited labels remain the unambiguous forms.
        This bridge lets a project-execution Agent copy the compact label it
        just observed into a diagnostic command.  Ambiguous labels still fail
        closed at the existing unique-match check.
        """

        return ".".join((coordinate.component, coordinate.stage, coordinate.artifact_slot))

    def _load_frozen_target(
        self,
        *,
        app: FoundryApplication,
        scope_id: str,
        target: WorkCoordinate,
        allow_diagnostic_ancestor_closure: bool = False,
    ) -> _FrozenTarget:
        heads = app.controller.work_control
        source_head = heads.read_head(target)
        if source_head is None:
            raise TestNodeError("test_node_target_not_captured", "target has no captured Work head")
        if source_head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_node_target_not_terminal",
                "target must be terminal before it can be isolated",
            )
        source_attempt = app.artifacts.get_json(source_head.attempt_ref, WorkAttempt)
        candidates: list[_FrozenTarget] = []
        saw_matching_manifest = False
        saw_incomplete_definition_closure = False
        saw_missing_ancestor_closure = False
        missing_ancestor_detail: str | None = None
        saw_input_closure_mismatch = False
        for manifest_ref in app.artifacts.list_revisions():
            if manifest_ref.artifact_type != "control.work_graph_manifest":
                continue
            try:
                manifest = app.artifacts.get_json(manifest_ref, WorkGraphManifest)
            except ValueError:
                continue
            if manifest.scope_id != scope_id or not any(
                item.work_id == source_head.work_id
                and item.definition_digest == source_head.definition_digest
                and item.coordinate == target
                for item in manifest.node_bindings
            ):
                continue
            saw_matching_manifest = True
            try:
                graph = self._reconstruct_graph(app.controller.artifacts, manifest)
                rendered = graph.manifest(
                    topology_id=manifest.topology_id,
                    external_root_refs=manifest.external_root_refs,
                )
            except WorkResumeError:
                saw_incomplete_definition_closure = True
                continue
            except ValueError:
                continue
            if rendered != manifest:
                continue
            definition = graph.require(target)
            contexts = tuple(
                ref
                for ref in manifest.external_root_refs
                if ref.artifact_type == "control.generation_context"
            )
            if len(contexts) != 1:
                continue
            context_ref = contexts[0]
            try:
                context = app.artifacts.get_json(context_ref, GenerationContext)
            except ValueError:
                continue
            diagnostic_runtime = (
                _diagnostic_work_runtime(
                    app=app,
                    heads=heads,
                    budget=self._single_attempt_budget(definition),
                )
                if allow_diagnostic_ancestor_closure
                else None
            )
            scheduler = WorkScheduler(
                graph=graph,
                manifest=manifest,
                manifest_ref=manifest_ref,
                heads=heads,
                artifacts=app.controller.artifacts,
                runtime=diagnostic_runtime,
                allow_diagnostic_ancestors=allow_diagnostic_ancestor_closure,
            )
            try:
                self._assert_complete_ancestor_closure(
                    app=app,
                    graph=graph,
                    target=target,
                    allow_diagnostic_ancestor_closure=allow_diagnostic_ancestor_closure,
                )
                resolved = scheduler.resolve_inputs(target)
            except TestNodeError as exc:
                if exc.code != "missing_ancestor_closure":
                    raise
                saw_missing_ancestor_closure = True
                missing_ancestor_detail = missing_ancestor_detail or str(exc)
                continue
            except WorkResumeError:
                saw_missing_ancestor_closure = True
                continue
            if resolved.all_input_refs != source_attempt.input_refs:
                saw_input_closure_mismatch = True
                continue
            candidates.append(
                _FrozenTarget(
                    graph=graph,
                    manifest=manifest,
                    manifest_ref=manifest_ref,
                    definition=definition,
                    context=context,
                    context_ref=context_ref,
                    source_head=source_head,
                )
            )
        if candidates:
            return min(
                candidates,
                key=lambda item: (len(item.graph.definitions), item.manifest.topology_id),
            )
        if saw_incomplete_definition_closure:
            raise TestNodeError(
                "test_node_frozen_graph_incomplete",
                "the frozen graph does not retain its exact WorkDefinition closure",
            )
        if saw_missing_ancestor_closure:
            raise TestNodeError(
                "missing_ancestor_closure",
                missing_ancestor_detail
                or "the copied scope does not retain one committed ancestor closure",
            )
        if saw_input_closure_mismatch:
            raise TestNodeError(
                "test_node_input_closure_mismatch",
                "the persisted target input closure does not match its frozen graph",
            )
        if saw_matching_manifest:
            raise TestNodeError(
                "test_node_frozen_graph_invalid",
                "the frozen graph cannot be reconstructed exactly",
            )
        raise TestNodeError(
            "test_node_frozen_graph_not_found",
            "no exact frozen WorkGraph manifest is available for the target",
        )

    @staticmethod
    def _reconstruct_graph(
        artifacts: ArtifactWriter,
        manifest: WorkGraphManifest,
    ) -> GenerationWorkGraph:
        definitions = tuple(
            TestNodeRunner._definition_for_binding(artifacts, binding)
            for binding in manifest.node_bindings
        )
        groups = tuple(
            WorkGroupDefinition(
                group_id=binding.group_id,
                scope_id=manifest.scope_id,
                member_coordinates=binding.member_coordinates,
                aggregate_coordinate=binding.aggregate_coordinate,
            )
            for binding in manifest.group_bindings
        )
        if any(
            group.content_digest() != binding.group_digest
            for group, binding in zip(groups, manifest.group_bindings, strict=True)
        ):
            raise WorkResumeError("persisted WorkGraph group binding cannot be reconstructed")
        milestones = tuple(
            WorkGraphMilestone(
                milestone_id=binding.milestone_id,
                kind=binding.kind,
                required_coordinates=binding.required_coordinates,
                establishes=binding.establishes,
            )
            for binding in manifest.milestone_bindings
        )
        if any(
            milestone.content_digest() != binding.milestone_digest
            for milestone, binding in zip(milestones, manifest.milestone_bindings, strict=True)
        ):
            raise WorkResumeError("persisted WorkGraph milestone cannot be reconstructed")
        return GenerationWorkGraph.compile(
            definitions,
            mode=manifest.mode,
            required_terminal_coordinates=manifest.required_terminal_coordinates,
            groups=groups,
            milestones=milestones,
        )

    @staticmethod
    def _definition_for_binding(
        artifacts: ArtifactWriter,
        binding: WorkGraphNodeBinding,
    ) -> WorkDefinition:
        # ``WorkGraphNodeBinding`` is intentionally compact; the immutable
        # WorkDefinition revision is the executable contract.  Recover only a
        # byte-equivalent definition bearing this exact digest and coordinate.
        definition_digest = binding.definition_digest
        coordinate = binding.coordinate
        work_id = binding.work_id
        candidates: list[WorkDefinition] = []
        for ref in artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != definition_digest
            ):
                continue
            try:
                definition = artifacts.get_json(ref, WorkDefinition)
            except ValueError:
                continue
            if (
                definition.work_id == work_id
                and definition.coordinate == coordinate
                and definition.definition_digest == definition_digest
            ):
                candidates.append(definition)
        if not candidates or any(item != candidates[0] for item in candidates[1:]):
            raise WorkResumeError("frozen WorkGraph node lacks one exact WorkDefinition")
        return candidates[0]

    @staticmethod
    def _assert_complete_ancestor_closure(
        *,
        app: FoundryApplication,
        graph: GenerationWorkGraph,
        target: WorkCoordinate,
        allow_diagnostic_ancestor_closure: bool = False,
    ) -> None:
        visited: set[str] = set()

        def visit(coordinate: WorkCoordinate) -> None:
            definition = graph.require(coordinate)
            for parent_coordinate in definition.dependency_coordinates:
                key = parent_coordinate.coordinate_key
                if key in visited:
                    continue
                visited.add(key)
                parent_definition = graph.require(parent_coordinate)
                parent_label = TestNodeRunner._coordinate_scene_label(parent_coordinate)
                parent_head = app.controller.work_control.read_head(parent_coordinate)
                if parent_head is None or parent_head.status != "committed":
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        (
                            "ancestor "
                            f"{TestNodeRunner._coordinate_scene_label(parent_coordinate)} "
                            "has no committed Work head in the copied scope"
                        ),
                    )
                parent_attempt = app.artifacts.get_json(parent_head.attempt_ref, WorkAttempt)
                parent_commit: WorkCommit | None = None
                if parent_head.commit_ref is not None:
                    parent_commit = app.artifacts.get_json(parent_head.commit_ref, WorkCommit)
                    if parent_commit.diagnostic_only:
                        if allow_diagnostic_ancestor_closure:
                            try:
                                diagnostic = app.controller.work_control.require_diagnostic_commit(
                                    definition=parent_definition,
                                    input_refs=parent_attempt.input_refs,
                                    artifacts=app.controller.artifacts,
                                )
                            except WorkResumeError as exc:
                                raise TestNodeError(
                                    "missing_ancestor_closure",
                                    (
                                        "ancestor "
                                        f"{parent_label} "
                                        "does not retain one exact diagnostic WorkCommit"
                                    ),
                                ) from exc
                            if diagnostic is None:
                                raise TestNodeError(
                                    "missing_ancestor_closure",
                                    (
                                        "ancestor "
                                        f"{parent_label} "
                                        "does not retain one exact diagnostic WorkCommit"
                                    ),
                                )
                            visit(parent_coordinate)
                            continue
                        if not parent_commit.releasable:
                            raise TestNodeError(
                                "missing_ancestor_closure",
                                (
                                    "ancestor "
                                    f"{TestNodeRunner._coordinate_scene_label(parent_coordinate)} "
                                    "is a diagnostic-only commit; use a marked descendant or "
                                    "successor runner so the diagnostic parent remains explicit"
                                ),
                            )
                # A diagnostic-only commit is never normal release authority;
                # only the explicit branch above may consume it.
                if parent_commit is not None and parent_commit.diagnostic_only:
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        (
                            "ancestor "
                            f"{TestNodeRunner._coordinate_scene_label(parent_coordinate)} "
                            "does not retain one active releasable WorkCommit"
                        ),
                    )
                try:
                    active = app.controller.work_control.require_active_commit(
                        definition=parent_definition,
                        input_refs=parent_attempt.input_refs,
                        artifacts=app.controller.artifacts,
                    )
                except WorkResumeError as exc:
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        (
                            "ancestor "
                            f"{TestNodeRunner._coordinate_scene_label(parent_coordinate)} "
                            "does not retain one active releasable WorkCommit"
                        ),
                    ) from exc
                if active is None:
                    raise TestNodeError(
                        "missing_ancestor_closure",
                        (
                            "ancestor "
                            f"{TestNodeRunner._coordinate_scene_label(parent_coordinate)} "
                            "does not retain one active releasable WorkCommit"
                        ),
                    )
                visit(parent_coordinate)

        visit(target)

    @staticmethod
    def _single_attempt_budget(definition: WorkDefinition) -> Budget:
        operation_budgets = [definition.proposal_policy.budget, definition.validation_policy.budget]
        if definition.assurance_policy is not None:
            operation_budgets.append(definition.assurance_policy.budget)
        values: dict[str, int | float] = {}
        for field_name in Budget.model_fields:
            if field_name == "schema_version":
                continue
            if field_name == "repair_attempts":
                values[field_name] = 0
            else:
                values[field_name] = sum(getattr(item, field_name) for item in operation_budgets)
        return Budget.model_validate(values)

    @staticmethod
    def _proposal_execution_envelope(definition: WorkDefinition) -> ProposalExecutionEnvelope:
        """Project the frozen physical and logical Agent budget separately."""

        policy = definition.proposal_policy
        return ProposalExecutionEnvelope(
            physical_turn_llm_tokens=policy.budget.llm_tokens,
            physical_turn_wall_seconds=policy.budget.wall_seconds,
            logical_session_token_limit=policy.session_token_limit,
            logical_session_wall_seconds=policy.session_wall_seconds,
            maximum_session_continuations=definition.repair_policy.maximum_session_continuations,
        )

    def _production_executor(self, execution: TestNodeExecution) -> WorkExecutor:
        runner = execution.app.controller.direct_work_runner
        if runner is None:
            raise TestNodeError(
                "test_node_executor_missing",
                "the configured application has no Direct WorkGraph executor",
            )
        kernel = SchedulerLeafExecutor(
            runtime=execution.runtime,
            local_terminal_diagnostic_sink=(
                execution.terminal_feedback.capture
                if execution.terminal_feedback is not None
                else None
            ),
        )
        epoch_ref, epoch = self._epoch_for_manifest(
            execution.app.controller.artifacts,
            execution.manifest_ref,
        )
        if epoch.epoch_kind == "bootstrap":
            definitions = tuple(
                self._one_definition(execution.graph, component, node_stage)
                for component, node_stage in (
                    ("research", "research_plan"),
                    ("research", "evidence_acquisition"),
                    ("research", "evidence_synthesis"),
                    ("design", "world_architecture"),
                )
            )
            executors = runner._bootstrap_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                workspace=execution.workspace_root,
                kernel=kernel,
                definitions=definitions,
            )
        elif epoch.epoch_kind == "world":
            executors = runner._design_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                workspace=execution.workspace_root,
                kernel=kernel,
                graph=execution.graph,
                verifier_plan=None,
            )
        elif epoch.epoch_kind == "design":
            verifier_plan = self._one_definition(execution.graph, "verifier", "verifier_plan")
            executors = runner._design_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                workspace=execution.workspace_root,
                kernel=kernel,
                graph=execution.graph,
                verifier_plan=verifier_plan,
            )
        elif epoch.epoch_kind == "final":
            executors = runner._final_executors(  # noqa: SLF001 - frozen runner assembly
                context_ref=execution.context_ref,
                context=execution.context,
                workspace=execution.workspace_root,
                run_id=execution.run_id,
                trace_id=execution.trace_id,
                kernel=kernel,
                graph=execution.graph,
                final_epoch_ref=epoch_ref,
                final_manifest_ref=execution.manifest_ref,
            )
        else:  # pragma: no cover - WorkGraphEpoch has a closed literal
            raise TestNodeError(
                "test_node_frozen_graph_epoch_invalid",
                "frozen graph epoch has an unsupported kind",
            )
        try:
            return executors[execution.definition.work_id]  # type: ignore[return-value]
        except KeyError as exc:
            raise TestNodeError(
                "test_node_executor_missing",
                "the frozen target has no framework-owned leaf executor",
            ) from exc

    @staticmethod
    def _one_definition(
        graph: GenerationWorkGraph,
        component: str,
        stage: str,
    ) -> WorkDefinition:
        matches = tuple(
            definition
            for definition in graph.definitions
            if definition.coordinate.component == component and definition.coordinate.stage == stage
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_frozen_graph_invalid",
                "frozen graph lacks one required unique work definition",
            )
        return matches[0]

    @staticmethod
    def _epoch_for_manifest(
        artifacts: ArtifactWriter,
        manifest_ref: ArtifactRef,
    ) -> tuple[ArtifactRef, WorkGraphEpoch]:
        matches: list[tuple[ArtifactRef, WorkGraphEpoch]] = []
        for ref in artifacts.list_revisions():
            if ref.artifact_type != "control.work_graph_epoch":
                continue
            try:
                epoch = artifacts.get_json(ref, WorkGraphEpoch)
            except ValueError:
                continue
            if epoch.manifest_ref == manifest_ref:
                matches.append((ref, epoch))
        if len(matches) != 1:
            raise TestNodeError(
                "test_node_frozen_graph_epoch_missing",
                "frozen target requires one exact WorkGraph epoch",
            )
        return matches[0]

    @staticmethod
    def _proposal_executions(
        artifacts: ArtifactWriter,
        attempt: WorkAttempt,
    ) -> tuple[ProposalExecution, ...]:
        executions: list[ProposalExecution] = []
        for operation_ref in attempt.operation_run_refs:
            operation = artifacts.get_json(operation_ref, OperationRun)
            if operation.kind != "proposal" or operation.execution_ref is None:
                continue
            executions.append(artifacts.get_json(operation.execution_ref, ProposalExecution))
        return tuple(executions)

    @staticmethod
    def _scene_payload(
        app: FoundryApplication,
        *,
        scope_id: str,
        run_id: str,
    ) -> dict[str, object]:
        try:
            scene = app.controller.scene_projector.rebuild(scope_id, run_id=run_id)
        except Exception as exc:
            raise TestNodeError(
                "test_node_scene_unavailable",
                "diagnostic scene could not be rebuilt from durable facts",
            ) from exc
        return {
            "index": scene.index.model_dump(mode="json"),
            "coordinates": [item.model_dump(mode="json") for item in scene.coordinates],
        }


class DiagnosticDescendantNodeResult(V2Contract):
    """Safe result for one descendant proof below a diagnostic parent.

    The ordinary form targets one unheaded frozen definition.  The explicitly
    requested infrastructure-retry form instead consumes one exact failed,
    retryable diagnostic terminal through a new ``RepairAction``.  An already
    authorized semantic correction may likewise be executed once through the
    normal Scheduler, without changing its definition, prompt, Skill, or
    feedback.  A current runtime implementation refresh instead supersedes
    that authority and regenerates from the same immutable parent closure.
    All forms retain their diagnostic parents and remain non-releasable.
    """

    source_scope_id: str
    target_coordinate: WorkCoordinate
    source_diagnostic_state_root: str
    diagnostic_state_root: str
    source_manifest_ref: ArtifactRef
    diagnostic_manifest_ref: ArtifactRef
    source_proposal_llm_tokens: int
    proposal_llm_tokens: int
    source_proposal_wall_seconds: float
    proposal_wall_seconds: float
    source_execution_envelope: ProposalExecutionEnvelope
    execution_envelope: ProposalExecutionEnvelope
    proposal_budget_override_ref: ArtifactRef | None = None
    diagnostic_terminal_feedback_override_ref: ArtifactRef | None = None
    runtime_implementation_override_ref: ArtifactRef | None = None
    runtime_profile_override_ref: ArtifactRef | None = None
    superseded_stale_attempt_ref: ArtifactRef | None = None
    superseded_stale_definition_digest: str | None = None
    superseded_authorized_repair_action_ref: ArtifactRef | None = None
    infrastructure_retry_action_ref: ArtifactRef | None = None
    authorized_repair_action_ref: ArtifactRef | None = None
    predecessor_attempt_refs: tuple[ArtifactRef, ...]
    predecessor_commit_refs: tuple[ArtifactRef, ...]
    target_attempt_ref: ArtifactRef
    target_evaluation_ref: ArtifactRef
    target_commit_ref: ArtifactRef | None = None
    status: Literal["committed", "failed", "needs_human", "interrupted", "repair_authorized"]
    validation_report: ValidationReport
    proposal_executions: tuple[ProposalExecution, ...] = ()
    actual_usage: BudgetUsage
    unknown_usage: BudgetUsage
    conservative_usage: BudgetUsage
    reserved_budget: Budget
    scene: dict[str, object]
    diagnostic_terminal_feedback_status: DiagnosticTerminalFeedbackStatus = "not_requested"
    diagnostic_terminal_feedback_path: str | None = None
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


@dataclass(frozen=True, slots=True)
class _FrozenDiagnosticDescendant:
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context: GenerationContext
    context_ref: ArtifactRef
    predecessor_attempt_refs: tuple[ArtifactRef, ...]
    predecessor_commit_refs: tuple[ArtifactRef, ...]
    stale_head: WorkControlHead | None = None
    infrastructure_retry_head: WorkControlHead | None = None
    authorized_repair_head: WorkControlHead | None = None


@dataclass(frozen=True, slots=True)
class _FinalEpochDiagnosticAnchor:
    """The narrowly scoped diagnostic ancestry proof for one final-graph root.

    ``BuildImplementationPlan`` deliberately consumes the ModelingBoundary,
    rather than VerifierPlan.  A diagnostic final epoch can nevertheless be
    causally anchored by its exact diagnostic VerifierPlan commit.  This
    private record carries the immutable epoch facts needed to prove that
    relationship without adding a false production dependency or weakening
    ordinary descendant checks.
    """

    final_epoch_ref: ArtifactRef
    final_manifest_ref: ArtifactRef
    design_epoch_ref: ArtifactRef
    verifier_plan_coordinate: WorkCoordinate
    verifier_plan_definition_digest: str
    verifier_plan_commit_ref: ArtifactRef


class DiagnosticProposalBudgetOverride(V2Contract):
    """One immutable, non-releasable proposal-envelope delta for a diagnostic node.

    A failed frozen node is historical evidence and must never be silently
    edited.  This record binds a fresh diagnostic graph to exactly one larger,
    finite Agent envelope, while keeping its input topology, prompt, Runtime
    Skill, capability profile, and acceptance policy unchanged.  It records
    the complete before/after operation budgets so a longer test cannot be
    mistaken for an unbounded retry or a semantic-model change.
    """

    source_manifest_ref: ArtifactRef
    target_coordinate: WorkCoordinate
    source_definition_digest: str
    source_proposal_budget: OperationBudget
    proposal_budget: OperationBudget
    diagnostic_generation_budget: Budget
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticTerminalFeedbackOverride(V2Contract):
    """One explicit local-observability change for a failed Agent node.

    The semantic input closure, Prompt, Runtime Skill, capability profile, and
    proposal envelope remain immutable.  Only the leaf implementation revision
    gains an opt-in, worker-redacted local terminal sidecar.  This turns a
    feedback-defect follow-up into a new diagnostic definition rather than an
    unsupported retry of the previous failed attempt.
    """

    source_manifest_ref: ArtifactRef
    target_coordinate: WorkCoordinate
    source_definition_digest: str
    source_implementation_revision_id: str
    implementation_revision_id: str
    diagnostic_capture_terminal_excerpt: Literal[True] = True
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticRuntimeImplementationOverride(V2Contract):
    """One explicit current-runtime revision for a frozen diagnostic node.

    The frozen graph remains the immutable input topology and authority record.
    This record merely declares that the real leaf's effective runtime
    instruction/input, mounted Runtime Skill, source schema/compiler, or
    deterministic validation implementation has changed.  It is intentionally
    separate from a budget experiment and does not disclose a raw Prompt,
    Runtime Skill body, provider transcript, or model output.
    """

    source_manifest_ref: ArtifactRef
    target_coordinate: WorkCoordinate
    source_definition_digest: str
    source_implementation_revision_id: str
    implementation_revision_id: str
    source_validator_revision_id: str
    validator_revision_id: str
    source_proposal_budget: OperationBudget | None = None
    proposal_budget: OperationBudget | None = None
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticRuntimeProfileOverride(V2Contract):
    """One explicit profile-only change for a non-releasable node proof.

    The matching definition receives a fresh implementation revision because
    Agent proposal acceptance already treats model/profile provenance as
    material. This record exposes the one safe before/after model delta, never
    a credential, endpoint, rendered Prompt, Skill body, or provider payload.
    """

    source_manifest_ref: ArtifactRef
    target_coordinate: WorkCoordinate
    source_definition_digest: str
    source_implementation_revision_id: str
    implementation_revision_id: str
    source_model: str
    model: str
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticDescendantNodeRunner:
    """Dispatch one frozen descendant below a real diagnostic commit.

    A normal ``test-node`` deliberately requires a terminal target head so it
    can prove that its one output is a fresh rerun rather than a captured
    replay.  That contract cannot advance a staged proof from a newly
    committed diagnostic parent to the first never-attempted downstream node.

    This runner is intentionally narrower than a diagnostic scheduler:

    * source state must already be a marked test-node diagnostic copy;
    * target must be one unheaded definition, a stale terminal head under a
      different immutable definition, an already-authorized repair explicitly
      executed once or superseded by a current-runtime refresh, or an
      explicitly requested retryable infrastructure terminal with the *same*
      immutable definition;
    * all direct parents must be committed and at least one must be a real
      diagnostic commit, except for the two initial final-graph boundaries
      where one exact final epoch retains a diagnostic VerifierPlan anchor;
    * execution happens only in one fresh marked child copy with the ordinary
      Scheduler and a diagnostic-only runtime.

    It does not publish, adopt a diagnostic commit in normal state, or derive
    new topology.  A same-definition semantic repair is permitted only with
    explicit ``execute_authorized_repair`` and goes through the ordinary
    Scheduler; a current-runtime refresh is instead a fresh regeneration that
    never inherits old repair authority or private continuation state.
    ``DiagnosticSuccessorNodeRunner`` remains responsible for the special
    Architecture-to-new-Design-graph case.
    """

    _SETTLED_HEAD_STATUSES = frozenset(
        {"committed", "failed", "needs_human", "interrupted", "repair_authorized"}
    )
    _TERMINAL_FEEDBACK_IMPLEMENTATION_SUFFIX = ".diagnostic-terminal-feedback.v1"

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        target_coordinate: str,
        proposal_llm_tokens: int | None = None,
        proposal_wall_seconds: float | None = None,
        required_manifest_ref: ArtifactRef | None = None,
        required_manifest_revision: str | None = None,
        infrastructure_retry: bool = False,
        execute_authorized_repair: bool = False,
        authorize_semantic_repair: bool = False,
        diagnostic_terminal_feedback: bool = False,
        refresh_current_implementation: bool = False,
        diagnostic_model: str | None = None,
        diagnostic_source_model: str | None = None,
        final_epoch_diagnostic_anchor: _FinalEpochDiagnosticAnchor | None = None,
    ) -> DiagnosticDescendantNodeResult:
        profile_change = _diagnostic_runtime_profile_change(
            self.config,
            diagnostic_model=diagnostic_model,
            diagnostic_source_model=diagnostic_source_model,
        )
        if diagnostic_terminal_feedback and infrastructure_retry:
            raise TestNodeError(
                "test_descendant_terminal_feedback_retry_conflict",
                "local terminal-feedback capture is a new diagnostic definition, not a retry",
            )
        if execute_authorized_repair and authorize_semantic_repair:
            raise TestNodeError(
                "test_descendant_semantic_repair_phase_conflict",
                (
                    "authorize one exact semantic RepairAction first, then execute it in a "
                    "separate diagnostic command"
                ),
            )
        if (execute_authorized_repair or authorize_semantic_repair) and (
            infrastructure_retry
            or diagnostic_terminal_feedback
            or refresh_current_implementation
            or proposal_llm_tokens is not None
            or proposal_wall_seconds is not None
            or profile_change.requested
        ):
            raise TestNodeError(
                "test_descendant_authorized_repair_overlay_conflict",
                (
                    "a semantic repair authorization or execution must retain its exact frozen "
                    "definition, "
                    "input closure, feedback, Prompt, Agent-only Runtime Skill, profile, and "
                    "execution envelope"
                ),
            )
        if diagnostic_terminal_feedback and (
            proposal_llm_tokens is not None or proposal_wall_seconds is not None
        ):
            raise TestNodeError(
                "test_descendant_terminal_feedback_envelope_conflict",
                (
                    "local terminal-feedback capture retains the frozen proposal envelope; "
                    "run one causal diagnostic change at a time"
                ),
            )
        if refresh_current_implementation and (
            infrastructure_retry
            or diagnostic_terminal_feedback
            or proposal_llm_tokens is not None
            or proposal_wall_seconds is not None
            or profile_change.requested
        ):
            raise TestNodeError(
                "test_descendant_runtime_implementation_overlay_conflict",
                (
                    "a current runtime implementation refresh, proposal-envelope change, "
                    "terminal-feedback capture, runtime-profile change, and infrastructure retry "
                    "are separate causal experiments"
                ),
            )
        if profile_change.requested and (
            infrastructure_retry
            or diagnostic_terminal_feedback
            or proposal_llm_tokens is not None
            or proposal_wall_seconds is not None
            or refresh_current_implementation
        ):
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_conflict",
                (
                    "a diagnostic runtime-profile change, proposal-envelope change, "
                    "terminal-feedback capture, and infrastructure retry are separate "
                    "causal experiments"
                ),
            )
        diagnostic_config = profile_change.config
        if required_manifest_ref is not None and required_manifest_revision is not None:
            raise TestNodeError(
                "test_descendant_manifest_selector_conflict",
                (
                    "supply either one manifest ArtifactRef or one manifest revision selector, "
                    "not both"
                ),
            )
        source_diagnostic_root = self._resolve_diagnostic_root()
        diagnostic_root = _prepare_diagnostic_clone(
            source_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            marker_error_code="test_descendant_diagnostic_marker_failed",
            marker_message="fresh diagnostic descendant state could not be marked",
        )

        # Keep the production composition root at the same lazy import seam as
        # ``TestNodeRunner`` and ``DiagnosticSuccessorNodeRunner``.
        from agent_world.app import build_application

        app = build_application(
            diagnostic_config.model_copy(update={"state_root": diagnostic_root})
        )
        if required_manifest_revision is not None:
            required_manifest_ref = self._resolve_manifest_revision(
                app=app,
                revision_id=required_manifest_revision,
            )
        frozen = self._load_frozen_descendant(
            app=app,
            scope_id=scope_id,
            supplied=target_coordinate,
            required_manifest_ref=required_manifest_ref,
            infrastructure_retry=infrastructure_retry,
            diagnostic_terminal_feedback=diagnostic_terminal_feedback,
            allow_authorized_repair_regeneration=refresh_current_implementation,
            allow_authorized_repair_execution=execute_authorized_repair,
            semantic_repair_mode=(
                "authorize"
                if authorize_semantic_repair
                else "execute"
                if execute_authorized_repair
                else None
            ),
            final_epoch_diagnostic_anchor=final_epoch_diagnostic_anchor,
        )
        inherited_profile_config, inherited_profile_overrides = (
            _inherited_diagnostic_runtime_profile_config(
                app=app,
                manifest_ref=frozen.manifest_ref,
                definition=frozen.definition,
                config=diagnostic_config,
            )
        )
        if inherited_profile_overrides:
            if profile_change.requested:
                raise TestNodeError(
                    "test_descendant_runtime_profile_override_conflict",
                    (
                        "the selected frozen target already has a diagnostic model "
                        "profile; preserve it for repair or start one separate fresh profile "
                        "experiment"
                    ),
                )
            if inherited_profile_config != diagnostic_config:
                diagnostic_config = inherited_profile_config
                # The first application exists only to inspect the frozen
                # diagnostic topology.  Rebuild before any Scheduler/runtime
                # work so a same-definition repair resolves the exact model
                # profile that produced its private parsed candidate.
                app = build_application(
                    diagnostic_config.model_copy(update={"state_root": diagnostic_root})
                )
                frozen = self._load_frozen_descendant(
                    app=app,
                    scope_id=scope_id,
                    supplied=target_coordinate,
                    required_manifest_ref=required_manifest_ref,
                    infrastructure_retry=infrastructure_retry,
                    diagnostic_terminal_feedback=diagnostic_terminal_feedback,
                    allow_authorized_repair_regeneration=refresh_current_implementation,
                    allow_authorized_repair_execution=execute_authorized_repair,
                    semantic_repair_mode=(
                        "authorize"
                        if authorize_semantic_repair
                        else "execute"
                        if execute_authorized_repair
                        else None
                    ),
                    final_epoch_diagnostic_anchor=final_epoch_diagnostic_anchor,
                )
        if infrastructure_retry and frozen.infrastructure_retry_head is not None:
            terminal_profile_config = _diagnostic_terminal_profile_config(
                app=app,
                retry_head=frozen.infrastructure_retry_head,
                config=diagnostic_config,
            )
            if terminal_profile_config != diagnostic_config:
                diagnostic_config = terminal_profile_config
                # Same-model recovery is defined by the route that actually
                # produced the failed ProposalExecution.  Older test-node
                # roots could retain a profile-overlay manifest while a
                # refresh accidentally executed with the caller's default
                # model.  Rebuild from the terminal fact before materializing
                # the private workspace profile; otherwise the recovery
                # rejects its own valid draft as a foreign lineage.
                app = build_application(
                    diagnostic_config.model_copy(update={"state_root": diagnostic_root})
                )
                frozen = self._load_frozen_descendant(
                    app=app,
                    scope_id=scope_id,
                    supplied=target_coordinate,
                    required_manifest_ref=required_manifest_ref,
                    infrastructure_retry=True,
                    diagnostic_terminal_feedback=False,
                    allow_authorized_repair_regeneration=False,
                    allow_authorized_repair_execution=False,
                    semantic_repair_mode=None,
                    final_epoch_diagnostic_anchor=final_epoch_diagnostic_anchor,
                )
            retry_head = frozen.infrastructure_retry_head
            if retry_head is None:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_profile_reload_invalid",
                    (
                        "the terminal-model profile reload no longer selects the exact "
                        "retryable Work head"
                    ),
                )
            _mirror_settled_retry_control_record(
                source_state_root=source_diagnostic_root,
                app=app,
                retry_head=retry_head,
            )
        source_manifest_ref = frozen.manifest_ref
        source_proposal_llm_tokens = frozen.definition.proposal_policy.budget.llm_tokens
        source_proposal_wall_seconds = frozen.definition.proposal_policy.budget.wall_seconds
        source_execution_envelope = TestNodeRunner._proposal_execution_envelope(frozen.definition)
        proposal_budget_override_ref: ArtifactRef | None = None
        terminal_feedback_override_ref: ArtifactRef | None = None
        runtime_implementation_override_ref: ArtifactRef | None = None
        runtime_profile_override_ref: ArtifactRef | None = None
        if infrastructure_retry:
            self._assert_retry_envelope_matches(
                source_definition=frozen.definition,
                requested_llm_tokens=proposal_llm_tokens,
                requested_wall_seconds=proposal_wall_seconds,
            )
        elif proposal_llm_tokens is not None or proposal_wall_seconds is not None:
            frozen, proposal_budget_override_ref = self._with_proposal_budget_overlay(
                app=app,
                frozen=frozen,
                proposal_llm_tokens=proposal_llm_tokens,
                proposal_wall_seconds=proposal_wall_seconds,
            )
        elif diagnostic_terminal_feedback:
            frozen, terminal_feedback_override_ref = self._with_terminal_feedback_overlay(
                app=app,
                frozen=frozen,
            )
        elif refresh_current_implementation:
            overlay = _apply_diagnostic_runtime_implementation_overlay(
                app=app,
                source=_ProposalEnvelopeOverlaySource(
                    graph=frozen.graph,
                    manifest=frozen.manifest,
                    manifest_ref=frozen.manifest_ref,
                    definition=frozen.definition,
                    context_ref=frozen.context_ref,
                ),
            )
            frozen = replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            )
            runtime_implementation_override_ref = overlay.override_ref
        elif profile_change.requested:
            overlay = _apply_diagnostic_runtime_profile_overlay(
                app=app,
                source=_ProposalEnvelopeOverlaySource(
                    graph=frozen.graph,
                    manifest=frozen.manifest,
                    manifest_ref=frozen.manifest_ref,
                    definition=frozen.definition,
                    context_ref=frozen.context_ref,
                ),
                source_model=profile_change.source_model,
                model=profile_change.model,
            )
            frozen = replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            )
            runtime_profile_override_ref = overlay.override_ref
        refreshed_causal_repair_sources = (
            self._causal_feedback_for_runtime_implementation_refresh(
                app=app,
                stale_head=frozen.stale_head,
                definition=frozen.definition,
            )
            if refresh_current_implementation
            else None
        )
        budget = TestNodeRunner._single_attempt_budget(frozen.definition)
        if (
            infrastructure_retry
            or execute_authorized_repair
            or refreshed_causal_repair_sources is not None
        ):
            # The frozen operation envelope remains unchanged, but the
            # Scheduler must be able to charge the one newly authorized
            # physical repair attempt.  A current authoring-surface refresh
            # may derive a *new* action from exact causal feedback, but never
            # borrows the old action or private session.  This remains one
            # bounded repair: ``RepairAction.repair_attempt_charge`` is
            # exactly one and the WorkRepairLedger enforces the policy.
            budget = budget.model_copy(update={"repair_attempts": 1})
        run_token = uuid.uuid4().hex
        run_id = f"test-descendant-node:{run_token}"
        trace_id = run_id
        source_workspace_root = source_diagnostic_root / "runs"
        if (
            (infrastructure_retry or authorize_semantic_repair)
            and source_workspace_root.is_dir()
            and not source_workspace_root.is_symlink()
        ):
            continuation_workspace_root = source_workspace_root
        elif execute_authorized_repair:
            continuation_workspace_root = _authorized_semantic_continuation_workspace_root(
                app=app,
                definition=frozen.definition,
                diagnostic_root=diagnostic_root,
            )
        else:
            continuation_workspace_root = diagnostic_root / "runs"
        runtime = _diagnostic_work_runtime(
            app=app,
            heads=app.controller.work_control,
            budget=budget,
            trace_id=trace_id,
            run_id=run_id,
            repair_scope_id=scope_id,
            # A retry's child clone must not copy private agent homes or
            # drafts.  It may receive one explicit record that points back to
            # the immediately preceding marked diagnostic workspace; a fresh
            # first attempt instead captures only its own private root.
            continuation_workspace_root=continuation_workspace_root,
            # The continuation root above is the source child on a retry.
            # A fresh Agent workspace created by this child must be retained
            # under this child's root if it itself ends in a transient.
            diagnostic_workspace_recovery_capture_root=diagnostic_root / "runs",
        )
        terminal_feedback = _diagnostic_terminal_feedback_collector(
            config=app.config,
            scope_id=scope_id,
            requested=diagnostic_terminal_feedback,
        )
        scheduler = WorkScheduler(
            graph=frozen.graph,
            manifest=frozen.manifest,
            manifest_ref=frozen.manifest_ref,
            heads=app.controller.work_control,
            artifacts=app.controller.artifacts,
            runtime=runtime,
            allow_diagnostic_ancestors=True,
        )
        try:
            resolved = scheduler.resolve_inputs(frozen.definition.coordinate)
        except WorkResumeError as exc:
            raise TestNodeError(
                "test_descendant_ancestor_closure_missing",
                f"the frozen descendant lacks one exact committed diagnostic ancestor: {exc}",
            ) from exc
        refreshed_causal_repair_action_ref: ArtifactRef | None = None
        if refreshed_causal_repair_sources is not None:
            source_evaluation_ref, source_report_ref, route_ref = refreshed_causal_repair_sources
            try:
                with app.controller.work_control.exclusive(frozen.definition.coordinate) as lock:
                    authorized = runtime.authorize_causal_repair(
                        lock,
                        definition=frozen.definition,
                        input_refs=resolved.all_input_refs,
                        source_evaluation_ref=source_evaluation_ref,
                        source_report_ref=source_report_ref,
                        route_ref=route_ref,
                    )
            except Exception as exc:
                raise TestNodeError(
                    "test_descendant_runtime_refresh_causal_repair_denied",
                    (
                        "the refreshed authoring definition could not create one new "
                        "feedback-bound causal repair action"
                    ),
                ) from exc
            refreshed_causal_repair_action_ref = authorized.repair_action_ref
            if (
                authorized.status != "repair_authorized"
                or refreshed_causal_repair_action_ref is None
            ):
                raise TestNodeError(
                    "test_descendant_runtime_refresh_causal_repair_invalid",
                    "the refreshed authoring definition did not create one exact RepairAction",
                )
        scheduled_target = next(
            (
                item
                for item in scheduler.snapshot().work
                if item.coordinate == frozen.definition.coordinate
            ),
            None,
        )
        if (
            not authorize_semantic_repair
            and frozen.stale_head is not None
            and frozen.stale_head.definition_digest == frozen.definition.definition_digest
            and scheduled_target is not None
            and scheduled_target.state not in {"ready", "repair_ready", "stale"}
        ):
            raise TestNodeError(
                "test_descendant_target_already_captured",
                (
                    "the exact diagnostic descendant already has a terminal Work head for "
                    "its resolved input closure"
                ),
            )
        if execute_authorized_repair and (
            frozen.authorized_repair_head is None
            or frozen.authorized_repair_head.repair_action_ref is None
            or scheduled_target is None
            or scheduled_target.state != "repair_ready"
        ):
            raise TestNodeError(
                "test_descendant_authorized_repair_not_ready",
                (
                    "the copied diagnostic target no longer has the exact Scheduler-authorized "
                    "semantic repair ready for one normal dispatch"
                ),
            )

        infrastructure_retry_action_ref: ArtifactRef | None = None
        authorized_semantic_repair_action_ref: ArtifactRef | None = None
        authorized_semantic_repair_evaluation_ref: ArtifactRef | None = None
        if infrastructure_retry:
            try:
                with app.controller.work_control.exclusive(frozen.definition.coordinate) as lock:
                    authorized = runtime.authorize_diagnostic_infrastructure_retry(
                        lock,
                        definition=frozen.definition,
                        input_refs=resolved.all_input_refs,
                    )
            except (WorkHeadConflictError, WorkRepairDenied, WorkRuntimeError) as exc:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_denied",
                    (
                        "the exact terminal diagnostic result does not retain one "
                        "policy-authorized retryable infrastructure route: "
                        f"{type(exc).__name__}({exc})"
                    ),
                ) from exc
            except Exception as exc:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_denied",
                    (
                        "the exact terminal diagnostic result does not retain one "
                        "policy-authorized retryable infrastructure route: "
                        f"unexpected_control_exception({type(exc).__name__})"
                    ),
                ) from exc
            infrastructure_retry_action_ref = authorized.repair_action_ref
            if authorized.status != "repair_authorized" or infrastructure_retry_action_ref is None:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_authorization_invalid",
                    "the diagnostic infrastructure retry did not create one exact RepairAction",
                )
        if authorize_semantic_repair:
            try:
                with app.controller.work_control.exclusive(frozen.definition.coordinate) as lock:
                    authorized = runtime.authorize_diagnostic_semantic_repair(
                        lock,
                        definition=frozen.definition,
                        input_refs=resolved.all_input_refs,
                    )
            except Exception as exc:
                raise TestNodeError(
                    "test_descendant_semantic_repair_authorization_denied",
                    (
                        "the exact diagnostic target does not retain one policy-authorized "
                        "actionable semantic repair"
                    ),
                ) from exc
            authorized_semantic_repair_action_ref = authorized.repair_action_ref
            if (
                authorized.status != "repair_authorized"
                or authorized_semantic_repair_action_ref is None
            ):
                raise TestNodeError(
                    "test_descendant_semantic_repair_authorization_invalid",
                    "the diagnostic semantic repair did not create one exact RepairAction",
                )
            authorized_semantic_repair_evaluation_ref = authorized.evaluation_ref

        root_span = app.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation=(
                "test_descendant_node.authorize_semantic_repair"
                if authorize_semantic_repair
                else "test_descendant_node.dispatch"
            ),
            run_id=run_id,
            node=frozen.definition.work_id,
            input_refs=resolved.all_input_refs,
            attributes={
                "diagnostic_only": True,
                "releasable": False,
                "infrastructure_retry": infrastructure_retry,
                "authorized_repair_execution": execute_authorized_repair,
                "semantic_repair_prepare": authorize_semantic_repair,
                "diagnostic_terminal_feedback": diagnostic_terminal_feedback,
                "runtime_implementation_override": refresh_current_implementation,
                "runtime_implementation_causal_repair": (
                    refreshed_causal_repair_action_ref is not None
                ),
                "runtime_profile_override": profile_change.requested,
            },
        )
        app.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root_span.span_id,
        )
        dispatch = None
        if authorize_semantic_repair:
            root_span.finish(
                status="passed",
                output_refs=tuple(
                    ref
                    for ref in (
                        authorized_semantic_repair_action_ref,
                        authorized_semantic_repair_evaluation_ref,
                    )
                    if ref is not None
                ),
            )
            app.telemetry.flush()
        else:
            workspace_root = diagnostic_root / "runs" / "test-descendant-node" / run_token
            workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            execution = TestNodeExecution(
                app=app,
                graph=frozen.graph,
                manifest=frozen.manifest,
                manifest_ref=frozen.manifest_ref,
                definition=frozen.definition,
                context=frozen.context,
                context_ref=frozen.context_ref,
                runtime=runtime,
                workspace_root=workspace_root,
                run_id=run_id,
                trace_id=trace_id,
                terminal_feedback=terminal_feedback,
            )
            executor = (
                self.executor_factory(execution)
                if self.executor_factory is not None
                else TestNodeRunner(config=self.config)._production_executor(execution)
            )
            dispatch = await _dispatch_diagnostic_target(
                scheduler=scheduler,
                coordinate=frozen.definition.coordinate,
                executor=executor,
                runtime=runtime,
                definition=frozen.definition,
                app=app,
                scope_id=scope_id,
                run_id=run_id,
                span=root_span,
                dispatch_error_code="test_descendant_node_dispatch_error",
                interrupt_code="test_descendant_node_dispatch_interrupted",
                cancel_code="test_descendant_node_dispatch_cancelled",
                nonterminal_code="test_descendant_nonterminal_dispatch_failure",
                settled_statuses=self._SETTLED_HEAD_STATUSES,
            )
        if dispatch is not None:
            root_span.finish(
                status="passed" if dispatch.after_state == "committed" else "failed",
                output_refs=tuple(
                    ref for ref in (dispatch.commit_ref, dispatch.evaluation_ref) if ref is not None
                ),
            )
            app.telemetry.flush()

        head = app.controller.work_control.read_head(frozen.definition.coordinate)
        if head is None or head.status not in self._SETTLED_HEAD_STATUSES:
            raise TestNodeError(
                "test_descendant_no_terminal_result",
                "the fresh diagnostic descendant did not produce one terminal Work head",
            )
        attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.validation_report_ref is None or head.evaluation_ref is None:
            raise TestNodeError(
                "test_descendant_missing_validation_report",
                "the fresh diagnostic descendant did not persist ValidationReport and evaluation",
            )
        report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = app.artifacts.get_json(head.evaluation_ref)
        commit = (
            app.artifacts.get_json(head.commit_ref, WorkCommit)
            if head.commit_ref is not None
            else None
        )
        if not (
            attempt.diagnostic_only
            and not attempt.releasable
            and report.diagnostic_only
            and not report.releasable
            and bool(evaluation.get("diagnostic_only"))
            and not bool(evaluation.get("releasable"))
            and (commit is None or (commit.diagnostic_only and not commit.releasable))
        ):
            raise TestNodeError(
                "test_descendant_diagnostic_marking_failed",
                "the fresh diagnostic descendant was not fully diagnostic-only and non-releasable",
            )
        terminal_feedback_status, terminal_feedback_path = (
            terminal_feedback.finalize()
            if terminal_feedback is not None
            else ("not_requested", None)
        )
        return DiagnosticDescendantNodeResult(
            source_scope_id=scope_id,
            target_coordinate=frozen.definition.coordinate,
            source_diagnostic_state_root=str(source_diagnostic_root),
            diagnostic_state_root=str(diagnostic_root),
            source_manifest_ref=source_manifest_ref,
            diagnostic_manifest_ref=frozen.manifest_ref,
            source_proposal_llm_tokens=source_proposal_llm_tokens,
            proposal_llm_tokens=frozen.definition.proposal_policy.budget.llm_tokens,
            source_proposal_wall_seconds=source_proposal_wall_seconds,
            proposal_wall_seconds=frozen.definition.proposal_policy.budget.wall_seconds,
            source_execution_envelope=source_execution_envelope,
            execution_envelope=TestNodeRunner._proposal_execution_envelope(frozen.definition),
            proposal_budget_override_ref=proposal_budget_override_ref,
            diagnostic_terminal_feedback_override_ref=terminal_feedback_override_ref,
            runtime_implementation_override_ref=runtime_implementation_override_ref,
            runtime_profile_override_ref=runtime_profile_override_ref,
            superseded_stale_attempt_ref=(
                frozen.stale_head.attempt_ref if frozen.stale_head is not None else None
            ),
            superseded_stale_definition_digest=(
                frozen.stale_head.definition_digest if frozen.stale_head is not None else None
            ),
            superseded_authorized_repair_action_ref=(
                frozen.stale_head.repair_action_ref
                if frozen.stale_head is not None and frozen.stale_head.status == "repair_authorized"
                else None
            ),
            infrastructure_retry_action_ref=infrastructure_retry_action_ref,
            authorized_repair_action_ref=(
                authorized_semantic_repair_action_ref
                or refreshed_causal_repair_action_ref
                or (
                    frozen.authorized_repair_head.repair_action_ref
                    if frozen.authorized_repair_head is not None
                    else None
                )
            ),
            predecessor_attempt_refs=frozen.predecessor_attempt_refs,
            predecessor_commit_refs=frozen.predecessor_commit_refs,
            target_attempt_ref=head.attempt_ref,
            target_evaluation_ref=head.evaluation_ref,
            target_commit_ref=head.commit_ref,
            status=cast(
                Literal[
                    "committed",
                    "failed",
                    "needs_human",
                    "interrupted",
                    "repair_authorized",
                ],
                head.status,
            ),
            validation_report=report,
            proposal_executions=TestNodeRunner._proposal_executions(
                app.controller.artifacts,
                attempt,
            ),
            actual_usage=attempt.observed_actual,
            unknown_usage=attempt.unknown_upper_bound,
            conservative_usage=attempt.conservative_committed,
            reserved_budget=budget,
            scene=TestNodeRunner._scene_payload(app, scope_id=scope_id, run_id=run_id),
            diagnostic_terminal_feedback_status=terminal_feedback_status,
            diagnostic_terminal_feedback_path=terminal_feedback_path,
        )

    @staticmethod
    def _proposal_envelope(
        *,
        source_definition: WorkDefinition,
        requested_llm_tokens: int | None,
        requested_wall_seconds: float | None,
        diagnostic_budget: Budget,
    ) -> tuple[int, float]:
        """Resolve one explicit finite Agent envelope for a descendant proof."""

        policy = source_definition.proposal_policy
        if policy.executor != "agent":
            raise TestNodeError(
                "test_descendant_proposal_envelope_target_not_agent",
                "a diagnostic proposal envelope is valid only for one Agent target",
            )
        source_tokens = policy.budget.llm_tokens
        source_wall = policy.budget.wall_seconds
        tokens = source_tokens if requested_llm_tokens is None else requested_llm_tokens
        wall = source_wall if requested_wall_seconds is None else requested_wall_seconds
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
            raise TestNodeError(
                "test_descendant_proposal_token_invalid",
                "diagnostic proposal output-token budget must be one positive integer",
            )
        if tokens < source_tokens:
            raise TestNodeError(
                "test_descendant_proposal_token_decreased",
                "diagnostic proposal output-token budget may not decrease the frozen value",
            )
        if tokens > diagnostic_budget.llm_tokens:
            raise TestNodeError(
                "test_descendant_proposal_token_exceeds_generation_budget",
                "diagnostic proposal output-token budget exceeds the configured generation budget",
            )
        if (
            isinstance(wall, bool)
            or not isinstance(wall, (int, float))
            or not math.isfinite(wall)
            or wall <= 0
        ):
            raise TestNodeError(
                "test_descendant_proposal_wall_invalid",
                "diagnostic proposal wall budget must be one finite positive number",
            )
        wall = float(wall)
        if wall < source_wall:
            raise TestNodeError(
                "test_descendant_proposal_wall_decreased",
                "diagnostic proposal wall budget may not decrease the frozen value",
            )
        if wall > diagnostic_budget.wall_seconds:
            raise TestNodeError(
                "test_descendant_proposal_wall_exceeds_generation_budget",
                "diagnostic proposal wall budget exceeds the configured generation budget",
            )
        if (
            (requested_llm_tokens is not None or requested_wall_seconds is not None)
            and tokens == source_tokens
            and wall == source_wall
        ):
            raise TestNodeError(
                "test_descendant_proposal_envelope_not_changed",
                "diagnostic proposal envelope must change at least one frozen budget dimension",
            )
        return tokens, wall

    def _with_proposal_budget_overlay(
        self,
        *,
        app: FoundryApplication,
        frozen: _FrozenDiagnosticDescendant,
        proposal_llm_tokens: int | None,
        proposal_wall_seconds: float | None,
    ) -> tuple[_FrozenDiagnosticDescendant, ArtifactRef]:
        overlay = _apply_diagnostic_proposal_envelope_overlay(
            app=app,
            config=self.config,
            source=_ProposalEnvelopeOverlaySource(
                graph=frozen.graph,
                manifest=frozen.manifest,
                manifest_ref=frozen.manifest_ref,
                definition=frozen.definition,
                context_ref=frozen.context_ref,
            ),
            proposal_llm_tokens=proposal_llm_tokens,
            proposal_wall_seconds=proposal_wall_seconds,
        )
        return (
            replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            ),
            overlay.override_ref,
        )

    def _with_terminal_feedback_overlay(
        self,
        *,
        app: FoundryApplication,
        frozen: _FrozenDiagnosticDescendant,
    ) -> tuple[_FrozenDiagnosticDescendant, ArtifactRef]:
        overlay = _apply_diagnostic_terminal_feedback_overlay(
            app=app,
            source=_ProposalEnvelopeOverlaySource(
                graph=frozen.graph,
                manifest=frozen.manifest,
                manifest_ref=frozen.manifest_ref,
                definition=frozen.definition,
                context_ref=frozen.context_ref,
            ),
            implementation_suffix=self._TERMINAL_FEEDBACK_IMPLEMENTATION_SUFFIX,
        )
        return (
            replace(
                frozen,
                graph=overlay.graph,
                manifest=overlay.manifest,
                manifest_ref=overlay.manifest_ref,
                definition=overlay.definition,
            ),
            overlay.override_ref,
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_descendant"
        )

    @staticmethod
    def _resolve_manifest_revision(
        *,
        app: FoundryApplication,
        revision_id: str,
    ) -> ArtifactRef:
        """Resolve one CLI-safe manifest revision without accepting an Artifact blob."""

        if not isinstance(revision_id, str) or not revision_id.startswith("sha256:"):
            raise TestNodeError(
                "test_descendant_manifest_selector_invalid",
                "the descendant manifest selector must be one sha256 WorkGraph manifest revision",
            )
        matches = tuple(
            ref for ref in app.artifacts.list_revisions() if ref.revision_id == revision_id
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_descendant_manifest_selector_missing",
                "the selected WorkGraph manifest revision is not retained in this diagnostic state",
            )
        manifest_ref = matches[0]
        if manifest_ref.artifact_type != "control.work_graph_manifest":
            raise TestNodeError(
                "test_descendant_manifest_selector_invalid",
                "the descendant manifest selector must reference one frozen WorkGraph manifest",
            )
        return manifest_ref

    @staticmethod
    def _require_final_epoch_diagnostic_anchor(
        *,
        app: FoundryApplication,
        manifest: WorkGraphManifest,
        manifest_ref: ArtifactRef,
        definition: WorkDefinition,
        predecessor_commit_refs: tuple[ArtifactRef, ...],
        anchor: _FinalEpochDiagnosticAnchor,
    ) -> None:
        """Prove the one non-direct diagnostic lineage allowed for final roots.

        A final graph has two independent initial Agent boundaries.  Its
        implementation planner consumes ModelingBoundary rather than
        VerifierPlan, even though the final epoch itself was frozen from the
        exact retained VerifierPlan closure.  In a marked diagnostic copy that
        anchor can be either the current normal/releasable Plan or a
        diagnostic/non-releasable Plan.  Requiring a direct diagnostic parent
        here would make the normal-Plan route unreachable; accepting an
        arbitrary ancestor would make the normal descendant guard meaningless.
        This method permits only the exact final-epoch relation that
        ``DiagnosticFinalNodeRunner`` has just frozen in the same marked copy.
        """

        if (
            manifest_ref != anchor.final_manifest_ref
            or manifest.mode != "production"
            or not manifest.releasable
            or (
                definition.coordinate.component,
                definition.coordinate.stage,
            )
            not in {
                ("build", "implementation_plan"),
                ("verifier", "verifier_intent_batch"),
            }
        ):
            raise TestNodeError(
                "test_final_node_diagnostic_anchor_invalid",
                "final-epoch diagnostic ancestry may authorize only one exact initial final node",
            )
        try:
            final_epoch = app.artifacts.get_json(anchor.final_epoch_ref, WorkGraphEpoch)
            design_epoch = app.artifacts.get_json(anchor.design_epoch_ref, WorkGraphEpoch)
            verifier_commit = app.artifacts.get_json(
                anchor.verifier_plan_commit_ref,
                WorkCommit,
            )
        except ValueError as exc:
            raise TestNodeError(
                "test_final_node_diagnostic_anchor_invalid",
                (
                    "final-epoch diagnostic ancestry is missing one durable epoch or "
                    "VerifierPlan commit"
                ),
            ) from exc
        if (
            final_epoch.epoch_kind != "final"
            or final_epoch.scope_id != definition.coordinate.scope_id
            or final_epoch.manifest_ref != manifest_ref
            or final_epoch.predecessor_epoch_ref != anchor.design_epoch_ref
            or design_epoch.epoch_kind != "design"
            or design_epoch.scope_id != definition.coordinate.scope_id
            or design_epoch.context_ref != final_epoch.context_ref
            or anchor.verifier_plan_commit_ref not in final_epoch.retained_commit_refs
            or not set(predecessor_commit_refs).issubset(final_epoch.retained_commit_refs)
            or verifier_commit.coordinate != anchor.verifier_plan_coordinate
            or verifier_commit.definition_digest != anchor.verifier_plan_definition_digest
            or not DiagnosticDescendantNodeRunner._is_eligible_final_epoch_verifier_plan_anchor(
                verifier_commit
            )
        ):
            raise TestNodeError(
                "test_final_node_diagnostic_anchor_invalid",
                ("final-epoch ancestry does not retain the exact eligible VerifierPlan closure"),
            )
        verifier_head = app.controller.work_control.read_head(anchor.verifier_plan_coordinate)
        if (
            verifier_head is None
            or verifier_head.status != "committed"
            or verifier_head.commit_ref != anchor.verifier_plan_commit_ref
            or verifier_head.definition_digest != anchor.verifier_plan_definition_digest
        ):
            raise TestNodeError(
                "test_final_node_diagnostic_anchor_invalid",
                "the diagnostic VerifierPlan commit is no longer the active final-epoch anchor",
            )

    @staticmethod
    def _is_eligible_final_epoch_verifier_plan_anchor(commit: WorkCommit) -> bool:
        """Accept only the two provenance modes final-node derivation proves.

        ``require_active_or_diagnostic_commit`` has already verified the
        exact acceptance/input closure.  This additional predicate excludes
        malformed mixed modes while allowing both an active normal Plan and a
        diagnostic Plan to anchor one non-releasable diagnostic final epoch.
        """

        return (commit.diagnostic_only and not commit.releasable) or (
            not commit.diagnostic_only and commit.releasable
        )

    @classmethod
    def _load_frozen_descendant(
        cls,
        *,
        app: FoundryApplication,
        scope_id: str,
        supplied: str,
        required_manifest_ref: ArtifactRef | None = None,
        infrastructure_retry: bool = False,
        diagnostic_terminal_feedback: bool = False,
        allow_authorized_repair_regeneration: bool = False,
        allow_authorized_repair_execution: bool = False,
        semantic_repair_mode: Literal["authorize", "execute"] | None = None,
        final_epoch_diagnostic_anchor: _FinalEpochDiagnosticAnchor | None = None,
    ) -> _FrozenDiagnosticDescendant:
        expected = cls._parse_coordinate(supplied)
        if (
            required_manifest_ref is not None
            and required_manifest_ref.artifact_type != "control.work_graph_manifest"
        ):
            raise TestNodeError(
                "test_descendant_manifest_selector_invalid",
                "the descendant manifest selector must reference one frozen WorkGraph manifest",
            )
        heads = app.controller.work_control
        candidates: list[_FrozenDiagnosticDescendant] = []
        saw_target = False
        saw_retry_target = False
        saw_retry_nonfailed_terminal = False
        saw_terminal_feedback_already_instrumented = False
        saw_terminal_feedback_missing_source = False
        saw_terminal_feedback_definition_mismatch = False
        saw_terminal_feedback_nonfailed = False
        saw_authorized_repair_requires_refresh = False
        saw_conflicting_live_head = False
        saw_conflicting_work_identity = False
        saw_missing_ancestor = False
        missing_ancestor_details: set[str] = set()
        saw_without_diagnostic_parent = False
        manifest_refs = (
            (required_manifest_ref,)
            if required_manifest_ref is not None
            else app.artifacts.list_revisions()
        )
        for manifest_ref in manifest_refs:
            if manifest_ref.artifact_type != "control.work_graph_manifest":
                continue
            try:
                manifest = app.artifacts.get_json(manifest_ref, WorkGraphManifest)
            except ValueError:
                continue
            if manifest.scope_id != scope_id:
                continue
            try:
                graph = TestNodeRunner._reconstruct_graph(app.controller.artifacts, manifest)
                rendered = graph.manifest(
                    topology_id=manifest.topology_id,
                    external_root_refs=manifest.external_root_refs,
                )
            except (WorkResumeError, ValueError):
                continue
            if rendered != manifest:
                continue
            matches = tuple(
                definition
                for definition in graph.definitions
                if cls._coordinate_matches(
                    definition.coordinate, supplied=supplied, expected=expected
                )
            )
            if not matches:
                continue
            saw_target = True
            if len(matches) != 1:
                continue
            definition = matches[0]
            existing_head = heads.read_head(definition.coordinate)
            stale_head: WorkControlHead | None = None
            infrastructure_retry_head: WorkControlHead | None = None
            authorized_repair_head: WorkControlHead | None = None
            if infrastructure_retry:
                # A retry is deliberately stricter than a fresh descendant.
                # It may consume only the exact immutable definition that
                # failed in this marked copy; a historical/stale manifest
                # must not be silently selected and rebudgeted as a retry.
                if existing_head is None:
                    continue
                if existing_head.definition_digest != definition.definition_digest:
                    continue
                saw_retry_target = True
                if existing_head.work_id != definition.work_id:
                    saw_conflicting_work_identity = True
                    continue
                if existing_head.status != "failed":
                    saw_retry_nonfailed_terminal = True
                    continue
                infrastructure_retry_head = existing_head
            elif diagnostic_terminal_feedback:
                # A feedback-only observation is meaningful only for the
                # exact failed definition whose ordinary scene was too weak.
                # Do not silently select a retained historical topology with
                # the same public coordinate but a different input, budget,
                # or implementation revision.
                if existing_head is None:
                    saw_terminal_feedback_missing_source = True
                    continue
                if existing_head.definition_digest != definition.definition_digest:
                    saw_terminal_feedback_definition_mismatch = True
                    continue
                if existing_head.work_id != definition.work_id:
                    saw_conflicting_work_identity = True
                    continue
                if existing_head.status != "failed":
                    saw_terminal_feedback_nonfailed = True
                    continue
                if cls._terminal_feedback_instrumented(definition):
                    saw_terminal_feedback_already_instrumented = True
                    continue
                stale_head = existing_head
            elif existing_head is not None:
                if existing_head.status == "repair_authorized":
                    if existing_head.work_id != definition.work_id:
                        saw_conflicting_work_identity = True
                        continue
                    if allow_authorized_repair_execution:
                        authorized_repair_head = existing_head
                    elif not allow_authorized_repair_regeneration:
                        saw_authorized_repair_requires_refresh = True
                        continue
                    else:
                        # The caller will freeze a changed current implementation
                        # below.  Scheduler then observes this old authority as
                        # stale and opens a fresh regeneration; it must never bind
                        # the old repair action or private continuation.
                        stale_head = existing_head
                elif existing_head.definition_digest == definition.definition_digest:
                    if existing_head.work_id != definition.work_id:
                        saw_conflicting_work_identity = True
                        continue
                    if existing_head.status not in cls._SETTLED_HEAD_STATUSES:
                        saw_conflicting_live_head = True
                        continue
                    # A child definition can be byte-identical while a newly
                    # committed parent changes its typed input closure.  Do
                    # not call that an already-captured node yet: Scheduler
                    # distinguishes an exact commit from a stale one using
                    # the resolved input fingerprint.
                    stale_head = existing_head
                elif existing_head.work_id != definition.work_id:
                    saw_conflicting_work_identity = True
                    continue
                elif existing_head.status not in cls._SETTLED_HEAD_STATUSES:
                    saw_conflicting_live_head = True
                    continue
                else:
                    # The Scheduler owns this exact stale-definition transition:
                    # its WorkControlRuntime records the old attempt as the new
                    # attempt's parent and invalidating evidence.  The diagnostic
                    # runner must therefore not reject a new frozen topology just
                    # because the coordinate key is reused.
                    stale_head = existing_head
            contexts = tuple(
                ref
                for ref in manifest.external_root_refs
                if ref.artifact_type == "control.generation_context"
            )
            if len(contexts) != 1:
                continue
            context_ref = contexts[0]
            try:
                context = app.artifacts.get_json(context_ref, GenerationContext)
            except ValueError:
                continue
            predecessor_heads = tuple(
                heads.read_head(coordinate) for coordinate in definition.dependency_coordinates
            )
            unresolved_parents = tuple(
                (
                    TestNodeRunner._coordinate_scene_label(parent_coordinate),
                    "missing"
                    if parent_head is None
                    else (
                        parent_head.status
                        if parent_head.commit_ref is not None
                        else f"{parent_head.status}:missing_commit"
                    ),
                )
                for parent_coordinate, parent_head in zip(
                    definition.dependency_coordinates,
                    predecessor_heads,
                    strict=True,
                )
                if parent_head is None
                or parent_head.status != "committed"
                or parent_head.commit_ref is None
            )
            if unresolved_parents:
                missing_ancestor_details.add(
                    ", ".join(f"{label}={state}" for label, state in unresolved_parents)
                )
                saw_missing_ancestor = True
                continue
            resolved_heads = cast(tuple[WorkControlHead, ...], predecessor_heads)
            predecessor_commits = tuple(
                app.artifacts.get_json(head.commit_ref, WorkCommit)
                for head in resolved_heads
                if head.commit_ref is not None
            )
            has_direct_diagnostic_parent = any(
                commit.diagnostic_only and not commit.releasable for commit in predecessor_commits
            )
            predecessor_commit_refs = tuple(
                cast(ArtifactRef, head.commit_ref) for head in resolved_heads
            )
            direct_diagnostic_repair_target = cls._is_direct_diagnostic_repair_target(
                app=app,
                definition=definition,
                head=existing_head,
                mode=semantic_repair_mode,
            )
            direct_diagnostic_infrastructure_retry_target = (
                infrastructure_retry
                and cls._is_direct_diagnostic_infrastructure_retry_target(
                    app=app,
                    definition=definition,
                    head=existing_head,
                )
            )
            # A revised authoring surface has two narrow ways to start a fresh
            # diagnostic first attempt without replaying an old private model
            # session: a settled Candidate can carry a causal downstream route
            # that becomes one new Scheduler action, or this exact node can
            # have a locally observed diagnostic validation failure.  The
            # latter is intentionally a *fresh first attempt*, not an action:
            # it lets a Code Agent's newly implemented own build/test/debug
            # loop run before any outer Scheduler repair is considered.
            direct_diagnostic_runtime_refresh_target = allow_authorized_repair_regeneration and (
                cls._causal_feedback_for_runtime_implementation_refresh(
                    app=app,
                    stale_head=existing_head,
                    definition=definition,
                )
                is not None
                or cls._is_direct_diagnostic_local_runtime_refresh_target(
                    app=app,
                    head=existing_head,
                    definition=definition,
                )
            )
            if (
                not has_direct_diagnostic_parent
                and not direct_diagnostic_repair_target
                and not direct_diagnostic_infrastructure_retry_target
                and not direct_diagnostic_runtime_refresh_target
            ):
                if final_epoch_diagnostic_anchor is None:
                    saw_without_diagnostic_parent = True
                    continue
                cls._require_final_epoch_diagnostic_anchor(
                    app=app,
                    manifest=manifest,
                    manifest_ref=manifest_ref,
                    definition=definition,
                    predecessor_commit_refs=predecessor_commit_refs,
                    anchor=final_epoch_diagnostic_anchor,
                )
            # Input resolution must use the same marked diagnostic runtime as
            # the eventual dispatch.  Constructing an opt-in Scheduler here
            # without that runtime is deliberately rejected by its authority
            # guard; ``run`` resolves the exact closure immediately after it
            # has constructed the one bounded runtime for this definition.
            candidates.append(
                _FrozenDiagnosticDescendant(
                    graph=graph,
                    manifest=manifest,
                    manifest_ref=manifest_ref,
                    definition=definition,
                    context=context,
                    context_ref=context_ref,
                    predecessor_attempt_refs=tuple(head.attempt_ref for head in resolved_heads),
                    predecessor_commit_refs=predecessor_commit_refs,
                    stale_head=stale_head,
                    infrastructure_retry_head=infrastructure_retry_head,
                    authorized_repair_head=authorized_repair_head,
                )
            )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            revisions = ", ".join(
                sorted(candidate.manifest_ref.revision_id for candidate in candidates)
            )
            raise TestNodeError(
                "test_descendant_target_ambiguous",
                (
                    f"target resolves to {len(candidates)} immutable diagnostic manifests; "
                    "coordinate-only selection is unsafe when historical and derived topologies "
                    "reuse a public boundary. Select one with --manifest-revision: "
                    f"{revisions}"
                ),
            )
        if infrastructure_retry:
            if saw_retry_nonfailed_terminal:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_not_failed",
                    (
                        "the exact diagnostic target is terminal but not one failed "
                        "infrastructure result"
                    ),
                )
            if saw_retry_target:
                raise TestNodeError(
                    "test_descendant_infrastructure_retry_target_invalid",
                    "the exact failed target lacks one committed diagnostic ancestor closure",
                )
            raise TestNodeError(
                "test_descendant_infrastructure_retry_target_missing",
                (
                    "the marked diagnostic source has no failed target with the exact frozen "
                    "definition required for an infrastructure retry"
                ),
            )
        if saw_terminal_feedback_already_instrumented:
            raise TestNodeError(
                "test_descendant_terminal_feedback_already_captured",
                (
                    "the exact diagnostic definition already enables local terminal feedback; "
                    "read its sidecar or make another explicit causal change"
                ),
            )
        if diagnostic_terminal_feedback and saw_terminal_feedback_missing_source:
            raise TestNodeError(
                "test_descendant_terminal_feedback_source_missing",
                "local terminal feedback requires one retained failed target head",
            )
        if diagnostic_terminal_feedback and saw_terminal_feedback_definition_mismatch:
            raise TestNodeError(
                "test_descendant_terminal_feedback_source_definition_mismatch",
                (
                    "the selected manifest does not contain the exact failed definition; "
                    "select the manifest revision bound to the failed target head"
                ),
            )
        if diagnostic_terminal_feedback and saw_terminal_feedback_nonfailed:
            raise TestNodeError(
                "test_descendant_terminal_feedback_source_not_failed",
                "local terminal feedback may be collected only from one failed target head",
            )
        if saw_authorized_repair_requires_refresh:
            raise TestNodeError(
                "test_descendant_authorized_repair_requires_runtime_refresh",
                (
                    "the exact target has Scheduler-authorized semantic repair for its "
                    "current frozen definition; use the normal repair path, or freeze one "
                    "--refresh-current-implementation definition refresh after a causal runtime "
                    "Prompt, Runtime Skill, leaf, or validator change"
                ),
            )
        if saw_conflicting_live_head:
            raise TestNodeError(
                "test_descendant_stale_head_running",
                "a conflicting predecessor topology is still running and cannot be superseded",
            )
        if saw_conflicting_work_identity:
            raise TestNodeError(
                "test_descendant_stale_work_identity_conflict",
                "a conflicting head reuses the coordinate with a different work identity",
            )
        if saw_missing_ancestor:
            details = "; ".join(sorted(missing_ancestor_details))
            raise TestNodeError(
                "test_descendant_ancestor_closure_missing",
                (
                    "the frozen descendant lacks one exact committed parent closure"
                    + (f": {details}" if details else "")
                ),
            )
        if saw_without_diagnostic_parent:
            raise TestNodeError(
                "test_descendant_no_diagnostic_parent",
                "the unheaded target must directly consume one diagnostic commit",
            )
        if saw_target:
            raise TestNodeError(
                "test_descendant_manifest_invalid",
                "target exists but has no unique immutable diagnostic manifest closure",
            )
        raise TestNodeError(
            "test_descendant_coordinate_not_frozen",
            (
                "target is not an unheaded definition in the captured WorkGraph manifest; use "
                "its exact hash, coordinate JSON, component|stage|artifact_slot|group_id|shard_id, "
                "or the component.stage.artifact_slot label shown by observe"
            ),
        )

    @staticmethod
    def _assert_retry_envelope_matches(
        *,
        source_definition: WorkDefinition,
        requested_llm_tokens: int | None,
        requested_wall_seconds: float | None,
    ) -> None:
        """Forbid a parameter change from masquerading as an infrastructure retry.

        The original diagnostic attempt is evidence for one exact frozen
        definition.  An operator can omit the envelope flags or restate their
        values (for an auditable command line), but cannot alter them here.
        A changed envelope must go through the ordinary fresh-definition
        diagnostic path instead.
        """

        budget = source_definition.proposal_policy.budget
        if requested_llm_tokens is not None and (
            isinstance(requested_llm_tokens, bool)
            or not isinstance(requested_llm_tokens, int)
            or requested_llm_tokens != budget.llm_tokens
        ):
            raise TestNodeError(
                "test_descendant_infrastructure_retry_envelope_mismatch",
                "an infrastructure retry must retain the frozen proposal token budget",
            )
        if requested_wall_seconds is not None and (
            isinstance(requested_wall_seconds, bool)
            or not isinstance(requested_wall_seconds, (int, float))
            or not math.isfinite(requested_wall_seconds)
            or float(requested_wall_seconds) != budget.wall_seconds
        ):
            raise TestNodeError(
                "test_descendant_infrastructure_retry_envelope_mismatch",
                "an infrastructure retry must retain the frozen proposal wall budget",
            )

    @classmethod
    def _terminal_feedback_instrumented(cls, definition: WorkDefinition) -> bool:
        """Identify a prior feedback-only diagnostic definition without heuristics."""

        return definition.proposal_policy.implementation_revision_id.endswith(
            cls._TERMINAL_FEEDBACK_IMPLEMENTATION_SUFFIX
        )

    @staticmethod
    def _causal_feedback_for_runtime_implementation_refresh(
        *,
        app: FoundryApplication,
        stale_head: WorkControlHead | None,
        definition: WorkDefinition,
    ) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef] | None:
        """Return one exact causal feedback route eligible for a new authoring revision.

        A current Prompt or Agent-only Runtime Skill revision cannot dispatch
        an old RepairAction: that action is tied to the old implementation
        identity. A *settled* Candidate can nevertheless carry a previous
        causal action whose downstream report, evaluation, route, snapshot,
        and frozen input closure remain independently auditable. In that
        narrow case the refreshed definition receives a new RepairAction from
        that same source evidence. Pending actions and ordinary local repairs
        intentionally fall back to fresh regeneration.
        """

        if (
            stale_head is None
            or stale_head.status not in _TERMINAL_WORK_HEAD_STATUSES
            or stale_head.repair_action_ref is None
        ):
            return None
        try:
            action = app.artifacts.get_json(stale_head.repair_action_ref, RepairAction)
            attempt = app.artifacts.get_json(stale_head.attempt_ref, WorkAttempt)
        except (ValueError, TypeError):
            return None
        if (
            action.decision != "local_correction"
            or action.reason_code != "causal_downstream_failure"
            or action.current_coordinate != definition.coordinate
            or action.target_coordinate != definition.coordinate
            # The retained action seeded the *previous* Candidate snapshot;
            # this settled head is the result of that correction. The new
            # authoring revision will seed a distinct action from this current
            # output, so equating the old seed to the current snapshot would
            # wrongly reject the ordinary r1 -> r2 repair shape.
            or attempt.repair_action_ref != stale_head.repair_action_ref
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
            or stale_head.input_fingerprint
            != app.controller.work_control.input_fingerprint(attempt.input_refs)
        ):
            return None
        reports = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.validation_report"
        )
        evaluations = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.feedback_evaluation"
        )
        routes = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.parent_repair_route"
        )
        if len(reports) != 1 or len(evaluations) != 1 or len(routes) != 1:
            return None
        try:
            report = app.artifacts.get_json(reports[0], ValidationReport)
            evaluation = app.artifacts.get_json(evaluations[0], FeedbackEvaluation)
            route = app.artifacts.get_json(routes[0], ParentRepairRoute)
        except (ValueError, TypeError):
            return None
        if (
            report.status != "failed"
            or not report.repair_actionable
            or not report.diagnostic_only
            or report.releasable
            or evaluation.status != "failed"
            or evaluation.validation_report_ref != reports[0]
            or evaluation.coordinate != report.coordinate
            or evaluation.attempt_id != report.attempt_id
            or not evaluation.diagnostic_only
            or evaluation.releasable
            or route.target_coordinate != definition.coordinate
            or route.source_coordinate != report.coordinate
            or route.source_attempt_id != report.attempt_id
            or route.issue_identities != tuple(issue.normalized_identity for issue in report.issues)
        ):
            return None
        return evaluations[0], reports[0], routes[0]

    @staticmethod
    def _is_direct_diagnostic_local_runtime_refresh_target(
        *,
        app: FoundryApplication,
        head: WorkControlHead | None,
        definition: WorkDefinition,
    ) -> bool:
        """Allow one changed authoring revision to restart its own failed node.

        This is deliberately narrower than a generic failed-node retry.  It
        requires a fully marked diagnostic ``ValidationReport.status=failed``,
        the exact persisted feedback evaluation and input closure, no retained
        Scheduler RepairAction, and a real implementation or validator
        revision change.  The later overlay starts a new first attempt with no
        repair authority or private continuation, so the Code Agent can apply
        its newly implemented bounded pre-commit self-check loop.
        """

        if (
            head is None
            or head.status != "failed"
            or head.repair_action_ref is not None
            or head.work_id != definition.work_id
            or head.definition_digest != definition.definition_digest
        ):
            return False
        revisions = current_runtime_revisions_for_definition(definition)
        if revisions is None:
            return False
        implementation_revision_id, validator_revision_id = revisions
        if (
            implementation_revision_id == definition.proposal_policy.implementation_revision_id
            and validator_revision_id == definition.validation_policy.validator_revision_id
        ):
            return False
        attempt_ref = head.attempt_ref
        evaluation_ref = head.evaluation_ref
        if attempt_ref is None or evaluation_ref is None:
            return False
        try:
            attempt = app.artifacts.get_json(attempt_ref, WorkAttempt)
            if attempt.validation_report_ref is None:
                return False
            report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
            evaluation = app.artifacts.get_json(evaluation_ref, FeedbackEvaluation)
        except (TypeError, ValueError):
            return False
        return (
            attempt.coordinate == definition.coordinate
            and attempt.definition_digest == definition.definition_digest
            and attempt.repair_action_ref is None
            and head.input_fingerprint
            == app.controller.work_control.input_fingerprint(attempt.input_refs)
            and report.status == "failed"
            and report.coordinate == definition.coordinate
            and report.attempt_id == attempt.attempt_id
            and report.diagnostic_only
            and not report.releasable
            and evaluation.status == "failed"
            and evaluation.coordinate == definition.coordinate
            and evaluation.attempt_id == attempt.attempt_id
            and evaluation.validation_report_ref == attempt.validation_report_ref
            and evaluation.diagnostic_only
            and not evaluation.releasable
        )

    @staticmethod
    def _parse_coordinate(supplied: str) -> WorkCoordinate | None:
        if not supplied.startswith("{"):
            return None
        try:
            return WorkCoordinate.model_validate(json.loads(supplied))
        except (ValueError, TypeError):
            raise TestNodeError(
                "test_descendant_coordinate_invalid",
                "target coordinate must be an exact coordinate key or JSON object",
            ) from None

    @staticmethod
    def _is_direct_diagnostic_repair_target(
        *,
        app: FoundryApplication,
        definition: WorkDefinition,
        head: WorkControlHead | None,
        mode: Literal["authorize", "execute"] | None,
    ) -> bool:
        """Allow one exact diagnostic repair that has no diagnostic parent.

        ``test-node`` deliberately reruns one captured node whose committed
        parents usually come from the source graph.  When that isolated turn
        reaches an actionable semantic failure, it is already fully marked
        diagnostic-only; requiring one of its *parents* to be diagnostic would
        make the explicit authorize/execute repair path unreachable.  This is
        not a general relaxation for descendants: only the exact failed
        initial target, or an already-authorized target whose action is bound
        to one diagnostic downstream ``ParentRepairRoute``, may use this
        bridge.  The ordinary runtime revalidates the complete report,
        evaluation, input closure, and RepairAction before mutating a head or
        dispatching a model turn.
        """

        if head is None or mode is None:
            return False
        expected_status = "failed" if mode == "authorize" else "repair_authorized"
        if (
            head.status != expected_status
            or head.work_id != definition.work_id
            or head.definition_digest != definition.definition_digest
            or head.acceptance_digest != definition.acceptance_digest
            or head.evaluation_ref is None
            or (mode == "authorize" and head.repair_action_ref is not None)
            or (mode == "execute" and head.repair_action_ref is None)
        ):
            return False
        try:
            attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        except (ValueError, TypeError):
            return False
        if attempt.validation_report_ref is not None:
            try:
                report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
            except (ValueError, TypeError):
                report = None
            if (
                attempt.status == "failed"
                and attempt.diagnostic_only
                and not attempt.releasable
                and report is not None
                and report.attempt_id == attempt.attempt_id
                and report.coordinate == definition.coordinate
                and report.diagnostic_only
                and not report.releasable
                and head.input_fingerprint
                == app.controller.work_control.input_fingerprint(attempt.input_refs)
            ):
                return True

        # A causal Candidate repair begins from a successful, non-diagnostic
        # Candidate attempt.  Its diagnostic authority is instead the exact
        # failed downstream report that the Scheduler routed back to this
        # Candidate.  Requiring the historical Candidate attempt itself to be
        # diagnostic makes that repair route unexecutable, despite its complete
        # causal evidence closure.  Accept only the one fully-bound shape the
        # Scheduler creates in ``authorize_causal_repair``.
        if mode != "execute" or head.repair_action_ref is None:
            return False
        try:
            action = app.artifacts.get_json(head.repair_action_ref, RepairAction)
        except (ValueError, TypeError):
            return False
        if (
            action.decision != "local_correction"
            or action.reason_code != "causal_downstream_failure"
            or action.current_coordinate != definition.coordinate
            or action.target_coordinate != definition.coordinate
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint
            != app.controller.work_control.input_fingerprint(attempt.input_refs)
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.repair_seed_attempt_ref != head.attempt_ref
            or action.repair_seed_output_refs != attempt.output_refs
        ):
            return False
        reports = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.validation_report"
        )
        evaluations = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.feedback_evaluation"
        )
        routes = tuple(
            ref
            for ref in action.causal_evidence_refs
            if ref.artifact_type == "control.parent_repair_route"
        )
        if len(reports) != 1 or len(evaluations) != 1 or len(routes) != 1:
            return False
        try:
            source_report = app.artifacts.get_json(reports[0], ValidationReport)
            source_evaluation = app.artifacts.get_json(evaluations[0], FeedbackEvaluation)
            route = app.artifacts.get_json(routes[0], ParentRepairRoute)
        except (ValueError, TypeError):
            return False
        return (
            source_report.status == "failed"
            and source_report.repair_actionable
            and source_report.diagnostic_only
            and not source_report.releasable
            and source_evaluation.status == "failed"
            and source_evaluation.validation_report_ref == reports[0]
            and source_evaluation.coordinate == source_report.coordinate
            and source_evaluation.attempt_id == source_report.attempt_id
            and source_evaluation.diagnostic_only
            and not source_evaluation.releasable
            and route.target_coordinate == definition.coordinate
            and route.source_coordinate == source_report.coordinate
            and route.source_attempt_id == source_report.attempt_id
            and route.issue_identities
            == tuple(issue.normalized_identity for issue in source_report.issues)
        )

    @staticmethod
    def _is_direct_diagnostic_infrastructure_retry_target(
        *,
        app: FoundryApplication,
        definition: WorkDefinition,
        head: WorkControlHead | None,
    ) -> bool:
        """Allow one classified retry of the failed initial diagnostic target.

        ``test-node`` normally copies ordinary captured parent commits, so an
        infrastructure failure of the one node it reran has no diagnostic
        *parent*. It is nevertheless itself a marked diagnostic terminal with
        an exact definition/input closure. Requiring a diagnostic ancestor here
        made the documented same-route retry unreachable after an authorized
        semantic repair lost transport. The runtime still revalidates the
        retryable report and policy before dispatch; this only admits that
        exact initial-node bridge.
        """

        if (
            head is None
            or head.status != "failed"
            or head.work_id != definition.work_id
            or head.definition_digest != definition.definition_digest
            or head.acceptance_digest != definition.acceptance_digest
            or head.evaluation_ref is None
        ):
            return False
        try:
            attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
            report = (
                app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
                if attempt.validation_report_ref is not None
                else None
            )
        except (ValueError, TypeError):
            return False
        return (
            attempt.status == "failed"
            and attempt.diagnostic_only
            and not attempt.releasable
            and report is not None
            and report.attempt_id == attempt.attempt_id
            and report.coordinate == definition.coordinate
            and report.diagnostic_only
            and not report.releasable
            and report.infrastructure_retryable
            and head.input_fingerprint
            == app.controller.work_control.input_fingerprint(attempt.input_refs)
        )

    @staticmethod
    def _coordinate_matches(
        coordinate: WorkCoordinate,
        *,
        supplied: str,
        expected: WorkCoordinate | None,
    ) -> bool:
        return (
            coordinate.coordinate_key == supplied
            or TestNodeRunner._coordinate_label(coordinate) == supplied
            or TestNodeRunner._coordinate_scene_label(coordinate) == supplied
            or (expected is not None and coordinate == expected)
        )


@dataclass(frozen=True, slots=True)
class _ProposalEnvelopeOverlaySource:
    """Frozen graph facts shared by captured-node and descendant diagnostics."""

    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    context_ref: ArtifactRef


@dataclass(frozen=True, slots=True)
class _ProposalEnvelopeOverlay:
    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    definition: WorkDefinition
    override_ref: ArtifactRef


def _freeze_diagnostic_overlay_epoch(
    *,
    app: FoundryApplication,
    source: _ProposalEnvelopeOverlaySource,
    overlay_graph: GenerationWorkGraph,
    topology_id: str,
    override_ref: ArtifactRef,
    invalid_epoch_code: str,
    label: str,
) -> tuple[WorkGraphManifest, ArtifactRef]:
    """Freeze one overlay on the exact epoch family that supplied the node.

    A diagnostic proposal budget or feedback capture changes no semantic input,
    topology, or acceptance policy.  It still needs a fresh retained epoch so
    the altered definition is observable.  Normal Direct execution can leave
    a target in bootstrap, world, plan-derived Design, legacy Design, or final
    graphs; treating only the last two as testable would silently hide the
    earlier real Agent boundaries.
    """

    _source_epoch_ref, source_epoch = TestNodeRunner._epoch_for_manifest(
        app.controller.artifacts,
        source.manifest_ref,
    )
    if source_epoch.context_ref != source.context_ref:
        raise TestNodeError(
            invalid_epoch_code,
            f"{label} requires an epoch bound to the captured GenerationContext",
        )
    epoch_runtime = WorkGraphEpochRuntime(
        artifacts=app.controller.artifacts,
        heads=app.controller.work_control,
    )
    try:
        if source_epoch.epoch_kind == "bootstrap":
            if source_epoch.predecessor_epoch_ref is not None:
                raise TestNodeError(
                    invalid_epoch_code,
                    f"{label} bootstrap epoch unexpectedly has a predecessor",
                )
            manifest, manifest_ref, _epoch, _epoch_ref = epoch_runtime.freeze_bootstrap(
                context_ref=source.context_ref,
                graph=overlay_graph,
                topology_id=topology_id,
                allow_diagnostic_predecessors=True,
                diagnostic_overlay_ref=override_ref,
            )
        else:
            predecessor_ref = source_epoch.predecessor_epoch_ref
            if predecessor_ref is None:
                raise TestNodeError(
                    invalid_epoch_code,
                    f"{label} {source_epoch.epoch_kind} epoch lacks its required predecessor",
                )
            predecessor = app.controller.artifacts.get_json(predecessor_ref, WorkGraphEpoch)
            if source_epoch.epoch_kind == "world":
                if predecessor.epoch_kind == "bootstrap":
                    manifest, manifest_ref, _epoch, _epoch_ref = epoch_runtime.freeze_world(
                        context_ref=source.context_ref,
                        bootstrap_epoch_ref=predecessor_ref,
                        graph=overlay_graph,
                        topology_id=topology_id,
                        allow_diagnostic_predecessors=True,
                        diagnostic_overlay_ref=override_ref,
                    )
                elif predecessor.epoch_kind == "design":
                    manifest, manifest_ref, _epoch, _epoch_ref = (
                        epoch_runtime.freeze_diagnostic_world_from_legacy_design(
                            context_ref=source.context_ref,
                            legacy_design_epoch_ref=predecessor_ref,
                            legacy_manifest_ref=predecessor.manifest_ref,
                            graph=overlay_graph,
                            topology_id=topology_id,
                            diagnostic_overlay_ref=override_ref,
                        )
                    )
                else:
                    raise TestNodeError(
                        invalid_epoch_code,
                        f"{label} World epoch has an unsupported predecessor kind",
                    )
            elif source_epoch.epoch_kind == "design":
                if predecessor.epoch_kind == "bootstrap":
                    manifest, manifest_ref, _epoch, _epoch_ref = epoch_runtime.freeze_design(
                        context_ref=source.context_ref,
                        bootstrap_epoch_ref=predecessor_ref,
                        graph=overlay_graph,
                        topology_id=topology_id,
                        allow_diagnostic_predecessors=True,
                        diagnostic_overlay_ref=override_ref,
                    )
                elif predecessor.epoch_kind == "world":
                    manifest, manifest_ref, _epoch, _epoch_ref = (
                        epoch_runtime.freeze_design_from_world(
                            context_ref=source.context_ref,
                            world_epoch_ref=predecessor_ref,
                            graph=overlay_graph,
                            topology_id=topology_id,
                            allow_diagnostic_predecessors=True,
                            diagnostic_overlay_ref=override_ref,
                        )
                    )
                else:
                    raise TestNodeError(
                        invalid_epoch_code,
                        f"{label} Design epoch has an unsupported predecessor kind",
                    )
            elif source_epoch.epoch_kind == "final":
                if predecessor.epoch_kind != "design":
                    raise TestNodeError(
                        invalid_epoch_code,
                        f"{label} final epoch does not retain a Design predecessor",
                    )
                manifest, manifest_ref, _epoch, _epoch_ref = epoch_runtime.freeze_final(
                    context_ref=source.context_ref,
                    design_epoch_ref=predecessor_ref,
                    graph=overlay_graph,
                    topology_id=topology_id,
                    allow_diagnostic_predecessors=True,
                    diagnostic_overlay_ref=override_ref,
                )
            else:  # pragma: no cover - WorkGraphEpoch has a closed epoch kind
                raise TestNodeError(
                    invalid_epoch_code,
                    f"{label} has an unsupported graph epoch kind",
                )
    except (WorkGraphError, WorkResumeError, WorkControlStoreError) as exc:
        remediation = _final_epoch_rederivation_required(
            source_epoch_kind=source_epoch.epoch_kind,
            error=exc,
            label=label,
        )
        if remediation is not None:
            raise remediation from exc
        raise TestNodeError(
            invalid_epoch_code,
            f"{label} could not freeze one retained graph epoch",
        ) from exc
    if manifest.external_root_refs != source.manifest.external_root_refs:
        raise TestNodeError(
            invalid_epoch_code,
            f"{label} changed the frozen external input root",
        )
    return manifest, manifest_ref


def _final_epoch_rederivation_required(
    *,
    source_epoch_kind: str,
    error: Exception,
    label: str,
) -> TestNodeError | None:
    """Route a stale final graph to the only truthful diagnostic successor.

    ``test-descendant-node`` can dispatch an unheaded node from a graph that
    is already frozen.  It cannot silently rebuild final topology after a
    diagnostic Design predecessor (notably ``VerifierPlan``) has changed.
    The normal epoch check correctly rejects that stale closure; this helper
    keeps the safe coordinate and routes the project-execution Agent to the
    dedicated final-epoch harness instead of leaving an opaque epoch error.
    """

    prefix = "predecessor WorkCommit is not active for the next graph: "
    if (
        source_epoch_kind != "final"
        or not isinstance(error, WorkResumeError)
        or not str(error).startswith(prefix)
    ):
        return None
    predecessor = str(error).removeprefix(prefix)
    return TestNodeError(
        "test_node_final_epoch_rederivation_required",
        (
            f"{label} cannot retain the frozen final graph because its committed "
            f"diagnostic predecessor {predecessor} no longer matches that graph's "
            "definition, acceptance, or input closure. No model invocation was started. "
            "Freeze a new diagnostic final graph from the committed Design and "
            "VerifierPlan closure with test-final-node, then dispatch the selected "
            "initial final node."
        ),
    )


@dataclass(frozen=True, slots=True)
class _DiagnosticRuntimeProfileChange:
    """One explicit model-only diagnostic profile delta."""

    config: FoundryConfig
    requested: bool
    source_model: str
    model: str


def _diagnostic_runtime_profile_change(
    config: FoundryConfig,
    *,
    diagnostic_model: str | None,
    diagnostic_source_model: str | None,
) -> _DiagnosticRuntimeProfileChange:
    """Materialize exactly one named runtime-profile hypothesis.

    A model switch is not a harmless configuration edit: it changes the real
    Agent execution surface, so an isolated node result must retain the
    exact source and target identity.
    """

    if (diagnostic_model is None) != (diagnostic_source_model is None):
        raise TestNodeError(
            "test_node_runtime_profile_model_pair_missing",
            "diagnostic model changes require both source and target model identifiers",
        )
    source_model = config.agent.model
    model = config.agent.model
    if diagnostic_model is not None and diagnostic_source_model is not None:
        source_model = diagnostic_source_model.strip()
        model = diagnostic_model.strip()
        if not source_model or not model:
            raise TestNodeError(
                "test_node_runtime_profile_model_invalid",
                "diagnostic source and target model identifiers must be non-empty",
            )
    model_changed = source_model != model
    requested = diagnostic_model is not None
    if requested and not model_changed:
        raise TestNodeError(
            "test_node_runtime_profile_not_changed",
            "diagnostic runtime-profile experiment must change the model identity",
        )

    updates: dict[str, object] = {}
    if model_changed:
        updates["model"] = model
        # A profile experiment promotes its target only for this diagnostic
        # definition.  Preserve the former primary immediately after it:
        # should the promoted route later end in a typed transient, the normal
        # recovery policy may return to the configured baseline before trying
        # the remaining declared routes.  The experiment itself consumes no
        # fallback; this only keeps its future policy route truthful instead
        # of silently dropping the source model from the route graph.
        updates["fallback_models"] = _promoted_diagnostic_fallback_models(
            routes=config.agent.model_routes,
            source_model=source_model,
            promoted_model=model,
        )
    diagnostic_config = (
        config
        if not updates
        else config.model_copy(update={"agent": config.agent.model_copy(update=updates)})
    )
    return _DiagnosticRuntimeProfileChange(
        config=diagnostic_config,
        requested=requested,
        source_model=source_model,
        model=model,
    )


def _promoted_diagnostic_fallback_models(
    *,
    routes: tuple[str, ...],
    source_model: str,
    promoted_model: str,
) -> tuple[str, ...]:
    """Keep one profile experiment's bounded recovery order intact.

    ``routes`` is the proven configuration order before the experiment.  A
    profile diagnostic changes the active Agent model, but it must not erase
    the prior primary from a later policy-authorized recovery.  The returned
    tuple excludes ``promoted_model`` because it becomes the new primary.
    Unknown source identities deliberately are not invented into the route:
    the later frozen-lineage check will retain its existing fail-closed
    behavior for a malformed experiment.
    """

    ordered = [promoted_model]
    if source_model in routes:
        ordered.append(source_model)
    ordered.extend(
        candidate for candidate in routes if candidate not in {promoted_model, source_model}
    )
    return tuple(dict.fromkeys(ordered))[1:]


_DIAGNOSTIC_OVERLAY_ARTIFACT_TYPES = frozenset(
    {
        "control.diagnostic_proposal_budget_override",
        "control.diagnostic_terminal_feedback_override",
        "control.diagnostic_runtime_implementation_override",
        "control.diagnostic_runtime_profile_override",
    }
)


def _inherited_diagnostic_runtime_profile_config(
    *,
    app: FoundryApplication,
    manifest_ref: ArtifactRef,
    definition: WorkDefinition,
    config: FoundryConfig,
) -> tuple[FoundryConfig, tuple[DiagnosticRuntimeProfileOverride, ...]]:
    """Recover a target's frozen diagnostic model lineage.

    A profile-only test-node overlay writes a new WorkDefinition plus a
    diagnostic overlay artifact.  The definition alone intentionally carries
    no model or endpoint data, so a later authorize/execute repair must walk
    the retained overlay chain rather than silently reverting to the caller's
    default model.  Only profile overlays for this exact target affect its
    runtime; overlays for a different node remain graph provenance, not a
    global configuration change.
    """

    overrides = _diagnostic_runtime_profile_overrides_for_target(
        app=app,
        manifest_ref=manifest_ref,
        definition=definition,
    )
    effective = config
    applied: list[DiagnosticRuntimeProfileOverride] = []
    for override in overrides:
        if effective.agent.model != override.source_model:
            # Older diagnostic roots can contain an immediately repeated
            # profile overlay: both records name the same source/target
            # model pair, and the later record starts from the earlier
            # overlay's implementation revision.  That is a provenance
            # duplication, not a second model experiment.  It must retain
            # the already-frozen effective model for an authorized repair;
            # every other discontinuity remains a hard error.
            previous = applied[-1] if applied else None
            if (
                previous is not None
                and effective.agent.model == override.model
                and override.source_model == previous.source_model
                and override.model == previous.model
                and override.source_implementation_revision_id
                == previous.implementation_revision_id
            ):
                applied.append(override)
                continue
            raise TestNodeError(
                "test_descendant_runtime_profile_inheritance_mismatch",
                (
                    "the frozen diagnostic profile lineage does not begin at the configured "
                    "model; start a fresh profile experiment instead of mixing "
                    "profile evidence"
                ),
            )
        model_changed = override.model != override.source_model
        if not model_changed:
            raise TestNodeError(
                "test_descendant_runtime_profile_inheritance_invalid",
                "a frozen diagnostic profile overlay must change the model identity",
            )
        agent_updates: dict[str, object] = {}
        if model_changed:
            agent_updates["model"] = override.model
            agent_updates["fallback_models"] = _promoted_diagnostic_fallback_models(
                routes=effective.agent.model_routes,
                source_model=override.source_model,
                promoted_model=override.model,
            )
        effective = effective.model_copy(
            update={"agent": effective.agent.model_copy(update=agent_updates)}
        )
        applied.append(override)
    return effective, tuple(applied)


def _diagnostic_runtime_profile_overrides_for_target(
    *,
    app: FoundryApplication,
    manifest_ref: ArtifactRef,
    definition: WorkDefinition,
) -> tuple[DiagnosticRuntimeProfileOverride, ...]:
    """Return target-local profile overlays from oldest to newest.

    Every diagnostic overlay retains its source manifest.  Walking that chain
    also survives an intervening budget, feedback, or implementation overlay,
    so a model experiment cannot disappear merely because another independent
    diagnostic observation was recorded later.
    """

    current_manifest_ref = manifest_ref
    seen_manifest_revisions: set[str] = set()
    target_overrides: list[DiagnosticRuntimeProfileOverride] = []
    while True:
        if current_manifest_ref.revision_id in seen_manifest_revisions:
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_cycle",
                "diagnostic overlay manifest ancestry contains a cycle",
            )
        seen_manifest_revisions.add(current_manifest_ref.revision_id)
        try:
            overlay_refs = tuple(
                ref
                for ref in app.controller.artifacts.dependencies(current_manifest_ref)
                if ref.artifact_type in _DIAGNOSTIC_OVERLAY_ARTIFACT_TYPES
            )
        except (OSError, ValueError) as exc:
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_unreadable",
                "diagnostic overlay ancestry cannot be read from the frozen manifest",
            ) from exc
        if not overlay_refs:
            break
        if len(overlay_refs) != 1:
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_ambiguous",
                "one frozen diagnostic manifest must retain at most one direct overlay",
            )
        overlay_ref = overlay_refs[0]
        try:
            payload = app.controller.artifacts.get_json(overlay_ref)
            source_manifest_ref = ArtifactRef.model_validate(payload["source_manifest_ref"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_invalid",
                "a diagnostic overlay does not retain one valid source manifest reference",
            ) from exc
        if source_manifest_ref.artifact_type != "control.work_graph_manifest":
            raise TestNodeError(
                "test_descendant_runtime_profile_overlay_invalid",
                "a diagnostic overlay source must be one frozen WorkGraph manifest",
            )
        if overlay_ref.artifact_type == "control.diagnostic_runtime_profile_override":
            try:
                override = app.controller.artifacts.get_json(
                    overlay_ref,
                    DiagnosticRuntimeProfileOverride,
                )
            except ValueError as exc:
                raise TestNodeError(
                    "test_descendant_runtime_profile_overlay_invalid",
                    "the frozen diagnostic runtime-profile override is malformed",
                ) from exc
            if override.target_coordinate == definition.coordinate:
                target_overrides.append(override)
        current_manifest_ref = source_manifest_ref
    target_overrides.reverse()
    return tuple(target_overrides)


def _apply_diagnostic_runtime_profile_overlay(
    *,
    app: FoundryApplication,
    source: _ProposalEnvelopeOverlaySource,
    source_model: str,
    model: str,
) -> _ProposalEnvelopeOverlay:
    """Freeze one profile-only experiment as a fresh diagnostic definition.

    Profile selection is an Agent proposal provenance surface, not an opaque
    retry knob. The dedicated record preserves exactly one before/after model
    model delta; the fresh definition changes only its implementation provenance
    while the overlay epoch retains the exact semantic input closure.
    """

    definition = source.definition
    policy = definition.proposal_policy
    if policy.executor != "agent":
        raise TestNodeError(
            "test_node_runtime_profile_target_not_agent",
            "a diagnostic runtime-profile override is valid only for one Agent target",
        )
    model_changed = source_model != model
    if not model_changed:
        raise TestNodeError(
            "test_node_runtime_profile_not_isolated",
            "diagnostic runtime-profile overlay must change the model identity",
        )
    overlay_digest = sha256_digest(
        canonical_json_bytes(
            {
                "source_manifest_ref": source.manifest_ref.revision_id,
                "target_coordinate": definition.coordinate.model_dump(mode="json"),
                "source_definition_digest": definition.definition_digest,
                "source_implementation_revision_id": policy.implementation_revision_id,
                "source_model": source_model,
                "model": model,
            }
        )
    ).removeprefix("sha256:")[:24]
    implementation_revision_id = (
        f"{policy.implementation_revision_id}.diagnostic-profile-model-{overlay_digest}.v1"
    )
    profile_definition = definition.model_copy(
        update={
            "proposal_policy": policy.model_copy(
                update={"implementation_revision_id": implementation_revision_id}
            )
        }
    )
    expected_payload = definition.model_dump(mode="json")
    expected_payload["proposal_policy"]["implementation_revision_id"] = implementation_revision_id
    if profile_definition.model_dump(mode="json") != expected_payload:
        raise TestNodeError(
            "test_node_runtime_profile_not_isolated",
            "diagnostic runtime-profile overlay changed more than its implementation provenance",
        )
    overlay_definitions = tuple(
        profile_definition if item.coordinate == definition.coordinate else item
        for item in source.graph.definitions
    )
    try:
        overlay_graph = GenerationWorkGraph.compile(
            overlay_definitions,
            mode=source.graph.mode,
            required_terminal_coordinates=source.graph.required_terminal_coordinates,
            groups=source.graph.groups,
            milestones=source.graph.milestones,
        )
    except WorkGraphError as exc:
        raise TestNodeError(
            "test_node_runtime_profile_overlay_invalid",
            "diagnostic runtime-profile overlay could not preserve the frozen graph topology",
        ) from exc
    unchanged = tuple(
        item for item in source.graph.definitions if item.coordinate != definition.coordinate
    )
    overlay_unchanged = tuple(
        item for item in overlay_graph.definitions if item.coordinate != definition.coordinate
    )
    if overlay_unchanged != unchanged:
        raise TestNodeError(
            "test_node_runtime_profile_not_isolated",
            "diagnostic runtime-profile overlay changed another frozen WorkDefinition",
        )
    override = DiagnosticRuntimeProfileOverride(
        source_manifest_ref=source.manifest_ref,
        target_coordinate=definition.coordinate,
        source_definition_digest=definition.definition_digest,
        source_implementation_revision_id=policy.implementation_revision_id,
        implementation_revision_id=implementation_revision_id,
        source_model=source_model,
        model=model,
    )
    override_ref = app.controller.artifacts.put_json(
        artifact_id=f"diagnostic-runtime-profile-override:{overlay_digest}",
        artifact_type="control.diagnostic_runtime_profile_override",
        value=override,
        dependencies=(source.manifest_ref,),
    )
    manifest, manifest_ref = _freeze_diagnostic_overlay_epoch(
        app=app,
        source=source,
        overlay_graph=overlay_graph,
        topology_id=f"topology:diagnostic-runtime-profile:{overlay_digest}",
        override_ref=override_ref,
        invalid_epoch_code="test_node_runtime_profile_epoch_invalid",
        label="diagnostic runtime-profile override",
    )
    return _ProposalEnvelopeOverlay(
        graph=overlay_graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        definition=profile_definition,
        override_ref=override_ref,
    )


def _apply_diagnostic_proposal_envelope_overlay(
    *,
    app: FoundryApplication,
    config: FoundryConfig,
    source: _ProposalEnvelopeOverlaySource,
    proposal_llm_tokens: int | None,
    proposal_wall_seconds: float | None,
) -> _ProposalEnvelopeOverlay:
    """Freeze one larger finite envelope without changing semantic Agent inputs.

    This path serves both an unheaded descendant and a captured terminal node.
    The latter archives its old head before dispatching the new graph, so the
    changed definition is visible evidence rather than a retry under the old
    definition.
    """

    definition = source.definition
    policy = definition.proposal_policy
    source_budget = policy.budget
    proposal_llm_tokens, proposal_wall_seconds = DiagnosticDescendantNodeRunner._proposal_envelope(
        source_definition=definition,
        requested_llm_tokens=proposal_llm_tokens,
        requested_wall_seconds=proposal_wall_seconds,
        diagnostic_budget=config.generation_budget,
    )
    budget_updates: dict[str, int | float | None] = {
        "llm_tokens": proposal_llm_tokens,
        "wall_seconds": proposal_wall_seconds,
    }
    if source_budget.build_seconds > 0:
        budget_updates["build_seconds"] = proposal_wall_seconds
    if source_budget.first_progress_seconds is not None:
        budget_updates["first_progress_seconds"] = proposal_wall_seconds
    if source_budget.first_write_seconds is not None:
        budget_updates["first_write_seconds"] = proposal_wall_seconds
    proposal_budget = source_budget.model_copy(update=budget_updates)
    rebudgeted_definition = definition.model_copy(
        update={"proposal_policy": policy.model_copy(update={"budget": proposal_budget})}
    )
    source_payload = definition.model_dump(mode="json")
    expected_payload = definition.model_dump(mode="json")
    expected_payload["proposal_policy"]["budget"] = proposal_budget.model_dump(mode="json")
    if rebudgeted_definition.model_dump(mode="json") != expected_payload:
        raise TestNodeError(
            "test_diagnostic_proposal_envelope_not_isolated",
            "diagnostic proposal envelope changed more than its declared budget dimensions",
        )
    if source_payload["proposal_policy"]["budget"] != source_budget.model_dump(mode="json"):
        raise TestNodeError(
            "test_diagnostic_proposal_budget_source_invalid",
            "frozen source proposal budget does not match its WorkDefinition",
        )
    overlay_definitions = tuple(
        rebudgeted_definition if item.coordinate == definition.coordinate else item
        for item in source.graph.definitions
    )
    try:
        overlay_graph = GenerationWorkGraph.compile(
            overlay_definitions,
            mode=source.graph.mode,
            required_terminal_coordinates=source.graph.required_terminal_coordinates,
            groups=source.graph.groups,
            milestones=source.graph.milestones,
        )
    except WorkGraphError as exc:
        raise TestNodeError(
            "test_diagnostic_proposal_envelope_overlay_invalid",
            "diagnostic proposal envelope could not preserve the frozen graph topology",
        ) from exc
    unchanged = tuple(
        item for item in source.graph.definitions if item.coordinate != definition.coordinate
    )
    overlay_unchanged = tuple(
        item for item in overlay_graph.definitions if item.coordinate != definition.coordinate
    )
    if overlay_unchanged != unchanged:
        raise TestNodeError(
            "test_diagnostic_proposal_envelope_not_isolated",
            "diagnostic proposal envelope changed another frozen WorkDefinition",
        )

    overlay_digest = sha256_digest(
        canonical_json_bytes(
            {
                "source_manifest_ref": source.manifest_ref.revision_id,
                "target_coordinate": definition.coordinate.model_dump(mode="json"),
                "source_proposal_budget": source_budget.model_dump(mode="json"),
                "proposal_budget": proposal_budget.model_dump(mode="json"),
            }
        )
    ).removeprefix("sha256:")[:24]
    override = DiagnosticProposalBudgetOverride(
        source_manifest_ref=source.manifest_ref,
        target_coordinate=definition.coordinate,
        source_definition_digest=definition.definition_digest,
        source_proposal_budget=source_budget,
        proposal_budget=proposal_budget,
        diagnostic_generation_budget=config.generation_budget,
    )
    override_ref = app.controller.artifacts.put_json(
        artifact_id=f"diagnostic-proposal-budget-override:{overlay_digest}",
        artifact_type="control.diagnostic_proposal_budget_override",
        value=override,
        dependencies=(source.manifest_ref,),
    )
    manifest, manifest_ref = _freeze_diagnostic_overlay_epoch(
        app=app,
        source=source,
        overlay_graph=overlay_graph,
        topology_id=f"topology:diagnostic-proposal-budget:{overlay_digest}",
        override_ref=override_ref,
        invalid_epoch_code="test_diagnostic_proposal_envelope_epoch_invalid",
        label="diagnostic proposal envelope overlay",
    )
    return _ProposalEnvelopeOverlay(
        graph=overlay_graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        definition=rebudgeted_definition,
        override_ref=override_ref,
    )


def _apply_diagnostic_runtime_implementation_overlay(
    *,
    app: FoundryApplication,
    source: _ProposalEnvelopeOverlaySource,
) -> _ProposalEnvelopeOverlay:
    """Freeze one current leaf/Skill/compiler revision without altering inputs.

    Unlike a replay, this makes the causal runtime change durable in a fresh
    diagnostic graph.  The narrow registry in ``work_graph`` owns which
    coordinates may be refreshed and which source/Skill/validator files make
    up their current revisions; this harness only verifies that all other
    frozen definition fields remain byte-for-byte unchanged.
    """

    definition = source.definition
    revisions = current_runtime_revisions_for_definition(definition)
    if revisions is None:
        raise TestNodeError(
            "test_node_runtime_implementation_unavailable",
            (
                "the selected frozen node has no registered current runtime revision; "
                "do not relabel an unchanged diagnostic run as a new implementation"
            ),
        )
    implementation_revision_id, validator_revision_id = revisions
    policy = definition.proposal_policy
    validation = definition.validation_policy
    refreshed_budget = _current_runtime_operation_budget(app=app, source=source)
    if (
        policy.implementation_revision_id == implementation_revision_id
        and validation.validator_revision_id == validator_revision_id
        and policy.budget == refreshed_budget
    ):
        raise TestNodeError(
            "test_node_runtime_implementation_not_changed",
            (
                "the selected node already records the current runtime implementation and "
                "validator revisions and framework-owned operation budget"
            ),
        )
    refreshed_definition = definition.model_copy(
        update={
            "proposal_policy": policy.model_copy(
                update={
                    "implementation_revision_id": implementation_revision_id,
                    "budget": refreshed_budget,
                }
            ),
            "validation_policy": validation.model_copy(
                update={"validator_revision_id": validator_revision_id}
            ),
        }
    )
    source_payload = definition.model_dump(mode="json")
    expected_payload = definition.model_dump(mode="json")
    expected_payload["proposal_policy"]["implementation_revision_id"] = implementation_revision_id
    expected_payload["proposal_policy"]["budget"] = refreshed_budget.model_dump(mode="json")
    expected_payload["validation_policy"]["validator_revision_id"] = validator_revision_id
    if refreshed_definition.model_dump(mode="json") != expected_payload:
        raise TestNodeError(
            "test_node_runtime_implementation_not_isolated",
            (
                "the current runtime implementation refresh changed more than its declared "
                "implementation, validator, and framework-owned budget revisions"
            ),
        )
    if (
        source_payload["proposal_policy"]["implementation_revision_id"]
        != policy.implementation_revision_id
        or source_payload["validation_policy"]["validator_revision_id"]
        != validation.validator_revision_id
    ):
        raise TestNodeError(
            "test_node_runtime_implementation_source_invalid",
            "the frozen source definition does not match its recorded runtime revisions",
        )
    overlay_definitions = tuple(
        refreshed_definition if item.coordinate == definition.coordinate else item
        for item in source.graph.definitions
    )
    try:
        overlay_graph = GenerationWorkGraph.compile(
            overlay_definitions,
            mode=source.graph.mode,
            required_terminal_coordinates=source.graph.required_terminal_coordinates,
            groups=source.graph.groups,
            milestones=source.graph.milestones,
        )
    except WorkGraphError as exc:
        raise TestNodeError(
            "test_node_runtime_implementation_overlay_invalid",
            "current runtime implementation refresh could not preserve the frozen graph topology",
        ) from exc
    unchanged = tuple(
        item for item in source.graph.definitions if item.coordinate != definition.coordinate
    )
    overlay_unchanged = tuple(
        item for item in overlay_graph.definitions if item.coordinate != definition.coordinate
    )
    if overlay_unchanged != unchanged:
        raise TestNodeError(
            "test_node_runtime_implementation_not_isolated",
            "current runtime implementation refresh changed another frozen WorkDefinition",
        )
    overlay_digest = sha256_digest(
        canonical_json_bytes(
            {
                "source_manifest_ref": source.manifest_ref.revision_id,
                "target_coordinate": definition.coordinate.model_dump(mode="json"),
                "source_definition_digest": definition.definition_digest,
                "source_implementation_revision_id": policy.implementation_revision_id,
                "implementation_revision_id": implementation_revision_id,
                "source_validator_revision_id": validation.validator_revision_id,
                "validator_revision_id": validator_revision_id,
                "source_proposal_budget": policy.budget.model_dump(mode="json"),
                "proposal_budget": refreshed_budget.model_dump(mode="json"),
            }
        )
    ).removeprefix("sha256:")[:24]
    override = DiagnosticRuntimeImplementationOverride(
        source_manifest_ref=source.manifest_ref,
        target_coordinate=definition.coordinate,
        source_definition_digest=definition.definition_digest,
        source_implementation_revision_id=policy.implementation_revision_id,
        implementation_revision_id=implementation_revision_id,
        source_validator_revision_id=validation.validator_revision_id,
        validator_revision_id=validator_revision_id,
        source_proposal_budget=policy.budget,
        proposal_budget=refreshed_budget,
    )
    override_ref = app.controller.artifacts.put_json(
        artifact_id=f"diagnostic-runtime-implementation-override:{overlay_digest}",
        artifact_type="control.diagnostic_runtime_implementation_override",
        value=override,
        dependencies=(source.manifest_ref,),
    )
    manifest, manifest_ref = _freeze_diagnostic_overlay_epoch(
        app=app,
        source=source,
        overlay_graph=overlay_graph,
        topology_id=f"topology:diagnostic-runtime-implementation:{overlay_digest}",
        override_ref=override_ref,
        invalid_epoch_code="test_node_runtime_implementation_epoch_invalid",
        label="current runtime implementation refresh",
    )
    return _ProposalEnvelopeOverlay(
        graph=overlay_graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        definition=refreshed_definition,
        override_ref=override_ref,
    )


def _current_runtime_operation_budget(
    *,
    app: FoundryApplication,
    source: _ProposalEnvelopeOverlaySource,
) -> OperationBudget:
    """Re-derive a code leaf's framework-owned budget from its committed input.

    A current implementation refresh normally changes only revision labels.
    CandidateBuild and Integration also own framework mechanics that changed
    with their implementation: CandidateBuild reserves its bounded Code-Agent
    development correction; Integration derives its probe reservation from
    the exact committed Candidate's Design.  Neither case changes user
    semantics, the model profile, or the immutable input closure.
    """

    definition = source.definition
    if (
        definition.coordinate.component == "build"
        and definition.coordinate.stage == "candidate_build"
        and definition.coordinate.artifact_slot == "environment_candidate"
        and definition.proposal_policy.executor == "agent"
        and definition.proposal_policy.output_contract_id == "contract:environment-candidate.v3"
    ):
        return definition.proposal_policy.budget.model_copy(
            update={"agent_turns": CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS}
        )
    if (definition.coordinate.component, definition.coordinate.stage) != (
        "integration",
        "runtime_integration",
    ):
        return definition.proposal_policy.budget
    if definition.proposal_policy.executor != "code" or len(definition.dependency_coordinates) != 1:
        raise TestNodeError(
            "test_node_runtime_budget_integration_definition_invalid",
            "Integration budget rederivation requires one code-owned Candidate parent",
        )

    candidate_definition = source.graph.require(definition.dependency_coordinates[0])
    if (candidate_definition.coordinate.component, candidate_definition.coordinate.stage) != (
        "build",
        "candidate_build",
    ):
        raise TestNodeError(
            "test_node_runtime_budget_candidate_parent_invalid",
            "Integration budget rederivation requires its direct CandidateBuild parent",
        )
    candidate_head = app.controller.work_control.read_head(candidate_definition.coordinate)
    if candidate_head is None or candidate_head.status != "committed":
        raise TestNodeError(
            "test_node_runtime_budget_candidate_closure_missing",
            "Integration budget rederivation requires one committed exact Candidate parent",
        )
    candidate_attempt = app.controller.artifacts.get_json(candidate_head.attempt_ref, WorkAttempt)
    candidate_commit = app.controller.work_control.require_active_or_diagnostic_commit(
        definition=candidate_definition,
        input_refs=candidate_attempt.input_refs,
        artifacts=app.controller.artifacts,
    )
    if candidate_commit is None:
        raise TestNodeError(
            "test_node_runtime_budget_candidate_closure_stale",
            "Integration budget rederivation cannot reuse a stale Candidate definition",
        )
    committed_candidate, _candidate_commit_ref = candidate_commit
    candidate_refs = tuple(
        ref
        for ref in committed_candidate.consumer_refs
        if ref.artifact_type == "build.environment_candidate"
    )
    if len(candidate_refs) != 1:
        raise TestNodeError(
            "test_node_runtime_budget_candidate_artifact_missing",
            "the committed Candidate parent must disclose one EnvironmentCandidate artifact",
        )
    candidate = app.controller.artifacts.get_json(candidate_refs[0], EnvironmentCandidate)
    design = app.controller.artifacts.get_json(candidate.design_ref, EnvironmentDesign)
    requirements = integration_budget_requirements(design)
    return definition.proposal_policy.budget.model_copy(
        update={
            "llm_tokens": requirements.llm_tokens,
            "agent_turns": requirements.agent_turns,
            "tool_calls": requirements.tool_calls,
            "evaluation_episodes": requirements.evaluation_episodes,
        }
    )


def _apply_diagnostic_terminal_feedback_overlay(
    *,
    app: FoundryApplication,
    source: _ProposalEnvelopeOverlaySource,
    implementation_suffix: str,
) -> _ProposalEnvelopeOverlay:
    """Freeze one feedback-only diagnostic definition for an Agent terminal.

    Unlike an infrastructure retry, this is an explicit new observation
    experiment.  It leaves the Agent's semantic input, prompt, Runtime Skill,
    capability profile, output contract, and every budget field untouched;
    only the leaf implementation revision declares the local terminal-feedback
    instrumentation that will be present during the next real call.
    """

    definition = source.definition
    policy = definition.proposal_policy
    if policy.executor != "agent":
        raise TestNodeError(
            "test_descendant_terminal_feedback_target_not_agent",
            "local terminal-feedback capture is valid only for one Agent target",
        )
    if policy.implementation_revision_id.endswith(implementation_suffix):
        raise TestNodeError(
            "test_descendant_terminal_feedback_already_captured",
            "the frozen definition already declares local terminal-feedback capture",
        )
    implementation_revision_id = f"{policy.implementation_revision_id}{implementation_suffix}"
    feedback_definition = definition.model_copy(
        update={
            "proposal_policy": policy.model_copy(
                update={"implementation_revision_id": implementation_revision_id}
            )
        }
    )
    source_payload = definition.model_dump(mode="json")
    expected_payload = definition.model_dump(mode="json")
    expected_payload["proposal_policy"]["implementation_revision_id"] = implementation_revision_id
    if feedback_definition.model_dump(mode="json") != expected_payload:
        raise TestNodeError(
            "test_diagnostic_terminal_feedback_not_isolated",
            "local terminal-feedback capture changed more than its implementation revision",
        )
    if (
        source_payload["proposal_policy"]["implementation_revision_id"]
        != policy.implementation_revision_id
    ):
        raise TestNodeError(
            "test_diagnostic_terminal_feedback_source_invalid",
            "frozen source implementation revision does not match its WorkDefinition",
        )
    overlay_definitions = tuple(
        feedback_definition if item.coordinate == definition.coordinate else item
        for item in source.graph.definitions
    )
    try:
        overlay_graph = GenerationWorkGraph.compile(
            overlay_definitions,
            mode=source.graph.mode,
            required_terminal_coordinates=source.graph.required_terminal_coordinates,
            groups=source.graph.groups,
            milestones=source.graph.milestones,
        )
    except WorkGraphError as exc:
        raise TestNodeError(
            "test_diagnostic_terminal_feedback_overlay_invalid",
            "local terminal-feedback capture could not preserve the frozen graph topology",
        ) from exc
    unchanged = tuple(
        item for item in source.graph.definitions if item.coordinate != definition.coordinate
    )
    overlay_unchanged = tuple(
        item for item in overlay_graph.definitions if item.coordinate != definition.coordinate
    )
    if overlay_unchanged != unchanged:
        raise TestNodeError(
            "test_diagnostic_terminal_feedback_not_isolated",
            "local terminal-feedback capture changed another frozen WorkDefinition",
        )

    overlay_digest = sha256_digest(
        canonical_json_bytes(
            {
                "source_manifest_ref": source.manifest_ref.revision_id,
                "target_coordinate": definition.coordinate.model_dump(mode="json"),
                "source_definition_digest": definition.definition_digest,
                "source_implementation_revision_id": policy.implementation_revision_id,
                "implementation_revision_id": implementation_revision_id,
            }
        )
    ).removeprefix("sha256:")[:24]
    override = DiagnosticTerminalFeedbackOverride(
        source_manifest_ref=source.manifest_ref,
        target_coordinate=definition.coordinate,
        source_definition_digest=definition.definition_digest,
        source_implementation_revision_id=policy.implementation_revision_id,
        implementation_revision_id=implementation_revision_id,
    )
    override_ref = app.controller.artifacts.put_json(
        artifact_id=f"diagnostic-terminal-feedback-override:{overlay_digest}",
        artifact_type="control.diagnostic_terminal_feedback_override",
        value=override,
        dependencies=(source.manifest_ref,),
    )
    manifest, manifest_ref = _freeze_diagnostic_overlay_epoch(
        app=app,
        source=source,
        overlay_graph=overlay_graph,
        topology_id=f"topology:diagnostic-terminal-feedback:{overlay_digest}",
        override_ref=override_ref,
        invalid_epoch_code="test_diagnostic_terminal_feedback_epoch_invalid",
        label="local terminal-feedback capture",
    )
    return _ProposalEnvelopeOverlay(
        graph=overlay_graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        definition=feedback_definition,
        override_ref=override_ref,
    )


class DiagnosticWorldPlanNodeResult(V2Contract):
    """One real CurriculumPlan call migrated from a legacy diagnostic graph.

    ``prepared_diagnostic_state_root`` is the intermediate marked copy where
    the immutable old closure was rebound into a new World epoch.  The nested
    descendant result names the second marked copy that actually dispatched
    the Plan.  Keeping both roots visible prevents this diagnostic migration
    from being mistaken for a normal Direct resume or a replayed result.
    """

    source_scope_id: str
    source_diagnostic_state_root: str
    prepared_diagnostic_state_root: str
    legacy_design_epoch_ref: ArtifactRef
    legacy_manifest_ref: ArtifactRef
    world_epoch_ref: ArtifactRef
    world_manifest_ref: ArtifactRef
    node: DiagnosticDescendantNodeResult
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticWorldPlanNodeRunner:
    """Prove one new CurriculumPlan above a committed legacy WorldRules node.

    The original diagnostic manifest predates task-family fan-out.  Replaying
    its broad ``TaskCurriculum`` turn would not prove the new topology, while
    regenerating WorldRules under changed code would discard the only credible
    frozen failure closure.  This narrow harness copies the marked source,
    preserves every committed historical definition and WorkCommit exactly,
    replaces only the unheaded legacy tail with one compact CurriculumPlan,
    then delegates the actual call to :class:`DiagnosticDescendantNodeRunner`.
    """

    _LEGACY_CURRICULUM_LABEL = "design|task_curriculum|task_curriculum||"
    _LEGACY_UNHEADED_TAIL = frozenset(
        {
            ("design", "task_curriculum"),
            ("design", "modeling_boundary"),
            ("verifier", "verifier_plan"),
        }
    )

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        required_manifest_revision: str | None = None,
    ) -> DiagnosticWorldPlanNodeResult:
        source_diagnostic_root = self._resolve_diagnostic_root()
        prepared_root = _prepare_diagnostic_clone(
            source_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            marker_error_code="test_world_plan_diagnostic_marker_failed",
            marker_message="fresh diagnostic World-plan state could not be marked",
        )

        # Keep the production composition root at the same lazy-import seam as
        # the other test-node runners; this command does not create an
        # alternate provider or executor path.
        from agent_world.app import build_application

        app = build_application(self.config.model_copy(update={"state_root": prepared_root}))
        required_manifest_ref = (
            DiagnosticDescendantNodeRunner._resolve_manifest_revision(  # noqa: SLF001
                app=app,
                revision_id=required_manifest_revision,
            )
            if required_manifest_revision is not None
            else None
        )
        legacy = DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=prepared_root,
        )._load_frozen_descendant(  # noqa: SLF001 - exact legacy manifest resolver
            app=app,
            scope_id=scope_id,
            supplied=self._LEGACY_CURRICULUM_LABEL,
            required_manifest_ref=required_manifest_ref,
        )
        if (legacy.definition.coordinate.component, legacy.definition.coordinate.stage) != (
            "design",
            "task_curriculum",
        ):
            raise TestNodeError(
                "test_world_plan_legacy_target_invalid",
                "legacy World-plan migration requires one unheaded TaskCurriculum target",
            )
        legacy_epoch_ref, legacy_epoch = TestNodeRunner._epoch_for_manifest(  # noqa: SLF001
            app.controller.artifacts,
            legacy.manifest_ref,
        )
        if legacy_epoch.epoch_kind != "design":
            raise TestNodeError(
                "test_world_plan_legacy_epoch_invalid",
                "legacy World-plan migration requires a frozen Design epoch",
            )

        try:
            curriculum_plan = curriculum_plan_work_definition(
                scope_id=scope_id,
                task_curriculum_template=legacy.definition,
                agent_wall_seconds=legacy.definition.proposal_policy.budget.wall_seconds,
                agent_token_limit=legacy.definition.proposal_policy.budget.llm_tokens,
            )
            retained_definitions: list[WorkDefinition] = []
            for definition in legacy.graph.definitions:
                stage_key = (definition.coordinate.component, definition.coordinate.stage)
                if definition.coordinate == legacy.definition.coordinate:
                    continue
                if stage_key in self._LEGACY_UNHEADED_TAIL:
                    continue
                if stage_key in {
                    ("design", "curriculum_plan"),
                    ("design", "task_requirement"),
                }:
                    raise WorkGraphError(
                        "legacy World-plan migration cannot replace an already fan-out-aware graph"
                    )
                retained_definitions.append(definition)
            world_graph = compile_world_work_graph(
                scope_id=scope_id,
                world_definitions=(*retained_definitions, curriculum_plan),
                strict_input_contracts=True,
            )
            (
                _world_manifest,
                world_manifest_ref,
                _world_epoch,
                world_epoch_ref,
            ) = WorkGraphEpochRuntime(
                artifacts=app.controller.artifacts,
                heads=app.controller.work_control,
            ).freeze_diagnostic_world_from_legacy_design(
                context_ref=legacy.context_ref,
                legacy_design_epoch_ref=legacy_epoch_ref,
                legacy_manifest_ref=legacy.manifest_ref,
                graph=world_graph,
                topology_id=(
                    "topology:test-world-plan:"
                    f"{scope_id}:{legacy.manifest.graph_digest.removeprefix('sha256:')[:16]}"
                ),
            )
        except (WorkGraphError, WorkResumeError, WorkControlStoreError) as exc:
            raise TestNodeError(
                "test_world_plan_topology_migration_failed",
                "the legacy diagnostic closure cannot safely freeze one CurriculumPlan boundary",
            ) from exc

        node = await DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=prepared_root,
            diagnostic_parent=self.diagnostic_parent,
            executor_factory=self.executor_factory,
        ).run(
            scope_id=scope_id,
            target_coordinate=curriculum_plan.coordinate.coordinate_key,
        )
        return DiagnosticWorldPlanNodeResult(
            source_scope_id=scope_id,
            source_diagnostic_state_root=str(source_diagnostic_root),
            prepared_diagnostic_state_root=str(prepared_root),
            legacy_design_epoch_ref=legacy_epoch_ref,
            legacy_manifest_ref=legacy.manifest_ref,
            world_epoch_ref=world_epoch_ref,
            world_manifest_ref=world_manifest_ref,
            node=node,
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_world_plan"
        )


@dataclass(frozen=True, slots=True)
class _CommittedDiagnosticWorldPlan:
    """Exact committed Plan closure from which task shards may be derived."""

    graph: GenerationWorkGraph
    manifest: WorkGraphManifest
    manifest_ref: ArtifactRef
    world_epoch_ref: ArtifactRef
    context_ref: ArtifactRef
    curriculum_plan_definition: WorkDefinition
    curriculum_plan_ref: ArtifactRef
    curriculum_plan: CurriculumPlanSourceDraft
    modeling_template: WorkDefinition


class DiagnosticTaskRequirementNodeResult(V2Contract):
    """One real plan-derived TaskRequirement call in a diagnostic Design epoch."""

    source_scope_id: str
    source_diagnostic_state_root: str
    prepared_diagnostic_state_root: str
    world_epoch_ref: ArtifactRef
    curriculum_plan_ref: ArtifactRef
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    task_type: str
    node: DiagnosticDescendantNodeResult
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticTaskRequirementNodeRunner:
    """Derive one plan-owned TaskRequirement coordinate and dispatch it once.

    ``CurriculumPlan`` is the fan-out boundary: a committed plan, rather than
    a CLI loop or model-selected target, determines the physical task-family
    members.  This diagnostic helper preserves that same rule.  Its first
    invocation freezes one non-releasable Design epoch with every plan-derived
    child.  Later invocations must reuse that exact epoch, so every committed
    task family remains in the same closure for the deterministic
    ``TaskCurriculum`` join.  It then asks
    :class:`DiagnosticDescendantNodeRunner` to execute exactly the selected
    previously-unheaded child.
    """

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        task_type: str,
    ) -> DiagnosticTaskRequirementNodeResult:
        source_diagnostic_root = self._resolve_diagnostic_root()
        prepared_root = _prepare_diagnostic_clone(
            source_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            marker_error_code="test_task_requirement_diagnostic_marker_failed",
            marker_message="fresh diagnostic TaskRequirement state could not be marked",
        )

        from agent_world.app import build_application

        app = build_application(self.config.model_copy(update={"state_root": prepared_root}))
        frozen = self._load_committed_world_plan(app=app, scope_id=scope_id)
        plan_derived: _PlanDerivedDiagnosticJoin | None = None
        try:
            plan_derived = DiagnosticTaskCurriculumJoinRunner._load_plan_derived_join(  # noqa: SLF001
                app=app,
                scope_id=scope_id,
                require_unheaded_join=False,
            )
        except TestNodeError as exc:
            if exc.code != "test_task_curriculum_join_design_missing":
                raise TestNodeError(
                    "test_task_requirement_plan_derived_design_invalid",
                    "the diagnostic CurriculumPlan has no unique reusable TaskRequirement fan-out",
                ) from exc

        if plan_derived is not None:
            if (
                plan_derived.curriculum_plan_definition.coordinate
                != frozen.curriculum_plan_definition.coordinate
                or plan_derived.curriculum_plan_definition.definition_digest
                != frozen.curriculum_plan_definition.definition_digest
            ):
                raise TestNodeError(
                    "test_task_requirement_plan_derived_design_mismatch",
                    (
                        "the reusable TaskRequirement fan-out is not bound to the committed "
                        "CurriculumPlan"
                    ),
                )
            target = self._task_requirement_coordinate(
                definitions=plan_derived.task_requirement_definitions,
                task_type=task_type,
            )
            design_manifest_ref = plan_derived.manifest_ref
            design_epoch_ref = plan_derived.design_epoch_ref
        else:
            try:
                design_definitions, modeling = derive_task_requirement_design_definitions(
                    scope_id=scope_id,
                    world_definitions=frozen.graph.definitions,
                    curriculum_plan_ref=frozen.curriculum_plan_ref,
                    curriculum_plan=frozen.curriculum_plan,
                    modeling_template=frozen.modeling_template,
                    agent_wall_seconds=frozen.curriculum_plan_definition.proposal_policy.budget.wall_seconds,
                    agent_token_limit=frozen.curriculum_plan_definition.proposal_policy.budget.llm_tokens,
                )
                target = self._task_requirement_coordinate(
                    definitions=design_definitions,
                    task_type=task_type,
                )
                verifier_plan = verifier_plan_work_definition(
                    scope_id=scope_id,
                    modeling_coordinate=modeling.coordinate,
                )
                design_graph = compile_design_work_graph(
                    scope_id=scope_id,
                    design_definitions=design_definitions,
                    modeling_definition=modeling,
                    verifier_plan_definition=verifier_plan,
                    strict_input_contracts=True,
                )
                (
                    _design_manifest,
                    design_manifest_ref,
                    _design_epoch,
                    design_epoch_ref,
                ) = WorkGraphEpochRuntime(
                    artifacts=app.controller.artifacts,
                    heads=app.controller.work_control,
                ).freeze_design_from_world(
                    context_ref=frozen.context_ref,
                    world_epoch_ref=frozen.world_epoch_ref,
                    graph=design_graph,
                    topology_id=(
                        "topology:test-task-requirement:"
                        f"{scope_id}:{frozen.curriculum_plan_ref.content_hash.removeprefix('sha256:')[:16]}"
                    ),
                    allow_diagnostic_predecessors=True,
                )
            except (WorkGraphError, WorkResumeError, WorkControlStoreError) as exc:
                raise TestNodeError(
                    "test_task_requirement_topology_derivation_failed",
                    (
                        "the committed CurriculumPlan cannot safely freeze one plan-derived "
                        "Design epoch"
                    ),
                ) from exc

        node = await DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=prepared_root,
            diagnostic_parent=self.diagnostic_parent,
            executor_factory=self.executor_factory,
        ).run(
            scope_id=scope_id,
            target_coordinate=target.coordinate_key,
            required_manifest_ref=design_manifest_ref,
        )
        return DiagnosticTaskRequirementNodeResult(
            source_scope_id=scope_id,
            source_diagnostic_state_root=str(source_diagnostic_root),
            prepared_diagnostic_state_root=str(prepared_root),
            world_epoch_ref=frozen.world_epoch_ref,
            curriculum_plan_ref=frozen.curriculum_plan_ref,
            design_epoch_ref=design_epoch_ref,
            design_manifest_ref=design_manifest_ref,
            task_type=task_type,
            node=node,
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_task_requirement"
        )

    @staticmethod
    def _task_requirement_coordinate(
        *,
        definitions: tuple[WorkDefinition, ...],
        task_type: str,
    ) -> WorkCoordinate:
        matches = tuple(
            definition.coordinate
            for definition in definitions
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage == "task_requirement"
                and definition.coordinate.shard_id == task_type
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_task_requirement_task_type_not_planned",
                "task_type must name exactly one task family in the committed CurriculumPlan",
            )
        return matches[0]

    @staticmethod
    def _one_consumer_ref(commit: WorkCommit, *, artifact_type: str) -> ArtifactRef:
        matches = tuple(ref for ref in commit.consumer_refs if ref.artifact_type == artifact_type)
        if len(matches) != 1:
            raise TestNodeError(
                "test_task_requirement_plan_output_invalid",
                "committed CurriculumPlan lacks one exact plan source Artifact",
            )
        return matches[0]

    @classmethod
    def _modeling_template_for_world_plan(
        cls,
        *,
        app: FoundryApplication,
        world_epoch_ref: ArtifactRef,
        world_epoch: WorkGraphEpoch,
        world_graph: GenerationWorkGraph,
        planner: WorkDefinition,
    ) -> WorkDefinition | None:
        """Recover the immutable Modeling template for one diagnostic Plan.

        Historical diagnostic migration produces a World epoch from a legacy
        Design predecessor, so its template is immediately available there.
        Native Direct topology instead has ``bootstrap -> world -> design``.
        A diagnostic budget/feedback overlay can replace only CurriculumPlan
        in that World graph before a new Design epoch exists.  In that case,
        reuse only the one retained native Design template whose predecessor
        shares the exact bootstrap and every non-Plan World definition.

        The template is framework topology, not model output: the new
        TaskRequirement graph is still derived from the newly committed Plan,
        and no historical TaskRequirement/TaskCurriculum output is adopted.
        """

        predecessor_ref = world_epoch.predecessor_epoch_ref
        if predecessor_ref is None:
            return None
        predecessor = app.artifacts.get_json(predecessor_ref, WorkGraphEpoch)
        if predecessor.context_ref != world_epoch.context_ref:
            return None
        if predecessor.epoch_kind == "design":
            legacy_manifest = app.artifacts.get_json(
                predecessor.manifest_ref,
                WorkGraphManifest,
            )
            legacy_graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen template
                app.controller.artifacts,
                legacy_manifest,
            )
            return cls._compatible_modeling_template(
                graph=legacy_graph,
                planner=planner,
            )
        if predecessor.epoch_kind != "bootstrap":
            return None

        templates_by_digest: dict[str, WorkDefinition] = {}
        for design_epoch_ref in app.artifacts.list_revisions():
            if design_epoch_ref.artifact_type != "control.work_graph_epoch":
                continue
            try:
                design_epoch = app.artifacts.get_json(design_epoch_ref, WorkGraphEpoch)
                if (
                    design_epoch.scope_id != world_epoch.scope_id
                    or design_epoch.epoch_kind != "design"
                    or design_epoch.context_ref != world_epoch.context_ref
                    or design_epoch.predecessor_epoch_ref is None
                ):
                    continue
                template_world = app.artifacts.get_json(
                    design_epoch.predecessor_epoch_ref,
                    WorkGraphEpoch,
                )
                if (
                    template_world.epoch_kind != "world"
                    or template_world.context_ref != world_epoch.context_ref
                    or template_world.predecessor_epoch_ref != predecessor_ref
                    or template_world.manifest_ref == world_epoch.manifest_ref
                ):
                    continue
                template_world_manifest = app.artifacts.get_json(
                    template_world.manifest_ref,
                    WorkGraphManifest,
                )
                template_world_graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001
                    app.controller.artifacts,
                    template_world_manifest,
                )
                if not cls._native_world_template_matches(
                    world_graph=world_graph,
                    template_world_graph=template_world_graph,
                ):
                    continue
                template_design_manifest = app.artifacts.get_json(
                    design_epoch.manifest_ref,
                    WorkGraphManifest,
                )
                template_design_graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001
                    app.controller.artifacts,
                    template_design_manifest,
                )
                modeling = cls._compatible_modeling_template(
                    graph=template_design_graph,
                    planner=planner,
                )
                if modeling is not None:
                    templates_by_digest[modeling.definition_digest] = modeling
            except (ValueError, WorkGraphError, WorkResumeError):
                continue
        if len(templates_by_digest) == 1:
            return next(iter(templates_by_digest.values()))
        return None

    @staticmethod
    def _native_world_template_matches(
        *,
        world_graph: GenerationWorkGraph,
        template_world_graph: GenerationWorkGraph,
    ) -> bool:
        """Accept only a native predecessor differing at CurriculumPlan itself."""

        current = {definition.coordinate: definition for definition in world_graph.definitions}
        template = {
            definition.coordinate: definition for definition in template_world_graph.definitions
        }
        if current.keys() != template.keys():
            return False
        current_plans = tuple(
            definition
            for definition in current.values()
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage == "curriculum_plan"
            )
        )
        template_plans = tuple(
            definition
            for definition in template.values()
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage == "curriculum_plan"
            )
        )
        if len(current_plans) != 1 or len(template_plans) != 1:
            return False
        current_plan = current_plans[0]
        template_plan = template_plans[0]
        if (
            current_plan.coordinate != template_plan.coordinate
            or current_plan.dependency_coordinates != template_plan.dependency_coordinates
            or current_plan.input_slots != template_plan.input_slots
            or current_plan.output_slots != template_plan.output_slots
        ):
            return False
        return all(
            definition == template[coordinate]
            for coordinate, definition in current.items()
            if coordinate != current_plan.coordinate
        )

    @staticmethod
    def _compatible_modeling_template(
        *,
        graph: GenerationWorkGraph,
        planner: WorkDefinition,
    ) -> WorkDefinition | None:
        """Require the exact pre-fan-out Modeling shape before reusing it."""

        modelings = tuple(
            definition
            for definition in graph.definitions
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage == "modeling_boundary"
            )
        )
        if len(modelings) != 1:
            return None
        modeling = modelings[0]
        template_curriculum = tuple(
            coordinate
            for coordinate in modeling.dependency_coordinates
            if coordinate.component == "design" and coordinate.stage == "task_curriculum"
        )
        if len(template_curriculum) != 1:
            return None
        if modeling.dependency_coordinates != (
            *planner.dependency_coordinates,
            template_curriculum[0],
        ):
            return None
        return modeling

    @classmethod
    def _load_committed_world_plan(
        cls,
        *,
        app: FoundryApplication,
        scope_id: str,
    ) -> _CommittedDiagnosticWorldPlan:
        candidates: list[_CommittedDiagnosticWorldPlan] = []
        for world_epoch_ref in app.artifacts.list_revisions():
            if world_epoch_ref.artifact_type != "control.work_graph_epoch":
                continue
            try:
                world_epoch = app.artifacts.get_json(world_epoch_ref, WorkGraphEpoch)
            except ValueError:
                continue
            if world_epoch.scope_id != scope_id or world_epoch.epoch_kind != "world":
                continue
            if world_epoch.predecessor_epoch_ref is None:
                continue
            try:
                manifest = app.artifacts.get_json(world_epoch.manifest_ref, WorkGraphManifest)
                graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001 - exact manifest replay
                    app.controller.artifacts,
                    manifest,
                )
                if (
                    graph.manifest(
                        topology_id=manifest.topology_id,
                        external_root_refs=manifest.external_root_refs,
                    )
                    != manifest
                ):
                    continue
                planners = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage == "curriculum_plan"
                    )
                )
                if len(planners) != 1:
                    continue
                planner = planners[0]
                plan_head = app.controller.work_control.read_head(planner.coordinate)
                if plan_head is None or plan_head.status != "committed":
                    continue
                plan_attempt = app.artifacts.get_json(plan_head.attempt_ref, WorkAttempt)
                committed = app.controller.work_control.require_diagnostic_commit(
                    definition=planner,
                    input_refs=plan_attempt.input_refs,
                    artifacts=app.controller.artifacts,
                )
                if committed is None:
                    continue
                plan_commit, _plan_commit_ref = committed
                plan_ref = cls._one_consumer_ref(
                    plan_commit,
                    artifact_type="design.curriculum_plan_source",
                )
                curriculum_plan = app.artifacts.get_json(plan_ref, CurriculumPlanSourceDraft)
                modeling_template = cls._modeling_template_for_world_plan(
                    app=app,
                    world_epoch_ref=world_epoch_ref,
                    world_epoch=world_epoch,
                    world_graph=graph,
                    planner=planner,
                )
                if modeling_template is None:
                    continue
            except (ValueError, WorkGraphError, WorkResumeError):
                continue
            candidates.append(
                _CommittedDiagnosticWorldPlan(
                    graph=graph,
                    manifest=manifest,
                    manifest_ref=world_epoch.manifest_ref,
                    world_epoch_ref=world_epoch_ref,
                    context_ref=world_epoch.context_ref,
                    curriculum_plan_definition=planner,
                    curriculum_plan_ref=plan_ref,
                    curriculum_plan=curriculum_plan,
                    modeling_template=modeling_template,
                )
            )
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            raise TestNodeError(
                "test_task_requirement_world_plan_ambiguous",
                "diagnostic state has more than one committed CurriculumPlan world closure",
            )
        raise TestNodeError(
            "test_task_requirement_world_plan_missing",
            (
                "diagnostic state requires one committed CurriculumPlan World closure and one "
                "compatible retained ModelingBoundary template"
            ),
        )


_PlanDerivedDesignTailStage = Literal[
    "task_curriculum",
    "modeling_boundary",
    "verifier_plan",
]
_PlanDerivedDiagnosticAnchor = Literal["curriculum_plan", "verifier_plan"]


@dataclass(frozen=True, slots=True)
class _PlanDerivedDiagnosticJoin:
    """One exact deterministic tail in a Plan-derived Design epoch.

    The historical whole-curriculum graph and the Plan-derived graph retain
    several public coordinates so downstream artifact contracts stay stable.
    This object records the latter's complete deterministic tail, rather than
    permitting a caller to choose an arbitrary manifest revision.
    """

    design_epoch_ref: ArtifactRef
    manifest_ref: ArtifactRef
    curriculum_plan_definition: WorkDefinition
    task_requirement_definitions: tuple[WorkDefinition, ...]
    join_definition: WorkDefinition
    modeling_definition: WorkDefinition
    verifier_plan_definition: WorkDefinition

    def target_for(self, stage: _PlanDerivedDesignTailStage) -> WorkDefinition:
        if stage == "task_curriculum":
            return self.join_definition
        if stage == "modeling_boundary":
            return self.modeling_definition
        if stage == "verifier_plan":
            return self.verifier_plan_definition
        raise TestNodeError(
            "test_plan_derived_design_target_invalid",
            "target stage must be task_curriculum, modeling_boundary, or verifier_plan",
        )


class DiagnosticTaskCurriculumJoinResult(V2Contract):
    """One real deterministic TaskCurriculum join below committed task families."""

    source_scope_id: str
    source_diagnostic_state_root: str
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    node: DiagnosticDescendantNodeResult
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticTaskCurriculumJoinRunner:
    """Dispatch the exact Plan-derived TaskCurriculum join once.

    A historic whole-curriculum Agent definition and the new deterministic
    join intentionally share the downstream coordinate: downstream contracts
    still consume ``design.task_curriculum_source``.  Generic coordinate-only
    selection therefore fails closed when both historical and Plan-derived
    manifests survive in an isolated diagnostic closure.  This narrow runner
    proves the intended join by selecting the unique Design epoch that:

    * follows the committed World-plus-CurriculumPlan epoch;
    * contains one code-owned TaskCurriculum join and one or more physical
      TaskRequirement definitions; and
    * has every join parent committed, including a diagnostic CurriculumPlan.

    The ordinary descendant runner still performs the fresh child copy and
    Scheduler dispatch.  The manifest selector is internal evidence, never a
    user-supplied adoption or release authority.
    """

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(self, *, scope_id: str) -> DiagnosticTaskCurriculumJoinResult:
        source_diagnostic_root = self._resolve_diagnostic_root()
        from agent_world.app import build_application

        app = build_application(
            self.config.model_copy(update={"state_root": source_diagnostic_root})
        )
        frozen = self._load_plan_derived_join(app=app, scope_id=scope_id)
        node = await DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            executor_factory=self.executor_factory,
        ).run(
            scope_id=scope_id,
            target_coordinate=frozen.join_definition.coordinate.coordinate_key,
            required_manifest_ref=frozen.manifest_ref,
        )
        return DiagnosticTaskCurriculumJoinResult(
            source_scope_id=scope_id,
            source_diagnostic_state_root=str(source_diagnostic_root),
            design_epoch_ref=frozen.design_epoch_ref,
            design_manifest_ref=frozen.manifest_ref,
            node=node,
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_task_curriculum_join"
        )

    @classmethod
    def _load_plan_derived_join(
        cls,
        *,
        app: FoundryApplication,
        scope_id: str,
        require_unheaded_join: bool = True,
        diagnostic_anchor: _PlanDerivedDiagnosticAnchor = "curriculum_plan",
        allow_active_verifier_plan: bool = False,
    ) -> _PlanDerivedDiagnosticJoin:
        """Select one exact Plan-derived Design closure by its changed boundary.

        ``TaskCurriculum`` continuation is anchored to a diagnostic
        ``CurriculumPlan`` because that is the changed fan-out parent. A final
        graph can instead reuse the exact active deterministic
        ``ModelingBoundary`` and ``VerifierPlan`` from its marked copy: the
        child final epoch is itself diagnostic-only, while those committed
        parents remain immutable normal evidence. Both routes retain the same
        structural Design checks; this switch changes neither production
        scheduling nor release authority.
        """

        if diagnostic_anchor == "curriculum_plan":
            anchor_label = "CurriculumPlan"
            missing_code = "test_task_curriculum_join_design_missing"
            ambiguous_code = "test_task_curriculum_join_design_ambiguous"
            not_diagnostic_code = "test_task_curriculum_join_plan_not_diagnostic"
            missing_message = (
                "diagnostic state requires one Plan-derived TaskCurriculum Design epoch"
            )
            ambiguous_message = (
                "diagnostic state has more than one Plan-derived TaskCurriculum Design epoch"
            )
        elif diagnostic_anchor == "verifier_plan":
            anchor_label = "VerifierPlan"
            missing_code = "test_final_node_design_missing"
            ambiguous_code = "test_final_node_design_ambiguous"
            not_diagnostic_code = "test_final_node_verifier_plan_not_diagnostic"
            missing_message = (
                "diagnostic state requires one Plan-derived Design epoch whose "
                "VerifierPlan has one exact eligible active or diagnostic commit"
            )
            ambiguous_message = (
                "diagnostic state has more than one Plan-derived Design epoch whose "
                "VerifierPlan has one exact eligible active or diagnostic commit"
            )
        else:  # pragma: no cover - Literal callers are checked statically
            raise TestNodeError(
                "test_plan_derived_design_anchor_invalid",
                "diagnostic anchor must be curriculum_plan or verifier_plan",
            )

        candidates: list[_PlanDerivedDiagnosticJoin] = []
        for design_epoch_ref in app.artifacts.list_revisions():
            if design_epoch_ref.artifact_type != "control.work_graph_epoch":
                continue
            try:
                design_epoch = app.artifacts.get_json(design_epoch_ref, WorkGraphEpoch)
                if (
                    design_epoch.scope_id != scope_id
                    or design_epoch.epoch_kind != "design"
                    or design_epoch.predecessor_epoch_ref is None
                ):
                    continue
                predecessor = app.artifacts.get_json(
                    design_epoch.predecessor_epoch_ref,
                    WorkGraphEpoch,
                )
                if (
                    predecessor.epoch_kind != "world"
                    or predecessor.context_ref != design_epoch.context_ref
                ):
                    continue
                manifest = app.artifacts.get_json(
                    design_epoch.manifest_ref,
                    WorkGraphManifest,
                )
                graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001 - frozen closure proof
                    app.controller.artifacts,
                    manifest,
                )
                if (
                    graph.manifest(
                        topology_id=manifest.topology_id,
                        external_root_refs=manifest.external_root_refs,
                    )
                    != manifest
                ):
                    continue
                plans = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage == "curriculum_plan"
                    )
                )
                requirements = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage == "task_requirement"
                    )
                )
                joins = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage == "task_curriculum"
                    )
                )
                modelings = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage == "modeling_boundary"
                    )
                )
                verifier_plans = tuple(
                    definition
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "verifier"
                        and definition.coordinate.stage == "verifier_plan"
                    )
                )
                if (
                    len(plans) != 1
                    or not requirements
                    or len(joins) != 1
                    or len(modelings) != 1
                    or len(verifier_plans) != 1
                ):
                    continue
                join = joins[0]
                modeling = modelings[0]
                verifier_plan = verifier_plans[0]
                if any(
                    definition.proposal_policy.executor != "code"
                    for definition in (join, modeling, verifier_plan)
                ):
                    continue
                if (
                    plans[0].coordinate not in join.dependency_coordinates
                    or not {item.coordinate for item in requirements}.issubset(
                        join.dependency_coordinates
                    )
                    or join.coordinate not in modeling.dependency_coordinates
                    or verifier_plan.dependency_coordinates != (modeling.coordinate,)
                ):
                    continue
                # A normal native Design epoch and a diagnostic epoch
                # intentionally retain public coordinates.  Select the exact
                # digest-bound diagnostic boundary, never the first
                # structurally compatible manifest.  TaskCurriculum continues
                # below a diagnostic Plan; final derivation may instead follow
                # a normal Plan and one diagnostic VerifierPlan refresh.
                anchor_definition = (
                    plans[0] if diagnostic_anchor == "curriculum_plan" else verifier_plan
                )
                anchor_head = app.controller.work_control.read_head(anchor_definition.coordinate)
                if anchor_head is None or anchor_head.status != "committed":
                    continue
                anchor_attempt = app.artifacts.get_json(anchor_head.attempt_ref, WorkAttempt)
                anchor_commit = (
                    app.controller.work_control.require_active_or_diagnostic_commit(
                        definition=anchor_definition,
                        input_refs=anchor_attempt.input_refs,
                        artifacts=app.controller.artifacts,
                    )
                    if diagnostic_anchor == "verifier_plan" and allow_active_verifier_plan
                    else app.controller.work_control.require_diagnostic_commit(
                        definition=anchor_definition,
                        input_refs=anchor_attempt.input_refs,
                        artifacts=app.controller.artifacts,
                    )
                )
                if anchor_commit is None:
                    continue
            except (ValueError, WorkGraphError, WorkResumeError):
                continue
            candidates.append(
                _PlanDerivedDiagnosticJoin(
                    design_epoch_ref=design_epoch_ref,
                    manifest_ref=design_epoch.manifest_ref,
                    curriculum_plan_definition=plans[0],
                    task_requirement_definitions=requirements,
                    join_definition=join,
                    modeling_definition=modeling,
                    verifier_plan_definition=verifier_plan,
                )
            )
        if len(candidates) > 1:
            raise TestNodeError(
                ambiguous_code,
                ambiguous_message,
            )
        if not candidates:
            raise TestNodeError(
                missing_code,
                missing_message,
            )

        candidate = candidates[0]
        heads = app.controller.work_control
        # Do not decide that a copied deterministic join is already complete
        # from its definition digest alone. A fresh CurriculumPlan can retain
        # the public TaskCurriculum coordinate and definition while changing
        # the committed Plan/TaskRequirement Artifacts it consumes. The normal
        # Scheduler is the single owner of the resolved input closure and will
        # classify such a copied terminal head as ``stale`` by fingerprint.
        # Let ``DiagnosticDescendantNodeRunner`` make that decision after it
        # resolves inputs; otherwise this helper falsely blocks the exact
        # downstream proof that the new Plan requires.
        if require_unheaded_join:
            parent_heads = tuple(
                heads.read_head(coordinate)
                for coordinate in candidate.join_definition.dependency_coordinates
            )
            if len(parent_heads) != len(candidate.join_definition.dependency_coordinates) or any(
                head is None or head.status != "committed" or head.commit_ref is None
                for head in parent_heads
            ):
                raise TestNodeError(
                    "test_task_curriculum_join_parent_closure_missing",
                    "the Plan-derived TaskCurriculum join lacks one committed parent closure",
                )
        anchor_definition = (
            candidate.curriculum_plan_definition
            if diagnostic_anchor == "curriculum_plan"
            else candidate.verifier_plan_definition
        )
        anchor_head = heads.read_head(anchor_definition.coordinate)
        assert anchor_head is not None  # established by the exact candidate selector above
        anchor_attempt = app.artifacts.get_json(anchor_head.attempt_ref, WorkAttempt)
        anchor_commit = (
            app.controller.work_control.require_active_or_diagnostic_commit(
                definition=anchor_definition,
                input_refs=anchor_attempt.input_refs,
                artifacts=app.controller.artifacts,
            )
            if diagnostic_anchor == "verifier_plan" and allow_active_verifier_plan
            else app.controller.work_control.require_diagnostic_commit(
                definition=anchor_definition,
                input_refs=anchor_attempt.input_refs,
                artifacts=app.controller.artifacts,
            )
        )
        if anchor_commit is None:
            raise TestNodeError(
                not_diagnostic_code,
                (
                    "the selected Plan-derived Design epoch requires one exact eligible "
                    f"active or diagnostic {anchor_label} commit"
                ),
            )
        return candidate


class DiagnosticPlanDerivedDesignNodeResult(V2Contract):
    """One real deterministic tail node from the exact Plan-derived Design epoch."""

    source_scope_id: str
    source_diagnostic_state_root: str
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    target_stage: _PlanDerivedDesignTailStage
    target_coordinate: WorkCoordinate
    node: DiagnosticDescendantNodeResult
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticPlanDerivedDesignNodeRunner:
    """Dispatch one approved deterministic tail node below plan-derived tasks.

    A coordinate is deliberately insufficient here: the historical
    whole-curriculum topology and the new fan-out topology retain the same
    public TaskCurriculum, ModelingBoundary, and VerifierPlan coordinates.
    This runner derives selection from the committed CurriculumPlan topology
    itself, then delegates execution to the ordinary descendant Scheduler.
    It therefore neither exposes a manifest selector to the CLI nor gives a
    caller an adoption/release capability.
    """

    _ALLOWED_STAGES = frozenset({"task_curriculum", "modeling_boundary", "verifier_plan"})

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        target_stage: _PlanDerivedDesignTailStage,
    ) -> DiagnosticPlanDerivedDesignNodeResult:
        if target_stage not in self._ALLOWED_STAGES:
            raise TestNodeError(
                "test_plan_derived_design_target_invalid",
                "target stage must be task_curriculum, modeling_boundary, or verifier_plan",
            )
        source_diagnostic_root = self._resolve_diagnostic_root()
        from agent_world.app import build_application

        app = build_application(
            self.config.model_copy(update={"state_root": source_diagnostic_root})
        )
        frozen = DiagnosticTaskCurriculumJoinRunner._load_plan_derived_join(
            app=app,
            scope_id=scope_id,
            require_unheaded_join=False,
        )
        target = frozen.target_for(target_stage)
        node = await DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            executor_factory=self.executor_factory,
        ).run(
            scope_id=scope_id,
            target_coordinate=target.coordinate.coordinate_key,
            required_manifest_ref=frozen.manifest_ref,
        )
        return DiagnosticPlanDerivedDesignNodeResult(
            source_scope_id=scope_id,
            source_diagnostic_state_root=str(source_diagnostic_root),
            design_epoch_ref=frozen.design_epoch_ref,
            design_manifest_ref=frozen.manifest_ref,
            target_stage=target_stage,
            target_coordinate=target.coordinate,
            node=node,
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_plan_derived_design"
        )


_DiagnosticFinalInitialStage = Literal[
    "implementation_plan",
    "verifier_intent_batch",
    "runtime_integration",
]


class DiagnosticFinalNodeResult(V2Contract):
    """One real initial final-graph node below a frozen diagnostic Design closure.

    The production topology remains byte-for-byte the normal complete graph,
    but both the prepared state root and the dispatched child result are
    diagnostic-only.  This makes the result valid execution evidence without
    granting package or Registry authority to the copied lineage.
    """

    source_scope_id: str
    source_diagnostic_state_root: str
    prepared_diagnostic_state_root: str
    design_epoch_ref: ArtifactRef
    design_manifest_ref: ArtifactRef
    verifier_plan_ref: ArtifactRef
    final_epoch_ref: ArtifactRef
    final_manifest_ref: ArtifactRef
    target_stage: _DiagnosticFinalInitialStage
    source_proposal_llm_tokens: int
    proposal_llm_tokens: int
    source_proposal_wall_seconds: float
    proposal_wall_seconds: float
    source_execution_envelope: ProposalExecutionEnvelope
    execution_envelope: ProposalExecutionEnvelope
    target_batch_index: int | None = None
    target_coordinate: WorkCoordinate
    node: DiagnosticDescendantNodeResult
    diagnostic_only: Literal[True] = True
    releasable: Literal[False] = False


class DiagnosticFinalNodeRunner:
    """Re-derive and dispatch one real final-graph boundary safely.

    ``BuildImplementationPlan`` and physical ``Challenger`` batches are
    independent after the committed Design and VerifierPlan closure.
    ``Integration`` is included as the first deterministic successor that can
    reuse an already committed Candidate. This helper copies a marked
    diagnostic state, derives the exact production final graph from the
    persisted VerifierPlan and Design, freezes it with diagnostic ancestors
    allowed only in the copy, and dispatches one selected boundary through the
    normal Scheduler. It never accepts a caller-supplied manifest or creates
    a release path.
    """

    _ALLOWED_STAGES = frozenset(
        {"implementation_plan", "verifier_intent_batch", "runtime_integration"}
    )

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        diagnostic_parent: Path | None = None,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.diagnostic_parent = diagnostic_parent
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        target_stage: _DiagnosticFinalInitialStage,
        batch_index: int | None = None,
        proposal_llm_tokens: int | None = None,
        proposal_wall_seconds: float | None = None,
    ) -> DiagnosticFinalNodeResult:
        if target_stage not in self._ALLOWED_STAGES:
            raise TestNodeError(
                "test_final_node_target_invalid",
                (
                    "target stage must be implementation_plan, verifier_intent_batch, "
                    "or runtime_integration"
                ),
            )
        source_diagnostic_root = self._resolve_diagnostic_root()
        prepared_root = _prepare_diagnostic_clone(
            source_root=source_diagnostic_root,
            diagnostic_parent=self.diagnostic_parent,
            marker_error_code="test_final_node_diagnostic_marker_failed",
            marker_message="fresh diagnostic final-node state could not be marked",
        )

        from agent_world.app import build_application

        app = build_application(self.config.model_copy(update={"state_root": prepared_root}))
        frozen = DiagnosticTaskCurriculumJoinRunner._load_plan_derived_join(
            app=app,
            scope_id=scope_id,
            require_unheaded_join=False,
            diagnostic_anchor="verifier_plan",
            allow_active_verifier_plan=True,
        )
        try:
            design_epoch = app.artifacts.get_json(frozen.design_epoch_ref, WorkGraphEpoch)
            if (
                design_epoch.epoch_kind != "design"
                or design_epoch.manifest_ref != frozen.manifest_ref
                or design_epoch.predecessor_epoch_ref is None
            ):
                raise WorkGraphError("selected Design epoch is not one closed Plan-derived epoch")
            design_manifest = app.artifacts.get_json(frozen.manifest_ref, WorkGraphManifest)
            design_graph = TestNodeRunner._reconstruct_graph(  # noqa: SLF001 - exact manifest proof
                app.controller.artifacts,
                design_manifest,
            )
            if (
                design_graph.manifest(
                    topology_id=design_manifest.topology_id,
                    external_root_refs=design_manifest.external_root_refs,
                )
                != design_manifest
            ):
                raise WorkGraphError("selected Design manifest cannot be reconstructed exactly")
            verifier_head = app.controller.work_control.read_head(
                frozen.verifier_plan_definition.coordinate
            )
            if verifier_head is None or verifier_head.status != "committed":
                raise WorkResumeError("VerifierPlan has no committed Work head")
            verifier_attempt = app.artifacts.get_json(verifier_head.attempt_ref, WorkAttempt)
            verifier_commit_result = (
                app.controller.work_control.require_active_or_diagnostic_commit(
                    definition=frozen.verifier_plan_definition,
                    input_refs=verifier_attempt.input_refs,
                    artifacts=app.controller.artifacts,
                )
            )
            if verifier_commit_result is None:
                raise WorkResumeError("VerifierPlan has no exact committed parent")
            verifier_commit, verifier_commit_ref = verifier_commit_result
            verifier_plan_ref = self._one_consumer_ref(
                verifier_commit,
                artifact_type="judge.verifier_batch_plan",
            )
            verifier_plan = app.artifacts.get_json(verifier_plan_ref, VerifierBatchPlan)
            modeling_definition = TestNodeRunner._one_definition(
                design_graph,
                "design",
                "modeling_boundary",
            )
            modeling_head = app.controller.work_control.read_head(modeling_definition.coordinate)
            if modeling_head is None or modeling_head.status != "committed":
                raise WorkResumeError("ModelingBoundary has no committed Work head")
            modeling_attempt = app.artifacts.get_json(modeling_head.attempt_ref, WorkAttempt)
            modeling_commit_result = (
                app.controller.work_control.require_active_or_diagnostic_commit(
                    definition=modeling_definition,
                    input_refs=modeling_attempt.input_refs,
                    artifacts=app.controller.artifacts,
                )
            )
            if modeling_commit_result is None:
                raise WorkResumeError("ModelingBoundary has no exact committed parent")
            modeling_commit, _modeling_commit_ref = modeling_commit_result
            design_ref = self._one_consumer_ref(
                modeling_commit,
                artifact_type="design.environment_design",
            )
            environment_design = app.artifacts.get_json(design_ref, EnvironmentDesign)
            if verifier_plan.design_ref != design_ref:
                raise WorkGraphError(
                    "committed VerifierPlan does not bind the committed ModelingBoundary Design"
                )
            base_final_graph = self._reconcile_final_graph_with_committed(
                app=app,
                scope_id=scope_id,
                graph=self._final_graph(
                    scope_id=scope_id,
                    design_graph=design_graph,
                    verifier_batch_count=len(verifier_plan.batches),
                    environment_design=environment_design,
                    verifier_batch_plan=verifier_plan,
                ),
            )
            target = self._initial_target(
                final_graph=base_final_graph,
                verifier_plan=verifier_plan,
                target_stage=target_stage,
                batch_index=batch_index,
            )
            source_definition = base_final_graph.require(target)
            logical_plan_session = target_stage == "implementation_plan"
            is_agent_target = source_definition.proposal_policy.executor == "agent"
            if not is_agent_target and (
                proposal_llm_tokens is not None or proposal_wall_seconds is not None
            ):
                raise TestNodeError(
                    "test_final_node_proposal_envelope_target_not_agent",
                    (
                        "proposal token and wall overrides apply only to one Agent target; "
                        "runtime_integration has no model invocation"
                    ),
                )
            source_proposal_llm_tokens, source_proposal_wall_seconds = (
                self._definition_proposal_envelope(
                    source_definition=source_definition,
                    logical_session=logical_plan_session,
                )
            )
            source_execution_envelope = TestNodeRunner._proposal_execution_envelope(
                source_definition
            )
            if is_agent_target:
                proposal_llm_tokens, proposal_wall_seconds = self._proposal_envelope(
                    source_definition=source_definition,
                    requested_llm_tokens=proposal_llm_tokens,
                    requested_wall_seconds=proposal_wall_seconds,
                    diagnostic_budget=self.config.generation_budget,
                    logical_session=logical_plan_session,
                    allow_unchanged=True,
                )
            else:
                proposal_llm_tokens = source_proposal_llm_tokens
                proposal_wall_seconds = source_proposal_wall_seconds
            if (
                proposal_llm_tokens == source_proposal_llm_tokens
                and proposal_wall_seconds == source_proposal_wall_seconds
            ):
                final_graph = base_final_graph
            elif target_stage == "implementation_plan":
                final_graph = self._reconcile_final_graph_with_committed(
                    app=app,
                    scope_id=scope_id,
                    graph=self._final_graph(
                        scope_id=scope_id,
                        design_graph=design_graph,
                        verifier_batch_count=len(verifier_plan.batches),
                        environment_design=environment_design,
                        verifier_batch_plan=verifier_plan,
                        implementation_plan_session_token_limit=proposal_llm_tokens,
                        implementation_plan_session_wall_seconds=proposal_wall_seconds,
                    ),
                    exclude_coordinates=(target,),
                )
            elif target_stage == "verifier_intent_batch":
                final_graph = self._reconcile_final_graph_with_committed(
                    app=app,
                    scope_id=scope_id,
                    graph=self._final_graph(
                        scope_id=scope_id,
                        design_graph=design_graph,
                        verifier_token_limit=proposal_llm_tokens,
                        verifier_wall_seconds=proposal_wall_seconds,
                        verifier_batch_count=len(verifier_plan.batches),
                        environment_design=environment_design,
                        verifier_batch_plan=verifier_plan,
                    ),
                    exclude_coordinates=(target,),
                )
            target = self._initial_target(
                final_graph=final_graph,
                verifier_plan=verifier_plan,
                target_stage=target_stage,
                batch_index=batch_index,
            )
            effective_definition = final_graph.require(target)
            effective_tokens, effective_wall = self._definition_proposal_envelope(
                source_definition=effective_definition,
                logical_session=logical_plan_session,
            )
            if effective_tokens != proposal_llm_tokens or effective_wall != proposal_wall_seconds:
                raise WorkGraphError(
                    "diagnostic final proposal envelope did not bind the selected target"
                )
            final_manifest, final_manifest_ref, _final_epoch, final_epoch_ref = (
                WorkGraphEpochRuntime(
                    artifacts=app.controller.artifacts,
                    heads=app.controller.work_control,
                ).freeze_final(
                    context_ref=design_epoch.context_ref,
                    design_epoch_ref=frozen.design_epoch_ref,
                    graph=final_graph,
                    topology_id=(
                        "topology:test-final-node:"
                        f"{scope_id}:{verifier_plan_ref.content_hash.removeprefix('sha256:')[:16]}"
                    ),
                    allow_diagnostic_predecessors=True,
                )
            )
            final_epoch_diagnostic_anchor = _FinalEpochDiagnosticAnchor(
                final_epoch_ref=final_epoch_ref,
                final_manifest_ref=final_manifest_ref,
                design_epoch_ref=frozen.design_epoch_ref,
                verifier_plan_coordinate=frozen.verifier_plan_definition.coordinate,
                verifier_plan_definition_digest=(frozen.verifier_plan_definition.definition_digest),
                verifier_plan_commit_ref=verifier_commit_ref,
            )
        except (ValueError, WorkGraphError, WorkResumeError, WorkControlStoreError) as exc:
            raise TestNodeError(
                "test_final_node_topology_derivation_failed",
                (
                    "the committed diagnostic Design and VerifierPlan closure cannot freeze "
                    f"final work ({type(exc).__name__}: {exc})"
                ),
            ) from exc

        # ``runtime_integration`` is a genuine successor, not an independent
        # initial node: it can run only when this exact final graph has one
        # active Candidate closure.  Check that prerequisite before handing
        # control to the generic descendant dispatcher.  Otherwise its normal
        # ready-only fence raises an unclassified WorkRuntimeError, which
        # hides the actionable fact that the Candidate must be rebuilt under
        # the freshly frozen final graph.
        readiness_runtime = _diagnostic_work_runtime(
            app=app,
            heads=app.controller.work_control,
            budget=TestNodeRunner._single_attempt_budget(effective_definition),
            repair_scope_id=scope_id,
        )
        readiness_scheduler = WorkScheduler(
            graph=final_graph,
            manifest=final_manifest,
            manifest_ref=final_manifest_ref,
            heads=app.controller.work_control,
            artifacts=app.controller.artifacts,
            runtime=readiness_runtime,
            allow_diagnostic_ancestors=True,
        )
        scheduled_target = next(
            (item for item in readiness_scheduler.snapshot().work if item.coordinate == target),
            None,
        )
        self._require_dispatchable_final_target(
            target_stage=target_stage,
            scheduled_state=None if scheduled_target is None else scheduled_target.state,
        )

        node = await DiagnosticDescendantNodeRunner(
            config=self.config,
            diagnostic_state_root=prepared_root,
            diagnostic_parent=self.diagnostic_parent,
            executor_factory=self.executor_factory,
        ).run(
            scope_id=scope_id,
            target_coordinate=target.coordinate_key,
            required_manifest_ref=final_manifest_ref,
            final_epoch_diagnostic_anchor=final_epoch_diagnostic_anchor,
        )
        return DiagnosticFinalNodeResult(
            source_scope_id=scope_id,
            source_diagnostic_state_root=str(source_diagnostic_root),
            prepared_diagnostic_state_root=str(prepared_root),
            design_epoch_ref=frozen.design_epoch_ref,
            design_manifest_ref=frozen.manifest_ref,
            verifier_plan_ref=verifier_plan_ref,
            final_epoch_ref=final_epoch_ref,
            final_manifest_ref=final_manifest_ref,
            target_stage=target_stage,
            source_proposal_llm_tokens=source_proposal_llm_tokens,
            proposal_llm_tokens=proposal_llm_tokens,
            source_proposal_wall_seconds=source_proposal_wall_seconds,
            proposal_wall_seconds=proposal_wall_seconds,
            source_execution_envelope=source_execution_envelope,
            execution_envelope=TestNodeRunner._proposal_execution_envelope(effective_definition),
            target_batch_index=batch_index,
            target_coordinate=target,
            node=node,
        )

    @staticmethod
    def _proposal_envelope(
        *,
        source_definition: WorkDefinition,
        requested_llm_tokens: int | None,
        requested_wall_seconds: float | None,
        diagnostic_budget: Budget,
        logical_session: bool = False,
        allow_unchanged: bool = False,
    ) -> tuple[int, float]:
        """Resolve one explicit, finite diagnostic envelope for an initial node.

        A diagnostic may increase one target's logical session envelope after
        a budget terminal, but it cannot become an unbounded process or
        reserve more than the configured Direct-generation budget.  For a
        BuildImplementationPlan this resolves the *logical* session, not the
        Provider's physical output ceiling.  Selecting the already configured
        envelope is allowed for an initial diagnostic dispatch; it does not
        create a retry or a second hidden turn.
        """

        policy = source_definition.proposal_policy
        if policy.executor != "agent":
            raise TestNodeError(
                "test_final_node_proposal_envelope_target_not_agent",
                "a diagnostic proposal envelope is valid only for one Agent target",
            )
        source_tokens, source_wall = DiagnosticFinalNodeRunner._definition_proposal_envelope(
            source_definition=source_definition,
            logical_session=logical_session,
        )
        tokens = source_tokens if requested_llm_tokens is None else requested_llm_tokens
        wall = source_wall if requested_wall_seconds is None else requested_wall_seconds
        if isinstance(tokens, bool) or not isinstance(tokens, int) or tokens <= 0:
            raise TestNodeError(
                "test_final_node_proposal_budget_invalid",
                "diagnostic proposal output-token budget must be one positive integer",
            )
        if tokens < source_tokens:
            raise TestNodeError(
                "test_final_node_proposal_budget_decreased",
                "diagnostic proposal output-token budget may not decrease the frozen value",
            )
        if tokens > diagnostic_budget.llm_tokens:
            raise TestNodeError(
                "test_final_node_proposal_budget_exceeds_generation_budget",
                "diagnostic proposal output-token budget exceeds the configured generation budget",
            )
        if (
            isinstance(wall, bool)
            or not isinstance(wall, (int, float))
            or not math.isfinite(wall)
            or wall <= 0
        ):
            raise TestNodeError(
                "test_final_node_proposal_wall_invalid",
                "diagnostic proposal wall budget must be one finite positive number",
            )
        wall = float(wall)
        if wall < source_wall:
            raise TestNodeError(
                "test_final_node_proposal_wall_decreased",
                "diagnostic proposal wall budget may not decrease the frozen value",
            )
        if wall > diagnostic_budget.wall_seconds:
            raise TestNodeError(
                "test_final_node_proposal_wall_exceeds_generation_budget",
                "diagnostic proposal wall budget exceeds the configured generation budget",
            )
        if (
            not allow_unchanged
            and (requested_llm_tokens is not None or requested_wall_seconds is not None)
            and tokens == source_tokens
            and wall == source_wall
        ):
            raise TestNodeError(
                "test_final_node_proposal_envelope_not_changed",
                "diagnostic proposal envelope must change at least one frozen budget dimension",
            )
        return tokens, wall

    def _recover_committed_definition(
        self,
        *,
        app: FoundryApplication,
        head: WorkControlHead,
    ) -> WorkDefinition:
        """Recover the exact committed WorkDefinition that authorized ``head``.

        The active-commit gate binds a parent by its stored ``definition_digest``
        (repair_policy budgets + framework ``*_revision_id`` folded in).  Reuse
        that byte-exact definition rather than a freshly compiled one so the
        re-derived final manifest keeps the committed head active.
        """

        if head.commit_ref is None:
            raise TestNodeError(
                "test_final_node_committed_definition_reuse_failed",
                (
                    "committed head "
                    f"{head.coordinate.coordinate_key} lacks a commit reference"
                ),
            )
        try:
            commit = app.artifacts.get_json(head.commit_ref, WorkCommit)
            definition = WorkControlStore._require_commit_definition(  # noqa: SLF001
                commit=commit,
                artifacts=app.controller.artifacts,
            )
        except (ValueError, WorkResumeError, WorkControlStoreError) as exc:
            raise TestNodeError(
                "test_final_node_committed_definition_reuse_failed",
                (
                    "committed head "
                    f"{head.coordinate.coordinate_key} lacks one exact originating "
                    f"WorkDefinition ({type(exc).__name__}: {exc})"
                ),
            ) from exc
        if (
            definition.coordinate != head.coordinate
            or definition.definition_digest != head.definition_digest
        ):
            raise TestNodeError(
                "test_final_node_committed_definition_reuse_failed",
                (
                    "recovered committed definition does not match head "
                    f"{head.coordinate.coordinate_key}"
                ),
            )
        return definition

    def _reconcile_final_graph_with_committed(
        self,
        *,
        app: FoundryApplication,
        scope_id: str,
        graph: GenerationWorkGraph,
        exclude_coordinates: tuple[WorkCoordinate, ...] = (),
    ) -> GenerationWorkGraph:
        """Reuse committed definitions for benign passthrough coordinates.

        ``complete_generation_work_graph`` recompiles every final definition from
        live compiler functions, baking the CURRENT framework ``*_revision_id``
        values and config-derived ``repair_policy`` budgets.  For a coordinate
        whose head is already ``committed`` in this scope, that fresh definition
        carries a different ``definition_digest`` and orphans the parent under the
        active-commit gate.  Replace such fresh definitions with the exact
        committed WorkDefinition, leaving genuinely overridden targets
        (``exclude_coordinates``) fresh, then recompile the graph.
        """

        exclude_keys = {coordinate.coordinate_key for coordinate in exclude_coordinates}
        heads = app.controller.work_control
        reconciled: list[WorkDefinition] = []
        changed = False
        for definition in graph.definitions:
            coordinate = definition.coordinate
            if coordinate.coordinate_key in exclude_keys:
                reconciled.append(definition)
                continue
            head = heads.read_head(coordinate)
            if head is None or head.status != "committed":
                reconciled.append(definition)
                continue
            committed = self._recover_committed_definition(app=app, head=head)
            if committed.work_id != definition.work_id:
                raise TestNodeError(
                    "test_final_node_committed_definition_reuse_failed",
                    (
                        "committed definition work id diverges from the recompiled "
                        f"graph at {coordinate.coordinate_key}"
                    ),
                )
            if committed != definition:
                changed = True
            reconciled.append(committed)
        if not changed:
            return graph
        try:
            return GenerationWorkGraph.compile(
                reconciled,
                mode=graph.mode,
                strict_input_contracts=True,
                required_terminal_coordinates=graph.required_terminal_coordinates,
                groups=graph.groups,
                milestones=graph.milestones,
            )
        except WorkGraphError as exc:
            raise TestNodeError(
                "test_final_node_committed_definition_reuse_failed",
                (
                    "committed definitions cannot recompile the re-derived final "
                    f"graph ({type(exc).__name__}: {exc})"
                ),
            ) from exc

    def _final_graph(
        self,
        *,
        scope_id: str,
        design_graph: GenerationWorkGraph,
        verifier_batch_count: int,
        environment_design: EnvironmentDesign,
        verifier_batch_plan: VerifierBatchPlan,
        implementation_plan_session_token_limit: int | None = None,
        implementation_plan_session_wall_seconds: float | None = None,
        verifier_token_limit: int | None = None,
        verifier_wall_seconds: float | None = None,
    ) -> GenerationWorkGraph:
        """Compile the diagnostic's real final graph with Builder-style sessions.

        The diagnostic harness must exercise the same logical/physical split
        as Direct execution.  In particular, a 5M planning request is a 5M
        logical session with observable Provider turns, never one impossible
        5M-token SDK response.
        """

        default_session_tokens, default_session_wall = self._codegen_session_envelope()
        plan_session_tokens = (
            default_session_tokens
            if implementation_plan_session_token_limit is None
            else implementation_plan_session_token_limit
        )
        plan_session_wall = (
            default_session_wall
            if implementation_plan_session_wall_seconds is None
            else implementation_plan_session_wall_seconds
        )
        physical_plan_tokens = min(
            self.config.agent.environment_codegen_physical_turn_token_limit,
            plan_session_tokens,
        )
        return complete_generation_work_graph(
            scope_id=scope_id,
            design_graph=design_graph,
            implementation_plan_token_limit=physical_plan_tokens,
            implementation_plan_wall_seconds=plan_session_wall,
            implementation_plan_session_token_limit=plan_session_tokens,
            implementation_plan_session_wall_seconds=plan_session_wall,
            builder_token_limit=min(
                self.config.agent.environment_codegen_physical_turn_token_limit,
                default_session_tokens,
            ),
            builder_wall_seconds=default_session_wall,
            builder_session_token_limit=default_session_tokens,
            builder_session_wall_seconds=default_session_wall,
            verifier_token_limit=(48_000 if verifier_token_limit is None else verifier_token_limit),
            verifier_wall_seconds=(
                900.0 if verifier_wall_seconds is None else verifier_wall_seconds
            ),
            verifier_batch_count=verifier_batch_count,
            environment_design=environment_design,
            verifier_batch_plan=verifier_batch_plan,
            strict_input_contracts=True,
        )

    def _codegen_session_envelope(self) -> tuple[int, float]:
        """Return the finite 5M/parent-wall-style logical Builder envelope."""

        budget = self.config.generation_budget
        wall_candidates = (
            self.config.agent.environment_codegen_invocation_timeout_seconds,
            budget.wall_seconds,
            *((budget.build_seconds,) if budget.build_seconds > 0 else ()),
        )
        return (
            min(self.config.agent.environment_codegen_turn_token_limit, budget.llm_tokens),
            min(wall_candidates),
        )

    @staticmethod
    def _definition_proposal_envelope(
        *,
        source_definition: WorkDefinition,
        logical_session: bool,
    ) -> tuple[int, float]:
        policy = source_definition.proposal_policy
        if logical_session:
            if policy.session_token_limit is None or policy.session_wall_seconds is None:
                raise TestNodeError(
                    "test_final_node_logical_session_missing",
                    "BuildImplementationPlan must declare one logical session envelope",
                )
            return policy.session_token_limit, policy.session_wall_seconds
        return policy.budget.llm_tokens, policy.budget.wall_seconds

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_final_node"
        )

    @staticmethod
    def _one_consumer_ref(commit: WorkCommit, *, artifact_type: str) -> ArtifactRef:
        matches = tuple(ref for ref in commit.consumer_refs if ref.artifact_type == artifact_type)
        if len(matches) != 1:
            raise WorkGraphError("VerifierPlan commit lacks one exact verifier batch plan Artifact")
        return matches[0]

    @staticmethod
    def _initial_target(
        *,
        final_graph: GenerationWorkGraph,
        verifier_plan: VerifierBatchPlan,
        target_stage: _DiagnosticFinalInitialStage,
        batch_index: int | None,
    ) -> WorkCoordinate:
        if target_stage in {"implementation_plan", "runtime_integration"}:
            if batch_index is not None:
                raise TestNodeError(
                    "test_final_node_batch_index_unexpected",
                    "batch index is valid only for verifier_intent_batch",
                )
            component, stage = (
                ("build", "implementation_plan")
                if target_stage == "implementation_plan"
                else ("integration", "runtime_integration")
            )
            matches = tuple(
                definition.coordinate
                for definition in final_graph.definitions
                if (definition.coordinate.component, definition.coordinate.stage)
                == (component, stage)
            )
            if len(matches) == 1:
                return matches[0]
            raise TestNodeError(
                f"test_final_node_{target_stage}_missing",
                f"the frozen final graph lacks one exact {target_stage} boundary",
            )

        if (
            isinstance(batch_index, bool)
            or not isinstance(batch_index, int)
            or not 1 <= batch_index <= len(verifier_plan.batches)
        ):
            raise TestNodeError(
                "test_final_node_batch_index_invalid",
                "verifier_intent_batch requires one 1-based index from the frozen VerifierPlan",
            )
        matches = tuple(
            definition.coordinate
            for definition in final_graph.definitions
            if (
                definition.coordinate.component == "verifier"
                and definition.coordinate.stage == "verifier_intent_batch"
                and definition.coordinate.shard_id == f"batch-{batch_index}"
            )
        )
        if len(matches) == 1:
            return matches[0]
        raise TestNodeError(
            "test_final_node_batch_missing",
            "the frozen final graph does not match the selected VerifierPlan batch",
        )

    @staticmethod
    def _require_dispatchable_final_target(
        *,
        target_stage: _DiagnosticFinalInitialStage,
        scheduled_state: str | None,
    ) -> None:
        """Fail with the causal prerequisite instead of a generic scheduler error."""

        if scheduled_state in {"ready", "repair_ready", "stale"}:
            return
        if target_stage == "runtime_integration" and scheduled_state == "waiting":
            raise TestNodeError(
                "test_final_node_candidate_predecessor_inactive",
                (
                    "runtime_integration cannot start because its exact CandidateBuild "
                    "predecessor is not active in this freshly frozen final graph; run the "
                    "current ImplementationPlan and CandidateBuild first, then retry Integration"
                ),
            )
        raise TestNodeError(
            "test_final_node_target_not_dispatchable",
            (
                f"{target_stage} is {scheduled_state or 'absent'} in the freshly frozen "
                "final graph; inspect its committed predecessors before dispatching it"
            ),
        )


class DiagnosticSuccessorNodeRunner:
    """Run one new semantic node after a real diagnostic Architecture commit.

    Architecture is the only topology-discovery boundary.  A historic
    ``test-node`` target can therefore prove Architecture itself, but it
    cannot name the downstream physical semantic coordinates until the fresh
    Architecture output has been compiled.  This narrow runner closes that
    gap without weakening the regular ``test-node`` contract:

    * it operates only from a previously marked ``test-node-*`` state copy;
    * it makes one fresh marked child copy, excluding mutable scope budgets
      and execution workspaces just as ``test-node`` does;
    * it accepts only a passed, non-releasable Architecture commit from that
      copied ancestor closure;
    * framework code derives and freezes the Design graph from its exact
      coupling plan; and
    * it dispatches exactly one *new* semantic coordinate with no existing
      head, so no captured target output can be replayed.

    Normal schedulers, normal epoch freezing, final topology derivation, and
    Registry publication never opt into diagnostic ancestors.
    """

    _ALLOWED_STAGES = frozenset({"shared_tool_semantics", "world_behavior"})

    def __init__(
        self,
        *,
        config: FoundryConfig,
        diagnostic_state_root: Path,
        executor_factory: TestNodeExecutorFactory | None = None,
    ) -> None:
        self.config = config
        self.diagnostic_state_root = diagnostic_state_root
        self.executor_factory = executor_factory

    async def run(
        self,
        *,
        scope_id: str,
        target_coordinate: str,
    ) -> DiagnosticSuccessorNodeResult:
        source_diagnostic_root = self._resolve_diagnostic_root()
        diagnostic_root = _prepare_diagnostic_clone(
            source_root=source_diagnostic_root,
            diagnostic_parent=TestNodeRunner(config=self.config)._diagnostic_parent(source_diagnostic_root),
            marker_error_code="test_successor_diagnostic_marker_failed",
            marker_message="fresh diagnostic successor state could not be marked",
        )
        # Import lazily for the same composition-root cycle boundary as
        # ``TestNodeRunner``.
        from agent_world.app import build_application
        from agent_world.designer.models import ToolCouplingPlan

        app = build_application(self.config.model_copy(update={"state_root": diagnostic_root}))
        heads = app.controller.work_control
        architecture_coordinate = self._architecture_coordinate(heads.read_scope_heads(scope_id))
        frozen = TestNodeRunner(config=self.config)._load_frozen_target(
            app=app,
            scope_id=scope_id,
            target=architecture_coordinate,
            allow_diagnostic_ancestor_closure=True,
        )
        bootstrap_epoch_ref, bootstrap_epoch = TestNodeRunner._epoch_for_manifest(
            app.controller.artifacts,
            frozen.manifest_ref,
        )
        if bootstrap_epoch.epoch_kind != "bootstrap":
            raise TestNodeError(
                "test_successor_bootstrap_epoch_invalid",
                "diagnostic successor requires a frozen bootstrap Architecture graph",
            )

        architecture_attempt = app.artifacts.get_json(
            frozen.source_head.attempt_ref,
            WorkAttempt,
        )
        diagnostic_architecture = heads.require_diagnostic_commit(
            definition=frozen.definition,
            input_refs=architecture_attempt.input_refs,
            artifacts=app.controller.artifacts,
        )
        if diagnostic_architecture is None:
            raise TestNodeError(
                "test_successor_architecture_not_diagnostic",
                "the retained Architecture head is not one passed diagnostic test-node commit",
            )
        architecture_commit, architecture_commit_ref = diagnostic_architecture
        architecture_source_ref = self._one_consumer_ref(
            architecture_commit,
            artifact_type="design.world_architecture_source",
        )
        coupling_ref = self._one_consumer_ref(
            architecture_commit,
            artifact_type="design.tool_coupling_plan",
        )
        coupling_plan = app.controller.artifacts.get_json(coupling_ref, ToolCouplingPlan)
        try:
            design_definitions, modeling = derive_final_design_definitions(
                scope_id=scope_id,
                bootstrap_definitions=frozen.graph.definitions,
                architecture_source_ref=architecture_source_ref,
                coupling_plan=coupling_plan,
                agent_wall_seconds=frozen.definition.proposal_policy.budget.wall_seconds,
                agent_token_limit=frozen.definition.proposal_policy.budget.llm_tokens,
            )
            verifier_plan = verifier_plan_work_definition(
                scope_id=scope_id,
                modeling_coordinate=modeling.coordinate,
            )
            design_graph = compile_design_work_graph(
                scope_id=scope_id,
                design_definitions=design_definitions,
                modeling_definition=modeling,
                verifier_plan_definition=verifier_plan,
                strict_input_contracts=True,
            )
        except WorkGraphError as exc:
            raise TestNodeError(
                "test_successor_topology_derivation_failed",
                "the diagnostic Architecture output cannot derive one closed two-tool Design graph",
            ) from exc

        target = self._resolve_fresh_semantic_coordinate(design_graph, target_coordinate)
        if heads.read_head(target) is not None:
            raise TestNodeError(
                "test_successor_target_already_captured",
                "a diagnostic successor never archives or replays an existing target head",
            )
        epochs = WorkGraphEpochRuntime(
            artifacts=app.controller.artifacts,
            heads=heads,
        )
        try:
            _design_manifest, design_manifest_ref, _design_epoch, design_epoch_ref = (
                epochs.freeze_design(
                    context_ref=frozen.context_ref,
                    bootstrap_epoch_ref=bootstrap_epoch_ref,
                    graph=design_graph,
                    topology_id=(
                        "topology:test-successor-design:"
                        f"{scope_id}:{architecture_commit_ref.content_hash.removeprefix('sha256:')[:16]}"
                    ),
                    allow_diagnostic_predecessors=True,
                )
            )
        except (WorkGraphError, WorkResumeError) as exc:
            raise TestNodeError(
                "test_successor_epoch_freeze_failed",
                "the diagnostic Architecture commit cannot retain one closed Design epoch",
            ) from exc

        design_manifest = app.controller.artifacts.get_json(
            design_manifest_ref,
            WorkGraphManifest,
        )
        budget = TestNodeRunner._single_attempt_budget(design_graph.require(target))
        run_token = uuid.uuid4().hex
        run_id = f"test-successor-node:{run_token}"
        trace_id = run_id
        runtime = _diagnostic_work_runtime(
            app=app,
            heads=heads,
            budget=budget,
            trace_id=trace_id,
            run_id=run_id,
            continuation_workspace_root=diagnostic_root / "runs",
        )
        scheduler = WorkScheduler(
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            heads=heads,
            artifacts=app.controller.artifacts,
            runtime=runtime,
            allow_diagnostic_ancestors=True,
        )
        try:
            resolved = scheduler.resolve_inputs(target)
        except WorkResumeError as exc:
            raise TestNodeError(
                "test_successor_ancestor_closure_missing",
                "the fresh semantic target lacks one exact committed diagnostic ancestor",
            ) from exc
        root_span = app.telemetry.start_span(
            trace_id=trace_id,
            component="controller",
            operation="test_successor_node.dispatch",
            run_id=run_id,
            node=design_graph.require(target).work_id,
            input_refs=resolved.all_input_refs,
            attributes={"diagnostic_only": True, "releasable": False},
        )
        app.telemetry.activate_trace(
            trace_id=trace_id,
            run_id=run_id,
            parent_span_id=root_span.span_id,
        )
        workspace_root = diagnostic_root / "runs" / "test-successor-node" / run_token
        workspace_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        definition = design_graph.require(target)
        execution = TestNodeExecution(
            app=app,
            graph=design_graph,
            manifest=design_manifest,
            manifest_ref=design_manifest_ref,
            definition=definition,
            context=frozen.context,
            context_ref=frozen.context_ref,
            runtime=runtime,
            workspace_root=workspace_root,
            run_id=run_id,
            trace_id=trace_id,
        )
        executor = (
            self.executor_factory(execution)
            if self.executor_factory is not None
            else TestNodeRunner(config=self.config)._production_executor(execution)
        )
        dispatch = await _dispatch_diagnostic_target(
            scheduler=scheduler,
            coordinate=target,
            executor=executor,
            runtime=runtime,
            definition=definition,
            app=app,
            scope_id=scope_id,
            run_id=run_id,
            span=root_span,
            dispatch_error_code="test_successor_node_dispatch_error",
            interrupt_code="test_successor_node_dispatch_interrupted",
            cancel_code="test_successor_node_dispatch_cancelled",
            nonterminal_code="test_successor_nonterminal_dispatch_failure",
            settled_statuses=_TERMINAL_WORK_HEAD_STATUSES,
        )
        if dispatch is not None:
            root_span.finish(
                status="passed" if dispatch.after_state == "committed" else "failed",
                output_refs=tuple(
                    ref for ref in (dispatch.commit_ref, dispatch.evaluation_ref) if ref is not None
                ),
            )
            app.telemetry.flush()

        head = heads.read_head(target)
        if head is None or head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise TestNodeError(
                "test_successor_no_terminal_result",
                "the fresh semantic dispatch did not produce one terminal Work head",
            )
        attempt = app.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.validation_report_ref is None or head.evaluation_ref is None:
            raise TestNodeError(
                "test_successor_missing_validation_report",
                "the fresh semantic dispatch did not persist ValidationReport and evaluation",
            )
        report = app.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        evaluation = app.artifacts.get_json(head.evaluation_ref)
        commit = (
            app.artifacts.get_json(head.commit_ref, WorkCommit)
            if head.commit_ref is not None
            else None
        )
        if not (
            attempt.diagnostic_only
            and not attempt.releasable
            and report.diagnostic_only
            and not report.releasable
            and bool(evaluation.get("diagnostic_only"))
            and not bool(evaluation.get("releasable"))
            and (commit is None or (commit.diagnostic_only and not commit.releasable))
        ):
            raise TestNodeError(
                "test_successor_diagnostic_marking_failed",
                "the fresh semantic result was not fully diagnostic-only and non-releasable",
            )
        return DiagnosticSuccessorNodeResult(
            source_scope_id=scope_id,
            target_coordinate=target,
            source_diagnostic_state_root=str(source_diagnostic_root),
            diagnostic_state_root=str(diagnostic_root),
            bootstrap_epoch_ref=bootstrap_epoch_ref,
            design_epoch_ref=design_epoch_ref,
            design_manifest_ref=design_manifest_ref,
            architecture_attempt_ref=frozen.source_head.attempt_ref,
            architecture_commit_ref=architecture_commit_ref,
            target_attempt_ref=head.attempt_ref,
            target_evaluation_ref=head.evaluation_ref,
            target_commit_ref=head.commit_ref,
            status=cast(
                Literal["committed", "failed", "needs_human", "interrupted"],
                head.status,
            ),
            validation_report=report,
            proposal_executions=TestNodeRunner._proposal_executions(
                app.controller.artifacts,
                attempt,
            ),
            actual_usage=attempt.observed_actual,
            unknown_usage=attempt.unknown_upper_bound,
            conservative_usage=attempt.conservative_committed,
            reserved_budget=budget,
            scene=TestNodeRunner._scene_payload(app, scope_id=scope_id, run_id=run_id),
        )

    def _resolve_diagnostic_root(self) -> Path:
        return _resolve_marked_diagnostic_root(
            self.diagnostic_state_root, prefix="test_successor"
        )

    @staticmethod
    def _architecture_coordinate(heads: tuple[WorkControlHead, ...]) -> WorkCoordinate:
        matches = tuple(
            head.coordinate
            for head in heads
            if (
                head.coordinate.component == "design"
                and head.coordinate.stage == "world_architecture"
                and head.status == "committed"
            )
        )
        if len(matches) != 1:
            raise TestNodeError(
                "test_successor_architecture_ambiguous",
                "diagnostic successor requires exactly one committed Architecture head",
            )
        return matches[0]

    @classmethod
    def _resolve_fresh_semantic_coordinate(
        cls,
        graph: GenerationWorkGraph,
        supplied: str,
    ) -> WorkCoordinate:
        expected: WorkCoordinate | None = None
        if supplied.startswith("{"):
            try:
                expected = WorkCoordinate.model_validate(json.loads(supplied))
            except (ValueError, TypeError):
                raise TestNodeError(
                    "test_successor_coordinate_invalid",
                    "target coordinate must be an exact coordinate key or JSON object",
                ) from None
        matches = tuple(
            definition.coordinate
            for definition in graph.definitions
            if (
                definition.coordinate.component == "design"
                and definition.coordinate.stage in cls._ALLOWED_STAGES
                and (
                    definition.coordinate.coordinate_key == supplied
                    or TestNodeRunner._coordinate_label(definition.coordinate) == supplied
                    or TestNodeRunner._coordinate_scene_label(definition.coordinate) == supplied
                    or (expected is not None and definition.coordinate == expected)
                )
            )
        )
        if len(matches) != 1:
            candidates = tuple(
                sorted(
                    TestNodeRunner._coordinate_label(definition.coordinate)
                    for definition in graph.definitions
                    if (
                        definition.coordinate.component == "design"
                        and definition.coordinate.stage in cls._ALLOWED_STAGES
                    )
                )
            )
            available = ", ".join(candidates) if candidates else "none"
            raise TestNodeError(
                "test_successor_coordinate_not_fresh_semantic",
                (
                    "target must be one newly derived shared or physical ToolSemantics coordinate; "
                    "use its exact hash, coordinate JSON, "
                    "component|stage|artifact_slot|group_id|shard_id, or the "
                    "component.stage.artifact_slot label shown by observe; "
                    f"available diagnostic successor coordinates: {available}"
                ),
            )
        return matches[0]

    @staticmethod
    def _one_consumer_ref(commit: WorkCommit, *, artifact_type: str) -> ArtifactRef:
        matches = tuple(ref for ref in commit.consumer_refs if ref.artifact_type == artifact_type)
        if len(matches) != 1:
            raise TestNodeError(
                "test_successor_architecture_output_invalid",
                "diagnostic Architecture commit lacks one exact derived topology artifact",
            )
        return matches[0]


__all__ = [
    "DiagnosticDescendantNodeResult",
    "DiagnosticDescendantNodeRunner",
    "DiagnosticFinalNodeResult",
    "DiagnosticFinalNodeRunner",
    "DiagnosticPlanDerivedDesignNodeResult",
    "DiagnosticPlanDerivedDesignNodeRunner",
    "DiagnosticSuccessorNodeResult",
    "DiagnosticSuccessorNodeRunner",
    "DiagnosticTaskCurriculumJoinResult",
    "DiagnosticTaskCurriculumJoinRunner",
    "DiagnosticTaskRequirementNodeResult",
    "DiagnosticTaskRequirementNodeRunner",
    "DiagnosticRuntimeImplementationOverride",
    "DiagnosticRuntimeProfileOverride",
    "DiagnosticWorldPlanNodeResult",
    "DiagnosticWorldPlanNodeRunner",
    "TestNodeError",
    "TestNodeExecution",
    "TestNodeResult",
    "TestNodeRunner",
]

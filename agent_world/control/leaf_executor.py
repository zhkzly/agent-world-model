"""One-attempt Scheduler leaf execution for the production WorkGraph.

This module is intentionally small but strict.  A component callback may run
one real Agent/tool/subprocess operation and return immutable output evidence;
it never receives a retry budget, a repair router, or authority to dispatch a
different Work coordinate.  The surrounding framework turns that one physical
attempt into the durable Proposal/Validation/Assurance/Feedback chain.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from pydantic import ValidationError

from agent_world.contracts import ArtifactRef, BudgetUsage, canonical_json_bytes, sha256_digest

from .validation import pydantic_validation_diagnostic
from .work import (
    AssuranceProbeResult,
    AssuranceReport,
    FeedbackEvaluation,
    ParentRepairRoute,
    ProposalExecution,
    RepairAction,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    WorkCoordinate,
    WorkDefinition,
)
from .work_runtime import WorkControlRuntime, WorkRuntimeError
from .work_scheduler import WorkExecutionContext


@dataclass(frozen=True, slots=True)
class AgentExecutionProvenance:
    """Non-transcript provenance required for one Agent proposal execution."""

    invocation_id: str
    provider: str
    model: str
    profile_digest: str
    output_schema_digest: str
    continuation_commitment: str | None = None


@dataclass(frozen=True, slots=True)
class AgentCorrectionBrief:
    """Safe, data-only diagnostics for one Scheduler-authorized Agent correction.

    This is intentionally *not* a projection of :class:`RepairAction`.  The
    Agent needs the rejected output conditions, not repair policy, budgets,
    graph routing, authority, or release state.  Keeping that distinction in a
    typed boundary prevents a prompt from accidentally becoming a second
    control plane.
    """

    issues: tuple[ValidationIssue, ...]

    def __post_init__(self) -> None:
        if not self.issues:
            raise ValueError("AgentCorrectionBrief requires at least one issue")
        if any(issue.severity != "blocker" for issue in self.issues):
            raise ValueError("AgentCorrectionBrief may contain only blocking issues")

    def prompt_projection(self) -> dict[str, object]:
        """Return a bounded causal diagnostic view for one replacement proposal.

        The immutable ValidationReport retains every exact issue for audit,
        progress comparison and routing.  A model, however, cannot reliably
        act on a hundred repeated locations in one correction turn.  Grouping
        by the actual violated condition keeps the correction complete while
        presenting representative paths and total scope rather than a lossy
        arbitrary prefix of the report.
        """

        grouped: dict[tuple[str, str, str], list[ValidationIssue]] = {}
        for issue in self.issues:
            key = (issue.code, issue.violated_condition, issue.expected_category)
            grouped.setdefault(key, []).append(issue)

        clusters: list[dict[str, object]] = []
        for (code, condition, expected), issues in sorted(grouped.items()):
            patterns = tuple(
                dict.fromkeys(
                    tuple("*" if isinstance(part, int) else part for part in issue.path)
                    for issue in issues
                )
            )
            representatives = tuple(dict.fromkeys(issue.path for issue in issues))[:3]
            clusters.append(
                {
                    "code": code,
                    "violated_condition": condition,
                    "expected_category": expected,
                    "occurrence_count": len(issues),
                    "affected_path_patterns": patterns[:12],
                    "representative_paths": representatives,
                }
            )
        return {
            "total_blocking_issues": len(self.issues),
            "clusters": tuple(clusters),
        }


@dataclass(frozen=True, slots=True)
class AgentProposalOutcome:
    """Measured result retained while a leaf materializes one Agent proposal.

    An Agent turn can succeed and then encounter a deterministic framework
    failure while its typed output is compiled or persisted. The Scheduler must
    still settle that real turn exactly once. This task-local record is not an
    Artifact and grants no authority; it only preserves known provenance and
    usage for a terminal post-proposal failure.
    """

    agent: AgentExecutionProvenance
    observed_actual: BudgetUsage
    unknown_upper_bound: BudgetUsage


_ACTIVE_AGENT_PROPOSAL_OUTCOME: ContextVar[AgentProposalOutcome | None] = ContextVar(
    "agent_world_active_agent_proposal_outcome",
    default=None,
)


def record_agent_proposal_outcome(
    *,
    agent: AgentExecutionProvenance,
    observed_actual: BudgetUsage,
    unknown_upper_bound: BudgetUsage,
) -> None:
    """Make one completed Agent turn available to its enclosing leaf kernel."""

    _ACTIVE_AGENT_PROPOSAL_OUTCOME.set(
        AgentProposalOutcome(
            agent=agent,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
        )
    )


@dataclass(frozen=True, slots=True)
class LeafProposal:
    """A single leaf proposal result before framework validation.

    ``output_refs`` must be the full Artifact closure produced by this leaf.
    No bool success field exists: an empty or malformed closure is converted to
    a deterministic failed validation rather than being trusted as a component
    terminal state.
    """

    output_refs: tuple[ArtifactRef, ...]
    subject_refs: tuple[ArtifactRef, ...]
    observed_actual: BudgetUsage = BudgetUsage()
    unknown_upper_bound: BudgetUsage = BudgetUsage()
    agent: AgentExecutionProvenance | None = None
    validation_issues: tuple[ValidationIssue, ...] = ()
    validation_evidence_refs: tuple[ArtifactRef, ...] = ()
    child_commit_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class LeafAssurance:
    """Measured framework-derived results for the declared real probes."""

    probe_results: tuple[AssuranceProbeResult, ...]
    runtime_commitment: str
    observed_actual: BudgetUsage = BudgetUsage()
    unknown_upper_bound: BudgetUsage = BudgetUsage()


class LeafExecutionFailure(RuntimeError):
    """A leaf's safe terminal failure, including real Agent provenance if any."""

    def __init__(
        self,
        *,
        code: str,
        category: str,
        observed_actual: BudgetUsage | None = None,
        unknown_upper_bound: BudgetUsage | None = None,
        agent: AgentExecutionProvenance | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(category)
        self.code = code
        self.category = category
        self.observed_actual = observed_actual or BudgetUsage()
        self.unknown_upper_bound = unknown_upper_bound or BudgetUsage()
        self.agent = agent
        # An execution error is not automatically a useful retry.  The leaf
        # declares that fact; only WorkControlRuntime can authorize a retry.
        self.retryable = retryable


class LeafValidationFailure(RuntimeError):
    """A real proposal ran, but deterministic validation rejected its semantics.

    The Agent invocation is still a completed, auditable proposal.  The failure
    becomes a normal actionable ``ValidationReport`` rather than an opaque
    infrastructure error, so only the Scheduler's RepairPolicy may authorize a
    fresh physical correction attempt.
    """

    def __init__(
        self,
        *,
        issues: tuple[ValidationIssue, ...],
        output_commitment: str,
        category: str,
        observed_actual: BudgetUsage | None = None,
        unknown_upper_bound: BudgetUsage | None = None,
        agent: AgentExecutionProvenance | None = None,
        evidence_refs: tuple[ArtifactRef, ...] = (),
        parent_repair_target: WorkCoordinate | None = None,
    ) -> None:
        super().__init__(category)
        if not issues:
            raise ValueError("LeafValidationFailure requires at least one safe issue")
        self.issues = issues
        self.output_commitment = output_commitment
        self.category = category
        self.observed_actual = observed_actual or BudgetUsage()
        self.unknown_upper_bound = unknown_upper_bound or BudgetUsage()
        self.agent = agent
        self.evidence_refs = evidence_refs
        self.parent_repair_target = parent_repair_target


type ProposalRunner = Callable[
    [WorkExecutionContext, WorkAttempt, str], Awaitable[LeafProposal]
]
type AssuranceRunner = Callable[
    [WorkExecutionContext, WorkAttempt, LeafProposal], Awaitable[LeafAssurance]
]


class SchedulerLeafExecutor:
    """Execute one Scheduler-authorized leaf attempt and no more.

    Calls that raise are not allowed to escape as an untracked component retry.
    The executor commits a safe ``control.leaf_failure_evidence`` Artifact and
    evaluates the exact WorkAttempt as infrastructure error.  The Scheduler can
    then decide whether its declared RepairPolicy permits a physical retry.
    """

    def __init__(self, *, runtime: WorkControlRuntime) -> None:
        self.runtime = runtime

    def agent_correction_brief(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> AgentCorrectionBrief | None:
        """Compile one authorized semantic failure into safe Agent input.

        A Scheduler repair is useful only if the target Agent receives the
        field-addressable conditions that caused it.  Conversely, a
        ``RepairAction`` is framework authority and must never be disclosed as
        prompt data.  This method follows the immutable authority chain and
        exposes only blocker diagnostics.  Infrastructure retries deliberately
        receive no brief because there is no rejected semantic candidate to
        correct.
        """

        repair_action_ref = context.repair_action_ref
        if repair_action_ref is None:
            return None
        action = self.runtime.artifacts.get_json(repair_action_ref, RepairAction)
        if (
            action.definition_digest != definition.definition_digest
            or action.target_coordinate != definition.coordinate
            or context.coordinate != definition.coordinate
        ):
            raise WorkRuntimeError("repair action does not bind this Agent WorkDefinition")
        if action.decision == "infrastructure_retry":
            return None
        if action.decision not in {"local_correction", "parent_correction"}:
            raise WorkRuntimeError("Agent correction brief requires semantic repair authority")

        evaluation = self.runtime.artifacts.get_json(
            action.source_evaluation_ref,
            FeedbackEvaluation,
        )
        if (
            evaluation.coordinate != definition.coordinate
            or evaluation.work_id != definition.work_id
            or evaluation.validation_report_ref is None
            or evaluation.status != "failed"
        ):
            raise WorkRuntimeError("repair source evaluation does not bind this Agent Work")
        report = self.runtime.artifacts.get_json(
            evaluation.validation_report_ref,
            ValidationReport,
        )
        blockers = tuple(issue for issue in report.issues if issue.severity == "blocker")
        if (
            report.coordinate != definition.coordinate
            or report.attempt_id != evaluation.attempt_id
            or not report.repair_actionable
            or not blockers
        ):
            raise WorkRuntimeError("repair source report is not actionable for this Agent Work")
        return AgentCorrectionBrief(issues=blockers)

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
        proposal_runner: ProposalRunner,
        assurance_runner: AssuranceRunner | None = None,
    ) -> None:
        """Run exactly one physical attempt already opened by ``WorkScheduler``."""

        # The Scheduler always includes the immutable graph root alongside
        # parent outputs.  Do not discard it after the first node: otherwise a
        # child WorkAttempt's identity omits the request/permission/budget
        # context that its leaf is allowed to dereference.
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        # A Scheduler worker can execute many leaves sequentially in one task.
        # Do not attribute an earlier real Agent turn to a later failure.
        _ACTIVE_AGENT_PROPOSAL_OUTCOME.set(None)
        attempt, dispatch_id = self._start_proposal(definition, input_refs)
        try:
            proposal = await proposal_runner(context, attempt, dispatch_id)
        except LeafValidationFailure as exc:
            await self._finish_validation_failure(
                definition=definition,
                input_refs=input_refs,
                attempt=attempt,
                issues=exc.issues,
                output_commitment=exc.output_commitment,
                category=exc.category,
                observed_actual=exc.observed_actual,
                unknown_upper_bound=exc.unknown_upper_bound,
                agent=exc.agent,
                evidence_refs=exc.evidence_refs,
                parent_repair_target=exc.parent_repair_target,
            )
            return
        except LeafExecutionFailure as exc:
            await self._finish_exception(
                definition=definition,
                input_refs=input_refs,
                attempt=attempt,
                code=exc.code,
                category=exc.category,
                observed_actual=exc.observed_actual,
                unknown_upper_bound=exc.unknown_upper_bound,
                agent=exc.agent,
                retryable=exc.retryable,
            )
            return
        except asyncio.CancelledError:
            await self._finish_exception(
                definition=definition,
                input_refs=input_refs,
                attempt=attempt,
                # An Agent process may have started before the SDK can return
                # invocation/profile provenance.  The durable record must
                # preserve that interruption and reserve the unknown proposal
                # upper bound rather than strand the WorkHead or fabricate an
                # invocation id.
                code="process_interrupted_cancelled",
                category="cancelled external execution before Agent provenance",
            )
            raise
        except ValidationError as exc:
            # Code and real-tool leaves often construct a typed framework
            # Artifact immediately after completing their operation.  Treat a
            # schema failure there as a deterministic validation result with
            # safe field paths, rather than flattening it into the opaque
            # ``leaf_execution_error`` that previously starved the repair
            # router of causal information.  Agent leaves must translate the
            # error before returning so their real invocation provenance stays
            # attached to the proposal execution.
            if definition.proposal_policy.executor == "agent":
                outcome = _ACTIVE_AGENT_PROPOSAL_OUTCOME.get()
                if outcome is not None:
                    await self._finish_exception(
                        definition=definition,
                        input_refs=input_refs,
                        attempt=attempt,
                        code="agent_postproposal_schema_error",
                        category="post-proposal framework schema materialization failed",
                        observed_actual=outcome.observed_actual,
                        unknown_upper_bound=outcome.unknown_upper_bound,
                        agent=outcome.agent,
                        retryable=False,
                    )
                    return
                await self._finish_exception(
                    definition=definition,
                    input_refs=input_refs,
                    attempt=attempt,
                    code="agent_leaf_untranslated_schema_error",
                    category="Agent leaf failed to translate a schema error",
                )
                return
            diagnostic = pydantic_validation_diagnostic(
                exc,
                owner_component=definition.coordinate.component,
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
            )
            await self._finish_validation_failure(
                definition=definition,
                input_refs=input_refs,
                attempt=attempt,
                issues=tuple(
                    ValidationIssue(
                        code=issue.code,
                        path=issue.location,
                        violated_condition=(issue.violated_condition or issue.message),
                        expected_category=(
                            issue.expected_category
                            or "the closed framework contract at this field"
                        ),
                        retryable=issue.retryable,
                    )
                    for issue in diagnostic.issues
                ),
                output_commitment=sha256_digest(
                    canonical_json_bytes(
                        {
                            "definition_digest": definition.definition_digest,
                            "input_refs": tuple(ref.revision_id for ref in input_refs),
                            "failure_kind": "pydantic_validation",
                        }
                    )
                ),
                category=f"deterministic_{diagnostic.validation_phase}_schema",
                observed_actual=BudgetUsage(),
                unknown_upper_bound=BudgetUsage(),
                agent=None,
                evidence_refs=(),
                parent_repair_target=None,
            )
            return
        except Exception as exc:
            outcome = _ACTIVE_AGENT_PROPOSAL_OUTCOME.get()
            if outcome is not None:
                await self._finish_exception(
                    definition=definition,
                    input_refs=input_refs,
                    attempt=attempt,
                    code="agent_postproposal_framework_error",
                    category=(
                        "post-proposal framework materialization failed: "
                        f"{type(exc).__name__}"
                    ),
                    observed_actual=outcome.observed_actual,
                    unknown_upper_bound=outcome.unknown_upper_bound,
                    agent=outcome.agent,
                    retryable=False,
                )
                return
            await self._finish_exception(
                definition=definition,
                input_refs=input_refs,
                attempt=attempt,
                code="leaf_execution_error",
                category=type(exc).__name__,
            )
            return

        if proposal.child_commit_refs and proposal.child_commit_refs != context.parent_commit_refs:
            raise WorkRuntimeError(
                "aggregate leaf must bind exactly the Scheduler-resolved child WorkCommits"
            )
        self._finish_proposal_and_validation(
            definition=definition,
            input_refs=input_refs,
            attempt=attempt,
            proposal=proposal,
        )
        current = self.runtime.heads.read_head(definition.coordinate)
        if current is None:
            raise WorkRuntimeError("leaf WorkHead disappeared after validation")
        if current.status != "running":
            # A failed validation has already created a RepairAction or a
            # terminal block.  The leaf must return to the Scheduler here.
            return
        if definition.assurance_policy is None:
            self._evaluate_passing_leaf(definition=definition, proposal=proposal)
            return
        if assurance_runner is None:
            raise WorkRuntimeError("assurance WorkDefinition requires an assurance runner")

        assurance_attempt = self._start_assurance(definition)
        try:
            assurance = await assurance_runner(context, assurance_attempt, proposal)
        except asyncio.CancelledError:
            await self._finish_assurance_exception(
                definition=definition,
                code="assurance_cancelled",
                category="cancelled real execution",
            )
            raise
        except Exception as exc:
            await self._finish_assurance_exception(
                definition=definition,
                code="assurance_execution_error",
                category=type(exc).__name__,
            )
            return
        self._finish_assurance_and_evaluate(
            definition=definition,
            proposal=proposal,
            assurance=assurance,
        )

    def _start_proposal(
        self,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorkAttempt, str]:
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            head = self.runtime.heads.read_head(definition.coordinate)
            if head is None or head.status != "running" or head.active_operation_ref is not None:
                raise WorkRuntimeError("Scheduler leaf was not opened for one running attempt")
            attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            if attempt.input_refs != input_refs:
                raise WorkRuntimeError("Scheduler leaf inputs differ from its WorkAttempt")
            head = self.runtime.schedule_operation(
                lock,
                definition=definition,
                kind="proposal",
                replay_mode=definition.proposal_policy.replay_mode,
                elapsed_wall_seconds=0,
            )
            dispatch_id = f"dispatch:{attempt.attempt_id}:proposal"
            self.runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=dispatch_id,
            )
            return attempt, dispatch_id

    def _finish_proposal_and_validation(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        attempt: WorkAttempt,
        proposal: LeafProposal,
    ) -> None:
        if not proposal.output_refs or not proposal.subject_refs:
            raise WorkRuntimeError(
                "a leaf proposal must bind non-empty output and subject closures"
            )
        if not set(proposal.subject_refs) <= {*input_refs, *proposal.output_refs}:
            raise WorkRuntimeError("leaf subjects must be immutable inputs or produced outputs")
        if len(set(proposal.output_refs)) != len(proposal.output_refs) or len(
            set(proposal.subject_refs)
        ) != len(proposal.subject_refs):
            raise WorkRuntimeError("leaf output and subject Artifact refs must be unique")
        if definition.proposal_policy.executor == "agent" and proposal.agent is None:
            raise WorkRuntimeError("Agent leaf must bind real invocation/profile provenance")
        if definition.proposal_policy.executor != "agent" and proposal.agent is not None:
            raise WorkRuntimeError("non-Agent leaf cannot claim Agent execution provenance")
        now = datetime.now(UTC)
        # ``ProposalExecution`` has one commitment field while WorkCommit owns
        # the complete output closure.  Bind the first, deterministic primary
        # output here; the following ValidationReport and WorkCommit still bind
        # every produced ArtifactRef.
        output_commitment = proposal.output_refs[0].content_hash
        execution = ProposalExecution(
            execution_id=f"proposal-execution:{attempt.attempt_id}",
            attempt_id=attempt.attempt_id,
            executor=definition.proposal_policy.executor,
            executor_revision_id=definition.proposal_policy.executor_revision_id,
            operation=definition.proposal_policy.operation,
            status="completed",
            invocation_id=proposal.agent.invocation_id if proposal.agent else None,
            provider=proposal.agent.provider if proposal.agent else None,
            model=proposal.agent.model if proposal.agent else None,
            profile_digest=proposal.agent.profile_digest if proposal.agent else None,
            output_schema_digest=(proposal.agent.output_schema_digest if proposal.agent else None),
            continuation_commitment=(
                proposal.agent.continuation_commitment if proposal.agent else None
            ),
            output_commitment=output_commitment,
            observed_actual=proposal.observed_actual,
            unknown_upper_bound=proposal.unknown_upper_bound,
            conservative_committed=self._total_usage(
                proposal.observed_actual, proposal.unknown_upper_bound
            ),
            started_at=attempt.started_at or now,
            finished_at=now,
            duration_ms=max(0, int((now - (attempt.started_at or now)).total_seconds() * 1000)),
        )
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            self.runtime.checkpoint_proposal(
                lock,
                definition=definition,
                execution=execution,
                output_refs=proposal.output_refs,
            )
            head = self.runtime.schedule_operation(
                lock,
                definition=definition,
                kind="validation",
                replay_mode="deterministic",
                elapsed_wall_seconds=0,
                input_refs=tuple(dict.fromkeys((*input_refs, *proposal.output_refs))),
            )
            head = self.runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=f"dispatch:{attempt.attempt_id}:validation",
            )
            current_attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            report = self._validation_report(
                definition=definition,
                attempt=current_attempt,
                proposal=proposal,
            )
            self.runtime.checkpoint_validation(
                lock,
                definition=definition,
                report=report,
                observed_actual=BudgetUsage(),
            )

    def _evaluate_passing_leaf(self, *, definition: WorkDefinition, proposal: LeafProposal) -> None:
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            head = self.runtime.heads.read_head(definition.coordinate)
            if head is None:
                raise WorkRuntimeError("leaf WorkHead disappeared before evaluation")
            attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            if attempt.validation_report_ref is None:
                raise WorkRuntimeError("leaf validation did not persist its report")
            report = self.runtime.artifacts.get_json(
                attempt.validation_report_ref,
                ValidationReport,
            )
            self.runtime.evaluate(
                lock,
                definition=definition,
                report=report,
                output_refs=proposal.output_refs,
                child_commit_refs=proposal.child_commit_refs,
                elapsed_wall_seconds=0,
            )

    async def _finish_validation_failure(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        attempt: WorkAttempt,
        issues: tuple[ValidationIssue, ...],
        output_commitment: str,
        category: str,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
        agent: AgentExecutionProvenance | None,
        evidence_refs: tuple[ArtifactRef, ...],
        parent_repair_target: WorkCoordinate | None,
    ) -> None:
        """Persist an actionable failed validation without fabricating an output Artifact."""

        if definition.proposal_policy.executor == "agent" and agent is None:
            raise WorkRuntimeError("Agent validation failure lacks real invocation provenance")
        if definition.proposal_policy.executor != "agent" and agent is not None:
            raise WorkRuntimeError("non-Agent validation failure cannot claim Agent provenance")
        safe_evidence_ref = self._validation_failure_evidence(
            definition=definition,
            attempt=attempt,
            issues=issues,
            category=category,
        )
        route_refs: tuple[ArtifactRef, ...] = ()
        if parent_repair_target is not None:
            route = ParentRepairRoute(
                route_id=f"parent-repair-route:{attempt.attempt_id}",
                source_coordinate=definition.coordinate,
                source_attempt_id=attempt.attempt_id,
                source_definition_digest=definition.definition_digest,
                target_coordinate=parent_repair_target,
                issue_identities=tuple(item.normalized_identity for item in issues),
                routed_at=datetime.now(UTC),
            )
            route_refs = (
                self.runtime.artifacts.put_json(
                    artifact_id=route.route_id,
                    artifact_type="control.parent_repair_route",
                    value=route,
                    dependencies=attempt.input_refs,
                ),
            )
        now = datetime.now(UTC)
        execution = ProposalExecution(
            execution_id=f"proposal-execution:{attempt.attempt_id}",
            attempt_id=attempt.attempt_id,
            executor=definition.proposal_policy.executor,
            executor_revision_id=definition.proposal_policy.executor_revision_id,
            operation=definition.proposal_policy.operation,
            status="completed",
            invocation_id=agent.invocation_id if agent else None,
            provider=agent.provider if agent else None,
            model=agent.model if agent else None,
            profile_digest=agent.profile_digest if agent else None,
            output_schema_digest=agent.output_schema_digest if agent else None,
            continuation_commitment=(
                agent.continuation_commitment if agent else None
            ),
            output_commitment=output_commitment,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            conservative_committed=self._total_usage(observed_actual, unknown_upper_bound),
            started_at=attempt.started_at or now,
            finished_at=now,
            duration_ms=max(0, int((now - (attempt.started_at or now)).total_seconds() * 1000)),
        )
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            self.runtime.checkpoint_proposal(lock, definition=definition, execution=execution)
            head = self.runtime.schedule_operation(
                lock,
                definition=definition,
                kind="validation",
                replay_mode="deterministic",
                elapsed_wall_seconds=0,
                input_refs=input_refs,
            )
            head = self.runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=f"dispatch:{attempt.attempt_id}:validation",
            )
            current_attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            report = ValidationReport(
                report_id=f"validation-report:{current_attempt.attempt_id}",
                attempt_id=current_attempt.attempt_id,
                coordinate=definition.coordinate,
                policy_id=definition.validation_policy.policy_id,
                policy_digest=definition.validation_policy.content_digest(),
                subject_refs=(),
                status="failed",
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
                issues=issues,
                evidence_refs=tuple(
                    dict.fromkeys((*evidence_refs, safe_evidence_ref, *route_refs))
                ),
                diagnostic_quality=(
                    "actionable" if all(issue.actionable for issue in issues) else "insufficient"
                ),
                evaluated_at=datetime.now(UTC),
            )
            self.runtime.checkpoint_validation(
                lock,
                definition=definition,
                report=report,
                observed_actual=BudgetUsage(),
            )
            self.runtime.evaluate(
                lock,
                definition=definition,
                report=report,
                elapsed_wall_seconds=0,
            )

    def _start_assurance(self, definition: WorkDefinition) -> WorkAttempt:
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            head = self.runtime.schedule_operation(
                lock,
                definition=definition,
                kind="assurance",
                replay_mode="non_replayable",
                elapsed_wall_seconds=0,
            )
            head = self.runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=f"dispatch:{head.attempt_ref.artifact_id}:assurance",
            )
            return self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)

    def _finish_assurance_and_evaluate(
        self,
        *,
        definition: WorkDefinition,
        proposal: LeafProposal,
        assurance: LeafAssurance,
    ) -> None:
        policy = definition.assurance_policy
        if policy is None:  # pragma: no cover - guarded by caller
            raise WorkRuntimeError("leaf assurance has no policy")
        if tuple(item.probe_id for item in assurance.probe_results) != policy.probe_ids:
            raise WorkRuntimeError("assurance results do not cover the declared exact probes")
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            head = self.runtime.heads.read_head(definition.coordinate)
            if head is None:
                raise WorkRuntimeError("leaf WorkHead disappeared before assurance settlement")
            attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            report = AssuranceReport(
                report_id=f"assurance-report:{attempt.attempt_id}",
                attempt_id=attempt.attempt_id,
                coordinate=definition.coordinate,
                policy_id=policy.policy_id,
                policy_digest=policy.content_digest(),
                runtime_profile_id=policy.runtime_profile_id,
                runtime_commitment=assurance.runtime_commitment,
                evidence_freshness=policy.evidence_freshness,
                probe_results=assurance.probe_results,
                status=self._assurance_status(assurance.probe_results),
                evaluated_at=datetime.now(UTC),
            )
            self.runtime.checkpoint_assurance(
                lock,
                definition=definition,
                report=report,
                observed_actual=assurance.observed_actual,
                unknown_upper_bound=assurance.unknown_upper_bound,
            )
            current = self.runtime.heads.read_head(definition.coordinate)
            assert current is not None
            current_attempt = self.runtime.artifacts.get_json(current.attempt_ref, WorkAttempt)
            if current_attempt.validation_report_ref is None:
                raise WorkRuntimeError("assurance leaf lost its exact validation report")
            validation = self.runtime.artifacts.get_json(
                current_attempt.validation_report_ref,
                ValidationReport,
            )
            self.runtime.evaluate(
                lock,
                definition=definition,
                report=validation,
                output_refs=proposal.output_refs,
                child_commit_refs=proposal.child_commit_refs,
                elapsed_wall_seconds=0,
            )

    async def _finish_exception(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        attempt: WorkAttempt,
        code: str,
        category: str,
        observed_actual: BudgetUsage | None = None,
        unknown_upper_bound: BudgetUsage | None = None,
        agent: AgentExecutionProvenance | None = None,
        retryable: bool = True,
    ) -> None:
        if (
            definition.proposal_policy.executor == "agent"
            and agent is None
            and not (
                code.startswith("preflight_")
                or code.startswith("process_interrupted")
            )
        ):
            raise WorkRuntimeError(
                "Agent leaf failures must bind real invocation/profile provenance"
            )
        if definition.proposal_policy.executor != "agent" and agent is not None:
            raise WorkRuntimeError("non-Agent leaf failure cannot claim Agent provenance")
        evidence_ref = self._failure_evidence(
            definition,
            attempt,
            code,
            category,
            retryable=retryable,
        )
        now = datetime.now(UTC)
        actual = observed_actual or BudgetUsage()
        unknown = unknown_upper_bound or self._proposal_unknown(definition)
        execution = ProposalExecution(
            execution_id=f"proposal-execution:{attempt.attempt_id}",
            attempt_id=attempt.attempt_id,
            executor=definition.proposal_policy.executor,
            executor_revision_id=definition.proposal_policy.executor_revision_id,
            operation=definition.proposal_policy.operation,
            status=("interrupted" if code.startswith("process_interrupted") else "failed"),
            invocation_id=agent.invocation_id if agent else None,
            provider=agent.provider if agent else None,
            model=agent.model if agent else None,
            profile_digest=agent.profile_digest if agent else None,
            output_schema_digest=agent.output_schema_digest if agent else None,
            continuation_commitment=agent.continuation_commitment if agent else None,
            error_code=code,
            observed_actual=actual,
            unknown_upper_bound=unknown,
            conservative_committed=self._total_usage(actual, unknown),
            started_at=attempt.started_at or now,
            finished_at=now,
            duration_ms=max(0, int((now - (attempt.started_at or now)).total_seconds() * 1000)),
        )
        with self.runtime.heads.exclusive(definition.coordinate) as lock:
            self.runtime.checkpoint_proposal(lock, definition=definition, execution=execution)
            head = self.runtime.schedule_operation(
                lock,
                definition=definition,
                kind="validation",
                replay_mode="deterministic",
                elapsed_wall_seconds=0,
                input_refs=input_refs,
            )
            head = self.runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id=f"dispatch:{attempt.attempt_id}:validation",
            )
            current_attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            report = ValidationReport(
                report_id=f"validation-report:{current_attempt.attempt_id}:error",
                attempt_id=current_attempt.attempt_id,
                coordinate=definition.coordinate,
                policy_id=definition.validation_policy.policy_id,
                policy_digest=definition.validation_policy.content_digest(),
                subject_refs=(),
                status="error",
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
                issues=(
                    ValidationIssue(
                        code=code,
                        path=("operation",),
                        violated_condition=category[:512],
                        expected_category=(
                            "one fresh execution under the declared replay policy"
                            if retryable
                            else "a configuration or permission change outside this attempt"
                        ),
                        retryable=retryable,
                    ),
                ),
                evidence_refs=(evidence_ref,),
                diagnostic_quality="actionable" if retryable else "insufficient",
                evaluated_at=datetime.now(UTC),
            )
            self.runtime.checkpoint_validation(
                lock,
                definition=definition,
                report=report,
                observed_actual=BudgetUsage(),
            )
            self.runtime.evaluate(
                lock,
                definition=definition,
                report=report,
                elapsed_wall_seconds=0,
            )

    async def _finish_assurance_exception(
        self,
        *,
        definition: WorkDefinition,
        code: str,
        category: str,
    ) -> None:
        policy = definition.assurance_policy
        if policy is None:  # pragma: no cover - guarded by caller
            raise WorkRuntimeError("leaf assurance has no policy")
        with self.runtime.heads.exclusive(definition.coordinate):
            head = self.runtime.heads.read_head(definition.coordinate)
            if head is None:
                raise WorkRuntimeError("leaf WorkHead disappeared during assurance error")
            attempt = self.runtime.artifacts.get_json(head.attempt_ref, WorkAttempt)
            evidence_ref = self._failure_evidence(definition, attempt, code, category)
            failed = LeafAssurance(
                probe_results=tuple(
                    AssuranceProbeResult(
                        probe_id=probe_id,
                        status="error",
                        evidence_refs=(evidence_ref,),
                        issue_codes=(code,),
                    )
                    for probe_id in policy.probe_ids
                ),
                runtime_commitment=sha256_digest(
                    canonical_json_bytes((attempt.attempt_id, code, category))
                ),
                unknown_upper_bound=BudgetUsage(
                    process_calls=policy.budget.process_calls,
                    evaluation_episodes=policy.budget.evaluation_episodes,
                ),
            )
        self._finish_assurance_and_evaluate(
            definition=definition,
            proposal=LeafProposal(
                output_refs=attempt.output_refs,
                subject_refs=attempt.output_refs,
            ),
            assurance=failed,
        )

    def _validation_report(
        self,
        *,
        definition: WorkDefinition,
        attempt: WorkAttempt,
        proposal: LeafProposal,
    ) -> ValidationReport:
        issues = proposal.validation_issues
        return ValidationReport(
            report_id=f"validation-report:{attempt.attempt_id}",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=proposal.subject_refs,
            status="failed" if issues else "passed",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            passed_check_ids=(() if issues else (definition.required_claim_id,)),
            issues=issues,
            evidence_refs=proposal.validation_evidence_refs,
            diagnostic_quality=(
                "actionable"
                if issues and all(item.actionable for item in issues)
                else "insufficient"
                if issues
                else "not_applicable"
            ),
            evaluated_at=datetime.now(UTC),
        )

    def _failure_evidence(
        self,
        definition: WorkDefinition,
        attempt: WorkAttempt,
        code: str,
        category: str,
        *,
        retryable: bool = True,
    ) -> ArtifactRef:
        return self.runtime.artifacts.put_json(
            artifact_id=f"leaf-failure:{attempt.attempt_id}:{code}",
            artifact_type="control.leaf_failure_evidence",
            value={
                "attempt_id": attempt.attempt_id,
                "coordinate": definition.coordinate.model_dump(mode="json"),
                "failure_code": code,
                "failure_category": category[:120],
                "retryable_infrastructure": retryable,
            },
            dependencies=attempt.input_refs,
        )

    def _validation_failure_evidence(
        self,
        *,
        definition: WorkDefinition,
        attempt: WorkAttempt,
        issues: tuple[ValidationIssue, ...],
        category: str,
    ) -> ArtifactRef:
        return self.runtime.artifacts.put_json(
            artifact_id=f"leaf-validation:{attempt.attempt_id}",
            artifact_type="control.leaf_validation_evidence",
            value={
                "attempt_id": attempt.attempt_id,
                "coordinate": definition.coordinate.model_dump(mode="json"),
                "failure_category": category[:120],
                "issues": tuple(item.model_dump(mode="json") for item in issues),
            },
            dependencies=attempt.input_refs,
        )

    @staticmethod
    def _assurance_status(
        results: Sequence[AssuranceProbeResult],
    ) -> Literal["passed", "failed", "inconclusive", "error"]:
        statuses = {item.status for item in results}
        if "error" in statuses:
            return "error"
        if "failed" in statuses:
            return "failed"
        if "inconclusive" in statuses:
            return "inconclusive"
        return "passed"

    @staticmethod
    def _total_usage(actual: BudgetUsage, unknown: BudgetUsage) -> BudgetUsage:
        return BudgetUsage.model_validate(
            {
                field: getattr(actual, field) + getattr(unknown, field)
                for field in BudgetUsage.model_fields
                if field != "schema_version"
            }
        )

    @staticmethod
    def _proposal_unknown(definition: WorkDefinition) -> BudgetUsage:
        budget = definition.proposal_policy.budget
        return BudgetUsage(
            llm_tokens=budget.llm_tokens,
            agent_turns=budget.agent_turns,
            search_calls=budget.search_calls,
            tool_calls=budget.tool_calls,
            process_calls=budget.process_calls,
        )


__all__ = [
    "AgentExecutionProvenance",
    "LeafAssurance",
    "LeafExecutionFailure",
    "LeafValidationFailure",
    "LeafProposal",
    "SchedulerLeafExecutor",
]

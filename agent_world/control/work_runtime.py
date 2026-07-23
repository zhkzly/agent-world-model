"""Executable clean-break WorkGraph authority used before component migration.

The runtime is intentionally independent of Designer/Builder/Judge.  Components
may execute one proposal and one deterministic validator, but only this service
may reserve the next attempt, publish a boundary evaluation, authorize repair,
or create the resumable WorkCommit.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    canonical_json_bytes,
    sha256_digest,
)

from .budget import DurableLeaseBudgetCoordinator, LeaseBudgetLedger
from .continuation_store import NodeContinuationRecord, NodeContinuationStore
from .models import BudgetLease
from .telemetry import ComponentName, MetricPoint, TelemetryStore
from .work import (
    AssuranceExecution,
    AssuranceProbeResult,
    AssuranceReport,
    FeedbackEvaluation,
    OperationBudget,
    OperationKind,
    OperationRun,
    ParentRepairRoute,
    ProposalExecution,
    RepairAction,
    ReplayMode,
    ValidationExecution,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkDefinition,
    repair_epoch_digest,
    work_input_fingerprint,
)
from .work_repair import WorkRepairDenied, WorkRepairLedger
from .work_store import WorkControlHead, WorkControlLock, WorkControlStore


class WorkRuntimeError(RuntimeError):
    """A component attempted to bypass WorkGraph lifecycle authority."""


def _add_usage(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    return BudgetUsage.model_validate(
        {
            field_name: getattr(left, field_name) + getattr(right, field_name)
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
        }
    )


def restore_work_budget_ledger(
    artifacts: ArtifactWriter,
    *,
    reserved: Budget,
    scope_id: str,
) -> LeaseBudgetLedger:
    """Restore only leases owned by one exact WorkGraph scope after failure."""

    refs = artifacts.list_revisions()
    owned_lease_ids: set[str] = set()
    for ref in refs:
        if ref.artifact_type != "control.operation_run":
            continue
        operation = artifacts.get_json(ref, OperationRun)
        if operation.coordinate.scope_id == scope_id:
            owned_lease_ids.add(operation.budget_lease_ref.artifact_id)
    grouped: dict[str, list[BudgetLease]] = {}
    for ref in refs:
        if (
            ref.artifact_type != "control.budget_lease"
            or "budget-lease:" not in ref.artifact_id
            or ref.artifact_id not in owned_lease_ids
        ):
            continue
        grouped.setdefault(ref.artifact_id, []).append(artifacts.get_json(ref, BudgetLease))
    leases: list[BudgetLease] = []
    for lease_id, revisions in grouped.items():
        if any(item.lease_id != lease_id for item in revisions):
            raise WorkRuntimeError("BudgetLease Artifact identity mismatch")
        terminal = tuple(item for item in revisions if item.status != "active")
        if len(set(item.content_digest() for item in terminal)) > 1:
            raise WorkRuntimeError("BudgetLease has conflicting terminal revisions")
        if terminal:
            leases.append(terminal[0])
            continue
        if len(set(item.content_digest() for item in revisions)) > 1:
            raise WorkRuntimeError("BudgetLease has conflicting active revisions")
        leases.append(revisions[0])
    return LeaseBudgetLedger(reserved, leases=tuple(leases))


class WorkControlRuntime:
    """Persist one exact WorkAttempt lifecycle under a held coordinate lock."""

    def __init__(
        self,
        *,
        artifacts: ArtifactWriter,
        heads: WorkControlStore,
        budget: LeaseBudgetLedger,
        repairs: WorkRepairLedger | None = None,
        repair_scope_id: str | None = None,
        continuations: NodeContinuationStore | None = None,
        continuation_workspace_root: Path | None = None,
        telemetry: TelemetryStore | None = None,
        trace_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.heads = heads
        self.budget = budget
        self.budget_coordinator = DurableLeaseBudgetCoordinator(self.heads.root / "scope-budgets")
        self.repairs = (
            repairs
            if repairs is not None
            else WorkRepairLedger.restore(artifacts, scope_id=repair_scope_id)
            if repair_scope_id is not None
            else WorkRepairLedger()
        )
        self.continuations = continuations
        self.telemetry = telemetry
        self.trace_id = trace_id
        self.run_id = run_id
        if telemetry is not None and trace_id is None:
            raise WorkRuntimeError("Work telemetry requires one exact trace id")
        if continuations is not None and continuation_workspace_root is None:
            raise WorkRuntimeError(
                "a continuation store requires an explicit authorized workspace root"
            )
        self.continuation_workspace_root = (
            continuation_workspace_root.expanduser().resolve(strict=True)
            if continuation_workspace_root is not None
            else None
        )
        self._definitions: dict[str, WorkDefinition] = {}

    def register_definition(self, definition: WorkDefinition) -> WorkDefinition:
        """Register one exact definition for the eventual production manifest."""

        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        key = definition.coordinate.coordinate_key
        previous = self._definitions.get(key)
        if previous is not None and previous != definition:
            raise WorkRuntimeError("one WorkCoordinate received conflicting definitions")
        self._definitions[key] = definition
        return definition

    @property
    def definitions(self) -> tuple[WorkDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def proposal_execution_refs(
        self,
        attempt: WorkAttempt,
    ) -> tuple[ArtifactRef, ...]:
        """Return exact terminal proposal results from unified OperationRuns."""

        return tuple(
            operation.execution_ref
            for operation in (
                self.artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
            )
            if operation.kind == "proposal"
            and operation.status == "terminal"
            and operation.execution_ref is not None
        )

    def reactivate_historical_commit(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorkCommit, ArtifactRef] | None:
        """Recover an exact prior success without leaking an interrupted lease."""

        found = self.heads.find_historical_commit(
            definition=definition,
            input_refs=input_refs,
            artifacts=self.artifacts,
        )
        if found is None:
            return None
        _commit, commit_ref, _historical_attempt_ref = found
        head = self.heads.read_head(definition.coordinate)
        if head is None:
            return None
        if head.status == "repair_authorized" or (
            head.status == "running" and head.repair_action_ref is not None
        ):
            raise WorkRuntimeError(
                "historical cache recovery cannot replace active semantic repair authority"
            )
        if head.status == "running":
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            if head.active_operation_ref is not None:
                raise WorkRuntimeError(
                    "historical recovery requires active OperationRun reconciliation"
                )
            now = datetime.now(UTC)
            interrupted = attempt.model_copy(
                update={
                    "status": "interrupted",
                    "finished_at": now,
                    "failure_code": "historical_commit_reactivated",
                }
            )
            interrupted_ref = self._persist_attempt(
                interrupted,
                dependencies=(head.attempt_ref, commit_ref),
            )
            interrupted_head = head.model_copy(
                update={
                    "revision": head.revision + 1,
                    "status": "interrupted",
                    "attempt_ref": interrupted_ref,
                    "evaluation_ref": None,
                    "repair_action_ref": None,
                    "commit_ref": None,
                    "invalidated_by_refs": tuple(
                        dict.fromkeys((*head.invalidated_by_refs, commit_ref))
                    ),
                    "updated_at": now,
                }
            )
            self.heads.compare_and_swap(
                lock,
                expected_head=head,
                next_head=interrupted_head,
            )
        return self.heads.reactivate_historical_commit(
            lock,
            definition=definition,
            input_refs=input_refs,
            artifacts=self.artifacts,
        )

    def bind_repair_continuation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        record: NodeContinuationRecord,
    ) -> WorkControlHead:
        """Bind private same-session state to an already-authorized repair."""

        if self.continuations is None:
            raise WorkRuntimeError("repair continuation store is not configured")
        head = self.heads.read_head(definition.coordinate)
        if (
            head is None
            or head.status != "repair_authorized"
            or head.evaluation_ref is None
            or head.repair_action_ref is None
        ):
            raise WorkRuntimeError("continuation requires an authorized repair head")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        proposal_execution_refs = tuple(
            operation.execution_ref
            for operation in (
                self.artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
            )
            if operation.kind == "proposal"
            and operation.status == "terminal"
            and operation.execution_ref is not None
        )
        if (
            record.work_id != definition.work_id
            or record.attempt_id != attempt.attempt_id
            or record.definition_digest != definition.definition_digest
            or record.proposal_policy_digest != definition.proposal_policy.content_digest()
            or record.input_fingerprint != self.heads.input_fingerprint(attempt.input_refs)
            or record.source_report_ref != attempt.validation_report_ref
            or record.source_evaluation_ref != head.evaluation_ref
            or record.repair_action_ref != head.repair_action_ref
            or record.previous_execution_ref not in proposal_execution_refs
        ):
            raise WorkRuntimeError("continuation does not bind the exact repair authority")
        self.continuations.save(record)
        bound = attempt.model_copy(update={"continuation_commitment": record.record_commitment})
        bound_ref = self._persist_attempt(
            bound,
            dependencies=(
                head.attempt_ref,
                head.evaluation_ref,
                head.repair_action_ref,
                record.source_report_ref,
                record.previous_execution_ref,
            ),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "attempt_ref": bound_ref,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(lock, expected_head=head, next_head=next_head)

    def recover_pending_validation(
        self,
        *,
        definition: WorkDefinition,
        attempt: WorkAttempt,
    ) -> ValidationReport | None:
        """Recover a report durably written before a crash advanced the head."""

        candidates: dict[str, ValidationReport] = {}
        for ref in self.artifacts.list_revisions():
            if ref.artifact_type != "control.validation_report":
                continue
            report = self.artifacts.get_json(ref, ValidationReport)
            if (
                report.attempt_id == attempt.attempt_id
                and report.coordinate == definition.coordinate
                and report.policy_digest == definition.validation_policy.content_digest()
            ):
                candidates[report.content_digest()] = report
        if len(candidates) > 1:
            raise WorkRuntimeError("interrupted WorkAttempt has conflicting validation reports")
        return next(iter(candidates.values()), None)

    def reconcile_abandoned_operation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
    ) -> WorkControlHead:
        """Terminalize an operation whose previous owning process is gone.

        This is invoked only after the outer Direct-job lock established that
        no prior Scheduler process still owns the work graph.  A running
        operation is charged at its complete declared envelope as *unknown*;
        the immutable replay mode then decides whether the ordinary global
        infrastructure-repair policy may authorize one new attempt.  A merely
        scheduled operation has not crossed the dispatch fence and is
        cancelled with zero usage.

        The method deliberately writes a normal OperationRun, validation
        report and FeedbackEvaluation.  A crash is therefore observable and
        causal, not a hidden lease cleanup or an accidental new budget error.
        """

        head = self._require_running(definition)
        if head.active_operation_ref is None:
            return head
        operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
        if operation.status not in {"scheduled", "running"}:
            raise WorkRuntimeError("active Work operation is not recoverable")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if (
            operation.attempt_id != attempt.attempt_id
            or operation.coordinate != definition.coordinate
        ):
            raise WorkRuntimeError("active Work operation does not bind its current attempt")

        was_scheduled = operation.status == "scheduled"
        dispatched = operation.status == "running"
        recovery_code = (
            "process_interrupted_after_dispatch"
            if dispatched
            else "operation_cancelled_before_dispatch"
        )
        evidence_ref = self.artifacts.put_json(
            artifact_id=self._id("operation-recovery", operation.operation_run_id),
            artifact_type="control.operation_recovery_evidence",
            value={
                "attempt_id": attempt.attempt_id,
                "operation_run_id": operation.operation_run_id,
                "operation_kind": operation.kind,
                "prior_status": operation.status,
                "replay_mode": operation.replay_mode,
                "recovery_code": recovery_code,
            },
            dependencies=(head.attempt_ref, head.active_operation_ref),
        )

        # ``finish_operation`` is intentionally the one settlement path.  A
        # scheduled operation first gets a tiny framework recovery dispatch;
        # the original scheduled revision remains immutable evidence that no
        # external executor had started before cancellation.
        if was_scheduled:
            head = self.start_operation(
                lock,
                definition=definition,
                dispatch_id=self._id("recovery-dispatch", operation.operation_run_id),
            )
            if head.active_operation_ref is None:
                raise WorkRuntimeError("recovery dispatch did not retain its active operation")
            operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
            unknown = BudgetUsage()
        else:
            lease = self.artifacts.get_json(operation.budget_lease_ref, BudgetLease)
            unknown = BudgetUsage.model_validate(
                {
                    field_name: getattr(lease.reserved, field_name)
                    for field_name in BudgetUsage.model_fields
                    if field_name != "schema_version"
                }
            )

        now = datetime.now(UTC)
        allow_infrastructure_retry = (
            was_scheduled
            or operation.replay_mode in {"deterministic", "idempotent_with_key", "queryable"}
        )

        if operation.kind == "proposal":
            execution_code = (
                recovery_code
                if dispatched
                else "preflight_operation_cancelled_before_dispatch"
            )
            execution = ProposalExecution(
                execution_id=self._id("proposal-recovery", attempt.attempt_id),
                attempt_id=attempt.attempt_id,
                executor=definition.proposal_policy.executor,
                executor_revision_id=definition.proposal_policy.executor_revision_id,
                operation=definition.proposal_policy.operation,
                status="interrupted" if dispatched else "cancelled",
                error_code=execution_code,
                observed_actual=BudgetUsage(),
                unknown_upper_bound=unknown,
                conservative_committed=unknown,
                started_at=operation.started_at or now,
                finished_at=now,
                duration_ms=max(
                    0,
                    int((now - (operation.started_at or now)).total_seconds() * 1000),
                ),
            )
            head = self.checkpoint_proposal(lock, definition=definition, execution=execution)
            return self._complete_recovered_validation(
                lock,
                definition=definition,
                evidence_ref=evidence_ref,
                recovery_code=recovery_code,
                allow_infrastructure_retry=allow_infrastructure_retry,
            )

        if operation.kind == "validation":
            report = ValidationReport(
                report_id=self._id("validation-recovery-report", attempt.attempt_id),
                attempt_id=attempt.attempt_id,
                coordinate=definition.coordinate,
                policy_id=definition.validation_policy.policy_id,
                policy_digest=definition.validation_policy.content_digest(),
                status="error",
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
                issues=(
                    ValidationIssue(
                        code=recovery_code,
                        path=("operation", operation.kind),
                        violated_condition=(
                            "the prior owner stopped before the deterministic validation "
                            "operation could be settled"
                        ),
                        expected_category=(
                            "one safely replayable operation"
                            if allow_infrastructure_retry
                            else "manual recovery or a new generation request"
                        ),
                        retryable=allow_infrastructure_retry,
                    ),
                ),
                evidence_refs=(evidence_ref,),
                diagnostic_quality=(
                    "actionable" if allow_infrastructure_retry else "insufficient"
                ),
                evaluated_at=now,
            )
            self.checkpoint_validation(
                lock,
                definition=definition,
                report=report,
                observed_actual=BudgetUsage(),
                unknown_upper_bound=unknown,
            )
            return self.evaluate(
                lock,
                definition=definition,
                report=report,
                elapsed_wall_seconds=0,
                allow_infrastructure_retry=allow_infrastructure_retry,
            )

        policy = definition.assurance_policy
        if policy is None:
            raise WorkRuntimeError("assurance operation lacks its WorkDefinition policy")
        assurance_report = AssuranceReport(
            report_id=self._id("assurance-recovery-report", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=policy.policy_id,
            policy_digest=policy.content_digest(),
            runtime_profile_id=policy.runtime_profile_id,
            runtime_commitment=sha256_digest(
                canonical_json_bytes(
                    (attempt.attempt_id, operation.operation_run_id, recovery_code)
                )
            ),
            evidence_freshness=policy.evidence_freshness,
            probe_results=tuple(
                AssuranceProbeResult(
                    probe_id=probe_id,
                    status="error",
                    evidence_refs=(evidence_ref,),
                    issue_codes=(recovery_code,),
                )
                for probe_id in policy.probe_ids
            ),
            status="error",
            evaluated_at=now,
        )
        self.checkpoint_assurance(
            lock,
            definition=definition,
            report=assurance_report,
            observed_actual=BudgetUsage(),
            unknown_upper_bound=unknown,
        )
        updated = self.heads.read_head(definition.coordinate)
        if updated is None:
            raise WorkRuntimeError("assurance recovery lost its WorkHead")
        updated_attempt = self.artifacts.get_json(updated.attempt_ref, WorkAttempt)
        if updated_attempt.validation_report_ref is None:
            raise WorkRuntimeError("assurance recovery lacks its prior validation report")
        validation = self.artifacts.get_json(
            updated_attempt.validation_report_ref,
            ValidationReport,
        )
        return self.evaluate(
            lock,
            definition=definition,
            report=validation,
            output_refs=updated_attempt.output_refs,
            elapsed_wall_seconds=0,
            allow_infrastructure_retry=allow_infrastructure_retry,
        )

    def _complete_recovered_validation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        evidence_ref: ArtifactRef,
        recovery_code: str,
        allow_infrastructure_retry: bool,
    ) -> WorkControlHead:
        """Finish the deterministic half after a recovered proposal interruption."""

        head = self.heads.read_head(definition.coordinate)
        if head is None:
            raise WorkRuntimeError("proposal recovery lost its WorkHead")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        validation = self.schedule_operation(
            lock,
            definition=definition,
            kind="validation",
            replay_mode="deterministic",
            elapsed_wall_seconds=0,
            input_refs=attempt.input_refs,
        )
        validation = self.start_operation(
            lock,
            definition=definition,
            dispatch_id=self._id("recovery-validation", attempt.attempt_id),
        )
        current_attempt = self.artifacts.get_json(validation.attempt_ref, WorkAttempt)
        report = ValidationReport(
            report_id=self._id("proposal-recovery-report", current_attempt.attempt_id),
            attempt_id=current_attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            issues=(
                ValidationIssue(
                    code=recovery_code,
                    path=("operation", "proposal"),
                    violated_condition=(
                        "the prior owner stopped after dispatch and before the proposal "
                        "could be settled"
                    ),
                    expected_category=(
                        "one safely replayable operation"
                        if allow_infrastructure_retry
                        else "manual recovery or a new generation request"
                    ),
                    retryable=allow_infrastructure_retry,
                ),
            ),
            evidence_refs=(evidence_ref,),
            diagnostic_quality=(
                "actionable" if allow_infrastructure_retry else "insufficient"
            ),
            evaluated_at=datetime.now(UTC),
        )
        self.checkpoint_validation(
            lock,
            definition=definition,
            report=report,
            observed_actual=BudgetUsage(),
        )
        return self.evaluate(
            lock,
            definition=definition,
            report=report,
            elapsed_wall_seconds=0,
            allow_infrastructure_retry=allow_infrastructure_retry,
        )

    def execute_deterministic_boundary(
        self,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        subject_ref: ArtifactRef,
        output_refs: tuple[ArtifactRef, ...],
        child_commit_refs: tuple[ArtifactRef, ...] = (),
        issues: tuple[tuple[str, tuple[str | int, ...], str, str], ...] = (),
    ) -> WorkControlHead:
        """Execute one real in-process Claim boundary under the same authority chain."""

        definition = self.register_definition(definition)
        if definition.proposal_policy.executor != "code":
            raise WorkRuntimeError("deterministic boundary requires a code proposal policy")
        with self.heads.exclusive(definition.coordinate) as lock:
            active = self.heads.require_active_commit(
                definition=definition,
                input_refs=input_refs,
                artifacts=self.artifacts,
            )
            if active is None:
                active = self.reactivate_historical_commit(
                    lock,
                    definition=definition,
                    input_refs=input_refs,
                )
            if active is not None:
                head = self.heads.read_head(definition.coordinate)
                assert head is not None
                return head
            head = self.heads.read_head(definition.coordinate)
            if head is None:
                head = self.begin(
                    lock,
                    definition=definition,
                    input_refs=input_refs,
                    elapsed_wall_seconds=0,
                )
            elif (
                head.definition_digest != definition.definition_digest
                or head.input_fingerprint != self.heads.input_fingerprint(input_refs)
            ):
                head = self.supersede_stale(
                    lock,
                    definition=definition,
                    input_refs=input_refs,
                    previous=head,
                    elapsed_wall_seconds=0,
                )
            elif head.status != "running":
                raise WorkRuntimeError("deterministic boundary has a terminal stale head")
            if head.active_operation_ref is not None:
                raise WorkRuntimeError(
                    "deterministic boundary requires explicit OperationRun recovery"
                )
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            existing_operations = tuple(
                self.artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
            )
            if not any(
                item.kind == "proposal" and item.status == "terminal"
                for item in existing_operations
            ):
                head = self.schedule_operation(
                    lock,
                    definition=definition,
                    kind="proposal",
                    replay_mode="deterministic",
                    elapsed_wall_seconds=0,
                )
                head = self.start_operation(
                    lock,
                    definition=definition,
                    dispatch_id=self._id("dispatch", definition.work_id, "proposal"),
                )
                attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
                started_at = datetime.now(UTC)
                finished_at = datetime.now(UTC)
                execution = ProposalExecution(
                    execution_id=self._id("code-execution", attempt.attempt_id),
                    attempt_id=attempt.attempt_id,
                    executor="code",
                    executor_revision_id=definition.proposal_policy.executor_revision_id,
                    operation=definition.proposal_policy.operation,
                    status="completed",
                    output_commitment=subject_ref.content_hash,
                    observed_actual=BudgetUsage(
                        wall_seconds=max(
                            0.0,
                            (finished_at - started_at).total_seconds(),
                        )
                    ),
                    conservative_committed=BudgetUsage(
                        wall_seconds=max(
                            0.0,
                            (finished_at - started_at).total_seconds(),
                        )
                    ),
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=max(
                        0,
                        int((finished_at - started_at).total_seconds() * 1000),
                    ),
                )
                head = self.checkpoint_proposal(
                    lock,
                    definition=definition,
                    execution=execution,
                    output_refs=output_refs,
                )
            head = self.schedule_operation(
                lock,
                definition=definition,
                kind="validation",
                replay_mode="deterministic",
                elapsed_wall_seconds=0,
                input_refs=tuple(dict.fromkeys((*input_refs, *output_refs))),
            )
            head = self.start_operation(
                lock,
                definition=definition,
                dispatch_id=self._id("dispatch", definition.work_id, "validation"),
            )
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            validation_issues = tuple(
                ValidationIssue(
                    code=code,
                    path=path,
                    violated_condition=condition,
                    expected_category=expected,
                    retryable=False,
                )
                for code, path, condition, expected in issues
            )
            report = ValidationReport(
                report_id=self._id("code-report", attempt.attempt_id),
                attempt_id=attempt.attempt_id,
                coordinate=definition.coordinate,
                policy_id=definition.validation_policy.policy_id,
                policy_digest=definition.validation_policy.content_digest(),
                subject_refs=(
                    subject_ref,
                    *tuple(ref for ref in output_refs if ref != subject_ref),
                ),
                status="failed" if validation_issues else "passed",
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
                passed_check_ids=(() if validation_issues else (definition.required_claim_id,)),
                issues=validation_issues,
                evidence_refs=(subject_ref,),
                diagnostic_quality=("insufficient" if validation_issues else "not_applicable"),
                evaluated_at=datetime.now(UTC),
            )
            head = self.checkpoint_validation(
                lock,
                definition=definition,
                report=report,
                observed_actual=BudgetUsage(),
            )
            return self.evaluate(
                lock,
                definition=definition,
                report=report,
                output_refs=() if validation_issues else output_refs,
                elapsed_wall_seconds=0,
                child_commit_refs=child_commit_refs,
            )

    def schedule_operation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        kind: OperationKind,
        replay_mode: ReplayMode,
        elapsed_wall_seconds: float,
        input_refs: tuple[ArtifactRef, ...] | None = None,
    ) -> WorkControlHead:
        """Durably reserve and authorize one operation before any real work."""

        head = self._require_running(definition)
        if head.active_operation_ref is not None:
            raise WorkRuntimeError("WorkAttempt already has an active OperationRun")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        existing = tuple(
            self.artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
        )
        if any(item.status != "terminal" for item in existing):
            raise WorkRuntimeError("WorkAttempt contains an unreconciled OperationRun")
        if kind != "proposal" and not any(
            item.kind == "proposal" and item.status == "terminal" for item in existing
        ):
            raise WorkRuntimeError(f"{kind} cannot precede proposal execution")
        policy_id, policy_digest, operation_name, operation_budget = self._operation_policy(
            definition, kind
        )
        ordinal = 1 + sum(item.kind == kind for item in existing)
        operation_run_id = self._id(
            "operation-run",
            attempt.attempt_id,
            kind,
            str(ordinal),
        )
        requested = self._budget_from_operation(
            operation_budget,
            repair=kind == "proposal" and bool(attempt.repair_attempt_charge),
        )
        self.budget_coordinator.initialize(
            scope_id=definition.coordinate.scope_id,
            reserved=self.budget.reserved,
            leases=self.budget.leases,
        )
        lease = self.budget_coordinator.reserve(
            scope_id=definition.coordinate.scope_id,
            lease_id=self._id("operation-budget-lease", operation_run_id),
            owner_id=operation_run_id,
            requested=requested,
            elapsed_wall_seconds=elapsed_wall_seconds,
        )
        lease_ref = self.artifacts.put_json(
            artifact_id=lease.lease_id,
            artifact_type="control.budget_lease",
            value=lease,
        )
        now = datetime.now(UTC)
        operation = OperationRun(
            operation_run_id=operation_run_id,
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            kind=kind,
            ordinal=ordinal,
            revision=1,
            policy_id=policy_id,
            policy_digest=policy_digest,
            operation=operation_name,
            replay_mode=replay_mode,
            status="scheduled",
            input_refs=input_refs if input_refs is not None else attempt.input_refs,
            budget_lease_ref=lease_ref,
            scheduled_at=now,
        )
        operation_ref = self._persist_operation(
            operation,
            dependencies=(head.attempt_ref, lease_ref, *operation.input_refs),
        )
        checkpointed = attempt.model_copy(
            update={"operation_run_refs": (*attempt.operation_run_refs, operation_ref)}
        )
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(head.attempt_ref, operation_ref, lease_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "attempt_ref": attempt_ref,
                "active_operation_ref": operation_ref,
                "updated_at": now,
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def start_operation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        dispatch_id: str,
        backend_handle_commitment: str | None = None,
    ) -> WorkControlHead:
        """Install the dispatch fence; callers may execute only after this CAS."""

        head = self._require_running(definition)
        if head.active_operation_ref is None:
            raise WorkRuntimeError("WorkAttempt has no scheduled OperationRun")
        operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
        if operation.status != "scheduled":
            raise WorkRuntimeError("only a scheduled OperationRun may start")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        running = OperationRun.model_validate(
            operation.model_copy(
                update={
                    "revision": operation.revision + 1,
                    "status": "running",
                    "dispatch_id": dispatch_id,
                    "backend_handle_commitment": backend_handle_commitment,
                    "started_at": datetime.now(UTC),
                }
            ).model_dump(mode="python")
        )
        running_ref = self._persist_operation(
            running,
            dependencies=(head.active_operation_ref, head.attempt_ref),
        )
        checkpointed = self._replace_operation_ref(
            attempt,
            old=head.active_operation_ref,
            new=running_ref,
        )
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(head.attempt_ref, running_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "attempt_ref": attempt_ref,
                "active_operation_ref": running_ref,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def finish_operation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        execution: ProposalExecution | ValidationExecution | AssuranceExecution,
        output_refs: tuple[ArtifactRef, ...] = (),
    ) -> WorkControlHead:
        """Settle and adopt one real result without permitting stale runners."""

        head = self._require_running(definition)
        if head.active_operation_ref is None:
            raise WorkRuntimeError("WorkAttempt has no running OperationRun")
        operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
        if operation.status != "running":
            raise WorkRuntimeError("only a running OperationRun may finish")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if execution.attempt_id != attempt.attempt_id:
            raise WorkRuntimeError("execution belongs to another WorkAttempt")
        expected_type = {
            "proposal": ProposalExecution,
            "validation": ValidationExecution,
            "assurance": AssuranceExecution,
        }[operation.kind]
        if not isinstance(execution, expected_type):
            raise WorkRuntimeError("execution record does not match OperationRun kind")
        if operation.kind == "proposal":
            proposal = ProposalExecution.model_validate(execution.model_dump(mode="python"))
            if (
                proposal.executor != definition.proposal_policy.executor
                or proposal.executor_revision_id != definition.proposal_policy.executor_revision_id
                or proposal.operation != definition.proposal_policy.operation
                or (
                    proposal.executor == "agent"
                    and proposal.invocation_id is not None
                    and proposal.invocation_id != operation.dispatch_id
                )
            ):
                raise WorkRuntimeError("proposal result does not match dispatch authority")
            if (
                proposal.status == "completed"
                and output_refs
                and (proposal.output_commitment not in {ref.content_hash for ref in output_refs})
            ):
                raise WorkRuntimeError("proposal commitment does not bind produced output")
        execution_type = {
            "proposal": "control.proposal_execution",
            "validation": "control.validation_execution",
            "assurance": "control.assurance_execution",
        }[operation.kind]
        execution_ref = self.artifacts.put_json(
            artifact_id=self._id(execution_type.replace("control.", ""), execution.execution_id),
            artifact_type=execution_type,
            value=execution,
            dependencies=(head.active_operation_ref, *output_refs),
        )
        observed = execution.observed_actual
        if operation.kind == "proposal" and attempt.repair_attempt_charge:
            observed = observed.model_copy(update={"repair_attempts": observed.repair_attempts + 1})
        settled = self.budget_coordinator.settle(
            scope_id=definition.coordinate.scope_id,
            lease_id=operation.budget_lease_ref.artifact_id,
            observed_actual=observed,
            unknown_upper_bound=execution.unknown_upper_bound,
        )
        settled_ref = self.artifacts.put_json(
            artifact_id=settled.lease_id,
            artifact_type="control.budget_lease",
            value=settled,
            dependencies=(operation.budget_lease_ref, execution_ref),
        )
        terminal = OperationRun(
            **{
                **operation.model_dump(mode="python"),
                "revision": operation.revision + 1,
                "status": "terminal",
                "budget_lease_ref": settled_ref,
                "execution_ref": execution_ref,
                "output_refs": output_refs,
                "observed_actual": observed,
                "unknown_upper_bound": execution.unknown_upper_bound,
                "conservative_committed": _add_usage(
                    observed,
                    execution.unknown_upper_bound,
                ),
                "error_code": execution.error_code,
                "finished_at": execution.finished_at,
            }
        )
        terminal_ref = self._persist_operation(
            terminal,
            dependencies=(
                head.active_operation_ref,
                execution_ref,
                settled_ref,
                *output_refs,
            ),
        )
        checkpointed = self._replace_operation_ref(
            attempt,
            old=head.active_operation_ref,
            new=terminal_ref,
        )
        actual, unknown = self._attempt_usage(checkpointed)
        checkpointed = checkpointed.model_copy(
            update={
                "observed_actual": actual,
                "unknown_upper_bound": unknown,
                "conservative_committed": _add_usage(actual, unknown),
                "continuation_commitment": (
                    execution.continuation_commitment
                    if isinstance(execution, ProposalExecution)
                    else checkpointed.continuation_commitment
                ),
                "first_progress_at": (checkpointed.first_progress_at or execution.finished_at),
                "first_write_at": (
                    checkpointed.first_write_at or (execution.finished_at if output_refs else None)
                ),
            }
        )
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(head.attempt_ref, terminal_ref, execution_ref, settled_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "attempt_ref": attempt_ref,
                "active_operation_ref": None,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def begin(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        elapsed_wall_seconds: float,
    ) -> WorkControlHead:
        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        self._validate_slot_refs(definition, input_refs, direction="input")
        if self.heads.read_head(definition.coordinate) is not None:
            raise WorkRuntimeError("WorkCoordinate already has a durable head")
        definition_ref = self._persist_definition(definition, input_refs)
        self.budget_coordinator.initialize(
            scope_id=definition.coordinate.scope_id,
            reserved=self.budget.reserved,
            leases=self.budget.leases,
        )
        now = datetime.now(UTC)
        telemetry_trace_id, telemetry_span_id = self._start_attempt_span(
            definition,
            ordinal=1,
            input_refs=input_refs,
            repair_mode="initial",
        )
        attempt = WorkAttempt(
            attempt_id=self._id("attempt", definition.work_id, "1"),
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            ordinal=1,
            status="running",
            definition_digest=definition.definition_digest,
            proposal_policy_digest=definition.proposal_policy.content_digest(),
            validation_policy_digest=definition.validation_policy.content_digest(),
            assurance_policy_digest=(
                definition.assurance_policy.content_digest()
                if definition.assurance_policy is not None
                else None
            ),
            repair_policy_digest=definition.repair_policy.content_digest(),
            telemetry_trace_id=telemetry_trace_id,
            telemetry_span_id=telemetry_span_id,
            input_refs=input_refs,
            scheduled_at=now,
            started_at=now,
        )
        attempt_ref = self._persist_attempt(
            attempt,
            dependencies=(definition_ref, *input_refs),
        )
        head = WorkControlStore.new_head(
            definition=definition,
            input_refs=input_refs,
            attempt_ref=attempt_ref,
        )
        return self.heads.compare_and_swap(lock, expected_head=None, next_head=head)

    def supersede_stale(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        previous: WorkControlHead,
        elapsed_wall_seconds: float,
    ) -> WorkControlHead:
        """Start a new attempt after an exact definition/input invalidation."""

        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        input_fingerprint = self.heads.input_fingerprint(input_refs)
        if (
            previous.definition_digest == definition.definition_digest
            and previous.input_fingerprint == input_fingerprint
        ):
            raise WorkRuntimeError("unchanged terminal work cannot bypass repair authority")
        prior_attempt = self.artifacts.get_json(previous.attempt_ref, WorkAttempt)
        prior_attempt_ref = previous.attempt_ref
        if previous.status == "running":
            if previous.active_operation_ref is not None:
                raise WorkRuntimeError(
                    "stale Work with an active OperationRun must be reconciled first"
                )
            prior_attempt = prior_attempt.model_copy(
                update={
                    "status": "interrupted",
                    "finished_at": datetime.now(UTC),
                    "failure_code": "superseded_stale_execution",
                }
            )
            prior_attempt_ref = self._persist_attempt(
                prior_attempt,
                dependencies=(previous.attempt_ref,),
            )
            self._finish_attempt_span(
                prior_attempt,
                status="error",
                error_code=prior_attempt.failure_code,
            )
        ordinal = self._next_unused_attempt_ordinal(
            definition,
            minimum=prior_attempt.ordinal + 1,
        )
        definition_ref = self._persist_definition(definition, input_refs)
        now = datetime.now(UTC)
        telemetry_trace_id, telemetry_span_id = self._start_attempt_span(
            definition,
            ordinal=ordinal,
            input_refs=input_refs,
            repair_mode="stale_supersession",
        )
        attempt = WorkAttempt(
            attempt_id=self._id("attempt", definition.work_id, str(ordinal)),
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            ordinal=ordinal,
            parent_attempt_id=prior_attempt.attempt_id,
            status="running",
            definition_digest=definition.definition_digest,
            proposal_policy_digest=definition.proposal_policy.content_digest(),
            validation_policy_digest=definition.validation_policy.content_digest(),
            assurance_policy_digest=(
                definition.assurance_policy.content_digest()
                if definition.assurance_policy is not None
                else None
            ),
            repair_policy_digest=definition.repair_policy.content_digest(),
            telemetry_trace_id=telemetry_trace_id,
            telemetry_span_id=telemetry_span_id,
            input_refs=input_refs,
            scheduled_at=now,
            started_at=now,
        )
        invalidating_refs = tuple(
            dict.fromkeys(
                (
                    definition_ref,
                    *(input_refs if previous.input_fingerprint != input_fingerprint else ()),
                    previous.commit_ref or prior_attempt_ref,
                    previous.attempt_ref,
                )
            )
        )
        attempt_ref = self._persist_attempt(
            attempt,
            dependencies=tuple(
                dict.fromkeys(
                    (
                        prior_attempt_ref,
                        definition_ref,
                        *input_refs,
                        *invalidating_refs,
                    )
                )
            ),
        )
        next_head = WorkControlHead(
            scope_id=previous.scope_id,
            coordinate=definition.coordinate,
            work_id=definition.work_id,
            definition_digest=definition.definition_digest,
            acceptance_digest=definition.acceptance_digest,
            input_fingerprint=input_fingerprint,
            revision=previous.revision + 1,
            status="running",
            attempt_ref=attempt_ref,
            invalidated_by_refs=invalidating_refs,
            updated_at=now,
        )
        return self.heads.supersede_stale(
            lock,
            expected_head=previous,
            next_head=next_head,
        )

    def checkpoint_proposal(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        execution: ProposalExecution,
        output_refs: tuple[ArtifactRef, ...] = (),
    ) -> WorkControlHead:
        """Adopt a Proposal result only for the currently dispatched operation."""

        execution = ProposalExecution.model_validate(execution.model_dump(mode="python"))
        committed_head = self.finish_operation(
            lock,
            definition=definition,
            execution=execution,
            output_refs=output_refs,
        )
        checkpointed = self.artifacts.get_json(
            committed_head.attempt_ref,
            WorkAttempt,
        )
        self._record_proposal_progress(checkpointed, execution)
        return committed_head

    def checkpoint_validation(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        report: ValidationReport,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> WorkControlHead:
        """Finish a pre-authorized deterministic validator with its exact report."""

        head = self._require_running(definition)
        if head.active_operation_ref is None:
            raise WorkRuntimeError("validation was not authorized before execution")
        operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
        if operation.kind != "validation" or operation.status != "running":
            raise WorkRuntimeError("active operation is not a running validation")
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        report = ValidationReport.model_validate(report.model_dump(mode="python"))
        if (
            report.attempt_id != attempt.attempt_id
            or report.coordinate != definition.coordinate
            or report.policy_id != definition.validation_policy.policy_id
            or report.policy_digest != definition.validation_policy.content_digest()
        ):
            raise WorkRuntimeError("ValidationReport does not match active policy")
        report_ref = self.artifacts.put_json(
            artifact_id=self._id("validation-report", report.report_id),
            artifact_type="control.validation_report",
            value=report,
            dependencies=tuple(
                dict.fromkeys(
                    (
                        head.active_operation_ref,
                        *report.subject_refs,
                        *report.evidence_refs,
                    )
                )
            ),
        )
        unknown = unknown_upper_bound or BudgetUsage()
        now = datetime.now(UTC)
        execution = ValidationExecution(
            execution_id=self._id("validation-execution", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            policy_id=definition.validation_policy.policy_id,
            validator_id=definition.validation_policy.validator_id,
            validator_revision_id=definition.validation_policy.validator_revision_id,
            status="completed",
            evidence_refs=tuple(dict.fromkeys((report_ref, *report.evidence_refs))),
            observed_actual=observed_actual,
            unknown_upper_bound=unknown,
            conservative_committed=_add_usage(observed_actual, unknown),
            started_at=operation.started_at or now,
            finished_at=now,
            duration_ms=max(
                0,
                int((now - (operation.started_at or now)).total_seconds() * 1000),
            ),
        )
        committed_head = self.finish_operation(
            lock,
            definition=definition,
            execution=execution,
            output_refs=(report_ref,),
        )
        checkpointed = self.artifacts.get_json(committed_head.attempt_ref, WorkAttempt)
        checkpointed = checkpointed.model_copy(update={"validation_report_ref": report_ref})
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(committed_head.attempt_ref, report_ref),
        )
        next_head = committed_head.model_copy(
            update={
                "revision": committed_head.revision + 1,
                "attempt_ref": attempt_ref,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=committed_head,
            next_head=next_head,
        )

    def evaluate(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        report: ValidationReport,
        output_refs: tuple[ArtifactRef, ...] = (),
        child_commit_refs: tuple[ArtifactRef, ...] = (),
        elapsed_wall_seconds: float,
        repair_mutation_roots: tuple[str, ...] | None = None,
        allow_infrastructure_retry: bool = True,
    ) -> WorkControlHead:
        report = ValidationReport.model_validate(report.model_dump(mode="python"))
        # A successful validation proves the complete output closure and must
        # therefore satisfy every declared output slot.  A failed/error
        # proposal can legitimately have no output at all (for example an
        # isolated model transport failure before it produced JSON).  Applying
        # the success-only minimum slot cardinality to that case used to raise
        # after ValidationReport had been persisted, leaving the WorkAttempt
        # permanently ``running`` without its required FeedbackEvaluation.
        #
        # Do still validate any supplied failure outputs: a leaf must not use a
        # failure path to smuggle an artifact outside its declared contract.
        if output_refs or report.status == "passed":
            self._validate_slot_refs(definition, output_refs, direction="output")
        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if report.status == "error" and attempt.repair_action_ref is not None:
            action = self.artifacts.get_json(attempt.repair_action_ref, RepairAction)
            if action.decision in {"local_correction", "parent_correction"}:
                # A transport/infrastructure error during an already-authorized
                # semantic repair cannot establish semantic progress and must
                # not mint a second, independent infrastructure retry.  It
                # still has to pass through normal terminal settlement: that
                # closes the active repair ledger entry and prevents the
                # WorkHead from being stranded in ``running`` after its
                # Proposal/Validation operations were both settled.
                allow_infrastructure_retry = False
        if report.attempt_id != attempt.attempt_id:
            raise WorkRuntimeError("ValidationReport belongs to another WorkAttempt")
        if report.coordinate != definition.coordinate:
            raise WorkRuntimeError("ValidationReport coordinate mismatch")
        if report.policy_digest != definition.validation_policy.content_digest():
            raise WorkRuntimeError("ValidationReport policy digest mismatch")
        if head.active_operation_ref is not None:
            raise WorkRuntimeError("evaluation cannot precede OperationRun settlement")
        operations = tuple(
            self.artifacts.get_json(ref, OperationRun) for ref in attempt.operation_run_refs
        )
        proposal_runs = tuple(
            item for item in operations if item.kind == "proposal" and item.status == "terminal"
        )
        validation_runs = tuple(
            item for item in operations if item.kind == "validation" and item.status == "terminal"
        )
        if not proposal_runs or len(validation_runs) != 1:
            raise WorkRuntimeError(
                "evaluation requires terminal proposal and validation OperationRuns"
            )
        if attempt.validation_report_ref is None:
            raise WorkRuntimeError("validation OperationRun lacks its exact report")
        self.artifacts.require_exact_json(
            attempt.validation_report_ref,
            report,
            artifact_types=("control.validation_report",),
        )
        if attempt.validation_report_ref not in validation_runs[0].output_refs:
            raise WorkRuntimeError("validation OperationRun does not bind this report")
        if report.status == "passed" and (
            not output_refs
            or not set(output_refs) <= set(report.subject_refs)
            or not set(report.subject_refs) <= {*attempt.input_refs, *output_refs}
        ):
            raise WorkRuntimeError(
                "passing validation must bind the complete produced output closure"
            )
        if child_commit_refs and any(
            ref.artifact_type != "control.work_commit" for ref in child_commit_refs
        ):
            raise WorkRuntimeError("aggregate child refs must be WorkCommit Artifacts")
        if repair_mutation_roots is not None:
            if report.status != "failed" or not report.repair_actionable:
                raise WorkRuntimeError(
                    "repair mutation roots require one actionable failed validation"
                )
            if not repair_mutation_roots:
                raise WorkRuntimeError("repair mutation roots cannot be empty")
            allowed = set(definition.allowed_mutation_roots)
            if any(
                not any(
                    root == candidate or root.startswith(candidate.rstrip("/") + "/")
                    for candidate in allowed
                )
                for root in repair_mutation_roots
            ):
                raise WorkRuntimeError("repair mutation roots exceed WorkDefinition authority")
        if (
            report.status == "passed"
            and definition.required_claim_id not in report.passed_check_ids
        ):
            raise WorkRuntimeError("passing validation did not prove the required Claim")
        assurance_runs = tuple(
            item for item in operations if item.kind == "assurance" and item.status == "terminal"
        )
        assurance_executions = tuple(
            self.artifacts.get_json(item.execution_ref, AssuranceExecution)
            for item in assurance_runs
            if item.execution_ref is not None
        )
        assurance_report = (
            self.artifacts.get_json(attempt.assurance_report_ref, AssuranceReport)
            if attempt.assurance_report_ref is not None
            else None
        )
        if definition.assurance_policy is not None and (
            not assurance_executions or assurance_report is None
        ):
            raise WorkRuntimeError("boundary evaluation cannot precede required assurance")
        if assurance_report is not None:
            policy = definition.assurance_policy
            assert policy is not None
            if (
                assurance_report.attempt_id != attempt.attempt_id
                or assurance_report.coordinate != definition.coordinate
                or assurance_report.policy_id != policy.policy_id
                or assurance_report.policy_digest != policy.content_digest()
                or assurance_report.runtime_profile_id != policy.runtime_profile_id
                or assurance_report.evidence_freshness != policy.evidence_freshness
                or tuple(item.probe_id for item in assurance_report.probe_results)
                != policy.probe_ids
            ):
                raise WorkRuntimeError("AssuranceReport does not match AssurancePolicy")
        if report.status == "passed" and (
            any(execution.status != "completed" for execution in assurance_executions)
            or (assurance_report is not None and assurance_report.status != "passed")
        ):
            raise WorkRuntimeError("non-passing assurance can never satisfy a boundary Claim")
        assurance_evidence_refs = (
            assurance_report.evidence_refs if assurance_report is not None else ()
        )
        report_ref = attempt.validation_report_ref
        assert report_ref is not None
        validation_run = validation_runs[0]
        assert validation_run.execution_ref is not None
        validation_execution_ref = validation_run.execution_ref
        validation_execution = self.artifacts.get_json(
            validation_execution_ref,
            ValidationExecution,
        )
        self._record_boundary_execution_span(
            attempt,
            operation="work.validation",
            status="passed" if report.status in {"passed", "failed"} else "error",
            duration_ms=validation_execution.duration_ms,
            output_refs=(validation_execution_ref,),
            metrics=(
                MetricPoint(
                    "work.validation.issues",
                    len(report.issues),
                    "issues",
                    "framework",
                ),
            ),
        )
        evaluation = FeedbackEvaluation(
            evaluation_id=self._id("evaluation", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            claim_id=definition.required_claim_id,
            acceptance_digest=definition.acceptance_digest,
            policy_digest=definition.validation_policy.content_digest(),
            status=report.status,
            effect=definition.validation_policy.effect,
            readiness_effect=("satisfies" if report.status == "passed" else "blocks"),
            subject_refs=report.subject_refs,
            validation_report_ref=report_ref,
            assurance_report_ref=attempt.assurance_report_ref,
            assurance_evidence_refs=assurance_evidence_refs,
            evaluated_at=datetime.now(UTC),
        )
        evaluation_ref = self.artifacts.put_json(
            artifact_id=evaluation.evaluation_id,
            artifact_type="control.feedback_evaluation",
            value=evaluation,
            dependencies=(
                report_ref,
                head.attempt_ref,
                *attempt.operation_run_refs,
                *((attempt.assurance_report_ref,) if attempt.assurance_report_ref else ()),
                *assurance_evidence_refs,
                *output_refs,
            ),
        )
        self._complete_previous_repair(definition, attempt, report, report_ref)
        terminal_status = "succeeded" if report.status == "passed" else "failed"
        terminal = attempt.model_copy(
            update={
                "status": terminal_status,
                "output_refs": output_refs if report.status == "passed" else (),
                "child_commit_refs": (child_commit_refs if report.status == "passed" else ()),
                "validation_report_ref": report_ref,
                "feedback_evaluation_ref": evaluation_ref,
                "finished_at": datetime.now(UTC),
                "failure_code": (
                    None
                    if report.status == "passed"
                    else "validation_failed"
                    if report.status == "failed"
                    else "validation_error"
                ),
            }
        )
        terminal_ref = self._persist_attempt(
            terminal,
            dependencies=(
                head.attempt_ref,
                validation_execution_ref,
                report_ref,
                evaluation_ref,
                *child_commit_refs,
                *output_refs,
            ),
        )
        if report.status == "passed":
            commit = WorkCommit(
                commit_id=self._id("work-commit", attempt.attempt_id),
                work_id=definition.work_id,
                coordinate=definition.coordinate,
                attempt_id=attempt.attempt_id,
                definition_digest=definition.definition_digest,
                acceptance_digest=definition.acceptance_digest,
                validation_policy_digest=definition.validation_policy.content_digest(),
                input_refs=attempt.input_refs,
                validated_subject_refs=report.subject_refs,
                output_refs=output_refs,
                feedback_evaluation_ref=evaluation_ref,
                operation_run_refs=attempt.operation_run_refs,
                assurance_report_ref=attempt.assurance_report_ref,
                child_commit_refs=child_commit_refs,
                aggregate=bool(child_commit_refs),
                committed_at=datetime.now(UTC),
            )
            commit_ref = self.artifacts.put_json(
                artifact_id=commit.commit_id,
                artifact_type="control.work_commit",
                value=commit,
                dependencies=tuple(
                    dict.fromkeys(
                        (
                            terminal_ref,
                            *attempt.operation_run_refs,
                            *(
                                (attempt.assurance_report_ref,)
                                if attempt.assurance_report_ref
                                else ()
                            ),
                            evaluation_ref,
                            *attempt.input_refs,
                            *report.subject_refs,
                            *child_commit_refs,
                            *output_refs,
                        )
                    )
                ),
            )
            next_head = head.model_copy(
                update={
                    "revision": head.revision + 1,
                    "status": "committed",
                    "attempt_ref": terminal_ref,
                    "evaluation_ref": evaluation_ref,
                    "commit_ref": commit_ref,
                    "updated_at": datetime.now(UTC),
                }
            )
            committed_head = self.heads.compare_and_swap(
                lock,
                expected_head=head,
                next_head=next_head,
            )
            self._finish_attempt_span(
                terminal,
                status="passed",
                output_refs=output_refs,
            )
            return committed_head
        if report.status == "error" and not allow_infrastructure_retry:
            failed_head = self._fail_head(
                lock,
                head=head,
                terminal_ref=terminal_ref,
                evaluation_ref=evaluation_ref,
            )
            self._finish_attempt_span(
                terminal,
                status="error",
                error_code=terminal.failure_code,
            )
            return failed_head
        failed_head = self._authorize_next_or_fail(
            lock,
            head=head,
            terminal_attempt=terminal,
            terminal_ref=terminal_ref,
            definition=definition,
            report=report,
            report_ref=report_ref,
            evaluation_ref=evaluation_ref,
            elapsed_wall_seconds=elapsed_wall_seconds,
            repair_mutation_roots=repair_mutation_roots,
        )
        self._finish_attempt_span(
            terminal,
            status=("error" if report.status == "error" else "failed"),
            error_code=terminal.failure_code,
        )
        return failed_head

    def terminate_budget_exhausted(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        dimensions: tuple[str, ...],
    ) -> WorkControlHead:
        """Close a running attempt when code cannot reserve its next operation.

        Reservation happens before an ``OperationRun`` exists.  Therefore a
        normal ``evaluate()`` path cannot be used: it correctly requires a
        terminal proposal and validation operation.  This is instead a
        framework-owned scheduling boundary with its own safe evidence,
        ValidationReport and FeedbackEvaluation.  It never fabricates a
        proposal, a validator execution, or an Agent correction.
        """

        allowed_dimensions = set(Budget.model_fields) - {"schema_version"}
        normalized_dimensions = tuple(sorted(set(dimensions)))
        if not normalized_dimensions or any(
            item not in allowed_dimensions for item in normalized_dimensions
        ):
            raise WorkRuntimeError("budget exhaustion dimensions are invalid")
        head = self._require_running(definition)
        if head.active_operation_ref is not None:
            raise WorkRuntimeError(
                "budget exhaustion after an operation was scheduled requires operation settlement"
            )
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        now = datetime.now(UTC)
        evidence_ref = self.artifacts.put_json(
            artifact_id=self._id("budget-exhaustion", attempt.attempt_id),
            artifact_type="control.budget_exhaustion_evidence",
            value={
                "attempt_id": attempt.attempt_id,
                "coordinate": definition.coordinate.model_dump(mode="json"),
                "exhausted_dimensions": normalized_dimensions,
                "failure_code": "budget_exhausted",
            },
            dependencies=tuple(
                dict.fromkeys(
                    (
                        head.attempt_ref,
                        *(
                            (attempt.repair_action_ref,)
                            if attempt.repair_action_ref is not None
                            else ()
                        ),
                    )
                )
            ),
        )
        report = ValidationReport(
            report_id=self._id("budget-exhaustion-report", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            evidence_refs=(evidence_ref,),
            diagnostic_quality="insufficient",
            evaluated_at=now,
        )
        report_ref = self.artifacts.put_json(
            artifact_id=report.report_id,
            artifact_type="control.validation_report",
            value=report,
            dependencies=(head.attempt_ref, evidence_ref),
        )
        evaluation = FeedbackEvaluation(
            evaluation_id=self._id("budget-exhaustion-evaluation", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            claim_id=definition.required_claim_id,
            acceptance_digest=definition.acceptance_digest,
            policy_digest=definition.validation_policy.content_digest(),
            status="error",
            effect=definition.validation_policy.effect,
            readiness_effect="blocks",
            validation_report_ref=report_ref,
            evaluated_at=now,
        )
        evaluation_ref = self.artifacts.put_json(
            artifact_id=evaluation.evaluation_id,
            artifact_type="control.feedback_evaluation",
            value=evaluation,
            dependencies=(head.attempt_ref, report_ref, evidence_ref),
        )
        terminal = attempt.model_copy(
            update={
                "status": "budget_exhausted",
                "validation_report_ref": report_ref,
                "feedback_evaluation_ref": evaluation_ref,
                "finished_at": now,
                "failure_code": "budget_exhausted",
            }
        )
        terminal_ref = self._persist_attempt(
            terminal,
            dependencies=tuple(
                dict.fromkeys(
                    (
                        head.attempt_ref,
                        report_ref,
                        evaluation_ref,
                        evidence_ref,
                        *(
                            (attempt.repair_action_ref,)
                            if attempt.repair_action_ref is not None
                            else ()
                        ),
                    )
                )
            ),
        )
        if attempt.repair_action_ref is not None:
            entry = next(
                (
                    item
                    for item in self.repairs.entries
                    if item.repair_action_ref == attempt.repair_action_ref
                ),
                None,
            )
            if entry is None:
                raise WorkRuntimeError("budget-exhausted repair attempt lacks a ledger entry")
            exhausted = self.repairs.exhaust_budget(entry.entry_id)
            prior_refs = self.artifacts.list_revisions(exhausted.entry_id)
            self.artifacts.put_json(
                artifact_id=exhausted.entry_id,
                artifact_type="control.work_repair_ledger_entry",
                value=exhausted,
                dependencies=tuple(
                    dict.fromkeys(
                        (
                            exhausted.repair_action_ref,
                            evaluation_ref,
                            report_ref,
                            terminal_ref,
                            *(prior_refs[-1:] if prior_refs else ()),
                        )
                    )
                ),
            )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "failed",
                "attempt_ref": terminal_ref,
                "evaluation_ref": evaluation_ref,
                "repair_action_ref": None,
                "updated_at": now,
            }
        )
        failed_head = self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )
        self._finish_attempt_span(
            terminal,
            status="error",
            error_code="budget_exhausted",
        )
        return failed_head

    def checkpoint_assurance(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        report: AssuranceReport,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage | None = None,
        elapsed_wall_seconds: float = 0,
    ) -> WorkControlHead:
        """Persist measured execution plus framework-derived per-probe verdict."""

        policy = definition.assurance_policy
        if policy is None:
            raise WorkRuntimeError("WorkDefinition has no assurance policy")
        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if head.active_operation_ref is None:
            raise WorkRuntimeError("assurance was not authorized before execution")
        operation = self.artifacts.get_json(head.active_operation_ref, OperationRun)
        if operation.kind != "assurance" or operation.status != "running":
            raise WorkRuntimeError("active operation is not a running assurance")
        report = AssuranceReport.model_validate(report.model_dump(mode="python"))
        if (
            report.attempt_id != attempt.attempt_id
            or report.coordinate != definition.coordinate
            or report.policy_id != policy.policy_id
            or report.policy_digest != policy.content_digest()
            or report.runtime_profile_id != policy.runtime_profile_id
            or report.evidence_freshness != policy.evidence_freshness
            or tuple(item.probe_id for item in report.probe_results) != policy.probe_ids
        ):
            raise WorkRuntimeError("AssuranceReport does not match the active policy")
        unknown = unknown_upper_bound or BudgetUsage()
        now = datetime.now(UTC)
        report_ref = self.artifacts.put_json(
            artifact_id=report.report_id,
            artifact_type="control.assurance_report",
            value=report,
            dependencies=(head.active_operation_ref, *report.evidence_refs),
        )
        execution = AssuranceExecution(
            execution_id=self._id(
                "assurance-execution",
                attempt.attempt_id,
                str(operation.ordinal),
            ),
            attempt_id=attempt.attempt_id,
            policy_id=policy.policy_id,
            runtime_profile_id=policy.runtime_profile_id,
            probe_ids=policy.probe_ids,
            evidence_freshness=policy.evidence_freshness,
            evidence_refs=(report_ref, *report.evidence_refs),
            runtime_commitment=report.runtime_commitment,
            status="completed" if report.status != "error" else "failed",
            error_code=(None if report.status != "error" else "assurance_execution_error"),
            observed_actual=observed_actual,
            unknown_upper_bound=unknown,
            conservative_committed=_add_usage(observed_actual, unknown),
            started_at=operation.started_at or now,
            finished_at=now,
            duration_ms=max(
                0,
                int((now - (operation.started_at or now)).total_seconds() * 1000),
            ),
        )
        self._record_boundary_execution_span(
            attempt,
            operation="work.assurance",
            status="passed" if report.status == "passed" else "failed",
            duration_ms=execution.duration_ms,
            output_refs=(report_ref,),
            metrics=(
                MetricPoint(
                    "work.assurance.probes",
                    len(execution.probe_ids),
                    "probes",
                    "framework",
                ),
            ),
        )
        committed_head = self.finish_operation(
            lock,
            definition=definition,
            execution=execution,
            output_refs=(report_ref,),
        )
        checkpointed = self.artifacts.get_json(committed_head.attempt_ref, WorkAttempt)
        checkpointed = checkpointed.model_copy(update={"assurance_report_ref": report_ref})
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(committed_head.attempt_ref, report_ref),
        )
        next_head = committed_head.model_copy(
            update={
                "revision": committed_head.revision + 1,
                "attempt_ref": attempt_ref,
                "updated_at": now,
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=committed_head,
            next_head=next_head,
        )

    def begin_authorized_repair(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
    ) -> WorkControlHead:
        head = self.heads.read_head(definition.coordinate)
        if head is None or head.status != "repair_authorized" or head.repair_action_ref is None:
            raise WorkRuntimeError("WorkCoordinate has no authorized repair")
        prior = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        entry = next(
            (
                item
                for item in self.repairs.entries_for(
                    definition,
                    input_refs=prior.input_refs,
                )
                if item.repair_action_ref == head.repair_action_ref
            ),
            None,
        )
        if entry is None or entry.outcome != "authorized":
            raise WorkRuntimeError("repair action lacks an active WorkRepairLedger entry")
        now = datetime.now(UTC)
        action = self.artifacts.get_json(head.repair_action_ref, RepairAction)
        telemetry_trace_id, telemetry_span_id = self._start_attempt_span(
            definition,
            ordinal=prior.ordinal + 1,
            input_refs=prior.input_refs,
            repair_action=action,
            repair_action_ref=head.repair_action_ref,
        )
        attempt = prior.model_copy(
            update={
                "attempt_id": self._id("attempt", definition.work_id, str(prior.ordinal + 1)),
                "ordinal": prior.ordinal + 1,
                "parent_attempt_id": prior.attempt_id,
                "status": "running",
                "operation_run_refs": (),
                "output_refs": (),
                "validation_report_ref": None,
                "feedback_evaluation_ref": None,
                "repair_action_ref": head.repair_action_ref,
                "repair_attempt_charge": 1,
                "telemetry_trace_id": telemetry_trace_id,
                "telemetry_span_id": telemetry_span_id,
                "recovery_ordinal": 0,
                "recovery_reason_code": None,
                "continuation_commitment": prior.continuation_commitment,
                "observed_actual": BudgetUsage(),
                "unknown_upper_bound": BudgetUsage(),
                "conservative_committed": BudgetUsage(),
                "scheduled_at": now,
                "started_at": now,
                "first_progress_at": None,
                "first_write_at": None,
                "finished_at": None,
                "failure_code": None,
            }
        )
        attempt_ref = self._persist_attempt(
            attempt,
            dependencies=(head.attempt_ref, head.repair_action_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "running",
                "attempt_ref": attempt_ref,
                "evaluation_ref": None,
                "commit_ref": None,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(lock, expected_head=head, next_head=next_head)

    def authorize_causal_repair(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        source_evaluation_ref: ArtifactRef,
        source_report_ref: ArtifactRef,
        route_ref: ArtifactRef,
    ) -> WorkControlHead:
        """Authorize a target-local repair from one validated downstream route.

        The failed downstream coordinate remains failed evidence.  This method
        does not grant it a second attempt or permit it to mutate the parent.
        Instead it creates a target-coordinate proxy ValidationReport whose
        only evidence is the safe source report/evaluation/route, then applies
        the target's own local-repair budget and mutation roots.  Once that
        target commits a new immutable output, every downstream head becomes
        stale by input fingerprint and the Scheduler replays only the affected
        causal suffix.
        """

        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        if (
            definition.repair_policy.maximum_local_corrections == 0
            or not definition.allowed_mutation_roots
        ):
            raise WorkRuntimeError("causal repair target has no local mutation authority")
        if source_evaluation_ref.artifact_type != "control.feedback_evaluation":
            raise WorkRuntimeError("causal repair source evaluation has the wrong type")
        if source_report_ref.artifact_type != "control.validation_report":
            raise WorkRuntimeError("causal repair source report has the wrong type")
        if route_ref.artifact_type != "control.parent_repair_route":
            raise WorkRuntimeError("causal repair route has the wrong type")
        route = self.artifacts.get_json(route_ref, ParentRepairRoute)
        if route.target_coordinate != definition.coordinate:
            raise WorkRuntimeError("causal repair route target does not match definition")
        source_report = self.artifacts.get_json(source_report_ref, ValidationReport)
        source_evaluation = self.artifacts.get_json(source_evaluation_ref, FeedbackEvaluation)
        if (
            source_report.coordinate != route.source_coordinate
            or source_report.attempt_id != route.source_attempt_id
            or source_evaluation.coordinate != route.source_coordinate
            or source_evaluation.attempt_id != route.source_attempt_id
            or source_evaluation.validation_report_ref != source_report_ref
            or source_report.status != "failed"
            or not source_report.repair_actionable
            or tuple(item.normalized_identity for item in source_report.issues)
            != route.issue_identities
        ):
            raise WorkRuntimeError("causal repair route no longer binds its exact failure")

        head = self.heads.read_head(definition.coordinate)
        if head is None:
            raise WorkRuntimeError("causal repair target has no prior terminal head")
        if head.status == "repair_authorized":
            if head.repair_action_ref is None:
                raise WorkRuntimeError("repair-authorized target lacks its action")
            existing = self.artifacts.get_json(head.repair_action_ref, RepairAction)
            if route_ref in existing.causal_evidence_refs:
                return head
            raise WorkRuntimeError("causal repair target already has different authority")
        if head.status not in {"committed", "failed", "needs_human", "interrupted"}:
            raise WorkRuntimeError("causal repair target is not terminal")
        if head.input_fingerprint != self.heads.input_fingerprint(input_refs):
            raise WorkRuntimeError("causal repair target is stale and must be reconciled first")
        target_attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if target_attempt.input_refs != input_refs:
            raise WorkRuntimeError("causal repair target attempt does not bind current inputs")

        issues = tuple(
            ValidationIssue(
                code=f"causal_{source_issue.code}"[:120],
                path=(
                    "causal_feedback",
                    route.source_coordinate.component,
                    route.source_coordinate.stage,
                    index,
                ),
                violated_condition=(
                    "A validated downstream execution exposed a defect attributable to "
                    "this mutable artifact."
                ),
                expected_category=(
                    "a repair confined to the target WorkDefinition mutation roots"
                ),
                retryable=True,
            )
            for index, source_issue in enumerate(source_report.issues)
        )
        proxy_report = ValidationReport(
            report_id=self._id("causal-repair-report", target_attempt.attempt_id, route.route_id),
            attempt_id=target_attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            subject_refs=target_attempt.output_refs,
            status="failed",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            issues=issues,
            evidence_refs=(source_report_ref, source_evaluation_ref, route_ref),
            diagnostic_quality="actionable",
            evaluated_at=datetime.now(UTC),
        )
        proxy_report_ref = self.artifacts.put_json(
            artifact_id=proxy_report.report_id,
            artifact_type="control.validation_report",
            value=proxy_report,
            dependencies=(source_report_ref, source_evaluation_ref, route_ref, *input_refs),
        )
        proxy_evaluation = FeedbackEvaluation(
            evaluation_id=self._id(
                "causal-repair-evaluation", target_attempt.attempt_id, route.route_id
            ),
            attempt_id=target_attempt.attempt_id,
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            claim_id=definition.required_claim_id,
            acceptance_digest=definition.acceptance_digest,
            policy_digest=definition.validation_policy.content_digest(),
            status="failed",
            effect=definition.validation_policy.effect,
            readiness_effect="blocks",
            validation_report_ref=proxy_report_ref,
            evaluated_at=datetime.now(UTC),
        )
        proxy_evaluation_ref = self.artifacts.put_json(
            artifact_id=proxy_evaluation.evaluation_id,
            artifact_type="control.feedback_evaluation",
            value=proxy_evaluation,
            dependencies=(proxy_report_ref, source_evaluation_ref, route_ref),
        )
        ordinal = len(self.repairs.entries_for(definition, input_refs=input_refs)) + 1
        action = RepairAction(
            action_id=self._id("causal-repair-action", target_attempt.attempt_id, route.route_id),
            repair_policy_id=definition.repair_policy.policy_id,
            repair_epoch_digest=repair_epoch_digest(definition, input_refs),
            definition_digest=definition.definition_digest,
            input_fingerprint=work_input_fingerprint(input_refs),
            source_evaluation_ref=proxy_evaluation_ref,
            current_coordinate=definition.coordinate,
            target_coordinate=definition.coordinate,
            decision="local_correction",
            jump_distance=0,
            repair_attempt_ordinal=ordinal,
            immutable_input_refs=input_refs,
            allowed_mutation_roots=definition.allowed_mutation_roots,
            causal_evidence_refs=(source_evaluation_ref, source_report_ref, route_ref),
            reason_code="causal_downstream_failure",
            repair_attempt_charge=1,
            authorized_at=datetime.now(UTC),
        )
        action_ref = self.artifacts.put_json(
            artifact_id=action.action_id,
            artifact_type="control.repair_action",
            value=action,
            dependencies=(
                proxy_evaluation_ref,
                proxy_report_ref,
                source_evaluation_ref,
                source_report_ref,
                route_ref,
                *input_refs,
            ),
        )
        try:
            entry = self.repairs.authorize(
                definition=definition,
                action=action,
                action_ref=action_ref,
                evaluation_ref=proxy_evaluation_ref,
                report=proxy_report,
                report_ref=proxy_report_ref,
            )
        except WorkRepairDenied as exc:
            raise WorkRuntimeError(f"causal repair denied: {exc}") from exc
        self.artifacts.put_json(
            artifact_id=entry.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=entry,
            dependencies=(action_ref, proxy_evaluation_ref, proxy_report_ref, route_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "repair_authorized",
                "evaluation_ref": proxy_evaluation_ref,
                "repair_action_ref": action_ref,
                "commit_ref": None,
                "invalidated_by_refs": tuple(
                    dict.fromkeys(
                        (
                            *head.invalidated_by_refs,
                            head.commit_ref or head.attempt_ref,
                            source_evaluation_ref,
                            source_report_ref,
                            route_ref,
                            action_ref,
                        )
                    )
                ),
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.authorize_causal_repair(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def restart_interrupted_repair(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        reason_code: str,
        elapsed_wall_seconds: float,
    ) -> WorkControlHead:
        """Retry physical execution without closing or double-charging semantic repair."""

        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.repair_action_ref is None:
            raise WorkRuntimeError("physical repair recovery requires a semantic RepairAction")
        entry = next(
            (
                item
                for item in self.repairs.entries_for(
                    definition,
                    input_refs=attempt.input_refs,
                )
                if item.repair_action_ref == attempt.repair_action_ref
            ),
            None,
        )
        if entry is None or entry.outcome != "authorized":
            raise WorkRuntimeError("interrupted repair lacks an open semantic ledger entry")

        now = datetime.now(UTC)
        interrupted = attempt.model_copy(
            update={
                "status": "interrupted",
                "finished_at": now,
                "failure_code": reason_code,
            }
        )
        interrupted_ref = self._persist_attempt(
            interrupted,
            dependencies=(head.attempt_ref, *attempt.operation_run_refs),
        )
        self._finish_attempt_span(
            interrupted,
            status="error",
            error_code=reason_code,
        )
        prior_ledger_refs = self.artifacts.list_revisions(entry.entry_id)

        if entry.process_recovery_count >= definition.repair_policy.maximum_process_recoveries:
            exhausted = self.repairs.exhaust_process_recovery(entry.entry_id)
            exhausted_ref = self.artifacts.put_json(
                artifact_id=exhausted.entry_id,
                artifact_type="control.work_repair_ledger_entry",
                value=exhausted,
                dependencies=tuple(
                    dict.fromkeys(
                        (
                            entry.repair_action_ref,
                            interrupted_ref,
                            *(prior_ledger_refs[-1:] if prior_ledger_refs else ()),
                        )
                    )
                ),
            )
            next_head = head.model_copy(
                update={
                    "revision": head.revision + 1,
                    "status": "failed",
                    "attempt_ref": interrupted_ref,
                    "evaluation_ref": None,
                    "commit_ref": None,
                    "updated_at": now,
                    "invalidated_by_refs": tuple(
                        dict.fromkeys((*head.invalidated_by_refs, exhausted_ref))
                    ),
                }
            )
            return self.heads.compare_and_swap(
                lock,
                expected_head=head,
                next_head=next_head,
            )

        ordinal = self._next_unused_attempt_ordinal(
            definition,
            minimum=attempt.ordinal + 1,
        )
        updated = self.repairs.record_process_recovery(
            entry.entry_id,
            interrupted_attempt_ref=interrupted_ref,
            observed_actual=attempt.observed_actual,
            unknown_upper_bound=attempt.unknown_upper_bound,
        )
        ledger_ref = self.artifacts.put_json(
            artifact_id=updated.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=updated,
            dependencies=tuple(
                dict.fromkeys(
                    (
                        entry.repair_action_ref,
                        interrupted_ref,
                        *(prior_ledger_refs[-1:] if prior_ledger_refs else ()),
                    )
                )
            ),
        )
        action = self.artifacts.get_json(entry.repair_action_ref, RepairAction)
        telemetry_trace_id, telemetry_span_id = self._start_attempt_span(
            definition,
            ordinal=ordinal,
            input_refs=attempt.input_refs,
            repair_action=action,
            repair_action_ref=entry.repair_action_ref,
            repair_mode="process_recovery",
            process_recovery_ordinal=updated.process_recovery_count,
        )
        recovered = attempt.model_copy(
            update={
                "attempt_id": self._id("attempt", definition.work_id, str(ordinal)),
                "ordinal": ordinal,
                "parent_attempt_id": attempt.attempt_id,
                "status": "running",
                "operation_run_refs": (),
                "output_refs": (),
                "validation_report_ref": None,
                "feedback_evaluation_ref": None,
                "repair_attempt_charge": 0,
                "recovery_ordinal": updated.process_recovery_count,
                "recovery_reason_code": reason_code,
                "telemetry_trace_id": telemetry_trace_id,
                "telemetry_span_id": telemetry_span_id,
                "observed_actual": BudgetUsage(),
                "unknown_upper_bound": BudgetUsage(),
                "conservative_committed": BudgetUsage(),
                "scheduled_at": now,
                "started_at": now,
                "first_progress_at": None,
                "first_write_at": None,
                "finished_at": None,
                "failure_code": None,
            }
        )
        recovered_ref = self._persist_attempt(
            recovered,
            dependencies=(
                interrupted_ref,
                entry.repair_action_ref,
                ledger_ref,
                *attempt.input_refs,
            ),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "running",
                "attempt_ref": recovered_ref,
                "evaluation_ref": None,
                "commit_ref": None,
                "repair_action_ref": entry.repair_action_ref,
                "updated_at": now,
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def abort_interrupted_repair(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        reason_code: str,
    ) -> WorkControlHead:
        """Fail a semantic repair on non-recoverable infrastructure evidence."""

        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if attempt.repair_action_ref is None:
            raise WorkRuntimeError("repair abort requires an exact RepairAction")
        entry = next(
            (
                item
                for item in self.repairs.entries_for(
                    definition,
                    input_refs=attempt.input_refs,
                )
                if item.repair_action_ref == attempt.repair_action_ref
            ),
            None,
        )
        if entry is None or entry.outcome != "authorized":
            raise WorkRuntimeError("repair abort lacks an open semantic ledger entry")
        now = datetime.now(UTC)
        interrupted = attempt.model_copy(
            update={
                "status": "interrupted",
                "finished_at": now,
                "failure_code": reason_code,
            }
        )
        interrupted_ref = self._persist_attempt(
            interrupted,
            dependencies=(head.attempt_ref, *attempt.operation_run_refs),
        )
        self._finish_attempt_span(
            interrupted,
            status="error",
            error_code=reason_code,
        )
        exhausted = self.repairs.exhaust_process_recovery(entry.entry_id)
        prior_ledger_refs = self.artifacts.list_revisions(entry.entry_id)
        exhausted_ref = self.artifacts.put_json(
            artifact_id=exhausted.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=exhausted,
            dependencies=tuple(
                dict.fromkeys(
                    (
                        entry.repair_action_ref,
                        interrupted_ref,
                        *(prior_ledger_refs[-1:] if prior_ledger_refs else ()),
                    )
                )
            ),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "failed",
                "attempt_ref": interrupted_ref,
                "evaluation_ref": None,
                "commit_ref": None,
                "invalidated_by_refs": tuple(
                    dict.fromkeys((*head.invalidated_by_refs, exhausted_ref))
                ),
                "updated_at": now,
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def _authorize_next_or_fail(
        self,
        lock: WorkControlLock,
        *,
        head: WorkControlHead,
        terminal_attempt: WorkAttempt,
        terminal_ref: ArtifactRef,
        definition: WorkDefinition,
        report: ValidationReport,
        report_ref: ArtifactRef,
        evaluation_ref: ArtifactRef,
        elapsed_wall_seconds: float,
        repair_mutation_roots: tuple[str, ...] | None,
    ) -> WorkControlHead:
        decision: Literal["infrastructure_retry", "local_correction"] = (
            "infrastructure_retry" if report.status == "error" else "local_correction"
        )
        process_interrupted = (
            report.status == "error"
            and bool(report.issues)
            and all(issue.code.startswith("process_interrupted") for issue in report.issues)
        )
        no_local_repair_authority = (
            decision == "local_correction"
            and (
                not report.repair_actionable
                or definition.repair_policy.maximum_local_corrections == 0
                or not definition.allowed_mutation_roots
            )
        )
        no_infrastructure_retry_authority = (
            decision == "infrastructure_retry"
            and (
                definition.repair_policy.maximum_infrastructure_retries == 0
                or not report.infrastructure_retryable
            )
        )
        if no_local_repair_authority or no_infrastructure_retry_authority:
            # A FeedbackEvaluation records the failed Claim regardless, but an
            # actionable diagnostic cannot manufacture repair authority.  In
            # particular code-owned leaves deliberately have no mutation roots;
            # creating a malformed RepairAction here used to turn a precise
            # terminal diagnosis into a control-plane exception.
            return self._fail_head(
                lock,
                head=head,
                terminal_ref=terminal_ref,
                evaluation_ref=evaluation_ref,
            )
        ordinal = (
            len(
                self.repairs.entries_for(
                    definition,
                    input_refs=terminal_attempt.input_refs,
                )
            )
            + 1
        )
        authorized_at = datetime.now(UTC)
        action = RepairAction(
            action_id=self._id("repair-action", terminal_attempt.attempt_id, str(ordinal)),
            repair_policy_id=definition.repair_policy.policy_id,
            repair_epoch_digest=repair_epoch_digest(
                definition,
                terminal_attempt.input_refs,
            ),
            definition_digest=definition.definition_digest,
            input_fingerprint=work_input_fingerprint(terminal_attempt.input_refs),
            source_evaluation_ref=evaluation_ref,
            current_coordinate=definition.coordinate,
            target_coordinate=definition.coordinate,
            decision=decision,
            jump_distance=0,
            repair_attempt_ordinal=ordinal,
            immutable_input_refs=terminal_attempt.input_refs,
            allowed_mutation_roots=(
                (
                    repair_mutation_roots
                    if repair_mutation_roots is not None
                    else definition.allowed_mutation_roots
                )
                if decision == "local_correction"
                else ()
            ),
            causal_evidence_refs=(report_ref, evaluation_ref),
            reason_code=(
                "actionable_validation_failure"
                if decision == "local_correction"
                else "process_interrupted"
                if process_interrupted
                else "retryable_infrastructure_failure"
            ),
            repair_attempt_charge=1,
            authorized_at=authorized_at,
        )
        action_ref = self.artifacts.put_json(
            artifact_id=action.action_id,
            artifact_type="control.repair_action",
            value=action,
            dependencies=(report_ref, evaluation_ref, *terminal_attempt.input_refs),
        )
        try:
            entry = self.repairs.authorize(
                definition=definition,
                action=action,
                action_ref=action_ref,
                evaluation_ref=evaluation_ref,
                report=report,
                report_ref=report_ref,
            )
        except WorkRepairDenied as exc:
            denied_attempt = terminal_attempt.model_copy(
                update={"failure_code": f"repair_denied_{exc}"}
            )
            denied_ref = self._persist_attempt(
                denied_attempt,
                dependencies=(terminal_ref, action_ref),
            )
            return self._fail_head(
                lock,
                head=head,
                terminal_ref=denied_ref,
                evaluation_ref=evaluation_ref,
            )
        self.artifacts.put_json(
            artifact_id=entry.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=entry,
            dependencies=(action_ref, evaluation_ref, report_ref),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "repair_authorized",
                "attempt_ref": terminal_ref,
                "evaluation_ref": evaluation_ref,
                "repair_action_ref": action_ref,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(lock, expected_head=head, next_head=next_head)

    def _complete_previous_repair(
        self,
        definition: WorkDefinition,
        attempt: WorkAttempt,
        report_after: ValidationReport,
        report_after_ref: ArtifactRef,
    ) -> None:
        if attempt.repair_action_ref is None:
            return
        entry = next(
            (
                item
                for item in self.repairs.entries
                if item.repair_action_ref == attempt.repair_action_ref
            ),
            None,
        )
        if entry is None:
            raise WorkRuntimeError("attempt repair action lacks a WorkRepairLedger entry")
        report_before = self.artifacts.get_json(entry.report_before_ref, ValidationReport)
        history: list[ValidationReport] = []
        for item in self.repairs.entries_for(
            definition,
            input_refs=attempt.input_refs,
        ):
            if item.entry_id == entry.entry_id:
                continue
            history.append(self.artifacts.get_json(item.report_before_ref, ValidationReport))
            if item.report_after_ref is not None:
                history.append(self.artifacts.get_json(item.report_after_ref, ValidationReport))
        updated = self.repairs.complete(
            entry.entry_id,
            report_before=report_before,
            report_after=report_after,
            report_after_ref=report_after_ref,
            history=tuple(history),
            observed_actual=attempt.observed_actual,
            unknown_upper_bound=attempt.unknown_upper_bound,
            force_no_progress=(
                report_after.status == "error"
                and entry.decision in {"local_correction", "parent_correction"}
            ),
        )
        prior_refs = self.artifacts.list_revisions(updated.entry_id)
        dependencies: tuple[ArtifactRef, ...] = (
            entry.repair_action_ref,
            entry.report_before_ref,
            report_after_ref,
        )
        if prior_refs:
            dependencies = (*dependencies, prior_refs[-1])
        self.artifacts.put_json(
            artifact_id=updated.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=updated,
            dependencies=dependencies,
        )

    def _fail_head(
        self,
        lock: WorkControlLock,
        *,
        head: WorkControlHead,
        terminal_ref: ArtifactRef,
        evaluation_ref: ArtifactRef,
    ) -> WorkControlHead:
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "status": "failed",
                "attempt_ref": terminal_ref,
                "evaluation_ref": evaluation_ref,
                "repair_action_ref": None,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(lock, expected_head=head, next_head=next_head)

    @staticmethod
    def _operation_policy(
        definition: WorkDefinition,
        kind: OperationKind,
    ) -> tuple[str, str, str, OperationBudget]:
        if kind == "proposal":
            proposal_policy = definition.proposal_policy
            return (
                proposal_policy.policy_id,
                proposal_policy.content_digest(),
                proposal_policy.operation,
                proposal_policy.budget,
            )
        if kind == "validation":
            validation_policy = definition.validation_policy
            return (
                validation_policy.policy_id,
                validation_policy.content_digest(),
                validation_policy.validator_id,
                validation_policy.budget,
            )
        assurance_policy = definition.assurance_policy
        if assurance_policy is None:
            raise WorkRuntimeError("WorkDefinition has no assurance operation")
        return (
            assurance_policy.policy_id,
            assurance_policy.content_digest(),
            assurance_policy.runtime_profile_id,
            assurance_policy.budget,
        )

    @staticmethod
    def _budget_from_operation(
        operation: OperationBudget,
        *,
        repair: bool,
    ) -> Budget:
        return Budget(
            llm_tokens=operation.llm_tokens,
            agent_turns=operation.agent_turns,
            search_calls=operation.search_calls,
            tool_calls=operation.tool_calls,
            process_calls=operation.process_calls,
            build_seconds=operation.build_seconds,
            evaluation_episodes=operation.evaluation_episodes,
            container_seconds=operation.container_seconds,
            live_probe_cost=operation.live_probe_cost,
            repair_attempts=1 if repair else 0,
            wall_seconds=operation.wall_seconds,
            monetary_cost=operation.monetary_cost,
        )

    def _persist_operation(
        self,
        operation: OperationRun,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        operation = OperationRun.model_validate(operation.model_dump(mode="python"))
        return self.artifacts.put_json(
            artifact_id=operation.operation_run_id,
            artifact_type="control.operation_run",
            value=operation,
            dependencies=dependencies,
        )

    @staticmethod
    def _replace_operation_ref(
        attempt: WorkAttempt,
        *,
        old: ArtifactRef,
        new: ArtifactRef,
    ) -> WorkAttempt:
        if old not in attempt.operation_run_refs:
            raise WorkRuntimeError("active OperationRun is not bound to WorkAttempt")
        return attempt.model_copy(
            update={
                "operation_run_refs": tuple(
                    new if ref == old else ref for ref in attempt.operation_run_refs
                )
            }
        )

    def _attempt_usage(self, attempt: WorkAttempt) -> tuple[BudgetUsage, BudgetUsage]:
        actual = BudgetUsage()
        unknown = BudgetUsage()
        for ref in attempt.operation_run_refs:
            operation = self.artifacts.get_json(ref, OperationRun)
            if operation.status != "terminal":
                continue
            actual = _add_usage(actual, operation.observed_actual)
            unknown = _add_usage(unknown, operation.unknown_upper_bound)
        return actual, unknown

    def _start_attempt_span(
        self,
        definition: WorkDefinition,
        *,
        ordinal: int,
        input_refs: tuple[ArtifactRef, ...],
        repair_action: RepairAction | None = None,
        repair_action_ref: ArtifactRef | None = None,
        repair_mode: str | None = None,
        process_recovery_ordinal: int = 0,
    ) -> tuple[str | None, str | None]:
        if self.telemetry is None or self.trace_id is None:
            return None, None
        active_trace = self.telemetry.current_trace()
        if active_trace is not None and active_trace[0] != self.trace_id:
            raise WorkRuntimeError("Work telemetry trace differs from active Direct trace")
        component_by_work: dict[str, ComponentName] = {
            "controller": "controller",
            "research": "research",
            "design": "designer",
            "verifier": "judge",
            "build": "builder",
            "integration": "judge",
            "judge": "judge",
            "release": "controller",
            "registry": "registry",
        }
        if (repair_action is None) != (repair_action_ref is None):
            raise WorkRuntimeError("repair telemetry requires action and Artifact ref together")
        if process_recovery_ordinal < 0:
            raise WorkRuntimeError("process recovery telemetry ordinal cannot be negative")
        if repair_action is None:
            resolved_repair_mode = repair_mode or "initial"
            repair_depth = 0
        else:
            resolved_repair_mode = repair_mode or repair_action.decision
            repair_depth = repair_action.repair_attempt_ordinal
        span = self.telemetry.start_span(
            trace_id=self.trace_id,
            component=component_by_work[definition.coordinate.component],
            operation=definition.proposal_policy.operation,
            parent_span_id=(active_trace[3] if active_trace is not None else None),
            run_id=self.run_id or definition.coordinate.scope_id,
            node=definition.coordinate.stage,
            attempt=ordinal,
            repair_depth=repair_depth,
            input_refs=input_refs,
            attributes={
                "work_id": definition.work_id,
                "coordinate_key": definition.coordinate.coordinate_key,
                "claim_id": definition.required_claim_id,
                "repair_mode": resolved_repair_mode,
                "repair_action_revision": (
                    repair_action_ref.revision_id if repair_action_ref is not None else None
                ),
                "repair_decision": repair_action.decision if repair_action is not None else None,
                "repair_attempt_ordinal": (
                    repair_action.repair_attempt_ordinal if repair_action is not None else 0
                ),
                "process_recovery_ordinal": process_recovery_ordinal,
            },
        )
        self.telemetry.flush()
        return self.trace_id, span.span_id

    def _record_proposal_progress(
        self,
        attempt: WorkAttempt,
        execution: ProposalExecution,
    ) -> None:
        if self.telemetry is None or attempt.telemetry_span_id is None:
            return
        self.telemetry.mark_progress(
            attempt.telemetry_span_id,
            first=True,
            metrics=(
                MetricPoint(
                    "work.proposal.tokens.actual",
                    execution.observed_actual.llm_tokens,
                    "tokens",
                    "framework",
                ),
                MetricPoint(
                    "work.proposal.tokens.unknown_upper_bound",
                    execution.unknown_upper_bound.llm_tokens,
                    "tokens",
                    "unknown",
                ),
            ),
        )
        if execution.output_commitment is not None and attempt.telemetry_trace_id is not None:
            self.telemetry.record_event(
                trace_id=attempt.telemetry_trace_id,
                span_id=attempt.telemetry_span_id,
                event_type="work.first_write",
                payload={"output_committed": True},
            )

    def _record_boundary_execution_span(
        self,
        attempt: WorkAttempt,
        *,
        operation: str,
        status: Literal["passed", "failed", "error"],
        duration_ms: int,
        output_refs: tuple[ArtifactRef, ...],
        metrics: tuple[MetricPoint, ...],
    ) -> None:
        if (
            self.telemetry is None
            or attempt.telemetry_trace_id is None
            or attempt.telemetry_span_id is None
        ):
            return
        span = self.telemetry.start_span(
            trace_id=attempt.telemetry_trace_id,
            component="controller",
            operation=operation,
            parent_span_id=attempt.telemetry_span_id,
            run_id=self.run_id or attempt.coordinate.scope_id,
            node=attempt.coordinate.stage,
            attempt=attempt.ordinal,
        )
        self.telemetry.finish_span(
            span.span_id,
            status=status,
            duration_ns=duration_ms * 1_000_000,
            output_refs=output_refs,
            metrics=metrics,
        )

    def _finish_attempt_span(
        self,
        attempt: WorkAttempt,
        *,
        status: Literal["passed", "failed", "error"],
        error_code: str | None = None,
        output_refs: tuple[ArtifactRef, ...] = (),
    ) -> None:
        if self.telemetry is None or attempt.telemetry_span_id is None:
            return
        started_at = attempt.started_at or attempt.scheduled_at
        finished_at = attempt.finished_at or datetime.now(UTC)
        self.telemetry.finish_span(
            attempt.telemetry_span_id,
            status=status,
            duration_ns=max(0, int((finished_at - started_at).total_seconds() * 1e9)),
            error_code=error_code,
            output_refs=output_refs,
            metrics=(
                MetricPoint(
                    "work.repair.attempt_charge",
                    attempt.repair_attempt_charge,
                    "attempts",
                    "framework",
                ),
            ),
        )
        self.telemetry.flush()

    @staticmethod
    def _validate_slot_refs(
        definition: WorkDefinition,
        refs: tuple[ArtifactRef, ...],
        *,
        direction: Literal["input", "output"],
    ) -> None:
        slots = definition.input_slots if direction == "input" else definition.output_slots
        if not slots:
            return
        for slot in slots:
            try:
                slot.validate_refs(refs)
            except ValueError as exc:
                raise WorkRuntimeError(str(exc)) from exc
        declared_types = {artifact_type for slot in slots for artifact_type in slot.artifact_types}
        # The immutable GenerationContext is the one graph-level root that the
        # Scheduler deliberately carries into every WorkAttempt.  It is not a
        # component business input: WorkDefinitions declare only the typed
        # parent artifacts they consume.  Treating this root as an undeclared
        # slot used to make every strict downstream leaf fail before proposal.
        # No other artifact type receives this exemption.
        framework_root_types = (
            frozenset({"control.generation_context"}) if direction == "input" else frozenset()
        )
        unexpected = tuple(
            ref.artifact_type
            for ref in refs
            if ref.artifact_type not in declared_types
            and ref.artifact_type not in framework_root_types
        )
        if unexpected:
            raise WorkRuntimeError(
                f"{direction} Artifact refs contain undeclared types: {sorted(set(unexpected))}"
            )

    def _next_unused_attempt_ordinal(
        self,
        definition: WorkDefinition,
        *,
        minimum: int,
    ) -> int:
        """Skip crash-window identities already present in the Artifact Store."""

        for ordinal in range(max(1, minimum), max(1, minimum) + 10_000):
            attempt_id = self._id("attempt", definition.work_id, str(ordinal))
            lease_id = self._id("work-budget-lease", definition.work_id, str(ordinal))
            if not self.artifacts.list_revisions(attempt_id) and not self.artifacts.list_revisions(
                lease_id
            ):
                return ordinal
        raise WorkRuntimeError("WorkAttempt ordinal space is exhausted")

    def _persist_definition(
        self,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        return self.artifacts.put_json(
            artifact_id=self._id("work-definition", definition.work_id),
            artifact_type="control.work_definition",
            value=definition,
            dependencies=input_refs,
        )

    def _persist_attempt(
        self,
        attempt: WorkAttempt,
        *,
        dependencies: tuple[ArtifactRef, ...],
    ) -> ArtifactRef:
        attempt = WorkAttempt.model_validate(attempt.model_dump(mode="python"))
        return self.artifacts.put_json(
            artifact_id=attempt.attempt_id,
            artifact_type="control.work_attempt",
            value=attempt,
            dependencies=dependencies,
        )

    def _require_running(self, definition: WorkDefinition) -> WorkControlHead:
        head = self.heads.read_head(definition.coordinate)
        if (
            head is None
            or head.status != "running"
            or head.definition_digest != definition.definition_digest
        ):
            raise WorkRuntimeError("WorkCoordinate is not running under this definition")
        return head

    @staticmethod
    def _id(*parts: str) -> str:
        label = parts[0]
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
        return f"{label}:{digest}"


__all__ = ["WorkControlRuntime", "WorkRuntimeError", "restore_work_budget_ledger"]

"""Executable clean-break WorkGraph authority used before component migration.

The runtime is intentionally independent of Designer/Builder/Judge.  Components
may execute one proposal and one deterministic validator, but only this service
may reserve the next attempt, publish a boundary evaluation, authorize repair,
or create the resumable WorkCommit.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Literal

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, Budget, BudgetUsage

from .budget import LeaseBudgetLedger
from .models import BudgetLease
from .work import (
    FeedbackEvaluation,
    ProposalExecution,
    RepairAction,
    ValidationReport,
    WorkAttempt,
    WorkCommit,
    WorkDefinition,
)
from .work_repair import WorkRepairDenied, WorkRepairLedger
from .work_store import WorkControlHead, WorkControlLock, WorkControlStore


class WorkRuntimeError(RuntimeError):
    """A component attempted to bypass WorkGraph lifecycle authority."""


def restore_work_budget_ledger(
    artifacts: ArtifactWriter,
    *,
    reserved: Budget,
) -> LeaseBudgetLedger:
    """Restore exact terminal-or-active BudgetLease revisions after process failure."""

    grouped: dict[str, list[BudgetLease]] = {}
    for ref in artifacts.list_revisions():
        if ref.artifact_type != "control.budget_lease":
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
    ) -> None:
        self.artifacts = artifacts
        self.heads = heads
        self.budget = budget
        self.repairs = repairs if repairs is not None else WorkRepairLedger.restore(artifacts)

    def begin(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        input_refs: tuple[ArtifactRef, ...],
        elapsed_wall_seconds: float,
    ) -> WorkControlHead:
        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        if self.heads.read_head(definition.coordinate) is not None:
            raise WorkRuntimeError("WorkCoordinate already has a durable head")
        definition_ref = self._persist_definition(definition, input_refs)
        lease, lease_ref = self._reserve_attempt_lease(
            definition=definition,
            ordinal=1,
            elapsed_wall_seconds=elapsed_wall_seconds,
            repair=False,
        )
        now = datetime.now(UTC)
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
            budget_lease_ref=lease_ref,
            input_refs=input_refs,
            scheduled_at=lease.created_at,
            started_at=now,
        )
        attempt_ref = self._persist_attempt(
            attempt,
            dependencies=(definition_ref, lease_ref, *input_refs),
        )
        head = WorkControlStore.new_head(
            definition=definition,
            input_refs=input_refs,
            attempt_ref=attempt_ref,
        )
        return self.heads.compare_and_swap(lock, expected_head=None, next_head=head)

    def checkpoint_proposal(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        execution: ProposalExecution,
    ) -> WorkControlHead:
        execution = ProposalExecution.model_validate(execution.model_dump(mode="python"))
        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if execution.attempt_id != attempt.attempt_id:
            raise WorkRuntimeError("ProposalExecution belongs to another WorkAttempt")
        execution_ref = self.artifacts.put_json(
            artifact_id=self._id("proposal-execution", execution.execution_id),
            artifact_type="control.proposal_execution",
            value=execution,
            dependencies=(head.attempt_ref, *attempt.input_refs),
        )
        lease = self.artifacts.get_json(attempt.budget_lease_ref, BudgetLease)
        lease_actual = execution.observed_actual
        if attempt.repair_action_ref is not None:
            lease_actual = lease_actual.model_copy(
                update={"repair_attempts": lease_actual.repair_attempts + 1}
            )
        lease_committed = BudgetUsage.model_validate(
            {
                field_name: getattr(lease_actual, field_name)
                + getattr(execution.unknown_upper_bound, field_name)
                for field_name in BudgetUsage.model_fields
                if field_name != "schema_version"
            }
        )
        settled = self.budget.settle(
            lease.lease_id,
            lease_actual,
            unknown_upper_bound=execution.unknown_upper_bound,
        )
        settled_ref = self.artifacts.put_json(
            artifact_id=lease.lease_id,
            artifact_type="control.budget_lease",
            value=settled,
            dependencies=(attempt.budget_lease_ref, execution_ref),
        )
        checkpointed = attempt.model_copy(
            update={
                "budget_lease_ref": settled_ref,
                "proposal_execution_refs": (*attempt.proposal_execution_refs, execution_ref),
                "continuation_commitment": execution.continuation_commitment,
                "observed_actual": lease_actual,
                "unknown_upper_bound": execution.unknown_upper_bound,
                "conservative_committed": lease_committed,
                "first_progress_at": execution.finished_at,
                "first_write_at": (
                    execution.finished_at if execution.output_commitment is not None else None
                ),
            }
        )
        attempt_ref = self._persist_attempt(
            checkpointed,
            dependencies=(head.attempt_ref, settled_ref, execution_ref, *attempt.input_refs),
        )
        next_head = head.model_copy(
            update={
                "revision": head.revision + 1,
                "attempt_ref": attempt_ref,
                "updated_at": datetime.now(UTC),
            }
        )
        return self.heads.compare_and_swap(
            lock,
            expected_head=head,
            next_head=next_head,
        )

    def evaluate(
        self,
        lock: WorkControlLock,
        *,
        definition: WorkDefinition,
        report: ValidationReport,
        output_refs: tuple[ArtifactRef, ...] = (),
        elapsed_wall_seconds: float,
    ) -> WorkControlHead:
        report = ValidationReport.model_validate(report.model_dump(mode="python"))
        head = self._require_running(definition)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        if report.attempt_id != attempt.attempt_id:
            raise WorkRuntimeError("ValidationReport belongs to another WorkAttempt")
        if report.coordinate != definition.coordinate:
            raise WorkRuntimeError("ValidationReport coordinate mismatch")
        if report.policy_digest != definition.validation_policy.content_digest():
            raise WorkRuntimeError("ValidationReport policy digest mismatch")
        if not attempt.proposal_execution_refs:
            raise WorkRuntimeError("validation cannot precede real proposal execution")
        if report.status == "passed" and (
            not output_refs or report.subject_ref not in output_refs
        ):
            raise WorkRuntimeError("passing validation must bind one exact output")
        report_ref = self.artifacts.put_json(
            artifact_id=self._id("validation-report", report.report_id),
            artifact_type="control.validation_report",
            value=report,
            dependencies=(head.attempt_ref, *attempt.proposal_execution_refs, *output_refs),
        )
        evaluation = FeedbackEvaluation(
            evaluation_id=self._id("evaluation", attempt.attempt_id),
            attempt_id=attempt.attempt_id,
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            claim_id=definition.required_claim_id,
            policy_digest=definition.validation_policy.content_digest(),
            status=report.status,
            effect=definition.validation_policy.effect,
            readiness_effect=("satisfies" if report.status == "passed" else "blocks"),
            subject_ref=report.subject_ref,
            validation_report_ref=report_ref,
            evaluated_at=datetime.now(UTC),
        )
        evaluation_ref = self.artifacts.put_json(
            artifact_id=evaluation.evaluation_id,
            artifact_type="control.feedback_evaluation",
            value=evaluation,
            dependencies=(report_ref, head.attempt_ref, *output_refs),
        )
        self._complete_previous_repair(attempt, report, report_ref)
        terminal_status = "succeeded" if report.status == "passed" else "failed"
        terminal = attempt.model_copy(
            update={
                "status": terminal_status,
                "output_refs": output_refs if report.status == "passed" else (),
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
            dependencies=(head.attempt_ref, report_ref, evaluation_ref, *output_refs),
        )
        if report.status == "passed":
            commit = WorkCommit(
                commit_id=self._id("work-commit", attempt.attempt_id),
                work_id=definition.work_id,
                coordinate=definition.coordinate,
                attempt_id=attempt.attempt_id,
                definition_digest=definition.definition_digest,
                validation_policy_digest=definition.validation_policy.content_digest(),
                input_refs=attempt.input_refs,
                output_refs=output_refs,
                feedback_evaluation_ref=evaluation_ref,
                committed_at=datetime.now(UTC),
            )
            commit_ref = self.artifacts.put_json(
                artifact_id=commit.commit_id,
                artifact_type="control.work_commit",
                value=commit,
                dependencies=(terminal_ref, evaluation_ref, *attempt.input_refs, *output_refs),
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
            return self.heads.compare_and_swap(
                lock,
                expected_head=head,
                next_head=next_head,
            )
        return self._authorize_next_or_fail(
            lock,
            head=head,
            terminal_attempt=terminal,
            terminal_ref=terminal_ref,
            definition=definition,
            report=report,
            report_ref=report_ref,
            evaluation_ref=evaluation_ref,
            elapsed_wall_seconds=elapsed_wall_seconds,
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
                for item in self.repairs.entries_for(definition)
                if item.repair_action_ref == head.repair_action_ref
            ),
            None,
        )
        if entry is None or entry.outcome != "authorized":
            raise WorkRuntimeError("repair action lacks an active WorkRepairLedger entry")
        now = datetime.now(UTC)
        attempt = prior.model_copy(
            update={
                "attempt_id": self._id("attempt", definition.work_id, str(prior.ordinal + 1)),
                "ordinal": prior.ordinal + 1,
                "parent_attempt_id": prior.attempt_id,
                "status": "running",
                "budget_lease_ref": entry.budget_lease_ref,
                "output_refs": (),
                "proposal_execution_refs": (),
                "validation_report_ref": None,
                "feedback_evaluation_ref": None,
                "repair_action_ref": head.repair_action_ref,
                "continuation_commitment": prior.continuation_commitment,
                "observed_actual": BudgetUsage(),
                "unknown_upper_bound": BudgetUsage(),
                "conservative_committed": BudgetUsage(),
                "scheduled_at": entry.authorized_at,
                "started_at": now,
                "first_progress_at": None,
                "first_write_at": None,
                "finished_at": None,
                "failure_code": None,
            }
        )
        attempt_ref = self._persist_attempt(
            attempt,
            dependencies=(head.attempt_ref, head.repair_action_ref, entry.budget_lease_ref),
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
    ) -> WorkControlHead:
        decision: Literal["infrastructure_retry", "local_correction"] = (
            "infrastructure_retry" if report.status == "error" else "local_correction"
        )
        if decision == "local_correction" and not report.repair_actionable:
            return self._fail_head(
                lock,
                head=head,
                terminal_ref=terminal_ref,
                evaluation_ref=evaluation_ref,
            )
        ordinal = len(self.repairs.entries_for(definition)) + 1
        lease, lease_ref = self._reserve_attempt_lease(
            definition=definition,
            ordinal=terminal_attempt.ordinal + 1,
            elapsed_wall_seconds=elapsed_wall_seconds,
            repair=True,
        )
        action = RepairAction(
            action_id=self._id("repair-action", terminal_attempt.attempt_id, str(ordinal)),
            repair_policy_id=definition.repair_policy.policy_id,
            source_evaluation_ref=evaluation_ref,
            current_coordinate=definition.coordinate,
            target_coordinate=definition.coordinate,
            decision=decision,
            jump_distance=0,
            repair_attempt_ordinal=ordinal,
            immutable_input_refs=terminal_attempt.input_refs,
            allowed_mutation_roots=(
                definition.allowed_mutation_roots if decision == "local_correction" else ()
            ),
            causal_evidence_refs=(report_ref, evaluation_ref),
            reason_code=(
                "actionable_validation_failure"
                if decision == "local_correction"
                else "retryable_infrastructure_failure"
            ),
            repair_attempt_charge=1,
            authorized_at=lease.created_at,
        )
        action_ref = self.artifacts.put_json(
            artifact_id=action.action_id,
            artifact_type="control.repair_action",
            value=action,
            dependencies=(report_ref, evaluation_ref, lease_ref, *terminal_attempt.input_refs),
        )
        try:
            entry = self.repairs.authorize(
                definition=definition,
                action=action,
                action_ref=action_ref,
                evaluation_ref=evaluation_ref,
                report=report,
                report_ref=report_ref,
                budget_lease_ref=lease_ref,
            )
        except WorkRepairDenied:
            released = self.budget.release(lease.lease_id)
            self.artifacts.put_json(
                artifact_id=lease.lease_id,
                artifact_type="control.budget_lease",
                value=released,
                dependencies=(lease_ref, action_ref),
            )
            return self._fail_head(
                lock,
                head=head,
                terminal_ref=terminal_ref,
                evaluation_ref=evaluation_ref,
            )
        self.artifacts.put_json(
            artifact_id=entry.entry_id,
            artifact_type="control.work_repair_ledger_entry",
            value=entry,
            dependencies=(action_ref, evaluation_ref, report_ref, lease_ref),
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
        for item in self.repairs.entries:
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

    def _reserve_attempt_lease(
        self,
        *,
        definition: WorkDefinition,
        ordinal: int,
        elapsed_wall_seconds: float,
        repair: bool,
    ) -> tuple[BudgetLease, ArtifactRef]:
        operation = definition.proposal_policy.budget
        requested = Budget(
            llm_tokens=operation.llm_tokens,
            agent_turns=operation.agent_turns,
            search_calls=operation.search_calls,
            tool_calls=operation.tool_calls + operation.process_calls,
            evaluation_episodes=operation.evaluation_episodes,
            repair_attempts=1 if repair else 0,
            wall_seconds=operation.wall_seconds,
            monetary_cost=operation.monetary_cost,
        )
        lease_id = self._id("work-budget-lease", definition.work_id, str(ordinal))
        lease = self.budget.reserve(
            lease_id=lease_id,
            owner_id=self._id("attempt", definition.work_id, str(ordinal)),
            requested=requested,
            elapsed_wall_seconds=elapsed_wall_seconds,
        )
        ref = self.artifacts.put_json(
            artifact_id=lease.lease_id,
            artifact_type="control.budget_lease",
            value=lease,
        )
        return lease, ref

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

"""Deterministic RepairAction authorization for the clean-break WorkGraph."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, BudgetUsage

from .work import (
    RepairAction,
    ValidationReport,
    WorkDefinition,
    WorkRepairLedgerEntry,
    classify_progress,
    repair_epoch_digest,
    work_input_fingerprint,
)


class WorkRepairDenied(RuntimeError):
    """The unique WorkGraph repair policy denied another executing attempt."""


def _add_usage(left: BudgetUsage, right: BudgetUsage) -> BudgetUsage:
    return BudgetUsage.model_validate(
        {
            field_name: getattr(left, field_name) + getattr(right, field_name)
            for field_name in BudgetUsage.model_fields
            if field_name != "schema_version"
        }
    )


class WorkRepairLedger:
    """In-memory projection of durable WorkRepairLedgerEntry Artifacts."""

    def __init__(self, entries: tuple[WorkRepairLedgerEntry, ...] = ()) -> None:
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise ValueError("WorkRepairLedger contains duplicate entry ids")
        self._entries = list(entries)

    @classmethod
    def restore(cls, artifacts: ArtifactWriter) -> WorkRepairLedger:
        """Restore one terminal-or-active revision per durable ledger entry id."""

        grouped: dict[str, list[WorkRepairLedgerEntry]] = {}
        for ref in artifacts.list_revisions():
            if ref.artifact_type != "control.work_repair_ledger_entry":
                continue
            grouped.setdefault(ref.artifact_id, []).append(
                artifacts.get_json(ref, WorkRepairLedgerEntry)
            )
        restored: list[WorkRepairLedgerEntry] = []
        for entry_id, revisions in grouped.items():
            if any(item.entry_id != entry_id for item in revisions):
                raise ValueError("WorkRepairLedger Artifact identity mismatch")
            terminal = tuple(item for item in revisions if item.outcome != "authorized")
            if len(set(item.content_digest() for item in terminal)) > 1:
                raise ValueError("WorkRepairLedger contains conflicting terminal revisions")
            if terminal:
                restored.append(terminal[0])
                continue
            if len(set(item.content_digest() for item in revisions)) > 1:
                raise ValueError("WorkRepairLedger contains conflicting active revisions")
            restored.append(revisions[0])
        return cls(tuple(sorted(restored, key=lambda item: item.entry_id)))

    @property
    def entries(self) -> tuple[WorkRepairLedgerEntry, ...]:
        return tuple(self._entries)

    def entries_for(
        self,
        definition: WorkDefinition,
        *,
        input_refs: tuple[ArtifactRef, ...],
    ) -> tuple[WorkRepairLedgerEntry, ...]:
        epoch = repair_epoch_digest(definition, input_refs)
        return tuple(
            entry
            for entry in self._entries
            if entry.work_id == definition.work_id
            and entry.coordinate == definition.coordinate
            and entry.repair_epoch_digest == epoch
            and entry.definition_digest == definition.definition_digest
            and entry.input_fingerprint == work_input_fingerprint(input_refs)
            and entry.repair_policy_digest == definition.repair_policy.content_digest()
        )

    def authorize(
        self,
        *,
        definition: WorkDefinition,
        action: RepairAction,
        action_ref: ArtifactRef,
        evaluation_ref: ArtifactRef,
        report: ValidationReport,
        report_ref: ArtifactRef,
    ) -> WorkRepairLedgerEntry:
        definition = WorkDefinition.model_validate(definition.model_dump(mode="python"))
        action = RepairAction.model_validate(action.model_dump(mode="python"))
        report = ValidationReport.model_validate(report.model_dump(mode="python"))
        policy = definition.repair_policy
        if action.repair_policy_id != policy.policy_id:
            raise WorkRepairDenied("repair_policy_identity_mismatch")
        if action.current_coordinate != definition.coordinate:
            raise WorkRepairDenied("repair_current_coordinate_mismatch")
        if action.source_evaluation_ref != evaluation_ref:
            raise WorkRepairDenied("repair_evaluation_identity_mismatch")
        if report.coordinate != definition.coordinate:
            raise WorkRepairDenied("repair_report_coordinate_mismatch")
        if report.policy_digest != definition.validation_policy.content_digest():
            raise WorkRepairDenied("repair_validation_policy_mismatch")
        if action_ref.artifact_type != "control.repair_action":
            raise WorkRepairDenied("repair_action_artifact_type_mismatch")
        if report_ref.artifact_type != "control.validation_report":
            raise WorkRepairDenied("repair_report_artifact_type_mismatch")

        epoch = repair_epoch_digest(definition, action.immutable_input_refs)
        if (
            action.repair_epoch_digest != epoch
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint != work_input_fingerprint(action.immutable_input_refs)
        ):
            raise WorkRepairDenied("repair_epoch_identity_mismatch")
        prior = self.entries_for(
            definition,
            input_refs=action.immutable_input_refs,
        )
        executing = tuple(entry for entry in prior if entry.outcome != "rejected")
        ordinal = len(executing) + 1
        if action.repair_attempt_ordinal != ordinal:
            raise WorkRepairDenied("repair_attempt_ordinal_mismatch")
        if ordinal > policy.maximum_total_repair_attempts:
            raise WorkRepairDenied("repair_total_exhausted")
        if any(entry.outcome == "no_progress" for entry in prior):
            raise WorkRepairDenied("repair_no_progress_terminal")

        if action.decision == "local_correction":
            if not report.repair_actionable:
                raise WorkRepairDenied("repair_diagnostic_not_actionable")
            if action.target_coordinate != definition.coordinate:
                raise WorkRepairDenied("local_repair_target_mismatch")
            if not action.allowed_mutation_roots or any(
                not any(
                    root == authorized or root.startswith(authorized.rstrip("/") + "/")
                    for authorized in definition.allowed_mutation_roots
                )
                for root in action.allowed_mutation_roots
            ):
                raise WorkRepairDenied("repair_mutation_authority_mismatch")
            local_prior = tuple(entry for entry in prior if entry.decision == "local_correction")
            local_ordinal = len(local_prior) + 1
            normal = policy.maximum_local_corrections
            if local_ordinal > normal + policy.strict_progress_bonus_corrections:
                raise WorkRepairDenied("repair_local_exhausted")
            if local_ordinal > normal and (
                not local_prior or local_prior[-1].outcome != "progressed"
            ):
                raise WorkRepairDenied("repair_progress_bonus_denied")
        elif action.decision == "infrastructure_retry":
            if report.status != "error":
                raise WorkRepairDenied("infrastructure_retry_requires_error_report")
            process_recovery = action.reason_code == "process_interrupted"
            if process_recovery:
                process_count = sum(
                    entry.decision == "infrastructure_retry"
                    and entry.reason_code == "process_interrupted"
                    for entry in prior
                )
                if process_count >= policy.maximum_process_recoveries:
                    raise WorkRepairDenied("repair_process_recovery_exhausted")
            else:
                infrastructure_count = sum(
                    entry.decision == "infrastructure_retry"
                    and entry.reason_code != "process_interrupted"
                    for entry in prior
                )
                if infrastructure_count >= policy.maximum_infrastructure_retries:
                    raise WorkRepairDenied("repair_infrastructure_exhausted")
        elif action.decision == "parent_correction":
            if (
                action.jump_distance != 1
                or policy.maximum_automatic_backjump < 1
                or not action.causal_evidence_refs
            ):
                raise WorkRepairDenied("repair_parent_backjump_denied")
        else:
            raise WorkRepairDenied("non_executing_action_has_no_ledger_authority")

        digest = hashlib.sha256(
            f"{action_ref.revision_id}\0{definition.work_id}\0{ordinal}".encode()
        ).hexdigest()[:24]
        entry = WorkRepairLedgerEntry(
            entry_id=f"work-repair-ledger:{digest}",
            work_id=definition.work_id,
            coordinate=definition.coordinate,
            repair_epoch_digest=epoch,
            definition_digest=definition.definition_digest,
            input_fingerprint=work_input_fingerprint(action.immutable_input_refs),
            repair_policy_digest=policy.content_digest(),
            repair_action_ref=action_ref,
            decision=action.decision,
            reason_code=action.reason_code,
            source_evaluation_ref=evaluation_ref,
            report_before_ref=report_ref,
            repair_attempt_ordinal=ordinal,
            authorized_at=datetime.now(UTC),
        )
        self._entries.append(entry)
        return entry

    def complete(
        self,
        entry_id: str,
        *,
        report_before: ValidationReport,
        report_after: ValidationReport,
        report_after_ref: ArtifactRef,
        history: tuple[ValidationReport, ...] = (),
        observed_actual: BudgetUsage | None = None,
        unknown_upper_bound: BudgetUsage | None = None,
    ) -> WorkRepairLedgerEntry:
        report_before = ValidationReport.model_validate(report_before.model_dump(mode="python"))
        report_after = ValidationReport.model_validate(report_after.model_dump(mode="python"))
        index = next(
            (index for index, entry in enumerate(self._entries) if entry.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown WorkRepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise ValueError("WorkRepairLedger entry is already terminal")
        if report_after_ref.artifact_type != "control.validation_report":
            raise ValueError("after report ref has the wrong Artifact type")
        if report_before.coordinate != current.coordinate:
            raise ValueError("before report coordinate does not match repair entry")
        progress = classify_progress(report_before, report_after, history=history)
        if (
            current.decision == "infrastructure_retry"
            and progress == "unknown"
            and report_after.frontier_ordinal > report_before.frontier_ordinal
        ):
            # Transport recovery is code-observable progress, but it does not
            # consume or manufacture a semantic-correction bonus.
            progress = "strict_progress"
        outcome = (
            "resolved"
            if progress == "resolved"
            else "progressed"
            if progress == "strict_progress"
            else "no_progress"
        )
        actual = _add_usage(current.observed_actual, observed_actual or BudgetUsage())
        unknown = _add_usage(
            current.unknown_upper_bound,
            unknown_upper_bound or BudgetUsage(),
        )
        committed = _add_usage(actual, unknown)
        updated = WorkRepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "report_after_ref": report_after_ref,
                "progress": progress,
                "outcome": outcome,
                "observed_actual": actual,
                "unknown_upper_bound": unknown,
                "conservative_committed": committed,
                "finished_at": datetime.now(UTC),
            }
        )
        self._entries[index] = updated
        return updated

    def record_process_recovery(
        self,
        entry_id: str,
        *,
        interrupted_attempt_ref: ArtifactRef,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
    ) -> WorkRepairLedgerEntry:
        """Keep one semantic repair open while recording a physical retry."""

        index = next(
            (index for index, entry in enumerate(self._entries) if entry.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown WorkRepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise WorkRepairDenied("repair_process_recovery_not_authorized")
        if current.decision not in {"local_correction", "parent_correction"}:
            raise WorkRepairDenied("repair_process_recovery_wrong_decision")
        if interrupted_attempt_ref in current.recovery_attempt_refs:
            raise WorkRepairDenied("repair_process_recovery_duplicate_attempt")
        actual = _add_usage(current.observed_actual, observed_actual)
        unknown = _add_usage(current.unknown_upper_bound, unknown_upper_bound)
        updated = WorkRepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "process_recovery_count": current.process_recovery_count + 1,
                "recovery_attempt_refs": (
                    *current.recovery_attempt_refs,
                    interrupted_attempt_ref,
                ),
                "observed_actual": actual,
                "unknown_upper_bound": unknown,
                "conservative_committed": _add_usage(actual, unknown),
            }
        )
        self._entries[index] = updated
        return updated

    def exhaust_process_recovery(self, entry_id: str) -> WorkRepairLedgerEntry:
        """Terminate an open semantic repair without inventing semantic progress."""

        index = next(
            (index for index, entry in enumerate(self._entries) if entry.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown WorkRepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise WorkRepairDenied("repair_process_recovery_not_authorized")
        updated = WorkRepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "outcome": "exhausted",
                "finished_at": datetime.now(UTC),
            }
        )
        self._entries[index] = updated
        return updated

    def exhaust_budget(self, entry_id: str) -> WorkRepairLedgerEntry:
        """Close an authorized repair that cannot reserve its next real operation.

        Budget exhaustion is neither semantic no-progress nor a process crash:
        the framework never started the next physical operation.  Keep that
        distinction in the ledger so recovery cannot redispatch an already
        unaffordable RepairAction as though it were still authorized.
        """

        index = next(
            (index for index, entry in enumerate(self._entries) if entry.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown WorkRepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise WorkRepairDenied("repair_budget_exhaustion_not_authorized")
        updated = WorkRepairLedgerEntry.model_validate(
            {
                **current.model_dump(mode="python"),
                "outcome": "exhausted",
                "finished_at": datetime.now(UTC),
            }
        )
        self._entries[index] = updated
        return updated


__all__ = ["WorkRepairDenied", "WorkRepairLedger"]

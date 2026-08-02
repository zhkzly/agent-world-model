"""Deterministic RepairAction authorization for the clean-break WorkGraph."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, BudgetUsage

from .work import (
    ExecutingRepairDecision,
    FeedbackEvaluation,
    RepairAction,
    RepairPolicy,
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
    def restore(
        cls,
        artifacts: ArtifactWriter,
        *,
        scope_id: str,
        diagnostic_only: bool | None = None,
        active_repair_action_refs: tuple[ArtifactRef, ...] = (),
    ) -> WorkRepairLedger:
        """Restore one exact WorkGraph scope without parsing unrelated history.

        Old live stores are retained as audit evidence, not a compatibility
        input to a new Direct job.  Read only the untyped coordinate envelope
        needed to select this scope, then validate the current typed contract.
        A malformed entry in the requested scope still fails closed.

        A test-node clone deliberately reuses a production scope and immutable
        input closure, so its first real diagnostic attempt may otherwise
        collide with an exhausted production repair entry.  When a caller
        explicitly selects ``diagnostic_only``, the authoritative
        FeedbackEvaluation distinguishes the two ownership domains.  A
        currently repair-authorized Work head is retained explicitly: it is
        live control state which the Scheduler must either dispatch or
        supersede, including records produced before diagnostic provenance was
        propagated to causal repair proxies.  This never revives a settled
        production retry allowance in a non-releasable experiment.
        """

        grouped: dict[str, list[WorkRepairLedgerEntry]] = {}
        for ref in artifacts.list_revisions():
            if ref.artifact_type != "control.work_repair_ledger_entry":
                continue
            raw = artifacts.get_json(ref)
            coordinate = raw.get("coordinate") if isinstance(raw, Mapping) else None
            if not isinstance(coordinate, Mapping) or coordinate.get("scope_id") != scope_id:
                continue
            entry = artifacts.get_json(ref, WorkRepairLedgerEntry)
            if (
                diagnostic_only is not None
                and entry.repair_action_ref not in active_repair_action_refs
            ):
                evaluation = artifacts.get_json(
                    entry.source_evaluation_ref,
                    FeedbackEvaluation,
                )
                if evaluation.diagnostic_only is not diagnostic_only:
                    continue
            grouped.setdefault(ref.artifact_id, []).append(entry)
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
        causal_strict_progress: bool = False,
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
        charged_ordinal = 1 + sum(
            (
                entry.decision != "session_continuation"
                or entry.reason_code != "provider_output_ceiling"
            )
            and entry.outcome != "rejected"
            for entry in prior
        )
        if (
            not (
                action.decision == "session_continuation"
                and action.reason_code == "provider_output_ceiling"
            )
            and charged_ordinal > policy.maximum_total_repair_attempts
        ):
            raise WorkRepairDenied("repair_total_exhausted")
        # ``no_progress`` is a comparison of validation reports, not a
        # universal "never dispatch again" signal.  Only a completed semantic
        # correction can establish that its actionable content made no
        # progress.  An infrastructure retry that reaches the same closed
        # transient terminal has no comparable semantic proposal; the
        # recovery policy may instead authorize its explicit next-model route.
        # Treating that transport recurrence as semantic no-progress used to
        # block the policy-selected fallback before it could start.
        semantic_no_progress = any(
            entry.outcome == "no_progress"
            and entry.decision in {"local_correction", "parent_correction"}
            for entry in prior
        )
        # A later correction against the same semantic route would be blind
        # repetition.  A transient recovery that explicitly carries the
        # original semantic context is different: it replays that already
        # authorized correction on a fresh Provider route, preserving its
        # feedback/seed rather than emitting the original prompt again.  It
        # still has to satisfy the exact source-route, per-route, fallback,
        # and total-budget checks below.
        semantic_context_recovery = (
            action.decision in {"infrastructure_retry", "model_fallback"}
            and action.semantic_repair_context_ref is not None
        )
        if semantic_no_progress and not semantic_context_recovery:
            raise WorkRepairDenied("repair_no_progress_terminal")

        if action.workspace_recovery and (
            action.decision != "infrastructure_retry"
            or action.target_coordinate != definition.coordinate
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
        ):
            raise WorkRepairDenied("workspace_recovery_authority_mismatch")

        if action.decision == "session_continuation":
            if (
                definition.proposal_policy.executor != "agent"
                or definition.proposal_policy.session_token_limit is None
                or definition.proposal_policy.session_wall_seconds is None
            ):
                raise WorkRepairDenied("session_continuation_not_declared")
            if (
                action.target_coordinate != definition.coordinate
                or action.allowed_mutation_roots != definition.allowed_mutation_roots
            ):
                raise WorkRepairDenied("session_continuation_authority_mismatch")
            continuation_count = sum(entry.decision == "session_continuation" for entry in prior)
            if continuation_count >= policy.maximum_session_continuations:
                raise WorkRepairDenied("session_continuation_exhausted")
            if action.reason_code == "provider_output_ceiling":
                if report.status != "error" or tuple(issue.code for issue in report.issues) != (
                    "turn_failed_output_limit",
                ):
                    raise WorkRepairDenied("session_continuation_requires_closed_output_limit")
            elif action.reason_code == "provider_session_continuation":
                if (
                    report.status != "error"
                    or not report.infrastructure_retryable
                    or action.route_model is None
                ):
                    raise WorkRepairDenied("session_continuation_requires_transient_terminal")
                infrastructure_count = sum(
                    entry.decision in {"infrastructure_retry", "session_continuation"}
                    and entry.reason_code != "provider_output_ceiling"
                    and entry.route_model == action.route_model
                    and entry.semantic_repair_context_ref == action.semantic_repair_context_ref
                    for entry in prior
                )
                if infrastructure_count >= policy.maximum_infrastructure_retries:
                    raise WorkRepairDenied("repair_infrastructure_exhausted")
            else:
                raise WorkRepairDenied("session_continuation_reason_invalid")
        elif action.decision == "local_correction":
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
            if local_ordinal > normal:
                if not local_prior:
                    raise WorkRepairDenied("repair_progress_bonus_denied")
                previous = local_prior[-1]
                durable_progress = previous.outcome == "progressed"
                downstream_progress = (
                    causal_strict_progress
                    and action.reason_code == "causal_downstream_failure"
                    and previous.reason_code == "causal_downstream_failure"
                    and previous.outcome == "resolved"
                )
                if not durable_progress and not downstream_progress:
                    raise WorkRepairDenied("repair_progress_bonus_denied")
            elif causal_strict_progress:
                raise WorkRepairDenied("repair_progress_bonus_not_required")
        elif action.decision in {"infrastructure_retry", "model_fallback"}:
            if report.status != "error":
                raise WorkRepairDenied("transport_recovery_requires_error_report")
            if action.decision == "model_fallback":
                if action.model_override is None:
                    raise WorkRepairDenied("model_fallback_requires_target_model")
                if action.route_model is None:
                    raise WorkRepairDenied("model_fallback_requires_source_route")
                fallback_count = sum(
                    entry.decision == "model_fallback"
                    and entry.semantic_repair_context_ref == action.semantic_repair_context_ref
                    for entry in prior
                )
                if fallback_count >= policy.maximum_model_fallbacks:
                    raise WorkRepairDenied("repair_model_fallback_exhausted")
                direct_output_ceiling_fallback = (
                    action.reason_code == "direct_output_ceiling_model_fallback"
                )
                if direct_output_ceiling_fallback:
                    blocker_codes = {
                        issue.code.removeprefix("agent_backend_").removeprefix("verifier_backend_")
                        for issue in report.issues
                        if issue.severity == "blocker"
                    }
                    if report.infrastructure_retryable or blocker_codes != {"direct_output_limit"}:
                        raise WorkRepairDenied(
                            "direct_output_ceiling_fallback_requires_exact_terminal"
                        )
                # A fallback is only admissible after the exact same current
                # node has consumed its one fresh-session infrastructure
                # retry. The typed recovery policy selected it; the ledger
                # still proves that no upstream Work was reopened.
                if not direct_output_ceiling_fallback and not any(
                    entry.decision in {"infrastructure_retry", "session_continuation"}
                    and entry.reason_code != "provider_output_ceiling"
                    and entry.route_model == action.route_model
                    and entry.semantic_repair_context_ref == action.semantic_repair_context_ref
                    for entry in prior
                ):
                    raise WorkRepairDenied("model_fallback_requires_prior_infrastructure_retry")
                return self._append_authorized(
                    definition=definition,
                    policy=policy,
                    action=action,
                    action_ref=action_ref,
                    evaluation_ref=evaluation_ref,
                    report_ref=report_ref,
                    epoch=epoch,
                    ordinal=ordinal,
                )
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
                if action.route_model is None:
                    # Old or generic recovery records remain auditable, but
                    # do not gain the newer per-route allowance.  New
                    # classified model-route retries always declare it.
                    infrastructure_count = sum(
                        entry.decision == "infrastructure_retry"
                        and entry.reason_code != "process_interrupted"
                        and entry.semantic_repair_context_ref == action.semantic_repair_context_ref
                        for entry in prior
                    )
                else:
                    infrastructure_count = sum(
                        entry.decision == "infrastructure_retry"
                        and entry.reason_code != "process_interrupted"
                        and entry.route_model == action.route_model
                        and entry.semantic_repair_context_ref == action.semantic_repair_context_ref
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

        return self._append_authorized(
            definition=definition,
            policy=policy,
            action=action,
            action_ref=action_ref,
            evaluation_ref=evaluation_ref,
            report_ref=report_ref,
            epoch=epoch,
            ordinal=ordinal,
        )

    def _append_authorized(
        self,
        *,
        definition: WorkDefinition,
        policy: RepairPolicy,
        action: RepairAction,
        action_ref: ArtifactRef,
        evaluation_ref: ArtifactRef,
        report_ref: ArtifactRef,
        epoch: str,
        ordinal: int,
    ) -> WorkRepairLedgerEntry:
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
            decision=cast(ExecutingRepairDecision, action.decision),
            reason_code=action.reason_code,
            route_model=action.route_model,
            semantic_repair_context_ref=action.semantic_repair_context_ref,
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
        force_no_progress: bool = False,
        force_strict_progress: bool = False,
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
        if force_no_progress:
            # A semantic correction that ended in an infrastructure error has
            # no comparable semantic candidate.  It cannot earn a progress
            # bonus merely because its original blockers are absent from a
            # transport report.
            progress = "unknown"
        elif force_strict_progress:
            # A second exact Provider output-ceiling terminal proves that the
            # resumed physical turn consumed a real bounded slice of the same
            # logical session.  It is not semantic progress, but it must not
            # be classified as a no-op merely because both error reports share
            # the same closed code.
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

    def exhaust_pre_dispatch(self, entry_id: str) -> WorkRepairLedgerEntry:
        """Close an authorized repair before a new physical operation starts.

        A failed route-liveness gate differs from a budget denial and from an
        interrupted operation: it has not opened the successor WorkAttempt at
        all. The shared terminal ``exhausted`` outcome prevents its durable
        RepairAction from being redispatched after restart without inventing a
        semantic progress report.
        """

        index = next(
            (index for index, entry in enumerate(self._entries) if entry.entry_id == entry_id),
            None,
        )
        if index is None:
            raise ValueError("unknown WorkRepairLedger entry")
        current = self._entries[index]
        if current.outcome != "authorized":
            raise WorkRepairDenied("repair_pre_dispatch_exhaustion_not_authorized")
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

"""Framework-owned, resumable ask/tell orchestration for tool-first Expansion."""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import model_validator

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CandidateOutcome,
    CoverageMap,
    DiscoveryAdmissionDecision,
    EnvironmentDesign,
    EnvironmentPackageManifest,
    ExpansionCampaign,
    ExpansionCampaignReport,
    ExpansionClue,
    ExpansionClueSnapshot,
    ExpansionInboxSnapshot,
    ExpansionSourceCatalog,
    ExpansionSourceDescriptor,
    ExpansionSourceHypothesis,
    ExpansionSourceParent,
    ExpansionSourceRequest,
    ExpansionSourceResult,
    KeyValue,
    MutationIntent,
    PermissionScope,
    ReleaseProfile,
    V2Contract,
)
from agent_world.contracts.expansion_source import CapabilityFeedback
from agent_world.control import (
    BudgetExceeded,
    BudgetLease,
    CampaignIterationRecord,
    CampaignLock,
    CampaignRunCheckpoint,
    CampaignStore,
    ExpansionCandidateAttempt,
    LeaseBudgetLedger,
)
from agent_world.control.campaign import SourceIntakeRecord
from agent_world.control.campaign_store import CampaignHead
from agent_world.designer import (
    AskBudget,
    EnvironmentExpansionPolicy,
    EvolutionaryArchivePolicy,
    ExpansionContext,
    OperatorCatalog,
    ParentDescriptor,
    PolicyCheckpoint,
    RandomSearchPolicy,
    WideSearchPolicy,
)
from agent_world.designer.expansion_source import ExpansionSource, ExpansionSourceBundle
from agent_world.registry import EnvironmentPoolSnapshot, EnvironmentRegistry

_RECOVERY_UNKNOWN_LEASE_REASON = "campaign_resume_unknown_leased_execution"
_SOURCE_RECOVERY_UNKNOWN_LEASE_REASON = "source_resume_unknown_active_lease"


def validate_campaign_report_graph(
    artifacts: ArtifactStore | ArtifactWriter,
    head: CampaignHead,
) -> tuple[ExpansionCampaign, CampaignRunCheckpoint, ExpansionCampaignReport]:
    """Reparse and cross-bind one terminal Campaign graph for resume/inspection."""

    if head.report_ref is None:
        raise ValueError("Campaign head is not terminal")
    checkpoint = artifacts.get_json(head.checkpoint_ref, CampaignRunCheckpoint)
    if not isinstance(checkpoint, CampaignRunCheckpoint):
        raise ValueError("Campaign checkpoint has an invalid type")
    artifacts.require_exact_json(
        head.checkpoint_ref,
        checkpoint,
        artifact_types=("control.campaign_checkpoint",),
    )
    campaign = artifacts.get_json(checkpoint.campaign_ref, ExpansionCampaign)
    if not isinstance(campaign, ExpansionCampaign):
        raise ValueError("Campaign artifact has an invalid type")
    artifacts.require_exact_json(
        checkpoint.campaign_ref,
        campaign,
        artifact_types=("expansion.campaign",),
    )
    report = artifacts.get_json(head.report_ref, ExpansionCampaignReport)
    if not isinstance(report, ExpansionCampaignReport):
        raise ValueError("Campaign report has an invalid type")
    artifacts.require_exact_json(
        head.report_ref,
        report,
        artifact_types=("expansion.campaign_report",),
    )
    if (
        campaign.campaign_id != head.campaign_id
        or checkpoint.revision != head.checkpoint_revision
        or checkpoint.status == "running"
        or checkpoint.phase != "candidate_loop"
        or report.campaign_ref != checkpoint.campaign_ref
        or report.final_framework_checkpoint_ref != head.checkpoint_ref
        or report.pool_snapshot_ref != campaign.pool_snapshot_ref
        or report.source_catalog_ref != campaign.source_catalog_ref
        or report.source_catalog_ref != checkpoint.source_catalog_ref
        or report.source_request_refs != checkpoint.source_request_refs
        or report.source_result_refs != checkpoint.source_result_refs
        or report.clue_snapshot_ref != checkpoint.clue_snapshot_ref
        or report.context_ref != checkpoint.context_ref
        or report.final_policy_checkpoint_ref != checkpoint.policy_checkpoint_ref
        or report.iteration_refs != checkpoint.completed_iteration_refs
        or report.outcome_refs != checkpoint.outcome_refs
        or report.released_package_refs != checkpoint.released_package_refs
        or report.stop_reason != checkpoint.stop_reason
    ):
        raise ValueError("Campaign report is not cross-bound to its terminal checkpoint")

    source_catalog = artifacts.get_json(campaign.source_catalog_ref, ExpansionSourceCatalog)
    if not isinstance(source_catalog, ExpansionSourceCatalog):
        raise ValueError("Campaign Source catalog has an invalid type")
    artifacts.require_exact_json(
        campaign.source_catalog_ref,
        source_catalog,
        artifact_types=("expansion.source_catalog",),
    )
    intake = artifacts.get_json(checkpoint.source_intake_ref, SourceIntakeRecord)
    if not isinstance(intake, SourceIntakeRecord):
        raise ValueError("Campaign Source intake has an invalid type")
    artifacts.require_exact_json(
        checkpoint.source_intake_ref,
        intake,
        artifact_types=("control.source_intake",),
    )
    if (
        intake.status != "completed"
        or intake.campaign_ref != checkpoint.campaign_ref
        or intake.source_catalog_ref != campaign.source_catalog_ref
        or intake.source_request_refs != report.source_request_refs
        or intake.source_result_refs != report.source_result_refs
        or intake.clue_snapshot_ref != report.clue_snapshot_ref
        or intake.context_ref != report.context_ref
    ):
        raise ValueError("Campaign report is not bound to completed Source intake")

    requests: list[ExpansionSourceRequest] = []
    for descriptor, request_ref in zip(
        source_catalog.sources,
        report.source_request_refs,
        strict=True,
    ):
        request = artifacts.get_json(request_ref, ExpansionSourceRequest)
        if not isinstance(request, ExpansionSourceRequest):
            raise ValueError("Campaign Source request has an invalid type")
        artifacts.require_exact_json(
            request_ref,
            request,
            artifact_types=("expansion.source_request",),
        )
        if request.descriptor != descriptor:
            raise ValueError("Campaign Source request differs from the frozen catalog")
        requests.append(request)
    for _request, request_ref, result_ref in zip(
        requests,
        report.source_request_refs,
        report.source_result_refs,
        strict=True,
    ):
        result = artifacts.get_json(result_ref, ExpansionSourceResult)
        if not isinstance(result, ExpansionSourceResult):
            raise ValueError("Campaign Source result has an invalid type")
        artifacts.require_exact_json(
            result_ref,
            result,
            artifact_types=("expansion.source_result",),
        )
        if result.source_request_ref != request_ref:
            raise ValueError("Campaign Source result belongs to another request")

    clue_snapshot = artifacts.get_json(report.clue_snapshot_ref, ExpansionClueSnapshot)
    context = artifacts.get_json(report.context_ref, ExpansionContext)
    policy_checkpoint = artifacts.get_json(
        report.final_policy_checkpoint_ref,
        PolicyCheckpoint,
    )
    if not isinstance(clue_snapshot, ExpansionClueSnapshot):
        raise ValueError("Campaign clue snapshot has an invalid type")
    if not isinstance(context, ExpansionContext):
        raise ValueError("Campaign context has an invalid type")
    if not isinstance(policy_checkpoint, PolicyCheckpoint):
        raise ValueError("Campaign policy checkpoint has an invalid type")
    artifacts.require_exact_json(
        report.clue_snapshot_ref,
        clue_snapshot,
        artifact_types=("expansion.clue_snapshot",),
    )
    artifacts.require_exact_json(
        report.context_ref,
        context,
        artifact_types=("expansion.context",),
    )
    artifacts.require_exact_json(
        report.final_policy_checkpoint_ref,
        policy_checkpoint,
        artifact_types=("expansion.policy_checkpoint",),
    )
    if (
        clue_snapshot.source_catalog_ref != report.source_catalog_ref
        or clue_snapshot.source_request_refs != report.source_request_refs
        or clue_snapshot.source_result_refs != report.source_result_refs
        or clue_snapshot.feedback_refs != campaign.feedback_refs
        or clue_snapshot.inbox_snapshot_ref != campaign.inbox_snapshot_ref
        or context.snapshot_ref != campaign.pool_snapshot_ref
        or context.anchor_parent_refs != campaign.anchor_package_refs
        or context.clue_refs != clue_snapshot.clue_refs
        or policy_checkpoint.policy_id != campaign.policy_id
        or policy_checkpoint.policy_version != campaign.policy_version
    ):
        raise ValueError("Campaign report changed its frozen Source/Policy context")

    flattened_outcomes: list[ArtifactRef] = []
    for iteration_ref in report.iteration_refs:
        iteration = artifacts.get_json(iteration_ref, CampaignIterationRecord)
        if not isinstance(iteration, CampaignIterationRecord):
            raise ValueError("Campaign iteration has an invalid type")
        artifacts.require_exact_json(
            iteration_ref,
            iteration,
            artifact_types=("control.campaign_iteration",),
        )
        if iteration.status != "told" or iteration.campaign_ref != report.campaign_ref:
            raise ValueError("Campaign report contains a non-terminal iteration")
        flattened_outcomes.extend(iteration.outcome_refs)
    if tuple(flattened_outcomes) != report.outcome_refs:
        raise ValueError("Campaign report outcome ordering differs from its told iterations")
    released: list[ArtifactRef] = []
    for outcome_ref in report.outcome_refs:
        outcome = artifacts.get_json(outcome_ref, CandidateOutcome)
        if not isinstance(outcome, CandidateOutcome):
            raise ValueError("Campaign outcome has an invalid type")
        artifacts.require_exact_json(
            outcome_ref,
            outcome,
            artifact_types=("expansion.candidate_outcome",),
        )
        if outcome.campaign_ref != report.campaign_ref:
            raise ValueError("Campaign outcome belongs to another Campaign")
        if outcome.released_package_ref is not None:
            released.append(outcome.released_package_ref)
    if tuple(released) != report.released_package_refs:
        raise ValueError("Campaign report release refs differ from CandidateOutcomes")

    required_dependencies = {
        report.campaign_ref,
        report.pool_snapshot_ref,
        report.source_catalog_ref,
        *report.source_request_refs,
        *report.source_result_refs,
        report.clue_snapshot_ref,
        report.context_ref,
        report.final_policy_checkpoint_ref,
        report.final_framework_checkpoint_ref,
        *report.iteration_refs,
        *report.outcome_refs,
        *report.released_package_refs,
    }
    if not required_dependencies <= set(artifacts.dependencies(head.report_ref)):
        raise ValueError("Campaign report artifact has an incomplete dependency closure")
    return campaign, checkpoint, report


@dataclass(frozen=True, slots=True)
class CampaignCandidateResult:
    outcome: CandidateOutcome
    outcome_ref: ArtifactRef
    attempt_ref: ArtifactRef


class ExpansionCandidateExecutor(Protocol):
    async def execute_expansion_candidate(
        self,
        *,
        campaign: ExpansionCampaign,
        campaign_ref: ArtifactRef,
        iteration_ref: ArtifactRef,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        lease: BudgetLease,
        lease_ref: ArtifactRef,
        registry_snapshot_id: str,
        authorized_archive_parent_refs: Sequence[ArtifactRef],
    ) -> CampaignCandidateResult: ...


class ExpandResult(V2Contract):
    campaign_ref: ArtifactRef
    final_checkpoint_ref: ArtifactRef
    report_ref: ArtifactRef
    report: ExpansionCampaignReport

    @model_validator(mode="after")
    def exact_report_refs(self) -> ExpandResult:
        if self.report.campaign_ref != self.campaign_ref:
            raise ValueError("Expansion report does not bind the returned Campaign")
        if self.report.final_framework_checkpoint_ref != self.final_checkpoint_ref:
            raise ValueError("Expansion report does not bind the returned final checkpoint")
        return self


@dataclass(slots=True)
class _CampaignState:
    campaign: ExpansionCampaign
    campaign_ref: ArtifactRef
    snapshot: EnvironmentPoolSnapshot
    source_catalog: ExpansionSourceCatalog
    source_catalog_ref: ArtifactRef
    intake: SourceIntakeRecord
    intake_ref: ArtifactRef
    context: ExpansionContext | None
    context_ref: ArtifactRef | None
    policy: EnvironmentExpansionPolicy
    policy_checkpoint: PolicyCheckpoint
    policy_checkpoint_ref: ArtifactRef
    checkpoint: CampaignRunCheckpoint
    checkpoint_ref: ArtifactRef
    ledger: LeaseBudgetLedger
    started_monotonic: float


class ExpansionCampaignRunner:
    """Own campaign state transitions; Policy owns only ask/tell selection state."""

    def __init__(
        self,
        *,
        artifact_store: ArtifactWriter,
        registry: EnvironmentRegistry,
        campaign_store: CampaignStore,
        candidate_executor: ExpansionCandidateExecutor,
        expansion_source: ExpansionSource,
        source_workspace_root: Path,
    ) -> None:
        self.artifacts = artifact_store
        self.registry = registry
        self.campaign_store = campaign_store
        self.executor = candidate_executor
        self.source = expansion_source
        self.source_workspace_root = self._secure_workspace_root(source_workspace_root)

    async def start(
        self,
        *,
        anchor_package_refs: Sequence[ArtifactRef],
        target_coverage_dimensions: Sequence[str],
        inbox_snapshot_ref: ArtifactRef | None,
        source_catalog: ExpansionSourceCatalog,
        feedback_refs: Sequence[ArtifactRef],
        campaign_id: str | None,
        policy_id: str,
        policy_parameters: Sequence[KeyValue],
        permissions: PermissionScope,
        campaign_budget: Budget,
        candidate_budget: Budget,
        release_profile: ReleaseProfile,
        campaign_seed: int,
        maximum_intents_per_iteration: int,
        maximum_in_flight: int,
        maximum_iterations: int,
        maximum_no_release_iterations: int,
        maximum_infrastructure_error_iterations: int,
        version_reservation_ttl_seconds: float,
        allowed_source_kinds: Sequence[str],
        risk_level: Literal["low", "medium", "high", "critical"],
        fidelity_requirements: Sequence[str],
    ) -> ExpandResult:
        selected_id = campaign_id or f"campaign:{uuid.uuid4().hex}"
        with self.campaign_store.exclusive(selected_id) as lock:
            if self.campaign_store.read_head(selected_id) is not None:
                raise ValueError("campaign already exists; use resume_expansion")
            state = self._create_state(
                lock=lock,
                campaign_id=selected_id,
                anchor_package_refs=anchor_package_refs,
                target_coverage_dimensions=target_coverage_dimensions,
                inbox_snapshot_ref=inbox_snapshot_ref,
                source_catalog=source_catalog,
                feedback_refs=feedback_refs,
                policy_id=policy_id,
                policy_parameters=policy_parameters,
                permissions=permissions,
                campaign_budget=campaign_budget,
                candidate_budget=candidate_budget,
                release_profile=release_profile,
                campaign_seed=campaign_seed,
                maximum_intents_per_iteration=maximum_intents_per_iteration,
                maximum_in_flight=maximum_in_flight,
                maximum_iterations=maximum_iterations,
                maximum_no_release_iterations=maximum_no_release_iterations,
                maximum_infrastructure_error_iterations=(maximum_infrastructure_error_iterations),
                version_reservation_ttl_seconds=version_reservation_ttl_seconds,
                allowed_source_kinds=allowed_source_kinds,
                risk_level=risk_level,
                fidelity_requirements=fidelity_requirements,
            )
            return await self._run(lock, state)

    async def resume(self, campaign_id: str) -> ExpandResult:
        with self.campaign_store.exclusive(campaign_id) as lock:
            head = self.campaign_store.read_head(campaign_id)
            if head is None:
                raise ValueError(f"campaign does not exist: {campaign_id}")
            if head.report_ref is not None:
                _campaign, _checkpoint, report = validate_campaign_report_graph(
                    self.artifacts,
                    head,
                )
                return ExpandResult(
                    campaign_ref=report.campaign_ref,
                    final_checkpoint_ref=head.checkpoint_ref,
                    report_ref=head.report_ref,
                    report=report,
                )
            state = self._load_state(head.checkpoint_ref)
            if state.checkpoint.phase == "source_intake":
                state = await self._recover_source_intake(lock, state)
            elif state.checkpoint.active_iteration_ref is not None:
                state = await self._recover_active_iteration(lock, state)
            return await self._run(lock, state)

    def _create_state(
        self,
        *,
        lock: CampaignLock,
        campaign_id: str,
        anchor_package_refs: Sequence[ArtifactRef],
        target_coverage_dimensions: Sequence[str],
        inbox_snapshot_ref: ArtifactRef | None,
        source_catalog: ExpansionSourceCatalog,
        feedback_refs: Sequence[ArtifactRef],
        policy_id: str,
        policy_parameters: Sequence[KeyValue],
        permissions: PermissionScope,
        campaign_budget: Budget,
        candidate_budget: Budget,
        release_profile: ReleaseProfile,
        campaign_seed: int,
        maximum_intents_per_iteration: int,
        maximum_in_flight: int,
        maximum_iterations: int,
        maximum_no_release_iterations: int,
        maximum_infrastructure_error_iterations: int,
        version_reservation_ttl_seconds: float,
        allowed_source_kinds: Sequence[str],
        risk_level: Literal["low", "medium", "high", "critical"],
        fidelity_requirements: Sequence[str],
    ) -> _CampaignState:
        anchors = self._unique_refs(tuple(anchor_package_refs))
        targets = tuple(dict.fromkeys(target_coverage_dimensions))
        feedback = tuple(feedback_refs)
        if not anchors:
            raise ValueError("Expansion requires at least one exact released manifest anchor")
        if not targets:
            raise ValueError("Expansion requires target coverage dimensions")
        if len(self._unique_refs(feedback)) != len(feedback):
            raise ValueError("Expansion capability feedback refs must be unique")
        if campaign_budget.wall_seconds <= 0 or candidate_budget.wall_seconds <= 0:
            raise ValueError("Campaign and candidate wall-time budgets must be positive")
        self._validate_source_catalog_budget(
            source_catalog,
            campaign_budget=campaign_budget,
            candidate_budget=candidate_budget,
        )

        snapshot = self.registry.pool_snapshot(statuses=("released",))
        for anchor in anchors:
            self.registry.require_snapshot_parent(snapshot.snapshot_id, anchor)
        snapshot_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("pool-snapshot", campaign_id),
            artifact_type="expansion.pool_snapshot",
            value=snapshot,
            dependencies=tuple(item.manifest_ref for item in snapshot.releases),
        )
        self._validate_inbox(inbox_snapshot_ref)
        self._validate_feedback(feedback)
        operator_catalog = OperatorCatalog.tool_first_default()
        operator_catalog_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("operator-catalog", campaign_id),
            artifact_type="expansion.operator_catalog",
            value=operator_catalog,
        )
        source_catalog_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("source-catalog", campaign_id),
            artifact_type="expansion.source_catalog",
            value=source_catalog,
        )
        policy = self._policy(policy_id, policy_parameters)
        now = datetime.now(UTC)
        campaign = ExpansionCampaign(
            campaign_id=campaign_id,
            created_at=now,
            anchor_package_refs=anchors,
            pool_snapshot_ref=snapshot_ref,
            inbox_snapshot_ref=inbox_snapshot_ref,
            source_catalog_ref=source_catalog_ref,
            feedback_refs=feedback,
            target_coverage_dimensions=targets,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_parameters=tuple(policy_parameters),
            operator_catalog_ref=operator_catalog_ref,
            budget=campaign_budget,
            candidate_budget=candidate_budget,
            permissions=permissions,
            allowed_source_kinds=tuple(allowed_source_kinds),
            risk_level=risk_level,
            fidelity_requirements=tuple(fidelity_requirements),
            release_profile=release_profile,
            campaign_seed=campaign_seed,
            maximum_intents_per_iteration=maximum_intents_per_iteration,
            maximum_in_flight=maximum_in_flight,
            maximum_iterations=maximum_iterations,
            maximum_no_release_iterations=maximum_no_release_iterations,
            maximum_infrastructure_error_iterations=(maximum_infrastructure_error_iterations),
            version_reservation_ttl_seconds=version_reservation_ttl_seconds,
        )
        campaign_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("campaign", campaign_id),
            artifact_type="expansion.campaign",
            value=campaign,
            dependencies=self._unique_refs(
                (
                    snapshot_ref,
                    operator_catalog_ref,
                    source_catalog_ref,
                    *anchors,
                    *feedback,
                    *((inbox_snapshot_ref,) if inbox_snapshot_ref is not None else ()),
                )
            ),
        )
        pool_manifest_refs = tuple(item.manifest_ref for item in snapshot.releases)
        source_requests = tuple(
            ExpansionSourceRequest(
                request_id=self._stable_id(
                    "source-request",
                    campaign_id,
                    descriptor.source_id,
                ),
                created_at=now,
                descriptor=descriptor,
                parents=self._source_parents(
                    pool_manifest_refs,
                    anchor_refs=anchors,
                    descriptor=descriptor,
                    campaign_seed=campaign_seed,
                ),
                target_coverage_dimensions=targets,
                feedback_refs=feedback,
                permissions=permissions,
                allowed_source_kinds=tuple(allowed_source_kinds),
                maximum_risk=risk_level,
                seed=self._source_seed(campaign_seed, descriptor.source_id),
            )
            for descriptor in source_catalog.sources
        )
        source_request_refs = tuple(
            self.artifacts.put_json(
                artifact_id=self._stable_id(
                    "source-request-artifact",
                    campaign_id,
                    request.descriptor.source_id,
                ),
                artifact_type="expansion.source_request",
                value=request,
                dependencies=self._unique_refs(
                    (
                        campaign_ref,
                        source_catalog_ref,
                        *feedback,
                        *(
                            ref
                            for parent in request.parents
                            for ref in (
                                parent.package_manifest_ref,
                                parent.design_ref,
                                parent.coverage_map_ref,
                            )
                        ),
                    )
                ),
            )
            for request in source_requests
        )
        intake = SourceIntakeRecord(
            intake_id=self._stable_id("source-intake", campaign_id),
            campaign_ref=campaign_ref,
            revision=1,
            status="planned",
            source_catalog_ref=source_catalog_ref,
            source_request_refs=source_request_refs,
        )
        intake_ref = self._persist_source_intake(intake, previous_ref=None)
        policy_checkpoint = PolicyCheckpoint(
            policy_id=policy.policy_id,
            policy_version=policy.version,
        )
        policy_checkpoint_ref = self._persist_policy_checkpoint(
            campaign_ref,
            policy_checkpoint,
            previous_ref=None,
        )
        checkpoint = CampaignRunCheckpoint(
            checkpoint_id=self._stable_id("campaign-checkpoint", campaign_id),
            campaign_ref=campaign_ref,
            revision=1,
            started_at=now,
            deadline_at=now + timedelta(seconds=campaign_budget.wall_seconds),
            next_iteration=0,
            status="running",
            updated_at=now,
            policy_checkpoint_ref=policy_checkpoint_ref,
            phase="source_intake",
            source_catalog_ref=source_catalog_ref,
            source_intake_ref=intake_ref,
            source_request_refs=source_request_refs,
        )
        checkpoint_ref = self._persist_checkpoint(checkpoint, previous_ref=None)
        self.campaign_store.compare_and_swap(
            lock,
            expected_checkpoint_ref=None,
            checkpoint_ref=checkpoint_ref,
            checkpoint_revision=1,
        )
        return _CampaignState(
            campaign=campaign,
            campaign_ref=campaign_ref,
            snapshot=snapshot,
            source_catalog=source_catalog,
            source_catalog_ref=source_catalog_ref,
            intake=intake,
            intake_ref=intake_ref,
            context=None,
            context_ref=None,
            policy=policy,
            policy_checkpoint=policy_checkpoint,
            policy_checkpoint_ref=policy_checkpoint_ref,
            checkpoint=checkpoint,
            checkpoint_ref=checkpoint_ref,
            ledger=LeaseBudgetLedger(campaign_budget),
            started_monotonic=time.monotonic(),
        )

    async def _execute_source_intake(
        self,
        lock: CampaignLock,
        state: _CampaignState,
    ) -> _CampaignState:
        """Cross the Source boundary only after every request and lease is durable."""

        if state.checkpoint.phase != "source_intake" or state.intake.status != "planned":
            raise ValueError("new Source execution requires the planned intake phase")
        requests = self._load_source_requests(state)
        active: list[tuple[BudgetLease, ArtifactRef]] = []
        for request, request_ref in zip(
            requests,
            state.intake.source_request_refs,
            strict=True,
        ):
            lease = state.ledger.reserve(
                lease_id=self._stable_id(
                    "source-budget-lease",
                    state.campaign.campaign_id,
                    request.request_id,
                ),
                owner_id=request.request_id,
                requested=request.descriptor.budget,
                elapsed_wall_seconds=self._elapsed(state),
            )
            lease_ref = self._persist_lease(
                state.campaign_ref,
                request_ref,
                lease,
                previous_ref=None,
            )
            active.append((lease, lease_ref))

        leased = SourceIntakeRecord.model_validate(
            {
                **state.intake.model_dump(mode="python"),
                "revision": state.intake.revision + 1,
                "status": "leased",
                "source_lease_refs": tuple(item[1] for item in active),
            }
        )
        leased_ref = self._persist_source_intake(leased, previous_ref=state.intake_ref)
        state.intake = leased
        state.intake_ref = leased_ref
        state = self._advance_checkpoint(
            lock,
            state,
            source_intake_ref=leased_ref,
            source_lease_refs=leased.source_lease_refs,
            lease_refs=self._unique_refs(
                (*state.checkpoint.lease_refs, *leased.source_lease_refs)
            ),
        )

        semaphore = asyncio.Semaphore(state.campaign.maximum_in_flight)

        async def execute(
            request: ExpansionSourceRequest,
            request_ref: ArtifactRef,
            lease_ref: ArtifactRef,
        ) -> tuple[ExpansionSourceResult, ArtifactRef]:
            async with semaphore:
                try:
                    campaign_remaining = max(
                        0.0,
                        (
                            state.checkpoint.deadline_at - datetime.now(UTC)
                        ).total_seconds(),
                    )
                    boundary_timeout = min(
                        request.descriptor.budget.wall_seconds,
                        campaign_remaining,
                    )
                    if boundary_timeout <= 0:
                        raise TimeoutError("Campaign deadline elapsed before Source execution")
                    async with asyncio.timeout(boundary_timeout):
                        bundle = await self.source.discover(
                            request=request,
                            request_ref=request_ref,
                            workspace=self._source_workspace(
                                state.campaign.campaign_id,
                                request.descriptor.source_id,
                            ),
                            invocation_budget=request.descriptor.budget,
                        )
                    self._validate_source_bundle(request, request_ref, bundle)
                    return bundle.result, bundle.result_ref
                except Exception as exc:
                    return self._source_infrastructure_result(
                        request=request,
                        request_ref=request_ref,
                        lease_ref=lease_ref,
                        reason=f"source_{type(exc).__name__}",
                    )

        results = await asyncio.gather(
            *(
                execute(request, request_ref, lease_ref)
                for request, request_ref, (_lease, lease_ref) in zip(
                    requests,
                    state.intake.source_request_refs,
                    active,
                    strict=True,
                )
            )
        )
        return self._settle_and_freeze_source_intake(
            lock,
            state,
            requests=requests,
            active=tuple(active),
            results=tuple(results),
        )

    async def _recover_source_intake(
        self,
        lock: CampaignLock,
        state: _CampaignState,
    ) -> _CampaignState:
        """Conservatively recover Source work without replaying an unknown lease."""

        if state.checkpoint.phase != "source_intake":
            return state
        completed = self._find_completed_source_intake(state)
        if completed is not None:
            completed_record, completed_ref = completed
            return self._adopt_completed_source_intake(
                lock,
                state,
                completed_record,
                completed_ref,
            )
        if state.intake.status == "planned":
            return await self._execute_source_intake(lock, state)
        if state.intake.status != "leased":
            raise ValueError("Source-intake checkpoint references an unsupported phase")

        requests = self._load_source_requests(state)
        if len(state.intake.source_lease_refs) != len(requests):
            raise ValueError("leased Source intake does not bind every request")
        active: list[tuple[BudgetLease, ArtifactRef]] = []
        results: list[tuple[ExpansionSourceResult, ArtifactRef]] = []
        for request, request_ref, lease_ref in zip(
            requests,
            state.intake.source_request_refs,
            state.intake.source_lease_refs,
            strict=True,
        ):
            lease = self.artifacts.get_json(lease_ref, BudgetLease)
            self.artifacts.require_exact_json(
                lease_ref,
                lease,
                artifact_types=("control.budget_lease",),
            )
            if (
                lease.status != "active"
                or lease.owner_id != request.request_id
                or lease.reserved != request.descriptor.budget
            ):
                raise ValueError("Source intake does not bind the expected active lease")
            restored = next(
                (item for item in state.ledger.active_leases if item.lease_id == lease.lease_id),
                None,
            )
            if restored != lease:
                raise ValueError("Campaign ledger does not contain the exact Source lease")
            active.append((lease, lease_ref))
            durable = self._find_durable_source_result(request, request_ref)
            if durable is None:
                durable = self._source_infrastructure_result(
                    request=request,
                    request_ref=request_ref,
                    lease_ref=lease_ref,
                    reason=_SOURCE_RECOVERY_UNKNOWN_LEASE_REASON,
                )
            results.append(durable)
        return self._settle_and_freeze_source_intake(
            lock,
            state,
            requests=requests,
            active=tuple(active),
            results=tuple(results),
        )

    def _settle_and_freeze_source_intake(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        *,
        requests: tuple[ExpansionSourceRequest, ...],
        active: tuple[tuple[BudgetLease, ArtifactRef], ...],
        results: tuple[tuple[ExpansionSourceResult, ArtifactRef], ...],
    ) -> _CampaignState:
        terminal_lease_refs: list[ArtifactRef] = []
        for request_ref, (lease, lease_ref), (result, _result_ref) in zip(
            state.intake.source_request_refs,
            active,
            results,
            strict=True,
        ):
            try:
                settled = state.ledger.settle(lease.lease_id, result.budget_usage)
            except (BudgetExceeded, ValueError):
                settled = state.ledger.settle(
                    lease.lease_id,
                    BudgetUsage(),
                    unknown_upper_bound=self._full_usage(lease.reserved),
                )
            terminal_lease_refs.append(
                self._persist_lease(
                    state.campaign_ref,
                    request_ref,
                    settled,
                    previous_ref=lease_ref,
                )
            )
        return self._freeze_source_context(
            lock,
            state,
            requests=requests,
            result_refs=tuple(item[1] for item in results),
            terminal_lease_refs=tuple(terminal_lease_refs),
        )

    def _freeze_source_context(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        *,
        requests: tuple[ExpansionSourceRequest, ...],
        result_refs: tuple[ArtifactRef, ...],
        terminal_lease_refs: tuple[ArtifactRef, ...],
    ) -> _CampaignState:
        if len(result_refs) != len(requests):
            raise ValueError("Source freeze requires one terminal result per request")
        source_clue_refs: list[ArtifactRef] = []
        for request, request_ref, result_ref in zip(
            requests,
            state.intake.source_request_refs,
            result_refs,
            strict=True,
        ):
            result = self.artifacts.get_json(result_ref, ExpansionSourceResult)
            self._validate_source_result(request, request_ref, result, result_ref)
            source_clue_refs.extend(result.clue_refs)
        inbox_clue_refs = self._validate_inbox(state.campaign.inbox_snapshot_ref)
        clue_refs = self._deduplicate_clues(
            inbox_clue_refs=tuple(inbox_clue_refs),
            source_clue_refs=tuple(source_clue_refs),
        )
        now = datetime.now(UTC)
        clue_snapshot = ExpansionClueSnapshot(
            snapshot_id=self._stable_id(
                "source-clue-snapshot",
                state.campaign.campaign_id,
            ),
            created_at=now,
            source_catalog_ref=state.source_catalog_ref,
            inbox_snapshot_ref=state.campaign.inbox_snapshot_ref,
            source_request_refs=state.intake.source_request_refs,
            source_result_refs=result_refs,
            clue_refs=clue_refs,
            feedback_refs=state.campaign.feedback_refs,
        )
        clue_snapshot_ref = self.artifacts.put_json(
            artifact_id=f"{clue_snapshot.snapshot_id}:record",
            artifact_type="expansion.clue_snapshot",
            value=clue_snapshot,
            dependencies=self._unique_refs(
                (
                    state.campaign_ref,
                    state.source_catalog_ref,
                    *state.intake.source_request_refs,
                    *result_refs,
                    *clue_refs,
                    *state.campaign.feedback_refs,
                    *(
                        (state.campaign.inbox_snapshot_ref,)
                        if state.campaign.inbox_snapshot_ref
                        else ()
                    ),
                )
            ),
        )
        operator_catalog = self.artifacts.get_json(
            state.campaign.operator_catalog_ref,
            OperatorCatalog,
        )
        self.artifacts.require_exact_json(
            state.campaign.operator_catalog_ref,
            operator_catalog,
            artifact_types=("expansion.operator_catalog",),
        )
        context = ExpansionContext(
            context_id=self._stable_id("expansion-context", state.campaign.campaign_id),
            snapshot_ref=state.campaign.pool_snapshot_ref,
            parents=self._parent_descriptors(
                tuple(item.manifest_ref for item in state.snapshot.releases)
            ),
            anchor_parent_refs=state.campaign.anchor_package_refs,
            clue_refs=clue_refs,
            target_coverage_dimensions=state.campaign.target_coverage_dimensions,
            operator_catalog=operator_catalog,
            campaign_seed=state.campaign.campaign_seed,
            maximum_iterations=state.campaign.maximum_iterations,
            maximum_no_release_iterations=state.campaign.maximum_no_release_iterations,
        )
        context_ref = self.artifacts.put_json(
            artifact_id=self._stable_id("expansion-context-artifact", state.campaign.campaign_id),
            artifact_type="expansion.context",
            value=context,
            dependencies=self._unique_refs(
                (
                    state.campaign_ref,
                    state.campaign.pool_snapshot_ref,
                    state.campaign.operator_catalog_ref,
                    state.source_catalog_ref,
                    clue_snapshot_ref,
                    *(item.package_ref for item in context.parents),
                    *context.clue_refs,
                )
            ),
        )
        completed = SourceIntakeRecord.model_validate(
            {
                **state.intake.model_dump(mode="python"),
                "revision": state.intake.revision + 1,
                "status": "completed",
                "source_lease_refs": terminal_lease_refs,
                "source_result_refs": result_refs,
                "clue_snapshot_ref": clue_snapshot_ref,
                "context_ref": context_ref,
            }
        )
        completed_ref = self._persist_source_intake(
            completed,
            previous_ref=state.intake_ref,
        )
        state.intake = completed
        state.intake_ref = completed_ref
        state.context = context
        state.context_ref = context_ref
        return self._advance_checkpoint(
            lock,
            state,
            phase="candidate_loop",
            source_intake_ref=completed_ref,
            source_lease_refs=terminal_lease_refs,
            source_result_refs=result_refs,
            clue_snapshot_ref=clue_snapshot_ref,
            context_ref=context_ref,
            lease_refs=self._unique_refs(
                (*state.checkpoint.lease_refs, *terminal_lease_refs)
            ),
        )

    async def _run(self, lock: CampaignLock, state: _CampaignState) -> ExpandResult:
        while True:
            if state.checkpoint.phase == "source_intake":
                state = await self._execute_source_intake(lock, state)
            if state.context is None or state.context_ref is None:
                raise ValueError("candidate Policy cannot run before Source context freeze")
            if state.checkpoint.next_iteration == 0 and any(
                self.artifacts.get_json(ref, ExpansionSourceResult).status == "needs_human"
                for ref in state.checkpoint.source_result_refs
            ):
                return self._finish(lock, state, "needs_human")
            elapsed = self._elapsed(state)
            remaining = state.ledger.remaining(elapsed_wall_seconds=elapsed)
            if (
                state.checkpoint.consecutive_infrastructure_failures
                >= state.campaign.maximum_infrastructure_error_iterations
            ):
                return self._finish(lock, state, "infrastructure_error")
            stop = state.policy.should_stop(
                state.context,
                state.policy_checkpoint,
                remaining,
            )
            if stop.stop:
                if stop.reason == "continue":
                    raise ValueError("Policy returned an inconsistent StopDecision")
                return self._finish(lock, state, stop.reason)
            affordable = self._affordable_count(
                remaining,
                state.campaign.candidate_budget,
                state.campaign.maximum_intents_per_iteration,
            )
            if affordable == 0:
                return self._finish(lock, state, "budget_exhausted")
            intents = await state.policy.ask(
                state.context,
                state.policy_checkpoint,
                AskBudget(maximum_intents=affordable, remaining=remaining),
            )
            if not intents:
                return self._finish(lock, state, "no_admissible_operator")
            if len(intents) > affordable:
                raise ValueError("Expansion Policy exceeded AskBudget.maximum_intents")
            state = await self._execute_iteration(lock, state, intents)
            if any(
                self.artifacts.get_json(ref, CandidateOutcome).terminal_status == "needs_human"
                for ref in state.checkpoint.outcome_refs[-len(intents) :]
            ):
                return self._finish(lock, state, "needs_human")

    async def _execute_iteration(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        intents: Sequence[MutationIntent],
    ) -> _CampaignState:
        number = state.checkpoint.next_iteration
        if state.context_ref is None or state.checkpoint.clue_snapshot_ref is None:
            raise ValueError("candidate iteration requires a frozen Source context")
        context_ref = state.context_ref
        clue_snapshot_ref = state.checkpoint.clue_snapshot_ref
        iteration_id = self._stable_id(
            "campaign-iteration", state.campaign.campaign_id, str(number)
        )
        if len({item.intent_id for item in intents}) != len(intents):
            raise ValueError("Expansion Policy returned duplicate intent ids")
        intent_refs = tuple(
            self.artifacts.put_json(
                artifact_id=self._stable_id(
                    "mutation-intent", state.campaign.campaign_id, intent.intent_id
                ),
                artifact_type="expansion.mutation_intent",
                value=intent,
                dependencies=self._unique_refs(
                    (
                        state.campaign_ref,
                        state.policy_checkpoint_ref,
                        context_ref,
                        clue_snapshot_ref,
                        *intent.parent_refs,
                        *intent.clue_refs,
                    )
                ),
            )
            for intent in intents
        )
        planned = CampaignIterationRecord(
            iteration_id=iteration_id,
            campaign_ref=state.campaign_ref,
            number=number,
            status="planned",
            policy_before_ref=state.policy_checkpoint_ref,
            intent_refs=intent_refs,
        )
        planned_ref = self._persist_iteration(planned, previous_ref=None)
        state = self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=planned_ref,
        )

        admission_errors = tuple(self._admission_error(state, intent) for intent in intents)
        active_leases: dict[int, tuple[BudgetLease, ArtifactRef]] = {}
        lease_refs: list[ArtifactRef] = []
        for index, (intent, intent_ref, error) in enumerate(
            zip(intents, intent_refs, admission_errors, strict=True)
        ):
            if error is not None:
                continue
            lease = state.ledger.reserve(
                lease_id=self._stable_id("budget-lease", iteration_id, intent.intent_id),
                owner_id=intent.intent_id,
                requested=state.campaign.candidate_budget,
                elapsed_wall_seconds=self._elapsed(state),
            )
            lease_ref = self._persist_lease(
                state.campaign_ref,
                intent_ref,
                lease,
                previous_ref=None,
            )
            active_leases[index] = (lease, lease_ref)
            lease_refs.append(lease_ref)
        leased = planned.model_copy(update={"status": "leased", "lease_refs": tuple(lease_refs)})
        leased_ref = self._persist_iteration(leased, previous_ref=planned_ref)
        state = self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=leased_ref,
            lease_refs=tuple((*state.checkpoint.lease_refs, *lease_refs)),
        )

        semaphore = asyncio.Semaphore(state.campaign.maximum_in_flight)

        async def execute(index: int) -> CampaignCandidateResult:
            intent = intents[index]
            intent_ref = intent_refs[index]
            error = admission_errors[index]
            if error is not None:
                return self._admission_rejected(
                    state=state,
                    iteration_ref=leased_ref,
                    intent=intent,
                    intent_ref=intent_ref,
                    reason=error,
                )
            lease, lease_ref = active_leases[index]
            async with semaphore:
                try:
                    return await self.executor.execute_expansion_candidate(
                        campaign=state.campaign,
                        campaign_ref=state.campaign_ref,
                        iteration_ref=leased_ref,
                        intent=intent,
                        intent_ref=intent_ref,
                        lease=lease,
                        lease_ref=lease_ref,
                        registry_snapshot_id=state.snapshot.snapshot_id,
                        authorized_archive_parent_refs=(state.checkpoint.released_package_refs),
                    )
                except Exception as exc:
                    return self._infrastructure_outcome(
                        state=state,
                        iteration_ref=leased_ref,
                        intent=intent,
                        intent_ref=intent_ref,
                        lease=lease,
                        lease_ref=lease_ref,
                        reason=f"candidate_executor_{type(exc).__name__}",
                    )

        results = await asyncio.gather(*(execute(index) for index in range(len(intents))))
        terminal_lease_refs: list[ArtifactRef] = []
        for index, (lease, lease_ref) in active_leases.items():
            outcome = results[index].outcome
            try:
                settled = state.ledger.settle(lease.lease_id, outcome.budget_usage)
            except (BudgetExceeded, ValueError):
                settled = state.ledger.settle(
                    lease.lease_id,
                    BudgetUsage(),
                    unknown_upper_bound=self._full_usage(lease.reserved),
                )
            terminal_lease_refs.append(
                self._persist_lease(
                    state.campaign_ref,
                    intent_refs[index],
                    settled,
                    previous_ref=lease_ref,
                )
            )
        outcome_refs = tuple(item.outcome_ref for item in results)
        evaluated = leased.model_copy(
            update={
                "status": "evaluated",
                "lease_refs": tuple(terminal_lease_refs),
                "outcome_refs": outcome_refs,
            }
        )
        evaluated_ref = self._persist_iteration(evaluated, previous_ref=leased_ref)
        state = self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=evaluated_ref,
            lease_refs=tuple((*state.checkpoint.lease_refs, *terminal_lease_refs)),
            outcome_refs=tuple((*state.checkpoint.outcome_refs, *outcome_refs)),
        )

        return await self._tell_evaluated_iteration(
            lock,
            state,
            evaluated,
            evaluated_ref,
        )

    def _finish(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        reason: Literal[
            "iteration_limit",
            "no_release_progress",
            "budget_exhausted",
            "no_admissible_operator",
            "completed_requested_iterations",
            "needs_human",
            "infrastructure_error",
        ],
    ) -> ExpandResult:
        if (
            state.context_ref is None
            or state.checkpoint.clue_snapshot_ref is None
            or state.checkpoint.phase != "candidate_loop"
        ):
            raise ValueError("Campaign cannot finish before Source context freeze")
        status: Literal[
            "completed",
            "needs_human",
            "budget_exhausted",
            "infrastructure_error",
        ]
        if reason == "needs_human":
            status = "needs_human"
        elif reason == "budget_exhausted":
            status = "budget_exhausted"
        elif reason == "infrastructure_error":
            status = "infrastructure_error"
        else:
            status = "completed"
        final_checkpoint = CampaignRunCheckpoint.model_validate(
            {
                **state.checkpoint.model_dump(mode="python"),
                "revision": state.checkpoint.revision + 1,
                "status": status,
                "updated_at": datetime.now(UTC),
                "active_iteration_ref": None,
                "stop_reason": reason,
            }
        )
        final_checkpoint_ref = self._persist_checkpoint(
            final_checkpoint,
            previous_ref=state.checkpoint_ref,
        )
        report = ExpansionCampaignReport(
            report_id=self._stable_id("campaign-report", state.campaign.campaign_id),
            campaign_ref=state.campaign_ref,
            pool_snapshot_ref=state.campaign.pool_snapshot_ref,
            source_catalog_ref=state.source_catalog_ref,
            source_request_refs=final_checkpoint.source_request_refs,
            source_result_refs=final_checkpoint.source_result_refs,
            clue_snapshot_ref=state.checkpoint.clue_snapshot_ref,
            context_ref=state.context_ref,
            final_policy_checkpoint_ref=state.policy_checkpoint_ref,
            final_framework_checkpoint_ref=final_checkpoint_ref,
            iteration_refs=final_checkpoint.completed_iteration_refs,
            outcome_refs=final_checkpoint.outcome_refs,
            released_package_refs=final_checkpoint.released_package_refs,
            stop_reason=reason,
            budget_usage=state.ledger.usage(elapsed_wall_seconds=self._elapsed(state)),
        )
        report_ref = self.artifacts.put_json(
            artifact_id=f"{report.report_id}:record",
            artifact_type="expansion.campaign_report",
            value=report,
            dependencies=self._unique_refs(
                (
                    state.campaign_ref,
                    state.campaign.pool_snapshot_ref,
                    state.source_catalog_ref,
                    *report.source_request_refs,
                    *report.source_result_refs,
                    report.clue_snapshot_ref,
                    report.context_ref,
                    state.policy_checkpoint_ref,
                    final_checkpoint_ref,
                    *report.iteration_refs,
                    *report.outcome_refs,
                    *report.released_package_refs,
                )
            ),
        )
        self.campaign_store.compare_and_swap(
            lock,
            expected_checkpoint_ref=state.checkpoint_ref,
            checkpoint_ref=final_checkpoint_ref,
            checkpoint_revision=final_checkpoint.revision,
            report_ref=report_ref,
        )
        return ExpandResult(
            campaign_ref=state.campaign_ref,
            final_checkpoint_ref=final_checkpoint_ref,
            report_ref=report_ref,
            report=report,
        )

    def _load_state(self, checkpoint_ref: ArtifactRef) -> _CampaignState:
        checkpoint = self.artifacts.get_json(checkpoint_ref, CampaignRunCheckpoint)
        self.artifacts.require_exact_json(
            checkpoint_ref,
            checkpoint,
            artifact_types=("control.campaign_checkpoint",),
        )
        campaign = self.artifacts.get_json(checkpoint.campaign_ref, ExpansionCampaign)
        self.artifacts.require_exact_json(
            checkpoint.campaign_ref,
            campaign,
            artifact_types=("expansion.campaign",),
        )
        snapshot = self.artifacts.get_json(
            campaign.pool_snapshot_ref,
            EnvironmentPoolSnapshot,
        )
        self.artifacts.require_exact_json(
            campaign.pool_snapshot_ref,
            snapshot,
            artifact_types=("expansion.pool_snapshot",),
        )
        if self.registry.load_pool_snapshot(snapshot.snapshot_id) != snapshot:
            raise ValueError("Registry snapshot differs from the Campaign artifact")
        source_catalog = self.artifacts.get_json(
            campaign.source_catalog_ref,
            ExpansionSourceCatalog,
        )
        self.artifacts.require_exact_json(
            campaign.source_catalog_ref,
            source_catalog,
            artifact_types=("expansion.source_catalog",),
        )
        if checkpoint.source_catalog_ref != campaign.source_catalog_ref:
            raise ValueError("Campaign checkpoint changed the frozen Source catalog")
        intake = self.artifacts.get_json(checkpoint.source_intake_ref, SourceIntakeRecord)
        self.artifacts.require_exact_json(
            checkpoint.source_intake_ref,
            intake,
            artifact_types=("control.source_intake",),
        )
        if (
            intake.campaign_ref != checkpoint.campaign_ref
            or intake.source_catalog_ref != campaign.source_catalog_ref
            or intake.source_request_refs != checkpoint.source_request_refs
        ):
            raise ValueError("Campaign checkpoint does not bind its exact Source intake")
        operator_catalog = self.artifacts.get_json(
            campaign.operator_catalog_ref,
            OperatorCatalog,
        )
        self.artifacts.require_exact_json(
            campaign.operator_catalog_ref,
            operator_catalog,
            artifact_types=("expansion.operator_catalog",),
        )
        policy = self._policy(campaign.policy_id, campaign.policy_parameters)
        policy_checkpoint = self.artifacts.get_json(
            checkpoint.policy_checkpoint_ref,
            PolicyCheckpoint,
        )
        self.artifacts.require_exact_json(
            checkpoint.policy_checkpoint_ref,
            policy_checkpoint,
            artifact_types=("expansion.policy_checkpoint",),
        )
        self._validate_inbox(campaign.inbox_snapshot_ref)
        self._validate_feedback(campaign.feedback_refs)
        context: ExpansionContext | None = None
        context_ref = checkpoint.context_ref
        if context_ref is not None:
            context = self.artifacts.get_json(context_ref, ExpansionContext)
            self.artifacts.require_exact_json(
                context_ref,
                context,
                artifact_types=("expansion.context",),
            )
            if checkpoint.clue_snapshot_ref is None:
                raise ValueError("Campaign context is missing its clue snapshot")
            clue_snapshot = self.artifacts.get_json(
                checkpoint.clue_snapshot_ref,
                ExpansionClueSnapshot,
            )
            self.artifacts.require_exact_json(
                checkpoint.clue_snapshot_ref,
                clue_snapshot,
                artifact_types=("expansion.clue_snapshot",),
            )
            if (
                context.snapshot_ref != campaign.pool_snapshot_ref
                or context.anchor_parent_refs != campaign.anchor_package_refs
                or context.clue_refs != clue_snapshot.clue_refs
                or context.operator_catalog != operator_catalog
                or clue_snapshot.source_catalog_ref != campaign.source_catalog_ref
                or clue_snapshot.source_request_refs != checkpoint.source_request_refs
                or clue_snapshot.source_result_refs != checkpoint.source_result_refs
                or clue_snapshot.feedback_refs != campaign.feedback_refs
                or clue_snapshot.inbox_snapshot_ref != campaign.inbox_snapshot_ref
            ):
                raise ValueError("Campaign Policy context differs from its frozen inputs")
        leases = tuple(self.artifacts.get_json(ref, BudgetLease) for ref in checkpoint.lease_refs)
        latest_by_id: dict[str, BudgetLease] = {}
        for lease in leases:
            latest_by_id[lease.lease_id] = lease
        return _CampaignState(
            campaign=campaign,
            campaign_ref=checkpoint.campaign_ref,
            snapshot=snapshot,
            source_catalog=source_catalog,
            source_catalog_ref=campaign.source_catalog_ref,
            intake=intake,
            intake_ref=checkpoint.source_intake_ref,
            context=context,
            context_ref=context_ref,
            policy=policy,
            policy_checkpoint=policy_checkpoint,
            policy_checkpoint_ref=checkpoint.policy_checkpoint_ref,
            checkpoint=checkpoint,
            checkpoint_ref=checkpoint_ref,
            ledger=LeaseBudgetLedger(
                campaign.budget,
                leases=tuple(latest_by_id.values()),
            ),
            started_monotonic=time.monotonic()
            - min(
                campaign.budget.wall_seconds,
                max(0.0, (datetime.now(UTC) - checkpoint.started_at).total_seconds()),
            ),
        )

    def _load_source_requests(
        self,
        state: _CampaignState,
    ) -> tuple[ExpansionSourceRequest, ...]:
        requests: list[ExpansionSourceRequest] = []
        if len(state.intake.source_request_refs) != len(state.source_catalog.sources):
            raise ValueError("Source intake does not match the frozen catalog")
        for descriptor, request_ref in zip(
            state.source_catalog.sources,
            state.intake.source_request_refs,
            strict=True,
        ):
            expected_parents = self._source_parents(
                tuple(item.manifest_ref for item in state.snapshot.releases),
                anchor_refs=state.campaign.anchor_package_refs,
                descriptor=descriptor,
                campaign_seed=state.campaign.campaign_seed,
            )
            request = self.artifacts.get_json(request_ref, ExpansionSourceRequest)
            self.artifacts.require_exact_json(
                request_ref,
                request,
                artifact_types=("expansion.source_request",),
            )
            if (
                request.descriptor != descriptor
                or request.parents != expected_parents
                or request.target_coverage_dimensions
                != state.campaign.target_coverage_dimensions
                or request.feedback_refs != state.campaign.feedback_refs
                or request.permissions != state.campaign.permissions
                or request.allowed_source_kinds != state.campaign.allowed_source_kinds
                or request.maximum_risk != state.campaign.risk_level
            ):
                raise ValueError("Source request differs from frozen Campaign inputs")
            requests.append(request)
        return tuple(requests)

    def _validate_source_bundle(
        self,
        request: ExpansionSourceRequest,
        request_ref: ArtifactRef,
        bundle: ExpansionSourceBundle,
    ) -> None:
        clues = self._validate_source_result(
            request,
            request_ref,
            bundle.result,
            bundle.result_ref,
        )
        if bundle.result.clue_refs != bundle.clue_refs or clues != bundle.clues:
            raise ValueError("ExpansionSource bundle differs from its durable terminal result")

    def _validate_source_result(
        self,
        request: ExpansionSourceRequest,
        request_ref: ArtifactRef,
        result: ExpansionSourceResult,
        result_ref: ArtifactRef,
    ) -> tuple[ExpansionClue, ...]:
        self.artifacts.require_exact_json(
            result_ref,
            result,
            artifact_types=("expansion.source_result",),
        )
        if result.source_request_ref != request_ref:
            raise ValueError("ExpansionSource result belongs to another request")
        exceeded = tuple(
            field
            for field in Budget.model_fields
            if field != "schema_version"
            and Decimal(str(getattr(result.budget_usage, field)))
            > Decimal(str(getattr(request.descriptor.budget, field)))
        )
        if exceeded:
            raise ValueError(f"ExpansionSource exceeded reserved budget: {exceeded}")
        dependencies = set(self.artifacts.dependencies(result_ref))
        required = {
            request_ref,
            *result.hypothesis_refs,
            *result.clue_refs,
            *result.evidence_refs,
        }
        if not required <= dependencies:
            raise ValueError("ExpansionSource result has incomplete artifact dependencies")
        for hypothesis_ref in result.hypothesis_refs:
            hypothesis = self.artifacts.get_json(
                hypothesis_ref,
                ExpansionSourceHypothesis,
            )
            self.artifacts.require_exact_json(
                hypothesis_ref,
                hypothesis,
                artifact_types=("expansion.source_hypothesis",),
            )
            if hypothesis.source_request_ref != request_ref:
                raise ValueError("Source hypothesis belongs to another request")
        for evidence_ref in result.evidence_refs:
            self._validate_source_evidence(evidence_ref)
        clues: list[ExpansionClue] = []
        for clue_ref in result.clue_refs:
            clue = self.artifacts.get_json(clue_ref, ExpansionClue)
            self.artifacts.require_exact_json(
                clue_ref,
                clue,
                artifact_types=("expansion.source_clue",),
            )
            if clue.origin_run_ref != request_ref:
                raise ValueError("Source clue belongs to another request")
            if not set(clue.evidence_refs) <= set(result.evidence_refs):
                raise ValueError("Source clue evidence is absent from the terminal result")
            clues.append(clue)
        return tuple(clues)

    def _validate_source_evidence(self, evidence_ref: ArtifactRef) -> None:
        if evidence_ref.artifact_type != "evidence.extracted_content":
            raise ValueError("Source evidence must be a complete extracted Web body")
        revision = self.artifacts.get_revision(evidence_ref)
        if revision.producer != "research-toolchain":
            raise ValueError("Source evidence was not materialized by ResearchToolchain")
        self.artifacts.get_blob(evidence_ref)
        dependencies = self.artifacts.dependencies(evidence_ref)
        raw_refs = tuple(
            ref for ref in dependencies if ref.artifact_type == "evidence.raw_content"
        )
        metadata_refs = tuple(
            ref for ref in dependencies if ref.artifact_type == "evidence.response_metadata"
        )
        if len(raw_refs) != 1 or len(metadata_refs) != 1:
            raise ValueError(
                "Source extracted evidence requires one raw body and response metadata record"
            )
        raw_ref = raw_refs[0]
        metadata_ref = metadata_refs[0]
        if (
            self.artifacts.get_revision(raw_ref).producer != "research-toolchain"
            or self.artifacts.get_revision(metadata_ref).producer != "research-toolchain"
        ):
            raise ValueError("Source evidence ancestry has an invalid producer")
        self.artifacts.get_blob(raw_ref)
        self.artifacts.get_json(metadata_ref)
        if raw_ref not in self.artifacts.dependencies(metadata_ref):
            raise ValueError("Source response metadata does not bind the exact raw body")

    def _source_infrastructure_result(
        self,
        *,
        request: ExpansionSourceRequest,
        request_ref: ArtifactRef,
        lease_ref: ArtifactRef,
        reason: str,
    ) -> tuple[ExpansionSourceResult, ArtifactRef]:
        failure_code = self._safe_identifier(reason)
        result = ExpansionSourceResult(
            result_id=self._stable_id(
                "source-framework-result",
                request.request_id,
                failure_code,
            ),
            source_request_ref=request_ref,
            status="infrastructure_error",
            budget_usage=self._full_usage(request.descriptor.budget),
            failure_code=failure_code,
        )
        result_ref = self.artifacts.put_json(
            artifact_id=f"{result.result_id}:record",
            artifact_type="expansion.source_result",
            value=result,
            dependencies=(request_ref, lease_ref),
        )
        return result, result_ref

    @staticmethod
    def _secure_workspace_root(path: Path) -> Path:
        requested = Path(os.path.abspath(path.expanduser()))
        for component in (requested, *requested.parents):
            if component.exists() and component.is_symlink():
                raise ValueError("ExpansionSource workspace cannot contain symlink components")
        requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ValueError("ExpansionSource workspace root must be a real directory")
        requested.chmod(0o700)
        return requested.resolve(strict=True)

    def _source_workspace(self, campaign_id: str, source_id: str) -> Path:
        current = self.source_workspace_root
        for segment in (campaign_id, source_id):
            if not segment or segment in {".", ".."} or "/" in segment or "\\" in segment:
                raise ValueError("ExpansionSource workspace identity is not path-safe")
            child = current / segment
            if child.exists() and child.is_symlink():
                raise ValueError("ExpansionSource workspace cannot be a symlink")
            child.mkdir(mode=0o700, exist_ok=True)
            if child.is_symlink() or not child.is_dir():
                raise ValueError("ExpansionSource workspace must be a real directory")
            child.chmod(0o700)
            current = child
        resolved = current.resolve(strict=True)
        if self.source_workspace_root not in resolved.parents:
            raise ValueError("ExpansionSource workspace escaped its configured root")
        return resolved

    def _find_durable_source_result(
        self,
        request: ExpansionSourceRequest,
        request_ref: ArtifactRef,
    ) -> tuple[ExpansionSourceResult, ArtifactRef] | None:
        matches: list[tuple[ExpansionSourceResult, ArtifactRef]] = []
        for result_ref in self.artifacts.list_revisions():
            if result_ref.artifact_type != "expansion.source_result":
                continue
            result = self.artifacts.get_json(result_ref, ExpansionSourceResult)
            if result.source_request_ref != request_ref:
                continue
            try:
                self._validate_source_result(request, request_ref, result, result_ref)
            except ValueError:
                continue
            matches.append((result, result_ref))
        if not matches:
            return None
        known = tuple(
            item
            for item in matches
            if item[0].failure_code != _SOURCE_RECOVERY_UNKNOWN_LEASE_REASON
        )
        selected = known or tuple(matches)
        if len({item[0].stable_json() for item in selected}) != 1:
            raise ValueError("multiple conflicting Source results bind one request")
        return min(selected, key=lambda item: item[1].revision_id)

    def _find_completed_source_intake(
        self,
        state: _CampaignState,
    ) -> tuple[SourceIntakeRecord, ArtifactRef] | None:
        matches: list[tuple[SourceIntakeRecord, ArtifactRef]] = []
        for intake_ref in self.artifacts.list_revisions(f"{state.intake.intake_id}:state"):
            if intake_ref.artifact_type != "control.source_intake":
                continue
            intake = self.artifacts.get_json(intake_ref, SourceIntakeRecord)
            self.artifacts.require_exact_json(
                intake_ref,
                intake,
                artifact_types=("control.source_intake",),
            )
            if (
                intake.status == "completed"
                and intake.campaign_ref == state.campaign_ref
                and intake.source_catalog_ref == state.source_catalog_ref
                and intake.source_request_refs == state.intake.source_request_refs
            ):
                matches.append((intake, intake_ref))
        if not matches:
            return None
        if len({item[0].stable_json() for item in matches}) != 1:
            raise ValueError("multiple conflicting completed Source-intake records")
        return min(matches, key=lambda item: item[1].revision_id)

    def _adopt_completed_source_intake(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        completed: SourceIntakeRecord,
        completed_ref: ArtifactRef,
    ) -> _CampaignState:
        requests = self._load_source_requests(state)
        assert completed.context_ref is not None
        assert completed.clue_snapshot_ref is not None
        for request, request_ref, lease_ref, result_ref in zip(
            requests,
            completed.source_request_refs,
            completed.source_lease_refs,
            completed.source_result_refs,
            strict=True,
        ):
            result = self.artifacts.get_json(result_ref, ExpansionSourceResult)
            self._validate_source_result(request, request_ref, result, result_ref)
            terminal = self.artifacts.get_json(lease_ref, BudgetLease)
            self.artifacts.require_exact_json(
                lease_ref,
                terminal,
                artifact_types=("control.budget_lease",),
            )
            if (
                terminal.status != "settled"
                or terminal.owner_id != request.request_id
                or terminal.reserved != request.descriptor.budget
                or terminal.conservative_committed != result.budget_usage
            ):
                raise ValueError("completed Source intake contains an invalid terminal lease")
            active = next(
                (
                    item
                    for item in state.ledger.active_leases
                    if item.lease_id == terminal.lease_id
                ),
                None,
            )
            if active is None:
                raise ValueError("completed Source intake lost its active checkpoint lease")
            state.ledger.settle(
                active.lease_id,
                terminal.observed_actual,
                unknown_upper_bound=terminal.unknown_upper_bound,
            )
        clue_snapshot = self.artifacts.get_json(
            completed.clue_snapshot_ref,
            ExpansionClueSnapshot,
        )
        self.artifacts.require_exact_json(
            completed.clue_snapshot_ref,
            clue_snapshot,
            artifact_types=("expansion.clue_snapshot",),
        )
        context = self.artifacts.get_json(completed.context_ref, ExpansionContext)
        self.artifacts.require_exact_json(
            completed.context_ref,
            context,
            artifact_types=("expansion.context",),
        )
        if (
            clue_snapshot.source_catalog_ref != state.source_catalog_ref
            or clue_snapshot.source_request_refs != completed.source_request_refs
            or clue_snapshot.source_result_refs != completed.source_result_refs
            or clue_snapshot.inbox_snapshot_ref != state.campaign.inbox_snapshot_ref
            or clue_snapshot.feedback_refs != state.campaign.feedback_refs
            or context.snapshot_ref != state.campaign.pool_snapshot_ref
            or context.anchor_parent_refs != state.campaign.anchor_package_refs
            or context.clue_refs != clue_snapshot.clue_refs
        ):
            raise ValueError("completed Source intake changed its frozen Policy context")
        state.intake = completed
        state.intake_ref = completed_ref
        state.context = context
        state.context_ref = completed.context_ref
        return self._advance_checkpoint(
            lock,
            state,
            phase="candidate_loop",
            source_intake_ref=completed_ref,
            source_lease_refs=completed.source_lease_refs,
            source_result_refs=completed.source_result_refs,
            clue_snapshot_ref=completed.clue_snapshot_ref,
            context_ref=completed.context_ref,
            lease_refs=self._unique_refs(
                (*state.checkpoint.lease_refs, *completed.source_lease_refs)
            ),
        )

    async def _recover_active_iteration(
        self,
        lock: CampaignLock,
        state: _CampaignState,
    ) -> _CampaignState:
        """Resume a committed iteration without replaying unknown external work.

        A planned batch has not crossed the durable lease boundary and can be
        continued from its already committed intents.  A leased batch may have
        spent any part of every child reservation before the process died.  A
        durable outcome is reused when one exists; otherwise the framework
        records an infrastructure outcome at the full reservation and settles
        the lease.  Evaluated/told phases only advance the idempotent policy and
        framework checkpoints.
        """

        assert state.checkpoint.active_iteration_ref is not None
        iteration_ref = state.checkpoint.active_iteration_ref
        iteration = self.artifacts.get_json(
            iteration_ref,
            CampaignIterationRecord,
        )
        self.artifacts.require_exact_json(
            iteration_ref,
            iteration,
            artifact_types=("control.campaign_iteration",),
        )
        self._validate_active_iteration(state, iteration, iteration_ref)
        if iteration.status == "planned":
            # Policy.ask already committed this exact batch.  Re-entering the
            # ordinary iteration path continues those intents without asking
            # the Policy again or replaying any external candidate work.
            return await self._execute_iteration(
                lock,
                state,
                self._load_iteration_intents(iteration),
            )
        if iteration.status == "leased":
            return await self._recover_leased_iteration(
                lock,
                state,
                iteration,
                iteration_ref,
            )
        if iteration.status == "evaluated":
            return await self._tell_evaluated_iteration(
                lock,
                state,
                iteration,
                iteration_ref,
            )
        if iteration.status == "told":
            return self._complete_told_iteration(
                lock,
                state,
                iteration,
                iteration_ref,
            )
        raise ValueError(f"unsupported active Campaign iteration phase: {iteration.status}")

    async def _recover_leased_iteration(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        leased: CampaignIterationRecord,
        leased_ref: ArtifactRef,
    ) -> _CampaignState:
        """Conservatively close every candidate behind a committed lease batch."""

        intents = self._load_iteration_intents(leased)
        leases_by_owner: dict[str, tuple[BudgetLease, ArtifactRef]] = {}
        for lease_ref in leased.lease_refs:
            lease = self.artifacts.get_json(lease_ref, BudgetLease)
            self.artifacts.require_exact_json(
                lease_ref,
                lease,
                artifact_types=("control.budget_lease",),
            )
            if lease.status != "active":
                raise ValueError("leased iteration must reference active budget leases")
            if lease.owner_id in leases_by_owner:
                raise ValueError("leased iteration contains duplicate lease owners")
            restored = next(
                (item for item in state.ledger.active_leases if item.lease_id == lease.lease_id),
                None,
            )
            if restored != lease:
                raise ValueError("Campaign ledger does not contain the exact active lease")
            leases_by_owner[lease.owner_id] = (lease, lease_ref)

        active_leases: dict[int, tuple[BudgetLease, ArtifactRef]] = {}
        results: list[CampaignCandidateResult] = []
        for index, (intent, intent_ref) in enumerate(zip(intents, leased.intent_refs, strict=True)):
            lease_binding = leases_by_owner.get(intent.intent_id)
            durable = self._find_durable_outcome(
                state=state,
                iteration_ref=leased_ref,
                intent=intent,
                intent_ref=intent_ref,
            )
            if durable is not None:
                if (lease_binding is None) != (
                    durable.outcome.terminal_status == "admission_rejected"
                ):
                    raise ValueError("durable outcome does not match its admission/lease state")
                results.append(durable)
                if lease_binding is not None:
                    active_leases[index] = lease_binding
                continue
            if lease_binding is not None:
                lease, lease_ref = lease_binding
                active_leases[index] = lease_binding
                results.append(
                    self._infrastructure_outcome(
                        state=state,
                        iteration_ref=leased_ref,
                        intent=intent,
                        intent_ref=intent_ref,
                        lease=lease,
                        lease_ref=lease_ref,
                        reason=_RECOVERY_UNKNOWN_LEASE_REASON,
                    )
                )
                continue
            admission_error = self._admission_error(state, intent)
            if admission_error is None:
                raise ValueError("admitted Campaign intent is missing its durable budget lease")
            results.append(
                self._admission_rejected(
                    state=state,
                    iteration_ref=leased_ref,
                    intent=intent,
                    intent_ref=intent_ref,
                    reason=admission_error,
                )
            )

        terminal_lease_refs: list[ArtifactRef] = []
        for index, (lease, lease_ref) in active_leases.items():
            usage = results[index].outcome.budget_usage
            try:
                settled = state.ledger.settle(lease.lease_id, usage)
            except (BudgetExceeded, ValueError):
                settled = state.ledger.settle(
                    lease.lease_id,
                    BudgetUsage(),
                    unknown_upper_bound=self._full_usage(lease.reserved),
                )
            terminal_lease_refs.append(
                self._persist_lease(
                    state.campaign_ref,
                    leased.intent_refs[index],
                    settled,
                    previous_ref=lease_ref,
                )
            )

        outcome_refs = tuple(item.outcome_ref for item in results)
        evaluated = leased.model_copy(
            update={
                "status": "evaluated",
                "lease_refs": tuple(terminal_lease_refs),
                "outcome_refs": outcome_refs,
            }
        )
        evaluated_ref = self._persist_iteration(evaluated, previous_ref=leased_ref)
        state = self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=evaluated_ref,
            lease_refs=self._unique_refs((*state.checkpoint.lease_refs, *terminal_lease_refs)),
            outcome_refs=self._unique_refs((*state.checkpoint.outcome_refs, *outcome_refs)),
        )
        return await self._tell_evaluated_iteration(
            lock,
            state,
            evaluated,
            evaluated_ref,
        )

    async def _tell_evaluated_iteration(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        evaluated: CampaignIterationRecord,
        evaluated_ref: ArtifactRef,
    ) -> _CampaignState:
        """Persist Policy.tell before making the iteration framework-terminal."""

        if evaluated.status != "evaluated":
            raise ValueError("Policy.tell requires an evaluated Campaign iteration")
        self._validate_active_iteration(state, evaluated, evaluated_ref)
        outcomes = self._load_iteration_outcomes(evaluated)
        policy_after = await state.policy.tell(state.policy_checkpoint, outcomes)
        self._validate_policy_after(state, policy_after, outcomes)
        policy_after_ref = self._persist_policy_checkpoint(
            state.campaign_ref,
            policy_after,
            previous_ref=state.policy_checkpoint_ref,
        )
        told = evaluated.model_copy(update={"status": "told", "policy_after_ref": policy_after_ref})
        told_ref = self._persist_iteration(told, previous_ref=evaluated_ref)
        state.policy_checkpoint = policy_after
        state.policy_checkpoint_ref = policy_after_ref
        state = self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=told_ref,
            policy_checkpoint_ref=policy_after_ref,
        )
        return self._complete_told_iteration(
            lock,
            state,
            told,
            told_ref,
        )

    def _complete_told_iteration(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        told: CampaignIterationRecord,
        told_ref: ArtifactRef,
    ) -> _CampaignState:
        """Move one durable told iteration into the Campaign checkpoint history."""

        if told.status != "told" or told.policy_after_ref is None:
            raise ValueError("Campaign completion requires a told iteration")
        self._validate_active_iteration(state, told, told_ref)
        outcomes = self._load_iteration_outcomes(told)
        policy_after = self.artifacts.get_json(
            told.policy_after_ref,
            PolicyCheckpoint,
        )
        self.artifacts.require_exact_json(
            told.policy_after_ref,
            policy_after,
            artifact_types=("expansion.policy_checkpoint",),
        )
        self._validate_policy_after(state, policy_after, outcomes)
        released_refs = tuple(
            outcome.released_package_ref
            for outcome in outcomes
            if outcome.terminal_status == "released" and outcome.released_package_ref is not None
        )
        all_infrastructure = bool(outcomes) and all(
            outcome.terminal_status == "infrastructure_error" for outcome in outcomes
        )
        state.policy_checkpoint = policy_after
        state.policy_checkpoint_ref = told.policy_after_ref
        return self._advance_checkpoint(
            lock,
            state,
            active_iteration_ref=None,
            next_iteration=told.number + 1,
            policy_checkpoint_ref=told.policy_after_ref,
            completed_iteration_refs=self._unique_refs(
                (*state.checkpoint.completed_iteration_refs, told_ref)
            ),
            outcome_refs=self._unique_refs((*state.checkpoint.outcome_refs, *told.outcome_refs)),
            released_package_refs=self._unique_refs(
                (*state.checkpoint.released_package_refs, *released_refs)
            ),
            consecutive_infrastructure_failures=(
                state.checkpoint.consecutive_infrastructure_failures + 1
                if all_infrastructure
                else 0
            ),
        )

    def _validate_active_iteration(
        self,
        state: _CampaignState,
        iteration: CampaignIterationRecord,
        iteration_ref: ArtifactRef,
    ) -> None:
        if state.checkpoint.active_iteration_ref != iteration_ref:
            raise ValueError("Campaign iteration is not the active checkpoint revision")
        if iteration.campaign_ref != state.campaign_ref:
            raise ValueError("active iteration belongs to another Campaign")
        if iteration.number != state.checkpoint.next_iteration:
            raise ValueError("active iteration number differs from the Campaign checkpoint")
        allowed_policy_refs = {iteration.policy_before_ref}
        if iteration.policy_after_ref is not None:
            allowed_policy_refs.add(iteration.policy_after_ref)
        if state.checkpoint.policy_checkpoint_ref not in allowed_policy_refs:
            raise ValueError("active iteration is not bound to the Campaign Policy checkpoint")

    def _load_iteration_intents(
        self,
        iteration: CampaignIterationRecord,
    ) -> tuple[MutationIntent, ...]:
        intents: list[MutationIntent] = []
        for intent_ref in iteration.intent_refs:
            intent = self.artifacts.get_json(intent_ref, MutationIntent)
            self.artifacts.require_exact_json(
                intent_ref,
                intent,
                artifact_types=("expansion.mutation_intent",),
            )
            intents.append(intent)
        return tuple(intents)

    def _load_iteration_outcomes(
        self,
        iteration: CampaignIterationRecord,
    ) -> tuple[CandidateOutcome, ...]:
        outcomes: list[CandidateOutcome] = []
        for intent_ref, outcome_ref in zip(
            iteration.intent_refs,
            iteration.outcome_refs,
            strict=True,
        ):
            outcome = self.artifacts.get_json(outcome_ref, CandidateOutcome)
            self.artifacts.require_exact_json(
                outcome_ref,
                outcome,
                artifact_types=("expansion.candidate_outcome",),
            )
            bound_iteration = self.artifacts.get_json(
                outcome.iteration_ref,
                CampaignIterationRecord,
            )
            self.artifacts.require_exact_json(
                outcome.iteration_ref,
                bound_iteration,
                artifact_types=("control.campaign_iteration",),
            )
            dependencies = set(self.artifacts.dependencies(outcome_ref))
            if (
                outcome.campaign_ref != iteration.campaign_ref
                or outcome.intent_ref != intent_ref
                or bound_iteration.iteration_id != iteration.iteration_id
                or bound_iteration.number != iteration.number
                or bound_iteration.campaign_ref != iteration.campaign_ref
                or bound_iteration.intent_refs != iteration.intent_refs
                or not {
                    iteration.campaign_ref,
                    outcome.iteration_ref,
                    intent_ref,
                    outcome.attempt_ref,
                }
                <= dependencies
            ):
                raise ValueError("CandidateOutcome does not bind its exact Campaign iteration")
            outcomes.append(outcome)
        return tuple(outcomes)

    def _find_durable_outcome(
        self,
        *,
        state: _CampaignState,
        iteration_ref: ArtifactRef,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
    ) -> CampaignCandidateResult | None:
        outcome_id = self._stable_id(
            "candidate-outcome",
            state.campaign.campaign_id,
            intent.intent_id,
        )
        matches: list[tuple[CandidateOutcome, ArtifactRef]] = []
        for outcome_ref in self.artifacts.list_revisions(f"{outcome_id}:record"):
            if outcome_ref.artifact_type != "expansion.candidate_outcome":
                continue
            outcome = self.artifacts.get_json(outcome_ref, CandidateOutcome)
            if (
                outcome.outcome_id == outcome_id
                and outcome.campaign_ref == state.campaign_ref
                and outcome.iteration_ref == iteration_ref
                and outcome.intent_ref == intent_ref
            ):
                dependencies = set(self.artifacts.dependencies(outcome_ref))
                required = {
                    state.campaign_ref,
                    iteration_ref,
                    intent_ref,
                    outcome.attempt_ref,
                }
                if not required <= dependencies:
                    raise ValueError("durable CandidateOutcome has incomplete dependencies")
                matches.append((outcome, outcome_ref))
        if not matches:
            return None
        known = tuple(
            item
            for item in matches
            if item[0].terminal_reason_code != _RECOVERY_UNKNOWN_LEASE_REASON
        )
        selected = known or tuple(matches)
        distinct = {item[0].stable_json() for item in selected}
        if len(distinct) != 1:
            raise ValueError("multiple conflicting durable outcomes bind one Campaign intent")
        outcome, outcome_ref = min(selected, key=lambda item: item[1].revision_id)
        return CampaignCandidateResult(
            outcome=outcome,
            outcome_ref=outcome_ref,
            attempt_ref=outcome.attempt_ref,
        )

    def _advance_checkpoint(
        self,
        lock: CampaignLock,
        state: _CampaignState,
        **updates: object,
    ) -> _CampaignState:
        checkpoint = CampaignRunCheckpoint.model_validate(
            {
                **state.checkpoint.model_dump(mode="python"),
                "revision": state.checkpoint.revision + 1,
                "updated_at": datetime.now(UTC),
                **updates,
            }
        )
        checkpoint_ref = self._persist_checkpoint(
            checkpoint,
            previous_ref=state.checkpoint_ref,
        )
        self.campaign_store.compare_and_swap(
            lock,
            expected_checkpoint_ref=state.checkpoint_ref,
            checkpoint_ref=checkpoint_ref,
            checkpoint_revision=checkpoint.revision,
        )
        state.checkpoint = checkpoint
        state.checkpoint_ref = checkpoint_ref
        return state

    def _admission_error(
        self,
        state: _CampaignState,
        intent: MutationIntent,
    ) -> str | None:
        if state.context is None:
            raise ValueError("candidate admission requires a frozen ExpansionContext")
        if not set(intent.target_coverage_dimensions) <= set(
            state.campaign.target_coverage_dimensions
        ):
            return "target_coverage_outside_campaign"
        operators = {item.kind: item for item in state.context.operator_catalog.operators}
        operator = operators.get(intent.operator)
        if operator is None or operator.version != intent.operator_version:
            return "operator_not_in_frozen_catalog"
        if not operator.minimum_parents <= len(intent.parent_refs) <= operator.maximum_parents:
            return "operator_parent_count_rejected"
        if operator.requires_clue and not intent.clue_refs:
            return "operator_requires_admitted_clue"
        if intent.operator == "composite" and len(intent.parent_refs) == 1 and not intent.clue_refs:
            return "composite_single_parent_requires_clue"
        if not set(intent.clue_refs) <= set(state.context.clue_refs):
            return "clue_not_in_frozen_inbox"
        parameters = {item.key: item.value for item in intent.parameters}
        if len(parameters) != len(intent.parameters):
            return "duplicate_operator_parameter"
        if set(parameters) - set(operator.parameter_axes):
            return "operator_parameter_axis_rejected"
        if any(
            not isinstance(value, str) or value not in operator.parameter_axes[key]
            for key, value in parameters.items()
        ):
            return "operator_parameter_value_rejected"
        snapshot_parents = {
            item.manifest_ref.revision_id: item.manifest_ref for item in state.snapshot.releases
        }
        archive_parents = {
            item.revision_id: item for item in state.checkpoint.released_package_refs
        }
        for parent_ref in intent.parent_refs:
            try:
                if archive_parents.get(parent_ref.revision_id) == parent_ref:
                    self.registry.require_released_manifest(parent_ref)
                elif snapshot_parents.get(parent_ref.revision_id) == parent_ref:
                    self.registry.require_snapshot_parent(
                        state.snapshot.snapshot_id,
                        parent_ref,
                    )
                else:
                    return "parent_not_authorized_by_campaign"
            except Exception:
                return "parent_no_longer_eligible"
        return None

    def _admission_rejected(
        self,
        *,
        state: _CampaignState,
        iteration_ref: ArtifactRef,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        reason: str,
    ) -> CampaignCandidateResult:
        attempt_id = self._stable_id(
            "admission-attempt", iteration_ref.revision_id, intent.intent_id
        )
        pending = ExpansionCandidateAttempt(
            attempt_id=attempt_id,
            campaign_ref=state.campaign_ref,
            iteration_number=state.checkpoint.next_iteration,
            intent_ref=intent_ref,
            status="admission_pending",
        )
        pending_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=pending,
            dependencies=(state.campaign_ref, iteration_ref, intent_ref),
        )
        outcome = CandidateOutcome(
            outcome_id=self._stable_id(
                "candidate-outcome", state.campaign.campaign_id, intent.intent_id
            ),
            campaign_ref=state.campaign_ref,
            iteration_ref=iteration_ref,
            intent_ref=intent_ref,
            attempt_ref=pending_ref,
            terminal_reason_code=self._safe_identifier(reason),
            terminal_status="admission_rejected",
        )
        outcome_ref = self._persist_outcome(outcome, (pending_ref,))
        terminal = pending.model_copy(
            update={"status": "admission_rejected", "outcome_ref": outcome_ref}
        )
        terminal_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=terminal,
            dependencies=(pending_ref, outcome_ref),
        )
        return CampaignCandidateResult(outcome, outcome_ref, terminal_ref)

    def _infrastructure_outcome(
        self,
        *,
        state: _CampaignState,
        iteration_ref: ArtifactRef,
        intent: MutationIntent,
        intent_ref: ArtifactRef,
        lease: BudgetLease,
        lease_ref: ArtifactRef,
        reason: str,
    ) -> CampaignCandidateResult:
        attempt_id = self._stable_id(
            "infrastructure-attempt", iteration_ref.revision_id, intent.intent_id
        )
        leased = ExpansionCandidateAttempt(
            attempt_id=attempt_id,
            campaign_ref=state.campaign_ref,
            iteration_number=state.checkpoint.next_iteration,
            intent_ref=intent_ref,
            lease_ref=lease_ref,
            status="leased",
        )
        leased_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=leased,
            dependencies=(state.campaign_ref, iteration_ref, intent_ref, lease_ref),
        )
        outcome = CandidateOutcome(
            outcome_id=self._stable_id(
                "candidate-outcome", state.campaign.campaign_id, intent.intent_id
            ),
            campaign_ref=state.campaign_ref,
            iteration_ref=iteration_ref,
            intent_ref=intent_ref,
            attempt_ref=leased_ref,
            terminal_reason_code=self._safe_identifier(reason),
            terminal_status="infrastructure_error",
            budget_usage=self._full_usage(lease.reserved),
        )
        outcome_ref = self._persist_outcome(outcome, (leased_ref, lease_ref))
        terminal = leased.model_copy(
            update={"status": "infrastructure_error", "outcome_ref": outcome_ref}
        )
        terminal_ref = self.artifacts.put_json(
            artifact_id=f"{attempt_id}:state",
            artifact_type="control.expansion_candidate_attempt",
            value=terminal,
            dependencies=(leased_ref, outcome_ref),
        )
        return CampaignCandidateResult(outcome, outcome_ref, terminal_ref)

    def _validate_policy_after(
        self,
        state: _CampaignState,
        checkpoint: PolicyCheckpoint,
        outcomes: Sequence[CandidateOutcome],
    ) -> None:
        if (
            checkpoint.policy_id != state.campaign.policy_id
            or checkpoint.policy_version != state.campaign.policy_version
        ):
            raise ValueError("Policy returned a checkpoint for another implementation")
        allowed_archive = set(state.policy_checkpoint.archive_parent_refs)
        allowed_archive.update(
            outcome.released_package_ref
            for outcome in outcomes
            if outcome.terminal_status == "released" and outcome.released_package_ref is not None
        )
        if set(checkpoint.archive_parent_refs) != allowed_archive:
            raise ValueError("Policy attempted to forge or omit the framework release archive")
        expected_seen = set(state.policy_checkpoint.seen_outcome_ids)
        expected_seen.update(outcome.outcome_id for outcome in outcomes)
        if set(checkpoint.seen_outcome_ids) != expected_seen:
            raise ValueError("Policy checkpoint outcome acknowledgement is incomplete")
        allowed_behavior = set(state.policy_checkpoint.archive_behavior_dimensions)
        allowed_behavior.update(
            item.descriptor for outcome in outcomes for item in outcome.behavior_descriptors
        )
        if not set(checkpoint.archive_behavior_dimensions) <= allowed_behavior:
            raise ValueError("Policy checkpoint forged a behavior descriptor")

    def _validate_inbox(self, inbox_ref: ArtifactRef | None) -> tuple[ArtifactRef, ...]:
        if inbox_ref is None:
            return ()
        inbox = self.artifacts.get_json(inbox_ref, ExpansionInboxSnapshot)
        self.artifacts.require_exact_json(
            inbox_ref,
            inbox,
            artifact_types=("discovery.expansion_inbox_snapshot",),
        )
        decisions: list[DiscoveryAdmissionDecision] = []
        for decision_ref in inbox.admission_decision_refs:
            decision = self.artifacts.get_json(decision_ref, DiscoveryAdmissionDecision)
            self.artifacts.require_exact_json(
                decision_ref,
                decision,
                artifact_types=("discovery.admission_decision",),
            )
            decisions.append(decision)
        for clue_ref in inbox.clue_refs:
            clue = self.artifacts.get_json(clue_ref, ExpansionClue)
            self.artifacts.require_exact_json(
                clue_ref,
                clue,
                artifact_types=("discovery.expansion_clue",),
            )
            matches = tuple(
                item
                for item in decisions
                if item.clue_ref == clue_ref
                and item.classification == "expansion"
                and item.destination == "expansion_inbox"
            )
            if len(matches) != 1:
                raise ValueError("Inbox clue lacks one exact expansion admission decision")
        return inbox.clue_refs

    def _validate_feedback(self, feedback_refs: Sequence[ArtifactRef]) -> None:
        for feedback_ref in feedback_refs:
            feedback = self.artifacts.get_json(feedback_ref, CapabilityFeedback)
            self.artifacts.require_exact_json(
                feedback_ref,
                feedback,
                artifact_types=("consumer.capability_feedback",),
            )
            snapshot = self.registry.load_suite_snapshot(feedback.suite_snapshot_id)
            if snapshot.snapshot_digest != feedback.suite_snapshot_digest:
                raise ValueError(
                    "CapabilityFeedback Suite digest differs from Registry snapshot"
                )
            required_dependencies = set(feedback.evidence_refs)
            if not required_dependencies <= set(self.artifacts.dependencies(feedback_ref)):
                raise ValueError("CapabilityFeedback has incomplete artifact dependencies")

    def _deduplicate_clues(
        self,
        *,
        inbox_clue_refs: tuple[ArtifactRef, ...],
        source_clue_refs: tuple[ArtifactRef, ...],
    ) -> tuple[ArtifactRef, ...]:
        seen: set[str] = set()
        result: list[ArtifactRef] = []
        for refs, artifact_type in (
            (inbox_clue_refs, "discovery.expansion_clue"),
            (source_clue_refs, "expansion.source_clue"),
        ):
            for clue_ref in refs:
                clue = self.artifacts.get_json(clue_ref, ExpansionClue)
                self.artifacts.require_exact_json(
                    clue_ref,
                    clue,
                    artifact_types=(artifact_type,),
                )
                if clue.dedup_fingerprint in seen:
                    continue
                seen.add(clue.dedup_fingerprint)
                result.append(clue_ref)
        return tuple(result)

    @staticmethod
    def _validate_source_catalog_budget(
        source_catalog: ExpansionSourceCatalog,
        *,
        campaign_budget: Budget,
        candidate_budget: Budget,
    ) -> None:
        for descriptor in source_catalog.sources:
            if descriptor.budget.wall_seconds > campaign_budget.wall_seconds:
                raise ValueError(
                    f"Source {descriptor.source_id} timeout exceeds Campaign deadline"
                )
        for field in Budget.model_fields:
            if field in {"schema_version", "wall_seconds"}:
                continue
            required = Decimal(str(getattr(candidate_budget, field))) + sum(
                Decimal(str(getattr(item.budget, field)))
                for item in source_catalog.sources
            )
            if required > Decimal(str(getattr(campaign_budget, field))):
                raise ValueError(
                    f"Campaign budget cannot reserve Source intake plus one candidate: {field}"
                )

    def _source_parents(
        self,
        manifest_refs: Sequence[ArtifactRef],
        *,
        anchor_refs: Sequence[ArtifactRef],
        descriptor: ExpansionSourceDescriptor,
        campaign_seed: int,
    ) -> tuple[ExpansionSourceParent, ...]:
        pool_by_revision = {item.revision_id: item for item in manifest_refs}
        anchors: list[ArtifactRef] = []
        seen: set[str] = set()
        for anchor in anchor_refs:
            if pool_by_revision.get(anchor.revision_id) != anchor:
                raise ValueError("ExpansionSource anchor is absent from the frozen Pool")
            if anchor.revision_id in seen:
                raise ValueError("ExpansionSource anchors must be unique")
            seen.add(anchor.revision_id)
            anchors.append(anchor)
        if len(anchors) > descriptor.maximum_parents:
            raise ValueError(
                f"Source {descriptor.source_id} maximum_parents cannot retain all anchors"
            )
        remaining = [item for item in manifest_refs if item.revision_id not in seen]
        remaining.sort(
            key=lambda item: hashlib.sha256(
                (
                    f"{campaign_seed}\0{descriptor.source_id}\0{descriptor.kind}\0"
                    f"{item.revision_id}"
                ).encode()
            ).digest()
        )
        selected = (
            *anchors,
            *remaining[: descriptor.maximum_parents - len(anchors)],
        )
        result: list[ExpansionSourceParent] = []
        for manifest_ref in selected:
            manifest = self.artifacts.get_json(manifest_ref, EnvironmentPackageManifest)
            self.artifacts.require_exact_json(
                manifest_ref,
                manifest,
                artifact_types=("environment_package_manifest",),
            )
            design = self.artifacts.get_json(manifest.design_ref, EnvironmentDesign)
            self.artifacts.require_exact_json(
                manifest.design_ref,
                design,
                artifact_types=("design.environment_design", "expansion.environment_design"),
            )
            coverage = self.artifacts.get_json(design.coverage_map_ref, CoverageMap)
            self.artifacts.require_exact_json(
                design.coverage_map_ref,
                coverage,
                artifact_types=("design.coverage_map", "expansion.coverage_map"),
            )
            result.append(
                ExpansionSourceParent(
                    package_manifest_ref=manifest_ref,
                    design_ref=manifest.design_ref,
                    coverage_map_ref=design.coverage_map_ref,
                )
            )
        return tuple(result)

    def _parent_descriptors(
        self,
        manifest_refs: Sequence[ArtifactRef],
    ) -> tuple[ParentDescriptor, ...]:
        result: list[ParentDescriptor] = []
        for manifest_ref in manifest_refs:
            manifest = self.artifacts.get_json(manifest_ref, EnvironmentPackageManifest)
            self.artifacts.require_exact_json(
                manifest_ref,
                manifest,
                artifact_types=("environment_package_manifest",),
            )
            design = self.artifacts.get_json(manifest.design_ref, EnvironmentDesign)
            self.artifacts.require_exact_json(
                manifest.design_ref,
                design,
                artifact_types=("design.environment_design", "expansion.environment_design"),
            )
            coverage = self.artifacts.get_json(design.coverage_map_ref, CoverageMap)
            self.artifacts.require_exact_json(
                design.coverage_map_ref,
                coverage,
                artifact_types=("design.coverage_map", "expansion.coverage_map"),
            )
            dimensions = tuple(item.dimension for item in coverage.dimensions)
            result.append(
                ParentDescriptor(
                    package_ref=manifest_ref,
                    coverage_dimensions=dimensions,
                    behavior_dimensions=(manifest.lineage.semantic.operator_id,),
                )
            )
        return tuple(result)

    @staticmethod
    def _policy(
        policy_id: str,
        parameters: Sequence[KeyValue],
    ) -> EnvironmentExpansionPolicy:
        values = {item.key: item.value for item in parameters}
        if len(values) != len(parameters):
            raise ValueError("policy parameters must have unique keys")
        if policy_id == "random-search" and not values:
            return RandomSearchPolicy()
        if policy_id == "wide-search" and not values:
            return WideSearchPolicy()
        if policy_id == "evolutionary-archive":
            unknown = set(values) - {"external_injection_rate"}
            if unknown:
                raise ValueError(f"unknown evolutionary policy parameters: {sorted(unknown)}")
            rate = values.get("external_injection_rate", 0.25)
            if not isinstance(rate, int | float):
                raise ValueError("external_injection_rate must be numeric")
            return EvolutionaryArchivePolicy(external_injection_rate=float(rate))
        raise ValueError(f"unknown Expansion Policy: {policy_id}")

    def _persist_iteration(
        self,
        iteration: CampaignIterationRecord,
        *,
        previous_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        dependencies = [
            iteration.campaign_ref,
            iteration.policy_before_ref,
            *iteration.intent_refs,
            *iteration.lease_refs,
            *iteration.outcome_refs,
        ]
        if iteration.policy_after_ref is not None:
            dependencies.append(iteration.policy_after_ref)
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{iteration.iteration_id}:state",
            artifact_type="control.campaign_iteration",
            value=iteration,
            dependencies=self._unique_refs(tuple(dependencies)),
        )

    def _persist_policy_checkpoint(
        self,
        campaign_ref: ArtifactRef,
        checkpoint: PolicyCheckpoint,
        *,
        previous_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        dependencies = [campaign_ref, *checkpoint.archive_parent_refs]
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=self._stable_id(
                "policy-checkpoint",
                campaign_ref.revision_id,
            ),
            artifact_type="expansion.policy_checkpoint",
            value=checkpoint,
            dependencies=self._unique_refs(tuple(dependencies)),
        )

    def _persist_checkpoint(
        self,
        checkpoint: CampaignRunCheckpoint,
        *,
        previous_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        dependencies = [
            checkpoint.campaign_ref,
            checkpoint.policy_checkpoint_ref,
            checkpoint.source_catalog_ref,
            checkpoint.source_intake_ref,
            *checkpoint.source_request_refs,
            *checkpoint.source_lease_refs,
            *checkpoint.source_result_refs,
            *checkpoint.completed_iteration_refs,
            *checkpoint.lease_refs,
            *checkpoint.outcome_refs,
            *checkpoint.released_package_refs,
        ]
        if checkpoint.clue_snapshot_ref is not None:
            dependencies.append(checkpoint.clue_snapshot_ref)
        if checkpoint.context_ref is not None:
            dependencies.append(checkpoint.context_ref)
        if checkpoint.active_iteration_ref is not None:
            dependencies.append(checkpoint.active_iteration_ref)
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{checkpoint.checkpoint_id}:state",
            artifact_type="control.campaign_checkpoint",
            value=checkpoint,
            dependencies=self._unique_refs(tuple(dependencies)),
        )

    def _persist_source_intake(
        self,
        intake: SourceIntakeRecord,
        *,
        previous_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        dependencies = [
            intake.campaign_ref,
            intake.source_catalog_ref,
            *intake.source_request_refs,
            *intake.source_lease_refs,
            *intake.source_result_refs,
        ]
        if intake.clue_snapshot_ref is not None:
            dependencies.append(intake.clue_snapshot_ref)
        if intake.context_ref is not None:
            dependencies.append(intake.context_ref)
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{intake.intake_id}:state",
            artifact_type="control.source_intake",
            value=intake,
            dependencies=self._unique_refs(tuple(dependencies)),
        )

    def _persist_lease(
        self,
        campaign_ref: ArtifactRef,
        intent_ref: ArtifactRef,
        lease: BudgetLease,
        *,
        previous_ref: ArtifactRef | None,
    ) -> ArtifactRef:
        dependencies = [campaign_ref, intent_ref]
        if previous_ref is not None:
            dependencies.append(previous_ref)
        return self.artifacts.put_json(
            artifact_id=f"{lease.lease_id}:state",
            artifact_type="control.budget_lease",
            value=lease,
            dependencies=tuple(dependencies),
        )

    def _persist_outcome(
        self,
        outcome: CandidateOutcome,
        extra_dependencies: Sequence[ArtifactRef],
    ) -> ArtifactRef:
        return self.artifacts.put_json(
            artifact_id=f"{outcome.outcome_id}:record",
            artifact_type="expansion.candidate_outcome",
            value=outcome,
            dependencies=self._unique_refs(
                (
                    outcome.campaign_ref,
                    outcome.iteration_ref,
                    outcome.intent_ref,
                    outcome.attempt_ref,
                    *extra_dependencies,
                )
            ),
        )

    @staticmethod
    def _affordable_count(remaining: Budget, candidate: Budget, maximum: int) -> int:
        if candidate.wall_seconds > remaining.wall_seconds:
            return 0
        counts = [maximum]
        for field_name in Budget.model_fields:
            if field_name in {"schema_version", "wall_seconds"}:
                continue
            required = getattr(candidate, field_name)
            if required:
                counts.append(int(getattr(remaining, field_name) // required))
        return max(0, min(counts))

    @staticmethod
    def _full_usage(budget: Budget) -> BudgetUsage:
        return BudgetUsage.model_validate(
            {
                field_name: getattr(budget, field_name)
                for field_name in Budget.model_fields
                if field_name != "schema_version"
            }
        )

    @staticmethod
    def _elapsed(state: _CampaignState) -> float:
        return min(
            state.campaign.budget.wall_seconds,
            max(0.0, time.monotonic() - state.started_monotonic),
        )

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
        return f"{prefix}:{digest}"

    @staticmethod
    def _source_seed(campaign_seed: int, source_id: str) -> int:
        digest = hashlib.sha256(f"{campaign_seed}\0{source_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big")

    @staticmethod
    def _safe_identifier(value: str) -> str:
        cleaned = "".join(character if character.isalnum() else "_" for character in value)
        cleaned = cleaned.strip("_")[:120]
        return cleaned or "unknown"

    @staticmethod
    def _unique_refs(refs: Sequence[ArtifactRef]) -> tuple[ArtifactRef, ...]:
        unique: dict[str, ArtifactRef] = {}
        for ref in refs:
            unique[ref.revision_id] = ref
        return tuple(unique.values())


__all__ = [
    "CampaignCandidateResult",
    "ExpandResult",
    "ExpansionCampaignRunner",
    "ExpansionCandidateExecutor",
    "validate_campaign_report_graph",
]

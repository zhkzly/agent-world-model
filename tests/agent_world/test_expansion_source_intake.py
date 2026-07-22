from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from v3_fixture import build_release_graph

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.contracts import (
    Budget,
    ExpansionSourceCatalog,
    ExpansionSourceDescriptor,
    ExpansionSourceRequest,
    ExpansionSourceResult,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.control import CampaignRunCheckpoint, CampaignStore
from agent_world.designer import ExpansionSourceBundle
from agent_world.expansion_runner import (
    ExpansionCampaignRunner,
    validate_campaign_report_graph,
)
from agent_world.registry import EnvironmentRegistry, ReleaseRecord


def _expansion_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="environment-expansion-intake-test",
        allowed_artifact_type_prefixes=("control.", "expansion."),
    )


def _publish_parent(
    root: Path,
    store: ArtifactStore,
    registry: EnvironmentRegistry,
) -> ReleaseRecord:
    root.mkdir(parents=True, exist_ok=True)
    graph = build_release_graph(root, store, variant="source-intake")
    reservation = registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
    )
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    return registry.publish(prepared)


class _NeverCandidateExecutor:
    async def execute_expansion_candidate(self, **_kwargs: object) -> object:
        raise AssertionError("candidate execution must not run during Source intake")


class _InterruptAfterDurableLeaseSource:
    def __init__(
        self,
        *,
        artifacts: ArtifactWriter,
        campaigns: CampaignStore,
        campaign_id: str,
    ) -> None:
        self.artifacts = artifacts
        self.campaigns = campaigns
        self.campaign_id = campaign_id
        self.calls = 0

    async def discover(
        self,
        *,
        request: ExpansionSourceRequest,
        request_ref: object,
        workspace: Path,
        invocation_budget: Budget,
    ) -> ExpansionSourceBundle:
        del request_ref, workspace, invocation_budget
        self.calls += 1
        head = self.campaigns.read_head(self.campaign_id)
        assert head is not None
        checkpoint = self.artifacts.get_json(
            head.checkpoint_ref,
            CampaignRunCheckpoint,
        )
        assert checkpoint.phase == "source_intake"
        assert len(checkpoint.source_lease_refs) == len(checkpoint.source_request_refs) == 1
        lease = self.artifacts.get_json(checkpoint.source_lease_refs[0])
        assert lease["owner_id"] == request.request_id
        assert lease["status"] == "active"
        raise asyncio.CancelledError


class _NeverReplaySource:
    def __init__(self) -> None:
        self.calls = 0

    async def discover(self, **_kwargs: object) -> ExpansionSourceBundle:
        self.calls += 1
        raise AssertionError("recovery must never replay a Source behind an active lease")


def test_resume_never_replays_unknown_source_lease_and_freezes_context(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        root = tmp_path / "foundry"
        store = ArtifactStore(root / "artifacts")
        artifacts = _expansion_writer(store)
        registry = EnvironmentRegistry(root / "registry", store)
        release = _publish_parent(root / "parent", store, registry)
        campaigns = CampaignStore(root / "campaigns")
        campaign_id = "campaign:source-intake-recovery"
        source = _InterruptAfterDurableLeaseSource(
            artifacts=artifacts,
            campaigns=campaigns,
            campaign_id=campaign_id,
        )
        runner = ExpansionCampaignRunner(
            artifact_store=artifacts,
            registry=registry,
            campaign_store=campaigns,
            candidate_executor=_NeverCandidateExecutor(),  # type: ignore[arg-type]
            expansion_source=source,
            source_workspace_root=root / "source-workspaces",
        )
        source_budget = Budget(
            llm_tokens=200,
            agent_turns=2,
            search_calls=1,
            tool_calls=3,
            wall_seconds=30,
        )
        candidate_budget = Budget(
            llm_tokens=100,
            agent_turns=1,
            wall_seconds=30,
        )
        campaign_budget = Budget(
            llm_tokens=400,
            agent_turns=4,
            search_calls=1,
            tool_calls=3,
            wall_seconds=120,
        )
        catalog = ExpansionSourceCatalog(
            catalog_id="source-catalog:recovery",
            sources=(
                ExpansionSourceDescriptor(
                    source_id="source:random-theme",
                    kind="random_theme",
                    budget=source_budget,
                ),
            ),
        )

        with campaigns.exclusive(campaign_id) as lock:
            state = runner._create_state(  # noqa: SLF001
                lock=lock,
                campaign_id=campaign_id,
                anchor_package_refs=(release.manifest_ref,),
                target_coverage_dimensions=("tool_semantics",),
                inbox_snapshot_ref=None,
                source_catalog=catalog,
                feedback_refs=(),
                policy_id="random-search",
                policy_parameters=(),
                permissions=PermissionScope(),
                campaign_budget=campaign_budget,
                candidate_budget=candidate_budget,
                release_profile=ReleaseProfile(profile_id="source-intake-test"),
                campaign_seed=17,
                maximum_intents_per_iteration=1,
                maximum_in_flight=1,
                maximum_iterations=1,
                maximum_no_release_iterations=1,
                maximum_infrastructure_error_iterations=1,
                version_reservation_ttl_seconds=60,
                allowed_source_kinds=("web",),
                risk_level="medium",
                fidelity_requirements=(),
            )
            with pytest.raises(asyncio.CancelledError):
                await runner._execute_source_intake(lock, state)  # noqa: SLF001
        assert source.calls == 1

        interrupted_head = campaigns.read_head(campaign_id)
        assert interrupted_head is not None
        interrupted = artifacts.get_json(
            interrupted_head.checkpoint_ref,
            CampaignRunCheckpoint,
        )
        assert interrupted.phase == "source_intake"
        assert len(interrupted.source_lease_refs) == 1

        no_replay = _NeverReplaySource()
        recovery_runner = ExpansionCampaignRunner(
            artifact_store=artifacts,
            registry=registry,
            campaign_store=campaigns,
            candidate_executor=_NeverCandidateExecutor(),  # type: ignore[arg-type]
            expansion_source=no_replay,
            source_workspace_root=root / "source-workspaces",
        )
        with campaigns.exclusive(campaign_id) as lock:
            recovered = recovery_runner._load_state(  # noqa: SLF001
                interrupted_head.checkpoint_ref
            )
            recovered = await recovery_runner._recover_source_intake(  # noqa: SLF001
                lock,
                recovered,
            )

        assert no_replay.calls == 0
        assert recovered.checkpoint.phase == "candidate_loop"
        assert recovered.context is not None
        assert recovered.context.parents[0].package_ref == release.manifest_ref
        assert recovered.context.anchor_parent_refs == (release.manifest_ref,)
        assert recovered.checkpoint.clue_snapshot_ref is not None
        assert recovered.checkpoint.context_ref == recovered.context_ref
        assert len(recovered.checkpoint.source_result_refs) == 1
        result = artifacts.get_json(
            recovered.checkpoint.source_result_refs[0],
            ExpansionSourceResult,
        )
        assert result.status == "infrastructure_error"
        assert result.failure_code == "source_resume_unknown_active_lease"
        assert result.budget_usage.model_dump() == source_budget.model_dump()
        assert not tuple(
            ref
            for ref in store.list_revisions()
            if ref.artifact_type == "expansion.candidate_outcome"
        )

        with campaigns.exclusive(campaign_id) as lock:
            finished = recovery_runner._finish(  # noqa: SLF001
                lock,
                recovered,
                "no_admissible_operator",
            )
        terminal_head = campaigns.read_head(campaign_id)
        assert terminal_head is not None
        validated = validate_campaign_report_graph(artifacts, terminal_head)
        assert validated[2] == finished.report

        incomplete_ref = artifacts.put_json(
            artifact_id="campaign-report:incomplete-dependencies",
            artifact_type="expansion.campaign_report",
            value=finished.report,
            dependencies=(finished.report.campaign_ref,),
        )
        incomplete_head = terminal_head.model_copy(update={"report_ref": incomplete_ref})
        with pytest.raises(ValueError, match="incomplete dependency closure"):
            validate_campaign_report_graph(artifacts, incomplete_head)

        inconsistent_report = finished.report.model_copy(
            update={"stop_reason": "iteration_limit"}
        )
        inconsistent_ref = artifacts.put_json(
            artifact_id="campaign-report:inconsistent-stop",
            artifact_type="expansion.campaign_report",
            value=inconsistent_report,
            dependencies=artifacts.dependencies(finished.report_ref),
        )
        inconsistent_head = terminal_head.model_copy(update={"report_ref": inconsistent_ref})
        with pytest.raises(ValueError, match="not cross-bound"):
            validate_campaign_report_graph(artifacts, inconsistent_head)

    asyncio.run(exercise())

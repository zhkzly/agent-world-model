"""Scheduler integration contract for the first new Direct research leaf.

The in-memory backend supplies one protocol result to isolate Scheduler and
artifact wiring.  It is not a stand-in for production evidence generation:
live E2E still uses the configured real InvocationBackend plus real research
providers.  This test proves a valid plan has no hidden Designer retry path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.artifact_store import ArtifactStore
from agent_world.config import AgentBackendConfig
from agent_world.contracts import (
    Budget,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.control import (
    GenerationWorkGraph,
    LeaseBudgetLedger,
    SchedulerLeafExecutor,
    WorkAttempt,
    WorkControlRuntime,
    WorkControlStore,
    WorkScheduler,
    research_plan_work_definition,
)
from agent_world.designer import ResearchPlanLeaf
from agent_world.designer.models import ResearchPlan
from agent_world.invocation import (
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)


class _PlanBackend:
    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        return ("framework.executor.v1",)

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id="turn:research-plan",
            final_text=None,
            structured_output={
                "queries": [
                    {
                        "text": "hotel booking workflow tools state authority errors risks",
                        "rationale": (
                            "Find real workflow, API surfaces, state transitions, and risks."
                        ),
                        "topics": [
                            "workflow",
                            "tools",
                            "state",
                            "authority",
                            "errors",
                            "risks",
                        ],
                    }
                ],
                "target_coverage_dimensions": [
                    "workflow",
                    "tools",
                    "state",
                    "authority",
                    "errors",
                    "risks",
                ],
                "stop_conditions": [
                    "At least one authoritative source body for each coverage area."
                ],
            },
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=17)),
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test-protocol-boundary",
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_research_plan_leaf_commits_one_context_bound_scheduler_attempt(
    tmp_path: Path,
) -> None:
    permissions = PermissionScope()
    release = ReleaseProfile(profile_id="release:research-plan")
    budget = Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300)
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    request = EnvironmentRequest(
        request_id="request:hotel",
        need="用户预订宾馆",
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="job:hotel",
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    generation = GenerationContext(
        context_id="context:hotel",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    context_ref = artifacts.put_json(
        artifact_id=generation.context_id,
        artifact_type="control.generation_context",
        value=generation,
        dependencies=generation.root_refs,
    )
    definition = research_plan_work_definition(
        scope_id=job.job_id,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:research-plan-leaf",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(budget),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=runtime.heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    backend = _PlanBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    leaf = ResearchPlanLeaf(
        context_ref=context_ref,
        workspace_root=tmp_path / "workspaces",
        backend=backend,
        profiles=profiles,
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert len(backend.requests) == 1
    assert [item.after_state for item in results] == ["committed"]
    head = runtime.heads.read_head(definition.coordinate)
    assert head is not None and head.commit_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.input_refs == (context_ref,)
    assert attempt.observed_actual.llm_tokens == 17
    plan_ref = next(
        ref for ref in attempt.output_refs if ref.artifact_type == "design.research_plan"
    )
    plan = artifacts.get_json(plan_ref, ResearchPlan)
    assert plan.target_coverage_dimensions == (
        "workflow",
        "tools",
        "state",
        "authority",
        "errors",
        "risks",
    )

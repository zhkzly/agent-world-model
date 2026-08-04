"""P1 real-node proof: research_plan runs through GraphExecutor end to end.

The backend below is a bounded protocol-boundary test double, exactly like the
ones in ``test_scheduler_structured_one_shot.py``. It never stands in for the
production success path: it returns one real ``InvocationResult`` envelope
through the normal ``InvocationBackend`` protocol so ``invoke_structured_once``
runs unmodified and the executor/router/state machinery is exercised for real.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.artifact_store import ArtifactStore
from agent_world.config import AgentBackendConfig
from agent_world.contracts.base import ArtifactRef
from agent_world.contracts.jobs import (
    Budget,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.graph import GraphExecutor, GraphTopology, NodeRegistry, RunState
from agent_world.graph.nodes.research_plan import NODE_ID, make_research_plan_node
from agent_world.invocation.contracts import (
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)


class _StaticResearchPlanBackend:
    """Bounded protocol-boundary double; test-only, never a production path."""

    def __init__(self, output: dict) -> None:
        self.output = output
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
            turn_id="turn:research-plan-e2e",
            final_text=None,
            structured_output=self.output,
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=42)),
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test-protocol-boundary",
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


def _valid_research_plan_output() -> dict:
    return {
        "queries": [
            {
                "text": "hotel booking workflow API",
                "rationale": "cover workflow and tools",
                "topics": ["workflow", "tools", "state", "authority", "errors", "risks"],
            }
        ],
        "target_coverage_dimensions": [
            "workflow lifecycle",
            "tool api surface",
            "state transition",
            "authority permission",
            "error retry",
            "risk concurrency idempotent",
        ],
        "known_source_urls": [],
        "stop_conditions": ["enough evidence to design the booking flow"],
    }


def _build_generation_context(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="graph-e2e",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    request_ref = artifacts.put_json(
        artifact_id="request:e2e",
        artifact_type="control.environment_request",
        value=EnvironmentRequest(
            request_id="request:e2e",
            need="Book a hotel room end to end",
            release_profile=ReleaseProfile(profile_id="release:e2e"),
        ),
    )
    job_ref = artifacts.put_json(
        artifact_id="job:e2e",
        artifact_type="control.environment_job",
        value=EnvironmentJob(
            job_id="job:e2e",
            kind="generate",
            request_ref=request_ref,
            release_profile=ReleaseProfile(profile_id="release:e2e"),
        ),
        dependencies=(request_ref,),
    )
    context_ref = artifacts.put_json(
        artifact_id="context:e2e",
        artifact_type="control.generation_context",
        value=GenerationContext(
            context_id="context:e2e",
            job_ref=job_ref,
            kind="generate",
            request_ref=request_ref,
            permissions=PermissionScope(),
            budget=Budget(llm_tokens=10_000, agent_turns=5, wall_seconds=600),
            release_profile=ReleaseProfile(profile_id="release:e2e"),
        ),
        dependencies=(job_ref, request_ref),
    )
    return artifacts, context_ref


def _profiles() -> AgentProfileProvider:
    return AgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )


def test_research_plan_node_commits_through_the_real_executor(tmp_path: Path) -> None:
    artifacts, context_ref = _build_generation_context(tmp_path)
    backend = _StaticResearchPlanBackend(_valid_research_plan_output())

    node_fn = make_research_plan_node(
        backend=backend,
        profiles=_profiles(),
        artifacts=artifacts,
        workspace_root=tmp_path / "workspace",
    )
    registry = NodeRegistry()
    registry.function(NODE_ID)(node_fn)
    topology = GraphTopology.build({NODE_ID: set()})
    executor = GraphExecutor(topology, registry)

    state = RunState(
        request_id="request:e2e",
        scope_id="job:e2e",
        context_ref=context_ref,
        lease_id="lease:e2e",
    )

    outcome = asyncio.run(executor.run(state))

    assert outcome.is_released
    assert len(backend.requests) == 1
    assert backend.requests[0].execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    plan_ref = outcome.state.slice_for(NODE_ID).outputs["research_plan"]
    assert isinstance(plan_ref, ArtifactRef)
    assert plan_ref.artifact_type == "design.research_plan"


def test_research_plan_node_honest_stops_on_semantic_rejection(tmp_path: Path) -> None:
    artifacts, context_ref = _build_generation_context(tmp_path)
    # Missing coverage categories in both dimensions and query topics/text/rationale
    # -> semantic validator rejects (the corpus the validator scans is the union).
    bad_output = _valid_research_plan_output()
    bad_output["target_coverage_dimensions"] = ["irrelevant"]
    bad_output["queries"] = [
        {
            "text": "unrelated query",
            "rationale": "no coverage signal here",
            "topics": ["misc"],
        }
    ]
    backend = _StaticResearchPlanBackend(bad_output)

    node_fn = make_research_plan_node(
        backend=backend,
        profiles=_profiles(),
        artifacts=artifacts,
        workspace_root=tmp_path / "workspace",
    )
    registry = NodeRegistry()
    registry.function(NODE_ID)(node_fn)
    topology = GraphTopology.build({NODE_ID: set()})
    executor = GraphExecutor(topology, registry)

    state = RunState(
        request_id="request:e2e",
        scope_id="job:e2e",
        context_ref=context_ref,
        lease_id="lease:e2e",
    )

    outcome = asyncio.run(executor.run(state))

    assert not outcome.is_released
    stopped = outcome.state.slice_for(NODE_ID)
    assert stopped.status in ("failed", "honest_stop")
    assert stopped.failure_code == "research_plan_semantic_rejected"

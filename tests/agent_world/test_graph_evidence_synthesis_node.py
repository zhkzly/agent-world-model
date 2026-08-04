"""P1 real-node proof: evidence_synthesis runs through GraphExecutor end to end.

The backend below is the same bounded protocol-boundary test double pattern as
``test_graph_research_plan_node.py`` and ``test_scheduler_research_acquisition_leaf.py``
(never a stand-in for a production evidence claim). This test chains a stub
research_plan output straight into a real ``ResearchToolchain`` acquisition and
then into the new evidence_synthesis node, proving the three-node slice of the
research pipeline runs through one real ``GraphExecutor``.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

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
from agent_world.designer.models import PlannedSearchQuery, ResearchPlan
from agent_world.graph import GraphExecutor, GraphTopology, NodeRegistry, RunState
from agent_world.graph.node import NodeContext, NodeResult
from agent_world.graph.nodes.evidence_synthesis import NODE_ID, make_evidence_synthesis_node
from agent_world.graph.nodes.research_acquisition import (
    NODE_ID as ACQUISITION_NODE_ID,
    make_research_acquisition_node,
)
from agent_world.invocation.contracts import (
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)
from agent_world.research import ResearchToolchain
from agent_world.research.models import (
    ExtractedDocument,
    FetchedDocument,
    SearchHit,
    SearchQuery,
    SearchRecord,
)

PLAN_NODE_ID = "research_plan"


class _Search:
    name = "local-real-toolchain-search"

    def __init__(self) -> None:
        self.calls = 0

    async def search(
        self,
        query: SearchQuery,
        *,
        limit: int = 10,
        credential_handles: frozenset[str] = frozenset(),
    ) -> SearchRecord:
        del limit, credential_handles
        self.calls += 1
        return SearchRecord(
            query=query,
            provider=self.name,
            requested_at=datetime.now(UTC),
            raw_response_sha256=hashlib.sha256(query.text.encode()).hexdigest(),
            hits=(
                SearchHit(
                    url="https://hotel.example.test/booking-policy",
                    title="Booking policy",
                    snippet="Not evidence until fetched.",
                ),
            ),
        )


class _Fetch:
    name = "local-real-toolchain-fetch"

    def __init__(self) -> None:
        self.calls = 0

    async def fetch(
        self,
        url: str,
        *,
        source_policy: object | None = None,
        credential_handles: frozenset[str] = frozenset(),
    ) -> FetchedDocument:
        del source_policy, credential_handles
        self.calls += 1
        return FetchedDocument(
            requested_url=url,
            final_url=url,
            fetched_at=datetime.now(UTC),
            status_code=200,
            media_type="text/plain",
            body=("Reservation availability must be checked before confirmation. " * 8).encode(),
            fetcher=self.name,
            network_assurance="local-toolchain-contract",
        )


class _Extract:
    name = "local-real-toolchain-extract"

    def __init__(self) -> None:
        self.calls = 0

    async def extract(self, source: FetchedDocument) -> ExtractedDocument:
        self.calls += 1
        text = source.body.decode()
        return ExtractedDocument(
            source=source,
            text=text,
            title="Booking policy",
            raw_sha256=hashlib.sha256(source.body).hexdigest(),
            text_sha256=hashlib.sha256(text.encode()).hexdigest(),
            extractor=self.name,
            extractor_version="1",
        )


class _SynthesisBackend:
    """Protocol double for the graph node; never a production evidence claim."""

    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        return ("framework.executor.v1",)

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        assert "CitationCatalog:" in request.prompt
        assert "evidence_id" not in request.prompt
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id="turn:evidence-synthesis",
            final_text=None,
            structured_output={
                "claims": [
                    {
                        "claim_id": "claim:reservation-precondition",
                        "kind": "observed",
                        "statement": "Availability is checked before a reservation is confirmed.",
                        "confidence": 0.9,
                        "evidence_catalog_indexes": [1],
                        "claim_status": "supported",
                        "risk": "medium",
                    }
                ],
                "conflicts": [],
                "unresolved_questions": ["Cancellation policy remains outside this source."],
            },
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=19)),
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test-protocol-boundary",
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


def _stub_research_plan_node(plan_ref: ArtifactRef):
    async def run(_state: RunState, _ctx: NodeContext) -> NodeResult:
        return NodeResult(status="committed", outputs={"research_plan": plan_ref})

    return run


def _build_generation_context(tmp_path: Path):
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="graph-e2e",
        allowed_artifact_type_prefixes=("control.", "design.", "evidence."),
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


def _build_research_plan(artifacts, context_ref: ArtifactRef) -> ArtifactRef:
    plan = ResearchPlan(
        queries=(
            PlannedSearchQuery(
                text="hotel booking policy",
                rationale="cover cancellation and confirmation rules",
                topics=("booking",),
            ),
        ),
        target_coverage_dimensions=("booking policy",),
        stop_conditions=("enough evidence to design the booking flow",),
    )
    return artifacts.put_json(
        artifact_id="context:e2e:research-plan",
        artifact_type="design.research_plan",
        value=plan,
        dependencies=(context_ref,),
    )


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


def test_evidence_synthesis_node_commits_through_the_real_executor(tmp_path: Path) -> None:
    artifacts, context_ref = _build_generation_context(tmp_path)
    plan_ref = _build_research_plan(artifacts, context_ref)

    toolchain = ResearchToolchain(_Search(), _Fetch(), _Extract())
    synthesis_backend = _SynthesisBackend()

    registry = NodeRegistry()
    registry.function(PLAN_NODE_ID)(_stub_research_plan_node(plan_ref))
    registry.function(ACQUISITION_NODE_ID)(
        make_research_acquisition_node(research=toolchain, artifacts=artifacts)
    )
    registry.function(NODE_ID)(
        make_evidence_synthesis_node(
            backend=synthesis_backend,
            profiles=_profiles(),
            artifacts=artifacts,
            workspace_root=tmp_path / "workspace",
        )
    )
    topology = GraphTopology.build(
        {
            PLAN_NODE_ID: {ACQUISITION_NODE_ID},
            ACQUISITION_NODE_ID: {NODE_ID},
            NODE_ID: set(),
        }
    )
    executor = GraphExecutor(topology, registry)

    state = RunState(
        request_id="request:e2e",
        scope_id="job:e2e",
        context_ref=context_ref,
        lease_id="lease:e2e",
    )

    outcome = asyncio.run(executor.run(state))

    assert outcome.is_released
    assert len(synthesis_backend.requests) == 1
    assert (
        synthesis_backend.requests[0].execution_mode
        is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    )
    synthesis_slice = outcome.state.slice_for(NODE_ID)
    graph_ref = synthesis_slice.outputs["evidence_graph"]
    assert isinstance(graph_ref, ArtifactRef)
    assert graph_ref.artifact_type == "design.evidence_graph"


def test_evidence_synthesis_node_honest_stops_when_acquisition_output_missing(
    tmp_path: Path,
) -> None:
    artifacts, context_ref = _build_generation_context(tmp_path)
    synthesis_backend = _SynthesisBackend()

    registry = NodeRegistry()
    registry.function(NODE_ID)(
        make_evidence_synthesis_node(
            backend=synthesis_backend,
            profiles=_profiles(),
            artifacts=artifacts,
            workspace_root=tmp_path / "workspace",
        )
    )
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
    assert stopped.status == "honest_stop"
    assert stopped.failure_code == "evidence_synthesis_acquisition_missing"
    assert not synthesis_backend.requests

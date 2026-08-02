"""Scheduler integration for the real-tools Acquisition leaf.

The provider transports are local protocol doubles so the test can prove
control/Artifact behavior deterministically.  The leaf itself calls the real
``ResearchToolchain.run`` and materializes the same immutable evidence closure
used by the configured Searxng/Jina/Bing production adapter.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.artifact_store import ArtifactStore
from agent_world.config import AgentBackendConfig
from agent_world.contracts import (
    Budget,
    EnvironmentJob,
    EnvironmentRequest,
    EvidenceGraph,
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
    WorkGraphEpochRuntime,
    WorkScheduler,
    research_acquisition_work_definition,
    research_plan_work_definition,
    research_synthesis_work_definition,
    world_architecture_work_definition,
)
from agent_world.designer import (
    EvidenceSynthesisLeaf,
    ResearchAcquisitionLeaf,
    ResearchPlanLeaf,
    WorldArchitectureLeaf,
)
from agent_world.designer.models import ResearchAcquisition, WorldSkeletonDraft
from agent_world.invocation import (
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)
from agent_world.research import (
    ExtractedDocument,
    FetchedDocument,
    ResearchToolchain,
    SearchHit,
    SearchQuery,
    SearchRecord,
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
                        "rationale": "Find authoritative hotel booking workflow documents.",
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
                    "One admissible fetched source body is sufficient for this run."
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


class _SynthesisBackend:
    """Protocol double for Scheduler wiring; never a production evidence claim."""

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
                        "statement": (
                            "Availability is checked before a reservation is confirmed."
                        ),
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


class _ArchitectureBackend:
    """Protocol double for typed Scheduler wiring; it never substitutes for live generation."""

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
            turn_id="turn:world-architecture",
            final_text=None,
            structured_output={
                "boundary": {
                    "primary_domain": "hotel_booking",
                    "actors_and_authority": [
                        {"actor": "guest", "authorities": ["reservation.manage"]}
                    ],
                    "systems_of_record": ["reservation_system"],
                    "transition_authorities": ["reservation.manage"],
                    "tool_namespaces": ["reservation"],
                    "core_invariants": [
                        "A reservation cannot be confirmed before availability is checked."
                    ],
                    "task_dimensions": ["reservation_completion"],
                    "fidelity": [
                        {
                            "statement_id": "fidelity:reservation-policy",
                            "claim": "The local environment models reservation confirmation.",
                            "level": "bounded_approximation",
                            "known_divergence": (
                                "The retrieved source does not specify inventory allocation."
                            ),
                            "evidence_claim_ids": ["claim:reservation-precondition"],
                        }
                    ],
                },
                "state_entities": [
                    {
                        "entity": "reservation",
                        "purpose": "Own reservation lifecycle state.",
                        "root_field": "reservations",
                        "storage": "collection",
                        "system_of_record": "reservation_system",
                        "owned_resource_ids": ["reservation"],
                        "visible_to_actor_ids": ["guest"],
                        "fields": [
                            {
                                "name": "reservation_id",
                                "value_type": "string",
                                "description": "Stable reservation identifier.",
                                "string_format": "uuid",
                                "role": "primary_key",
                            },
                            {
                                "name": "status",
                                "value_type": "string",
                                "description": "Reservation lifecycle state.",
                                "enum_values": ["pending", "confirmed", "cancelled"],
                                "role": "mutable",
                                "lifecycle": True,
                            },
                        ],
                        "evidence_claim_ids": ["claim:reservation-precondition"],
                    }
                ],
                "tool_inventory": {
                    "tools": [
                        {
                            "namespace": "reservation",
                            "name": "reserve",
                            "description": "Create a reservation after availability validation.",
                            "transport": "runtime",
                            "reads_state_entities": ["reservation"],
                            "writes_state_entities": ["reservation"],
                            "evidence_claim_ids": ["claim:reservation-precondition"],
                            "interface": {
                                "input_fields": [
                                    {
                                        "name": "hotel_id",
                                        "value_type": "string",
                                        "description": "Requested hotel identifier.",
                                    }
                                ],
                                "output_fields": [
                                    {
                                        "name": "reservation_id",
                                        "value_type": "string",
                                        "description": "Created reservation identifier.",
                                    },
                                    {
                                        "name": "status",
                                        "value_type": "string",
                                        "description": "Created reservation lifecycle state.",
                                        "enum_values": ["pending", "confirmed", "cancelled"],
                                    },
                                ],
                                "observation_fields": [
                                    {
                                        "name": "status",
                                        "value_type": "string",
                                        "description": "Visible reservation lifecycle state.",
                                        "enum_values": ["pending", "confirmed", "cancelled"],
                                    }
                                ],
                            },
                        }
                    ]
                },
            },
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=23)),
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test-protocol-boundary",
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


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


@pytest.mark.asyncio
async def test_acquisition_runs_one_real_toolchain_operation_and_exposes_evidence_closure(
    tmp_path: Path,
) -> None:
    permissions = PermissionScope()
    release = ReleaseProfile(profile_id="release:research-acquisition")
    budget = Budget(llm_tokens=3_000, agent_turns=3, search_calls=1, tool_calls=3, wall_seconds=300)
    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    research_artifacts = store.issue_writer(
        producer="research-materializer",
        allowed_artifact_type_prefixes=("evidence.",),
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
    plan_definition = research_plan_work_definition(
        scope_id=job.job_id,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    acquisition_definition = research_acquisition_work_definition(
        scope_id=job.job_id,
        dependency_coordinate=plan_definition.coordinate,
        wall_seconds=60,
        maximum_search_calls=1,
        maximum_tool_calls=3,
    )
    synthesis_definition = research_synthesis_work_definition(
        scope_id=job.job_id,
        dependency_coordinate=acquisition_definition.coordinate,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    architecture_definition = world_architecture_work_definition(
        scope_id=job.job_id,
        dependency_coordinate=synthesis_definition.coordinate,
        agent_wall_seconds=60,
        agent_token_limit=1_000,
    )
    graph = GenerationWorkGraph.compile(
        (
            plan_definition,
            acquisition_definition,
            synthesis_definition,
            architecture_definition,
        ),
        mode="diagnostic",
    )
    manifest = graph.manifest(
        topology_id="topology:research-acquisition-leaf",
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
    profiles = AgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    plan_leaf = ResearchPlanLeaf(
        context_ref=context_ref,
        workspace_root=tmp_path / "workspaces",
        backend=backend,
        profiles=profiles,
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    search, fetch, extract = _Search(), _Fetch(), _Extract()
    acquisition_leaf = ResearchAcquisitionLeaf(
        context_ref=context_ref,
        research=ResearchToolchain(search, fetch, extract),
        research_artifacts=research_artifacts,
        workspace_root=tmp_path / "workspaces",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    synthesis_backend = _SynthesisBackend()
    synthesis_leaf = EvidenceSynthesisLeaf(
        context_ref=context_ref,
        workspace_root=tmp_path / "workspaces",
        backend=synthesis_backend,
        profiles=profiles,
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    architecture_backend = _ArchitectureBackend()
    architecture_leaf = WorldArchitectureLeaf(
        context_ref=context_ref,
        workspace_root=tmp_path / "workspaces",
        backend=architecture_backend,
        profiles=profiles,
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )

    async def execute_plan(context) -> None:
        await plan_leaf.execute(context, definition=plan_definition)

    async def execute_acquisition(context) -> None:
        await acquisition_leaf.execute(context, definition=acquisition_definition)

    async def execute_synthesis(context) -> None:
        await synthesis_leaf.execute(context, definition=synthesis_definition)

    async def execute_architecture(context) -> None:
        await architecture_leaf.execute(context, definition=architecture_definition)

    results = await scheduler.run_until_stalled(
        executors={
            plan_definition.work_id: execute_plan,
            acquisition_definition.work_id: execute_acquisition,
            synthesis_definition.work_id: execute_synthesis,
            architecture_definition.work_id: execute_architecture,
        }
    )

    assert [item.after_state for item in results] == [
        "committed",
        "committed",
        "committed",
        "committed",
    ]
    assert len(backend.requests) == search.calls == fetch.calls == extract.calls == 1
    head = runtime.heads.read_head(acquisition_definition.coordinate)
    assert head is not None and head.commit_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.input_refs[0] == context_ref
    assert attempt.observed_actual.search_calls == 1
    assert attempt.observed_actual.tool_calls == 3
    record_ref = next(
        ref for ref in attempt.output_refs if ref.artifact_type == "design.research_acquisition"
    )
    record = artifacts.get_json(record_ref, ResearchAcquisition)
    assert len(record.evidence) == 1
    assert record.passage_pack_ref in attempt.output_refs
    assert set(record.source_refs) <= set(attempt.output_refs)
    synthesis_head = runtime.heads.read_head(synthesis_definition.coordinate)
    assert synthesis_head is not None and synthesis_head.commit_ref is not None
    synthesis_attempt = artifacts.get_json(synthesis_head.attempt_ref, WorkAttempt)
    assert synthesis_attempt.input_refs[0] == context_ref
    assert record_ref in synthesis_attempt.input_refs
    assert record.passage_pack_ref in synthesis_attempt.input_refs
    graph_ref = next(
        ref for ref in synthesis_attempt.output_refs if ref.artifact_type == "design.evidence_graph"
    )
    evidence_graph = artifacts.get_json(graph_ref, EvidenceGraph)
    assert evidence_graph.evidence == record.evidence
    architecture_head = runtime.heads.read_head(architecture_definition.coordinate)
    assert architecture_head is not None and architecture_head.commit_ref is not None
    architecture_attempt = artifacts.get_json(architecture_head.attempt_ref, WorkAttempt)
    assert architecture_attempt.input_refs[0] == context_ref
    assert graph_ref in architecture_attempt.input_refs
    assert any(
        ref.artifact_type == "design.evidence_synthesis" for ref in architecture_attempt.input_refs
    )
    skeleton_ref = next(
        ref
        for ref in architecture_attempt.output_refs
        if ref.artifact_type == "design.world_skeleton"
    )
    skeleton = artifacts.get_json(skeleton_ref, WorldSkeletonDraft)
    assert skeleton.state.entities[0].entity == "reservation"
    assert skeleton.tool_surfaces[0].surface.tool_id == "reservation.reserve"
    assert len(architecture_backend.requests) == 1
    assert "hotel.example.test" not in architecture_backend.requests[0].prompt
    assert "Reservation availability must be checked" not in architecture_backend.requests[0].prompt

    epochs = WorkGraphEpochRuntime(artifacts=artifacts, heads=runtime.heads)
    bootstrap_manifest, _, bootstrap_epoch, _ = epochs.freeze_bootstrap(
        context_ref=context_ref,
        graph=graph,
        topology_id="topology:hotel-research-architecture",
    )
    assert bootstrap_manifest.diagnostic_only
    assert not bootstrap_manifest.releasable
    assert bootstrap_epoch.epoch_kind == "bootstrap"
    assert evidence_graph.claims[0].evidence_ids == (record.evidence[0].evidence_id,)
    assert len(synthesis_backend.requests) == 1
    assert record.evidence[0].evidence_id not in synthesis_backend.requests[0].prompt

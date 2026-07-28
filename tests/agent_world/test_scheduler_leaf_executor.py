"""Production leaf-kernel contracts, exercised through a real WorkScheduler."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ValidationError

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget, BudgetUsage, canonical_json_bytes, sha256_digest
from agent_world.control import (
    AgentExecutionProvenance,
    ArtifactSlotContract,
    GenerationWorkGraph,
    LeafExecutionFailure,
    LeafProposal,
    LeafSemanticRepairContinuation,
    LeafSessionContinuation,
    LeafValidationFailure,
    LeaseBudgetLedger,
    NodeContinuationStore,
    OperationRun,
    ProposalExecution,
    RepairAction,
    SchedulerLeafExecutor,
    ValidationIssue,
    ValidationReport,
    WorkAttempt,
    WorkControlRuntime,
    WorkControlStore,
    WorkScheduler,
    deterministic_boundary_work_definition,
    structured_agent_work_definition,
    tool_semantics_batch_definition,
)
from agent_world.control.direct_runner import DirectWorkRunner
from agent_world.control.leaf_executor import record_agent_proposal_outcome
from agent_world.invocation.contracts import InvocationSession
from agent_world.observability import CoordinateScene, ObservabilityRoot, SceneProjector


def _setup(
    tmp_path: Path,
    *,
    definition=None,
    budget: Budget | None = None,
    session_continuations: bool = False,
):
    scope_id = "job:leaf-kernel"
    if definition is None:
        definition = deterministic_boundary_work_definition(
            scope_id=scope_id,
            component="release",
            stage="observability_closure",
            artifact_slot="telemetry_release_summary",
            dependency_coordinates=(),
            claim_id="release.observability.closed",
            claim="One real leaf closes observable release evidence.",
            timing_reason="Packaging must consume an auditable committed output.",
            effect="block_release",
            success_maturity="observability_closed",
        )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design.", "release."),
    )
    root_ref = artifacts.put_json(
        artifact_id="context",
        artifact_type="control.generation_context",
        value={"context": "test"},
    )
    manifest = graph.manifest(
        topology_id="topology:leaf-kernel-test",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    continuation_workspace_root = tmp_path / "continuation-workspaces"
    if session_continuations:
        continuation_workspace_root.mkdir()
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(budget or Budget(wall_seconds=300, process_calls=4)),
        continuations=(
            NodeContinuationStore(tmp_path / "continuations") if session_continuations else None
        ),
        continuation_workspace_root=(
            continuation_workspace_root if session_continuations else None
        ),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    return artifacts, definition, heads, runtime, scheduler


def test_direct_runner_binds_tool_batch_leaf_by_artifact_slot(tmp_path: Path) -> None:
    """The semantic stage name may differ from the physical leaf contract."""

    definition = tool_semantics_batch_definition(
        job_id="job:tool-batch-leaf",
        group_id="tool-semantics-batches",
        batch_id="tool-batch-1",
        dependency_coordinates=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    context_ref = artifacts.put_json(
        artifact_id="context",
        artifact_type="control.generation_context",
        value={"context": "tool-batch-leaf"},
    )
    runner = object.__new__(DirectWorkRunner)
    runner.designer = SimpleNamespace(backend=object(), profiles=object())

    executors = runner._design_executors(  # noqa: SLF001
        context_ref=context_ref,
        workspace=tmp_path / "workspace",
        kernel=object(),
        graph=graph,
        verifier_plan=definition,
    )

    assert definition.coordinate.stage == "world_behavior"
    assert definition.coordinate.artifact_slot == "tool_semantics_batch"
    assert definition.work_id in executors


@pytest.mark.asyncio
async def test_direct_runner_runs_plan_derived_task_requirements_one_at_a_time_and_stops(
    tmp_path: Path,
) -> None:
    """A failed first task family cannot launch an unrelated sibling Agent turn.

    This exercises the Direct runner's actual scheduler path, not a mock loop:
    both physical task Requirement nodes have normal WorkAttempts and the
    first node becomes terminal before the second can spend its own budget.
    """

    def requirement(shard_id: str):
        return structured_agent_work_definition(
            scope_id="job:task-loop",
            component="design",
            stage="task_requirement",
            artifact_slot="task_requirement_source",
            group_id="task-requirements",
            shard_id=shard_id,
            dependency_coordinates=(),
            claim_id="design.task_requirement.compiles",
            claim="One independently repairable task family compiles against a frozen plan.",
            timing_reason="Each family must prove its own semantic boundary before join.",
            output_contract_id="contract:task-requirement-source.v1",
            agent_role="environment_engineer",
            allowed_mutation_roots=(),
            agent_wall_seconds=30,
            agent_token_limit=1_000,
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_total_repair_attempts=0,
            output_slots=(
                ArtifactSlotContract(
                    slot_id="output:task-requirement-source",
                    direction="output",
                    artifact_types=("design.task_requirement_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        )

    first = requirement("counter-increment")
    second = requirement("counter-inspect")
    graph = GenerationWorkGraph.compile((first, second), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    context_ref = artifacts.put_json(
        artifact_id="context:task-loop",
        artifact_type="control.generation_context",
        value={"context": "task-loop"},
    )
    manifest = graph.manifest(
        topology_id="topology:task-loop",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(llm_tokens=2_000, agent_turns=2, wall_seconds=300)),
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    dispatched: list[str] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="test-provider",
            model="test-model",
            profile_digest=sha256_digest(canonical_json_bytes({"profile": "task"})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "task"})),
        )

    async def first_execute(context) -> None:
        async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
            dispatched.append("counter-increment")
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="task_success_rule_family",
                        path=("success_conditions", 0, "family"),
                        violated_condition="success Rules use task_success",
                        expected_category="a Rule with family task_success",
                    ),
                ),
                output_commitment=sha256_digest(b"rejected-task-family"),
                category="task_requirement_semantics",
                agent=provenance(_dispatch_id),
            )

        await kernel.execute(context, definition=first, proposal_runner=proposal)

    async def second_execute(context) -> None:
        async def proposal(_context, attempt, dispatch_id) -> LeafProposal:
            dispatched.append("counter-inspect")
            output_ref = artifacts.put_json(
                artifact_id=f"task-requirement:{attempt.attempt_id}",
                artifact_type="design.task_requirement_source",
                value={"task_type": "counter-inspect"},
                dependencies=context.external_input_refs,
            )
            return LeafProposal(
                output_refs=(output_ref,),
                subject_refs=(output_ref,),
                agent=provenance(dispatch_id),
            )

        await kernel.execute(context, definition=second, proposal_runner=proposal)

    runner = object.__new__(DirectWorkRunner)
    runner.artifacts = artifacts
    runner.heads = heads
    snapshot = await runner._run_graph(  # noqa: SLF001 - Direct loop proof
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        runtime=runtime,
        executors={first.work_id: first_execute, second.work_id: second_execute},
        stop_after_first_block=True,
        preferred_order=(first.coordinate, second.coordinate),
    )

    assert dispatched == ["counter-increment"]
    assert heads.read_head(first.coordinate).status == "failed"  # type: ignore[union-attr]
    assert heads.read_head(second.coordinate) is None
    assert {item.coordinate for item in snapshot.work if item.state == "blocked"} == {
        first.coordinate,
    }


@pytest.mark.asyncio
async def test_leaf_kernel_commits_one_scheduler_authorized_code_attempt(tmp_path: Path) -> None:
    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)
    received_attempts: list[WorkAttempt] = []

    async def proposal(context, attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        received_attempts.append(attempt)
        output_ref = artifacts.put_json(
            artifact_id="telemetry-summary",
            artifact_type="release.final_telemetry_summary",
            value={"attempt_id": attempt.attempt_id, "graph": context.graph_digest},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(output_refs=(output_ref,), subject_refs=(output_ref,))

    async def execute(context) -> None:
        await leaf.execute(
            context,
            definition=definition,
            proposal_runner=proposal,
        )

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert len(received_attempts) == 1
    assert results[0].after_state == "committed"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed" and head.commit_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.ordinal == 1
    assert attempt.validation_report_ref is not None
    assert len(attempt.operation_run_refs) == 2


@pytest.mark.asyncio
async def test_leaf_kernel_terminalizes_incomplete_passing_output_closure(
    tmp_path: Path,
) -> None:
    """A framework-owned proposal closure error must not strand the WorkAttempt."""

    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def proposal(context, attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        output_ref = artifacts.put_json(
            artifact_id="incomplete-telemetry-summary",
            artifact_type="release.final_telemetry_summary",
            value={"attempt_id": attempt.attempt_id, "graph": context.graph_digest},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(context.external_input_refs[0],),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "blocked"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.active_operation_ref is None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "failed"
    assert report.issues[0].code == "framework_passing_output_closure_incomplete"
    assert report.issues[0].retryable is False


@pytest.mark.asyncio
async def test_leaf_kernel_converts_untracked_exception_to_terminal_evidence(
    tmp_path: Path,
) -> None:
    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def proposal(_context, _attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        raise RuntimeError("do not leak raw component exception into scheduler state")

    async def execute(context) -> None:
        await leaf.execute(
            context,
            definition=definition,
            proposal_runner=proposal,
        )

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "blocked"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["failure_code"] == "leaf_execution_error"


@pytest.mark.asyncio
async def test_agent_backend_error_with_no_candidate_output_still_reaches_terminal_evaluation(
    tmp_path: Path,
) -> None:
    """An unavailable model may not strand a required-output WorkAttempt running."""

    definition = structured_agent_work_definition(
        scope_id="job:leaf-kernel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_infrastructure_retries=0,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    condition = (
        "structured JSON response invalid (shape=markdown_fence; parse=syntax; offset=0; chars=73)"
    )
    expected_category = "a provider route that returns one valid structured JSON response"

    async def proposal(_context, _attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        raise LeafExecutionFailure(
            code="agent_backend_transport_failed",
            category=condition,
            expected_category=expected_category,
            terminal_details={
                "terminal_error_shape": "object",
                "codex_error_info": "enum:sessionbudgetexceeded",
            },
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai",
                model="grok-4.5",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "research"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
            ),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "blocked"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    assert head.evaluation_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.feedback_evaluation_ref == head.evaluation_ref
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert not report.subject_refs
    assert report.issues[0].path == ("operation",)
    assert report.issues[0].violated_condition == condition
    assert report.issues[0].expected_category == expected_category
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["failure_category"] == condition
    assert evidence["terminal_details"] == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:sessionbudgetexceeded",
    }


@pytest.mark.asyncio
async def test_closed_output_ceiling_creates_one_private_session_continuation_attempt(
    tmp_path: Path,
) -> None:
    """A logical session continues through two durable physical Scheduler turns.

    This is the actual ``WorkAttempt -> Proposal -> Validation -> Feedback ->
    RepairAction -> WorkAttempt`` boundary.  It does not pretend a local
    assertion proves a provider call: the follow-up real CandidateBuild proof
    still has to exercise the same path with an InvocationBackend session.
    """

    definition = structured_agent_work_definition(
        scope_id="job:session-continuation",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One logical Agent session may cross a Provider physical output ceiling.",
        timing_reason="A physical ceiling must preserve the same frozen session boundary.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/workspace",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        session_token_limit=2_000,
        session_wall_seconds=120,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_session_continuations=1,
        maximum_total_repair_attempts=0,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=0,
            wall_seconds=300,
        ),
        session_continuations=True,
    )
    workspace = tmp_path / "continuation-workspaces" / "workspace"
    workspace.mkdir()
    session = InvocationSession(
        thread_id="private-thread-output-ceiling",
        lineage_id="job:session-continuation",
        workspace=workspace.resolve(),
        profile_hash="a" * 64,
        codex_config_sha256="b" * 64,
    )
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "research-plan"}))
    session_commitment = sha256_digest(b"private-session-output-ceiling")
    kernel = SchedulerLeafExecutor(runtime=runtime)
    seen_attempts: list[int] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai",
            model="gpt-5.3-codex-spark",
            profile_digest=f"sha256:{session.profile_hash}",
            output_schema_digest=schema_digest,
            continuation_commitment=session_commitment,
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        seen_attempts.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafExecutionFailure(
                code="turn_failed_output_limit",
                category="Provider ended this physical turn at its output-token ceiling.",
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                retryable=False,
                agent=provenance(dispatch_id),
                session_continuation=LeafSessionContinuation(
                    session=session,
                    model="gpt-5.3-codex-spark",
                    output_schema_digest=schema_digest,
                ),
            )
        assert attempt.continuation_commitment is not None
        assert runtime.continuations is not None
        record = runtime.continuations.load_commitment(
            attempt.continuation_commitment,
            workspace_root=tmp_path / "continuation-workspaces",
        )
        assert record is not None
        assert record.restore_session() == session
        output_ref = artifacts.put_json(
            artifact_id="research-plan:continued",
            artifact_type="design.research_plan",
            value={"status": "completed-after-same-session-continuation"},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
            agent=provenance(dispatch_id),
        )

    async def execute(context) -> None:
        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert seen_attempts == [1, 2]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.parent_attempt_id is not None
    assert attempt.repair_attempt_charge == 0
    repair = runtime.artifacts.get_json(attempt.repair_action_ref, RepairAction)
    assert repair.decision == "session_continuation"
    assert repair.reason_code == "provider_output_ceiling"
    assert repair.repair_attempt_charge == 0
    proposal_execution = next(
        artifacts.get_json(ref, ProposalExecution)
        for ref in runtime.proposal_execution_refs(attempt)
    )
    assert proposal_execution.continuation_commitment == session_commitment
    assert "private-thread-output-ceiling" not in attempt.model_dump_json()


@pytest.mark.asyncio
async def test_cancelled_agent_before_provenance_is_terminal_unknown_evidence(
    tmp_path: Path,
) -> None:
    """A cancelled live Agent turn may not leave a running head or invent provenance."""

    definition = structured_agent_work_definition(
        scope_id="job:leaf-kernel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_infrastructure_retries=0,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def proposal(_context, _attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        raise asyncio.CancelledError

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    with pytest.raises(asyncio.CancelledError):
        await scheduler.dispatch_one(
            definition.coordinate,
            executors={definition.work_id: execute},
        )

    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert report.issues[0].code == "process_interrupted_cancelled"

    proposal_run = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    assert proposal_run.status == "terminal"
    assert proposal_run.error_code == "process_interrupted_cancelled"
    assert proposal_run.unknown_upper_bound.llm_tokens == 1_000
    assert proposal_run.unknown_upper_bound.agent_turns == 1
    assert proposal_run.execution_ref is not None
    execution = artifacts.get_json(proposal_run.execution_ref, ProposalExecution)
    assert execution.status == "interrupted"
    assert execution.invocation_id is None
    assert execution.provider is None
    assert execution.model is None
    assert execution.profile_digest is None
    assert execution.output_schema_digest is None


@pytest.mark.asyncio
async def test_typed_nonretryable_infrastructure_error_cannot_spend_a_second_envelope(
    tmp_path: Path,
) -> None:
    """BC-31: provider/configuration failures are not blind local retries."""

    definition = structured_agent_work_definition(
        scope_id="job:leaf-kernel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_infrastructure_retries=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[int] = []

    async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt.ordinal)
        raise LeafExecutionFailure(
            code="research_infrastructure_upstream_unavailable",
            category="the configured provider could not produce an admissible response",
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai",
                model="gpt-5.4-mini",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "research"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
            ),
            retryable=False,
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["blocked"]
    assert attempts == [1]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.repair_action_ref is None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert report.infrastructure_retryable is False
    assert report.issues[0].code == "research_infrastructure_upstream_unavailable"
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["retryable_infrastructure"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("replay_mode", "expected_head_status"),
    (("queryable", "repair_authorized"), ("non_replayable", "failed")),
)
async def test_interrupted_running_operation_is_charged_and_routed_by_replay_policy(
    tmp_path: Path,
    replay_mode: str,
    expected_head_status: str,
) -> None:
    """BC-26: an orphaned real dispatch cannot become a fresh free retry."""

    definition = structured_agent_work_definition(
        scope_id="job:leaf-kernel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        replay_mode=replay_mode,  # type: ignore[arg-type]
        maximum_infrastructure_retries=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, _scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
    )
    root_ref = next(
        ref
        for ref in artifacts.list_revisions("context")
        if ref.artifact_type == "control.generation_context"
    )

    with heads.exclusive(definition.coordinate) as lock:
        runtime.begin(
            lock,
            definition=definition,
            input_refs=(root_ref,),
            elapsed_wall_seconds=0,
        )
        runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode=definition.proposal_policy.replay_mode,
            elapsed_wall_seconds=0,
        )
        runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id="dispatch:orphaned-real-agent-turn",
        )
        recovered = runtime.reconcile_abandoned_operation(lock, definition=definition)

    assert recovered.status == expected_head_status
    attempt = artifacts.get_json(recovered.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    proposal_run = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    assert proposal_run.status == "terminal"
    assert proposal_run.replay_mode == replay_mode
    assert proposal_run.unknown_upper_bound.llm_tokens == 1_000
    assert proposal_run.unknown_upper_bound.agent_turns == 1
    direct_usage = DirectWorkRunner._scope_budget_usage(  # noqa: SLF001
        runtime=runtime,
        scope_id=definition.coordinate.scope_id,
    )
    assert direct_usage["observed_actual"] == BudgetUsage()
    assert direct_usage["unknown_upper_bound"].llm_tokens == 1_000
    assert direct_usage["unknown_upper_bound"].agent_turns == 1
    if replay_mode == "queryable":
        assert recovered.repair_action_ref is not None
    else:
        assert recovered.repair_action_ref is None


@pytest.mark.asyncio
async def test_scheduler_closes_an_unaffordable_authorized_repair_without_a_second_execution(
    tmp_path: Path,
) -> None:
    """A budget-rejected retry is terminal evidence, never a zombie WorkAttempt."""

    definition = structured_agent_work_definition(
        scope_id="job:leaf-kernel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_infrastructure_retries=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        # The first real attempt consumes the only 1,000-token envelope.  The
        # Scheduler may authorize the repair, but admission must reject it
        # before a second proposal operation begins.
        budget=Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=300),
    )
    observability_root = ObservabilityRoot(tmp_path / "observability")
    runtime.projector = SceneProjector(
        root=observability_root,
        artifacts=artifacts,
        heads=heads,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    proposals: list[int] = []

    async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        proposals.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafExecutionFailure(
                code="agent_backend_transport_failed",
                category="the isolated Agent backend returned a terminal transport failure",
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                unknown_upper_bound=BudgetUsage(),
                agent=AgentExecutionProvenance(
                    invocation_id=dispatch_id,
                    provider="openai",
                    model="grok-4.5",
                    profile_digest=sha256_digest(canonical_json_bytes({"profile": "research"})),
                    output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
                ),
            )
        raise AssertionError("the unaffordable repair must not call the proposal")

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [item.after_state for item in results] == ["repair_ready", "blocked"]
    assert proposals == [1]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.evaluation_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.status == "budget_exhausted"
    assert attempt.feedback_evaluation_ref == head.evaluation_ref
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["failure_code"] == "budget_exhausted"
    assert evidence["exhausted_dimensions"] == ["llm_tokens"]
    assert runtime.repairs.entries[0].outcome == "exhausted"
    scene_scope_id = runtime.projector.safe_scope_id(definition.coordinate.scope_id)
    coordinate = CoordinateScene.model_validate_json(
        observability_root.coordinate_json_path(
            scene_scope_id,
            definition.coordinate.coordinate_key,
        ).read_bytes()
    )
    assert coordinate.budget_exhaustion is not None
    assert coordinate.budget_exhaustion.exhausted_dimensions == ("llm_tokens",)
    assert coordinate.budget_exhaustion.during_authorized_repair is True
    assert coordinate.budget_exhaustion.operation_not_started is True
    expected_budget_line = (
        "Budget exhaustion: llm_tokens; before a Scheduler-authorized repair; "
        "no operation ran in this attempt."
    )
    assert expected_budget_line in (
        observability_root.coordinate_markdown_path(
            scene_scope_id,
            definition.coordinate.coordinate_key,
        ).read_text()
    )


@pytest.mark.asyncio
async def test_leaf_kernel_turns_safe_validation_failure_into_actionable_report(
    tmp_path: Path,
) -> None:
    """Semantic rejection is not downgraded to an opaque leaf execution error."""

    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def proposal(_context, _attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        raise LeafValidationFailure(
            issues=(
                ValidationIssue(
                    code="candidate_public_contract_missing",
                    path=("candidate", "public_check"),
                    violated_condition="Candidate must declare a public self-check entrypoint.",
                    expected_category="declared public check command",
                ),
            ),
            output_commitment=sha256_digest(b"rejected-proposal-without-persisted-source"),
            category="deterministic_candidate_contract",
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "blocked"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "failed"
    assert report.diagnostic_quality == "actionable"
    assert report.issues[0].code == "candidate_public_contract_missing"
    evidence = artifacts.get_json(report.evidence_refs[-1])
    assert evidence["failure_category"] == "deterministic_candidate_contract"


@pytest.mark.asyncio
async def test_scheduler_compiles_authorized_failure_into_agent_correction_brief(
    tmp_path: Path,
) -> None:
    """The second physical Agent turn receives the first turn's exact findings.

    This regression covers the former false ``repair_no_progress`` path: a
    local correction was authorized, but a stateless Agent was sent the same
    prompt twice and could not know which deterministic conditions to change.
    """

    definition = structured_agent_work_definition(
        scope_id="job:agent-correction-brief",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        maximum_infrastructure_retries=0,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    received = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model="grok-4.5",
            profile_digest=sha256_digest(canonical_json_bytes({"profile": "research"})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        received.append(leaf.agent_correction_brief(context, definition=definition))
        if attempt.ordinal == 1:
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="shared_contract_partition",
                        path=("concurrency_domains",),
                        violated_condition="shared domains omit or duplicate a frozen group tool",
                        expected_category=(
                            "one exact partition of frozen tool IDs: hotel.search, hotel.reserve"
                        ),
                    ),
                ),
                output_commitment=sha256_digest(b"rejected-first-agent-proposal"),
                category="deterministic_shared_contract",
                agent=provenance(dispatch_id),
            )
        output_ref = artifacts.put_json(
            artifact_id="research-plan-after-correction",
            artifact_type="design.research_plan",
            value={"attempt": attempt.ordinal},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert received[0] is None
    brief = received[1]
    assert brief is not None
    assert not hasattr(brief, "repair_action_ref")
    assert brief.issues[0].code == "shared_contract_partition"
    assert brief.issues[0].path == ("concurrency_domains",)
    assert brief.issues[0].expected_category == (
        "one exact partition of frozen tool IDs: hotel.search, hotel.reserve"
    )
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"
    assert runtime.repairs.entries[0].outcome == "resolved"


@pytest.mark.asyncio
async def test_scheduler_binds_semantic_repair_session_after_real_feedback_authorization(
    tmp_path: Path,
) -> None:
    """A successful first Agent turn can repair its own workspace exactly once.

    This is the normal ``proposal -> validation -> feedback -> repair``
    Scheduler path.  It proves that private same-session state is not saved
    before authority exists, and that the successor sees the exact safe brief
    rather than a second copy of the original prompt.
    """

    definition = structured_agent_work_definition(
        scope_id="job:semantic-repair-session",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="A repair must retain the exact successful Agent workspace.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        maximum_infrastructure_retries=0,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
        session_continuations=True,
    )
    assert runtime.continuation_workspace_root is not None
    workspace = (
        runtime.continuation_workspace_root
        / "research"
        / "attempt-initial"
        / ".agent-runtime"
        / "workspace"
    )
    workspace.mkdir(parents=True)
    session = InvocationSession(
        thread_id="private-semantic-repair-thread",
        lineage_id="research:semantic-repair-session",
        workspace=workspace.resolve(),
        profile_hash="a" * 64,
        codex_config_sha256="b" * 64,
    )
    output_schema_digest = sha256_digest(canonical_json_bytes({"schema": "research-plan"}))
    leaf = SchedulerLeafExecutor(runtime=runtime)
    received = []
    successor_continuations = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model="gpt-5.4-mini",
            profile_digest=f"sha256:{session.profile_hash}",
            output_schema_digest=output_schema_digest,
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        received.append(leaf.agent_correction_brief(context, definition=definition))
        if attempt.ordinal == 1:
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="candidate_manifest_undeclared_files",
                        path=("candidate", "files"),
                        violated_condition=(
                            "the final candidate/ tree contains 2 regular paths absent from "
                            "CandidateCompletion.files"
                        ),
                        expected_category=(
                            "a one-for-one declaration of every final regular candidate file"
                        ),
                        remediation=(
                            "Inspect the final candidate inventory and reconcile its complete "
                            "declaration."
                        ),
                    ),
                ),
                output_commitment=sha256_digest(b"rejected-first-semantic-proposal"),
                category="manifest_closure",
                agent=provenance(dispatch_id),
                semantic_repair_continuation=LeafSemanticRepairContinuation(
                    session=session,
                    model="gpt-5.4-mini",
                    output_schema_digest=output_schema_digest,
                ),
            )
        assert attempt.continuation_commitment is not None
        successor_continuations.append(attempt.continuation_commitment)
        output_ref = artifacts.put_json(
            artifact_id="research-plan-after-semantic-repair",
            artifact_type="design.research_plan",
            value={"attempt": attempt.ordinal},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert received[0] is None
    brief = received[1]
    assert brief is not None
    assert brief.issues[0].code == "candidate_manifest_undeclared_files"
    assert brief.issues[0].path == ("candidate", "files")
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed" and head.attempt_ref is not None
    successor = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert successor.parent_attempt_id is not None
    assert successor.continuation_commitment is None  # private state is cleared after success
    assert len(successor_continuations) == 1
    assert runtime.continuations is not None
    record = runtime.continuations.load_commitment(
        successor_continuations[0],
        workspace_root=runtime.continuation_workspace_root,
    )
    assert record is not None
    assert record.attempt_id == successor.parent_attempt_id
    assert record.workspace == str(workspace.resolve())
    assert record.model == "gpt-5.4-mini"
    assert runtime.repairs.entries[0].outcome == "resolved"


@pytest.mark.asyncio
async def test_postproposal_framework_error_settles_the_real_agent_turn(
    tmp_path: Path,
) -> None:
    """BC-32: output materialization cannot orphan a completed Agent dispatch."""

    definition = structured_agent_work_definition(
        scope_id="job:agent-postproposal-error",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_infrastructure_retries=0,
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def proposal(_context, _attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        record_agent_proposal_outcome(
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai-compatible",
                model="grok-4.5",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "research"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
            ),
            observed_actual=BudgetUsage(llm_tokens=23, agent_turns=1),
            unknown_upper_bound=BudgetUsage(),
        )
        raise RuntimeError("simulated immutable Artifact DAG write failure")

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["blocked"]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.attempt_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.status == "failed"
    assert attempt.observed_actual.llm_tokens == 23
    assert attempt.observed_actual.agent_turns == 1
    assert attempt.unknown_upper_bound.llm_tokens == 0
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert report.issues[0].code == "agent_postproposal_framework_error"
    assert report.infrastructure_retryable is False
    assert all(
        artifacts.get_json(ref)["status"] == "terminal" for ref in attempt.operation_run_refs
    )


@pytest.mark.asyncio
async def test_leaf_kernel_translates_code_leaf_pydantic_errors_to_safe_field_diagnostics(
    tmp_path: Path,
) -> None:
    """A framework schema fault is not flattened into a generic leaf error."""

    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)

    class ClosedOutput(BaseModel):
        count: int

    async def proposal(_context, _attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        try:
            ClosedOutput.model_validate({"count": "not-an-integer"})
        except ValidationError:
            raise
        raise AssertionError("the invalid framework value must not be accepted")

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "blocked"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.attempt_ref is not None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "failed"
    assert report.diagnostic_quality == "actionable"
    assert report.issues[0].path == ("count",)
    assert report.issues[0].code == "schema_int_parsing"


@pytest.mark.asyncio
async def test_leaf_kernel_binds_real_agent_dispatch_provenance(tmp_path: Path) -> None:
    artifacts, _definition, _heads, runtime, _scheduler = _setup(tmp_path)
    scope_id = "job:agent-leaf"
    definition = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture_source",
        dependency_coordinates=(),
        claim_id="design.architecture.compiles",
        claim="One structured Agent proposal compiles to an Architecture source.",
        timing_reason="The graph may freeze only after grounded Architecture.",
        output_contract_id="contract:architecture-source",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    context_ref = artifacts.put_json(
        artifact_id="agent-context",
        artifact_type="control.generation_context",
        value={"context": "agent"},
    )
    manifest = graph.manifest(
        topology_id="topology:agent-leaf-test",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "agent-work-control")
    agent_runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300)),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=agent_runtime,
    )
    leaf = SchedulerLeafExecutor(runtime=agent_runtime)

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        output_ref = artifacts.put_json(
            artifact_id="architecture-source",
            artifact_type="design.world_architecture_source",
            value={"attempt": attempt.attempt_id},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai-compatible",
                model="grok-4.5",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "engineer"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "source"})),
            ),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert results[0].after_state == "committed"


@pytest.mark.asyncio
async def test_scheduler_routes_one_validated_downstream_failure_to_its_causal_owner(
    tmp_path: Path,
) -> None:
    """A downstream code check repairs Build once, then only its suffix reruns.

    This is the regression for the previous "repair target only exists in the
    graph" bug.  The failing Integration leaf cannot retry itself or mutate a
    candidate.  It emits one safe route; Scheduler validates the declared edge,
    authorizes the target's own Agent repair budget, and stale input fingerprints
    re-open Integration after the new Candidate WorkCommit exists.
    """

    artifacts, _definition, heads, _runtime, _scheduler = _setup(tmp_path)
    scope_id = "job:causal-route"
    target = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture_source",
        dependency_coordinates=(),
        claim_id="design.architecture.compiles",
        claim="One Agent-owned source artifact is the minimal mutable repair target.",
        timing_reason="The downstream runtime check must not edit source itself.",
        output_contract_id="contract:architecture-source",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/source",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
    )
    source_base = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependency_coordinates=(target.coordinate,),
        claim_id="integration.runtime.executable",
        claim="The current candidate must pass an isolated runtime check.",
        timing_reason="A real downstream check gives the first causal execution evidence.",
        effect="block_release",
        success_maturity="integration_passed",
    )
    source = source_base.model_copy(
        update={
            "repair_target_coordinates": (target.coordinate,),
            "repair_policy": source_base.repair_policy.model_copy(
                update={
                    "maximum_automatic_backjump": 1,
                    "maximum_total_repair_attempts": 1,
                }
            ),
            "allowed_mutation_roots": ("/source",),
        }
    )
    graph = GenerationWorkGraph.compile((target, source), mode="diagnostic")
    root_ref = artifacts.put_json(
        artifact_id="causal-context",
        artifact_type="control.generation_context",
        value={"context": "causal-route"},
    )
    manifest = graph.manifest(
        topology_id="topology:causal-route",
        external_root_refs=(root_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(root_ref,),
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(llm_tokens=3_000, agent_turns=3, repair_attempts=1, wall_seconds=300)
        ),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    target_turns: list[int] = []
    source_turns: list[int] = []

    async def target_proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        target_turns.append(attempt.ordinal)
        output_ref = artifacts.put_json(
            artifact_id=f"candidate-source:{attempt.ordinal}",
            artifact_type="design.world_architecture_source",
            value={"revision": attempt.ordinal},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai-compatible",
                model="grok-4.5",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "engineer"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "source"})),
            ),
        )

    async def source_proposal(context, attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        source_turns.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="runtime_protocol_rejects_candidate",
                        path=("runtime", "handshake"),
                        violated_condition="The isolated runtime protocol rejected this candidate.",
                        expected_category="candidate source satisfying the runtime protocol",
                    ),
                ),
                output_commitment=sha256_digest(b"failed-real-integration-evidence"),
                category="isolated_runtime_protocol",
                parent_repair_target=target.coordinate,
            )
        output_ref = artifacts.put_json(
            artifact_id="integration-after-causal-repair",
            artifact_type="release.final_telemetry_summary",
            value={"candidate_parent_commit": context.parent_commit_refs[0].revision_id},
            dependencies=context.parent_output_refs,
        )
        return LeafProposal(output_refs=(output_ref,), subject_refs=(output_ref,))

    async def execute_target(context) -> None:
        await kernel.execute(context, definition=target, proposal_runner=target_proposal)

    async def execute_source(context) -> None:
        await kernel.execute(context, definition=source, proposal_runner=source_proposal)

    results = await scheduler.run_until_stalled(
        executors={target.work_id: execute_target, source.work_id: execute_source},
        maximum_concurrency=1,
    )

    assert target_turns == [1, 2]
    assert source_turns == [1, 2]
    assert [item.before_state for item in results] == [
        "ready",
        "ready",
        "repair_ready",
        "stale",
    ]
    assert [item.after_state for item in results] == [
        "committed",
        "blocked",
        "committed",
        "committed",
    ]
    target_head = heads.read_head(target.coordinate)
    source_head = heads.read_head(source.coordinate)
    assert target_head is not None and target_head.status == "committed"
    assert source_head is not None and source_head.status == "committed"
    assert target_head.repair_action_ref is not None
    action = artifacts.get_json(target_head.repair_action_ref, RepairAction)
    assert action.reason_code == "causal_downstream_failure"
    assert any(
        ref.artifact_type == "control.parent_repair_route" for ref in action.causal_evidence_refs
    )
    assert runtime.repairs.entries[0].outcome == "resolved"

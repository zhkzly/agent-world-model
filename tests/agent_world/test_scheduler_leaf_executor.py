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
    LeafValidationFailure,
    LeaseBudgetLedger,
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


def _setup(tmp_path: Path, *, definition=None, budget: Budget | None = None):
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
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(budget or Budget(wall_seconds=300, process_calls=4)),
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

    async def proposal(_context, _attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        raise LeafExecutionFailure(
            code="agent_backend_transport_failed",
            category="the isolated Agent backend returned a terminal transport failure",
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
        # The first real attempt may spend this lease.  No additional Agent or
        # repair capacity exists for the policy-authorized infrastructure retry.
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    proposals: list[int] = []

    async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        proposals.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafExecutionFailure(
                code="agent_backend_transport_failed",
                category="the isolated Agent backend returned a terminal transport failure",
                agent=AgentExecutionProvenance(
                    invocation_id=dispatch_id,
                    provider="openai",
                    model="grok-4.5",
                    profile_digest=sha256_digest(
                        canonical_json_bytes({"profile": "research"})
                    ),
                    output_schema_digest=sha256_digest(
                        canonical_json_bytes({"schema": "plan"})
                    ),
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
    assert evidence["exhausted_dimensions"] == ["repair_attempts"]
    assert runtime.repairs.entries[0].outcome == "exhausted"


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
                profile_digest=sha256_digest(
                    canonical_json_bytes({"profile": "research"})
                ),
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
        ref.artifact_type == "control.parent_repair_route"
        for ref in action.causal_evidence_refs
    )
    assert runtime.repairs.entries[0].outcome == "resolved"

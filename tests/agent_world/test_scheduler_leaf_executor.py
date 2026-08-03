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
    BudgetExceeded,
    ContinuationStoreError,
    GenerationWorkGraph,
    LeafExecutionFailure,
    LeafProposal,
    LeafSemanticRepairContinuation,
    LeafSemanticRepairSeed,
    LeafSessionContinuation,
    LeafValidationFailure,
    LeafWorkspaceRecovery,
    LeaseBudgetLedger,
    NodeContinuationStore,
    OperationBudget,
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
from agent_world.invocation import (
    InvocationControlRouteLivenessChecker,
    InvocationControlStore,
    InvocationStatus,
    InvocationTerminalFact,
)
from agent_world.invocation.contracts import InvocationSession
from agent_world.observability import CoordinateScene, ObservabilityRoot, SceneProjector


def _setup(
    tmp_path: Path,
    *,
    definition=None,
    budget: Budget | None = None,
    session_continuations: bool = False,
    model_routes: tuple[str, ...] = (),
    route_liveness_checker=None,
    require_route_liveness_gate: bool = False,
    infrastructure_retry_backoff_seconds: float = 0.0,
    diagnostic_only: bool = False,
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
    if diagnostic_only:
        heads.mark_test_node_diagnostic_clone()
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
        model_routes=model_routes,
        route_liveness_checker=route_liveness_checker,
        require_route_liveness_gate=require_route_liveness_gate,
        infrastructure_retry_backoff_seconds=infrastructure_retry_backoff_seconds,
        diagnostic_only=diagnostic_only,
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


@pytest.mark.asyncio
async def test_diagnostic_parsed_candidate_binds_after_explicit_semantic_repair_authorization(
    tmp_path: Path,
) -> None:
    """A test-node repair keeps parsed JSON privately until explicit authorization.

    The first pass is a true Scheduler proposal/validation/evaluation boundary
    in diagnostic mode.  It must settle failed before authorization, retain no
    public candidate Artifact, and then promote the exact private candidate to
    the ordinary repair seed only after the explicit RepairAction exists.
    """

    definition = structured_agent_work_definition(
        scope_id="job:diagnostic-semantic-seed",
        component="design",
        stage="diagnostic_semantic_seed",
        artifact_slot="diagnostic_semantic_seed",
        dependency_coordinates=(),
        claim_id="design.diagnostic_seed.repairs",
        claim="One parsed diagnostic candidate can receive a feedback-bound repair.",
        timing_reason="A real semantic rejection needs its exact parsed baseline.",
        output_contract_id="contract:diagnostic-semantic-seed.v1",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_total_repair_attempts=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:diagnostic-semantic-seed",
                direction="output",
                artifact_types=("design.diagnostic_semantic_seed",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
    )
    artifacts, definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=2_000, agent_turns=2, repair_attempts=1, wall_seconds=300),
        diagnostic_only=True,
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    candidate = {"cases": [{"expectations": [{"expected": True}]}]}
    received_seeds: list[LeafSemanticRepairSeed | None] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="test-provider",
            model="test-direct-model",
            profile_digest=sha256_digest(canonical_json_bytes({"profile": "diagnostic"})),
            output_schema_digest=sha256_digest(
                canonical_json_bytes({"schema": "diagnostic-semantic-seed"})
            ),
        )

    async def rejected(context) -> None:
        async def proposal(_context, _attempt, dispatch_id: str) -> LeafProposal:
            agent = provenance(dispatch_id)
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="semantic_negative_expectation_missing",
                        path=("cases", 0, "expectations"),
                        violated_condition="the parsed candidate omits the negative expectation",
                        expected_category="a separate compatible expectation with expected=false",
                        remediation="Preserve valid expectations and add the missing negative one.",
                    ),
                ),
                output_commitment=sha256_digest(
                    canonical_json_bytes(
                        {
                            "invocation_id": dispatch_id,
                            "structured_output": candidate,
                        }
                    )
                ),
                category="semantic_coverage",
                agent=agent,
                semantic_repair_seed=LeafSemanticRepairSeed(
                    model=agent.model,
                    profile_digest=agent.profile_digest,
                    output_schema_digest=agent.output_schema_digest,
                    previous_candidate=candidate,
                ),
            )

        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    first = await scheduler.run_until_stalled(executors={definition.work_id: rejected})
    # The graph reports its terminal dependency state as blocked; the exact
    # diagnostic Work head below remains the failed node that can be explicitly
    # authorized for one repair.
    assert [result.after_state for result in first] == ["blocked"]
    failed_head = heads.read_head(definition.coordinate)
    assert failed_head is not None and failed_head.status == "failed"
    failed_attempt = artifacts.get_json(failed_head.attempt_ref, WorkAttempt)
    assert failed_attempt.semantic_repair_seed_commitment is None

    with heads.exclusive(definition.coordinate) as lock:
        authorized_head = runtime.authorize_diagnostic_semantic_repair(
            lock,
            definition=definition,
            input_refs=failed_attempt.input_refs,
        )

    assert authorized_head.status == "repair_authorized"
    authorized_attempt = artifacts.get_json(authorized_head.attempt_ref, WorkAttempt)
    assert authorized_attempt.semantic_repair_seed_commitment is not None
    stored = runtime.semantic_repair_seeds.load_commitment(
        authorized_attempt.semantic_repair_seed_commitment
    )
    assert stored is not None
    assert stored.previous_candidate == candidate
    assert stored.repair_action_ref == authorized_head.repair_action_ref

    async def repaired(context) -> None:
        async def proposal(current_context, attempt, dispatch_id: str) -> LeafProposal:
            seed = kernel.agent_semantic_repair_seed(
                current_context,
                definition=definition,
                attempt=attempt,
            )
            received_seeds.append(seed)
            assert seed is not None and seed.previous_candidate == candidate
            output_ref = artifacts.put_json(
                artifact_id="diagnostic-semantic-seed:repaired",
                artifact_type="design.diagnostic_semantic_seed",
                value={"repaired": True},
                dependencies=current_context.external_input_refs,
            )
            return LeafProposal(
                output_refs=(output_ref,),
                subject_refs=(output_ref,),
                agent=provenance(dispatch_id),
            )

        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    # This test proves one isolated diagnostic node, whose non-releasable
    # commit is intentionally not a converged release graph.  Dispatch the
    # explicitly authorized repair once instead of asking the diagnostic
    # scheduler to re-schedule its deliberately non-active terminal commit.
    repaired_result = await scheduler.dispatch_one(
        definition.coordinate,
        executors={definition.work_id: repaired},
    )
    assert repaired_result.after_state == "committed"
    assert len(received_seeds) == 1


@pytest.mark.asyncio
async def test_diagnostic_agent_session_binds_after_explicit_semantic_repair_authorization(
    tmp_path: Path,
) -> None:
    """A completed Agent turn remains privately repairable after later auth.

    This is the Code-Agent counterpart to the parsed Direct seed test above.
    It proves that a diagnostic semantic failure can settle first, then bind
    its real workspace/thread only after one exact RepairAction exists.  The
    session never enters an Artifact or the public WorkAttempt payload.
    """

    model = "grok-4.5"
    definition = structured_agent_work_definition(
        scope_id="job:diagnostic-semantic-continuation",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="builder.candidate.metadata.repairs",
        claim="A complete Candidate declaration may receive one local correction.",
        timing_reason="A field-addressable completion mismatch is repairable.",
        output_contract_id="contract:candidate-completion.v1",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_total_repair_attempts=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:environment-candidate",
                direction="output",
                artifact_types=("design.candidate_build",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    artifacts, definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=2_000, agent_turns=2, repair_attempts=1, wall_seconds=300),
        session_continuations=True,
        model_routes=(model,),
        diagnostic_only=True,
    )
    assert runtime.continuation_workspace_root is not None
    workspace = runtime.continuation_workspace_root / "candidate-repair"
    (workspace / "candidate").mkdir(parents=True)
    profile_digest = sha256_digest(canonical_json_bytes({"profile": "engineer"}))
    config_digest = sha256_digest(canonical_json_bytes({"config": "engineer"}))
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "candidate-completion"}))
    session = InvocationSession(
        thread_id="private-candidate-repair-thread",
        lineage_id="implementation:diagnostic-semantic-continuation",
        workspace=workspace,
        profile_hash=profile_digest.removeprefix("sha256:"),
        codex_config_sha256=config_digest.removeprefix("sha256:"),
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="test-provider",
            model=model,
            profile_digest=profile_digest,
            output_schema_digest=schema_digest,
        )

    async def execute(context) -> None:
        async def proposal(_context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
            agent = provenance(dispatch_id)
            if attempt.ordinal == 1:
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="task_materializer_binding_mismatch",
                            path=("task_materializer",),
                            violated_condition=(
                                "entrypoint must equal the module derived from entry_path"
                            ),
                            expected_category="a matching module:materialize declaration",
                            remediation="Use the module derived from the candidate-relative path.",
                        ),
                    ),
                    output_commitment=sha256_digest(
                        canonical_json_bytes(
                            {"invocation_id": dispatch_id, "completion": "rejected"}
                        )
                    ),
                    category="candidate_metadata",
                    agent=agent,
                    semantic_repair_continuation=LeafSemanticRepairContinuation(
                        session=session,
                        model=model,
                        output_schema_digest=schema_digest,
                    ),
                )
            assert attempt.ordinal == 2
            assert attempt.continuation_commitment is not None
            assert runtime.continuations is not None
            record = runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=runtime.continuation_workspace_root,
            )
            assert record is not None
            assert record.restore_session() == session
            output = artifacts.put_json(
                artifact_id="diagnostic-semantic-continuation:repaired",
                artifact_type="design.candidate_build",
                value={"repaired": True},
                dependencies=context.external_input_refs,
            )
            return LeafProposal(
                output_refs=(output,),
                subject_refs=(output,),
                agent=agent,
            )

        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    first = await scheduler.run_until_stalled(executors={definition.work_id: execute})
    assert [result.after_state for result in first] == ["blocked"]
    failed = heads.read_head(definition.coordinate)
    assert failed is not None and failed.status == "failed"
    failed_attempt = artifacts.get_json(failed.attempt_ref, WorkAttempt)
    assert failed_attempt.continuation_commitment is None
    assert list(runtime.diagnostic_semantic_repair_continuations.root.glob("*.json"))

    with heads.exclusive(definition.coordinate) as lock:
        authorized = runtime.authorize_diagnostic_semantic_repair(
            lock,
            definition=definition,
            input_refs=failed_attempt.input_refs,
        )

    assert authorized.status == "repair_authorized"
    authorized_attempt = artifacts.get_json(authorized.attempt_ref, WorkAttempt)
    assert authorized_attempt.continuation_commitment is not None
    assert "private-candidate-repair-thread" not in authorized_attempt.model_dump_json()

    repaired = await scheduler.dispatch_one(
        definition.coordinate,
        executors={definition.work_id: execute},
    )
    assert repaired.after_state == "committed"


@pytest.mark.asyncio
async def test_diagnostic_candidate_draft_binds_only_after_explicit_infrastructure_retry(
    tmp_path: Path,
) -> None:
    """A diagnostic CandidateBuild keeps a private draft across one fresh session.

    This exercises the actual Scheduler proposal -> validation -> evaluation ->
    explicit RepairAction transition.  The first Agent turn writes an
    untrusted draft and reaches a closed transient terminal; no draft becomes
    an Artifact.  Only the later authorized retry receives an action-bound
    private record, and it must use a fresh Provider session.
    """

    model = "gpt-5.3-codex-spark"
    definition = structured_agent_work_definition(
        scope_id="job:diagnostic-candidate-workspace",
        component="build",
        stage="candidate_build",
        artifact_slot="candidate_build",
        dependency_coordinates=(),
        claim_id="builder.candidate.completes",
        claim="A fresh Builder session may inspect one untrusted private draft.",
        timing_reason="A closed Provider capacity terminal cannot adopt a draft.",
        output_contract_id="contract:candidate-build.v1",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=0,
        maximum_total_repair_attempts=2,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:candidate-build",
                direction="output",
                artifact_types=("design.candidate_build",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    artifacts, definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=2_000, agent_turns=2, repair_attempts=1, wall_seconds=300),
        session_continuations=True,
        model_routes=(model,),
        diagnostic_only=True,
    )
    assert runtime.continuation_workspace_root is not None
    workspace = runtime.continuation_workspace_root / "candidate-attempt"
    (workspace / "candidate").mkdir(parents=True)
    draft = workspace / "candidate" / "runtime.py"
    draft.write_text("def draft(): return 'untrusted'\n", encoding="utf-8")
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "candidate-completion"}))
    profile_digest = sha256_digest(canonical_json_bytes({"profile": "engineer"}))
    config_digest = sha256_digest(canonical_json_bytes({"config": "engineer"}))
    kernel = SchedulerLeafExecutor(runtime=runtime)
    seen_sessions: list[str | None] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="test-provider",
            model=model,
            profile_digest=profile_digest,
            output_schema_digest=schema_digest,
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        if attempt.ordinal == 1:
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the Provider closed after regular private Candidate files were written",
                retryable=True,
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
                workspace_recovery=LeafWorkspaceRecovery(
                    workspace=workspace,
                    lineage_id="implementation:diagnostic-candidate",
                    profile_digest=profile_digest,
                    codex_config_digest=config_digest,
                    model=model,
                    output_schema_digest=schema_digest,
                ),
            )
        assert attempt.ordinal == 2
        assert attempt.continuation_commitment is not None
        assert runtime.continuations is not None
        record = runtime.continuations.load_commitment(
            attempt.continuation_commitment,
            workspace_root=runtime.continuation_workspace_root,
        )
        assert record is not None
        assert record.continuation_kind == "workspace_recovery"
        assert record.thread_id is None
        assert record.workspace_for_recovery() == workspace.resolve()
        with pytest.raises(ContinuationStoreError, match="cannot resume a Provider thread"):
            record.restore_session()
        assert draft.read_text(encoding="utf-8").startswith("def draft")
        seen_sessions.append(record.thread_id)
        output = artifacts.put_json(
            artifact_id="diagnostic-candidate:completed",
            artifact_type="design.candidate_build",
            value={"completed_after_fresh_workspace_inspection": True},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output,),
            subject_refs=(output,),
            observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
            agent=provenance(dispatch_id),
        )

    async def execute(context) -> None:
        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    first = await scheduler.run_until_stalled(executors={definition.work_id: execute})
    assert [result.after_state for result in first] == ["blocked"]
    failed = heads.read_head(definition.coordinate)
    assert failed is not None and failed.status == "failed"
    failed_attempt = artifacts.get_json(failed.attempt_ref, WorkAttempt)
    assert failed_attempt.continuation_commitment is None
    assert not any("candidate-attempt" in ref.artifact_id for ref in artifacts.list_revisions())

    with heads.exclusive(definition.coordinate) as lock:
        authorized = runtime.authorize_diagnostic_infrastructure_retry(
            lock,
            definition=definition,
            input_refs=failed_attempt.input_refs,
        )

    assert authorized.status == "repair_authorized"
    action = artifacts.get_json(authorized.repair_action_ref, RepairAction)
    assert action.decision == "infrastructure_retry"
    assert action.workspace_recovery is True
    bound = artifacts.get_json(authorized.attempt_ref, WorkAttempt)
    assert bound.continuation_commitment is not None

    recovered = await scheduler.dispatch_one(
        definition.coordinate,
        executors={definition.work_id: execute},
    )
    assert recovered.after_state == "committed"
    assert seen_sessions == [None]


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
async def test_scheduler_records_backoff_gate_then_falls_back_without_rerunning_parents(
    tmp_path: Path,
) -> None:
    """One closed transient retry is gated, then only this node changes model.

    This is a constructed **real Scheduler/WorkRuntime boundary**. It uses an
    actual durable InvocationControlStore record for the first retry gate, but
    it deliberately does not claim that a fake Provider failure proves live
    model availability. The later live CandidateBuild mechanism remains the
    required proof for the configured provider route.
    """

    definition = structured_agent_work_definition(
        scope_id="job:model-fallback",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=1,
        maximum_total_repair_attempts=2,
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
    store = InvocationControlStore(tmp_path / "invocation-control")
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=3_000,
            agent_turns=3,
            repair_attempts=2,
            wall_seconds=300,
        ),
        model_routes=("grok-4.5", "gpt-5.3-codex-spark", "gpt-5.4-mini"),
        route_liveness_checker=InvocationControlRouteLivenessChecker(store),
        require_route_liveness_gate=True,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[WorkAttempt] = []

    def provenance(dispatch_id: str, model: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model=model,
            profile_digest=sha256_digest(canonical_json_bytes({"profile": model})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    def record_closed_transient(
        *,
        attempt: WorkAttempt,
        dispatch_id: str,
    ) -> None:
        ownership = leaf.invocation_ownership(
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
        )
        store.begin(
            invocation_id=dispatch_id,
            owner=ownership,
            route="codex_sdk",
            model="grok-4.5",
            profile_digest="sha256:" + "a" * 64,
            envelope_digest="b" * 64,
            declared_wall_seconds=30,
        )
        store.settle(
            dispatch_id,
            terminal=InvocationTerminalFact(
                status=InvocationStatus.FAILED,
                code="turn_failed_provider_unavailable",
                retryable=True,
            ),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt)
        if attempt.ordinal in {1, 2}:
            assert attempt.model_override is None
            assert attempt.continuation_commitment is None
            record_closed_transient(attempt=attempt, dispatch_id=dispatch_id)
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the configured provider temporarily rejected the route",
                retryable=True,
                terminal_details={"codex_error_info": "enum:serveroverloaded"},
                agent=provenance(dispatch_id, "grok-4.5"),
            )
        assert attempt.ordinal == 3
        assert attempt.model_override == "gpt-5.3-codex-spark"
        assert attempt.continuation_commitment is None
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.attempt_id}",
            artifact_type="design.research_plan",
            value={"model": attempt.model_override},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id, "gpt-5.3-codex-spark"),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == [
        "repair_ready",
        "repair_ready",
        "committed",
    ]
    assert [attempt.model_override for attempt in attempts] == [
        None,
        None,
        "gpt-5.3-codex-spark",
    ]
    assert len({attempt.input_refs for attempt in attempts}) == 1
    assert attempts[1].route_liveness_evidence_ref is not None
    gate = artifacts.get_json(attempts[1].route_liveness_evidence_ref)
    assert gate["status"] == "verified"
    assert gate["source"] == "invocation_control"
    assert gate["code"] == "route_liveness_prior_terminal_verified"

    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    # The repeated transport terminal has no semantic proposal to compare, so
    # its ledger outcome may be ``no_progress`` without suppressing the
    # independently authorized next-model route.
    assert runtime.repairs.entries[0].outcome == "no_progress"
    assert [action.decision for action in actions] == [
        "infrastructure_retry",
        "model_fallback",
    ]
    assert actions[0].route_liveness_required
    assert actions[0].retry_not_before is not None
    assert actions[1].model_override == "gpt-5.3-codex-spark"
    recovery_ref = next(
        ref
        for ref in actions[1].causal_evidence_refs
        if ref.artifact_type == "control.invocation_recovery_decision"
    )
    recovery = artifacts.get_json(recovery_ref)
    assert recovery["route"] == "model_fallback"
    assert recovery["target_model"] == "gpt-5.3-codex-spark"

    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_runs_two_definition_bound_same_model_retries_with_scaled_backoff(
    tmp_path: Path,
) -> None:
    """Two classified transients may use two fresh sessions when policy binds two."""

    definition = structured_agent_work_definition(
        scope_id="job:two-same-model-retries",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=2,
        maximum_model_fallbacks=0,
        maximum_total_repair_attempts=2,
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
    store = InvocationControlStore(tmp_path / "invocation-control")
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=3_000,
            agent_turns=3,
            repair_attempts=2,
            wall_seconds=300,
        ),
        model_routes=("gpt-5.4-mini",),
        route_liveness_checker=InvocationControlRouteLivenessChecker(store),
        require_route_liveness_gate=True,
        infrastructure_retry_backoff_seconds=0.01,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[WorkAttempt] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model="gpt-5.4-mini",
            profile_digest=sha256_digest(canonical_json_bytes({"profile": "mini"})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    def record_closed_transient(*, attempt: WorkAttempt, dispatch_id: str) -> None:
        ownership = leaf.invocation_ownership(
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
        )
        store.begin(
            invocation_id=dispatch_id,
            owner=ownership,
            route="codex_sdk",
            model="gpt-5.4-mini",
            profile_digest="sha256:" + "a" * 64,
            envelope_digest="b" * 64,
            declared_wall_seconds=30,
        )
        store.settle(
            dispatch_id,
            terminal=InvocationTerminalFact(
                status=InvocationStatus.FAILED,
                code="turn_failed_provider_unavailable",
                retryable=True,
            ),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt)
        if attempt.ordinal < 3:
            record_closed_transient(attempt=attempt, dispatch_id=dispatch_id)
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the configured provider temporarily rejected the route",
                retryable=True,
                terminal_details={"codex_error_info": "enum:internalservererror"},
                agent=provenance(dispatch_id),
            )
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.attempt_id}",
            artifact_type="design.research_plan",
            value={"model": "gpt-5.4-mini"},
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

    assert [result.after_state for result in results] == [
        "repair_ready",
        "repair_ready",
        "committed",
    ]
    assert [attempt.model_override for attempt in attempts] == [None, None, None]
    assert attempts[1].route_liveness_evidence_ref is not None
    assert attempts[2].route_liveness_evidence_ref is not None
    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    assert [action.decision for action in actions] == [
        "infrastructure_retry",
        "infrastructure_retry",
    ]
    delays: list[float] = []
    for action in actions:
        assert action.retry_not_before is not None
        delays.append((action.retry_not_before - action.authorized_at).total_seconds())
    assert delays == pytest.approx((0.01, 0.02))
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_switches_direct_output_ceiling_to_the_next_model_once(
    tmp_path: Path,
) -> None:
    """A Direct response ceiling changes route; it never repeats the same turn."""

    definition = structured_agent_work_definition(
        scope_id="job:direct-output-ceiling",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=1,
        maximum_total_repair_attempts=1,
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
        model_routes=("gpt-5.3-codex-spark", "gpt-5.4-mini"),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[WorkAttempt] = []

    def provenance(dispatch_id: str, model: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model=model,
            profile_digest=sha256_digest(canonical_json_bytes({"profile": model})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt)
        if attempt.ordinal == 1:
            assert attempt.model_override is None
            raise LeafExecutionFailure(
                code="agent_backend_direct_output_limit",
                category="the direct provider exhausted its physical response envelope",
                retryable=False,
                terminal_details={"terminal_reason": "max_output_tokens"},
                agent=provenance(dispatch_id, "gpt-5.3-codex-spark"),
            )
        assert attempt.ordinal == 2
        assert attempt.model_override == "gpt-5.4-mini"
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.attempt_id}",
            artifact_type="design.research_plan",
            value={"model": attempt.model_override},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id, "gpt-5.4-mini"),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert [attempt.model_override for attempt in attempts] == [None, "gpt-5.4-mini"]
    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    assert len(actions) == 1
    assert actions[0].decision == "model_fallback"
    assert actions[0].reason_code == "direct_output_ceiling_model_fallback"
    assert actions[0].model_override == "gpt-5.4-mini"
    assert not actions[0].route_liveness_required
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_falls_back_after_cross_class_transient_failure_during_semantic_repair(
    tmp_path: Path,
) -> None:
    """A transient recovery retains the exact authorized semantic repair.

    This is the true Scheduler boundary reproduced by the E2E ToolSemantics
    failure: Grok yields a parsed candidate with precise semantic findings;
    its authorized fresh correction loses the Provider before its first event,
    then the one permitted same-model retry receives a closed capacity
    terminal.  Those are different transient subclasses on the same failed
    route, not authority for a second Grok retry. Spark must receive the same
    correction brief and private parsed seed without reusing a Provider
    session or redispatching an upstream node.
    """

    definition = structured_agent_work_definition(
        scope_id="job:semantic-repair-transport-fallback",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="A classified transport terminal must preserve its fallback path.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=1,
        maximum_total_repair_attempts=3,
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
    store = InvocationControlStore(tmp_path / "invocation-control")
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=4_000,
            agent_turns=4,
            repair_attempts=3,
            wall_seconds=300,
        ),
        model_routes=("grok-4.5", "gpt-5.3-codex-spark"),
        route_liveness_checker=InvocationControlRouteLivenessChecker(store),
        require_route_liveness_gate=True,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[WorkAttempt] = []
    received_briefs = []
    received_seeds: list[LeafSemanticRepairSeed | None] = []
    candidate = {"steps": [{"kind": "research"}]}

    def provenance(dispatch_id: str, model: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model=model,
            profile_digest=sha256_digest(canonical_json_bytes({"profile": model})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    def record_closed_transient(
        *,
        attempt: WorkAttempt,
        dispatch_id: str,
        model: str,
        code: str,
    ) -> None:
        store.begin(
            invocation_id=dispatch_id,
            owner=leaf.invocation_ownership(
                definition=definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
            ),
            route="direct_llm",
            model=model,
            profile_digest="sha256:" + "a" * 64,
            envelope_digest="b" * 64,
            declared_wall_seconds=30,
        )
        store.settle(
            dispatch_id,
            terminal=InvocationTerminalFact(
                status=InvocationStatus.FAILED,
                code=code,
                retryable=True,
            ),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt)
        current_model = attempt.model_override or "grok-4.5"
        if attempt.ordinal in {2, 3}:
            assert current_model == "grok-4.5"
            brief = leaf.agent_correction_brief(context, definition=definition)
            seed = leaf.agent_semantic_repair_seed(
                context,
                definition=definition,
                attempt=attempt,
            )
            received_briefs.append(brief)
            received_seeds.append(seed)
            assert brief is not None
            assert brief.issues[0].code == "semantic_required_step_missing"
            assert seed is not None and seed.previous_candidate == candidate
            terminal_code = (
                "direct_no_first_provider_event"
                if attempt.ordinal == 2
                else "direct_provider_unavailable"
            )
            record_closed_transient(
                attempt=attempt,
                dispatch_id=dispatch_id,
                model=current_model,
                code=terminal_code,
            )
            raise LeafExecutionFailure(
                code=f"agent_backend_{terminal_code}",
                category=(
                    "the Direct Provider stream emitted no first event"
                    if attempt.ordinal == 2
                    else "the configured Direct Provider was temporarily unavailable"
                ),
                retryable=True,
                terminal_details=(
                    {"waiting_phase": "direct_awaiting_stream_event"}
                    if attempt.ordinal == 2
                    else {}
                ),
                agent=provenance(dispatch_id, current_model),
            )
        if attempt.ordinal == 1:
            assert current_model == "grok-4.5"
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="semantic_required_step_missing",
                        path=("steps",),
                        violated_condition="the parsed plan omits its required verification step",
                        expected_category="one complete plan including that verification step",
                    ),
                ),
                output_commitment=sha256_digest(canonical_json_bytes(candidate)),
                category="semantic_plan",
                agent=provenance(dispatch_id, current_model),
                semantic_repair_seed=LeafSemanticRepairSeed(
                    model=current_model,
                    profile_digest=provenance(dispatch_id, current_model).profile_digest,
                    output_schema_digest=provenance(
                        dispatch_id, current_model
                    ).output_schema_digest,
                    previous_candidate=candidate,
                ),
            )
        assert attempt.ordinal == 4
        assert current_model == "gpt-5.3-codex-spark"
        brief = leaf.agent_correction_brief(context, definition=definition)
        seed = leaf.agent_semantic_repair_seed(
            context,
            definition=definition,
            attempt=attempt,
        )
        received_briefs.append(brief)
        received_seeds.append(seed)
        assert brief is not None
        assert brief.issues[0].code == "semantic_required_step_missing"
        assert seed is not None and seed.previous_candidate == candidate
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.attempt_id}",
            artifact_type="design.research_plan",
            value={"model": current_model},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id, current_model),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == [
        "repair_ready",
        "repair_ready",
        "repair_ready",
        "committed",
    ]
    assert [attempt.model_override for attempt in attempts] == [
        None,
        None,
        None,
        "gpt-5.3-codex-spark",
    ]
    assert len({attempt.input_refs for attempt in attempts}) == 1
    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    assert [action.decision for action in actions] == [
        "local_correction",
        "infrastructure_retry",
        "model_fallback",
    ]
    assert actions[1].semantic_repair_context_ref == runtime.repairs.entries[0].repair_action_ref
    assert actions[2].semantic_repair_context_ref == runtime.repairs.entries[0].repair_action_ref
    assert actions[2].model_override == "gpt-5.3-codex-spark"
    assert not actions[2].route_liveness_required
    assert len(received_briefs) == 3
    assert len(received_seeds) == 3
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_retries_committed_candidate_snapshot_repair_after_transport_terminal(
    tmp_path: Path,
) -> None:
    """A Candidate snapshot repair survives a fresh transport recovery.

    This is the Scheduler boundary behind the live Candidate failure: a
    downstream Integration finding authorizes a Candidate correction whose
    seed is the already-committed Candidate closure, not a private parsed
    Direct-output seed.  When that correction reaches a classified Provider
    terminal, the next fresh Agent attempt must retain the original safe
    feedback and snapshot authority rather than becoming a blind initial
    build.
    """

    scope_id = "job:candidate-snapshot-transport-recovery"
    candidate = structured_agent_work_definition(
        scope_id=scope_id,
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One committed Candidate can receive an Integration-owned repair.",
        timing_reason="Integration must run against a complete Candidate closure.",
        output_contract_id="contract:environment-candidate.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/source", "/runtime"),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=0,
        # The initial Candidate delivery consumes one same-model retry before
        # it commits. A later Integration-selected correction must still get
        # its own fresh-route retry: it is a separate semantic-repair lineage.
        maximum_total_repair_attempts=3,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:environment-candidate",
                direction="output",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    integration_base = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependency_coordinates=(candidate.coordinate,),
        claim_id="integration.runtime.executable",
        claim="One isolated runtime gate verifies the current Candidate.",
        timing_reason="Only the independent runtime gate can identify this repair target.",
        effect="block_release",
        success_maturity="integration_passed",
    )
    integration = integration_base.model_copy(
        update={
            "repair_target_coordinates": (candidate.coordinate,),
            "repair_policy": integration_base.repair_policy.model_copy(
                update={
                    "maximum_automatic_backjump": 1,
                    "maximum_total_repair_attempts": 1,
                }
            ),
            "allowed_mutation_roots": candidate.allowed_mutation_roots,
        }
    )
    graph = GenerationWorkGraph.compile((candidate, integration), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "build.", "release."),
    )
    root_ref = artifacts.put_json(
        artifact_id="candidate-snapshot-context",
        artifact_type="control.generation_context",
        value={"context": "candidate-snapshot-transport-recovery"},
    )
    manifest = graph.manifest(
        topology_id="topology:candidate-snapshot-transport-recovery",
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
        budget=LeaseBudgetLedger(
            Budget(
                llm_tokens=5_000,
                agent_turns=4,
                repair_attempts=3,
                process_calls=4,
                wall_seconds=300,
            )
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
    candidate_attempts: list[WorkAttempt] = []
    integration_attempts: list[int] = []
    received_briefs: list[tuple[ValidationIssue, ...]] = []
    received_private_seeds: list[LeafSemanticRepairSeed | None] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model="gpt-5.4-mini",
            profile_digest=sha256_digest(canonical_json_bytes({"profile": "engineer"})),
            output_schema_digest=sha256_digest(
                canonical_json_bytes({"schema": "environment-candidate"})
            ),
        )

    def candidate_output(
        context,
        attempt: WorkAttempt,
        dispatch_id: str,
    ) -> LeafProposal:
        output_ref = artifacts.put_json(
            artifact_id=f"candidate-snapshot:{attempt.ordinal}",
            artifact_type="build.environment_candidate",
            value={"candidate_revision": attempt.ordinal},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id),
        )

    async def candidate_proposal(
        context,
        attempt: WorkAttempt,
        dispatch_id: str,
    ) -> LeafProposal:
        candidate_attempts.append(attempt)
        if attempt.ordinal == 1:
            # This is the already-consumed infrastructure retry from the
            # initial Candidate delivery.  It must not spend the later
            # Integration-repair route's allowance.
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the configured Provider became unavailable before a terminal response",
                retryable=True,
                agent=provenance(dispatch_id),
            )
        if attempt.ordinal == 2:
            initial_physical_action = artifacts.get_json(context.repair_action_ref, RepairAction)
            assert initial_physical_action.decision == "infrastructure_retry"
            assert initial_physical_action.semantic_repair_context_ref is None
            return candidate_output(context, attempt, dispatch_id)

        brief = kernel.agent_correction_brief(context, definition=candidate)
        assert brief is not None
        received_briefs.append(brief.issues)
        received_private_seeds.append(
            kernel.agent_semantic_repair_seed(
                context,
                definition=candidate,
                attempt=attempt,
            )
        )
        if attempt.ordinal == 3:
            semantic_action = artifacts.get_json(context.repair_action_ref, RepairAction)
            assert context.semantic_repair_context_ref == context.repair_action_ref
            assert semantic_action.decision == "local_correction"
            assert semantic_action.repair_seed_attempt_ref is not None
            assert (
                len(
                    tuple(
                        ref
                        for ref in semantic_action.repair_seed_output_refs
                        if ref.artifact_type == "build.environment_candidate"
                    )
                )
                == 1
            )
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the configured Provider became unavailable before a terminal response",
                retryable=True,
                agent=provenance(dispatch_id),
            )

        assert attempt.ordinal == 4
        physical_action = artifacts.get_json(context.repair_action_ref, RepairAction)
        assert physical_action.decision == "infrastructure_retry"
        assert physical_action.semantic_repair_context_ref is not None
        return candidate_output(context, attempt, dispatch_id)

    async def integration_proposal(
        context,
        attempt: WorkAttempt,
        _dispatch_id: str,
    ) -> LeafProposal:
        integration_attempts.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="runtime_protocol_rejects_candidate",
                        path=("runtime", "handshake"),
                        violated_condition="The isolated runtime protocol rejected this Candidate.",
                        expected_category="a Candidate source satisfying the runtime protocol",
                        remediation="Repair the Candidate runtime handshake implementation.",
                    ),
                ),
                output_commitment=sha256_digest(b"failed-integration-candidate-snapshot"),
                category="isolated_runtime_protocol",
                parent_repair_target=candidate.coordinate,
            )
        output_ref = artifacts.put_json(
            artifact_id="integration-after-candidate-snapshot-retry",
            artifact_type="release.final_telemetry_summary",
            value={"candidate_parent_commit": context.parent_commit_refs[0].revision_id},
            dependencies=context.parent_output_refs,
        )
        return LeafProposal(output_refs=(output_ref,), subject_refs=(output_ref,))

    async def execute_candidate(context) -> None:
        await kernel.execute(context, definition=candidate, proposal_runner=candidate_proposal)

    async def execute_integration(context) -> None:
        await kernel.execute(context, definition=integration, proposal_runner=integration_proposal)

    results = await scheduler.run_until_stalled(
        executors={
            candidate.work_id: execute_candidate,
            integration.work_id: execute_integration,
        },
        maximum_concurrency=1,
    )

    assert [attempt.ordinal for attempt in candidate_attempts] == [1, 2, 3, 4]
    assert integration_attempts == [1, 2]
    assert received_private_seeds == [None, None]
    assert received_briefs == [
        (
            ValidationIssue(
                code="causal_runtime_protocol_rejects_candidate",
                path=(
                    "causal_feedback",
                    "integration",
                    "runtime_integration",
                    "runtime",
                    "handshake",
                ),
                violated_condition="The isolated runtime protocol rejected this Candidate.",
                expected_category="a Candidate source satisfying the runtime protocol",
                remediation="Repair the Candidate runtime handshake implementation.",
            ),
        ),
        (
            ValidationIssue(
                code="causal_runtime_protocol_rejects_candidate",
                path=(
                    "causal_feedback",
                    "integration",
                    "runtime_integration",
                    "runtime",
                    "handshake",
                ),
                violated_condition="The isolated runtime protocol rejected this Candidate.",
                expected_category="a Candidate source satisfying the runtime protocol",
                remediation="Repair the Candidate runtime handshake implementation.",
            ),
        ),
    ]
    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    assert [action.decision for action in actions] == [
        "infrastructure_retry",
        "local_correction",
        "infrastructure_retry",
    ]
    assert actions[0].semantic_repair_context_ref is None
    assert actions[2].semantic_repair_context_ref == runtime.repairs.entries[1].repair_action_ref
    assert actions[2].allowed_mutation_roots == candidate.allowed_mutation_roots
    assert runtime.repairs.entries[2].semantic_repair_context_ref == (
        runtime.repairs.entries[1].repair_action_ref
    )
    assert candidate_attempts[3].semantic_repair_seed_commitment is None
    assert [entry.outcome for entry in runtime.repairs.entries] == [
        "resolved",
        "no_progress",
        "resolved",
    ]
    candidate_head = heads.read_head(candidate.coordinate)
    integration_head = heads.read_head(integration.coordinate)
    assert candidate_head is not None and candidate_head.status == "committed"
    assert integration_head is not None and integration_head.status == "committed"
    assert [item.after_state for item in results] == [
        "repair_ready",
        "committed",
        "blocked",
        "repair_ready",
        "committed",
        "committed",
    ]


@pytest.mark.asyncio
async def test_scheduler_retries_each_fallback_route_before_advancing_again(
    tmp_path: Path,
) -> None:
    """A retry is scoped to the active model, never a prior fallback route.

    This extends the durable Scheduler/WorkRuntime proof across three
    configured models.  The first Grok retry and the first Spark retry both
    require their own closed control-plane record and fresh node-local turn;
    neither may be skipped because another model already consumed a retry.
    """

    routes = ("grok-4.5", "gpt-5.3-codex-spark", "gpt-5.4-mini")
    definition = structured_agent_work_definition(
        scope_id="job:per-route-model-retry",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_model_fallbacks=2,
        maximum_total_repair_attempts=5,
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
    store = InvocationControlStore(tmp_path / "invocation-control")
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=5_000,
            agent_turns=5,
            repair_attempts=5,
            wall_seconds=300,
        ),
        model_routes=routes,
        route_liveness_checker=InvocationControlRouteLivenessChecker(store),
        require_route_liveness_gate=True,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    attempts: list[WorkAttempt] = []

    def provenance(dispatch_id: str, model: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model=model,
            profile_digest=sha256_digest(canonical_json_bytes({"profile": model})),
            output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
        )

    def record_closed_transient(
        *,
        attempt: WorkAttempt,
        dispatch_id: str,
        model: str,
    ) -> None:
        store.begin(
            invocation_id=dispatch_id,
            owner=leaf.invocation_ownership(
                definition=definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
            ),
            route="codex_sdk",
            model=model,
            profile_digest="sha256:" + "a" * 64,
            envelope_digest="b" * 64,
            declared_wall_seconds=30,
        )
        store.settle(
            dispatch_id,
            terminal=InvocationTerminalFact(
                status=InvocationStatus.FAILED,
                code="turn_failed_provider_unavailable",
                retryable=True,
            ),
        )

    expected_models = (routes[0], routes[0], routes[1], routes[1], routes[2])

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        attempts.append(attempt)
        expected_model = expected_models[attempt.ordinal - 1]
        actual_model = attempt.model_override or routes[0]
        assert actual_model == expected_model
        assert attempt.continuation_commitment is None
        if attempt.ordinal < len(expected_models):
            record_closed_transient(
                attempt=attempt,
                dispatch_id=dispatch_id,
                model=actual_model,
            )
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the configured provider temporarily rejected the route",
                retryable=True,
                terminal_details={"codex_error_info": "enum:serveroverloaded"},
                agent=provenance(dispatch_id, actual_model),
            )
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.attempt_id}",
            artifact_type="design.research_plan",
            value={"model": actual_model},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=provenance(dispatch_id, actual_model),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == [
        "repair_ready",
        "repair_ready",
        "repair_ready",
        "repair_ready",
        "committed",
    ]
    assert [attempt.model_override for attempt in attempts] == [
        None,
        None,
        routes[1],
        routes[1],
        routes[2],
    ]
    assert len({attempt.input_refs for attempt in attempts}) == 1
    assert attempts[1].route_liveness_evidence_ref is not None
    assert attempts[3].route_liveness_evidence_ref is not None

    actions = tuple(
        artifacts.get_json(entry.repair_action_ref, RepairAction)
        for entry in runtime.repairs.entries
    )
    assert [(action.decision, action.route_model, action.model_override) for action in actions] == [
        ("infrastructure_retry", routes[0], None),
        ("model_fallback", routes[0], routes[1]),
        ("infrastructure_retry", routes[1], None),
        ("model_fallback", routes[1], routes[2]),
    ]
    assert [entry.outcome for entry in runtime.repairs.entries] == [
        "no_progress",
        "no_progress",
        "no_progress",
        "resolved",
    ]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


@pytest.mark.asyncio
async def test_scheduler_rejects_missing_route_liveness_before_second_leaf_turn(
    tmp_path: Path,
) -> None:
    """A missing durable prior record closes the retry before a second call.

    This is the opposite branch of the same Scheduler/WorkRuntime boundary:
    the first leaf reaches a closed retryable terminal, but no matching
    InvocationControl record exists.  The gate must leave no second proposal
    turn or hidden retry behind.
    """

    definition = structured_agent_work_definition(
        scope_id="job:route-liveness-rejection",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=(),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_total_repair_attempts=2,
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
    store = InvocationControlStore(tmp_path / "invocation-control")
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
        model_routes=("grok-4.5", "gpt-5.3-codex-spark"),
        route_liveness_checker=InvocationControlRouteLivenessChecker(store),
        require_route_liveness_gate=True,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    calls: list[str] = []

    async def proposal(_context, _attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        calls.append(dispatch_id)
        raise LeafExecutionFailure(
            code="agent_backend_turn_failed_provider_unavailable",
            category="the configured provider temporarily rejected the route",
            retryable=True,
            terminal_details={"codex_error_info": "enum:serveroverloaded"},
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="openai-compatible",
                model="grok-4.5",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "grok"})),
                output_schema_digest=sha256_digest(canonical_json_bytes({"schema": "plan"})),
            ),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "blocked"]
    assert len(calls) == 1
    assert len(runtime.repairs.entries) == 1
    assert runtime.repairs.entries[0].outcome == "exhausted"
    gate_refs = tuple(
        ref
        for ref in artifacts.list_revisions()
        if ref.artifact_type == "control.invocation_route_liveness_check"
    )
    assert len(gate_refs) == 1
    gate = artifacts.get_json(gate_refs[0])
    assert gate["status"] == "rejected"
    assert gate["code"] == "route_liveness_prior_record_missing"
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.active_operation_ref is None


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
        maximum_total_repair_attempts=1,
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
async def test_closed_transient_with_resumable_session_continues_same_thread(
    tmp_path: Path,
) -> None:
    """A settled Provider terminal resumes the exact Agent session first.

    This crosses the real Scheduler/continuation-store boundary. It proves
    that a transport terminal spends the declared infrastructure retry while
    retaining the private thread and workspace; a fresh draft recovery remains
    the fallback only when that session is unavailable.
    """

    definition = structured_agent_work_definition(
        scope_id="job:transient-session-continuation",
        component="build",
        stage="candidate_build",
        artifact_slot="candidate_build",
        dependency_coordinates=(),
        claim_id="builder.candidate.completes",
        claim="A transient Provider terminal may continue the exact Agent session.",
        timing_reason="A resumable thread preserves work already completed in its workspace.",
        output_contract_id="contract:candidate-build",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        session_token_limit=2_000,
        session_wall_seconds=120,
        maximum_local_corrections=0,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_session_continuations=1,
        maximum_total_repair_attempts=1,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:candidate-build",
                direction="output",
                artifact_types=("design.candidate_build",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
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
    workspace = tmp_path / "continuation-workspaces" / "workspace"
    workspace.mkdir()
    session = InvocationSession(
        thread_id="private-thread-transient",
        lineage_id="job:transient-session-continuation",
        workspace=workspace.resolve(),
        profile_hash="a" * 64,
        codex_config_sha256="b" * 64,
    )
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "candidate-build"}))
    kernel = SchedulerLeafExecutor(runtime=runtime)
    seen_attempts: list[int] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model="gpt-5.4-mini",
            profile_digest=f"sha256:{session.profile_hash}",
            output_schema_digest=schema_digest,
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        seen_attempts.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the Provider ended before a terminal CandidateCompletion",
                retryable=True,
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
                session_continuation=LeafSessionContinuation(
                    session=session,
                    model="gpt-5.4-mini",
                    output_schema_digest=schema_digest,
                ),
            )
        assert attempt.ordinal == 2
        assert attempt.continuation_commitment is not None
        assert runtime.continuations is not None
        record = runtime.continuations.load_commitment(
            attempt.continuation_commitment,
            workspace_root=tmp_path / "continuation-workspaces",
        )
        assert record is not None
        assert record.restore_session() == session
        output_ref = artifacts.put_json(
            artifact_id="candidate-build:continued-after-transient",
            artifact_type="design.candidate_build",
            value={"continued_same_thread": True},
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
    assert attempt.repair_attempt_charge == 1
    action = artifacts.get_json(attempt.repair_action_ref, RepairAction)
    assert action.decision == "session_continuation"
    assert action.reason_code == "provider_session_continuation"
    assert action.repair_attempt_charge == 1
    assert action.route_model == "gpt-5.4-mini"
    assert action.route_liveness_required
    assert action.retry_not_before is not None
    recovery_ref = next(
        ref
        for ref in action.causal_evidence_refs
        if ref.artifact_type == "control.invocation_recovery_decision"
    )
    recovery = artifacts.get_json(recovery_ref)
    assert recovery["route"] == "session_continuation"
    assert recovery["private_session_continuation_available"] is True


@pytest.mark.asyncio
async def test_closed_transient_private_draft_starts_fresh_workspace_recovery_attempt(
    tmp_path: Path,
) -> None:
    """A written Builder draft is input to one new thread, never an adopted output.

    This is a constructed real Scheduler/WorkRuntime boundary: the first
    physical Agent attempt writes a regular private draft and reaches a
    settled transient terminal.  The successor has a private draft record but
    no Provider thread; it must still produce normal output that commits only
    through the ordinary validation path.
    """

    definition = structured_agent_work_definition(
        scope_id="job:candidate-workspace-recovery",
        component="build",
        stage="candidate_build",
        artifact_slot="candidate_build",
        dependency_coordinates=(),
        claim_id="builder.candidate.completes",
        claim="One fresh Builder session may inspect an interrupted private draft.",
        timing_reason="A terminal Provider outage must not adopt an uncommitted candidate.",
        output_contract_id="contract:candidate-build",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        # CandidateBuild declares normal semantic repair roots as well; this
        # test takes only the distinct infrastructure-recovery branch.
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=1,
        maximum_total_repair_attempts=2,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:candidate-build",
                direction="output",
                artifact_types=("design.candidate_build",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    invocation_store = InvocationControlStore(tmp_path / "invocation-control")
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
        route_liveness_checker=InvocationControlRouteLivenessChecker(invocation_store),
        require_route_liveness_gate=True,
    )
    assert runtime.continuation_workspace_root is not None
    workspace = (
        runtime.continuation_workspace_root
        / "builder"
        / "attempt-initial"
        / ".agent-runtime"
        / "workspace"
    )
    (workspace / "candidate").mkdir(parents=True)
    draft_path = workspace / "candidate" / "runtime.py"
    draft_path.write_text("def draft_runtime():\n    return 'untrusted'\n", encoding="utf-8")

    model = "grok-4.5"
    profile_digest = f"sha256:{'a' * 64}"
    config_digest = f"sha256:{'b' * 64}"
    schema_digest = sha256_digest(canonical_json_bytes({"schema": "candidate-build"}))
    leaf = SchedulerLeafExecutor(runtime=runtime)
    seen_attempts: list[WorkAttempt] = []

    def provenance(dispatch_id: str) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=dispatch_id,
            provider="openai-compatible",
            model=model,
            profile_digest=profile_digest,
            output_schema_digest=schema_digest,
        )

    def record_closed_transient(*, attempt: WorkAttempt, dispatch_id: str) -> None:
        ownership = leaf.invocation_ownership(
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
        )
        invocation_store.begin(
            invocation_id=dispatch_id,
            owner=ownership,
            route="codex_sdk",
            model=model,
            profile_digest=profile_digest,
            envelope_digest="c" * 64,
            declared_wall_seconds=30,
        )
        invocation_store.settle(
            dispatch_id,
            terminal=InvocationTerminalFact(
                status=InvocationStatus.FAILED,
                code="turn_failed_provider_unavailable",
                retryable=True,
            ),
        )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        seen_attempts.append(attempt)
        if attempt.ordinal == 1:
            record_closed_transient(attempt=attempt, dispatch_id=dispatch_id)
            raise LeafExecutionFailure(
                code="agent_backend_turn_failed_provider_unavailable",
                category="the Provider became unavailable after a private candidate write",
                retryable=True,
                observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
                agent=provenance(dispatch_id),
                workspace_recovery=LeafWorkspaceRecovery(
                    workspace=workspace.resolve(),
                    lineage_id="implementation:candidate-workspace-recovery",
                    profile_digest=profile_digest,
                    codex_config_digest=config_digest,
                    model=model,
                    output_schema_digest=schema_digest,
                ),
            )
        assert attempt.ordinal == 2
        assert attempt.continuation_commitment is not None
        assert attempt.model_override is None
        assert runtime.continuations is not None
        record = runtime.continuations.load_commitment(
            attempt.continuation_commitment,
            workspace_root=runtime.continuation_workspace_root,
        )
        assert record is not None
        assert record.continuation_kind == "workspace_recovery"
        assert record.thread_id is None
        assert record.workspace_for_recovery() == workspace.resolve()
        with pytest.raises(ContinuationStoreError, match="cannot resume a Provider thread"):
            record.restore_session()
        assert draft_path.read_text(encoding="utf-8").startswith("def draft_runtime")
        output_ref = artifacts.put_json(
            artifact_id="candidate-build:completed-after-workspace-recovery",
            artifact_type="design.candidate_build",
            value={"accepted_only_after_fresh_completion": True},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            observed_actual=BudgetUsage(llm_tokens=1_000, agent_turns=1),
            agent=provenance(dispatch_id),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert [attempt.ordinal for attempt in seen_attempts] == [1, 2]
    repair = runtime.artifacts.get_json(seen_attempts[1].repair_action_ref, RepairAction)
    assert repair.decision == "infrastructure_retry"
    assert repair.workspace_recovery
    assert repair.reason_code == "private_workspace_recovery"
    assert repair.route_liveness_required
    assert seen_attempts[1].route_liveness_evidence_ref is not None
    route_gate = artifacts.get_json(seen_attempts[1].route_liveness_evidence_ref)
    assert route_gate["status"] == "verified"
    recovery_ref = next(
        ref
        for ref in repair.causal_evidence_refs
        if ref.artifact_type == "control.invocation_recovery_decision"
    )
    assert artifacts.get_json(recovery_ref)["route"] == "workspace_recovery"
    assert str(workspace) not in seen_attempts[1].model_dump_json()
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"


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
    assert execution.invocation_id == proposal_run.dispatch_id
    assert execution.provider is None
    assert execution.model is None
    assert execution.profile_digest is None
    assert execution.output_schema_digest is None


@pytest.mark.asyncio
async def test_scheduler_boundary_settles_an_uncooperative_cancelled_executor(
    tmp_path: Path,
) -> None:
    """The outer Scheduler owns the last cancellation fence, not one leaf type."""

    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    started = asyncio.Event()

    async def uncooperative_executor(context) -> None:
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        with runtime.heads.exclusive(definition.coordinate) as lock:
            runtime.schedule_operation(
                lock,
                definition=definition,
                kind="proposal",
                replay_mode="non_replayable",
                elapsed_wall_seconds=0,
                input_refs=input_refs,
            )
            runtime.start_operation(
                lock,
                definition=definition,
                dispatch_id="dispatch:scheduler-boundary-cancellation",
            )
        started.set()
        await asyncio.Event().wait()

    dispatch = asyncio.create_task(
        scheduler.dispatch_one(
            definition.coordinate,
            executors={definition.work_id: uncooperative_executor},
        )
    )
    await started.wait()
    dispatch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await dispatch

    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed" and head.active_operation_ref is None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    proposal = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    assert proposal.status == "terminal"
    assert proposal.error_code == "process_interrupted_cancelled"
    assert proposal.execution_ref is not None
    execution = artifacts.get_json(proposal.execution_ref, ProposalExecution)
    assert execution.invocation_id is None


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
    assert proposal_run.execution_ref is not None
    recovered_execution = artifacts.get_json(proposal_run.execution_ref, ProposalExecution)
    assert recovered_execution.invocation_id == "dispatch:orphaned-real-agent-turn"
    assert recovered_execution.provider is None
    assert recovered_execution.model is None
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


def test_direct_runner_recovers_an_old_running_definition_before_current_graph_restarts(
    tmp_path: Path,
) -> None:
    """An old orphan settles under its own definition; the new graph sees only stale state.

    This is a true recovery boundary: no Agent executor is registered or
    invoked.  It reproduces a process interruption after a frozen definition
    was superseded by an implementation change, then exercises the production
    Direct runner recovery hook and current scheduler projection.
    """

    historical_definition = structured_agent_work_definition(
        scope_id="job:historical-running-definition",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Acquisition cannot begin without an exact plan.",
        output_contract_id="contract:research-plan",
        implementation_revision_id="framework.impl.research-plan.v1",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        replay_mode="non_replayable",
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
        definition=historical_definition,
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
    artifacts.put_json(
        artifact_id=f"work-definition:{historical_definition.work_id}",
        artifact_type="control.work_definition",
        value=historical_definition,
    )
    with heads.exclusive(historical_definition.coordinate) as lock:
        runtime.begin(
            lock,
            definition=historical_definition,
            input_refs=(root_ref,),
            elapsed_wall_seconds=0,
        )
        runtime.schedule_operation(
            lock,
            definition=historical_definition,
            kind="proposal",
            replay_mode=historical_definition.proposal_policy.replay_mode,
            elapsed_wall_seconds=0,
        )
        runtime.start_operation(
            lock,
            definition=historical_definition,
            dispatch_id="dispatch:historical-orphan",
        )

    current_definition = historical_definition.model_copy(
        update={
            "proposal_policy": historical_definition.proposal_policy.model_copy(
                update={"implementation_revision_id": "framework.impl.research-plan.v2"}
            )
        }
    )
    current_graph = GenerationWorkGraph.compile((current_definition,), mode="diagnostic")
    current_manifest = current_graph.manifest(
        topology_id="topology:current-definition-after-recovery",
        external_root_refs=(root_ref,),
    )
    current_manifest_ref = artifacts.put_json(
        artifact_id=current_manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=current_manifest,
        dependencies=(root_ref,),
    )
    current_scheduler = WorkScheduler(
        graph=current_graph,
        manifest=current_manifest,
        manifest_ref=current_manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )

    DirectWorkRunner._reconcile_abandoned_operations(  # noqa: SLF001
        graph=current_graph,
        runtime=runtime,
        scheduler=current_scheduler,
    )

    recovered = heads.read_head(historical_definition.coordinate)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.active_operation_ref is None
    assert recovered.definition_digest == historical_definition.definition_digest
    attempt = artifacts.get_json(recovered.attempt_ref, WorkAttempt)
    assert attempt.definition_digest == historical_definition.definition_digest
    operation = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    assert operation.status == "terminal"
    assert operation.error_code == "process_interrupted_after_dispatch"

    assert current_scheduler.snapshot().work[0].state == "stale"


def test_recovery_reuses_a_lease_settled_before_the_operation_terminalizes(
    tmp_path: Path,
) -> None:
    """A crash after durable budget settlement cannot try to overwrite that charge."""

    definition = structured_agent_work_definition(
        scope_id="job:settled-lease-recovery",
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
        replay_mode="non_replayable",
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
            dispatch_id="dispatch:settled-before-operation-terminal",
        )

    head = heads.read_head(definition.coordinate)
    assert head is not None and head.active_operation_ref is not None
    operation = artifacts.get_json(head.active_operation_ref, OperationRun)
    prior_unknown = BudgetUsage(llm_tokens=1_000, agent_turns=1)
    runtime.budget_coordinator.settle(
        scope_id=definition.coordinate.scope_id,
        lease_id=operation.budget_lease_ref.artifact_id,
        observed_actual=BudgetUsage(),
        unknown_upper_bound=prior_unknown,
    )

    with heads.exclusive(definition.coordinate) as lock:
        recovered = runtime.reconcile_abandoned_operation(lock, definition=definition)

    assert recovered.status == "failed"
    attempt = artifacts.get_json(recovered.attempt_ref, WorkAttempt)
    proposal_operation = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    assert proposal_operation.status == "terminal"
    assert proposal_operation.unknown_upper_bound == prior_unknown
    settled = runtime.budget_coordinator.snapshot(scope_id=definition.coordinate.scope_id)
    durable = next(
        item for item in settled.leases if item.lease_id == operation.budget_lease_ref.artifact_id
    )
    assert durable.observed_actual == BudgetUsage()
    assert durable.unknown_upper_bound == prior_unknown


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
async def test_scheduler_rejects_an_impossible_validation_envelope_before_agent_dispatch(
    tmp_path: Path,
) -> None:
    """A missing process budget fails before the first expensive proposal.

    This is the real Scheduler-to-leaf boundary behind the BuilderPlan bad
    case: a future deterministic validation needs two process calls, while the
    configured scope admits none. The proposal runner represents the actual
    backend boundary and must not be reached.
    """

    base = structured_agent_work_definition(
        scope_id="job:validation-envelope",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One isolated Researcher call produces a bounded research plan.",
        timing_reason="Validation capacity must be admitted before the Agent proposal.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=1,
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
    definition = base.model_copy(
        update={
            "validation_policy": base.validation_policy.model_copy(
                update={"budget": OperationBudget(wall_seconds=30, process_calls=2)}
            )
        }
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    dispatched: list[str] = []

    async def proposal(_context, _attempt, _dispatch_id) -> LeafProposal:
        dispatched.append("agent")
        raise AssertionError("the preflight must reject before the Agent dispatch")

    async def execute(context) -> None:
        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    result = await scheduler.dispatch_one(
        definition.coordinate,
        executors={definition.work_id: execute},
    )

    assert result.after_state == "blocked"
    assert dispatched == []
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.status == "budget_exhausted"
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["exhausted_dimensions"] == ["process_calls"]


@pytest.mark.asyncio
async def test_scheduler_projects_exact_remaining_budget_at_envelope_admission(
    tmp_path: Path,
) -> None:
    """The project Agent sees the actual reserve deficit, not just its dimension.

    This is the ReleaseAssurance bad-case shape: a prior settled lease leaves
    3,151 tool calls, while the frozen full operation envelope needs 3,587.
    The Scheduler must reject before any executor crosses a real boundary and
    the scene must expose only that exact deterministic comparison.
    """

    base = deterministic_boundary_work_definition(
        scope_id="job:release-assurance-budget",
        component="release",
        stage="release_assurance",
        artifact_slot="release_assurance",
        dependency_coordinates=(),
        claim_id="release.assurance.closes",
        claim="One release assurance operation closes the frozen release evidence.",
        timing_reason="The complete assurance envelope must fit before any proposal runs.",
        effect="block_release",
        success_maturity="release_assurance_closed",
    )
    definition = base.model_copy(
        update={
            "validation_policy": base.validation_policy.model_copy(
                update={"budget": OperationBudget(wall_seconds=30, tool_calls=3_587)}
            )
        }
    )
    artifacts, _definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(
            tool_calls=3_200,
            wall_seconds=300,
        ),
    )
    runtime.budget_coordinator.initialize(
        scope_id=definition.coordinate.scope_id,
        reserved=runtime.budget.reserved,
        leases=runtime.budget.leases,
    )
    settled = runtime.budget_coordinator.reserve(
        scope_id=definition.coordinate.scope_id,
        lease_id="lease:already-settled-tool-calls",
        owner_id="operation:already-settled-tool-calls",
        requested=Budget(tool_calls=49),
        elapsed_wall_seconds=0,
    )
    runtime.budget_coordinator.settle(
        scope_id=definition.coordinate.scope_id,
        lease_id=settled.lease_id,
        observed_actual=BudgetUsage(tool_calls=49),
    )
    root = ObservabilityRoot(tmp_path / "observability")
    runtime.projector = SceneProjector(root=root, artifacts=artifacts, heads=heads)
    dispatched: list[str] = []

    async def execute(_context) -> None:
        dispatched.append("executor")
        raise AssertionError("the complete envelope must reject before dispatch")

    result = await scheduler.dispatch_one(
        definition.coordinate,
        executors={definition.work_id: execute},
    )

    assert result.after_state == "blocked"
    assert dispatched == []
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["exhausted_dimensions"] == ["tool_calls"]
    assert evidence["admission"] == [
        {
            "dimension": "tool_calls",
            "requested": 3_587,
            "available": 3_151,
        }
    ]
    scene_scope_id = runtime.projector.safe_scope_id(definition.coordinate.scope_id)
    coordinate = CoordinateScene.model_validate_json(
        root.coordinate_json_path(
            scene_scope_id,
            definition.coordinate.coordinate_key,
        ).read_bytes()
    )
    assert coordinate.budget_exhaustion is not None
    assert coordinate.budget_exhaustion.operation_not_started is True
    assert coordinate.budget_exhaustion.admission[0].dimension == "tool_calls"
    assert coordinate.budget_exhaustion.admission[0].requested == 3_587
    assert coordinate.budget_exhaustion.admission[0].available == 3_151
    assert (
        "Budget admission: tool_calls requested 3587, available 3151 (deficit 436)."
        in root.coordinate_markdown_path(
            scene_scope_id,
            definition.coordinate.coordinate_key,
        ).read_text()
    )


def test_settlement_overshoot_carries_no_pre_dispatch_admission_comparison() -> None:
    """A real operation overshoot is not falsely labelled as a reserve rejection."""

    ledger = LeaseBudgetLedger(Budget(tool_calls=10, wall_seconds=30))
    lease = ledger.reserve(
        lease_id="lease:settlement-overshoot",
        owner_id="operation:settlement-overshoot",
        requested=Budget(tool_calls=2),
        elapsed_wall_seconds=0,
    )

    with pytest.raises(BudgetExceeded) as captured:
        ledger.settle(lease.lease_id, BudgetUsage(tool_calls=3))

    assert captured.value.dimensions == ("tool_calls",)
    assert captured.value.requested is None
    assert captured.value.available is None


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
async def test_multiturn_agent_proposal_cannot_replace_scheduler_dispatch_authority(
    tmp_path: Path,
) -> None:
    """A child physical turn is diagnosed and settled instead of orphaning Work."""

    definition = structured_agent_work_definition(
        scope_id="job:agent-child-invocation-id",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One logical CandidateBuild may own bounded internal Agent turns.",
        timing_reason="Integration requires a committed Candidate closure.",
        output_contract_id="contract:environment-candidate.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/candidate",),
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

    async def proposal(context, _attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        output_ref = artifacts.put_json(
            artifact_id="candidate-from-child-turn",
            artifact_type="design.environment_candidate",
            value={"candidate": "complete"},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            observed_actual=BudgetUsage(llm_tokens=37, agent_turns=1),
            agent=AgentExecutionProvenance(
                invocation_id="child-physical-invocation",
                provider="openai-compatible",
                model="gpt-5.4-mini",
                profile_digest=sha256_digest(
                    canonical_json_bytes({"profile": "environment-engineer"})
                ),
                output_schema_digest=sha256_digest(
                    canonical_json_bytes({"schema": "candidate-completion"})
                ),
            ),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["blocked"]
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert report.issues[0].code == "agent_proposal_dispatch_binding_invalid"
    proposal_execution = artifacts.get_json(
        next(
            ref
            for ref in attempt.operation_run_refs
            if artifacts.get_json(ref, OperationRun).kind == "proposal"
        ),
        OperationRun,
    )
    assert proposal_execution.status == "terminal"
    execution = artifacts.get_json(proposal_execution.execution_ref, ProposalExecution)
    assert execution.invocation_id == proposal_execution.dispatch_id
    assert attempt.observed_actual.llm_tokens == 37


@pytest.mark.asyncio
async def test_scheduler_last_resort_settles_unhandled_active_operation(
    tmp_path: Path,
) -> None:
    """An executor exception cannot leave its already-dispatched operation running."""

    artifacts, definition, heads, runtime, scheduler = _setup(tmp_path)
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def execute(context) -> None:
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        leaf._start_proposal(definition, input_refs)  # noqa: SLF001 - true owner boundary
        raise RuntimeError("constructed post-dispatch framework failure")

    with pytest.raises(RuntimeError, match="constructed post-dispatch"):
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
    assert report.issues[0].code == "scheduler_executor_framework_error"
    assert all(
        artifacts.get_json(ref, OperationRun).status == "terminal"
        for ref in attempt.operation_run_refs
    )


@pytest.mark.asyncio
async def test_scheduler_last_resort_settles_dispatched_agent_without_fake_profile(
    tmp_path: Path,
) -> None:
    """A post-dispatch framework error keeps only its known Agent dispatch id."""

    definition = structured_agent_work_definition(
        scope_id="job:agent-last-resort",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One real Agent proposal must settle after a framework exception.",
        timing_reason="No dispatched Agent operation may remain a ghost running head.",
        output_contract_id="contract:agent-last-resort.v1",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_model_fallbacks=0,
        maximum_process_recoveries=0,
        maximum_total_repair_attempts=1,
    )
    artifacts, definition, heads, runtime, scheduler = _setup(
        tmp_path,
        definition=definition,
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=300),
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)

    async def execute(context) -> None:
        input_refs = tuple(
            dict.fromkeys((*context.external_input_refs, *context.parent_output_refs))
        )
        leaf._start_proposal(definition, input_refs)  # noqa: SLF001 - true dispatch fence
        raise RuntimeError("constructed Agent framework failure")

    with pytest.raises(RuntimeError, match="constructed Agent framework failure"):
        await scheduler.dispatch_one(
            definition.coordinate,
            executors={definition.work_id: execute},
        )

    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "failed"
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    proposal_run = next(
        artifacts.get_json(ref, OperationRun)
        for ref in attempt.operation_run_refs
        if artifacts.get_json(ref, OperationRun).kind == "proposal"
    )
    execution = artifacts.get_json(proposal_run.execution_ref, ProposalExecution)
    assert execution.status == "interrupted"
    assert execution.error_code == "scheduler_executor_framework_error"
    assert execution.invocation_id == proposal_run.dispatch_id
    assert execution.provider is None
    assert execution.model is None
    assert execution.profile_digest is None
    assert execution.output_schema_digest is None


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
    """Strictly shrinking downstream feedback earns one bounded bonus repair.

    This is the regression for the previous "repair target only exists in the
    graph" bug and the later Candidate r1 -> Integration -> Candidate r2 failure:
    Candidate's local validator marked the first repair ``resolved`` before
    Integration proved that two original blockers had only shrunk to one.  The
    failing Integration leaf cannot retry itself or mutate a candidate.  It
    emits exact safe routes; Scheduler grants the second correction only because
    the same causal issue set is a strict subset, then stale input fingerprints
    re-open only Integration after each new Candidate WorkCommit.
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
    # The second downstream result both shrinks the prior causal issue set and
    # discloses a new safe feedback digest. Both proofs refer to the same prior
    # RepairAction and must be persisted once.
    target = target.model_copy(
        update={
            "repair_policy": target.repair_policy.model_copy(
                update={"maximum_feedback_refresh_corrections": 1}
            )
        }
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
            Budget(llm_tokens=3_000, agent_turns=3, repair_attempts=2, wall_seconds=300)
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
    repair_issues: list[tuple[ValidationIssue, ...]] = []

    async def target_proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        target_turns.append(attempt.ordinal)
        if attempt.ordinal in {2, 3}:
            brief = kernel.agent_correction_brief(context, definition=target)
            assert brief is not None
            repair_issues.append(brief.issues)
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
        if attempt.ordinal in {1, 2}:
            issues = [
                ValidationIssue(
                    code="runtime_protocol_rejects_candidate",
                    path=("runtime", "handshake"),
                    violated_condition="The isolated runtime protocol rejected this candidate.",
                    expected_category="candidate source satisfying the runtime protocol",
                    remediation="Repair the Candidate runtime handshake implementation.",
                )
            ]
            if attempt.ordinal == 1:
                issues.append(
                    ValidationIssue(
                        code="runtime_launch_rejects_candidate",
                        path=("runtime", "launch"),
                        violated_condition="The isolated runtime could not launch this candidate.",
                        expected_category="candidate source satisfying the runtime launch contract",
                        remediation="Repair the Candidate runtime launch implementation.",
                    )
                )
            raise LeafValidationFailure(
                issues=tuple(issues),
                output_commitment=sha256_digest(
                    f"failed-real-integration-evidence:{attempt.ordinal}".encode()
                ),
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

    assert target_turns == [1, 2, 3]
    assert source_turns == [1, 2, 3]
    assert len(repair_issues) == 2
    assert repair_issues[0] == (
        ValidationIssue(
            code="causal_runtime_protocol_rejects_candidate",
            path=(
                "causal_feedback",
                "integration",
                "runtime_integration",
                "runtime",
                "handshake",
            ),
            violated_condition="The isolated runtime protocol rejected this candidate.",
            expected_category="candidate source satisfying the runtime protocol",
            remediation="Repair the Candidate runtime handshake implementation.",
        ),
        ValidationIssue(
            code="causal_runtime_launch_rejects_candidate",
            path=(
                "causal_feedback",
                "integration",
                "runtime_integration",
                "runtime",
                "launch",
            ),
            violated_condition="The isolated runtime could not launch this candidate.",
            expected_category="candidate source satisfying the runtime launch contract",
            remediation="Repair the Candidate runtime launch implementation.",
        ),
    )
    assert repair_issues[1] == (
        ValidationIssue(
            code="causal_runtime_protocol_rejects_candidate",
            path=(
                "causal_feedback",
                "integration",
                "runtime_integration",
                "runtime",
                "handshake",
            ),
            violated_condition="The isolated runtime protocol rejected this candidate.",
            expected_category="candidate source satisfying the runtime protocol",
            remediation="Repair the Candidate runtime handshake implementation.",
        ),
    )
    assert [item.before_state for item in results] == [
        "ready",
        "ready",
        "repair_ready",
        "stale",
        "repair_ready",
        "stale",
    ]
    assert [item.after_state for item in results] == [
        "committed",
        "blocked",
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
    assert action.repair_attempt_ordinal == 2
    assert any(
        ref.artifact_type == "control.parent_repair_route" for ref in action.causal_evidence_refs
    )
    assert any(ref.artifact_type == "control.repair_action" for ref in action.causal_evidence_refs)
    assert action.repair_seed_attempt_ref is not None
    seed_attempt = artifacts.get_json(action.repair_seed_attempt_ref, WorkAttempt)
    assert seed_attempt.status == "succeeded"
    assert action.repair_seed_output_refs == seed_attempt.output_refs
    assert [entry.outcome for entry in runtime.repairs.entries] == ["resolved", "resolved"]


@pytest.mark.asyncio
async def test_frozen_recovery_executes_an_authorized_parent_repair_before_returning(
    tmp_path: Path,
) -> None:
    """A frozen Release-like retry may backjump to its committed Candidate owner.

    This covers the real r9 incident: the downstream gate is the selected
    frozen suffix, so its failed result is initially ``blocked``.  Its exact
    Scheduler route authorizes a Candidate-local correction, which must run
    before the runner decides that the frozen recovery is terminal.  An
    unrelated protected prerequisite would still fail the normal protection
    guard; only this graph-declared causal route opens the mutable cone.
    """

    artifacts, _definition, heads, _runtime, _scheduler = _setup(tmp_path)
    scope_id = "job:frozen-causal-recovery"
    candidate = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="candidate",
        artifact_slot="candidate_source",
        dependency_coordinates=(),
        claim_id="build.candidate.completes",
        claim="The mutable Candidate source completes its local contract.",
        timing_reason="A downstream gate can request one bounded Candidate correction.",
        output_contract_id="contract:frozen-causal-candidate.v1",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/candidate",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_total_repair_attempts=1,
    )
    release_base = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="integration",
        stage="release_gate",
        artifact_slot="release_gate_report",
        dependency_coordinates=(candidate.coordinate,),
        claim_id="judge.release.passes",
        claim="The current Candidate passes the selected downstream gate.",
        timing_reason="The gate supplies causal evidence for Candidate repair.",
        effect="block_release",
        success_maturity="release_gate_passed",
    )
    release = release_base.model_copy(
        update={
            "repair_target_coordinates": (candidate.coordinate,),
            "repair_policy": release_base.repair_policy.model_copy(
                update={
                    "maximum_automatic_backjump": 1,
                    "maximum_total_repair_attempts": 1,
                }
            ),
            "allowed_mutation_roots": ("/release",),
        }
    )
    graph = GenerationWorkGraph.compile((candidate, release), mode="diagnostic")
    root_ref = artifacts.put_json(
        artifact_id="context:frozen-causal-recovery",
        artifact_type="control.generation_context",
        value={"context": "frozen-causal-recovery"},
    )
    manifest = graph.manifest(
        topology_id="topology:frozen-causal-recovery",
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
            Budget(llm_tokens=2_000, agent_turns=2, repair_attempts=1, wall_seconds=300)
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
    candidate_turns: list[int] = []
    release_turns: list[int] = []
    correction_issues: list[tuple[ValidationIssue, ...]] = []

    async def candidate_proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        candidate_turns.append(attempt.ordinal)
        if attempt.ordinal == 2:
            brief = kernel.agent_correction_brief(context, definition=candidate)
            assert brief is not None
            correction_issues.append(brief.issues)
        output_ref = artifacts.put_json(
            artifact_id=f"candidate:frozen-causal-recovery:{attempt.ordinal}",
            artifact_type="design.world_architecture_source",
            value={"candidate_revision": attempt.ordinal},
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            agent=AgentExecutionProvenance(
                invocation_id=dispatch_id,
                provider="test-provider",
                model="test-model",
                profile_digest=sha256_digest(canonical_json_bytes({"profile": "engineer"})),
                output_schema_digest=sha256_digest(
                    canonical_json_bytes({"schema": "candidate"})
                ),
            ),
        )

    async def release_proposal(context, attempt: WorkAttempt, _dispatch_id: str) -> LeafProposal:
        release_turns.append(attempt.ordinal)
        if attempt.ordinal == 1:
            raise LeafValidationFailure(
                issues=(
                    ValidationIssue(
                        code="release_rejects_candidate",
                        path=("behavior",),
                        violated_condition="The downstream release gate rejected this Candidate.",
                        expected_category="Candidate source that passes the release gate",
                        remediation="Repair the Candidate behavior required by the gate.",
                    ),
                ),
                output_commitment=sha256_digest(b"frozen-causal-release-failure"),
                category="release_behavior",
                parent_repair_target=candidate.coordinate,
            )
        output_ref = artifacts.put_json(
            artifact_id="release:frozen-causal-recovery",
            artifact_type="release.final_telemetry_summary",
            value={"candidate_commit": context.parent_commit_refs[0].revision_id},
            dependencies=context.parent_output_refs,
        )
        return LeafProposal(output_refs=(output_ref,), subject_refs=(output_ref,))

    async def execute_candidate(context) -> None:
        await kernel.execute(context, definition=candidate, proposal_runner=candidate_proposal)

    async def execute_release(context) -> None:
        await kernel.execute(context, definition=release, proposal_runner=release_proposal)

    # This is the pre-existing committed frozen prefix.  The recovery must not
    # redispatch it until the downstream gate gives a valid causal route.
    initial = await scheduler.dispatch_one(
        candidate.coordinate,
        executors={candidate.work_id: execute_candidate, release.work_id: execute_release},
    )
    assert initial.after_state == "committed"

    runner = object.__new__(DirectWorkRunner)
    runner.artifacts = artifacts
    runner.heads = heads
    runner.maximum_concurrency = 1
    protected = frozenset({candidate.coordinate.coordinate_key})
    snapshot = await runner._run_graph(  # noqa: SLF001 - frozen recovery boundary
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        runtime=runtime,
        executors={candidate.work_id: execute_candidate, release.work_id: execute_release},
        protected_coordinate_keys=protected,
        frozen_recovery_protection=runner._frozen_recovery_protection(
            graph=graph,
            coordinate=release.coordinate,
            protected_coordinate_keys=protected,
        ),
    )

    assert candidate_turns == [1, 2]
    assert release_turns == [1, 2]
    assert correction_issues == [
        (
            ValidationIssue(
                code="causal_release_rejects_candidate",
                path=("causal_feedback", "integration", "release_gate", "behavior"),
                violated_condition="The downstream release gate rejected this Candidate.",
                expected_category="Candidate source that passes the release gate",
                remediation="Repair the Candidate behavior required by the gate.",
            ),
        ),
    ]
    assert all(item.state == "committed" for item in snapshot.work)
    repaired_candidate = heads.read_head(candidate.coordinate)
    repaired_release = heads.read_head(release.coordinate)
    assert repaired_candidate is not None and repaired_candidate.status == "committed"
    assert repaired_release is not None and repaired_release.status == "committed"


def test_verifier_group_leases_restore_a_full_turn_per_batch() -> None:
    """Direct runner must size the verifier group so each batch keeps a full turn.

    ``_verifier_intent_group`` splits the group token and wall leases evenly
    across its batches. A high-``reasoning_challenger`` batch is one real turn
    that genuinely spends the per-turn envelope (~49-56k tokens, and observed
    ~456s of continuous provider progress). The frozen graph defaults (48_000
    tokens / 900s) split below that floor for any multi-batch plan, turning a
    clean judge turn into a fatal ``budget_exhausted`` settle overshoot on the
    first attempt. The runner therefore scales both leases by the batch count so
    the even split restores the full per-turn envelope.
    """

    runner = object.__new__(DirectWorkRunner)
    runner.structured_turn_token_limit = 5_000_000
    runner.structured_turn_wall_seconds = 28_800.0

    budget = Budget(llm_tokens=100_000_000, wall_seconds=1_000_000.0)

    for batch_count in (1, 2, 4):
        group_tokens = runner._verifier_group_tokens(  # noqa: SLF001
            budget, batch_count=batch_count
        )
        group_wall = runner._verifier_group_wall(  # noqa: SLF001
            budget, batch_count=batch_count
        )
        # The graph splits the group lease evenly; every batch must recover a
        # full per-turn envelope rather than a starved fraction.
        assert group_tokens // batch_count == runner.structured_turn_token_limit
        assert group_wall / batch_count == pytest.approx(runner.structured_turn_wall_seconds)
        # Both leases stay strictly above the frozen graph defaults that caused
        # the fatal per-batch overshoots for any real multi-batch plan.
        if batch_count > 1:
            assert group_tokens > 48_000
            assert group_wall > 900.0


def test_verifier_group_leases_are_clamped_to_remaining_scope_budget() -> None:
    """A group lease can never exceed the scope's remaining budget."""

    runner = object.__new__(DirectWorkRunner)
    runner.structured_turn_token_limit = 5_000_000
    runner.structured_turn_wall_seconds = 28_800.0

    scarce = Budget(llm_tokens=10_000, wall_seconds=120.0)

    assert runner._verifier_group_tokens(scarce, batch_count=4) == 10_000  # noqa: SLF001
    assert runner._verifier_group_wall(scarce, batch_count=4) == pytest.approx(120.0)  # noqa: SLF001

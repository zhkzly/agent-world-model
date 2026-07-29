from __future__ import annotations

import json
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from v3_fixture import candidate_files, portable_counter_contracts, write_candidate_project

import agent_world.builder.leaf as builder_leaf_module
from agent_world.artifact_store import ArtifactStore
from agent_world.builder import (
    BuilderError,
    BuilderLeaf,
    BuildInvocationSummary,
    CandidateCompletion,
    CandidateFileDeclaration,
    CandidatePublicSelfCheckDeclaration,
    CandidateRuntimeDeclaration,
    CandidateTaskMaterializerDeclaration,
    CandidateWorkspaceError,
    CandidateWorkspaceValidator,
    EnvironmentBuilder,
    ImplementationContract,
    ImplementationPlan,
    normalize_candidate_completion_output,
)
from agent_world.builder.models import (
    RepairDisclosure,
    TaskMaterializerContract,
    ToolBindingRequirement,
)
from agent_world.contracts import (
    Budget,
    EnvironmentCandidate,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    PublicSelfCheckDescriptor,
    ReleaseProfile,
    RuntimeLaunch,
    TaskMaterializerDescriptor,
    sha256_digest,
)
from agent_world.control import (
    ArtifactSlotContract,
    GenerationWorkGraph,
    LeaseBudgetLedger,
    OperationBudget,
    ProposalPolicy,
    RepairPolicy,
    SchedulerLeafExecutor,
    ValidationDiagnostic,
    ValidationPolicy,
    ValidationReport,
    WorkAttempt,
    WorkControlRuntime,
    WorkControlStore,
    WorkCoordinate,
    WorkDefinition,
    WorkScheduler,
    deterministic_boundary_work_definition,
)
from agent_world.control.continuation_store import NodeContinuationRecord, NodeContinuationStore
from agent_world.control.work import RepairAction, work_input_fingerprint
from agent_world.control.work_scheduler import WorkExecutionContext
from agent_world.invocation import InvocationSession, InvocationStatus


def _completed_values() -> dict[str, object]:
    return {
        "status": "completed",
        "project_root": "candidate",
        "root_project_mode": "virtual-read-only-source-tree",
        "dependency_install_mode": "offline-wheel-only",
        "runtime": CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "environment.runtime"),
            entry_path="src/environment/runtime.py",
        ),
        "task_materializer": CandidateTaskMaterializerDeclaration(
            entrypoint="environment.tasks:materialize",
            entry_path="src/environment/tasks.py",
        ),
        "public_self_check": CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "environment.public_check"),
            entry_path="src/environment/public_check.py",
        ),
        "public_test_paths": ("tests/test_public.py",),
        "files": (
            CandidateFileDeclaration(path="LICENSE", role="license"),
            CandidateFileDeclaration(path="pyproject.toml", role="configuration"),
            CandidateFileDeclaration(path="uv.lock", role="dependency_lock"),
            CandidateFileDeclaration(path="src/environment/runtime.py", role="runtime"),
            CandidateFileDeclaration(
                path="src/environment/tasks.py",
                role="task_materializer",
            ),
            CandidateFileDeclaration(
                path="src/environment/public_check.py",
                role="public_verifier",
            ),
            CandidateFileDeclaration(path="tests/test_public.py", role="public_test"),
        ),
    }


def test_completed_candidate_requires_materializer_v3_and_supply_chain_echo() -> None:
    completion = CandidateCompletion.model_validate(_completed_values())

    assert completion.task_materializer is not None
    assert completion.task_materializer.protocol == "python-callable-v3"
    assert completion.root_project_mode == "virtual-read-only-source-tree"
    assert completion.dependency_install_mode == "offline-wheel-only"


def test_builder_repair_prompt_preserves_unrelated_regression_obligations() -> None:
    prompt = EnvironmentBuilder._repair_prompt(4, "repair-disclosure-4.json")  # noqa: SLF001
    normalized = " ".join(prompt.split())

    assert "unrelated to the disclosed Finding as regression obligations" in normalized
    assert "do not delete, relax, invert, or replace" in normalized
    assert "Add or strengthen a focused regression test" in normalized


def test_runtime_contract_uses_declared_schema_and_repair_feedback_allows_domain_task_id() -> None:
    runtime_contract = EnvironmentBuilder._runtime_wire_contract()  # noqa: SLF001

    rendered_contract = runtime_contract.model_dump_json()
    assert "evaluator_goal" not in rendered_contract
    assert "sealed_case" not in rendered_contract
    assert "verifier_ir" not in rendered_contract
    handshake = next(item for item in runtime_contract.operations if item.operation == "handshake")
    assert "JSON string array" in " ".join(handshake.result_requirements)
    assert '"handshake","reset","invoke","snapshot","close"' in " ".join(
        handshake.result_requirements
    )
    reset = next(item for item in runtime_contract.operations if item.operation == "reset")
    assert "only the reset payload fields declared" in " ".join(reset.result_requirements)
    digest_requirement = (
        "state_digest must be exactly `sha256:` followed by 64 lowercase hexadecimal characters"
    )
    for operation in ("reset", "invoke", "snapshot"):
        runtime_operation = next(
            item for item in runtime_contract.operations if item.operation == operation
        )
        assert digest_requirement in " ".join(runtime_operation.result_requirements)

    initial_prompt = EnvironmentBuilder._initial_prompt(  # noqa: SLF001
        SimpleNamespace(design_id="design:wire-format", revision=1),
        has_implementation_plan=True,
    )
    assert (
        "literal `sha256:` prefix followed by 64 lowercase hexadecimal characters" in initial_prompt
    )
    skill = Path("agent_world/agent_assets/skills/engineer-environment-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "`state_digest` must be exactly `sha256:` followed by 64 lowercase hexadecimal" in skill

    disclosure = RepairDisclosure(
        disclosure_id="repair-disclosure:domain-task-id",
        category="runtime_protocol",
        severity="high",
        disclosure="repair",
        summary="WorldSpec tool schema requires the domain task_id property.",
        suggested_repair="Keep the domain task_id tool argument intact.",
    )
    assert "task_id" in disclosure.summary

    with pytest.raises(ValidationError, match="private evaluation vocabulary"):
        RepairDisclosure(
            disclosure_id="repair-disclosure:sealed-case",
            category="runtime_protocol",
            severity="high",
            disclosure="repair",
            summary="The sealed_case must not cross the Runtime boundary.",
        )

    with pytest.raises(ValidationError, match="private evaluation vocabulary"):
        RepairDisclosure(
            disclosure_id="repair-disclosure:evaluation-binding",
            category="runtime_protocol",
            severity="high",
            disclosure="repair",
            summary="The evaluator goal must not cross the Runtime boundary.",
        )


def test_builder_surfaces_retired_contract_projection_as_safe_preflight(tmp_path: Path) -> None:
    """An old frozen Builder projection must settle, not escape Scheduler dispatch.

    The raw artifact intentionally models a prior framework projection.  The
    real Artifact reader rejects it before any model invocation; Builder must
    turn that into one safe preflight diagnosis rather than silently normalizing
    the immutable payload or exposing the retired field name in feedback.
    """

    store = ArtifactStore(tmp_path / "artifacts")
    control_artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("design.",),
    )
    builder_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    design = portable_counter_contracts(store).design
    design_ref = control_artifacts.put_json(
        artifact_id="design:retired-builder-projection",
        artifact_type="design.environment_design",
        value=design,
    )
    current_contract = ImplementationContract(
        contract_id="implementation-contract:retired-builder-projection",
        design_ref=design_ref,
        world_spec_hash=design.world_spec.content_digest(),
        state_schema_hash=design.world_spec.state.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        runtime=EnvironmentBuilder._runtime_wire_contract(),  # noqa: SLF001 - frozen projection
        tools=tuple(
            ToolBindingRequirement(
                tool_id=tool.surface.tool_id,
                tool_contract_hash=tool.content_digest(),
            )
            for tool in design.world_spec.tools
        ),
        task_materializer=TaskMaterializerContract(
            task_types=tuple(item.task_type for item in design.curriculum.task_types),
            minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
            minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        ),
    )
    retired_payload = current_contract.model_dump(mode="json")
    retired_payload["runtime"]["retired_framework_projection"] = ("old",)
    retired_contract_ref = builder_artifacts.put_json(
        artifact_id=current_contract.contract_id,
        artifact_type="build.implementation_contract",
        value=retired_payload,
        dependencies=(design_ref,),
    )
    plan = ImplementationPlan(
        plan_id="implementation-plan:retired-builder-projection",
        design_ref=design_ref,
        implementation_contract_ref=retired_contract_ref,
        world_spec_hash=design.world_spec.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        implementation_strategy="Use the frozen framework-owned codegen projection.",
    )
    plan_ref = builder_artifacts.put_json(
        artifact_id=plan.plan_id,
        artifact_type="build.implementation_plan",
        value=plan,
        dependencies=(design_ref, retired_contract_ref),
    )
    builder = EnvironmentBuilder(
        artifact_store=builder_artifacts,
        invocation_backend=SimpleNamespace(),
        profile_provider=SimpleNamespace(),
    )

    with pytest.raises(BuilderError) as raised:
        builder._implementation_contract_for_build(  # noqa: SLF001 - real frozen input boundary
            design=design,
            design_ref=design_ref,
            implementation_plan=plan,
            implementation_plan_ref=plan_ref,
        )

    assert raised.value.stage == "implementation_contract"
    assert "regenerate BuildImplementationPlan" in str(raised.value)
    assert "retired_framework_projection" not in str(raised.value)
    assert BuilderLeaf._preflight_expected_category(  # noqa: SLF001 - feedback contract
        raised.value.stage
    ) == (
        "a current framework-owned ImplementationContract compiled by "
        "BuildImplementationPlan from the exact frozen EnvironmentDesign"
    )


def test_builder_leaf_projects_safe_source_phase_through_framework_diagnostic() -> None:
    try:
        try:
            raise BuilderError(
                "agent.output",
                "candidate completion violates the framework schema",
            )
        except BuilderError as source:
            raise BuilderError(
                "framework.diagnostic",
                "Builder reached a non-actionable framework diagnostic",
            ) from source
    except BuilderError as wrapped:
        category = BuilderLeaf._failure_category(wrapped)  # noqa: SLF001 - feedback contract
        expected = BuilderLeaf._framework_diagnostic_expected_category(  # noqa: SLF001
            wrapped
        )

    assert "BuilderError[framework.diagnostic]" in category
    assert "source[agent.output]" in category
    assert expected == "a typed remediation for Builder phase agent.output"


def test_builder_quota_terminal_has_safe_nonretryable_diagnostic() -> None:
    diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001 - feedback contract
        BuilderError(
            "agent",
            "TOP_SECRET_PROVIDER_TRANSCRIPT",
            backend_error_code="turn_failed_quota_exhausted",
            backend_retryable=True,
        )
    )

    issue = diagnostic.issues[0]
    assert diagnostic.validation_phase == "agent_backend"
    assert issue.issue_code == "agent_backend_turn_failed_quota_exhausted@provider"
    assert issue.retryable is False
    assert issue.message == "the configured Provider reported that its quota is exhausted"
    assert issue.expected_category == (
        "restored Provider quota or an explicitly authorized model/provider route; "
        "do not issue a model correction or blind retry"
    )
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in diagnostic.feedback


def test_builder_preserves_safe_codex_stream_disconnect_feedback() -> None:
    diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001 - feedback contract
        BuilderError(
            "agent",
            "TOP_SECRET_PROVIDER_TRANSCRIPT",
            backend_error_code="turn_failed_provider_unavailable",
            backend_retryable=True,
            backend_error_details={
                "terminal_error_shape": "object",
                "codex_error_info": "transport:response_stream_disconnected",
                "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
            },
        )
    )

    issue = diagnostic.issues[0]
    assert diagnostic.validation_phase == "agent_backend"
    assert issue.issue_code == "agent_backend_turn_failed_provider_unavailable@provider"
    assert issue.retryable is True
    assert issue.message == (
        "the Codex Provider response stream disconnected before a terminal response"
    )
    assert issue.expected_category == (
        "a recovered Codex Provider route followed by an authorized bounded infrastructure "
        "retry; do not issue a model correction"
    )
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in diagnostic.feedback


@pytest.mark.asyncio
async def test_builder_leaf_scheduler_preserves_quota_terminal_without_repair(
    tmp_path: Path,
) -> None:
    """Exercise the real BuilderLeaf -> Scheduler feedback boundary with a Provider terminal.

    The preceding live Build produced this exact terminal category but cannot
    be safely retried while quota remains exhausted.  This constructed frozen
    Design closure proves the post-fix Scheduler behavior: one Build operation
    becomes a non-retryable typed report, preserves Agent provenance, and does
    not fabricate an Agent correction or a second call.
    """

    budget = Budget(
        llm_tokens=1_000,
        agent_turns=1,
        build_seconds=90,
        repair_attempts=1,
        wall_seconds=120,
    )
    release_profile = ReleaseProfile(profile_id="release:builder-quota")
    permissions = PermissionScope()
    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    request = EnvironmentRequest(
        request_id="request:builder-quota",
        need="Compile one isolated Builder feedback boundary.",
        permissions=permissions,
        budget=budget,
        release_profile=release_profile,
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="job:builder-quota",
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    generation = GenerationContext(
        context_id="context:builder-quota",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=generation.context_id,
        artifact_type="control.generation_context",
        value=generation,
        dependencies=generation.root_refs,
    )
    design = portable_counter_contracts(store).design
    design_ref = artifacts.put_json(
        artifact_id="design:builder-quota",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(context_ref,),
    )
    builder_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    implementation_contract = ImplementationContract(
        contract_id="implementation-contract:builder-quota",
        design_ref=design_ref,
        world_spec_hash=design.world_spec.content_digest(),
        state_schema_hash=design.world_spec.state.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        runtime=EnvironmentBuilder._runtime_wire_contract(),  # noqa: SLF001
        tools=tuple(
            ToolBindingRequirement(
                tool_id=tool.surface.tool_id,
                tool_contract_hash=tool.content_digest(),
            )
            for tool in design.world_spec.tools
        ),
        task_materializer=TaskMaterializerContract(
            task_types=tuple(item.task_type for item in design.curriculum.task_types),
            minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
            minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        ),
    )
    implementation_contract_ref = builder_artifacts.put_json(
        artifact_id=implementation_contract.contract_id,
        artifact_type="build.implementation_contract",
        value=implementation_contract,
        dependencies=(design_ref,),
    )
    implementation_plan = ImplementationPlan(
        plan_id="implementation-plan:builder-quota",
        design_ref=design_ref,
        implementation_contract_ref=implementation_contract_ref,
        world_spec_hash=design.world_spec.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        implementation_strategy=(
            "Map the one counter operation into Runtime and Materializer modules."
        ),
    )
    implementation_plan_ref = builder_artifacts.put_json(
        artifact_id=implementation_plan.plan_id,
        artifact_type="build.implementation_plan",
        value=implementation_plan,
        dependencies=(design_ref, implementation_contract_ref),
    )

    modeling = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
        dependency_coordinates=(),
        claim_id="design.modeling.passed",
        claim="One frozen EnvironmentDesign is available to Builder.",
        timing_reason="Builder may consume only the committed Modeling closure.",
        effect="block_compile",
        success_maturity="design_valid",
    ).model_copy(
        update={
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:environment-design",
                    direction="output",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            )
        }
    )
    planning = deterministic_boundary_work_definition(
        scope_id=job.job_id,
        component="build",
        stage="implementation_plan",
        artifact_slot="implementation_plan",
        dependency_coordinates=(modeling.coordinate,),
        claim_id="build.implementation.plan.ready",
        claim="One advisory implementation plan is available to CandidateBuild.",
        timing_reason="CandidateBuild consumes one exact planning closure.",
        effect="block_compile",
        success_maturity="implementation_planned",
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:environment-design",
                    direction="input",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": tuple(
                ArtifactSlotContract(
                    slot_id=f"output:{artifact_type}",
                    direction="output",
                    artifact_types=(artifact_type,),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="build",
                )
                for artifact_type in ("build.implementation_contract", "build.implementation_plan")
            ),
        }
    )
    build = WorkDefinition(
        work_id="work:builder-quota",
        coordinate=WorkCoordinate(
            scope_id=job.job_id,
            component="build",
            stage="candidate_build",
            artifact_slot="environment_candidate",
        ),
        claim="The frozen Design is implemented as one executable Candidate.",
        timing_reason="Integration can consume only a committed Builder closure.",
        dependency_coordinates=(modeling.coordinate, planning.coordinate),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-contract",
                direction="input",
                artifact_types=("build.implementation_contract",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-plan",
                direction="input",
                artifact_types=("build.implementation_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            )
            for artifact_type in (
                "build.source_workspace_snapshot",
                "build.implementation_lineage",
                "build.candidate_manifest",
                "build.record",
                "build.environment_candidate",
            )
        ),
        proposal_policy=ProposalPolicy(
            policy_id="proposal:builder-quota",
            executor="agent",
            operation="build.environment_candidate",
            budget=OperationBudget(
                wall_seconds=90,
                first_progress_seconds=30,
                first_write_seconds=60,
                llm_tokens=1_000,
                agent_turns=1,
                build_seconds=90,
            ),
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:environment-candidate.v3",
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:builder-quota",
            validator_id="validator:builder-quota",
            validator_revision_id="framework.validator.builder-quota.v1",
            validation_phase="candidate_build",
            frontier_ordinal=100,
            claim_id="build.candidate.valid",
            effect="block_integration",
            budget=OperationBudget(wall_seconds=30),
        ),
        repair_policy=RepairPolicy(
            policy_id="repair:builder-quota",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=1,
            maximum_process_recoveries=0,
            maximum_total_repair_attempts=1,
        ),
        required_claim_id="build.candidate.valid",
        success_maturity="candidate_built",
    )
    graph = GenerationWorkGraph.compile((modeling, planning, build), mode="diagnostic")
    manifest = graph.manifest(
        topology_id="topology:builder-quota",
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
        budget=LeaseBudgetLedger(budget),
    )
    runtime.execute_deterministic_boundary(
        definition=modeling,
        input_refs=(context_ref,),
        subject_ref=design_ref,
        output_refs=(design_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=planning,
        input_refs=(context_ref, design_ref),
        subject_ref=implementation_plan_ref,
        output_refs=(implementation_contract_ref, implementation_plan_ref),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )

    local_excerpt = "DIAGNOSTIC_EXCERPT_MUST_STAY_LOCAL"

    class QuotaExhaustedBuilder:
        calls = 0
        request_kwargs: dict[str, object] | None = None

        async def build_once(self, **kwargs):
            self.calls += 1
            self.request_kwargs = dict(kwargs)
            profile = SimpleNamespace(
                model_provider="test-provider",
                model="test-builder-model",
                profile_hash="a" * 64,
            )
            state = SimpleNamespace(profile=profile, invocation_session=None)
            raise BuilderError(
                "agent",
                "TOP_SECRET_PROVIDER_TRANSCRIPT",
                state=state,
                invocation=BuildInvocationSummary(
                    invocation_id=kwargs["proposal_invocation_id"],
                    status=InvocationStatus.FAILED,
                    duration_ms=12,
                    usage=None,
                    backend_version="test-backend",
                    total_tokens=0,
                    unknown_token_upper_bounds=(1_000,),
                ),
                backend_error_code="turn_failed_quota_exhausted",
                backend_retryable=True,
                backend_error_details={
                    "terminal_error_shape": "object",
                    "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
                },
                diagnostic_terminal_excerpt=local_excerpt,
            )

    builder = QuotaExhaustedBuilder()
    local_terminal_feedback = []
    leaf = BuilderLeaf(
        builder=builder,  # type: ignore[arg-type] - constructed terminal boundary
        workspace_root=tmp_path / "builder-workspace",
        run_id="run:builder-quota",
        kernel=SchedulerLeafExecutor(
            runtime=runtime,
            local_terminal_diagnostic_sink=local_terminal_feedback.append,
        ),
    )

    async def execute(context) -> None:
        await leaf.execute(context, definition=build)

    results = await scheduler.run_until_stalled(executors={build.work_id: execute})

    assert [result.after_state for result in results] == ["blocked"]
    assert builder.calls == 1
    assert builder.request_kwargs is not None
    assert builder.request_kwargs["diagnostic_capture_terminal_excerpt"] is True
    assert len(local_terminal_feedback) == 1
    feedback = local_terminal_feedback[0]
    assert feedback.code == "turn_failed_quota_exhausted"
    assert feedback.terminal_details == {"terminal_error_shape": "object"}
    assert feedback.excerpt == local_excerpt
    head = heads.read_head(build.coordinate)
    assert head is not None and head.status == "failed" and head.repair_action_ref is None
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    issue = report.issues[0]
    assert report.status == "error"
    assert report.diagnostic_quality == "informative"
    assert report.infrastructure_retryable is False
    assert issue.code == "turn_failed_quota_exhausted"
    assert issue.path == ("operation",)
    assert (
        issue.violated_condition == "the configured Provider reported that its quota is exhausted"
    )
    assert issue.expected_category == (
        "restored Provider quota or an explicitly authorized model/provider route; "
        "do not issue a model correction or blind retry"
    )
    assert issue.remediation == (
        "Restore quota or select an explicitly authorized Provider/model route; do not replay "
        "this physical attempt."
    )
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in report.model_dump_json()
    assert local_excerpt not in report.model_dump_json()
    evidence = artifacts.get_json(report.evidence_refs[0])
    assert evidence["terminal_details"] == {"terminal_error_shape": "object"}
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in json.dumps(evidence)
    assert local_excerpt not in json.dumps(evidence)


@pytest.mark.asyncio
async def test_builder_leaf_resumes_only_the_private_output_limited_session(tmp_path: Path) -> None:
    """Exercise the Builder adapter after the generic Scheduler proof.

    ``test_closed_output_ceiling_creates_one_private_session_continuation_attempt``
    proves the normal Scheduler authorization and durable private checkpoint.
    This constructed boundary proves that CandidateBuild consumes that exact
    checkpoint with ``resume_output_limited_build`` rather than starting a
    fresh Builder turn or feeding Provider text back to the model.
    """

    budget = Budget(
        llm_tokens=250_000,
        agent_turns=2,
        build_seconds=1_440,
        repair_attempts=0,
        wall_seconds=1_440,
    )
    permissions = PermissionScope()
    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    builder_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    request = EnvironmentRequest(
        request_id="request:builder-continuation",
        need="Exercise one private Builder session continuation.",
        permissions=permissions,
        budget=budget,
        release_profile=ReleaseProfile(profile_id="release:builder-continuation"),
    )
    request_ref = artifacts.put_json(
        artifact_id=request.request_id,
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="job:builder-continuation",
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=request.release_profile,
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    generation = GenerationContext(
        context_id="context:builder-continuation",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=request.release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=generation.context_id,
        artifact_type="control.generation_context",
        value=generation,
        dependencies=generation.root_refs,
    )
    design = portable_counter_contracts(store).design
    design_ref = artifacts.put_json(
        artifact_id="design:builder-continuation",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(context_ref,),
    )
    contract = ImplementationContract(
        contract_id="implementation-contract:builder-continuation",
        design_ref=design_ref,
        world_spec_hash=design.world_spec.content_digest(),
        state_schema_hash=design.world_spec.state.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        runtime=EnvironmentBuilder._runtime_wire_contract(),  # noqa: SLF001
        tools=tuple(
            ToolBindingRequirement(
                tool_id=tool.surface.tool_id,
                tool_contract_hash=tool.content_digest(),
            )
            for tool in design.world_spec.tools
        ),
        task_materializer=TaskMaterializerContract(
            task_types=tuple(item.task_type for item in design.curriculum.task_types),
            minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
            minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        ),
    )
    contract_ref = builder_artifacts.put_json(
        artifact_id=contract.contract_id,
        artifact_type="build.implementation_contract",
        value=contract,
        dependencies=(design_ref,),
    )
    plan = ImplementationPlan(
        plan_id="implementation-plan:builder-continuation",
        design_ref=design_ref,
        implementation_contract_ref=contract_ref,
        world_spec_hash=design.world_spec.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        implementation_strategy=(
            "Continue the exact frozen candidate implementation in its workspace."
        ),
    )
    plan_ref = builder_artifacts.put_json(
        artifact_id=plan.plan_id,
        artifact_type="build.implementation_plan",
        value=plan,
        dependencies=(design_ref, contract_ref),
    )
    definition = WorkDefinition(
        work_id="work:builder-continuation",
        coordinate=WorkCoordinate(
            scope_id=job.job_id,
            component="build",
            stage="candidate_build",
            artifact_slot="environment_candidate",
        ),
        claim="One logical Builder session may continue after a closed Provider output ceiling.",
        timing_reason="The same SDK thread and workspace preserve unfinished implementation work.",
        dependency_coordinates=(),
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            )
            for artifact_type in (
                "build.source_workspace_snapshot",
                "build.implementation_lineage",
                "build.candidate_manifest",
                "build.record",
                "build.environment_candidate",
            )
        ),
        proposal_policy=ProposalPolicy(
            policy_id="proposal:builder-continuation",
            executor="agent",
            operation="build.environment_candidate",
            budget=OperationBudget(
                wall_seconds=720,
                first_progress_seconds=120,
                first_write_seconds=300,
                llm_tokens=125_000,
                agent_turns=1,
                build_seconds=720,
            ),
            session_token_limit=250_000,
            session_wall_seconds=1_440,
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:environment-candidate.v3",
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:builder-continuation",
            validator_id="validator:builder-continuation",
            validator_revision_id="framework.validator.builder-continuation.v1",
            validation_phase="candidate_build",
            frontier_ordinal=100,
            claim_id="build.candidate.valid",
            effect="block_integration",
            budget=OperationBudget(wall_seconds=60),
        ),
        repair_policy=RepairPolicy(
            policy_id="repair:builder-continuation",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_session_continuations=1,
            maximum_process_recoveries=0,
            maximum_total_repair_attempts=0,
        ),
        required_claim_id="build.candidate.valid",
        allowed_mutation_roots=("/source", "/dependencies", "/runtime", "/materializer"),
        success_maturity="candidate_built",
    )
    report_ref = artifacts.put_json(
        artifact_id="validation-report:builder-continuation",
        artifact_type="control.validation_report",
        value={"closed": "output-limit"},
    )
    evaluation_ref = artifacts.put_json(
        artifact_id="feedback:builder-continuation",
        artifact_type="control.feedback_evaluation",
        value={"closed": "output-limit"},
        dependencies=(report_ref,),
    )
    execution_ref = artifacts.put_json(
        artifact_id="proposal-execution:builder-continuation",
        artifact_type="control.proposal_execution",
        value={"closed": "output-limit"},
    )
    all_inputs = (context_ref, design_ref, contract_ref, plan_ref)
    input_fingerprint = work_input_fingerprint(all_inputs)
    action = RepairAction(
        action_id="repair-action:builder-continuation",
        repair_policy_id=definition.repair_policy.policy_id,
        repair_epoch_digest=sha256_digest(b"builder-continuation"),
        definition_digest=definition.definition_digest,
        input_fingerprint=input_fingerprint,
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision="session_continuation",
        jump_distance=0,
        repair_attempt_ordinal=1,
        immutable_input_refs=all_inputs,
        allowed_mutation_roots=definition.allowed_mutation_roots,
        causal_evidence_refs=(report_ref, evaluation_ref),
        reason_code="provider_output_ceiling",
        repair_attempt_charge=0,
        authorized_at=datetime.now(UTC),
    )
    action_ref = artifacts.put_json(
        artifact_id=action.action_id,
        artifact_type="control.repair_action",
        value=action,
        dependencies=(report_ref, evaluation_ref, *all_inputs),
    )
    continuation_workspace_root = tmp_path / "continuation-workspace"
    agent_workspace = (
        continuation_workspace_root / "builder" / "attempt-initial" / ".agent-runtime" / "workspace"
    )
    agent_workspace.mkdir(parents=True)
    session = InvocationSession(
        thread_id="private-builder-thread",
        lineage_id="implementation:builder-continuation",
        workspace=agent_workspace.resolve(),
        profile_hash="a" * 64,
        codex_config_sha256="b" * 64,
    )
    record = NodeContinuationRecord.capture(
        work_id=definition.work_id,
        attempt_id="attempt:builder-initial",
        session=session,
        model="gpt-5.3-codex-spark",
        output_schema_digest=BuilderLeaf._candidate_schema_digest(),  # noqa: SLF001
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        input_fingerprint=input_fingerprint,
        previous_candidate=None,
        allowed_mutation_roots=definition.allowed_mutation_roots,
        source_report_ref=report_ref,
        source_evaluation_ref=evaluation_ref,
        repair_action_ref=action_ref,
        previous_execution_ref=execution_ref,
    )
    continuations = NodeContinuationStore(tmp_path / "continuations")
    continuations.save(record)
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(budget),
        continuations=continuations,
        continuation_workspace_root=continuation_workspace_root,
    )
    attempt_time = datetime.now(UTC)
    attempt = WorkAttempt(
        attempt_id="attempt:builder-continuation",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=2,
        parent_attempt_id=record.attempt_id,
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        input_refs=all_inputs,
        repair_action_ref=action_ref,
        continuation_commitment=record.record_commitment,
        # The prior fallback route remains effective across an authorized
        # output-ceiling continuation; the continuation action itself does
        # not name a second model change.
        model_override="gpt-5.3-codex-spark",
        scheduled_at=attempt_time,
        started_at=attempt_time,
    )
    output_refs = tuple(
        builder_artifacts.put_json(
            artifact_id=f"builder-continuation-output:{index}",
            artifact_type=artifact_type,
            value={"continued": artifact_type},
            dependencies=(plan_ref,),
        )
        for index, artifact_type in enumerate(
            (
                "build.source_workspace_snapshot",
                "build.implementation_lineage",
                "build.candidate_manifest",
                "build.record",
                "build.environment_candidate",
            )
        )
    )
    profile = SimpleNamespace(
        model_provider="openai",
        model="gpt-5.3-codex-spark",
        profile_hash="a" * 64,
    )
    success_state = SimpleNamespace(profile=profile, invocation_session=session)

    class ResumingBuilder:
        normal_calls = 0
        resume_kwargs: dict[str, object] | None = None

        async def build_once(self, **_kwargs):
            self.normal_calls += 1
            raise AssertionError("a session continuation must not start a fresh Builder workspace")

        async def resume_output_limited_build(self, **kwargs):
            self.resume_kwargs = dict(kwargs)
            return SimpleNamespace(
                state=success_state,
                source_snapshot_ref=output_refs[0],
                implementation_lineage_ref=output_refs[1],
                candidate_manifest_ref=output_refs[2],
                build_artifact_ref=output_refs[3],
                candidate_ref=output_refs[4],
                invocation=BuildInvocationSummary(
                    invocation_id=kwargs["proposal_invocation_id"],
                    status=InvocationStatus.COMPLETED,
                    duration_ms=12,
                    usage=None,
                    backend_version="constructed-boundary",
                    total_tokens=125_000,
                ),
            )

    builder = ResumingBuilder()
    leaf = BuilderLeaf(
        builder=builder,  # type: ignore[arg-type] - constructed adapter boundary
        workspace_root=continuation_workspace_root / "builder",
        run_id="run:builder-continuation",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    definition_ref = artifacts.put_json(
        artifact_id="work-definition:builder-continuation",
        artifact_type="control.work_definition",
        value=definition,
    )
    context = WorkExecutionContext(
        definition_ref=definition_ref,
        coordinate=definition.coordinate,
        graph_digest=sha256_digest(b"builder-continuation-graph"),
        external_input_refs=(context_ref,),
        parent_output_refs=(design_ref, contract_ref, plan_ref),
        repair_action_ref=action_ref,
    )

    proposal = await leaf._proposal(  # noqa: SLF001 - adapter boundary under test
        context,
        attempt,
        "dispatch:builder-continuation",
        definition=definition,
    )

    assert builder.normal_calls == 0
    assert builder.resume_kwargs is not None
    assert builder.resume_kwargs["workspace"] == agent_workspace.resolve()
    assert builder.resume_kwargs["session"] == session
    assert builder.resume_kwargs["session_token_limit"] == 250_000
    assert builder.resume_kwargs["session_wall_seconds"] == 1_440
    assert builder.resume_kwargs["attempt_ordinal"] == 2
    assert builder.resume_kwargs["model_override"] == "gpt-5.3-codex-spark"
    assert proposal.output_refs == output_refs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "model_override"),
    (
        ("infrastructure_retry", None),
        ("model_fallback", "gpt-5.3-codex-spark"),
    ),
)
async def test_builder_leaf_uses_fresh_session_for_authorized_transport_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
    model_override: str | None,
) -> None:
    """Transport recovery must start a fresh Builder turn, never a correction.

    ``RepairAction`` owns authorization and route choice.  CandidateBuild owns
    only the new physical session, so an infrastructure retry or model fallback
    must call ``build_once`` with the frozen input closure and no prior-session
    or correction material.
    """

    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    build_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    budget = Budget(
        llm_tokens=1_000,
        agent_turns=1,
        build_seconds=60,
        repair_attempts=1,
        wall_seconds=120,
    )
    definition = deterministic_boundary_work_definition(
        scope_id=f"job:builder-{decision}",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One frozen Candidate may recover one classified transport route.",
        timing_reason="A retry must retain only immutable inputs.",
        effect="block_integration",
        success_maturity="candidate_built",
    )
    context_ref = artifacts.put_json(
        artifact_id=f"context:builder-{decision}",
        artifact_type="control.generation_context",
        value={"case": decision},
    )
    design = portable_counter_contracts(store).design
    design_ref = artifacts.put_json(
        artifact_id=f"design:builder-{decision}",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(context_ref,),
    )
    implementation_plan_ref = build_artifacts.put_json(
        artifact_id=f"implementation-plan:builder-{decision}",
        artifact_type="build.implementation_plan",
        value={"case": decision},
        dependencies=(design_ref,),
    )
    report_ref = artifacts.put_json(
        artifact_id=f"validation-report:builder-{decision}",
        artifact_type="control.validation_report",
        value={"case": decision},
        dependencies=(context_ref,),
    )
    evaluation_ref = artifacts.put_json(
        artifact_id=f"evaluation:builder-{decision}",
        artifact_type="control.feedback_evaluation",
        value={"case": decision},
        dependencies=(report_ref,),
    )
    input_refs = (context_ref,)
    action = RepairAction(
        action_id=f"repair-action:builder-{decision}",
        repair_policy_id=definition.repair_policy.policy_id,
        repair_epoch_digest=sha256_digest(f"builder-{decision}".encode()),
        definition_digest=definition.definition_digest,
        input_fingerprint=work_input_fingerprint(input_refs),
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision=decision,  # type: ignore[arg-type] - parametrized closed recovery decisions
        jump_distance=0,
        repair_attempt_ordinal=1,
        immutable_input_refs=input_refs,
        allowed_mutation_roots=(),
        causal_evidence_refs=(report_ref, evaluation_ref),
        reason_code="retryable_infrastructure_failure",
        repair_attempt_charge=1,
        authorized_at=datetime.now(UTC),
        route_model="gpt-5.4-mini",
        model_override=model_override,
    )
    action_ref = artifacts.put_json(
        artifact_id=action.action_id,
        artifact_type="control.repair_action",
        value=action,
        dependencies=(*input_refs, report_ref, evaluation_ref),
    )
    definition_ref = artifacts.put_json(
        artifact_id=f"work-definition:builder-{decision}",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(context_ref,),
    )
    now = datetime.now(UTC)
    attempt = WorkAttempt(
        attempt_id=f"attempt:builder-{decision}",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=2,
        parent_attempt_id="attempt:builder-prior",
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        input_refs=input_refs,
        repair_action_ref=action_ref,
        repair_attempt_charge=1,
        model_override=model_override,
        scheduled_at=now,
        started_at=now,
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(budget),
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    output_refs = tuple(
        build_artifacts.put_json(
            artifact_id=f"builder-{decision}-output:{index}",
            artifact_type=artifact_type,
            value={"case": decision, "artifact_type": artifact_type},
            dependencies=(implementation_plan_ref,),
        )
        for index, artifact_type in enumerate(
            (
                "build.source_workspace_snapshot",
                "build.implementation_lineage",
                "build.candidate_manifest",
                "build.record",
                "build.environment_candidate",
            )
        )
    )

    class FreshSessionBuilder:
        calls: list[dict[str, object]] = []

        async def build_once(self, **kwargs):
            self.calls.append(dict(kwargs))
            profile = SimpleNamespace(
                model_provider="openai",
                model=(model_override or "gpt-5.4-mini"),
                profile_hash="a" * 64,
            )
            return SimpleNamespace(
                state=SimpleNamespace(profile=profile, invocation_session=None),
                source_snapshot_ref=output_refs[0],
                implementation_lineage_ref=output_refs[1],
                candidate_manifest_ref=output_refs[2],
                build_artifact_ref=output_refs[3],
                candidate_ref=output_refs[4],
                invocation=BuildInvocationSummary(
                    invocation_id="dispatch:builder-transport-recovery",
                    status=InvocationStatus.COMPLETED,
                    duration_ms=12,
                    usage=None,
                    backend_version="constructed-boundary",
                    total_tokens=100,
                ),
            )

    builder = FreshSessionBuilder()
    leaf = BuilderLeaf(
        builder=builder,  # type: ignore[arg-type] - constructed fresh-session boundary
        workspace_root=tmp_path / "builder-workspace",
        run_id=f"run:builder-{decision}",
        kernel=kernel,
    )
    context = WorkExecutionContext(
        definition_ref=definition_ref,
        coordinate=definition.coordinate,
        graph_digest=sha256_digest(f"builder-{decision}".encode()),
        external_input_refs=input_refs,
        parent_output_refs=(),
        repair_action_ref=action_ref,
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_modeling_design_from_context",
        lambda _context, _kernel: (design_ref, design),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_implementation_plan_from_context",
        lambda _context, _kernel, **_kwargs: (implementation_plan_ref, SimpleNamespace()),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_generation_permissions",
        lambda _context, _kernel: PermissionScope(),
    )

    proposal = await leaf._proposal(  # noqa: SLF001 - recovery action boundary
        context,
        attempt,
        "dispatch:builder-transport-recovery",
        definition=definition,
    )

    assert len(builder.calls) == 1
    call = builder.calls[0]
    assert call["workspace"] == (tmp_path / "builder-workspace" / attempt.attempt_id)
    assert call["model_override"] == model_override
    assert call["parent_workspace_refs"] == ()
    assert "correction_feedback" not in call
    assert "session" not in call
    assert proposal.output_refs == output_refs


@pytest.mark.asyncio
async def test_builder_leaf_uses_private_draft_in_a_fresh_workspace_recovery_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CandidateBuild never turns a transiently interrupted draft into output.

    The Scheduler proof owns authorization and private-record binding.  This
    adapter proof verifies the next boundary: Builder receives the exact
    private workspace plus binding facts, starts no old Provider session, and
    must return an ordinary complete bundle before the leaf can expose output.
    """

    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    build_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    budget = Budget(
        llm_tokens=1_000,
        agent_turns=1,
        build_seconds=60,
        repair_attempts=1,
        wall_seconds=120,
    )
    base_definition = deterministic_boundary_work_definition(
        scope_id="job:builder-workspace-recovery",
        component="build",  # type: ignore[arg-type]
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One private draft may be completed by one fresh Builder session.",
        timing_reason="A Provider terminal cannot adopt an uncommitted candidate.",
        effect="block_integration",
        success_maturity="candidate_built",
    )
    definition = base_definition.model_copy(
        update={
            "repair_policy": RepairPolicy(
                policy_id="repair:builder-workspace-recovery",
                maximum_local_corrections=1,
                strict_progress_bonus_corrections=0,
                maximum_infrastructure_retries=1,
                maximum_session_continuations=0,
                maximum_process_recoveries=0,
                maximum_total_repair_attempts=2,
            ),
            "allowed_mutation_roots": ("/candidate",),
        }
    )
    context_ref = artifacts.put_json(
        artifact_id="context:builder-workspace-recovery",
        artifact_type="control.generation_context",
        value={"case": "workspace-recovery"},
    )
    design = portable_counter_contracts(store).design
    design_ref = artifacts.put_json(
        artifact_id="design:builder-workspace-recovery",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(context_ref,),
    )
    implementation_plan_ref = build_artifacts.put_json(
        artifact_id="implementation-plan:builder-workspace-recovery",
        artifact_type="build.implementation_plan",
        value={"case": "workspace-recovery"},
        dependencies=(design_ref,),
    )
    report_ref = artifacts.put_json(
        artifact_id="validation-report:builder-workspace-recovery",
        artifact_type="control.validation_report",
        value={"case": "workspace-recovery"},
        dependencies=(context_ref,),
    )
    evaluation_ref = artifacts.put_json(
        artifact_id="evaluation:builder-workspace-recovery",
        artifact_type="control.feedback_evaluation",
        value={"case": "workspace-recovery"},
        dependencies=(report_ref,),
    )
    execution_ref = artifacts.put_json(
        artifact_id="proposal-execution:builder-workspace-recovery",
        artifact_type="control.proposal_execution",
        value={"case": "workspace-recovery"},
        dependencies=(report_ref,),
    )
    input_refs = (context_ref,)
    model = "grok-4.5"
    action = RepairAction(
        action_id="repair-action:builder-workspace-recovery",
        repair_policy_id=definition.repair_policy.policy_id,
        repair_epoch_digest=sha256_digest(b"builder-workspace-recovery"),
        definition_digest=definition.definition_digest,
        input_fingerprint=work_input_fingerprint(input_refs),
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision="infrastructure_retry",
        jump_distance=0,
        repair_attempt_ordinal=1,
        immutable_input_refs=input_refs,
        allowed_mutation_roots=definition.allowed_mutation_roots,
        causal_evidence_refs=(report_ref, evaluation_ref),
        reason_code="private_workspace_recovery",
        repair_attempt_charge=1,
        route_model=model,
        workspace_recovery=True,
        authorized_at=datetime.now(UTC),
    )
    action_ref = artifacts.put_json(
        artifact_id=action.action_id,
        artifact_type="control.repair_action",
        value=action,
        dependencies=(*input_refs, report_ref, evaluation_ref),
    )
    continuation_workspace_root = tmp_path / "continuation-workspaces"
    workspace = (
        continuation_workspace_root / "builder" / "attempt-initial" / ".agent-runtime" / "workspace"
    )
    (workspace / "candidate").mkdir(parents=True)
    (workspace / "candidate" / "runtime.py").write_text(
        "def generated_before_terminal():\n    return 'draft'\n",
        encoding="utf-8",
    )
    profile_digest = f"sha256:{'a' * 64}"
    config_digest = f"sha256:{'b' * 64}"
    record = NodeContinuationRecord.capture_workspace_recovery(
        work_id=definition.work_id,
        attempt_id="attempt:builder-workspace-prior",
        lineage_id=f"implementation:{design_ref.revision_id}",
        workspace=workspace,
        profile_digest=profile_digest,
        codex_config_digest=config_digest,
        model=model,
        output_schema_digest=BuilderLeaf._candidate_schema_digest(),  # noqa: SLF001
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        input_fingerprint=work_input_fingerprint(input_refs),
        allowed_mutation_roots=definition.allowed_mutation_roots,
        source_report_ref=report_ref,
        source_evaluation_ref=evaluation_ref,
        repair_action_ref=action_ref,
        previous_execution_ref=execution_ref,
    )
    continuations = NodeContinuationStore(tmp_path / "continuations")
    continuations.save(record)
    definition_ref = artifacts.put_json(
        artifact_id="work-definition:builder-workspace-recovery",
        artifact_type="control.work_definition",
        value=definition,
        dependencies=(context_ref,),
    )
    now = datetime.now(UTC)
    attempt = WorkAttempt(
        attempt_id="attempt:builder-workspace-recovery",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=2,
        parent_attempt_id=record.attempt_id,
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        input_refs=input_refs,
        repair_action_ref=action_ref,
        repair_attempt_charge=1,
        continuation_commitment=record.record_commitment,
        scheduled_at=now,
        started_at=now,
    )
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(budget),
        continuations=continuations,
        continuation_workspace_root=continuation_workspace_root,
    )
    output_refs = tuple(
        build_artifacts.put_json(
            artifact_id=f"builder-workspace-recovery-output:{index}",
            artifact_type=artifact_type,
            value={"case": "workspace-recovery", "artifact_type": artifact_type},
            dependencies=(implementation_plan_ref,),
        )
        for index, artifact_type in enumerate(
            (
                "build.source_workspace_snapshot",
                "build.implementation_lineage",
                "build.candidate_manifest",
                "build.record",
                "build.environment_candidate",
            )
        )
    )

    class WorkspaceRecoveryBuilder:
        normal_calls = 0
        recovery_calls: list[dict[str, object]] = []

        async def build_once(self, **_kwargs):
            self.normal_calls += 1
            raise AssertionError("a private workspace recovery must not start an empty build")

        async def resume_interrupted_workspace_build(self, **kwargs):
            self.recovery_calls.append(dict(kwargs))
            profile = SimpleNamespace(
                model_provider="openai-compatible",
                model=model,
                profile_hash="a" * 64,
            )
            return SimpleNamespace(
                state=SimpleNamespace(profile=profile, invocation_session=None),
                source_snapshot_ref=output_refs[0],
                implementation_lineage_ref=output_refs[1],
                candidate_manifest_ref=output_refs[2],
                build_artifact_ref=output_refs[3],
                candidate_ref=output_refs[4],
                invocation=BuildInvocationSummary(
                    invocation_id=kwargs["proposal_invocation_id"],
                    status=InvocationStatus.COMPLETED,
                    duration_ms=12,
                    usage=None,
                    backend_version="constructed-boundary",
                    total_tokens=100,
                ),
            )

    builder = WorkspaceRecoveryBuilder()
    leaf = BuilderLeaf(
        builder=builder,  # type: ignore[arg-type]
        workspace_root=tmp_path / "empty-builder-workspace",
        run_id="run:builder-workspace-recovery",
        kernel=SchedulerLeafExecutor(runtime=runtime),
    )
    context = WorkExecutionContext(
        definition_ref=definition_ref,
        coordinate=definition.coordinate,
        graph_digest=sha256_digest(b"builder-workspace-recovery"),
        external_input_refs=input_refs,
        parent_output_refs=(),
        repair_action_ref=action_ref,
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_modeling_design_from_context",
        lambda _context, _kernel: (design_ref, design),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_implementation_plan_from_context",
        lambda _context, _kernel, **_kwargs: (implementation_plan_ref, SimpleNamespace()),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_generation_permissions",
        lambda _context, _kernel: PermissionScope(),
    )

    proposal = await leaf._proposal(  # noqa: SLF001 - adapter recovery boundary
        context,
        attempt,
        "dispatch:builder-workspace-recovery",
        definition=definition,
    )

    assert builder.normal_calls == 0
    assert len(builder.recovery_calls) == 1
    call = builder.recovery_calls[0]
    assert call["workspace"] == workspace.resolve()
    assert call["recovery_lineage_id"] == record.lineage_id
    assert call["recovery_profile_digest"] == profile_digest
    assert call["recovery_codex_config_digest"] == config_digest
    assert call["recovery_model"] == model
    assert call["model_override"] is None
    assert "session" not in call
    assert proposal.output_refs == output_refs


@pytest.mark.asyncio
async def test_builder_leaf_repairs_committed_seed_in_a_fresh_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A downstream repair restores the immutable Candidate, not a lost thread."""

    store = ArtifactStore(tmp_path / "artifacts")
    control_artifacts = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    build_artifacts = store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )
    input_ref = control_artifacts.put_json(
        artifact_id="context:builder-snapshot-repair",
        artifact_type="control.generation_context",
        value={"context": "builder-snapshot-repair"},
    )
    definition = deterministic_boundary_work_definition(
        scope_id="job:builder-snapshot-repair",
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependency_coordinates=(),
        claim_id="build.candidate.valid",
        claim="One committed Candidate may receive one focused downstream correction.",
        timing_reason="Integration must repair only the exact committed Candidate closure.",
        effect="block_integration",
        success_maturity="candidate_built",
    ).model_copy(
        update={
            "repair_policy": RepairPolicy(
                policy_id="repair:builder-snapshot-repair",
                maximum_local_corrections=1,
                strict_progress_bonus_corrections=0,
                maximum_infrastructure_retries=0,
                maximum_session_continuations=0,
                maximum_process_recoveries=0,
                maximum_total_repair_attempts=1,
            ),
            "allowed_mutation_roots": ("/source", "/runtime"),
        }
    )
    task_schema_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:task-schema",
        artifact_type="build.task_materialization_schema",
        value={"schema": "task"},
    )
    curriculum_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:curriculum",
        artifact_type="build.curriculum",
        value={"curriculum": "frozen"},
    )
    manifest_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:manifest",
        artifact_type="build.candidate_manifest",
        value={"manifest": "frozen"},
    )
    lineage_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:lineage",
        artifact_type="build.implementation_lineage",
        value={"lineage": "frozen"},
    )
    build_record_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:record",
        artifact_type="build.record",
        value={"record": "frozen"},
    )
    snapshot_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:source",
        artifact_type="build.source_workspace_snapshot",
        value={"snapshot": "frozen"},
    )
    verifier_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:verifier",
        artifact_type="build.public_verifier",
        value={"verifier": "public"},
    )
    contract_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:contract",
        artifact_type="build.implementation_contract",
        value={"contract": "frozen"},
    )
    candidate = EnvironmentCandidate(
        candidate_id="candidate:snapshot-repair",
        revision=1,
        design_ref=input_ref,
        implementation_contract_ref=contract_ref,
        source_workspace_snapshot_ref=snapshot_ref,
        build_artifact_ref=build_record_ref,
        runtime=RuntimeLaunch(argv=(".venv/bin/python", "-m", "environment.runtime")),
        task_materializer=TaskMaterializerDescriptor(
            entrypoint="environment.tasks:materialize",
            entry_path="src/environment/tasks.py",
            output_schema_ref=task_schema_ref,
            curriculum_ref=curriculum_ref,
        ),
        public_self_check=PublicSelfCheckDescriptor(
            argv=(".venv/bin/python", "-m", "environment.public_check"),
            entry_path="src/environment/public_check.py",
        ),
        public_verifier_ref=verifier_ref,
        candidate_manifest_ref=manifest_ref,
        implementation_lineage_ref=lineage_ref,
    )
    candidate_ref = build_artifacts.put_json(
        artifact_id="snapshot-repair:candidate",
        artifact_type="build.environment_candidate",
        value=candidate,
        dependencies=(snapshot_ref, contract_ref, manifest_ref, lineage_ref, build_record_ref),
    )
    operation_ref = control_artifacts.put_json(
        artifact_id="operation:snapshot-repair:initial",
        artifact_type="control.operation_run",
        value={"operation": "initial"},
    )
    evaluation_ref = control_artifacts.put_json(
        artifact_id="evaluation:snapshot-repair",
        artifact_type="control.feedback_evaluation",
        value={"evaluation": "initial"},
    )
    output_refs = (
        snapshot_ref,
        lineage_ref,
        manifest_ref,
        build_record_ref,
        candidate_ref,
    )
    now = datetime.now(UTC)
    source_attempt = WorkAttempt(
        attempt_id="attempt:builder-snapshot-repair:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=1,
        status="succeeded",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        input_refs=(input_ref,),
        output_refs=output_refs,
        operation_run_refs=(operation_ref,),
        feedback_evaluation_ref=evaluation_ref,
        scheduled_at=now,
        started_at=now,
        finished_at=now,
    )
    source_attempt_ref = control_artifacts.put_json(
        artifact_id=source_attempt.attempt_id,
        artifact_type="control.work_attempt",
        value=source_attempt,
        dependencies=(input_ref, *output_refs, operation_ref, evaluation_ref),
    )
    action = RepairAction(
        action_id="repair-action:builder-snapshot-repair",
        repair_policy_id=definition.repair_policy.policy_id,
        repair_epoch_digest=sha256_digest(b"builder-snapshot-repair"),
        definition_digest=definition.definition_digest,
        input_fingerprint=work_input_fingerprint((input_ref,)),
        source_evaluation_ref=evaluation_ref,
        current_coordinate=definition.coordinate,
        target_coordinate=definition.coordinate,
        decision="local_correction",
        jump_distance=0,
        repair_attempt_ordinal=1,
        immutable_input_refs=(input_ref,),
        repair_seed_attempt_ref=source_attempt_ref,
        repair_seed_output_refs=output_refs,
        allowed_mutation_roots=definition.allowed_mutation_roots,
        causal_evidence_refs=(evaluation_ref,),
        reason_code="causal_downstream_failure",
        repair_attempt_charge=1,
        authorized_at=now,
    )
    action_ref = control_artifacts.put_json(
        artifact_id=action.action_id,
        artifact_type="control.repair_action",
        value=action,
        dependencies=(source_attempt_ref, evaluation_ref, *output_refs, input_ref),
    )
    repair_attempt = WorkAttempt(
        attempt_id="attempt:builder-snapshot-repair:2",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=2,
        parent_attempt_id=source_attempt.attempt_id,
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        input_refs=(input_ref,),
        repair_action_ref=action_ref,
        repair_attempt_charge=1,
        scheduled_at=now,
        started_at=now,
    )
    runtime = WorkControlRuntime(
        artifacts=control_artifacts,
        heads=WorkControlStore(tmp_path / "work-control"),
        budget=LeaseBudgetLedger(Budget(llm_tokens=1_000, agent_turns=1, repair_attempts=1)),
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    monkeypatch.setattr(
        SchedulerLeafExecutor,
        "agent_correction_brief",
        lambda _self, _context, *, definition: SimpleNamespace(
            prompt_projection=lambda: {
                "total_blocking_issues": 1,
                "clusters": ({"code": "handshake", "remediation": "Return string operations."},),
            }
        ),
    )
    design = SimpleNamespace(design_id="design:snapshot-repair")
    plan = SimpleNamespace(implementation_strategy="repair exactly the restored source")
    monkeypatch.setattr(
        builder_leaf_module,
        "_modeling_design_from_context",
        lambda *_args: (input_ref, design),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_implementation_plan_from_context",
        lambda *_args, **_kwargs: (contract_ref, plan),
    )
    monkeypatch.setattr(
        builder_leaf_module,
        "_generation_permissions",
        lambda *_args: PermissionScope(),
    )
    fresh_session = InvocationSession(
        thread_id="fresh-builder-thread",
        lineage_id="implementation:snapshot-repair",
        workspace=(tmp_path / "fresh-workspace").resolve(),
        profile_hash="a" * 64,
        codex_config_sha256="b" * 64,
    )
    success_state = SimpleNamespace(
        profile=SimpleNamespace(
            model_provider="openai",
            model="gpt-5.3-codex-spark",
            profile_hash="a" * 64,
        ),
        invocation_session=fresh_session,
    )

    class SnapshotRepairBuilder:
        repair_kwargs: dict[str, object] | None = None

        async def repair_from_snapshot(self, **kwargs):
            self.repair_kwargs = dict(kwargs)
            return SimpleNamespace(
                state=success_state,
                source_snapshot_ref=snapshot_ref,
                implementation_lineage_ref=lineage_ref,
                candidate_manifest_ref=manifest_ref,
                build_artifact_ref=build_record_ref,
                candidate_ref=candidate_ref,
                invocation=BuildInvocationSummary(
                    invocation_id=kwargs["proposal_invocation_id"],
                    status=InvocationStatus.COMPLETED,
                    duration_ms=11,
                    usage=None,
                    backend_version="constructed-snapshot-repair",
                    total_tokens=11,
                ),
            )

    builder = SnapshotRepairBuilder()
    leaf = BuilderLeaf(
        builder=builder,  # type: ignore[arg-type] - constructed adapter boundary
        workspace_root=tmp_path / "workspaces",
        run_id="run:builder-snapshot-repair",
        kernel=kernel,
    )
    definition_ref = control_artifacts.put_json(
        artifact_id="work-definition:builder-snapshot-repair",
        artifact_type="control.work_definition",
        value=definition,
    )
    context = WorkExecutionContext(
        definition_ref=definition_ref,
        coordinate=definition.coordinate,
        graph_digest=sha256_digest(b"builder-snapshot-repair-graph"),
        external_input_refs=(input_ref,),
        repair_action_ref=action_ref,
    )

    proposal = await leaf._proposal(  # noqa: SLF001 - adapter boundary under test
        context,
        repair_attempt,
        "dispatch:builder-snapshot-repair",
        definition=definition,
    )

    assert builder.repair_kwargs is not None
    assert builder.repair_kwargs["candidate_ref"] == candidate_ref
    assert builder.repair_kwargs["workspace"] == tmp_path / "workspaces" / repair_attempt.attempt_id
    assert b"Return string operations." in builder.repair_kwargs["correction_feedback"]
    assert proposal.output_refs == output_refs


def test_completed_candidate_requires_a_real_license_role_file() -> None:
    values = _completed_values()
    files = values["files"]
    assert isinstance(files, tuple)
    values["files"] = tuple(
        item
        for item in files
        if not isinstance(item, CandidateFileDeclaration) or item.path != "LICENSE"
    )

    with pytest.raises(ValidationError, match="required component path"):
        CandidateCompletion.model_validate(values)


def test_builder_diagnostic_uses_validation_frontier_without_rejected_values() -> None:
    values = _completed_values()
    values["files"] = ()
    try:
        CandidateCompletion.model_validate(values)
    except ValidationError as validation_error:
        try:
            raise BuilderError(
                "agent.output",
                "raw rejected value /private/workspace/secret",
            ) from validation_error
        except BuilderError as builder_error:
            diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001
                builder_error
            )
    else:  # pragma: no cover - the contract deliberately rejects this payload
        raise AssertionError("invalid CandidateCompletion unexpectedly passed")

    assert diagnostic.validation_phase == "completion_declarations"
    assert diagnostic.frontier_ordinal == 20
    assert diagnostic.issue_codes == ("completion_files_missing@root",)
    assert "/private/workspace/secret" not in diagnostic.feedback
    assert all(not code.startswith("builder_agent.output:") for code in diagnostic.issue_codes)


def test_builder_workspace_progress_records_counts_without_file_names(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    source = candidate / "src" / "private_business_name.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    state = SimpleNamespace(
        run_id="run:heartbeat",
        attempt_id="attempt:build:1",
        workspace=tmp_path,
        lineage_id="lineage:heartbeat",
    )

    progress = EnvironmentBuilder._workspace_progress(  # type: ignore[arg-type]  # noqa: SLF001
        state,
        "changed",
    )

    assert progress.file_count == 1
    assert progress.run_id == "run:heartbeat"
    assert progress.attempt_id == "attempt:build:1"
    assert progress.total_bytes == len("value = 1\n")
    assert progress.metadata_digest is not None
    assert "private_business_name" not in str(progress.model_dump(mode="json"))


def test_builder_precommit_removes_only_derived_candidate_ephemera(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    package = candidate / "environment"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    source = package / "runtime.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (cache / "runtime.cpython-312.pyc").write_bytes(b"derived")
    loose_bytecode = package / "orphan.pyc"
    loose_bytecode.write_bytes(b"derived")
    ordinary_build_named_file = candidate / "build"
    ordinary_build_named_file.write_text("must remain for validator", encoding="utf-8")

    EnvironmentBuilder._remove_derived_candidate_ephemera(candidate)  # noqa: SLF001

    assert source.is_file()
    assert ordinary_build_named_file.is_file()
    assert not cache.exists()
    assert not loose_bytecode.exists()


def test_builder_precommit_never_follows_cache_symlink(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    external = tmp_path / "external-cache"
    external.mkdir()
    marker = external / "keep.pyc"
    marker.write_bytes(b"outside")
    cache_link = candidate / "__pycache__"
    cache_link.symlink_to(external, target_is_directory=True)

    EnvironmentBuilder._remove_derived_candidate_ephemera(candidate)  # noqa: SLF001

    assert cache_link.is_symlink()
    assert marker.read_bytes() == b"outside"


def test_workspace_validation_rejects_a_declared_but_missing_license(tmp_path: Path) -> None:
    completion = CandidateCompletion.model_validate(_completed_values())
    for declaration in completion.files:
        if declaration.path == "LICENSE":
            continue
        path = tmp_path / declaration.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError, match="declared files are missing.*LICENSE"):
        CandidateWorkspaceValidator().validate(tmp_path, completion)


def test_workspace_manifest_gap_becomes_safe_actionable_repair_feedback(tmp_path: Path) -> None:
    """The Agent learns the inventory relation, never a candidate-controlled path.

    This crosses the real validator -> Builder diagnostic boundary rather than
    asserting a hand-written ``ValidationDiagnostic``.  The raw exception may
    contain an untrusted filename, but neither Scheduler persistence nor a
    future Engineer correction receives it.
    """

    completion = CandidateCompletion.model_validate(_completed_values())
    missing_path = "src/environment/runtime.py"
    for declaration in completion.files:
        if declaration.path == missing_path:
            continue
        path = tmp_path / declaration.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError) as captured:
        CandidateWorkspaceValidator().validate(tmp_path, completion)

    workspace_error = captured.value
    assert missing_path in str(workspace_error)
    try:
        raise BuilderError("candidate.validation", str(workspace_error)) from workspace_error
    except BuilderError as builder_error:
        diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001 - boundary under test
            builder_error
        )

    issue = diagnostic.issues[0]
    persisted = json.dumps(diagnostic.persistence_projection())
    assert diagnostic.validation_phase == "manifest_closure"
    assert issue.issue_code == "candidate_manifest_declared_missing@candidate.files"
    assert issue.violated_condition == (
        "CandidateCompletion.files declares 1 path absent from the final candidate/ tree"
    )
    assert issue.expected_category == (
        "a one-for-one declaration of every final regular candidate file"
    )
    assert issue.actionable_for_agent is True
    assert missing_path not in diagnostic.feedback
    assert missing_path not in persisted


def test_workspace_python_range_mismatch_becomes_safe_actionable_repair_feedback(
    tmp_path: Path,
) -> None:
    """A real candidate tree exposes the frozen Python-range failure precisely."""

    project, _uv_path, _uv_cache = write_candidate_project(tmp_path)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace(
            'requires-python = ">=3.12,<3.13"',
            'requires-python = ">=3.12"',
        ),
        encoding="utf-8",
    )
    (project / "uv.lock").write_text(
        """version = 1
revision = 3
requires-python = ">=3.12"

[[package]]
name = "counter-runtime-v3"
version = "0.1.0"
source = { virtual = "." }
""",
        encoding="utf-8",
    )
    completion = CandidateCompletion(
        status="completed",
        project_root="candidate",
        root_project_mode="virtual-read-only-source-tree",
        dependency_install_mode="offline-wheel-only",
        runtime=CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "runtime"),
            entry_path="runtime.py",
        ),
        task_materializer=CandidateTaskMaterializerDeclaration(
            entrypoint="task_materializer:materialize",
            entry_path="task_materializer.py",
        ),
        public_self_check=CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "public_check"),
            entry_path="public_check.py",
        ),
        public_test_paths=("public_test.py",),
        files=tuple(
            CandidateFileDeclaration(path=item.path, role=item.role)  # type: ignore[arg-type]
            for item in candidate_files(project)
        ),
    )

    with pytest.raises(CandidateWorkspaceError) as captured:
        CandidateWorkspaceValidator().validate(project, completion)

    workspace_error = captured.value
    assert workspace_error.safe_diagnostic is not None
    assert workspace_error.safe_diagnostic.code == "python_requires_contract_mismatch"
    try:
        raise BuilderError("candidate.validation", str(workspace_error)) from workspace_error
    except BuilderError as builder_error:
        diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001 - boundary under test
            builder_error
        )

    issue = diagnostic.issues[0]
    assert diagnostic.validation_phase == "project_contract"
    assert issue.issue_code == (
        "candidate_python_requires_contract_mismatch@candidate.pyproject.toml.uv.lock"
    )
    assert issue.violated_condition == (
        "candidate Python ranges do not exactly represent the frozen implementation contract"
    )
    assert issue.expected_category == (
        "the exact frozen python_requires value in pyproject and either that value or "
        "uv's canonical Python 3.12 range in uv.lock"
    )
    assert "inputs/implementation-contract.json" in diagnostic.feedback
    assert ">=3.12" in diagnostic.feedback


def test_workspace_derives_executable_mode_from_physical_tree(tmp_path: Path) -> None:
    """A model no longer owns redundant mode metadata for Candidate files."""

    project, _uv_path, _uv_cache = write_candidate_project(tmp_path)
    runtime_path = project / "runtime.py"
    runtime_path.chmod(runtime_path.stat().st_mode | stat.S_IXUSR)
    completion = CandidateCompletion(
        status="completed",
        project_root="candidate",
        root_project_mode="virtual-read-only-source-tree",
        dependency_install_mode="offline-wheel-only",
        runtime=CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "runtime"),
            entry_path="runtime.py",
        ),
        task_materializer=CandidateTaskMaterializerDeclaration(
            entrypoint="task_materializer:materialize",
            entry_path="task_materializer.py",
        ),
        public_self_check=CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "public_check"),
            entry_path="public_check.py",
        ),
        public_test_paths=("public_test.py",),
        files=tuple(
            CandidateFileDeclaration(path=item.path, role=item.role)  # type: ignore[arg-type]
            for item in candidate_files(project)
        ),
    )

    validated = CandidateWorkspaceValidator().validate(project, completion)

    runtime = next(item for item in validated.files if item.path == "runtime.py")
    assert runtime.executable is True
    assert (
        "executable"
        not in CandidateFileDeclaration.model_json_schema(mode="validation")["properties"]
    )


@pytest.mark.parametrize("field", ("root_project_mode", "dependency_install_mode"))
def test_completed_candidate_cannot_omit_supply_chain_contract(field: str) -> None:
    values = _completed_values()
    values.pop(field)

    with pytest.raises(ValidationError) as captured:
        CandidateCompletion.model_validate(values)

    assert captured.value.errors(include_url=False)[0]["type"] == (
        "completion_missing_declarations"
    )


def test_candidate_completion_has_no_consumer_adapter_or_task_generator_fields() -> None:
    values = _completed_values()
    values["consumer_adapter_path"] = "src/environment/adapter.py"
    values["task_generator"] = {
        "entrypoint": "environment.tasks:generate",
        "entry_path": "src/environment/tasks.py",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateCompletion.model_validate(values)


def test_task_materializer_entrypoint_is_exact() -> None:
    with pytest.raises(ValidationError, match="package.module:materialize"):
        CandidateTaskMaterializerDeclaration(
            entrypoint="environment.tasks:generate",
            entry_path="src/environment/tasks.py",
        )


def _diagnostic_for_invalid_completion(
    values: dict[str, object],
) -> ValidationDiagnostic:
    try:
        CandidateCompletion.model_validate(values)
    except ValidationError as validation_error:
        try:
            raise BuilderError("agent.output", "private raw output") from validation_error
        except BuilderError as builder_error:
            return EnvironmentBuilder._validation_diagnostic(builder_error)  # noqa: SLF001
    raise AssertionError("invalid CandidateCompletion unexpectedly passed")


def test_builder_distinguishes_entrypoint_format_from_module_binding() -> None:
    format_values = _completed_values()
    format_values["task_materializer"] = {
        "entrypoint": "candidate/materializer.py:materialize",
        "entry_path": "candidate/materializer.py",
    }
    format_diagnostic = _diagnostic_for_invalid_completion(format_values)

    binding_values = _completed_values()
    binding_values["task_materializer"] = {
        "entrypoint": "materializer:materialize",
        "entry_path": "candidate/materializer.py",
    }
    binding_diagnostic = _diagnostic_for_invalid_completion(binding_values)

    assert format_diagnostic.validation_phase == "completion_entrypoint_format"
    assert format_diagnostic.frontier_ordinal == 15
    assert format_diagnostic.issue_codes == (
        "task_materializer_entrypoint_format@task_materializer.entrypoint",
    )
    assert "package.module:materialize" in format_diagnostic.feedback

    assert binding_diagnostic.validation_phase == "completion_entrypoint_binding"
    assert binding_diagnostic.frontier_ordinal == 16
    assert binding_diagnostic.issue_codes == (
        "task_materializer_binding_mismatch@task_materializer",
    )
    assert "replacing `/` with `.`" in binding_diagnostic.feedback
    assert binding_diagnostic.issues[0].violated_condition == (
        "the Task Materializer entrypoint module must equal the module derived from entry_path"
    )
    assert binding_diagnostic.issues[0].expected_category == (
        "`module:materialize` with module mechanically derived from entry_path"
    )


def test_task_materializer_binding_supports_src_and_main_mapping() -> None:
    declaration = CandidateTaskMaterializerDeclaration(
        entrypoint="environment.tasks:materialize",
        entry_path="src/environment/tasks/__main__.py",
    )

    assert declaration.entrypoint == "environment.tasks:materialize"


def _outer_prefixed_completion_output() -> dict[str, object]:
    return {
        "status": "completed",
        "project_root": "candidate",
        "root_project_mode": "virtual-read-only-source-tree",
        "dependency_install_mode": "offline-wheel-only",
        "runtime": {
            "argv": [".venv/bin/python", "-m", "candidate.runtime"],
            "entry_path": "candidate/runtime.py",
        },
        "task_materializer": {
            "entrypoint": "materialize",
            "entry_path": "candidate/materializer.py",
        },
        "public_self_check": {
            "argv": [".venv/bin/python", "-m", "candidate.self_check"],
            "entry_path": "candidate/self_check.py",
        },
        "public_test_paths": ["public_tests/test_runtime.py"],
        "files": [
            {"path": "candidate/LICENSE", "role": "license"},
            {"path": "candidate/pyproject.toml", "role": "configuration"},
            {"path": "candidate/uv.lock", "role": "dependency_lock"},
            {"path": "candidate/candidate/runtime.py", "role": "runtime"},
            {
                "path": "candidate/candidate/materializer.py",
                "role": "task_materializer",
            },
            {
                "path": "candidate/candidate/self_check.py",
                "role": "public_verifier",
            },
            {
                "path": "candidate/public_tests/test_runtime.py",
                "role": "public_test",
            },
        ],
    }


def _parse_json_completion(value: object) -> CandidateCompletion:
    return CandidateCompletion.model_validate_json(json.dumps(value))


def test_framework_normalizes_one_witnessed_outer_candidate_namespace() -> None:
    raw = _outer_prefixed_completion_output()

    normalized = normalize_candidate_completion_output(raw)
    completion = _parse_json_completion(normalized)

    assert raw["files"][0]["path"] == "candidate/LICENSE"  # type: ignore[index]
    assert tuple(item.path for item in completion.files) == (
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        "candidate/runtime.py",
        "candidate/materializer.py",
        "candidate/self_check.py",
        "public_tests/test_runtime.py",
    )
    assert completion.runtime is not None
    assert completion.runtime.entry_path == "candidate/runtime.py"
    assert completion.runtime.argv[-1] == "candidate.runtime"
    assert completion.task_materializer is not None
    assert completion.task_materializer.entrypoint == "candidate.materializer:materialize"


def test_framework_drops_legacy_agent_executable_declarations() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        item["executable"] = True

    normalized = normalize_candidate_completion_output(raw)

    normalized_files = normalized["files"]  # type: ignore[index]
    assert all("executable" not in item for item in normalized_files)
    assert _parse_json_completion(normalized).status == "completed"


def test_framework_preserves_legitimate_nested_candidate_package() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"

    normalized = normalize_candidate_completion_output(raw)

    assert normalized == raw
    assert _parse_json_completion(normalized).runtime is not None


def test_framework_does_not_guess_mixed_candidate_namespaces() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    license_declaration = files[0]
    assert isinstance(license_declaration, dict)
    license_declaration["path"] = "LICENSE"

    normalized = normalize_candidate_completion_output(raw)

    normalized_files = normalized["files"]  # type: ignore[index]
    assert normalized_files[1]["path"] == "candidate/pyproject.toml"  # type: ignore[index]
    with pytest.raises(ValidationError):
        _parse_json_completion(normalized)


def test_framework_canonicalizes_materializer_module_fixed_by_entry_path() -> None:
    raw = _outer_prefixed_completion_output()
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "wrong.module:materialize"

    normalized = normalize_candidate_completion_output(raw)

    completion = _parse_json_completion(normalized)

    assert completion.task_materializer is not None
    assert completion.task_materializer.entrypoint == "candidate.materializer:materialize"


def test_framework_does_not_normalize_an_arbitrary_materializer_callable() -> None:
    raw = _outer_prefixed_completion_output()
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "wrong.module:other"

    normalized = normalize_candidate_completion_output(raw)

    with pytest.raises(ValidationError, match="package.module:materialize"):
        _parse_json_completion(normalized)


def test_framework_canonicalizes_root_materializer_module_without_candidate_prefix() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        if item["role"] == "task_materializer":
            item["path"] = "task_materializer.py"
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entry_path"] = "task_materializer.py"
    task["entrypoint"] = "candidate.task_materializer:materialize"

    normalized = normalize_candidate_completion_output(raw)

    normalized_task = normalized["task_materializer"]  # type: ignore[index]
    assert normalized_task["entrypoint"] == "task_materializer:materialize"  # type: ignore[index]


def test_framework_normalizes_roles_fixed_by_component_path_claims() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"
    for item in files:
        assert isinstance(item, dict)
        item["role"] = "documentation"
    files.append(
        {
            "path": "public_tests/test_runtime_launch.py",
            "role": "documentation",
        }
    )
    public_tests = raw["public_test_paths"]
    assert isinstance(public_tests, list)
    public_tests.append("public_tests/test_runtime_launch.py")

    completion = _parse_json_completion(normalize_candidate_completion_output(raw))
    roles = {item.path: item.role for item in completion.files}

    assert roles["pyproject.toml"] == "configuration"
    assert roles["uv.lock"] == "dependency_lock"
    assert roles["LICENSE"] == "license"
    assert roles["candidate/runtime.py"] == "runtime"
    assert roles["candidate/materializer.py"] == "task_materializer"
    assert roles["candidate/self_check.py"] == "public_verifier"
    assert roles["public_tests/test_runtime.py"] == "public_test"
    assert roles["public_tests/test_runtime_launch.py"] == "public_test"


def test_framework_does_not_normalize_conflicting_component_role_claims() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"
    raw["public_test_paths"] = ["candidate/runtime.py"]

    normalized = normalize_candidate_completion_output(raw)

    with pytest.raises(ValidationError, match="public test path"):
        _parse_json_completion(normalized)


def test_builder_types_python_launch_mismatch_for_an_authorized_correction() -> None:
    values = _completed_values()
    values["runtime"] = {
        "argv": (".venv/bin/python", "-m", "wrong.module"),
        "entry_path": "src/environment/runtime.py",
    }

    diagnostic = _diagnostic_for_invalid_completion(values)

    assert diagnostic.validation_phase == "completion_launch"
    assert diagnostic.frontier_ordinal == 17
    assert diagnostic.issue_codes == ("python_launch_entrypoint_mismatch@runtime",)
    assert diagnostic.issues[0].retryable is True
    assert "declared `.py` entry_path" in diagnostic.feedback


def test_builder_types_every_path_format_error_from_one_candidate_completion() -> None:
    values = _completed_values()
    values["runtime"] = {
        "argv": (".venv/bin/python", "-m", "candidate.runtime"),
        "entry_path": "candidate.runtime",
    }
    values["task_materializer"] = {
        "entrypoint": "candidate/materializer.py:materialize",
        "entry_path": "candidate.materializer",
    }
    values["public_self_check"] = {
        "argv": (".venv/bin/python", "-m", "candidate.public_self_check"),
        "entry_path": "candidate.public_self_check",
    }

    diagnostic = _diagnostic_for_invalid_completion(values)

    assert diagnostic.validation_phase == "completion_entrypoint_format"
    assert diagnostic.frontier_ordinal == 15
    assert diagnostic.issue_codes == (
        "python_entry_path_invalid@runtime.entry_path",
        "task_materializer_entrypoint_format@task_materializer.entrypoint",
        "python_entry_path_invalid@task_materializer.entry_path",
        "python_entry_path_invalid@public_self_check.entry_path",
    )
    assert diagnostic.actionable_for_agent is True
    assert "private raw output" not in diagnostic.feedback

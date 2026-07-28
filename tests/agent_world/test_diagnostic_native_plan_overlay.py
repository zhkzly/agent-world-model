"""Regression for native World-plan diagnostic continuation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_world.app import build_application
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    Budget,
    CoverageDimension,
    DifficultyDimension,
    EnvironmentJob,
    EnvironmentRequest,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.control import (
    ArtifactSlotContract,
    GenerationWorkGraph,
    LeaseBudgetLedger,
    WorkControlRuntime,
    WorkCoordinate,
    WorkDefinition,
    WorkGraphEpochRuntime,
    compile_design_work_graph,
    compile_world_work_graph,
    derive_task_requirement_design_definitions,
    deterministic_boundary_work_definition,
    verifier_plan_work_definition,
)
from agent_world.control.test_node import (
    DiagnosticTaskCurriculumJoinRunner,
    DiagnosticTaskRequirementNodeRunner,
)
from agent_world.designer.models import CurriculumPlanSourceDraft, CurriculumTaskPlanSourceDraft


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="test-native-plan-overlay",
            api_key_environment="AGENT_WORLD_TEST_NATIVE_PLAN_OVERLAY_KEY",
        ),
        research=ResearchConfig(provider="bing_rss", use_jina_reader_fallback=False),
    )


def _curriculum_plan(*, seed_space: str) -> CurriculumPlanSourceDraft:
    return CurriculumPlanSourceDraft(
        coverage_dimensions=(CoverageDimension(dimension="task-list"),),
        task_plans=(
            CurriculumTaskPlanSourceDraft(
                task_type="todo-list",
                objective="Create one task.",
                allowed_actor_ids=("user",),
                required_tool_ids=("todo.add",),
                difficulty_dimensions=("task-list",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="task-list",
                description="One task list operation.",
                levels=("basic", "standard"),
            ),
        ),
        generation_seed_space=seed_space,
    )


def test_task_requirement_loader_accepts_native_plan_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native diagnostic Plan overlay can start its first TaskRequirement.

    The constructed state uses the real epoch store and control runtime.  Its
    only synthetic values are code-owned fixture outputs: this proves the
    deterministic diagnostic-topology bridge, while the follow-up CLI proof
    invokes the actual model for the task family.
    """

    monkeypatch.setenv("AGENT_WORLD_TEST_NATIVE_PLAN_OVERLAY_KEY", os.urandom(16).hex())
    config = _config(tmp_path)
    app = build_application(config)
    artifacts = app.controller.artifacts
    heads = app.controller.work_control
    scope_id = "generate-job:native-plan-overlay"
    budget = Budget(agent_turns=10, llm_tokens=5_000_000, wall_seconds=1_000)
    permissions = PermissionScope()
    release = ReleaseProfile(profile_id="release:native-plan-overlay")
    request = EnvironmentRequest(
        request_id="request:native-plan-overlay",
        need="A small task list workflow.",
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
        job_id=scope_id,
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
    context = GenerationContext(
        context_id="context:native-plan-overlay",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=permissions,
        budget=budget,
        release_profile=release,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )

    def definition(
        *,
        component: str,
        stage: str,
        artifact_slot: str,
        dependencies: tuple[WorkCoordinate, ...],
        group_id: str | None = None,
        shard_id: str | None = None,
    ) -> WorkDefinition:
        base = deterministic_boundary_work_definition(
            scope_id=scope_id,
            component="design",
            stage=f"fixture_{stage}",
            artifact_slot=artifact_slot,
            dependency_coordinates=dependencies,
            claim_id=f"fixture.{stage}.passed",
            claim=f"The fixture {stage} boundary is committed.",
            timing_reason="Construct one exact diagnostic topology closure.",
            effect="block_compile",
            success_maturity=f"fixture_{stage}_passed",
        )
        coordinate = WorkCoordinate(
            scope_id=scope_id,
            component=component,  # type: ignore[arg-type]
            stage=stage,
            artifact_slot=artifact_slot,
            group_id=group_id,
            shard_id=shard_id,
        )
        return base.model_copy(
            update={
                "work_id": (
                    f"work:fixture:{component}:{stage}:{group_id or 'root'}:{shard_id or 'root'}"
                ),
                "coordinate": coordinate,
                "dependency_coordinates": dependencies,
            }
        )

    research_plan = definition(
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependencies=(),
    )
    acquisition = definition(
        component="research",
        stage="evidence_acquisition",
        artifact_slot="research_acquisition",
        dependencies=(research_plan.coordinate,),
    )
    synthesis = definition(
        component="research",
        stage="evidence_synthesis",
        artifact_slot="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
    )
    architecture = definition(
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture",
        dependencies=(synthesis.coordinate,),
    )
    bootstrap_definitions = (research_plan, acquisition, synthesis, architecture)
    behavior = definition(
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        dependencies=(architecture.coordinate,),
        group_id="fixture-tools",
        shard_id="batch-1",
    )
    world_rules = definition(
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
        dependencies=(behavior.coordinate,),
    )
    plan_dependencies = (synthesis.coordinate, architecture.coordinate, world_rules.coordinate)
    base_plan = definition(
        component="design",
        stage="curriculum_plan",
        artifact_slot="curriculum_plan",
        dependencies=plan_dependencies,
    )
    plan_output_slot = ArtifactSlotContract(
        slot_id="output:curriculum-plan-source",
        direction="output",
        artifact_types=("design.curriculum_plan_source",),
        minimum_count=1,
        maximum_count=1,
        producer_component="design",
    )
    base_plan = base_plan.model_copy(
        update={
            "output_slots": (plan_output_slot,),
        }
    )

    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(budget),
    )
    epochs = WorkGraphEpochRuntime(artifacts=artifacts, heads=heads)
    bootstrap_graph = GenerationWorkGraph.compile(bootstrap_definitions, mode="diagnostic")
    _, _, _, bootstrap_epoch_ref = epochs.freeze_bootstrap(
        context_ref=context_ref,
        graph=bootstrap_graph,
        topology_id="topology:native-overlay-bootstrap",
    )

    def commit_fixture(item: WorkDefinition, *, artifact_type: str) -> None:
        output_ref = artifacts.put_json(
            artifact_id=(
                f"fixture-output:{item.coordinate.stage}:{item.coordinate.group_id or 'root'}:"
                f"{item.coordinate.shard_id or 'root'}"
            ),
            artifact_type=artifact_type,
            value={"stage": item.coordinate.stage},
            dependencies=(context_ref,),
        )
        runtime.execute_deterministic_boundary(
            definition=item,
            input_refs=(context_ref,),
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )

    for item in bootstrap_definitions:
        commit_fixture(item, artifact_type="design.fixture_bootstrap")

    base_world_definitions = (*bootstrap_definitions, behavior, world_rules, base_plan)
    base_world_graph = compile_world_work_graph(
        scope_id=scope_id,
        world_definitions=base_world_definitions,
    )
    _, _, _, base_world_epoch_ref = epochs.freeze_world(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=base_world_graph,
        topology_id="topology:native-overlay-world",
    )
    commit_fixture(behavior, artifact_type="design.fixture_behavior")
    commit_fixture(world_rules, artifact_type="design.fixture_world_rules")
    base_plan_ref = artifacts.put_json(
        artifact_id="fixture-output:base-curriculum-plan",
        artifact_type="design.curriculum_plan_source",
        value=_curriculum_plan(seed_space="base-fixture-seed-space"),
        dependencies=(context_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=base_plan,
        input_refs=(context_ref,),
        subject_ref=base_plan_ref,
        output_refs=(base_plan_ref,),
    )

    task_requirement = definition(
        component="design",
        stage="task_requirement",
        artifact_slot="task_requirement_source",
        dependencies=(*plan_dependencies, base_plan.coordinate),
        group_id="task-requirements",
        shard_id="todo-list",
    )
    task_curriculum = definition(
        component="design",
        stage="task_curriculum",
        artifact_slot="task_curriculum",
        dependencies=(*plan_dependencies, base_plan.coordinate, task_requirement.coordinate),
    )
    modeling = definition(
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
        dependencies=(*plan_dependencies, task_curriculum.coordinate),
    )
    verifier_plan = verifier_plan_work_definition(
        scope_id=scope_id,
        modeling_coordinate=modeling.coordinate,
    )
    native_design_graph = compile_design_work_graph(
        scope_id=scope_id,
        design_definitions=(*base_world_definitions, task_requirement, task_curriculum),
        modeling_definition=modeling,
        verifier_plan_definition=verifier_plan,
    )
    epochs.freeze_design_from_world(
        context_ref=context_ref,
        world_epoch_ref=base_world_epoch_ref,
        graph=native_design_graph,
        topology_id="topology:native-overlay-design",
    )
    commit_fixture(task_requirement, artifact_type="design.fixture_task_requirement")
    commit_fixture(task_curriculum, artifact_type="design.fixture_task_curriculum")

    heads.mark_test_node_diagnostic_clone()
    overlay_plan = base_plan.model_copy(
        update={
            "proposal_policy": base_plan.proposal_policy.model_copy(
                update={"implementation_revision_id": "framework.fixture.plan-overlay.v1"}
            )
        }
    )
    overlay_world_graph = compile_world_work_graph(
        scope_id=scope_id,
        world_definitions=(*bootstrap_definitions, behavior, world_rules, overlay_plan),
    )
    _, _, _, overlay_world_epoch_ref = epochs.freeze_world(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=overlay_world_graph,
        topology_id="topology:native-overlay-plan-definition",
        allow_diagnostic_predecessors=True,
    )
    overlay_plan_ref = artifacts.put_json(
        artifact_id="fixture-output:overlay-curriculum-plan",
        artifact_type="design.curriculum_plan_source",
        value=_curriculum_plan(seed_space="overlay-fixture-seed-space"),
        dependencies=(context_ref,),
    )
    diagnostic_runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(budget),
        diagnostic_only=True,
    )
    diagnostic_runtime.execute_deterministic_boundary(
        definition=overlay_plan,
        input_refs=(context_ref,),
        subject_ref=overlay_plan_ref,
        output_refs=(overlay_plan_ref,),
    )

    frozen = DiagnosticTaskRequirementNodeRunner._load_committed_world_plan(  # noqa: SLF001
        app=app,
        scope_id=scope_id,
    )

    assert frozen.world_epoch_ref == overlay_world_epoch_ref
    assert frozen.curriculum_plan_ref == overlay_plan_ref
    assert frozen.modeling_template == modeling

    # The retained native Design and this Plan-derived Design deliberately
    # share public coordinates.  The join loader must select the latter by
    # its exact diagnostic CurriculumPlan commit, rather than treating the
    # two frozen manifests as an irreducible ambiguity.
    overlay_design_definitions, overlay_modeling = derive_task_requirement_design_definitions(
        scope_id=scope_id,
        world_definitions=frozen.graph.definitions,
        curriculum_plan_ref=frozen.curriculum_plan_ref,
        curriculum_plan=frozen.curriculum_plan,
        modeling_template=frozen.modeling_template,
        # Fixture Plan is code-owned solely to create the frozen topology;
        # the real CLI proof supplies the Agent Plan's 5M budget.  The
        # derived graph nevertheless needs a valid Agent policy shape.
        agent_wall_seconds=budget.wall_seconds,
        agent_token_limit=budget.llm_tokens,
    )
    overlay_verifier_plan = verifier_plan_work_definition(
        scope_id=scope_id,
        modeling_coordinate=overlay_modeling.coordinate,
    )
    overlay_design_graph = compile_design_work_graph(
        scope_id=scope_id,
        design_definitions=overlay_design_definitions,
        modeling_definition=overlay_modeling,
        verifier_plan_definition=overlay_verifier_plan,
    )
    _, _, _, overlay_design_epoch_ref = epochs.freeze_design_from_world(
        context_ref=context_ref,
        world_epoch_ref=overlay_world_epoch_ref,
        graph=overlay_design_graph,
        topology_id="topology:native-overlay-plan-derived-design",
        allow_diagnostic_predecessors=True,
    )
    selected_join = DiagnosticTaskCurriculumJoinRunner._load_plan_derived_join(  # noqa: SLF001
        app=app,
        scope_id=scope_id,
    )
    assert selected_join.design_epoch_ref == overlay_design_epoch_ref
    assert selected_join.curriculum_plan_definition == overlay_plan
    app.telemetry.close()

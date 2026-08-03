from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from v3_fixture import portable_counter_contracts

import agent_world.control.test_node as test_node_module
from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    CoverageDimension,
    DifficultyDimension,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.control.work import ArtifactSlotContract, WorkCoordinate, WorkDefinition
from agent_world.control.work_graph import (
    _CANDIDATE_BUILD_VALIDATOR_MODULES,
    _EVIDENCE_SYNTHESIS_VALIDATOR_MODULES,
    _IMPLEMENTATION_PLAN_VALIDATOR_MODULES,
    _RELEASE_ASSURANCE_VALIDATOR_MODULES,
    _RUNTIME_INTEGRATION_VALIDATOR_MODULES,
    _SHARED_SCHEDULER_FEEDBACK_MODULES,
    _TOOL_SEMANTICS_BATCH_VALIDATOR_MODULES,
    _VERIFIER_INTENT_BATCH_VALIDATOR_MODULES,
    _VERIFIER_PLAN_VALIDATOR_MODULES,
    CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS,
    GenerationWorkGraph,
    JoinPolicy,
    WorkGraphEpoch,
    WorkGraphError,
    WorkGroupDefinition,
    bind_model_route_recovery_policy,
    compile_design_work_graph,
    compile_world_work_graph,
    complete_generation_work_graph,
    current_runtime_revisions_for_definition,
    derive_final_design_definitions,
    derive_task_requirement_design_definitions,
    derive_world_plan_definitions,
    deterministic_boundary_work_definition,
    research_acquisition_work_definition,
    research_plan_work_definition,
    research_synthesis_work_definition,
    structured_agent_work_definition,
    tool_semantics_batch_definition,
    verifier_plan_work_definition,
    world_architecture_work_definition,
)
from agent_world.designer.models import (
    CurriculumPlanSourceDraft,
    CurriculumTaskPlanSourceDraft,
    ToolCouplingGroupPlan,
    ToolCouplingPlan,
)
from agent_world.judge import VerifierBatchPlan, VerifierBatchPlanItem
from agent_world.judge_budgeting import (
    integration_budget_requirements,
    release_without_interactive_budget_requirements,
)


def _artifact_ref(artifact_id: str, artifact_type: str) -> ArtifactRef:
    digest = sha256_digest(artifact_id.encode("utf-8"))
    return ArtifactRef(
        artifact_id=artifact_id,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=1,
    )


def _coordinate(slot: str) -> WorkCoordinate:
    return WorkCoordinate(
        scope_id="job:hotel",
        component="design",
        stage=slot,
        artifact_slot=slot,
    )


def _definition(slot: str, dependencies: tuple[WorkCoordinate, ...] = ()):
    return tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id=f"group:{slot}",
        batch_id=f"batch:{slot}",
        dependency_coordinates=dependencies,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    ).model_copy(
        update={
            "work_id": f"work:{slot}",
            "coordinate": _coordinate(slot),
            "dependency_coordinates": dependencies,
        }
    )


def test_evidence_synthesis_definition_binds_current_prompt_skill_and_compiler_revisions() -> None:
    parent = WorkCoordinate(
        scope_id="job:hotel",
        component="research",
        stage="evidence_acquisition",
        artifact_slot="research_acquisition",
    )
    definition = research_synthesis_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=parent,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )

    revisions = current_runtime_revisions_for_definition(definition)

    assert revisions == (
        definition.proposal_policy.implementation_revision_id,
        definition.validation_policy.validator_revision_id,
    )
    assert definition.proposal_policy.implementation_revision_id.startswith(
        "framework.research-evidence-synthesis."
    )
    assert definition.validation_policy.validator_revision_id.startswith(
        "framework.validator-evidence-synthesis."
    )


def test_refreshable_validator_revisions_bind_shared_scheduler_feedback_route() -> None:
    """Feedback/control changes invalidate every registered refreshable leaf."""

    for modules in (
        _EVIDENCE_SYNTHESIS_VALIDATOR_MODULES,
        _TOOL_SEMANTICS_BATCH_VALIDATOR_MODULES,
        _VERIFIER_INTENT_BATCH_VALIDATOR_MODULES,
        _VERIFIER_PLAN_VALIDATOR_MODULES,
        _IMPLEMENTATION_PLAN_VALIDATOR_MODULES,
        _CANDIDATE_BUILD_VALIDATOR_MODULES,
        _RUNTIME_INTEGRATION_VALIDATOR_MODULES,
        _RELEASE_ASSURANCE_VALIDATOR_MODULES,
    ):
        assert set(_SHARED_SCHEDULER_FEEDBACK_MODULES).issubset(modules)


def test_tool_semantics_batch_definition_binds_current_revisions() -> None:
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(),
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )

    revisions = current_runtime_revisions_for_definition(definition)

    assert revisions == (
        definition.proposal_policy.implementation_revision_id,
        definition.validation_policy.validator_revision_id,
    )
    assert definition.proposal_policy.implementation_revision_id.startswith(
        "framework.design-tool-semantics-batch."
    )
    assert definition.validation_policy.validator_revision_id.startswith(
        "framework.validator-tool-semantics-batch."
    )


def test_all_direct_design_agent_leaves_bind_prompt_skill_and_validator_revisions() -> None:
    """No live Direct design leaf may silently retain the unversioned default.

    The graph has one true topology-discovery Architecture parent, then a
    committed shared contract before independent singleton tool shards.  This
    test checks the provenance rule, not whether a model can author the
    semantics: a Prompt, Runtime Skill, profile-shaping, or validator edit must
    make the affected current definition discoverable for a fresh node run.
    """

    plan = research_plan_work_definition(
        scope_id="job:hotel",
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    acquisition = research_acquisition_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=plan.coordinate,
        wall_seconds=120,
        maximum_search_calls=1,
        maximum_tool_calls=3,
    )
    synthesis = research_synthesis_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=acquisition.coordinate,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    architecture = world_architecture_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=synthesis.coordinate,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    architecture_ref = _artifact_ref("architecture:hotel", "design.world_architecture_source")
    coupling = ToolCouplingPlan(
        plan_id="plan:hotel-tool-singletons",
        architecture_ref=architecture_ref,
        groups=(
            ToolCouplingGroupPlan(
                group_id="group:booking",
                ordered_tool_ids=("hotel.search", "hotel.reserve"),
                namespaces=("hotel",),
                coupling_reasons=("state_overlap",),
                mode="multi_batch",
                batches=(("hotel.search",), ("hotel.reserve",)),
            ),
        ),
        execution_batches=(("hotel.search",), ("hotel.reserve",)),
    )
    legacy_definitions, _ = derive_final_design_definitions(
        scope_id="job:hotel",
        bootstrap_definitions=(plan, acquisition, synthesis, architecture),
        architecture_source_ref=architecture_ref,
        coupling_plan=coupling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    world_definitions, modeling = derive_world_plan_definitions(
        scope_id="job:hotel",
        bootstrap_definitions=(plan, acquisition, synthesis, architecture),
        architecture_source_ref=architecture_ref,
        coupling_plan=coupling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    curriculum_plan = CurriculumPlanSourceDraft(
        coverage_dimensions=(CoverageDimension(dimension="reservation"),),
        task_plans=(
            CurriculumTaskPlanSourceDraft(
                task_type="reservation-create",
                objective="Create a reservation for the requested room.",
                allowed_actor_ids=("user",),
                required_tool_ids=("hotel.reserve",),
                difficulty_dimensions=("lead-time",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="lead-time",
                description="Requested reservation lead time.",
                levels=("short", "long"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )
    task_definitions, _ = derive_task_requirement_design_definitions(
        scope_id="job:hotel",
        world_definitions=world_definitions,
        curriculum_plan_ref=_artifact_ref(
            "curriculum-plan:hotel",
            "design.curriculum_plan_source",
        ),
        curriculum_plan=curriculum_plan,
        modeling_template=modeling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    direct_agent_definitions = tuple(
        definition
        for definition in (*legacy_definitions, *task_definitions)
        if definition.proposal_policy.executor == "agent"
    )

    assert direct_agent_definitions
    assert all(
        definition.proposal_policy.implementation_revision_id != "framework.impl.unversioned.v0"
        for definition in direct_agent_definitions
    )
    assert all(
        current_runtime_revisions_for_definition(definition)
        == (
            definition.proposal_policy.implementation_revision_id,
            definition.validation_policy.validator_revision_id,
        )
        for definition in direct_agent_definitions
    )


def test_builder_agent_definitions_bind_current_prompt_skill_and_validator_revisions() -> None:
    """Every Builder Agent boundary supports a causal implementation refresh."""

    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=1,
    )
    definitions = {
        item.coordinate.stage: item
        for item in graph.definitions
        if item.coordinate.component == "build"
    }

    implementation_plan = definitions["implementation_plan"]
    candidate_build = definitions["candidate_build"]
    assert current_runtime_revisions_for_definition(implementation_plan) == (
        implementation_plan.proposal_policy.implementation_revision_id,
        implementation_plan.validation_policy.validator_revision_id,
    )
    assert current_runtime_revisions_for_definition(candidate_build) == (
        candidate_build.proposal_policy.implementation_revision_id,
        candidate_build.validation_policy.validator_revision_id,
    )
    assert implementation_plan.proposal_policy.implementation_revision_id.startswith(
        "framework.build-implementation-plan."
    )
    assert implementation_plan.validation_policy.validator_revision_id.startswith(
        "framework.validator-build-implementation-plan."
    )
    assert candidate_build.proposal_policy.implementation_revision_id.startswith(
        "framework.build-candidate."
    )
    assert candidate_build.validation_policy.validator_revision_id.startswith(
        "framework.validator-build-candidate."
    )
    # CandidateBuild reserves one same-workspace pre-commit correction as part
    # of the Code Agent's own build/test/debug loop.  This is deliberately not
    # a Scheduler RepairAction or an unbounded retry budget.
    assert candidate_build.proposal_policy.budget.agent_turns == 2
    assert implementation_plan.proposal_policy.budget.agent_turns == 1


def test_runtime_refresh_restores_candidate_bounded_development_turn() -> None:
    """A stale diagnostic Candidate definition cannot disable its own dev loop.

    This is the true current-runtime budget projection used by
    ``--refresh-current-implementation``.  The frozen source models the exact
    old single-turn Candidate definition that passed a first build but would
    otherwise have suppressed its framework-owned, same-workspace correction.
    """

    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=1,
    )
    candidate = next(
        item for item in graph.definitions if item.coordinate.stage == "candidate_build"
    )
    stale_candidate = candidate.model_copy(
        update={
            "proposal_policy": candidate.proposal_policy.model_copy(
                update={
                    "budget": candidate.proposal_policy.budget.model_copy(update={"agent_turns": 1})
                }
            )
        }
    )

    refreshed_budget = test_node_module._current_runtime_operation_budget(  # noqa: SLF001
        app=None,
        source=SimpleNamespace(definition=stale_candidate),
    )

    assert stale_candidate.proposal_policy.budget.agent_turns == 1
    assert refreshed_budget == candidate.proposal_policy.budget
    assert refreshed_budget.agent_turns == CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS


def test_assured_code_definitions_bind_current_execution_and_feedback_revisions() -> None:
    """Judge code leaves must be refreshable after an execution/feedback fix."""

    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=1,
    )
    definitions = {
        (item.coordinate.component, item.coordinate.stage): item for item in graph.definitions
    }

    integration = definitions[("integration", "runtime_integration")]
    release_assurance = definitions[("judge", "release_assurance")]
    for definition, implementation_prefix, validator_prefix in (
        (
            integration,
            "framework.integration-runtime.",
            "framework.validator-runtime-integration.",
        ),
        (
            release_assurance,
            "framework.judge-release-assurance.",
            "framework.validator-release-assurance.",
        ),
    ):
        assert current_runtime_revisions_for_definition(definition) == (
            definition.proposal_policy.implementation_revision_id,
            definition.validation_policy.validator_revision_id,
        )
        assert definition.proposal_policy.implementation_revision_id.startswith(
            implementation_prefix
        )
        assert definition.validation_policy.validator_revision_id.startswith(validator_prefix)


def test_graph_derives_descendant_invalidation_and_exact_parent_repair() -> None:
    architecture = _definition("architecture")
    behavior = _definition("behavior", (architecture.coordinate,))
    rules = _definition("rules", (behavior.coordinate,))
    curriculum = _definition("curriculum", (rules.coordinate,))
    graph = GenerationWorkGraph.compile(
        (architecture, behavior, rules, curriculum),
        mode="diagnostic",
    )

    assert graph.descendants(architecture.coordinate) == (
        behavior.coordinate,
        rules.coordinate,
        curriculum.coordinate,
    )
    assert (
        graph.automatic_repair_target(
            current=behavior.coordinate,
            proposed_target=behavior.coordinate,
        )
        == behavior
    )
    with pytest.raises(WorkGraphError, match="declared causal edge"):
        graph.automatic_repair_target(
            current=behavior.coordinate,
            proposed_target=architecture.coordinate,
        )
    with pytest.raises(WorkGraphError, match="declared causal edge"):
        graph.automatic_repair_target(
            current=curriculum.coordinate,
            proposed_target=architecture.coordinate,
        )

    repairable_behavior = behavior.model_copy(
        update={
            "repair_target_coordinates": (architecture.coordinate,),
            "repair_policy": behavior.repair_policy.model_copy(
                update={"maximum_automatic_backjump": 1}
            ),
        }
    )
    repair_graph = GenerationWorkGraph.compile(
        (architecture, repairable_behavior, rules, curriculum),
        mode="diagnostic",
    )
    assert (
        repair_graph.automatic_repair_target(
            current=repairable_behavior.coordinate,
            proposed_target=architecture.coordinate,
        )
        == architecture
    )


def test_strict_graph_rejects_an_input_without_a_direct_typed_producer() -> None:
    """Direct/Evolve topology errors fail before an Agent or tool is admitted."""

    producer = deterministic_boundary_work_definition(
        scope_id="job:closure",
        component="design",
        stage="producer",
        artifact_slot="producer",
        dependency_coordinates=(),
        claim_id="producer.passed",
        claim="The producer emits one typed Artifact.",
        timing_reason="The child needs an exact immutable input.",
        effect="block_compile",
        success_maturity="producer_passed",
    ).model_copy(
        update={
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:available",
                    direction="output",
                    artifact_types=("design.available",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            )
        }
    )
    consumer = deterministic_boundary_work_definition(
        scope_id="job:closure",
        component="release",
        stage="consumer",
        artifact_slot="consumer",
        dependency_coordinates=(producer.coordinate,),
        claim_id="consumer.passed",
        claim="The consumer receives only declared parent inputs.",
        timing_reason="The release boundary must be data-contract complete.",
        effect="block_release",
        success_maturity="consumer_passed",
    ).model_copy(
        update={
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:missing",
                    direction="input",
                    artifact_types=("design.missing",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )

    with pytest.raises(WorkGraphError, match="direct parent output"):
        GenerationWorkGraph.compile(
            (producer, consumer),
            mode="diagnostic",
            strict_input_contracts=True,
        )


def test_graph_rejects_missing_dependencies_duplicate_coordinates_and_cycles() -> None:
    architecture = _definition("architecture")
    missing = _definition("behavior", (_coordinate("not-registered"),))
    with pytest.raises(WorkGraphError, match="not registered"):
        GenerationWorkGraph.compile((architecture, missing), mode="diagnostic")
    with pytest.raises(WorkGraphError, match="duplicate coordinates"):
        GenerationWorkGraph.compile(
            (architecture, architecture.model_copy(update={"work_id": "work:duplicate"})),
            mode="diagnostic",
        )

    left = _definition("left")
    right = _definition("right", (left.coordinate,))
    cyclic_left = left.model_copy(update={"dependency_coordinates": (right.coordinate,)})
    with pytest.raises(WorkGraphError, match="cycle"):
        GenerationWorkGraph.compile((cyclic_left, right), mode="diagnostic")

    sibling = _definition("sibling")
    illegal_repair = right.model_copy(
        update={
            "repair_target_coordinates": (sibling.coordinate,),
            "repair_policy": right.repair_policy.model_copy(
                update={"maximum_automatic_backjump": 1}
            ),
        }
    )
    with pytest.raises(WorkGraphError, match="causal dependency ancestor"):
        GenerationWorkGraph.compile((left, sibling, illegal_repair), mode="diagnostic")


def test_threshold_join_is_rejected_until_exact_child_selection_is_executable() -> None:
    with pytest.raises(ValidationError):
        JoinPolicy.model_validate({"mode": "at_least", "minimum_commits": 1})


def test_graph_freezes_release_topology_and_diagnostic_graph_is_not_releasable() -> None:
    architecture = _definition("architecture")
    behavior = _definition("behavior", (architecture.coordinate,))
    diagnostic = GenerationWorkGraph.compile((architecture,), mode="diagnostic")
    assert not diagnostic.release_eligible

    with pytest.raises(WorkGraphError, match="complete generation topology"):
        GenerationWorkGraph.compile(
            (architecture, behavior),
            mode="production",
        )

    staged = GenerationWorkGraph.compile((architecture, behavior), mode="diagnostic")
    assert staged.required_terminal_coordinates == (behavior.coordinate,)
    assert staged.graph_digest != diagnostic.graph_digest


def test_generation_context_and_epoch_bind_one_dynamic_graph_freeze() -> None:
    context = GenerationContext(
        context_id="context:hotel",
        job_ref=_artifact_ref("job:hotel", "control.environment_job"),
        kind="generate",
        request_ref=_artifact_ref("request:hotel", "control.environment_request"),
        permissions=PermissionScope(network_domains=("example.com",)),
        budget=Budget(agent_turns=10, wall_seconds=3_600),
        release_profile=ReleaseProfile(profile_id="release:hotel"),
    )
    context_ref = _artifact_ref("context:hotel", "control.generation_context")
    bootstrap_ref = _artifact_ref("epoch:bootstrap", "control.work_graph_epoch")
    bootstrap = WorkGraphEpoch(
        epoch_id="epoch:bootstrap",
        scope_id="job:hotel",
        epoch_kind="bootstrap",
        context_ref=context_ref,
        manifest_ref=_artifact_ref("graph:bootstrap", "control.work_graph_manifest"),
    )
    assert context.root_refs == (context.job_ref, context.request_ref)
    assert bootstrap.retained_commit_refs == ()

    final = WorkGraphEpoch(
        epoch_id="epoch:final",
        scope_id="job:hotel",
        epoch_kind="final",
        context_ref=context_ref,
        manifest_ref=_artifact_ref("graph:final", "control.work_graph_manifest"),
        predecessor_epoch_ref=bootstrap_ref,
        retained_commit_refs=(_artifact_ref("commit:architecture", "control.work_commit"),),
    )
    assert final.predecessor_epoch_ref == bootstrap_ref
    with pytest.raises(ValidationError, match="retained commits"):
        WorkGraphEpoch(
            epoch_id="epoch:bad-final",
            scope_id="job:hotel",
            epoch_kind="final",
            context_ref=context_ref,
            manifest_ref=_artifact_ref("graph:bad-final", "control.work_graph_manifest"),
            predecessor_epoch_ref=bootstrap_ref,
        )


def _stage_definition(
    *,
    component: str,
    stage: str,
    dependencies: tuple[WorkCoordinate, ...] = (),
):
    return deterministic_boundary_work_definition(
        scope_id="job:hotel",
        component=component,  # type: ignore[arg-type]
        stage=stage,
        artifact_slot=stage,
        dependency_coordinates=dependencies,
        claim_id=f"{component}.{stage}.passed",
        claim=f"{component}/{stage} establishes its exact typed checkpoint.",
        timing_reason="The final production topology must bind every causal stage.",
        effect="block_release",
        success_maturity=f"{stage}_closed",
    )


def _complete_design_closure() -> tuple[tuple[WorkDefinition, ...], WorkDefinition]:
    plan = _stage_definition(component="research", stage="research_plan")
    acquisition = _stage_definition(
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan.coordinate,),
    )
    synthesis = _stage_definition(
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
    )
    architecture = _stage_definition(
        component="design",
        stage="world_architecture",
        dependencies=(synthesis.coordinate,),
    )
    behavior = _stage_definition(
        component="design",
        stage="tool_semantics_batch",
        dependencies=(architecture.coordinate,),
    )
    rules = _stage_definition(
        component="design",
        stage="world_rules",
        dependencies=(behavior.coordinate,),
    )
    curriculum_plan = _stage_definition(
        component="design",
        stage="curriculum_plan",
        dependencies=(rules.coordinate,),
    )
    task_requirement = _stage_definition(
        component="design",
        stage="task_requirement",
        dependencies=(rules.coordinate, curriculum_plan.coordinate),
    ).model_copy(
        update={
            "coordinate": WorkCoordinate(
                scope_id="job:hotel",
                component="design",
                stage="task_requirement",
                artifact_slot="task_requirement_source",
                group_id="task-requirements",
                shard_id="counter-increment",
            )
        }
    )
    curriculum = _stage_definition(
        component="design",
        stage="task_curriculum",
        dependencies=(rules.coordinate, curriculum_plan.coordinate, task_requirement.coordinate),
    )
    modeling = _stage_definition(
        component="design",
        stage="modeling_boundary",
        dependencies=(curriculum.coordinate,),
    ).model_copy(
        update={
            "coordinate": WorkCoordinate(
                scope_id="job:hotel",
                component="design",
                stage="modeling_boundary",
                artifact_slot="environment_design",
            )
        }
    )
    return (
        plan,
        acquisition,
        synthesis,
        architecture,
        behavior,
        rules,
        curriculum_plan,
        task_requirement,
        curriculum,
    ), modeling


def _design_graph(
    definitions: tuple[WorkDefinition, ...],
    modeling: WorkDefinition,
) -> GenerationWorkGraph:
    verifier_plan = verifier_plan_work_definition(
        scope_id="job:hotel",
        modeling_coordinate=modeling.coordinate,
    )
    return compile_design_work_graph(
        scope_id="job:hotel",
        design_definitions=definitions,
        modeling_definition=modeling,
        verifier_plan_definition=verifier_plan,
    )


def test_final_graph_sizes_judge_work_from_frozen_design_and_plan(
    tmp_path,
) -> None:
    """A real final graph cannot substitute a fixed probe count for its Design."""

    design_definitions, modeling = _complete_design_closure()
    design = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design
    plan = VerifierBatchPlan(
        plan_id="verifier-plan:budget-derived",
        design_ref=_artifact_ref("design:budget-derived", "design.environment_design"),
        world_spec_ref=_artifact_ref("world:budget-derived", "design.world_spec"),
        maximum_tasks_per_batch=1,
        batches=(
            VerifierBatchPlanItem(
                batch_id="verifier-batch:budget-derived",
                batch_index=0,
                task_types=(design.curriculum.task_types[0].task_type,),
                required_rule_ids=(),
                required_property_families=(),
                semantic_case_limit=2,
                context_hash=sha256_digest(b"budget-derived"),
            ),
        ),
    )
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=len(plan.batches),
        environment_design=design,
        verifier_batch_plan=plan,
    )
    definitions = {
        (item.coordinate.component, item.coordinate.stage): item for item in graph.definitions
    }

    integration = definitions[("integration", "runtime_integration")]
    release = definitions[("judge", "release_assurance")]
    assert integration.proposal_policy.budget.evaluation_episodes == (
        integration_budget_requirements(design).evaluation_episodes
    )
    assert (
        integration.proposal_policy.budget.tool_calls
        == integration_budget_requirements(design).tool_calls
    )
    assert release.proposal_policy.budget.evaluation_episodes == (
        release_without_interactive_budget_requirements(design, plan).evaluation_episodes
    )
    assert (
        release.proposal_policy.budget.tool_calls
        == release_without_interactive_budget_requirements(design, plan).tool_calls
    )


def test_strict_final_graph_rejects_missing_frozen_judge_budget_inputs() -> None:
    design_definitions, modeling = _complete_design_closure()

    with pytest.raises(WorkGraphError, match="EnvironmentDesign and VerifierPlan"):
        complete_generation_work_graph(
            scope_id="job:hotel",
            design_graph=_design_graph(design_definitions, modeling),
            verifier_batch_count=1,
            strict_input_contracts=True,
        )


def test_complete_generation_graph_cannot_stop_at_modeling_boundary() -> None:
    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=1,
    )

    stages = {item.coordinate.stage for item in graph.definitions}
    assert {
        "modeling_boundary",
        "implementation_plan",
        "candidate_build",
        "verifier_plan",
        "verifier_intent_batch",
        "verifier_intent",
        "runtime_integration",
        "release_assurance",
        "observability_closure",
        "package",
        "publication",
    } <= stages
    assert tuple(item.stage for item in graph.required_terminal_coordinates) == ("publication",)
    manifest = graph.manifest(topology_id="topology:complete")
    assert manifest.releasable
    assert {item.kind for item in manifest.milestone_bindings} == {
        "release_candidate",
        "released",
    }
    implementation_plan = next(
        item for item in graph.definitions if item.coordinate.stage == "implementation_plan"
    )
    build = next(item for item in graph.definitions if item.coordinate.stage == "candidate_build")
    assert implementation_plan.dependency_coordinates == (modeling.coordinate,)
    assert implementation_plan.proposal_policy.budget.build_seconds == 0
    assert implementation_plan.proposal_policy.budget.first_progress_seconds is None
    assert implementation_plan.proposal_policy.budget.first_write_seconds is None
    assert implementation_plan.proposal_policy.budget.llm_tokens == 16_384
    assert build.proposal_policy.budget.build_seconds == 1_200
    assert build.proposal_policy.budget.first_progress_seconds is None
    assert build.proposal_policy.budget.first_write_seconds is None
    assert implementation_plan.coordinate in build.dependency_coordinates
    assert {
        artifact_type for slot in build.input_slots for artifact_type in slot.artifact_types
    } >= {
        "build.implementation_contract",
        "build.implementation_plan",
    }
    release_assurance = next(
        item for item in graph.definitions if item.coordinate.stage == "release_assurance"
    )
    assert build.coordinate in release_assurance.dependency_coordinates
    assert build.coordinate in release_assurance.repair_target_coordinates


def test_agent_work_definitions_do_not_add_short_progress_or_write_deadlines() -> None:
    """LLM work inherits its declared logical envelope without a hidden liveness cap."""

    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=1,
    )

    agent_definitions = [
        definition
        for definition in graph.definitions
        if definition.proposal_policy.executor == "agent"
    ]
    assert agent_definitions
    assert all(
        definition.proposal_policy.budget.first_progress_seconds is None
        and definition.proposal_policy.budget.first_write_seconds is None
        for definition in agent_definitions
    )


def test_implementation_plan_splits_a_5m_logical_session_into_observable_provider_turns() -> None:
    design_definitions, modeling = _complete_design_closure()

    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        implementation_plan_token_limit=128_000,
        implementation_plan_wall_seconds=28_800,
        implementation_plan_session_token_limit=5_000_000,
        implementation_plan_session_wall_seconds=28_800,
        verifier_batch_count=1,
    )

    implementation_plan = next(
        item for item in graph.definitions if item.coordinate.stage == "implementation_plan"
    )
    assert implementation_plan.proposal_policy.budget.llm_tokens == 125_000
    assert implementation_plan.proposal_policy.budget.wall_seconds == 720
    assert implementation_plan.proposal_policy.session_token_limit == 5_000_000
    assert implementation_plan.proposal_policy.session_wall_seconds == 28_800
    assert implementation_plan.repair_policy.maximum_session_continuations == 39


def test_candidate_build_splits_a_5m_logical_session_into_observable_provider_turns() -> None:
    design_definitions, modeling = _complete_design_closure()

    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        builder_token_limit=128_000,
        builder_wall_seconds=28_800,
        builder_session_token_limit=5_000_000,
        builder_session_wall_seconds=28_800,
        verifier_batch_count=1,
    )

    build = next(item for item in graph.definitions if item.coordinate.stage == "candidate_build")
    assert build.proposal_policy.budget.llm_tokens == 125_000
    assert build.proposal_policy.budget.wall_seconds == 720
    assert build.proposal_policy.session_token_limit == 5_000_000
    assert build.proposal_policy.session_wall_seconds == 28_800
    assert build.repair_policy.maximum_session_continuations == 39


def test_candidate_build_rejects_a_partial_logical_session_envelope() -> None:
    design_definitions, modeling = _complete_design_closure()

    with pytest.raises(WorkGraphError, match="must be declared together"):
        complete_generation_work_graph(
            scope_id="job:hotel",
            design_graph=_design_graph(design_definitions, modeling),
            builder_session_token_limit=5_000_000,
            verifier_batch_count=1,
        )


def test_implementation_plan_rejects_a_partial_logical_session_envelope() -> None:
    design_definitions, modeling = _complete_design_closure()

    with pytest.raises(WorkGraphError, match="must be declared together"):
        complete_generation_work_graph(
            scope_id="job:hotel",
            design_graph=_design_graph(design_definitions, modeling),
            implementation_plan_session_token_limit=5_000_000,
            verifier_batch_count=1,
        )


def test_final_design_suffix_is_derived_only_from_frozen_tool_coupling_plan() -> None:
    """Architecture is the sole dynamic-topology boundary for the final epoch."""

    plan = _stage_definition(component="research", stage="research_plan")
    acquisition = _stage_definition(
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan.coordinate,),
    )
    synthesis = _stage_definition(
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
    )
    architecture = _stage_definition(
        component="design",
        stage="world_architecture",
        dependencies=(synthesis.coordinate,),
    )
    coupling = ToolCouplingPlan(
        plan_id="plan:hotel-tools",
        architecture_ref=_artifact_ref("architecture:hotel", "design.world_architecture_source"),
        groups=(
            ToolCouplingGroupPlan(
                group_id="group:booking",
                ordered_tool_ids=(
                    "hotel.search",
                    "hotel.hold",
                    "hotel.confirm",
                    "hotel.cancel",
                    "hotel.modify",
                ),
                namespaces=("hotel",),
                coupling_reasons=("namespace", "state_overlap"),
                mode="multi_batch",
                batches=(
                    ("hotel.search",),
                    ("hotel.hold",),
                    ("hotel.confirm",),
                    ("hotel.cancel",),
                    ("hotel.modify",),
                ),
            ),
        ),
        execution_batches=(
            ("hotel.search",),
            ("hotel.hold",),
            ("hotel.confirm",),
            ("hotel.cancel",),
            ("hotel.modify",),
        ),
    )

    world_definitions, modeling_template = derive_world_plan_definitions(
        scope_id="job:hotel",
        bootstrap_definitions=(plan, acquisition, synthesis, architecture),
        architecture_source_ref=coupling.architecture_ref,
        coupling_plan=coupling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    shared = tuple(
        item for item in world_definitions if item.coordinate.stage == "shared_tool_semantics"
    )
    batches = tuple(item for item in world_definitions if item.coordinate.stage == "world_behavior")
    rules = next(item for item in world_definitions if item.coordinate.stage == "world_rules")
    curriculum_plan = next(
        item for item in world_definitions if item.coordinate.stage == "curriculum_plan"
    )

    assert len(shared) == 1
    assert shared[0].coordinate.group_id == "group:booking"
    assert tuple(item.coordinate.shard_id for item in batches) == (
        "tool-batch-1",
        "tool-batch-2",
        "tool-batch-3",
        "tool-batch-4",
        "tool-batch-5",
    )
    assert all(
        item.dependency_coordinates
        == (architecture.coordinate, synthesis.coordinate, shared[0].coordinate)
        for item in batches
    )
    assert all(
        next(
            slot for slot in item.output_slots if slot.slot_id == "output:tool-semantics"
        ).minimum_count
        == 1
        for item in batches
    )
    assert rules.dependency_coordinates == (
        architecture.coordinate,
        synthesis.coordinate,
        *(item.coordinate for item in batches),
    )
    assert rules.proposal_policy.acceptance_transform_id == "framework.world-rules-compiler.v4"
    assert rules.validation_policy.validator_revision_id.startswith(
        "framework.validator-world-rules."
    )
    assert curriculum_plan.dependency_coordinates == (
        synthesis.coordinate,
        architecture.coordinate,
        rules.coordinate,
    )
    assert all(
        item.proposal_policy.budget.agent_turns == 1
        for item in (*shared, *batches, rules, curriculum_plan)
    )
    assert all(
        (
            item.repair_policy.maximum_local_corrections,
            item.repair_policy.strict_progress_bonus_corrections,
            item.repair_policy.maximum_infrastructure_retries,
            item.repair_policy.maximum_total_repair_attempts,
        )
        == (1, 1, 1, 8)
        for item in batches
    )
    assert all(
        item.input_slots and item.output_slots
        for item in (*shared, *batches, rules, curriculum_plan)
    )

    world_graph = compile_world_work_graph(
        scope_id="job:hotel",
        world_definitions=world_definitions,
    )
    assert world_graph.required_terminal_coordinates == (curriculum_plan.coordinate,)

    plan_source = CurriculumPlanSourceDraft(
        coverage_dimensions=(CoverageDimension(dimension="counter"),),
        task_plans=(
            CurriculumTaskPlanSourceDraft(
                task_type="counter-increment",
                objective="Increase the counter to the requested target.",
                allowed_actor_ids=("user",),
                required_tool_ids=("hotel.search",),
                difficulty_dimensions=("target-size",),
            ),
            CurriculumTaskPlanSourceDraft(
                task_type="counter-inspect",
                objective="Inspect the current counter value.",
                allowed_actor_ids=("user",),
                required_tool_ids=("hotel.hold",),
                difficulty_dimensions=("target-size",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="target-size",
                description="Requested target magnitude.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )
    definitions, modeling = derive_task_requirement_design_definitions(
        scope_id="job:hotel",
        world_definitions=world_definitions,
        curriculum_plan_ref=_artifact_ref(
            "curriculum-plan:hotel",
            "design.curriculum_plan_source",
        ),
        curriculum_plan=plan_source,
        modeling_template=modeling_template,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    requirements = tuple(
        item for item in definitions if item.coordinate.stage == "task_requirement"
    )
    curriculum = next(item for item in definitions if item.coordinate.stage == "task_curriculum")
    assert tuple(item.coordinate.shard_id for item in requirements) == (
        "counter-increment",
        "counter-inspect",
    )
    assert all(item.coordinate.group_id == "task-requirements" for item in requirements)
    assert curriculum.dependency_coordinates == (
        synthesis.coordinate,
        architecture.coordinate,
        rules.coordinate,
        curriculum_plan.coordinate,
        *(item.coordinate for item in requirements),
    )
    assert modeling.dependency_coordinates == (
        synthesis.coordinate,
        architecture.coordinate,
        rules.coordinate,
        curriculum.coordinate,
    )

    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(definitions, modeling),
        verifier_batch_count=1,
    )
    assert graph.release_eligible
    assert graph.require(architecture.coordinate) == architecture

    historical_multi_tool_coupling = coupling.model_copy(
        update={
            "execution_batches": (
                ("hotel.search", "hotel.hold"),
                ("hotel.confirm",),
                ("hotel.cancel",),
                ("hotel.modify",),
            )
        }
    )
    with pytest.raises(WorkGraphError, match="singleton physical tool shards"):
        derive_final_design_definitions(
            scope_id="job:hotel",
            bootstrap_definitions=(plan, acquisition, synthesis, architecture),
            architecture_source_ref=historical_multi_tool_coupling.architecture_ref,
            coupling_plan=historical_multi_tool_coupling,
            agent_wall_seconds=120,
            agent_token_limit=10_000,
        )


def test_final_design_suffix_does_not_create_shared_contract_for_single_batch_group() -> None:
    synthesis = _stage_definition(component="research", stage="evidence_synthesis")
    architecture = _stage_definition(component="design", stage="world_architecture")
    coupling = ToolCouplingPlan(
        plan_id="plan:single-tool",
        architecture_ref=_artifact_ref(
            "architecture:single-tool", "design.world_architecture_source"
        ),
        groups=(
            ToolCouplingGroupPlan(
                group_id="group:search",
                ordered_tool_ids=("hotel.search",),
                namespaces=("hotel",),
                coupling_reasons=("namespace",),
                mode="single_batch",
                batches=(("hotel.search",),),
            ),
        ),
        execution_batches=(("hotel.search",),),
    )
    definitions, _modeling = derive_final_design_definitions(
        scope_id="job:hotel",
        bootstrap_definitions=(synthesis, architecture),
        architecture_source_ref=coupling.architecture_ref,
        coupling_plan=coupling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    batch = next(item for item in definitions if item.coordinate.stage == "world_behavior")

    assert not [item for item in definitions if item.coordinate.stage == "shared_tool_semantics"]
    assert batch.dependency_coordinates == (architecture.coordinate, synthesis.coordinate)
    assert all(slot.slot_id != "input:shared-tool-semantics-contract" for slot in batch.input_slots)


def test_final_design_suffix_rejects_a_coupling_plan_from_another_architecture() -> None:
    synthesis = _stage_definition(component="research", stage="evidence_synthesis")
    architecture = _stage_definition(component="design", stage="world_architecture")
    coupling = ToolCouplingPlan(
        plan_id="plan:stale",
        architecture_ref=_artifact_ref("architecture:old", "design.world_architecture_source"),
        groups=(
            ToolCouplingGroupPlan(
                group_id="group:search",
                ordered_tool_ids=("hotel.search",),
                namespaces=("hotel",),
                coupling_reasons=("namespace",),
                mode="single_batch",
                batches=(("hotel.search",),),
            ),
        ),
        execution_batches=(("hotel.search",),),
    )

    with pytest.raises(WorkGraphError, match="not bound"):
        derive_final_design_definitions(
            scope_id="job:hotel",
            bootstrap_definitions=(synthesis, architecture),
            architecture_source_ref=_artifact_ref(
                "architecture:new", "design.world_architecture_source"
            ),
            coupling_plan=coupling,
            agent_wall_seconds=120,
            agent_token_limit=10_000,
        )


def test_complete_generation_graph_freezes_every_verifier_agent_batch_as_physical_work() -> None:
    """A batch count is real scheduler topology, never compiler-internal fan-out.

    This is the regression for the old verifier shape, where a nominal one-node
    WorkGraph could conceal several Challenger invocations.  Each call needs an
    independent operation budget, provenance record and causal repair target;
    only deterministic aggregation may sit behind the group join.
    """

    design_definitions, modeling = _complete_design_closure()
    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(design_definitions, modeling),
        verifier_batch_count=3,
    )

    batches = tuple(
        definition
        for definition in graph.definitions
        if (
            definition.coordinate.component == "verifier"
            and definition.coordinate.stage == "verifier_intent_batch"
        )
    )
    assert len(batches) == 3
    assert tuple(item.coordinate.shard_id for item in batches) == (
        "batch-1",
        "batch-2",
        "batch-3",
    )
    assert all(item.coordinate.group_id == "verifier-intent-batches" for item in batches)
    assert all(item.proposal_policy.executor == "agent" for item in batches)
    assert all(item.proposal_policy.budget.agent_turns == 1 for item in batches)
    assert all(
        item.proposal_policy.implementation_revision_id.startswith(
            "framework.verifier-intent-batch."
        )
        for item in batches
    )
    assert all(
        item.validation_policy.validator_revision_id.startswith(
            "framework.validator-verifier-intent-batch."
        )
        for item in batches
    )
    assert all(
        current_runtime_revisions_for_definition(item)
        == (
            item.proposal_policy.implementation_revision_id,
            item.validation_policy.validator_revision_id,
        )
        for item in batches
    )
    verifier_plan = next(
        definition
        for definition in graph.definitions
        if (
            definition.coordinate.component == "verifier"
            and definition.coordinate.stage == "verifier_plan"
        )
    )
    assert verifier_plan.dependency_coordinates == (modeling.coordinate,)
    assert verifier_plan.proposal_policy.executor == "code"
    assert current_runtime_revisions_for_definition(verifier_plan) == (
        verifier_plan.proposal_policy.implementation_revision_id,
        verifier_plan.validation_policy.validator_revision_id,
    )
    assert verifier_plan.proposal_policy.implementation_revision_id.startswith(
        "framework.verifier-plan."
    )
    assert verifier_plan.validation_policy.validator_revision_id.startswith(
        "framework.validator-verifier-plan."
    )
    assert all(item.dependency_coordinates == (verifier_plan.coordinate,) for item in batches)
    assert all(
        item.input_slots[0].artifact_types == ("judge.verifier_batch_plan",) for item in batches
    )
    assert all(
        tuple(slot.artifact_types for slot in item.output_slots)
        == (
            ("judge.verifier_intent_checkpoint",),
            ("judge.verifier_batch_draft",),
        )
        for item in batches
    )

    aggregate = next(
        definition
        for definition in graph.definitions
        if (
            definition.coordinate.component == "verifier"
            and definition.coordinate.stage == "verifier_intent"
        )
    )
    assert aggregate.coordinate.group_id == "verifier-intent-batches"
    assert aggregate.coordinate.shard_id is None
    assert aggregate.proposal_policy.executor == "code"
    assert aggregate.proposal_policy.budget.agent_turns == 0
    assert aggregate.dependency_coordinates == tuple(item.coordinate for item in batches)
    # A committed child WorkCommit already proves the public checkpoint;
    # aggregation needs only the sealed draft bytes it actually compiles.
    assert tuple(slot.artifact_types for slot in aggregate.input_slots) == (
        ("judge.verifier_batch_draft",),
    )
    assert aggregate.input_slots[0].minimum_count == 3
    assert aggregate.input_slots[0].maximum_count == 3

    group = next(item for item in graph.groups if item.group_id == "verifier-intent-batches")
    assert group.member_coordinates == tuple(item.coordinate for item in batches)
    assert group.aggregate_coordinate == aggregate.coordinate
    release_assurance = next(
        definition
        for definition in graph.definitions
        if definition.coordinate.stage == "release_assurance"
    )
    assert aggregate.coordinate in release_assurance.dependency_coordinates
    # release_assurance rebuilds the full VerifierIR (with sealed cases) from
    # the per-batch verifier drafts, so it must depend on every batch
    # coordinate (parent_output_refs only projects direct parents).
    assert {item.coordinate for item in batches} <= set(release_assurance.dependency_coordinates)


def test_work_group_freezes_members_and_requires_exact_aggregate_join() -> None:
    member_one_coordinate = WorkCoordinate(
        scope_id="job:hotel",
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_intent",
        group_id="verifier-batches",
        shard_id="batch-1",
    )
    member_two_coordinate = member_one_coordinate.model_copy(update={"shard_id": "batch-2"})
    aggregate_coordinate = WorkCoordinate(
        scope_id="job:hotel",
        component="verifier",
        stage="verifier_intent_aggregate",
        artifact_slot="verifier_intent_aggregate",
        group_id="verifier-batches",
    )
    template = _definition("verifier-template")
    member_one = template.model_copy(
        update={"work_id": "work:verifier:1", "coordinate": member_one_coordinate}
    )
    member_two = template.model_copy(
        update={"work_id": "work:verifier:2", "coordinate": member_two_coordinate}
    )
    aggregate = template.model_copy(
        update={
            "work_id": "work:verifier:aggregate",
            "coordinate": aggregate_coordinate,
            "dependency_coordinates": (member_one_coordinate, member_two_coordinate),
        }
    )
    group = WorkGroupDefinition(
        group_id="verifier-batches",
        scope_id="job:hotel",
        member_coordinates=(member_one_coordinate, member_two_coordinate),
        aggregate_coordinate=aggregate_coordinate,
        join_policy=JoinPolicy(mode="all"),
    )
    graph = GenerationWorkGraph.compile(
        (member_one, member_two, aggregate),
        groups=(group,),
        mode="diagnostic",
    )
    assert graph.groups == (group,)
    assert graph.manifest(topology_id="topology:test").group_bindings[0].group_id == (
        "verifier-batches"
    )

    broken_aggregate = aggregate.model_copy(
        update={"dependency_coordinates": (member_one_coordinate,)}
    )
    with pytest.raises(WorkGraphError, match="dependencies must equal"):
        GenerationWorkGraph.compile(
            (member_one, member_two, broken_aggregate),
            groups=(group,),
            mode="diagnostic",
        )


def test_tool_semantics_policy_keeps_the_configured_token_budget() -> None:
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(_coordinate("architecture"),),
        agent_wall_seconds=300,
        agent_token_limit=5_000_000,
    )

    assert definition.coordinate.artifact_slot == "tool_semantics_batch"
    assert definition.proposal_policy.budget.agent_turns == 1
    assert definition.proposal_policy.budget.llm_tokens == 5_000_000
    assert definition.proposal_policy.budget.monetary_cost == 0
    assert definition.repair_policy.maximum_local_corrections == 1
    assert definition.repair_policy.strict_progress_bonus_corrections == 1
    assert definition.repair_policy.maximum_infrastructure_retries == 1
    assert definition.repair_policy.maximum_automatic_backjump == 0


def test_model_route_recovery_binding_reaches_every_configured_fallback() -> None:
    agent_definition = research_plan_work_definition(
        scope_id="job:hotel",
        agent_wall_seconds=300,
        agent_token_limit=5_000_000,
    )
    deterministic_definition = research_acquisition_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=agent_definition.coordinate,
        wall_seconds=300,
        maximum_search_calls=3,
        maximum_tool_calls=8,
    )

    bound_agent, bound_deterministic = bind_model_route_recovery_policy(
        (agent_definition, deterministic_definition),
        model_routes=("grok-4.5", "gpt-5.3-codex-spark", "gpt-5.4-mini"),
        maximum_same_model_infrastructure_retries=2,
    )

    assert agent_definition.repair_policy.maximum_model_fallbacks == 1
    assert agent_definition.repair_policy.maximum_total_repair_attempts == 8
    assert bound_agent.repair_policy.maximum_infrastructure_retries == 2
    assert bound_agent.repair_policy.maximum_model_fallbacks == 2
    # Two semantic corrections, two infrastructure retries per model, and two
    # visible model transitions are all identity-bound before graph freezing.
    assert bound_agent.repair_policy.maximum_total_repair_attempts == 10
    assert bound_deterministic.repair_policy == deterministic_definition.repair_policy


def test_research_acquisition_is_real_tools_with_code_owned_evidence_admission() -> None:
    plan = WorkCoordinate(
        scope_id="job:hotel",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
    )
    definition = research_acquisition_work_definition(
        scope_id="job:hotel",
        dependency_coordinate=plan,
        wall_seconds=300,
        maximum_search_calls=3,
        maximum_tool_calls=8,
    )

    assert definition.coordinate.component == "research"
    assert definition.dependency_coordinates == (plan,)
    assert definition.proposal_policy.executor == "real_tools"
    assert definition.proposal_policy.agent_role is None
    assert definition.proposal_policy.tool_ids == (
        "research.search",
        "research.fetch",
        "research.extract",
    )
    assert definition.validation_policy.validator_id == "validator:evidence-acquisition"
    assert definition.validation_policy.effect == "block_compile"
    assert definition.repair_policy.maximum_local_corrections == 0
    assert definition.repair_policy.maximum_infrastructure_retries == 1

    with pytest.raises(ValueError, match="bounded search, fetch, and extract capacity"):
        research_acquisition_work_definition(
            scope_id="job:hotel",
            dependency_coordinate=plan,
            wall_seconds=300,
            maximum_search_calls=3,
            maximum_tool_calls=3,
        )


def test_work_identity_is_stable_across_contract_policy_and_dependency_revisions() -> None:
    dependency_v1 = _coordinate("architecture-v1")
    dependency_v2 = _coordinate("architecture-v2")
    common = {
        "scope_id": "job:hotel",
        "stage": "shared_tool_semantics",
        "artifact_slot": "shared_tool_semantics",
        "claim_id": "design.shared_behavior.closed",
        "claim": "Shared behavior closes.",
        "timing_reason": "Tool batches need a frozen shared policy.",
        "agent_wall_seconds": 120.0,
        "agent_token_limit": 10_000,
        "allowed_mutation_roots": ("/idempotency_domains",),
    }
    structured_v1 = structured_agent_work_definition(
        **common,
        dependency_coordinates=(dependency_v1,),
        output_contract_id="contract:shared-tool-semantics-source.v1",
        validator_revision_id="framework.validator.shared-tool-semantics.v1",
    )
    structured_v2 = structured_agent_work_definition(
        **common,
        dependency_coordinates=(dependency_v2,),
        output_contract_id="contract:shared-tool-semantics-source.v2",
        validator_revision_id="framework.validator.shared-tool-semantics.v2",
    )
    assert structured_v2.coordinate == structured_v1.coordinate
    assert structured_v2.work_id == structured_v1.work_id
    assert structured_v2.proposal_policy.policy_id == structured_v1.proposal_policy.policy_id
    assert structured_v2.validation_policy.policy_id == structured_v1.validation_policy.policy_id
    assert structured_v2.repair_policy.policy_id == structured_v1.repair_policy.policy_id
    assert structured_v2.definition_digest != structured_v1.definition_digest
    assert structured_v2.acceptance_digest != structured_v1.acceptance_digest

    boundary_v1 = deterministic_boundary_work_definition(
        scope_id="job:hotel",
        component="integration",
        stage="runtime_probe",
        artifact_slot="runtime_probe",
        dependency_coordinates=(dependency_v1,),
        claim_id="integration.runtime.responds",
        claim="The runtime responds.",
        timing_reason="Release requires a live runtime probe.",
        effect="block_release",
        success_maturity="integration_probed",
    )
    boundary_v2 = deterministic_boundary_work_definition(
        scope_id="job:hotel",
        component="integration",
        stage="runtime_probe",
        artifact_slot="runtime_probe",
        dependency_coordinates=(dependency_v2,),
        claim_id="integration.runtime.responds",
        claim="The runtime responds.",
        timing_reason="Release requires a live runtime probe.",
        effect="block_release",
        success_maturity="integration_probed",
    )
    assert boundary_v2.work_id == boundary_v1.work_id
    assert boundary_v2.definition_digest != boundary_v1.definition_digest
    assert boundary_v2.acceptance_digest != boundary_v1.acceptance_digest

    batch_v1 = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(dependency_v1,),
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    batch_v2 = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(dependency_v2,),
        agent_wall_seconds=180,
        agent_token_limit=20_000,
    )
    another_batch = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:2",
        dependency_coordinates=(dependency_v1,),
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    assert batch_v2.work_id == batch_v1.work_id
    assert batch_v2.proposal_policy.policy_id == batch_v1.proposal_policy.policy_id
    assert batch_v2.definition_digest != batch_v1.definition_digest
    assert batch_v2.acceptance_digest != batch_v1.acceptance_digest
    assert another_batch.work_id != batch_v1.work_id

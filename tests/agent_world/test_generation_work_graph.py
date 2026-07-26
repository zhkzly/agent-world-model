from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_world.contracts import (
    ArtifactRef,
    Budget,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.control.work import ArtifactSlotContract, WorkCoordinate, WorkDefinition
from agent_world.control.work_graph import (
    GenerationWorkGraph,
    JoinPolicy,
    WorkGraphEpoch,
    WorkGraphError,
    WorkGroupDefinition,
    compile_design_work_graph,
    complete_generation_work_graph,
    derive_final_design_definitions,
    deterministic_boundary_work_definition,
    research_acquisition_work_definition,
    structured_agent_work_definition,
    tool_semantics_batch_definition,
    verifier_plan_work_definition,
)
from agent_world.designer.models import ToolCouplingGroupPlan, ToolCouplingPlan


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
    curriculum = _stage_definition(
        component="design",
        stage="task_curriculum",
        dependencies=(rules.coordinate,),
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
    return (plan, acquisition, synthesis, architecture, behavior, rules, curriculum), modeling


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
    build = next(item for item in graph.definitions if item.coordinate.stage == "candidate_build")
    release_assurance = next(
        item for item in graph.definitions if item.coordinate.stage == "release_assurance"
    )
    assert build.coordinate in release_assurance.dependency_coordinates
    assert build.coordinate in release_assurance.repair_target_coordinates


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
                    ("hotel.search", "hotel.hold"),
                    ("hotel.confirm", "hotel.cancel"),
                    ("hotel.modify",),
                ),
            ),
        ),
        execution_batches=(
            ("hotel.search", "hotel.hold"),
            ("hotel.confirm", "hotel.cancel"),
            ("hotel.modify",),
        ),
    )

    definitions, modeling = derive_final_design_definitions(
        scope_id="job:hotel",
        bootstrap_definitions=(plan, acquisition, synthesis, architecture),
        architecture_source_ref=coupling.architecture_ref,
        coupling_plan=coupling,
        agent_wall_seconds=120,
        agent_token_limit=10_000,
    )
    shared = tuple(item for item in definitions if item.coordinate.stage == "shared_tool_semantics")
    batches = tuple(item for item in definitions if item.coordinate.stage == "world_behavior")
    rules = next(item for item in definitions if item.coordinate.stage == "world_rules")
    curriculum = next(item for item in definitions if item.coordinate.stage == "task_curriculum")

    assert len(shared) == 1
    assert shared[0].coordinate.group_id == "group:booking"
    assert tuple(item.coordinate.shard_id for item in batches) == (
        "tool-batch-1",
        "tool-batch-2",
        "tool-batch-3",
    )
    assert all(shared[0].coordinate in item.dependency_coordinates for item in batches)
    assert rules.dependency_coordinates == (
        architecture.coordinate,
        synthesis.coordinate,
        *(item.coordinate for item in batches),
    )
    assert rules.proposal_policy.acceptance_transform_id == "framework.world-rules-compiler.v4"
    assert rules.validation_policy.validator_revision_id == "framework.validator.world-rules.v4"
    assert curriculum.dependency_coordinates == (
        synthesis.coordinate,
        architecture.coordinate,
        rules.coordinate,
    )
    assert modeling.dependency_coordinates == (
        synthesis.coordinate,
        architecture.coordinate,
        rules.coordinate,
        curriculum.coordinate,
    )
    assert all(
        item.proposal_policy.budget.agent_turns == 1
        for item in (*shared, *batches, rules, curriculum)
    )
    assert all(
        (
            item.repair_policy.maximum_local_corrections,
            item.repair_policy.strict_progress_bonus_corrections,
            item.repair_policy.maximum_infrastructure_retries,
            item.repair_policy.maximum_total_repair_attempts,
        )
        == (1, 1, 1, 3)
        for item in batches
    )
    assert all(
        item.input_slots and item.output_slots for item in (*shared, *batches, rules, curriculum)
    )

    graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=_design_graph(definitions, modeling),
        verifier_batch_count=1,
    )
    assert graph.release_eligible
    assert graph.require(architecture.coordinate) == architecture

    oversized_coupling = coupling.model_copy(
        update={
            "execution_batches": (
                ("hotel.search", "hotel.hold", "hotel.confirm"),
                ("hotel.cancel", "hotel.modify"),
            )
        }
    )
    with pytest.raises(WorkGraphError, match="invalid physical batch"):
        derive_final_design_definitions(
            scope_id="job:hotel",
            bootstrap_definitions=(plan, acquisition, synthesis, architecture),
            architecture_source_ref=oversized_coupling.architecture_ref,
            coupling_plan=oversized_coupling,
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
    assert not {item.coordinate for item in batches} & set(release_assurance.dependency_coordinates)


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


def test_tool_semantics_policy_has_one_base_correction_progress_bonus_and_infra_retry() -> None:
    definition = tool_semantics_batch_definition(
        job_id="job:hotel",
        group_id="coupling:booking",
        batch_id="batch:1",
        dependency_coordinates=(_coordinate("architecture"),),
        agent_wall_seconds=300,
        agent_token_limit=65_536,
    )

    assert definition.coordinate.artifact_slot == "tool_semantics_batch"
    assert definition.proposal_policy.budget.agent_turns == 1
    assert definition.proposal_policy.budget.llm_tokens == 32_768
    assert definition.proposal_policy.budget.monetary_cost == 0
    assert definition.repair_policy.maximum_local_corrections == 1
    assert definition.repair_policy.strict_progress_bonus_corrections == 1
    assert definition.repair_policy.maximum_infrastructure_retries == 1
    assert definition.repair_policy.maximum_automatic_backjump == 0


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

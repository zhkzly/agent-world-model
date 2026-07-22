from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import JsonValue, ValidationError
from v3_fixture import portable_counter_contracts

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    Claim,
    CoverageDimension,
    CoverageMap,
    DifficultyDimension,
    EnvironmentRequest,
    EvidenceGraph,
    FidelityStatement,
    ReleaseProfile,
    RuleValueRef,
    StateSchema,
    ToolContract,
    ToolError,
    WorldSpec,
)
from agent_world.control.validation import (
    StructuredValidationError,
    pydantic_validation_diagnostic,
)
from agent_world.designer.expansion_service import ExpansionDesigner
from agent_world.designer.models import (
    ActorAuthoritySourceDraft,
    AssumptionResolutionDraft,
    CompactFieldSemanticDraft,
    CurriculumPlanDraft,
    CurriculumTaskPlan,
    EnvironmentDesignDraft,
    EnvironmentSemanticSourceDraft,
    EvidenceAssumptionClosureDraft,
    ExpansionSemanticDeltaDraft,
    InitialStateRulesDraft,
    SchemaArrayNodeDraft,
    SchemaIntegerNodeDraft,
    SchemaNullNodeDraft,
    SchemaObjectNodeDraft,
    SchemaPropertyDraft,
    SchemaStringNodeDraft,
    SchemaUnionNodeDraft,
    StateEntityInventoryDraft,
    StateEntityPlan,
    StateEntitySchemaDraft,
    StateEntitySchemaIRDraft,
    StateEntitySourceDraft,
    StateFieldSourceDraft,
    TaskDistributionDeltaClaimDraft,
    TaskRequirementDraft,
    TaskScopeDeltaClaimDraft,
    ToolAccessObservationDraft,
    ToolBehaviorDraft,
    ToolConditionsDraft,
    ToolErrorsDraft,
    ToolInterfaceSourceDraft,
    ToolReliabilityDraft,
    ToolSchemaDraft,
    ToolSchemaIRDraft,
    ToolSemanticsDraft,
    ToolStateTransitionDraft,
    ToolSurfaceDraft,
    ToolSurfacePlan,
    ToolSurfaceSchemasDraft,
    ToolSurfaceSourceDraft,
    WorldArchitectureSourceDraft,
    WorldBoundaryDraft,
    WorldBoundarySourceDraft,
    WorldClosureDraft,
    WorldClosureReferenceTerm,
    WorldModelDraft,
    WorldSemanticSourceIRDraft,
    WorldSkeletonDraft,
    WorldStateDraft,
    WorldStateShapeDraft,
    WorldToolInventoryDraft,
    WorldToolPlanInventoryDraft,
    WorldToolSourceInventoryDraft,
)
from agent_world.designer.service import (
    DIRECT_DESIGN_BASE_TURNS,
    DIRECT_DESIGN_MAX_TURNS,
    MAX_STATE_ENTITIES,
    MAX_WORLD_CLOSURE_CONTEXT_BYTES,
    MAX_WORLD_TOOL_SURFACES,
    DesignBundle,
    EnvironmentDesigner,
)
from agent_world.designer.validation import StructuredSemanticError


def _inputs(tmp_path: Path):  # type: ignore[no-untyped-def]
    world = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design.world_spec
    tool = world.tools[0]
    prefix = f"rule:{tool.surface.tool_id}:"
    semantics = tool.semantics.model_copy(
        update={
            "preconditions": tuple(
                rule.model_copy(update={"rule_id": f"{prefix}precondition:{index}"})
                for index, rule in enumerate(tool.semantics.preconditions)
            ),
            "transition": tuple(
                rule.model_copy(update={"rule_id": f"{prefix}transition:{index}"})
                for index, rule in enumerate(tool.semantics.transition)
            ),
            "postconditions": tuple(
                rule.model_copy(update={"rule_id": f"{prefix}postcondition:{index}"})
                for index, rule in enumerate(tool.semantics.postconditions)
            ),
            "errors": tuple(
                ToolError(
                    **error.model_dump(mode="python", exclude={"when"}),
                    when=error.when.model_copy(update={"rule_id": f"{prefix}error:{index}"}),
                )
                for index, error in enumerate(tool.semantics.errors)
            ),
        }
    )
    skeleton = WorldSkeletonDraft(
        boundary=world.boundary,
        state=world.state,
        tool_surfaces=(
            ToolSurfaceDraft(
                surface=tool.surface,
                evidence_claim_ids=("claim:counter",),
            ),
        ),
        task_dimensions=world.task_dimensions,
        fidelity=world.fidelity,
    )
    graph = EvidenceGraph(
        graph_id="evidence:counter",
        revision=1,
        claims=(
            Claim(
                claim_id="claim:counter",
                kind="product_decision",
                statement="The local environment uses deterministic counter semantics.",
                confidence=1,
                status="supported",
                risk="low",
            ),
        ),
    )
    tool_draft = ToolSemanticsDraft(
        tool_id=tool.surface.tool_id,
        semantics=semantics,
    )
    invariant = world.invariants[0].model_copy(update={"rule_id": "rule:world:counter-nonnegative"})
    return world, skeleton, graph, tool_draft, WorldClosureDraft(invariants=(invariant,))


def test_tool_access_observation_reports_all_missing_fields_by_actor(
    tmp_path: Path,
) -> None:
    world, skeleton, _, tool_draft, _ = _inputs(tmp_path)
    access = ToolAccessObservationDraft(
        tool_id=tool_draft.tool_id,
        permission=tool_draft.semantics.permission,
        observation=tool_draft.semantics.observation,
    )
    actors = {item.actor for item in skeleton.boundary.actors_and_authority}
    empty_projection = access.observation.model_copy(
        update={
            "visible_fields_by_actor": {actor: () for actor in actors},
            "redacted_fields_by_actor": {actor: () for actor in actors},
        }
    )

    with pytest.raises(StructuredSemanticError) as raised:
        EnvironmentDesigner._validate_tool_access_observation_draft(
            access.model_copy(update={"observation": empty_projection}),
            expected_tool_id=tool_draft.tool_id,
            skeleton=skeleton,
        )

    properties = cast(
        dict[str, JsonValue],
        skeleton.tool_surfaces[0].surface.observation_schema["properties"],
    )
    assert properties
    missing_locations = {
        issue.location for issue in raised.value.issues if issue.code == "observation_field_missing"
    }
    assert missing_locations == {("observation", "classification", actor) for actor in actors}


def test_public_tool_may_allow_every_frozen_actor_without_invented_condition(
    tmp_path: Path,
) -> None:
    world, skeleton, _, tool_draft, _ = _inputs(tmp_path)
    actors = tuple(item.actor for item in skeleton.boundary.actors_and_authority)
    permission = tool_draft.semantics.permission.model_copy(
        update={
            "allowed_actors": actors,
            "required_scopes_by_actor": {actor: () for actor in actors},
            "condition": None,
        }
    )
    access = ToolAccessObservationDraft(
        tool_id=tool_draft.tool_id,
        permission=permission,
        observation=tool_draft.semantics.observation,
    )

    EnvironmentDesigner._validate_tool_access_observation_draft(
        access,
        expected_tool_id=tool_draft.tool_id,
        skeleton=skeleton,
    )
    public_tool = world.tools[0].model_copy(
        update={"semantics": tool_draft.semantics.model_copy(update={"permission": permission})}
    )
    WorldSpec.model_validate(
        world.model_copy(update={"tools": (public_tool,)}).model_dump(mode="python")
    )


def test_tool_access_observation_routes_permission_rule_id_collision(
    tmp_path: Path,
) -> None:
    _, skeleton, _, tool_draft, _ = _inputs(tmp_path)
    semantics = tool_draft.semantics
    behavior = ToolBehaviorDraft(
        tool_id=tool_draft.tool_id,
        preconditions=semantics.preconditions,
        transition=semantics.transition,
        postconditions=semantics.postconditions,
        errors=semantics.errors,
    )
    colliding_condition = semantics.preconditions[0].model_copy(update={"family": "permission"})
    access = ToolAccessObservationDraft(
        tool_id=tool_draft.tool_id,
        permission=semantics.permission.model_copy(update={"condition": colliding_condition}),
        observation=semantics.observation,
    )

    with pytest.raises(StructuredSemanticError) as raised:
        EnvironmentDesigner._validate_tool_access_observation_draft(
            access,
            expected_tool_id=tool_draft.tool_id,
            skeleton=skeleton,
            behavior=behavior,
        )

    assert [issue.code for issue in raised.value.issues] == ["access_rule_identity_collision"]
    assert raised.value.issues[0].location == (
        "permission",
        "condition",
        "rule_id",
    )


def test_tool_access_observation_does_not_echo_unknown_rejected_field(
    tmp_path: Path,
) -> None:
    _, skeleton, _, tool_draft, _ = _inputs(tmp_path)
    access = ToolAccessObservationDraft(
        tool_id=tool_draft.tool_id,
        permission=tool_draft.semantics.permission,
        observation=tool_draft.semantics.observation,
    )
    actor = next(iter(access.observation.visible_fields_by_actor))
    rejected_field = "rejected-secret-field"
    visible = dict(access.observation.visible_fields_by_actor)
    visible[actor] = (*visible[actor], rejected_field)
    invalid_projection = access.observation.model_copy(update={"visible_fields_by_actor": visible})

    with pytest.raises(StructuredSemanticError) as raised:
        EnvironmentDesigner._validate_tool_access_observation_draft(
            access.model_copy(update={"observation": invalid_projection}),
            expected_tool_id=tool_draft.tool_id,
            skeleton=skeleton,
        )

    assert any(issue.code == "observation_field_unknown" for issue in raised.value.issues)
    assert rejected_field not in str(raised.value)


def test_world_model_is_framework_composed_from_bounded_real_semantic_nodes(
    tmp_path: Path,
) -> None:
    world, skeleton, graph, tool_draft, closure = _inputs(tmp_path)

    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )
    entity_plan = StateEntityPlan(
        entity="counter",
        purpose="Own the deterministic counter state.",
        root_field="counter",
        storage="singleton",
        system_of_record="counter-runtime",
        boundary_resource_ids=("counter",),
        primary_key_fields=("value",),
        evidence_claim_ids=("claim:counter",),
    )
    state_inventory = StateEntityInventoryDraft(entities=(entity_plan,))
    EnvironmentDesigner._validate_state_entity_inventory_draft(
        state_inventory,
        boundary=boundary,
        evidence_graph=graph,
    )
    entity_schema_draft = StateEntitySchemaDraft(
        entity="counter",
        json_schema=skeleton.state.entities[0].json_schema,
    )
    EnvironmentDesigner._validate_state_entity_schema_draft(
        entity_schema_draft,
        plan=entity_plan,
    )
    entity_schema = EnvironmentDesigner._compose_state_entity_schema(
        entity_plan,
        entity_schema_draft,
    )
    composed_shape = EnvironmentDesigner._compose_world_state_shape(
        state_inventory,
        (entity_schema,),
    )
    EnvironmentDesigner._validate_world_state_shape_draft(
        composed_shape,
        boundary=boundary,
        evidence_graph=graph,
    )
    assert composed_shape.root_state_schema["properties"] == {
        "counter": {"$ref": "#/$defs/counter"}
    }
    assert composed_shape.root_state_schema["$defs"] == {
        "counter": skeleton.state.entities[0].json_schema
    }
    state_shape = WorldStateShapeDraft(
        entities=skeleton.state.entities,
        root_state_schema=skeleton.state.root_state_schema,
    )
    initial_rules = InitialStateRulesDraft(
        initial_state_constraints=skeleton.state.initial_state_constraints,
    )
    EnvironmentDesigner._validate_world_state_shape_draft(
        state_shape,
        boundary=boundary,
        evidence_graph=graph,
    )
    EnvironmentDesigner._validate_initial_state_rules_draft(
        initial_rules,
        state_shape=state_shape,
        evidence_graph=graph,
    )
    state = EnvironmentDesigner._compose_world_state(state_shape, initial_rules)
    assert state == WorldStateDraft(state=skeleton.state)
    inventory = WorldToolInventoryDraft(tool_surfaces=skeleton.tool_surfaces)
    surface = skeleton.tool_surfaces[0].surface
    tool_plan = ToolSurfacePlan(
        tool_id=surface.tool_id,
        namespace=surface.namespace,
        name=surface.name,
        description=surface.description,
        transport=surface.transport,
        reads_state_entities=("counter",),
        evidence_claim_ids=("claim:counter",),
    )
    tool_plan_inventory = WorldToolPlanInventoryDraft(tools=(tool_plan,))
    EnvironmentDesigner._validate_world_tool_plan_inventory_draft(
        tool_plan_inventory,
        boundary=boundary,
        evidence_graph=graph,
    )
    surface_schemas = ToolSurfaceSchemasDraft(
        tool_id=surface.tool_id,
        input_schema=surface.input_schema,
        output_schema=surface.output_schema,
        observation_schema=surface.observation_schema,
    )
    EnvironmentDesigner._validate_tool_surface_schemas_draft(
        surface_schemas,
        plan=tool_plan,
    )
    assert (
        EnvironmentDesigner._compose_tool_surface(tool_plan, surface_schemas)
        == (skeleton.tool_surfaces[0])
    )
    EnvironmentDesigner._validate_world_boundary_draft(boundary, evidence_graph=graph)
    EnvironmentDesigner._validate_world_state_draft(
        state,
        boundary=boundary,
        evidence_graph=graph,
    )
    EnvironmentDesigner._validate_world_tool_inventory_draft(
        inventory,
        boundary=boundary,
        evidence_graph=graph,
    )
    composed_skeleton = EnvironmentDesigner._compose_world_skeleton(
        boundary,
        state,
        inventory,
    )
    assert composed_skeleton == skeleton
    EnvironmentDesigner._validate_world_skeleton(composed_skeleton, evidence_graph=graph)
    conditions = ToolConditionsDraft(
        tool_id=tool_draft.tool_id,
        preconditions=tool_draft.semantics.preconditions,
        postconditions=tool_draft.semantics.postconditions,
    )
    state_transition = ToolStateTransitionDraft(
        tool_id=tool_draft.tool_id,
        transition=tool_draft.semantics.transition,
    )
    errors = ToolErrorsDraft(
        tool_id=tool_draft.tool_id,
        errors=tool_draft.semantics.errors,
    )
    EnvironmentDesigner._validate_tool_conditions_draft(
        conditions,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        evidence_graph=graph,
    )
    EnvironmentDesigner._validate_tool_state_transition_draft(
        state_transition,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        evidence_graph=graph,
    )
    EnvironmentDesigner._validate_tool_errors_draft(
        errors,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        evidence_graph=graph,
    )
    behavior = EnvironmentDesigner._compose_tool_behavior(
        conditions,
        state_transition,
        errors,
    )
    access = ToolAccessObservationDraft(
        tool_id=tool_draft.tool_id,
        permission=tool_draft.semantics.permission,
        observation=tool_draft.semantics.observation,
    )
    reliability = ToolReliabilityDraft(
        tool_id=tool_draft.tool_id,
        idempotency=tool_draft.semantics.idempotency,
        retry=tool_draft.semantics.retry,
        timeout=tool_draft.semantics.timeout,
        transaction=tool_draft.semantics.transaction,
        rollback=tool_draft.semantics.rollback,
        concurrency=tool_draft.semantics.concurrency,
    )
    EnvironmentDesigner._validate_tool_behavior_draft(
        behavior,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        evidence_graph=graph,
    )
    EnvironmentDesigner._validate_tool_access_observation_draft(
        access,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        behavior=behavior,
    )
    EnvironmentDesigner._validate_tool_reliability_draft(
        reliability,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        behavior=behavior,
    )
    assert (
        EnvironmentDesigner._compose_tool_semantics(
            behavior,
            access,
            reliability,
        )
        == tool_draft.semantics
    )
    EnvironmentDesigner._validate_tool_semantics_draft(
        tool_draft,
        expected_tool_id="counter.increment",
        skeleton=skeleton,
        evidence_graph=graph,
    )
    tool = ToolContract(
        surface=skeleton.tool_surfaces[0].surface,
        semantics=tool_draft.semantics,
        evidence_claim_ids=skeleton.tool_surfaces[0].evidence_claim_ids,
    )
    assembled = EnvironmentDesigner._compose_world_model(skeleton, (tool,), closure)
    EnvironmentDesigner._validate_world_model_draft(
        assembled,
        evidence_graph=graph,
        evidence_graph_ref=world.evidence_graph_ref,
    )

    assert assembled.tools == (tool,)
    assert assembled.invariants == closure.invariants
    assert MAX_WORLD_TOOL_SURFACES == 8
    assert MAX_STATE_ENTITIES == 12
    # Cardinality changes payload size, never the number of semantic transactions.
    # Eight turns reserve two research calls, architecture, up to two tool
    # batches, task/curriculum, and at most two local corrections.
    assert DIRECT_DESIGN_BASE_TURNS == 8
    assert DIRECT_DESIGN_MAX_TURNS == 10


def test_compact_architecture_compiles_full_typed_skeleton_with_framework_tool_id(
    tmp_path: Path,
) -> None:
    _world, existing, graph, _tool_draft, _closure = _inputs(tmp_path)
    surface = existing.tool_surfaces[0]
    source = WorldArchitectureSourceDraft(
        boundary=WorldBoundarySourceDraft(
            primary_domain=existing.boundary.primary_domain,
            actors_and_authority=tuple(
                ActorAuthoritySourceDraft(
                    actor=actor.actor,
                    authorities=actor.authorities,
                )
                for actor in existing.boundary.actors_and_authority
            ),
            systems_of_record=existing.boundary.systems_of_record,
            transition_authorities=existing.boundary.transition_authorities,
            tool_namespaces=existing.boundary.tool_namespaces,
            core_invariants=existing.boundary.core_invariants,
            task_dimensions=existing.task_dimensions,
            fidelity=existing.fidelity,
        ),
        state_entities=(
            StateEntitySourceDraft(
                entity="counter",
                purpose="Own deterministic counter state.",
                root_field="counter",
                storage="singleton",
                system_of_record=existing.boundary.systems_of_record[0],
                owned_resource_ids=("counter",),
                visible_to_actor_ids=tuple(
                    actor.actor
                    for actor in existing.boundary.actors_and_authority
                    if "counter" in actor.visibility
                ),
                fields=(
                    StateFieldSourceDraft(
                        name="value",
                        value_type="integer",
                        description="Current counter value.",
                        minimum=0,
                        role="primary_key",
                    ),
                ),
                evidence_claim_ids=("claim:counter",),
            ),
        ),
        tool_inventory=WorldToolSourceInventoryDraft(
            tools=(
                ToolSurfaceSourceDraft(
                    namespace=surface.surface.namespace,
                    name=surface.surface.name,
                    description=surface.surface.description,
                    transport=surface.surface.transport,
                    writes_state_entities=("counter",),
                    evidence_claim_ids=surface.evidence_claim_ids,
                    interface=ToolInterfaceSourceDraft(
                        input_fields=(
                            CompactFieldSemanticDraft(
                                name="amount",
                                value_type="integer",
                                description="Increment amount.",
                                minimum=0,
                            ),
                        ),
                        output_fields=(
                            CompactFieldSemanticDraft(
                                name="value",
                                value_type="integer",
                                description="Updated counter value.",
                            ),
                        ),
                        observation_fields=(
                            CompactFieldSemanticDraft(
                                name="value",
                                value_type="integer",
                                description="Visible counter value.",
                            ),
                        ),
                    ),
                ),
            )
        ),
    )

    compiled = EnvironmentDesigner.__new__(EnvironmentDesigner)._compile_architecture_skeleton(
        source,
        evidence_graph=graph,
    )

    assert compiled.tool_surfaces[0].surface.tool_id == surface.surface.tool_id
    assert compiled.state.root_state_schema["additionalProperties"] is False


def test_state_entity_inventory_reports_independent_semantic_errors_together(
    tmp_path: Path,
) -> None:
    _world, skeleton, graph, _tool_draft, _closure = _inputs(tmp_path)
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )
    invalid = StateEntityInventoryDraft(
        entities=(
            StateEntityPlan(
                entity="counter",
                purpose="Own the counter.",
                root_field="counter",
                storage="singleton",
                system_of_record="undeclared-runtime",
                boundary_resource_ids=("counter",),
                primary_key_fields=("value",),
                mutable_fields=(),
                lifecycle_field="status",
                lifecycle_states=("active",),
                evidence_claim_ids=("claim:counter",),
            ),
            StateEntityPlan(
                entity="counter_view",
                purpose="Expose a derived view.",
                root_field="counter_view",
                storage="singleton",
                system_of_record=skeleton.boundary.systems_of_record[0],
                boundary_resource_ids=("counter",),
                primary_key_fields=("view_id",),
                evidence_claim_ids=("claim:counter",),
            ),
        )
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_state_entity_inventory_draft(
            invalid,
            boundary=boundary,
            evidence_graph=graph,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.owner_component == "design"
    assert diagnostic.validation_phase == "state_inventory_semantics"
    assert diagnostic.issue_codes == (
        "state_inventory_system_unknown@entities.0.system_of_record",
        "state_inventory_resource_ownership@entities.1.boundary_resource_ids.0",
        "state_inventory_lifecycle_mutability@entities.0.lifecycle_field",
    )
    assert "undeclared-runtime" not in diagnostic.feedback
    assert "lifecycle_field must exactly name one mutable_fields entry" in diagnostic.feedback


def test_world_boundary_rejects_an_impossible_state_visibility_cardinality(
    tmp_path: Path,
) -> None:
    _world, skeleton, graph, _tool_draft, _closure = _inputs(tmp_path)
    actor = skeleton.boundary.actors_and_authority[0].model_copy(
        update={"visibility": tuple(f"visible_{index}" for index in range(13))}
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary.model_copy(update={"actors_and_authority": (actor,)}),
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )

    with pytest.raises(ValueError, match="reset visibility exceeds") as captured:
        EnvironmentDesigner._validate_world_boundary_draft(
            boundary,
            evidence_graph=graph,
        )

    assert EnvironmentDesigner._validation_issue_codes(captured.value) == (
        "boundary_visibility_capacity@boundary.actors_and_authority",
    )


def test_world_boundary_rejects_duplicate_actor_visibility_before_inventory(
    tmp_path: Path,
) -> None:
    _world, skeleton, graph, _tool_draft, _closure = _inputs(tmp_path)
    original = skeleton.boundary.actors_and_authority[0]
    actor = original.model_copy(
        update={"visibility": (*original.visibility, original.visibility[0])}
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary.model_copy(update={"actors_and_authority": (actor,)}),
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )

    with pytest.raises(ValueError, match="visibility fields must be unique"):
        EnvironmentDesigner._validate_world_boundary_draft(
            boundary,
            evidence_graph=graph,
        )


def test_world_boundary_fidelity_feedback_is_field_addressable(tmp_path: Path) -> None:
    _world, skeleton, graph, _tool_draft, _closure = _inputs(tmp_path)
    faithful = skeleton.fidelity[0].model_copy(
        update={
            "level": "faithful",
            "known_divergence": "This must be removed for a faithful statement.",
        }
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=(faithful,),
    )

    with pytest.raises(ValueError) as captured:
        EnvironmentDesigner._validate_world_boundary_draft(
            boundary,
            evidence_graph=graph,
        )

    assert EnvironmentDesigner._validation_issue_codes(captured.value) == (
        f"faithful_fidelity_divergence_forbidden@fidelity.{faithful.statement_id}.known_divergence",
    )
    feedback = EnvironmentDesigner._structured_repair_feedback(captured.value)
    assert "known_divergence to be null" in feedback


def test_task_dimensions_are_identifiers_at_the_authoring_boundary(tmp_path: Path) -> None:
    _, skeleton, _, _, _ = _inputs(tmp_path)

    with pytest.raises(ValidationError, match="task_dimensions"):
        WorldBoundaryDraft(
            boundary=skeleton.boundary,
            task_dimensions=("human readable label",),
            fidelity=skeleton.fidelity,
        )


def test_world_composition_accepts_an_explicit_dimension_rework(tmp_path: Path) -> None:
    _, skeleton, graph, tool_draft, closure = _inputs(tmp_path)
    legacy_skeleton = skeleton.model_copy(update={"task_dimensions": ("human readable label",)})
    tool = ToolContract(
        surface=legacy_skeleton.tool_surfaces[0].surface,
        semantics=tool_draft.semantics,
        evidence_claim_ids=legacy_skeleton.tool_surfaces[0].evidence_claim_ids,
    )

    EnvironmentDesigner._validate_world_skeleton(
        legacy_skeleton,
        evidence_graph=graph,
        allow_task_dimension_rework=True,
    )
    with pytest.raises(ValidationError, match="task_dimensions"):
        EnvironmentDesigner._compose_world_model(legacy_skeleton, (tool,), closure)

    model = EnvironmentDesigner._compose_world_model(
        legacy_skeleton,
        (tool,),
        closure,
        task_dimensions=("human-readable-label",),
    )

    assert model.task_dimensions == ("human-readable-label",)


def test_world_closure_context_excludes_unrelated_operational_payload(
    tmp_path: Path,
) -> None:
    _, skeleton, graph, tool_draft, _ = _inputs(tmp_path)
    tool = ToolContract(
        surface=skeleton.tool_surfaces[0].surface,
        semantics=tool_draft.semantics,
        evidence_claim_ids=skeleton.tool_surfaces[0].evidence_claim_ids,
    )

    context = EnvironmentDesigner._world_closure_context(
        skeleton=skeleton,
        tools=(tool,),
        task_dimensions=skeleton.task_dimensions,
        evidence_graph=graph,
    )
    encoded = context.model_dump_json()

    projected = context.tool_paths[0].transition[0]
    assert projected.rule_id == tool.semantics.transition[0].rule_id
    assert projected.description == tool.semantics.transition[0].description
    catalog = {item.constraint_id: item for item in context.constraints}
    assert set(projected.constraint_ids) <= set(catalog)
    projected_clause = catalog[projected.constraint_ids[0]]
    original_clause = tool.semantics.transition[0].clauses[0]
    assert projected_clause.operator == original_clause.operator
    assert isinstance(projected_clause.left, WorldClosureReferenceTerm)
    assert isinstance(original_clause.left, RuleValueRef)
    assert projected_clause.left.pointer == original_clause.left.pointer
    assert "visible_fields_by_actor" not in encoded
    assert "idempotency" not in encoded
    assert "observation_schema" not in encoded
    assert "clause_id" not in encoded
    assert "schema_version" not in encoded.split('"evidence_claims"', 1)[0]
    assert len(encoded.encode("utf-8")) < MAX_WORLD_CLOSURE_CONTEXT_BYTES


def test_world_closure_context_deduplicates_identical_executable_clauses(
    tmp_path: Path,
) -> None:
    _, skeleton, graph, tool_draft, _ = _inputs(tmp_path)
    original = tool_draft.semantics.transition[0]
    duplicate = original.model_copy(
        update={
            "rule_id": "rule:counter.increment:transition:duplicate",
            "description": "The same executable relation under another validated path.",
        }
    )
    semantics = tool_draft.semantics.model_copy(
        update={"transition": (*tool_draft.semantics.transition, duplicate)}
    )
    tool = ToolContract(
        surface=skeleton.tool_surfaces[0].surface,
        semantics=semantics,
        evidence_claim_ids=skeleton.tool_surfaces[0].evidence_claim_ids,
    )

    context = EnvironmentDesigner._world_closure_context(
        skeleton=skeleton,
        tools=(tool,),
        task_dimensions=skeleton.task_dimensions,
        evidence_graph=graph,
    )

    first, second = context.tool_paths[0].transition
    assert first.constraint_ids == second.constraint_ids
    all_clauses = (
        *semantics.preconditions,
        *semantics.transition,
        *semantics.postconditions,
        *(error.when for error in semantics.errors),
    )
    assert len(context.constraints) < sum(len(rule.clauses) for rule in all_clauses)


def test_training_contract_context_preserves_task_semantics_without_runtime_payload(
    tmp_path: Path,
) -> None:
    _, skeleton, graph, tool_draft, closure = _inputs(tmp_path)
    tool = ToolContract(
        surface=skeleton.tool_surfaces[0].surface,
        semantics=tool_draft.semantics,
        evidence_claim_ids=skeleton.tool_surfaces[0].evidence_claim_ids,
    )
    world = EnvironmentDesigner._compose_world_model(skeleton, (tool,), closure)

    context = EnvironmentDesigner._training_contract_context(
        world=world,
        evidence_graph=graph,
    )
    encoded = context.model_dump_json()

    assert context.root_state_schema == world.state.root_state_schema
    assert context.tools[0].input_schema == tool.surface.input_schema
    assert context.tools[0].allowed_actor_ids == tool.semantics.permission.allowed_actors
    assert {item.rule_id for item in context.tools[0].rules} == {
        rule.rule_id
        for rule in (
            *tool.semantics.preconditions,
            *tool.semantics.transition,
            *tool.semantics.postconditions,
            *(error.when for error in tool.semantics.errors),
        )
    }
    assert "output_schema" not in encoded
    assert "observation_schema" not in encoded
    assert "idempotency" not in encoded
    assert "rollback" not in encoded
    assert len(encoded) < len(world.model_dump_json())


def test_training_contract_reward_and_verification_are_framework_compiled(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    design = portable_counter_contracts(store).design
    world = WorldModelDraft(
        boundary=design.world_spec.boundary,
        state=design.world_spec.state,
        tools=design.world_spec.tools,
        invariants=design.world_spec.invariants,
        task_dimensions=design.world_spec.task_dimensions,
        fidelity=design.world_spec.fidelity,
    )
    task = design.curriculum.task_types[0]
    plan = CurriculumPlanDraft(
        coverage_dimensions=(
            CoverageDimension(
                dimension="target",
                world_modelled="complete",
            ),
        ),
        task_plans=(
            CurriculumTaskPlan(
                task_type=task.task_type,
                objective=task.objective,
                allowed_actor_ids=task.allowed_actor_ids,
                required_tool_ids=task.required_tool_ids,
                difficulty_dimensions=task.difficulty_dimensions,
                minimum_tool_calls=task.minimum_tool_calls,
            ),
        ),
        difficulty_dimensions=design.curriculum.difficulty_dimensions,
        generation_seed_space=design.curriculum.generation_seed_space,
        minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
        minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        sampling_constraints=design.curriculum.sampling_constraints,
        unresolved_questions=("How should optional curriculum sampling be weighted?",),
    )
    draft = TaskRequirementDraft(
        task_type=task.task_type,
        objective=task.objective,
        allowed_actor_ids=task.allowed_actor_ids,
        required_tool_ids=task.required_tool_ids,
        initial_state_constraints=task.initial_state_constraints,
        success_conditions=task.success_conditions,
        failure_conditions=task.failure_conditions,
        terminal_conditions=task.terminal_conditions,
        difficulty_dimensions=task.difficulty_dimensions,
        minimum_tool_calls=task.minimum_tool_calls,
    )
    compiled_task = EnvironmentDesigner._compile_task_requirement_shard(
        draft,
        target=plan.task_plans[0],
        world=world,
    )
    authored = EnvironmentDesigner._compose_curriculum_contract(
        plan,
        (compiled_task,),
    )
    assert authored.unresolved_questions == ()

    compiled = EnvironmentDesigner._compile_training_contract(world, authored)

    success_ids = tuple(
        rule.rule_id for task in design.curriculum.task_types for rule in task.success_conditions
    )
    failure_ids = tuple(
        rule.rule_id for task in design.curriculum.task_types for rule in task.failure_conditions
    )
    terminal_ids = tuple(
        rule.rule_id for task in design.curriculum.task_types for rule in task.terminal_conditions
    )
    assert compiled.reward.success_rule_ids == success_ids
    assert compiled.reward.failure_rule_ids == failure_ids
    assert compiled.reward.terminal_rule_ids == terminal_ids
    assert compiled.reward.success_reward == 1.0
    assert compiled.reward.failure_reward == -1.0
    assert compiled.reward.outcome_precedence == "failure_over_success"
    assert set(compiled.verification.required_rule_ids) == set(
        design.verification.required_rule_ids
    )
    assert set(compiled.verification.required_property_families) == set(
        design.verification.required_property_families
    )
    assert compiled_task.initial_config_schema["type"] == "object"
    assert "$defs" not in compiled_task.initial_config_schema
    assert compiled_task.public_goal_schema == compiled_task.evaluator_goal_schema
    assert {item.evaluator_pointer for item in compiled_task.evaluator_goal_bindings}


def test_curriculum_plan_reports_exact_unknown_world_rule_reference(tmp_path: Path) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design
    world = WorldModelDraft(
        boundary=design.world_spec.boundary,
        state=design.world_spec.state,
        tools=design.world_spec.tools,
        invariants=design.world_spec.invariants,
        task_dimensions=design.world_spec.task_dimensions,
        fidelity=design.world_spec.fidelity,
    )
    task = design.curriculum.task_types[0]
    dimension = design.curriculum.difficulty_dimensions[0].model_copy(
        update={"dimension": world.task_dimensions[0]}
    )
    plan = CurriculumPlanDraft(
        coverage_dimensions=(
            CoverageDimension(
                dimension="target",
                world_modelled="complete",
                rule_ids=("rule:missing",),
            ),
        ),
        task_plans=(
            CurriculumTaskPlan(
                task_type=task.task_type,
                objective=task.objective,
                allowed_actor_ids=task.allowed_actor_ids,
                required_tool_ids=task.required_tool_ids,
                difficulty_dimensions=(dimension.dimension,),
                minimum_tool_calls=task.minimum_tool_calls,
            ),
        ),
        difficulty_dimensions=(dimension,),
        generation_seed_space=design.curriculum.generation_seed_space,
        minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
        minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_curriculum_plan(  # noqa: SLF001
            plan,
            world=world,
            evidence_graph=EvidenceGraph(graph_id="evidence:empty", revision=1),
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "curriculum_plan_semantics"
    assert diagnostic.issue_codes == (
        "curriculum_coverage_rule_unknown@coverage_dimensions.0.rule_ids.0",
    )


def test_entity_schema_rejects_refs_and_lifecycle_drift() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="Own reservation lifecycle.",
        root_field="reservations",
        storage="collection",
        system_of_record="booking-system",
        boundary_resource_ids=("reservation",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("status",),
        lifecycle_field="status",
        lifecycle_states=("pending", "confirmed"),
        evidence_claim_ids=("claim:reservation",),
    )
    with pytest.raises(ValueError, match=r"without \$ref/\$defs"):
        EnvironmentDesigner._validate_state_entity_schema_draft(
            StateEntitySchemaDraft(
                entity="reservation",
                json_schema={
                    "type": "object",
                    "properties": {
                        "reservation_id": {"type": "string"},
                        "status": {"$ref": "#/$defs/status"},
                    },
                    "required": ["reservation_id", "status"],
                    "additionalProperties": False,
                    "$defs": {"status": {"type": "string"}},
                },
            ),
            plan=plan,
        )

    with pytest.raises(ValueError, match="lifecycle field enum must match"):
        EnvironmentDesigner._validate_state_entity_schema_draft(
            StateEntitySchemaDraft(
                entity="reservation",
                json_schema={
                    "type": "object",
                    "properties": {
                        "reservation_id": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending"]},
                    },
                    "required": ["reservation_id", "status"],
                    "additionalProperties": False,
                },
            ),
            plan=plan,
        )


def test_state_entity_schema_ir_compiles_closed_planned_fields_and_lifecycle() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="Own reservation lifecycle.",
        root_field="reservations",
        storage="collection",
        system_of_record="booking-system",
        boundary_resource_ids=("reservation",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("status",),
        lifecycle_field="status",
        lifecycle_states=("pending", "confirmed"),
        evidence_claim_ids=("claim:reservation",),
    )
    draft = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id",
                        node_id="reservation_id",
                        required=True,
                    ),
                    SchemaPropertyDraft(name="status", node_id="status", required=True),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaStringNodeDraft(
                node_id="status",
                kind="string",
                enum_values=plan.lifecycle_states,
            ),
        ),
    )

    EnvironmentDesigner._validate_state_entity_schema_ir_draft(draft, plan=plan)
    compiled = EnvironmentDesigner._compile_state_entity_schema_ir(draft)

    assert compiled.json_schema == {
        "type": "object",
        "properties": {
            "reservation_id": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "confirmed"]},
        },
        "additionalProperties": False,
        "required": ["reservation_id", "status"],
    }


def test_state_entity_schema_ir_rejects_unplanned_root_fields() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="Own reservation lifecycle.",
        root_field="reservations",
        storage="collection",
        system_of_record="booking-system",
        boundary_resource_ids=("reservation",),
        primary_key_fields=("reservation_id",),
        evidence_claim_ids=("claim:reservation",),
    )
    draft = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id",
                        node_id="reservation_id",
                        required=True,
                    ),
                    SchemaPropertyDraft(name="secret", node_id="secret", required=False),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaStringNodeDraft(node_id="secret", kind="string"),
        ),
    )

    with pytest.raises(ValueError, match="root fields must match its frozen plan"):
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(draft, plan=plan)


def test_state_entity_schema_ir_accepts_only_scalar_nullable_union() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="Own reservation data.",
        root_field="reservations",
        storage="collection",
        system_of_record="booking-system",
        boundary_resource_ids=("reservation",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("note",),
        evidence_claim_ids=("claim:reservation",),
    )
    draft = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id",
                        node_id="reservation_id",
                        required=True,
                    ),
                    SchemaPropertyDraft(name="note", node_id="note_or_null", required=True),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaUnionNodeDraft(
                node_id="note_or_null",
                kind="union",
                variant_node_ids=("note", "null"),
            ),
            SchemaStringNodeDraft(node_id="note", kind="string", min_length=1),
            SchemaNullNodeDraft(node_id="null", kind="null"),
        ),
    )

    EnvironmentDesigner._validate_state_entity_schema_ir_draft(draft, plan=plan)


def test_state_entity_schema_ir_rejects_structural_nullable_union_before_fanout() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="Own reservation data.",
        root_field="reservations",
        storage="collection",
        system_of_record="booking-system",
        boundary_resource_ids=("reservation",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("details",),
        evidence_claim_ids=("claim:reservation",),
    )
    draft = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id",
                        node_id="reservation_id",
                        required=True,
                    ),
                    SchemaPropertyDraft(
                        name="details",
                        node_id="details_or_null",
                        required=True,
                    ),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaUnionNodeDraft(
                node_id="details_or_null",
                kind="union",
                variant_node_ids=("details", "null"),
            ),
            SchemaObjectNodeDraft(
                node_id="details",
                kind="object",
                properties=(SchemaPropertyDraft(name="note", node_id="note", required=True),),
            ),
            SchemaStringNodeDraft(node_id="note", kind="string"),
            SchemaNullNodeDraft(node_id="null", kind="null"),
        ),
    )

    with pytest.raises(ValueError, match="state schema unions must contain exactly"):
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(draft, plan=plan)


def test_semantic_source_canonically_compiles_task_reward_and_verification(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "semantic-source")).design
    base_world, skeleton, graph, tool_semantics, closure = _inputs(tmp_path / "semantic-source-ir")
    task = design.curriculum.task_types[0]
    task_type = task.task_type
    task_draft = TaskRequirementDraft(
        task_type=task_type,
        objective=task.objective,
        allowed_actor_ids=task.allowed_actor_ids,
        required_tool_ids=task.required_tool_ids,
        initial_state_constraints=task.initial_state_constraints,
        success_conditions=tuple(
            rule.model_copy(update={"rule_id": f"rule:task:{task_type}:success:{index}"})
            for index, rule in enumerate(task.success_conditions)
        ),
        failure_conditions=tuple(
            rule.model_copy(update={"rule_id": f"rule:task:{task_type}:failure:{index}"})
            for index, rule in enumerate(task.failure_conditions)
        ),
        terminal_conditions=tuple(
            rule.model_copy(update={"rule_id": f"rule:task:{task_type}:terminal:{index}"})
            for index, rule in enumerate(task.terminal_conditions)
        ),
        difficulty_dimensions=("target",),
    )
    tool = base_world.tools[0]
    world_source = WorldSemanticSourceIRDraft(
        boundary=WorldBoundaryDraft(
            boundary=skeleton.boundary,
            task_dimensions=("target",),
            fidelity=skeleton.fidelity,
        ),
        state_inventory=StateEntityInventoryDraft(
            entities=(
                StateEntityPlan(
                    entity="counter",
                    purpose="Own the deterministic counter state.",
                    root_field="counter",
                    storage="singleton",
                    system_of_record="counter-runtime",
                    boundary_resource_ids=("counter",),
                    primary_key_fields=("value",),
                    evidence_claim_ids=("claim:counter",),
                ),
            )
        ),
        state_entity_schemas=(
            StateEntitySchemaIRDraft(
                entity="counter",
                root_node_id="counter",
                nodes=(
                    SchemaObjectNodeDraft(
                        node_id="counter",
                        kind="object",
                        properties=(
                            SchemaPropertyDraft(
                                name="value",
                                node_id="counter_value",
                                required=True,
                            ),
                        ),
                    ),
                    SchemaIntegerNodeDraft(
                        node_id="counter_value",
                        kind="integer",
                        minimum=0,
                    ),
                ),
            ),
        ),
        initial_state_rules=InitialStateRulesDraft(),
        tool_inventory=WorldToolPlanInventoryDraft(
            tools=(
                ToolSurfacePlan(
                    tool_id=tool.surface.tool_id,
                    namespace=tool.surface.namespace,
                    name=tool.surface.name,
                    description=tool.surface.description,
                    transport=tool.surface.transport,
                    writes_state_entities=("counter",),
                    evidence_claim_ids=tool.evidence_claim_ids,
                ),
            )
        ),
        tool_schemas=(
            ToolSchemaIRDraft(
                tool_id=tool.surface.tool_id,
                schema_kind="input",
                root_node_id="input",
                nodes=(
                    SchemaObjectNodeDraft(
                        node_id="input",
                        kind="object",
                        properties=(
                            SchemaPropertyDraft(
                                name="amount",
                                node_id="amount",
                                required=True,
                            ),
                        ),
                    ),
                    SchemaIntegerNodeDraft(node_id="amount", kind="integer", minimum=0),
                ),
            ),
            ToolSchemaIRDraft(
                tool_id=tool.surface.tool_id,
                schema_kind="output",
                root_node_id="output",
                nodes=(
                    SchemaObjectNodeDraft(
                        node_id="output",
                        kind="object",
                        properties=(
                            SchemaPropertyDraft(
                                name="value",
                                node_id="output_value",
                                required=True,
                            ),
                        ),
                    ),
                    SchemaIntegerNodeDraft(node_id="output_value", kind="integer"),
                ),
            ),
            ToolSchemaIRDraft(
                tool_id=tool.surface.tool_id,
                schema_kind="observation",
                root_node_id="observation",
                nodes=(
                    SchemaObjectNodeDraft(
                        node_id="observation",
                        kind="object",
                        properties=(
                            SchemaPropertyDraft(
                                name="counter",
                                node_id="observed_counter",
                                required=True,
                            ),
                        ),
                    ),
                    SchemaObjectNodeDraft(
                        node_id="observed_counter",
                        kind="object",
                        properties=(
                            SchemaPropertyDraft(
                                name="value",
                                node_id="observed_value",
                                required=True,
                            ),
                        ),
                    ),
                    SchemaIntegerNodeDraft(
                        node_id="observed_value",
                        kind="integer",
                        minimum=0,
                    ),
                ),
            ),
        ),
        tool_semantics=(tool_semantics,),
        closure=closure,
    )
    plan = CurriculumPlanDraft(
        coverage_dimensions=(
            CoverageDimension(
                dimension="state_transitions",
                evidence_discovered="complete",
                world_modelled="complete",
            ),
        ),
        task_plans=(
            CurriculumTaskPlan(
                task_type=task_type,
                objective=task.objective,
                allowed_actor_ids=task.allowed_actor_ids,
                required_tool_ids=task.required_tool_ids,
                difficulty_dimensions=("target",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="target",
                description="Size of the requested counter target.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )
    source = EnvironmentSemanticSourceDraft(
        world=world_source,
        curriculum_plan=plan,
        task_requirements=(task_draft,),
    )
    designer = cast(EnvironmentDesigner, object.__new__(EnvironmentDesigner))

    compiled = designer._compile_semantic_source(
        source,
        evidence_graph=graph,
        evidence_graph_ref=design.evidence_graph_ref,
    )

    compiled_task = compiled.curriculum.task_types[0]
    assert compiled_task.initial_config_schema["properties"] == {
        "counter": {
            "type": "object",
            "properties": {
                "value": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
            "required": ["value"],
        }
    }
    assert set(compiled_task.public_goal_schema) == {
        "type",
        "properties",
        "required",
        "additionalProperties",
    }
    assert compiled_task.evaluator_goal_schema == compiled_task.public_goal_schema
    assert compiled.reward.default_reward == 0
    assert compiled.reward.success_reward == 1.0
    assert compiled.reward.failure_reward == -1.0
    assert set(compiled.verification.required_rule_ids) > {
        rule.rule_id for rule in task_draft.success_conditions
    }
    assert "reward" not in EnvironmentSemanticSourceDraft.model_fields
    assert "verification" not in EnvironmentSemanticSourceDraft.model_fields
    assert "unresolved_questions" not in EnvironmentSemanticSourceDraft.model_fields
    assert "initial_config_schema" not in TaskRequirementDraft.model_fields
    with pytest.raises(ValidationError, match="unresolved_questions"):
        EnvironmentSemanticSourceDraft.model_validate(
            {
                **source.model_dump(mode="json"),
                "unresolved_questions": ("Manufacture a new release blocker.",),
            }
        )


def test_expansion_delta_claim_cannot_supply_framework_owned_task_after(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "delta-claim")).design
    previous_task = design.curriculum.task_types[0]
    changed_task = previous_task.model_copy(
        update={"objective": "Reach a newly expanded counter target."}
    )
    changed_curriculum = design.curriculum.model_copy(update={"task_types": (changed_task,)})
    draft = EnvironmentDesignDraft.model_validate(
        {
            "boundary": design.world_spec.boundary,
            "state": design.world_spec.state,
            "tools": design.world_spec.tools,
            "invariants": design.world_spec.invariants,
            "task_dimensions": design.world_spec.task_dimensions,
            "fidelity": design.world_spec.fidelity,
            "coverage_dimensions": (
                CoverageDimension(
                    dimension="task_scope",
                    evidence_discovered="complete",
                    world_modelled="complete",
                ),
            ),
            "curriculum": changed_curriculum,
            "reward": design.reward,
            "verification": design.verification,
        }
    )
    computed = ExpansionDesigner._compute_delta(design, draft)
    declared = ExpansionSemanticDeltaDraft(
        task_scope_deltas=(
            TaskScopeDeltaClaimDraft(
                operation="modify",
                task_type=previous_task.task_type,
                before_hash=ExpansionDesigner._task_semantic_hash(previous_task),
                rationale="Expand the target distribution.",
            ),
        ),
    )

    ExpansionDesigner._validate_declared_delta(declared, computed)
    assert "after" not in TaskScopeDeltaClaimDraft.model_fields
    with pytest.raises(ValidationError, match="after"):
        TaskScopeDeltaClaimDraft.model_validate(
            {
                **declared.task_scope_deltas[0].model_dump(mode="json"),
                "after": changed_task.model_dump(mode="json"),
            }
        )


def test_expansion_task_delta_ignores_framework_compiled_protocol_schema(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "task-projection")).design
    previous_task = design.curriculum.task_types[0]
    compiler_rebuilt_task = previous_task.model_copy(
        update={
            "initial_config_schema": {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            }
        }
    )
    draft = EnvironmentDesignDraft.model_validate(
        {
            "boundary": design.world_spec.boundary,
            "state": design.world_spec.state,
            "tools": design.world_spec.tools,
            "invariants": design.world_spec.invariants,
            "task_dimensions": design.world_spec.task_dimensions,
            "fidelity": design.world_spec.fidelity,
            "coverage_dimensions": (
                CoverageDimension(
                    dimension="state_schema",
                    evidence_discovered="complete",
                    world_modelled="complete",
                ),
            ),
            "curriculum": design.curriculum.model_copy(
                update={"task_types": (compiler_rebuilt_task,)}
            ),
            "reward": design.reward,
            "verification": design.verification,
        }
    )

    computed = ExpansionDesigner._compute_delta(design, draft)

    assert computed.task_scope_deltas == ()
    assert computed.task_distribution_deltas == ()


def test_state_change_with_recompiled_task_schema_is_not_task_scope_drift(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "state-derived-task")).design
    state_payload = design.world_spec.state.model_dump(mode="python")
    entity_schema = state_payload["entities"][0]["json_schema"]
    root_schema = state_payload["root_state_schema"]
    entity_schema["properties"]["value"]["maximum"] = 10_000
    root_schema["properties"]["counter"]["properties"]["value"]["maximum"] = 10_000
    changed_state = StateSchema.model_validate(state_payload)
    previous_task = design.curriculum.task_types[0]
    rebuilt_task = previous_task.model_copy(
        update={"initial_config_schema": changed_state.root_state_schema}
    )
    draft = EnvironmentDesignDraft.model_validate(
        {
            "boundary": design.world_spec.boundary,
            "state": changed_state,
            "tools": design.world_spec.tools,
            "invariants": design.world_spec.invariants,
            "task_dimensions": design.world_spec.task_dimensions,
            "fidelity": design.world_spec.fidelity,
            "coverage_dimensions": (
                CoverageDimension(
                    dimension="state_schema",
                    evidence_discovered="complete",
                    world_modelled="complete",
                ),
            ),
            "curriculum": design.curriculum.model_copy(update={"task_types": (rebuilt_task,)}),
            "reward": design.reward,
            "verification": design.verification,
        }
    )

    computed = ExpansionDesigner._compute_delta(design, draft)

    assert len(computed.state_schema_deltas) == 1
    assert computed.task_scope_deltas == ()
    ExpansionDesigner._validate_operator(
        SimpleNamespace(operator="transition_constraint"),  # type: ignore[arg-type]
        computed,
    )


def test_expansion_seed_space_is_a_first_class_task_distribution_delta(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "task-distribution")).design
    changed_curriculum = design.curriculum.model_copy(
        update={"generation_seed_space": "counter-seeds-v2"}
    )
    draft = EnvironmentDesignDraft.model_validate(
        {
            "boundary": design.world_spec.boundary,
            "state": design.world_spec.state,
            "tools": design.world_spec.tools,
            "invariants": design.world_spec.invariants,
            "task_dimensions": design.world_spec.task_dimensions,
            "fidelity": design.world_spec.fidelity,
            "coverage_dimensions": (
                CoverageDimension(
                    dimension="task_distribution",
                    evidence_discovered="complete",
                    world_modelled="complete",
                ),
            ),
            "curriculum": changed_curriculum,
            "reward": design.reward,
            "verification": design.verification,
        }
    )
    computed = ExpansionDesigner._compute_delta(design, draft)
    before = ExpansionDesigner._task_distribution(
        task_dimensions=design.world_spec.task_dimensions,
        curriculum=design.curriculum,
    )
    declared = ExpansionSemanticDeltaDraft(
        task_distribution_deltas=(
            TaskDistributionDeltaClaimDraft(
                before_hash=before.content_digest(),
                changed_aspects=("generation_seed_space",),
                rationale="Expand deterministic curriculum sampling coverage.",
            ),
        )
    )

    ExpansionDesigner._validate_declared_delta(declared, computed)
    ExpansionDesigner._validate_operator(SimpleNamespace(operator="task_scope"), computed)  # type: ignore[arg-type]
    assert computed.task_scope_deltas == ()
    assert computed.task_distribution_deltas[0].after.generation_seed_space == "counter-seeds-v2"
    assert "after" not in TaskDistributionDeltaClaimDraft.model_fields


def test_tool_surface_schema_cannot_drift_or_remain_open() -> None:
    plan = ToolSurfacePlan(
        tool_id="booking.reserve",
        namespace="booking",
        name="reserve",
        description="Reserve selected inventory.",
        transport="runtime",
        reads_state_entities=("booking",),
        evidence_claim_ids=("claim:booking",),
    )
    closed: dict[str, JsonValue] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    with pytest.raises(ValueError, match="must target booking.reserve"):
        EnvironmentDesigner._validate_tool_surface_schemas_draft(
            ToolSurfaceSchemasDraft(
                tool_id="booking.cancel",
                input_schema=closed,
                output_schema=closed,
                observation_schema=closed,
            ),
            plan=plan,
        )
    with pytest.raises(ValueError, match="kind must remain input"):
        EnvironmentDesigner._validate_tool_schema_draft(
            ToolSchemaDraft(
                tool_id="booking.reserve",
                schema_kind="output",
                json_schema=closed,
            ),
            plan=plan,
            schema_kind="input",
        )
    with pytest.raises(ValueError, match="additionalProperties=false"):
        EnvironmentDesigner._validate_tool_surface_schemas_draft(
            ToolSurfaceSchemasDraft(
                tool_id="booking.reserve",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": True,
                },
                output_schema=closed,
                observation_schema=closed,
            ),
            plan=plan,
        )
    with pytest.raises(ValueError, match="invalid Draft 2020-12 JSON Schema"):
        EnvironmentDesigner._validate_tool_schema_draft(
            ToolSchemaDraft(
                tool_id="booking.reserve",
                schema_kind="observation",
                json_schema={
                    "type": "object",
                    "properties": {"required": ["reservation_id"]},
                    "additionalProperties": False,
                },
            ),
            plan=plan,
            schema_kind="observation",
        )


def test_tool_schema_ir_compiles_required_arrays_and_unions_to_valid_draft() -> None:
    plan = ToolSurfacePlan(
        tool_id="booking.reserve",
        namespace="booking",
        name="reserve",
        description="Reserve selected inventory.",
        transport="runtime",
        reads_state_entities=("booking",),
        evidence_claim_ids=("claim:booking",),
    )
    schema_ir = ToolSchemaIRDraft(
        tool_id=plan.tool_id,
        schema_kind="observation",
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id",
                        node_id="reservation_id",
                        required=True,
                    ),
                    SchemaPropertyDraft(
                        name="events",
                        node_id="events",
                        required=False,
                    ),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaArrayNodeDraft(
                node_id="events",
                kind="array",
                items_node_id="event_or_null",
            ),
            SchemaUnionNodeDraft(
                node_id="event_or_null",
                kind="union",
                variant_node_ids=("event", "no_event"),
            ),
            SchemaObjectNodeDraft(
                node_id="event",
                kind="object",
                properties=(SchemaPropertyDraft(name="status", node_id="status", required=True),),
            ),
            SchemaStringNodeDraft(
                node_id="status",
                kind="string",
                enum_values=("accepted", "rejected"),
            ),
            SchemaNullNodeDraft(node_id="no_event", kind="null"),
        ),
    )

    EnvironmentDesigner._validate_tool_schema_ir_draft(
        schema_ir,
        plan=plan,
        schema_kind="observation",
    )
    compiled = EnvironmentDesigner._compile_tool_schema_ir(schema_ir)
    EnvironmentDesigner._validate_tool_schema_draft(
        compiled,
        plan=plan,
        schema_kind="observation",
    )

    assert compiled.json_schema["required"] == ["reservation_id"]
    properties = compiled.json_schema["properties"]
    assert isinstance(properties, dict)
    events = properties["events"]
    assert isinstance(events, dict)
    items = events["items"]
    assert isinstance(items, dict)
    assert "anyOf" in items


def test_tool_schema_ir_rejects_cycles_before_compilation() -> None:
    plan = ToolSurfacePlan(
        tool_id="booking.reserve",
        namespace="booking",
        name="reserve",
        description="Reserve selected inventory.",
        transport="runtime",
        reads_state_entities=("booking",),
        evidence_claim_ids=("claim:booking",),
    )
    draft = ToolSchemaIRDraft.model_validate_json(
        json.dumps(
            {
                "tool_id": plan.tool_id,
                "schema_kind": "input",
                "root_node_id": "root",
                "nodes": [
                    {
                        "node_id": "root",
                        "kind": "object",
                        "properties": [
                            {"name": "children", "node_id": "children", "required": True}
                        ],
                    },
                    {
                        "node_id": "children",
                        "kind": "array",
                        "items_node_id": "root",
                    },
                ],
            }
        )
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_tool_schema_ir_draft(
            draft,
            plan=plan,
            schema_kind="input",
        )

    assert captured.value.diagnostic.issue_codes == ("schema_graph_cycle@root_node_id",)


def test_tool_schema_prompt_requests_typed_ir_not_raw_json_schema() -> None:
    request = EnvironmentRequest(
        request_id="request:tool-schema-prompt",
        need="Generate a booking environment.",
        release_profile=ReleaseProfile(profile_id="release:test"),
    )

    prompt = EnvironmentDesigner._tool_schema_prompt(
        request,
        tool_id="booking.reserve",
        schema_kind="observation",
    )

    assert "Produce exactly ToolSchemaIRDraft" in prompt
    assert "flat, closed, acyclic node graph, not JSON Schema" in prompt
    assert "SchemaPropertyDraft.required boolean" in prompt


def test_tool_semantics_cannot_drift_from_the_frozen_surface(tmp_path: Path) -> None:
    _, skeleton, graph, tool_draft, _ = _inputs(tmp_path)
    drifted = tool_draft.model_copy(update={"tool_id": "counter.replace"})

    with pytest.raises(StructuredSemanticError) as raised:
        EnvironmentDesigner._validate_tool_semantics_draft(
            drifted,
            expected_tool_id="counter.increment",
            skeleton=skeleton,
            evidence_graph=graph,
        )

    assert [(issue.code, issue.location) for issue in raised.value.issues] == [
        ("tool_semantics_identity", ("tool_id",)),
    ]


def test_tool_rule_shard_failure_is_field_addressable_before_feedback_routing(
    tmp_path: Path,
) -> None:
    """Regression for the live batch that previously produced opaque ValueError roots."""

    _, skeleton, graph, tool_draft, _ = _inputs(tmp_path)
    invalid_precondition = tool_draft.semantics.preconditions[0].model_copy(
        update={
            "rule_id": "rule:wrong-tool:precondition",
            "evidence_claim_ids": ("claim:not-frozen",),
        }
    )
    conditions = ToolConditionsDraft(
        tool_id=tool_draft.tool_id,
        preconditions=(invalid_precondition,),
        postconditions=tool_draft.semantics.postconditions,
    )

    with pytest.raises(StructuredSemanticError) as raised:
        EnvironmentDesigner._validate_tool_conditions_draft(
            conditions,
            expected_tool_id=tool_draft.tool_id,
            skeleton=skeleton,
            evidence_graph=graph,
        )

    assert {(issue.code, issue.location) for issue in raised.value.issues} == {
        ("tool_rule_id_prefix", ("preconditions", 0, "rule_id")),
        (
            "tool_rule_evidence_unknown",
            ("preconditions", 0, "evidence_claim_ids", 0),
        ),
    }
    routed = EnvironmentDesigner._prefixed_validation_issues(
        raised.value,
        prefix=("tools", 0, "conditions"),
    )
    assert {issue.code for issue in routed} == {
        "tool_rule_id_prefix",
        "tool_rule_evidence_unknown",
    }
    assert all(issue.code != "framework_diagnostic_incomplete" for issue in routed)
    assert all(issue.actionable_for_agent for issue in routed)
    prefix_issue = next(issue for issue in routed if issue.code == "tool_rule_id_prefix")
    assert prefix_issue.violated_condition == "tool Rule ids must use the frozen tool prefix"
    assert prefix_issue.expected_category == "a Rule identifier in the assigned tool namespace"


def test_validation_diagnostics_expose_only_bounded_code_and_path() -> None:
    with pytest.raises(ValidationError) as captured:
        WorldBoundaryDraft.model_validate(
            {
                "boundary": {"primary_domain": "invalid domain"},
                "task_dimensions": [],
                "fidelity": [],
            }
        )

    issues = EnvironmentDesigner._validation_issue_codes(captured.value)

    assert issues
    assert all("invalid domain" not in issue for issue in issues)
    assert any("boundary.primary_domain" in issue for issue in issues)


def test_assumption_closure_requires_typed_claim_and_fidelity() -> None:
    claim = Claim(
        claim_id="claim:scope:cancel-out-of-scope",
        kind="bounded_assumption",
        statement="Cancellation and no-show handling are outside the first package boundary.",
        confidence=1.0,
        status="supported",
        risk="medium",
    )
    fidelity = FidelityStatement(
        statement_id="fidelity.cancel-out-of-scope",
        claim="The first package models booking creation but not cancellation or no-show.",
        level="bounded_approximation",
        known_divergence="Cancellation, no-show, and deposit-deadline transitions are absent.",
        evidence_claim_ids=(claim.claim_id,),
    )

    closure = EvidenceAssumptionClosureDraft(
        resolutions=(
            AssumptionResolutionDraft(
                issue_id="assumption-issue:cancellation",
                question="How should cancellation be represented?",
                disposition="bounded_out_of_scope",
                rationale="The frozen tool surface contains booking creation only.",
                claim=claim,
                fidelity=fidelity,
            ),
        )
    )

    EnvironmentDesigner._validate_assumption_resolution(
        closure.resolutions[0],
        evidence_ids=set(),
        available_claim_ids={claim.claim_id},
    )
    with pytest.raises(ValidationError) as captured:
        AssumptionResolutionDraft(
            issue_id="assumption-issue:cancellation",
            question="How should cancellation be represented?",
            disposition="bounded_out_of_scope",
            rationale="It is outside the first package.",
        )
    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="evidenceassumptionclosuredraft_shape",
        frontier_ordinal=10,
    )
    assert diagnostic.issue_codes == ("schema_assumption_closure_payload_required@root",)
    assert "Provide both claim and fidelity" in diagnostic.feedback


def test_assumption_closure_collects_all_origins_without_duplicate_model_work(
    tmp_path: Path,
) -> None:
    design = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design
    shared = "Which inventory authority should the synthetic environment use?"
    coverage_only = "No direct inventory synchronization tool is in the frozen surface."
    world = design.world_spec.model_copy(update={"unknowns": (shared,)})
    revised_design = design.model_copy(
        update={"world_spec": world, "unresolved_questions": (shared,)}
    )
    graph = EvidenceGraph(
        graph_id="graph:assumption-origins",
        revision=1,
        unresolved_questions=(shared,),
    )
    coverage = CoverageMap(
        coverage_id="coverage:assumption-origins",
        revision=1,
        dimensions=(
            CoverageDimension(
                dimension="inventory",
                evidence_discovered="complete",
                world_modelled="complete",
                unknowns=(shared, coverage_only),
            ),
        ),
        evidence_graph_ref=design.evidence_graph_ref,
    )
    bundle = cast(
        DesignBundle,
        SimpleNamespace(
            evidence_graph=graph,
            design=revised_design,
            world_spec=world,
            coverage_map=coverage,
        ),
    )

    issues = EnvironmentDesigner._assumption_closure_issues(bundle)

    assert tuple(item.statement for item in issues) == (shared, coverage_only)
    assert tuple(origin.source for origin in issues[0].origins) == (
        "evidence_graph",
        "environment_design",
        "world_spec",
        "coverage_dimension",
    )
    assert issues[0].origins[-1].coverage_dimension == "inventory"
    assert issues[0].issue_id == EnvironmentDesigner._assumption_closure_issues(bundle)[0].issue_id

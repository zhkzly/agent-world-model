from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from pydantic import BaseModel, JsonValue, ValidationError
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
from agent_world.designer.final_design_compiler import (
    compile_curriculum_plan_semantics,
    compile_task_requirement_semantics,
    compile_training_semantics,
    compile_world_rules,
)
from agent_world.designer.final_design_leaves import (
    _curriculum_plan_prompt,
    _curriculum_prompt,
    _task_requirement_prompt,
    _world_rules_prompt,
)
from agent_world.designer.models import (
    ActorAuthoritySourceDraft,
    AssumptionResolutionDraft,
    CompactFieldSemanticDraft,
    CurriculumPlanDraft,
    CurriculumPlanSourceDraft,
    CurriculumTaskPlan,
    CurriculumTaskPlanSourceDraft,
    EnvironmentDesignDraft,
    EnvironmentSemanticSourceDraft,
    EvidenceAssumptionClosureDraft,
    ExpansionSemanticDeltaDraft,
    InitialStateRulesDraft,
    InitialStateRulesSourceDraft,
    RuleConstantDraft,
    RuleDraft,
    RuleGreaterOrEqualClauseDraft,
    RuleLessThanClauseDraft,
    RuleReferenceDraft,
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
    TaskRequirementSourceDraft,
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
    TrainingSemanticSourceDraft,
    WorldArchitectureSourceDraft,
    WorldBoundaryDraft,
    WorldBoundarySourceDraft,
    WorldClosureDraft,
    WorldClosureReferenceTerm,
    WorldClosureSourceDraft,
    WorldModelDraft,
    WorldRuleSemanticsSourceDraft,
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


def _world_rule_source(
    *,
    family: Literal["initial_state", "invariant"],
    rule_id: str | None,
) -> RuleDraft:
    """One complete semantic RuleDraft with no fixture-only compiler shortcut."""

    return RuleDraft(
        rule_id=rule_id,
        family=family,
        description="Counter state remains non-negative.",
        boolean_operator="all",
        clauses=(
            RuleGreaterOrEqualClauseDraft(
                clause_id="counter-non-negative",
                operator="greater_or_equal",
                ordering="number",
                left=RuleReferenceDraft(
                    kind="reference",
                    source="pre_state",
                    pointer="/counter/value",
                    value_type="number",
                ),
                right=RuleConstantDraft(kind="constant", value_type="number", value=0),
            ),
        ),
        case_sensitivity="positive_only",
    )


def _counter_architecture_source(skeleton: WorldSkeletonDraft) -> WorldArchitectureSourceDraft:
    """Complete frozen Architecture input for WorldRules compiler integration tests."""

    surface = skeleton.tool_surfaces[0]
    return WorldArchitectureSourceDraft(
        boundary=WorldBoundarySourceDraft(
            primary_domain=skeleton.boundary.primary_domain,
            actors_and_authority=tuple(
                ActorAuthoritySourceDraft(
                    actor=actor.actor,
                    authorities=actor.authorities,
                )
                for actor in skeleton.boundary.actors_and_authority
            ),
            systems_of_record=skeleton.boundary.systems_of_record,
            transition_authorities=skeleton.boundary.transition_authorities,
            tool_namespaces=skeleton.boundary.tool_namespaces,
            core_invariants=skeleton.boundary.core_invariants,
            task_dimensions=skeleton.task_dimensions,
            fidelity=skeleton.fidelity,
        ),
        state_entities=(
            StateEntitySourceDraft(
                entity="counter",
                purpose="Own deterministic counter state.",
                root_field="counter",
                storage="singleton",
                system_of_record=skeleton.boundary.systems_of_record[0],
                owned_resource_ids=("counter",),
                visible_to_actor_ids=tuple(
                    actor.actor
                    for actor in skeleton.boundary.actors_and_authority
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
                                # Match the already-committed ToolSemantics
                                # projection exactly.  WorldRules receives
                                # frozen Architecture plus that behavior, so
                                # this integration input must preserve the
                                # public observation field name rather than
                                # merely a similar scalar shape.
                                name="counter",
                                value_type="integer",
                                description="Visible counter observation.",
                            ),
                        ),
                    ),
                ),
            )
        ),
    )


def test_world_rule_source_derives_framework_rule_ids() -> None:
    """WorldRules accepts semantic Rules, never Agent-authored IR identities."""

    initial = EnvironmentDesigner._compile_initial_state_rules_source(
        InitialStateRulesSourceDraft(
            initial_state_constraints=(
                _world_rule_source(family="initial_state", rule_id="agent-initial-id"),
                _world_rule_source(family="initial_state", rule_id=None),
            )
        )
    )
    closure = EnvironmentDesigner._compile_world_closure_source(
        WorldClosureSourceDraft(
            invariants=(
                _world_rule_source(family="invariant", rule_id="agent-invariant-id"),
                _world_rule_source(family="invariant", rule_id=None),
            )
        )
    )

    assert tuple(rule.rule_id for rule in initial.initial_state_constraints) == (
        "rule:state:0",
        "rule:state:1",
    )
    assert tuple(rule.rule_id for rule in closure.invariants) == (
        "rule:world:0",
        "rule:world:1",
    )


def test_world_rules_compiler_canonicalizes_agent_rule_ids_before_persisting(
    tmp_path: Path,
) -> None:
    """The production compiler, not only its leaf helpers, owns Rule identities."""

    world, skeleton, graph, tool_semantics, _closure = _inputs(tmp_path)
    source = WorldRuleSemanticsSourceDraft(
        initial_state_rules=InitialStateRulesSourceDraft(
            initial_state_constraints=(
                _world_rule_source(family="initial_state", rule_id="agent-initial-id"),
            )
        ),
        invariants=(_world_rule_source(family="invariant", rule_id="agent-invariant-id"),),
    )

    compiled = compile_world_rules(
        source,
        architecture=_counter_architecture_source(skeleton),
        tool_semantics=(tool_semantics,),
        evidence_graph=graph,
        evidence_graph_ref=world.evidence_graph_ref,
    )

    assert (
        compiled.canonical_source.initial_state_rules.initial_state_constraints[0].rule_id is None
    )
    assert compiled.canonical_source.invariants[0].rule_id is None
    assert compiled.world.state.initial_state_constraints[0].rule_id == "rule:state:0"
    assert compiled.world.invariants[0].rule_id == "rule:world:0"


def test_world_rules_compiler_accepts_no_additional_global_invariant(
    tmp_path: Path,
) -> None:
    """Tool-local semantics need no placeholder World Rule when closure is empty."""

    world, skeleton, graph, tool_semantics, _closure = _inputs(tmp_path)
    compiled = compile_world_rules(
        WorldRuleSemanticsSourceDraft(
            initial_state_rules=InitialStateRulesSourceDraft(),
            invariants=(),
        ),
        architecture=_counter_architecture_source(skeleton),
        tool_semantics=(tool_semantics,),
        evidence_graph=graph,
        evidence_graph_ref=world.evidence_graph_ref,
    )

    assert compiled.canonical_source.invariants == ()
    assert compiled.world.invariants == ()
    validated_world = WorldSpec.model_validate(
        {
            **world.model_dump(),
            "invariants": (),
        }
    )
    assert validated_world.invariants == ()


@pytest.mark.parametrize(
    ("source", "compiler", "expected_code", "expected_path"),
    (
        (
            InitialStateRulesSourceDraft(
                initial_state_constraints=(_world_rule_source(family="invariant", rule_id=None),)
            ),
            EnvironmentDesigner._compile_initial_state_rules_source,
            "initial_state_rule_family",
            ("initial_state_rules", "initial_state_constraints", 0, "family"),
        ),
        (
            WorldClosureSourceDraft(
                invariants=(_world_rule_source(family="initial_state", rule_id=None),)
            ),
            EnvironmentDesigner._compile_world_closure_source,
            "world_invariant_rule_family",
            ("invariants", 0, "family"),
        ),
    ),
)
def test_world_rule_source_reports_section_family_as_actionable(
    source: InitialStateRulesSourceDraft | WorldClosureSourceDraft,
    compiler: object,
    expected_code: str,
    expected_path: tuple[str | int, ...],
) -> None:
    """Semantic family is repairable; framework-generated IDs are not."""

    with pytest.raises(StructuredValidationError) as captured:
        compiler(source)  # type: ignore[operator]

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "world_rules_source_compile"
    assert diagnostic.issue_codes == (f"{expected_code}@{'.'.join(map(str, expected_path))}",)
    assert diagnostic.issues[0].actionable_for_agent


def test_world_rule_prompts_keep_rule_id_ownership_in_framework() -> None:
    request = EnvironmentRequest(
        request_id="request:world-rules-prompt",
        need="Generate a bounded counter environment.",
        release_profile=ReleaseProfile(profile_id="release:test"),
    )
    active = _world_rules_prompt(
        SimpleNamespace(request=SimpleNamespace(need=request.need)),
        SimpleNamespace(model_dump=lambda **_kwargs: {}),
        (),
        EvidenceGraph(graph_id="evidence:world-rules-prompt", revision=1),
    )
    legacy_world = EnvironmentDesigner._world_rules_prompt(request)
    legacy_initial = EnvironmentDesigner._initial_state_rules_prompt(request)
    legacy_closure = EnvironmentDesigner._world_closure_prompt(request)
    normalized_legacy_initial = " ".join(legacy_initial.split())

    assert "initial_state_rules.initial_state_constraints" in active
    assert "family `initial_state`" in active
    assert "family `invariant`" in active
    assert "omit optional `rule_id`" in active
    assert "rule:state:<ordinal>" in active
    assert "rule:world:<ordinal>" in active
    assert "applies to every later task materialization" in active
    assert "permitted actor/tool path cannot create them" in active
    assert "an empty list is correct" in active
    assert "collection-existence restatement" in active
    assert "constant-only comparison" in active
    assert "omit optional `rule_id`" in legacy_world
    assert "an empty list is correct" in legacy_world
    assert "optional `rule_id`" in legacy_initial
    assert "applies to every later task materialization" in normalized_legacy_initial
    assert "optional `rule_id`" in legacy_closure


def test_task_curriculum_prompts_and_view_keep_semantics_bounded(tmp_path: Path) -> None:
    """The Agent sees only frozen world/claims plus role guidance, not broad state."""

    request = EnvironmentRequest(
        request_id="request:task-curriculum-prompt",
        need="Generate a bounded counter environment.",
        release_profile=ReleaseProfile(profile_id="release:test"),
    )
    design = portable_counter_contracts(ArtifactStore(tmp_path / "task-curriculum-prompt")).design
    world = WorldModelDraft(
        boundary=design.world_spec.boundary,
        state=design.world_spec.state,
        tools=design.world_spec.tools,
        invariants=design.world_spec.invariants,
        task_dimensions=design.world_spec.task_dimensions,
        fidelity=design.world_spec.fidelity,
    )
    active = _curriculum_prompt(
        SimpleNamespace(request=SimpleNamespace(need=request.need)),
        world,
        EvidenceGraph(graph_id="evidence:task-curriculum-prompt", revision=1),
    )
    active_context = json.loads(active.rsplit("Frozen context:\n", maxsplit=1)[1])
    task = design.curriculum.task_types[0]
    dimension = design.curriculum.difficulty_dimensions[0]
    plan_source = CurriculumPlanSourceDraft(
        coverage_dimensions=(CoverageDimension(dimension="state_transitions"),),
        task_plans=(
            CurriculumTaskPlanSourceDraft(
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
    )
    active_plan = _curriculum_plan_prompt(
        SimpleNamespace(request=SimpleNamespace(need=request.need)),
        world,
        EvidenceGraph(graph_id="evidence:curriculum-plan-prompt", revision=1),
    )
    active_plan_context = json.loads(active_plan.rsplit("Frozen context:\n", maxsplit=1)[1])
    active_task = _task_requirement_prompt(
        SimpleNamespace(request=SimpleNamespace(need=request.need)),
        world,
        plan_source,
        plan_source.task_plans[0].model_dump(mode="json"),
        EvidenceGraph(graph_id="evidence:task-requirement-prompt", revision=1),
    )
    active_task_context = json.loads(active_task.rsplit("Frozen context:\n", maxsplit=1)[1])
    legacy_training = EnvironmentDesigner._training_semantics_prompt(request)
    legacy_plan = EnvironmentDesigner._curriculum_plan_prompt(request)
    legacy_task = EnvironmentDesigner._task_requirement_prompt(
        request,
        task_type="increase_counter",
    )

    assert set(active_context) == {"claims", "coverage_rule_catalog", "world"}
    assert set(active_plan_context) == {
        "claims",
        "coverage_rule_catalog",
        "task_authoring_access",
        "task_dimension_catalog",
        "world",
    }
    assert tuple(active_plan_context["task_dimension_catalog"]) == world.task_dimensions
    assert active_plan_context["task_authoring_access"] == [
        {
            "actor_id": actor.actor,
            "permitted_tool_ids": [
                tool.surface.tool_id
                for tool in world.tools
                if actor.actor in tool.semantics.permission.allowed_actors
            ],
        }
        for actor in world.boundary.actors_and_authority
    ]
    assert tuple(
        (item["rule_id"], item["family"]) for item in active_context["coverage_rule_catalog"]
    ) == tuple(
        (rule.rule_id, rule.family)
        for rule in EnvironmentDesigner._world_rule_sequence(world)  # noqa: SLF001
    )
    assert "omit optional `rule_id`" in active
    assert "rule:sampling:<ordinal>" in active
    assert "rule:task:<task_type>:<section>:<ordinal>" in active
    for prompt in (
        active,
        active_plan,
        active_task,
        legacy_training,
        legacy_plan,
        legacy_task,
    ):
        assert "action-only args, tool_result, error, events" in " ".join(prompt.split())
    assert "Sampling Rules use family `sampling`" in active
    assert "initial-state Rules use family `initial_state`" in active
    assert "success Rules use `task_success`" in active
    assert "failure Rules use `task_failure`" in active
    assert "terminal Rules use `task_terminal`" in active
    assert "Every task requirement must include all four Rule-list fields" in active
    assert "`terminal_conditions` (non-empty)" in active
    assert (
        "For every task requirement, at least one success Rule and at least one terminal Rule"
        in (active)
    )
    assert "scalar, non-root, non-overlapping `task_goal` pointers" in active
    assert "Runtime `terminated` or `truncated`" in active
    assert "`coverage_dimensions[*].rule_ids`" in active
    assert "`coverage_rule_catalog`" in active
    assert "Leave `rule_ids` empty" in active
    assert "closed top-level catalog" in active_plan
    assert "every `task_dimension_catalog` id" in active_plan
    assert "do not rename, omit, add, or reorder ids" in active_plan
    assert "optional `rule_id` from sampling" in legacy_training
    assert "terminal_conditions (non-empty)" in legacy_training
    assert "`coverage_dimensions[*].rule_ids`" in legacy_training
    assert "rule:sampling:<ordinal>" in legacy_plan
    assert "`coverage_dimensions[*].rule_ids`" in legacy_plan
    assert "optional `rule_id`" in legacy_task
    assert legacy_task.count("use non-root, non-overlapping RFC 6901 pointers") == 1
    assert "`terminal_conditions` must" in legacy_task
    assert "Initial-state Rules may only read reset-available actor, pre_state" in legacy_task

    assert "Produce exactly one `CurriculumPlanSourceDraft`" in active_plan
    assert "one independent TaskRequirement call" in active_plan
    assert "alternative task callers, not a roster" in active_plan
    assert "every listed actor must be allowed to invoke every listed required tool" in active_plan
    assert "`task_authoring_access`" in active_plan
    assert "Do not emit TaskRequirement fields" in active_plan
    source_schema = CurriculumPlanSourceDraft.model_json_schema(mode="validation")
    task_properties = source_schema["$defs"]["CurriculumTaskPlanSourceDraft"]["properties"]
    assert "Alternative task callers" in task_properties["allowed_actor_ids"]["description"]
    assert "eligible task caller" in task_properties["required_tool_ids"]["description"]
    assert "success_conditions" not in active_plan_context
    assert set(active_task_context) == {
        "claims",
        "curriculum_plan",
        "target_task_plan",
        "world",
    }
    assert active_task_context["target_task_plan"]["task_type"] == task.task_type
    assert "Produce exactly one `TaskRequirementSourceDraft`" in active_task
    assert "Preserve target_task_plan.task_type" in active_task
    assert "Include all four Rule-list fields" in active_task
    assert "Do not emit sampling, coverage, schemas" in active_task


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
    source = _counter_architecture_source(existing)

    compiled = EnvironmentDesigner.__new__(EnvironmentDesigner)._compile_architecture_skeleton(
        source,
        evidence_graph=graph,
    )

    assert compiled.tool_surfaces[0].surface.tool_id == existing.tool_surfaces[0].surface.tool_id
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
    assert len(encoded.encode("utf-8")) > 0


def test_tool_free_frozen_input_projection_does_not_enforce_a_fixed_byte_ceiling() -> None:
    class LargeFrozenInput(BaseModel):
        payload: str

    prompt = EnvironmentDesigner._with_frozen_inputs(
        "Return the requested typed artifact.",
        input=LargeFrozenInput(payload="x" * (1024 * 1024 + 1)),
    )

    assert len(prompt.encode("utf-8")) > 1024 * 1024
    assert prompt.endswith("END_FROZEN_JSON name=input\n")


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
    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._compile_task_requirement_shard(
            draft.model_copy(update={"objective": "Drift from the frozen task plan."}),
            target=plan.task_plans[0],
            world=world,
            path_prefix=("task_requirements", 0),
        )
    drift_issue = captured.value.diagnostic.issues[0]
    assert drift_issue.code == "task_requirement_plan_field_drift"
    assert drift_issue.location == ("task_requirements", 0, "objective")
    assert drift_issue.violated_condition
    assert drift_issue.expected_category
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
    valid_plan = plan.model_copy(
        update={
            "coverage_dimensions": (
                plan.coverage_dimensions[0].model_copy(
                    update={"rule_ids": (world.invariants[0].rule_id,)}
                ),
            )
        }
    )
    EnvironmentDesigner._validate_curriculum_plan(  # noqa: SLF001
        valid_plan,
        world=world,
        evidence_graph=EvidenceGraph(graph_id="evidence:empty", revision=1),
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
    issue = diagnostic.issues[0]
    assert issue.violated_condition == (
        "coverage rule_ids reference only frozen world Rule identifiers"
    )
    assert issue.expected_category == "an exact frozen coverage Rule identifier"


def test_curriculum_plan_reports_closed_ordered_difficulty_catalog(tmp_path: Path) -> None:
    """A multi-item catalog must not collapse into generic Agent-invented axes."""

    design = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design
    world = WorldModelDraft(
        boundary=design.world_spec.boundary,
        state=design.world_spec.state,
        tools=design.world_spec.tools,
        invariants=design.world_spec.invariants,
        task_dimensions=("create_task", "complete_task", "delete_task", "list_tasks"),
        fidelity=design.world_spec.fidelity,
    )
    task = design.curriculum.task_types[0]
    catalog = tuple(
        DifficultyDimension(
            dimension=dimension,
            description=f"Frozen dimension {index}.",
            levels=("low", "high"),
        )
        for index, dimension in enumerate(world.task_dimensions)
    )
    plan = CurriculumPlanDraft(
        coverage_dimensions=(CoverageDimension(dimension="state_transitions"),),
        task_plans=(
            CurriculumTaskPlan(
                task_type=task.task_type,
                objective=task.objective,
                allowed_actor_ids=task.allowed_actor_ids,
                required_tool_ids=task.required_tool_ids,
                difficulty_dimensions=(world.task_dimensions[0],),
                minimum_tool_calls=task.minimum_tool_calls,
            ),
        ),
        difficulty_dimensions=tuple(reversed(catalog)),
        generation_seed_space=design.curriculum.generation_seed_space,
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_curriculum_plan(  # noqa: SLF001
            plan,
            world=world,
            evidence_graph=EvidenceGraph(graph_id="evidence:empty", revision=1),
        )

    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "curriculum_difficulty_catalog_drift"
    assert issue.location == ("difficulty_dimensions",)
    assert issue.message == (
        "Build the top-level DifficultyDimension catalog by copying every frozen WorldModel "
        "task_dimensions id exactly once and in order; task plans may then select an applicable "
        "subset."
    )
    assert issue.expected_category == "the full exact ordered WorldModel task_dimensions catalog"


def test_world_model_reports_unknown_evidence_claim_as_actionable_field(
    tmp_path: Path,
) -> None:
    # An unknown evidence-claim reference must surface as a typed, field-addressed,
    # actionable diagnostic that never echoes the rejected claim id.  Before this
    # was a bare ValueError that collapsed to a non-actionable
    # framework_diagnostic_incomplete, stranding the world_rules leaf.
    design = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design
    invariant = design.world_spec.invariants[0].model_copy(
        update={"evidence_claim_ids": ("claim:not-in-graph",)}
    )
    world = WorldModelDraft(
        boundary=design.world_spec.boundary,
        state=design.world_spec.state,
        tools=design.world_spec.tools,
        invariants=(invariant, *design.world_spec.invariants[1:]),
        task_dimensions=design.world_spec.task_dimensions,
        fidelity=design.world_spec.fidelity,
    )

    # A graph that catalogs every legitimately referenced claim so only the
    # poisoned invariant reference is unknown.
    evidence_graph = EvidenceGraph(
        graph_id="evidence:counter",
        revision=1,
        claims=(
            Claim(
                claim_id="claim:counter",
                kind="product_decision",
                statement="Counter semantics are a deterministic synthetic policy.",
                confidence=1.0,
            ),
        ),
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_world_model_draft(  # noqa: SLF001
            world,
            evidence_graph=evidence_graph,
            evidence_graph_ref=design.world_spec.evidence_graph_ref,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "world_model_semantics"
    assert diagnostic.issue_codes == (
        "world_model_evidence_claim_unknown@invariants.0.evidence_claim_ids.0",
    )
    for issue in diagnostic.issues:
        assert issue.actionable_for_agent
        assert "claim:not-in-graph" not in issue.message
        assert "claim:" not in issue.message


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
        "expected_actionable",
    ),
    (
        (
            "family",
            "initial_state_rule_family",
            ("initial_state_constraints", 0, "family"),
            "rejected-family",
            "initial-state rules must use family initial_state",
            "a Rule with family initial_state",
            True,
        ),
        (
            "id_prefix",
            "initial_state_rule_id_prefix",
            ("initial_state_constraints", 0, "rule_id"),
            "rejected-rule-id",
            "initial-state Rule ids must use the rule:state: prefix",
            "a Rule id beginning with rule:state:",
            False,
        ),
        (
            "duplicate_id",
            "initial_state_rule_id_duplicate",
            ("initial_state_constraints", 1, "rule_id"),
            "rule:state:duplicate",
            "initial-state Rule ids must be unique",
            "unique Rule ids within initial-state constraints",
            False,
        ),
    ),
)
def test_initial_state_rule_diagnostics_are_safe_and_actionable(
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path: tuple[str | int, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
    expected_actionable: bool,
) -> None:
    """WorldRules-owned reset rules retain a safe causal repair identity."""

    _, skeleton, graph, _, closure = _inputs(tmp_path)
    source_rule = closure.invariants[0]
    state_shape = WorldStateShapeDraft(
        entities=skeleton.state.entities,
        root_state_schema=skeleton.state.root_state_schema,
    )
    if case == "family":
        rules = InitialStateRulesDraft(
            initial_state_constraints=(
                source_rule.model_copy(
                    update={"family": rejected_value, "rule_id": "rule:state:valid"}
                ),
            )
        )
    elif case == "id_prefix":
        rules = InitialStateRulesDraft(
            initial_state_constraints=(
                source_rule.model_copy(
                    update={"family": "initial_state", "rule_id": rejected_value}
                ),
            )
        )
    else:
        rule = source_rule.model_copy(update={"family": "initial_state", "rule_id": rejected_value})
        rules = InitialStateRulesDraft(initial_state_constraints=(rule, rule))

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_initial_state_rules_draft(  # noqa: SLF001
            rules,
            state_shape=state_shape,
            evidence_graph=graph,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "initial_state_rules_semantics"
    assert diagnostic.issue_codes == (f"{expected_code}@{'.'.join(map(str, expected_path))}",)
    issue = diagnostic.issues[0]
    assert issue.actionable_for_agent is expected_actionable
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert rejected_value not in str(diagnostic)


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
    ),
    (
        (
            "root_schema",
            "world_state_shape_root_schema",
            ("root_state_schema",),
            "array",
            "root state schema must be an object with explicit properties",
            "an object state schema with explicit properties",
        ),
        (
            "duplicate_visibility",
            "world_state_shape_visibility_duplicate",
            ("boundary", "actors_and_authority", 0, "visibility", 1),
            "counter",
            "each actor visibility field may appear only once",
            "a visibility field list without repeats",
        ),
        (
            "unknown_visibility",
            "world_state_shape_visibility_unknown",
            ("boundary", "actors_and_authority", 0, "visibility", 1),
            "rejected-visibility-field",
            "actor visibility may reference only root state properties",
            "a visibility field declared by the root state schema",
        ),
    ),
)
def test_world_state_shape_diagnostics_preserve_source_ownership(
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path: tuple[str | int, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """The same compiler check is actionable only for its proposing source."""

    _, skeleton, graph, _, _ = _inputs(tmp_path)
    state_shape = WorldStateShapeDraft(
        entities=skeleton.state.entities,
        root_state_schema=skeleton.state.root_state_schema,
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )
    if case == "root_schema":
        state_shape = state_shape.model_copy(update={"root_state_schema": {"type": rejected_value}})
    else:
        actor = boundary.boundary.actors_and_authority[0]
        visibility = (
            (*actor.visibility, actor.visibility[0])
            if case == "duplicate_visibility"
            else (*actor.visibility, rejected_value)
        )
        boundary = boundary.model_copy(
            update={
                "boundary": boundary.boundary.model_copy(
                    update={
                        "actors_and_authority": (
                            actor.model_copy(update={"visibility": visibility}),
                            *boundary.boundary.actors_and_authority[1:],
                        )
                    }
                )
            }
        )

    for diagnostic_retryable in (True, False):
        with pytest.raises(StructuredValidationError) as captured:
            EnvironmentDesigner._validate_world_state_shape_draft(  # noqa: SLF001
                state_shape,
                boundary=boundary,
                evidence_graph=graph,
                diagnostic_retryable=diagnostic_retryable,
            )

        issue = captured.value.diagnostic.issues[0]
        assert issue.code == expected_code
        assert issue.location == expected_path
        assert issue.actionable_for_agent is diagnostic_retryable
        assert issue.violated_condition == expected_condition
        assert issue.expected_category == expected_category
        assert rejected_value not in str(captured.value.diagnostic)


def test_world_state_shape_frozen_evidence_issue_is_non_actionable(tmp_path: Path) -> None:
    """A frozen state shape cannot turn an evidence closure check into a retry."""

    _, skeleton, graph, _, _ = _inputs(tmp_path)
    rejected_value = "rejected-claim"
    state_shape = WorldStateShapeDraft(
        entities=(
            skeleton.state.entities[0].model_copy(update={"evidence_claim_ids": (rejected_value,)}),
        ),
        root_state_schema=skeleton.state.root_state_schema,
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_world_state_shape_draft(  # noqa: SLF001
            state_shape,
            boundary=boundary,
            evidence_graph=graph,
            diagnostic_retryable=False,
        )

    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "world_model_evidence_claim_unknown"
    assert issue.location == ("entities", 0, "evidence_claim_ids", 0)
    assert not issue.actionable_for_agent
    assert rejected_value not in str(captured.value.diagnostic)


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
    ),
    (
        (
            "bound",
            "world_tool_plan_bound",
            ("tools",),
            "increment8",
            "tool plan inventory must not exceed the framework tool limit",
            "at most the configured number of tool plans",
        ),
        (
            "duplicate_id",
            "world_tool_plan_id_duplicate",
            ("tools", 1, "tool_id"),
            "counter.increment",
            "tool plan ids must be unique",
            "a unique tool id within the plan inventory",
        ),
        (
            "id_mismatch",
            "world_tool_plan_id_mismatch",
            ("tools", 0, "tool_id"),
            "rejected.tool",
            "tool id must equal its namespace and name",
            "a tool id in the form <namespace>.<name>",
        ),
        (
            "namespace_unknown",
            "world_tool_plan_namespace_unknown",
            ("tools", 0, "namespace"),
            "rejected_namespace",
            "tool namespace must exist in the frozen WorldBoundary",
            "a namespace declared by the frozen WorldBoundary",
        ),
        (
            "claim_duplicate",
            "world_tool_plan_evidence_claim_duplicate",
            ("tools", 0, "evidence_claim_ids", 1),
            "claim:counter",
            "tool evidence claim ids must be unique",
            "an evidence claim list without repeats",
        ),
    ),
)
def test_world_tool_plan_inventory_diagnostics_preserve_source_ownership(
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path: tuple[str | int, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """Tool-plan diagnostics remain safe in proposal and frozen-input contexts."""

    _, skeleton, graph, _, _ = _inputs(tmp_path)
    surface = skeleton.tool_surfaces[0].surface
    plan = ToolSurfacePlan(
        tool_id=surface.tool_id,
        namespace=surface.namespace,
        name=surface.name,
        description=surface.description,
        transport=surface.transport,
        reads_state_entities=("counter",),
        evidence_claim_ids=("claim:counter",),
    )
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )
    if case == "bound":
        tools = tuple(
            plan.model_copy(
                update={
                    "name": f"increment{index}",
                    "tool_id": f"{plan.namespace}.increment{index}",
                }
            )
            for index in range(MAX_WORLD_TOOL_SURFACES + 1)
        )
        inventory = WorldToolPlanInventoryDraft.model_construct(tools=tools)
    elif case == "duplicate_id":
        inventory = WorldToolPlanInventoryDraft(tools=(plan, plan))
    elif case == "id_mismatch":
        inventory = WorldToolPlanInventoryDraft(
            tools=(plan.model_copy(update={"tool_id": rejected_value}),)
        )
    elif case == "namespace_unknown":
        inventory = WorldToolPlanInventoryDraft(
            tools=(
                plan.model_copy(
                    update={
                        "namespace": rejected_value,
                        "tool_id": f"{rejected_value}.{plan.name}",
                    }
                ),
            )
        )
    else:
        inventory = WorldToolPlanInventoryDraft(
            tools=(
                plan.model_copy(update={"evidence_claim_ids": ("claim:counter", rejected_value)}),
            )
        )

    for diagnostic_retryable in (True, False):
        with pytest.raises(StructuredValidationError) as captured:
            EnvironmentDesigner._validate_world_tool_plan_inventory_draft(  # noqa: SLF001
                inventory,
                boundary=boundary,
                evidence_graph=graph,
                diagnostic_retryable=diagnostic_retryable,
            )

        issue = captured.value.diagnostic.issues[0]
        assert issue.code == expected_code
        assert issue.location == expected_path
        assert issue.actionable_for_agent is diagnostic_retryable
        assert issue.violated_condition == expected_condition
        assert issue.expected_category == expected_category
        assert rejected_value not in str(captured.value.diagnostic)


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
    ),
    (
        (
            "bound",
            "world_tool_inventory_bound",
            ("tool_surfaces",),
            "increment8",
            "tool inventory must not exceed the framework tool limit",
            "at most the configured number of tool surfaces",
        ),
        (
            "duplicate_id",
            "world_tool_inventory_id_duplicate",
            ("tool_surfaces", 1, "surface", "tool_id"),
            "counter.increment",
            "tool inventory ids must be unique",
            "a unique tool id in the frozen inventory",
        ),
        (
            "namespace_unknown",
            "world_tool_inventory_namespace_unknown",
            ("tool_surfaces", 0, "surface", "namespace"),
            "rejected_namespace",
            "tool inventory namespaces must exist in the frozen WorldBoundary",
            "a namespace declared by the frozen WorldBoundary",
        ),
    ),
)
def test_world_tool_inventory_compiler_invariants_are_safe_and_non_actionable(
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path: tuple[str | int, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """Framework-composed ToolSurfaces cannot consume a semantic retry."""

    _, skeleton, graph, _, _ = _inputs(tmp_path)
    boundary = WorldBoundaryDraft(
        boundary=skeleton.boundary,
        task_dimensions=skeleton.task_dimensions,
        fidelity=skeleton.fidelity,
    )
    surface = skeleton.tool_surfaces[0]
    if case == "bound":
        tool_surfaces = tuple(
            surface.model_copy(
                update={
                    "surface": surface.surface.model_copy(
                        update={
                            "name": f"increment{index}",
                            "tool_id": f"{surface.surface.namespace}.increment{index}",
                        }
                    )
                }
            )
            for index in range(MAX_WORLD_TOOL_SURFACES + 1)
        )
        inventory = WorldToolInventoryDraft.model_construct(tool_surfaces=tool_surfaces)
    elif case == "duplicate_id":
        inventory = WorldToolInventoryDraft(tool_surfaces=(surface, surface))
    else:
        unknown_surface = surface.model_copy(
            update={
                "surface": surface.surface.model_copy(
                    update={
                        "namespace": rejected_value,
                        "tool_id": f"{rejected_value}.{surface.surface.name}",
                    }
                )
            }
        )
        inventory = WorldToolInventoryDraft(tool_surfaces=(unknown_surface,))

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_world_tool_inventory_draft(  # noqa: SLF001
            inventory,
            boundary=boundary,
            evidence_graph=graph,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "tool_inventory_semantics"
    issue = diagnostic.issues[0]
    assert issue.code == expected_code
    assert issue.location == expected_path
    assert not issue.actionable_for_agent
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert rejected_value not in str(diagnostic)


@pytest.mark.parametrize(
    (
        "case",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
    ),
    (
        (
            "task_dimension",
            "world_skeleton_task_dimension_invalid",
            ("task_dimensions",),
            "human readable label",
            "world skeleton task dimensions must be stable identifiers",
            "a stable task dimension identifier list",
        ),
        (
            "tool_bound",
            "world_skeleton_tool_bound",
            ("tool_surfaces",),
            "increment8",
            "world skeleton must not exceed the framework tool limit",
            "at most the configured number of tool surfaces",
        ),
        (
            "tool_duplicate",
            "world_skeleton_tool_id_duplicate",
            ("tool_surfaces", 1, "surface", "tool_id"),
            "counter.increment",
            "world skeleton tool ids must be unique",
            "a unique tool id in the frozen skeleton",
        ),
        (
            "tool_namespace",
            "world_skeleton_tool_namespace_unknown",
            ("tool_surfaces", 0, "surface", "namespace"),
            "rejected_namespace",
            "world skeleton tool namespaces must exist in the frozen WorldBoundary",
            "a namespace declared by the frozen WorldBoundary",
        ),
        (
            "root_schema",
            "world_skeleton_root_schema",
            ("state", "root_state_schema"),
            "array",
            "world skeleton root state schema must be an object with explicit properties",
            "an object state schema with explicit properties",
        ),
        (
            "visibility_duplicate",
            "world_skeleton_visibility_duplicate",
            ("boundary", "actors_and_authority", 0, "visibility", 1),
            "counter",
            "world skeleton actor visibility fields must be unique",
            "a visibility field list without repeats",
        ),
        (
            "visibility_unknown",
            "world_skeleton_visibility_unknown",
            ("boundary", "actors_and_authority", 0, "visibility", 1),
            "rejected_visibility",
            "world skeleton actor visibility may reference only root state properties",
            "a visibility field declared by the root state schema",
        ),
        (
            "bounded_divergence",
            "world_skeleton_bounded_divergence_missing",
            ("fidelity", 0, "known_divergence"),
            "bounded_approximation",
            "bounded approximation fidelity requires a known divergence",
            "a non-empty known divergence statement",
        ),
        (
            "faithful_divergence",
            "world_skeleton_faithful_divergence_forbidden",
            ("fidelity", 0, "known_divergence"),
            "rejected-divergence",
            "faithful fidelity must not declare a known divergence",
            "a null known divergence",
        ),
    ),
)
def test_world_skeleton_compiler_invariants_are_safe_and_non_actionable(
    tmp_path: Path,
    case: str,
    expected_code: str,
    expected_path: tuple[str | int, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """WorldRules cannot repair a framework-composed skeleton."""

    _, skeleton, graph, _, _ = _inputs(tmp_path)
    surface = skeleton.tool_surfaces[0]
    if case == "task_dimension":
        draft = skeleton.model_copy(update={"task_dimensions": (rejected_value,)})
    elif case == "tool_bound":
        tool_surfaces = tuple(
            surface.model_copy(
                update={
                    "surface": surface.surface.model_copy(
                        update={
                            "name": f"increment{index}",
                            "tool_id": f"{surface.surface.namespace}.increment{index}",
                        }
                    )
                }
            )
            for index in range(MAX_WORLD_TOOL_SURFACES + 1)
        )
        draft = WorldSkeletonDraft.model_construct(
            boundary=skeleton.boundary,
            state=skeleton.state,
            tool_surfaces=tool_surfaces,
            task_dimensions=skeleton.task_dimensions,
            fidelity=skeleton.fidelity,
        )
    elif case == "tool_duplicate":
        draft = skeleton.model_copy(update={"tool_surfaces": (surface, surface)})
    elif case == "tool_namespace":
        unknown_surface = surface.model_copy(
            update={
                "surface": surface.surface.model_copy(
                    update={
                        "namespace": rejected_value,
                        "tool_id": f"{rejected_value}.{surface.surface.name}",
                    }
                )
            }
        )
        draft = skeleton.model_copy(update={"tool_surfaces": (unknown_surface,)})
    elif case == "root_schema":
        draft = skeleton.model_copy(
            update={
                "state": skeleton.state.model_copy(
                    update={"root_state_schema": {"type": rejected_value}}
                )
            }
        )
    elif case.startswith("visibility"):
        actor = skeleton.boundary.actors_and_authority[0]
        visibility = (
            (*actor.visibility, actor.visibility[0])
            if case == "visibility_duplicate"
            else (*actor.visibility, rejected_value)
        )
        boundary = skeleton.boundary.model_copy(
            update={
                "actors_and_authority": (
                    actor.model_copy(update={"visibility": visibility}),
                    *skeleton.boundary.actors_and_authority[1:],
                )
            }
        )
        draft = skeleton.model_copy(update={"boundary": boundary})
    else:
        fidelity = skeleton.fidelity[0].model_copy(
            update=(
                {"level": rejected_value, "known_divergence": None}
                if case == "bounded_divergence"
                else {"level": "faithful", "known_divergence": rejected_value}
            )
        )
        draft = skeleton.model_copy(update={"fidelity": (fidelity,)})

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_world_skeleton(  # noqa: SLF001
            draft,
            evidence_graph=graph,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "world_skeleton_semantics"
    issue = diagnostic.issues[0]
    assert issue.code == expected_code
    assert issue.location == expected_path
    assert not issue.actionable_for_agent
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert rejected_value not in str(diagnostic)


@pytest.mark.parametrize(
    "validator",
    (
        EnvironmentDesigner._validate_world_state_shape_draft,
        EnvironmentDesigner._validate_initial_state_rules_draft,
        EnvironmentDesigner._validate_world_tool_plan_inventory_draft,
        EnvironmentDesigner._validate_tool_schema_draft,
        EnvironmentDesigner._validate_tool_surface_schemas_draft,
        EnvironmentDesigner._validate_world_tool_inventory_draft,
        EnvironmentDesigner._validate_world_skeleton,
    ),
)
def test_world_rules_diagnostic_validators_do_not_raise_bare_value_error(
    validator: object,
) -> None:
    """Known WorldRules compiler boundaries cannot fall through one-shot's catch-all."""

    assert "raise ValueError" not in inspect.getsource(validator)


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


def _counter_world_semantic_source(
    base_world: WorldSpec,
    skeleton: WorldSkeletonDraft,
    tool_semantics: ToolSemanticsDraft,
    closure: WorldClosureDraft,
    *,
    task_dimension: str = "target",
) -> WorldSemanticSourceIRDraft:
    """Build the complete frozen WorldRules closure used by TaskCurriculum tests."""

    tool = base_world.tools[0]
    return WorldSemanticSourceIRDraft(
        boundary=WorldBoundaryDraft(
            boundary=skeleton.boundary,
            task_dimensions=(task_dimension,),
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
    world_source = _counter_world_semantic_source(
        base_world,
        skeleton,
        tool_semantics,
        closure,
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

    poisoned_tool_plan = world_source.tool_inventory.tools[0].model_copy(
        update={"tool_id": "rejected.tool"}
    )
    poisoned_world_source = world_source.model_copy(
        update={
            "tool_inventory": world_source.tool_inventory.model_copy(
                update={"tools": (poisoned_tool_plan,)}
            )
        }
    )
    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._compile_world_semantic_source(  # noqa: SLF001
            poisoned_world_source,
            evidence_graph=graph,
            evidence_graph_ref=design.evidence_graph_ref,
        )
    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "world_tool_plan_id_mismatch"
    assert issue.location == ("tools", 0, "tool_id")
    assert not issue.actionable_for_agent
    assert "rejected.tool" not in str(captured.value.diagnostic)

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


def test_task_curriculum_compiler_derives_ids_and_reports_source_rule_family(
    tmp_path: Path,
) -> None:
    """Execute the real TaskCurriculum compiler on a complete frozen WorldRules closure.

    Provenance: a portable counter WorldRules closure.  The only poisoned value
    below is ``success_conditions[0].family``; the assertion records the exact
    safe Agent-facing diagnostic rather than a generic compiler exception.
    """

    design = portable_counter_contracts(ArtifactStore(tmp_path / "task-curriculum")).design
    base_world, skeleton, graph, tool_semantics, closure = _inputs(
        tmp_path / "task-curriculum-world-rules"
    )
    world = WorldModelDraft(
        boundary=base_world.boundary,
        state=base_world.state,
        tools=base_world.tools,
        invariants=base_world.invariants,
        task_dimensions=base_world.task_dimensions,
        fidelity=base_world.fidelity,
    )
    task_dimension = world.task_dimensions[0]
    world_source = _counter_world_semantic_source(
        base_world,
        skeleton,
        tool_semantics,
        closure,
        task_dimension=task_dimension,
    )
    task = design.curriculum.task_types[0]
    task_type = task.task_type

    pre_counter = RuleReferenceDraft(
        kind="reference",
        source="pre_state",
        pointer="/counter/value",
        value_type="number",
    )
    post_counter = RuleReferenceDraft(
        kind="reference",
        source="post_state",
        pointer="/counter/value",
        value_type="number",
    )
    task_goal = RuleReferenceDraft(
        kind="reference",
        source="task_goal",
        pointer="/target",
        value_type="number",
    )
    zero = RuleConstantDraft(kind="constant", value_type="number", value=0)

    def task_goal_rule(
        rule_id: str,
        family: Literal["task_success", "task_terminal"],
        description: str,
    ) -> RuleDraft:
        return RuleDraft(
            rule_id=rule_id,
            family=family,
            description=description,
            boolean_operator="all",
            clauses=(
                RuleGreaterOrEqualClauseDraft(
                    clause_id=f"{rule_id}-target",
                    operator="greater_or_equal",
                    ordering="number",
                    left=post_counter,
                    right=task_goal,
                ),
            ),
            case_sensitivity="positive_only",
        )

    initial_rule = RuleDraft(
        rule_id="agent-initial-rule",
        family="initial_state",
        description="Counter state starts at or above zero.",
        boolean_operator="all",
        clauses=(
            RuleGreaterOrEqualClauseDraft(
                clause_id="initial-counter-nonnegative",
                operator="greater_or_equal",
                ordering="number",
                left=pre_counter,
                right=zero,
            ),
        ),
        case_sensitivity="positive_only",
    )
    failure_rule = RuleDraft(
        rule_id="agent-failure-rule",
        family="task_failure",
        description="Counter remains below the requested target.",
        boolean_operator="all",
        clauses=(
            RuleLessThanClauseDraft(
                clause_id="counter-below-target",
                operator="less_than",
                ordering="number",
                left=post_counter,
                right=task_goal,
            ),
        ),
        case_sensitivity="positive_only",
    )
    sampling_rule = RuleDraft(
        rule_id="agent-sampling-rule",
        family="sampling",
        description="Sample only nonnegative counter starting states.",
        boolean_operator="all",
        clauses=(
            RuleGreaterOrEqualClauseDraft(
                clause_id="sample-counter-nonnegative",
                operator="greater_or_equal",
                ordering="number",
                left=pre_counter,
                right=zero,
            ),
        ),
        case_sensitivity="positive_only",
    )
    source = TrainingSemanticSourceDraft(
        curriculum_plan=CurriculumPlanSourceDraft(
            coverage_dimensions=(
                CoverageDimension(
                    dimension="state_transitions",
                    evidence_discovered="complete",
                    world_modelled="complete",
                ),
            ),
            task_plans=(
                CurriculumTaskPlanSourceDraft(
                    task_type=task_type,
                    objective=task.objective,
                    allowed_actor_ids=task.allowed_actor_ids,
                    required_tool_ids=task.required_tool_ids,
                    difficulty_dimensions=(task_dimension,),
                    minimum_tool_calls=task.minimum_tool_calls,
                ),
            ),
            difficulty_dimensions=(
                DifficultyDimension(
                    dimension=task_dimension,
                    description="Size of the requested counter target.",
                    levels=("small", "large"),
                ),
            ),
            generation_seed_space="all uint64 seeds",
            sampling_constraints=(sampling_rule,),
        ),
        task_requirements=(
            TaskRequirementSourceDraft(
                task_type=task_type,
                objective=task.objective,
                allowed_actor_ids=task.allowed_actor_ids,
                required_tool_ids=task.required_tool_ids,
                initial_state_constraints=(initial_rule,),
                success_conditions=(
                    task_goal_rule(
                        "agent-success-rule",
                        "task_success",
                        "Counter reaches the requested target.",
                    ),
                ),
                failure_conditions=(failure_rule,),
                terminal_conditions=(
                    task_goal_rule(
                        "agent-terminal-rule",
                        "task_terminal",
                        "Counter target terminates the task.",
                    ),
                ),
                difficulty_dimensions=(task_dimension,),
                minimum_tool_calls=task.minimum_tool_calls,
            ),
        ),
    )

    compiled_plan = compile_curriculum_plan_semantics(
        source.curriculum_plan,
        world=world,
        evidence_graph=graph,
    )
    action_scoped_sampling = sampling_rule.model_copy(
        update={
            "clauses": (
                sampling_rule.clauses[0].model_copy(
                    update={"left": pre_counter.model_copy(update={"source": "args"})}
                ),
            )
        }
    )
    with pytest.raises(StructuredValidationError) as action_scoped_error:
        compile_curriculum_plan_semantics(
            source.curriculum_plan.model_copy(
                update={"sampling_constraints": (action_scoped_sampling,)}
            ),
            world=world,
            evidence_graph=graph,
        )
    assert "curriculum_sampling_action_source_forbidden" in str(action_scoped_error.value)
    compiled_requirement = compile_task_requirement_semantics(
        source.task_requirements[0],
        curriculum_plan=compiled_plan.canonical_source,
        target_task_type=task_type,
        world=world,
        evidence_graph=graph,
    )
    assert compiled_plan.plan.task_plans[0].task_type == task_type
    assert compiled_plan.canonical_source.sampling_constraints[0].rule_id is None
    assert compiled_requirement.task.task_type == task_type
    assert tuple(rule.rule_id for rule in compiled_requirement.task.success_conditions) == (
        f"rule:task:{task_type}:success:0",
    )

    compiled = compile_training_semantics(
        source,
        world_source=world_source,
        world=world,
        evidence_graph=graph,
    )

    canonical_task = compiled.canonical_source.task_requirements[0]
    assert compiled.canonical_source.curriculum_plan.sampling_constraints[0].rule_id is None
    assert canonical_task.initial_state_constraints[0].rule_id is None
    assert canonical_task.success_conditions[0].rule_id is None
    assert canonical_task.failure_conditions[0].rule_id is None
    assert canonical_task.terminal_conditions[0].rule_id is None
    compiled_task = compiled.design.curriculum.task_types[0]
    assert tuple(rule.rule_id for rule in compiled.design.curriculum.sampling_constraints) == (
        "rule:sampling:0",
    )
    assert tuple(rule.rule_id for rule in compiled_task.initial_state_constraints) == (
        f"rule:task:{task_type}:initial_state:0",
    )
    assert tuple(rule.rule_id for rule in compiled_task.success_conditions) == (
        f"rule:task:{task_type}:success:0",
    )
    assert tuple(rule.rule_id for rule in compiled_task.failure_conditions) == (
        f"rule:task:{task_type}:failure:0",
    )
    assert tuple(rule.rule_id for rule in compiled_task.terminal_conditions) == (
        f"rule:task:{task_type}:terminal:0",
    )

    poisoned_task = source.task_requirements[0].model_copy(
        update={
            "success_conditions": (
                source.task_requirements[0]
                .success_conditions[0]
                .model_copy(update={"family": "task_failure"}),
            )
        }
    )
    poisoned = source.model_copy(update={"task_requirements": (poisoned_task,)})
    with pytest.raises(StructuredValidationError) as captured:
        compile_training_semantics(
            poisoned,
            world_source=world_source,
            world=world,
            evidence_graph=graph,
        )
    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "task_success_rule_family"
    assert issue.location == ("task_requirements", 0, "success_conditions", 0, "family")
    assert issue.violated_condition
    assert issue.expected_category
    assert issue.actionable_for_agent
    assert issue.code != "framework_diagnostic_incomplete"


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
    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_tool_surface_schemas_draft(
            ToolSurfaceSchemasDraft(
                tool_id="booking.cancel",
                input_schema=closed,
                output_schema=closed,
                observation_schema=closed,
            ),
            plan=plan,
        )
    issue = captured.value.diagnostic.issues[0]
    assert captured.value.diagnostic.validation_phase == "tool_surface_schemas_semantics"
    assert issue.code == "world_tool_surface_schema_target_mismatch"
    assert issue.location == ("tool_id",)
    assert not issue.actionable_for_agent
    assert issue.violated_condition == "tool surface schemas must target the frozen tool plan"
    assert issue.expected_category == "a schema bundle whose tool_id matches the frozen tool plan"
    assert "booking.cancel" not in str(captured.value.diagnostic)
    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_tool_schema_draft(
            ToolSchemaDraft(
                tool_id="booking.reserve",
                schema_kind="output",
                json_schema=closed,
            ),
            plan=plan,
            schema_kind="input",
        )
    assert captured.value.diagnostic.issues[0].code == "world_tool_schema_kind_mismatch"
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


@pytest.mark.parametrize(
    (
        "draft",
        "schema_kind",
        "expected_code",
        "expected_path",
        "rejected_value",
        "expected_condition",
        "expected_category",
    ),
    (
        (
            ToolSchemaDraft(
                tool_id="rejected.tool",
                schema_kind="input",
                json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            "input",
            "world_tool_schema_target_mismatch",
            ("tool_id",),
            "rejected.tool",
            "tool schema must target the frozen tool plan",
            "a schema whose tool_id matches the frozen tool plan",
        ),
        (
            ToolSchemaDraft(
                tool_id="booking.reserve",
                schema_kind="output",
                json_schema={
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            ),
            "input",
            "world_tool_schema_kind_mismatch",
            ("schema_kind",),
            "output",
            "tool schema kind must match the frozen schema role",
            "a schema_kind matching the frozen schema role",
        ),
    ),
)
def test_tool_schema_compiler_invariants_are_safe_and_non_actionable(
    draft: ToolSchemaDraft,
    schema_kind: str,
    expected_code: str,
    expected_path: tuple[str, ...],
    rejected_value: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """Compiled tool schemas cannot consume an Agent repair attempt."""

    plan = ToolSurfacePlan(
        tool_id="booking.reserve",
        namespace="booking",
        name="reserve",
        description="Reserve selected inventory.",
        transport="runtime",
        reads_state_entities=("booking",),
        evidence_claim_ids=("claim:booking",),
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._validate_tool_schema_draft(  # noqa: SLF001
            draft,
            plan=plan,
            schema_kind=schema_kind,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "tool_schema_semantics"
    issue = diagnostic.issues[0]
    assert issue.code == expected_code
    assert issue.location == expected_path
    assert not issue.actionable_for_agent
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert rejected_value not in str(diagnostic)


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

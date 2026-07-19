from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pydantic import BaseModel

from agent_world.contracts import ArtifactRef, EvidenceGraph
from agent_world.control.feedback import RepairTargetRef
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
)
from agent_world.designer.models import (
    CompactFieldSemanticDraft,
    SharedAtomicityDomainSourceDraft,
    SharedConcurrencyDomainSourceDraft,
    SharedErrorPolicySourceDraft,
    SharedIdempotencyDomainSourceDraft,
    SharedToolSemanticsSourceDraft,
    ToolInterfaceSourceDraft,
    ToolSemanticsBatchSourceDraft,
    ToolSemanticSourceDraft,
    ToolSurfacePlan,
    ToolSurfaceSourceDraft,
    WorldArchitectureSourceDraft,
    WorldToolPlanInventoryDraft,
    WorldToolSourceInventoryDraft,
)
from agent_world.designer.service import (
    DesignerError,
    EnvironmentDesigner,
    ToolSemanticsRepairProjection,
)
from agent_world.designer.validation import StructuredSemanticError, StructuredSemanticIssue


class _ProjectionTool(BaseModel):
    tool_id: str
    errors: dict[str, str]
    reliability: dict[str, str]


class _ProjectionBatch(BaseModel):
    tools: tuple[_ProjectionTool, ...]


def test_retired_world_skeleton_resume_is_not_a_public_success_path() -> None:
    assert not hasattr(EnvironmentDesigner, "resume_from_world_skeleton")
    assert not hasattr(EnvironmentDesigner, "adopt_world_skeleton_checkpoint")


def _plan(index: int, *, namespace: str, reads: tuple[str, ...]) -> ToolSurfacePlan:
    return ToolSurfacePlan(
        tool_id=f"hotel.tool-{index}",
        namespace=namespace,
        name=f"tool-{index}",
        description=f"Hotel operation {index}.",
        transport="runtime",
        reads_state_entities=reads,
        evidence_claim_ids=("claim:hotel",),
    )


def test_read_only_tool_is_valid_but_empty_footprint_is_not() -> None:
    readonly = _plan(1, namespace="hotel", reads=("inventory",))
    assert readonly.writes_state_entities == ()

    with pytest.raises(ValueError, match="non-empty read/write"):
        _plan(2, namespace="hotel", reads=())


def test_eight_tools_compile_to_at_most_two_stable_batches() -> None:
    plans = tuple(
        _plan(
            index,
            namespace="hotel" if index < 5 else f"aux-{index}",
            reads=("inventory" if index < 5 else f"state-{index}",),
        )
        for index in range(8)
    )
    architecture = WorldArchitectureSourceDraft.model_construct(
        tool_inventory=WorldToolPlanInventoryDraft(tools=plans)
    )

    batches = EnvironmentDesigner._tool_semantic_batches(architecture)

    assert len(batches) == 2
    assert all(1 <= len(batch) <= 4 for batch in batches)
    assert tuple(tool_id for batch in batches for tool_id in batch) == tuple(
        item.tool_id for item in plans
    )


def test_five_coupled_tools_get_one_shared_group_and_two_execution_batches() -> None:
    plans = tuple(
        _plan(index, namespace="hotel", reads=("inventory", "reservations"))
        for index in range(5)
    )
    architecture = WorldArchitectureSourceDraft.model_construct(
        tool_inventory=WorldToolPlanInventoryDraft(tools=plans)
    )
    architecture_ref = ArtifactRef(
        artifact_id="architecture:hotel",
        artifact_type="design.world_architecture_source",
        revision_id="sha256:" + "1" * 64,
        content_hash="sha256:" + "2" * 64,
        size_bytes=1,
        media_type="application/json",
    )

    plan = EnvironmentDesigner._compile_tool_coupling_plan(
        architecture,
        architecture_ref=architecture_ref,
    )

    assert len(plan.groups) == 1
    assert plan.groups[0].mode == "multi_batch"
    assert plan.groups[0].shared_state_entity_ids == ("inventory", "reservations")
    assert tuple(map(len, plan.execution_batches)) == (4, 1)


def test_shared_tool_policy_requires_exact_domain_partitions() -> None:
    tool_ids = ("hotel.search", "hotel.reserve")
    group = SimpleNamespace(ordered_tool_ids=tool_ids)
    source = SharedToolSemanticsSourceDraft(
        atomicity_domains=(
            SharedAtomicityDomainSourceDraft(
                domain_id="atomicity:hotel",
                member_tool_ids=tool_ids,
                atomicity="atomic",
                rationale="Both operations share one reservation workflow.",
            ),
        ),
        concurrency_domains=(
            SharedConcurrencyDomainSourceDraft(
                domain_id="concurrency:hotel",
                member_tool_ids=tool_ids,
                isolation="serializable",
                rationale="Reservation inventory must not be double-booked.",
            ),
        ),
        idempotency_domains=(
            SharedIdempotencyDomainSourceDraft(
                domain_id="idempotency:hotel",
                member_tool_ids=tool_ids,
                mode="natural",
                rationale="The same frozen request has a stable result.",
            ),
        ),
        error_policies=(
            SharedErrorPolicySourceDraft(
                policy_id="error-policy:timeout",
                member_tool_ids=tool_ids,
                required_error_suffix="timeout",
                retryable=True,
                rationale="Both operations expose bounded transient timeout behavior.",
            ),
        ),
    )

    EnvironmentDesigner._validate_shared_tool_semantics_source(
        source,
        group=cast(Any, group),
        evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
    )
    invalid = source.model_copy(
        update={
            "atomicity_domains": (
                source.atomicity_domains[0].model_copy(
                    update={"member_tool_ids": (tool_ids[0],)}
                ),
            )
        }
    )
    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_shared_tool_semantics_source(
            invalid,
            group=cast(Any, group),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
        )
    assert "shared_contract_partition" in {issue.code for issue in captured.value.issues}


def test_tool_batch_rejects_nested_identity_drift_before_semantic_compilation() -> None:
    expected_id = "hotel.reserve"
    valid_shard = SimpleNamespace(tool_id=expected_id)
    source = ToolSemanticSourceDraft.model_construct(
        tool_id=expected_id,
        conditions=SimpleNamespace(tool_id="hotel.cancel"),
        state_transition=valid_shard,
        errors=valid_shard,
        access_observation=valid_shard,
        reliability=valid_shard,
    )
    batch = ToolSemanticsBatchSourceDraft.model_construct(tools=(source,))
    designer = EnvironmentDesigner.__new__(EnvironmentDesigner)

    with pytest.raises(ValueError, match="nested identity"):
        designer._compile_tool_semantics_batch(
            batch,
            expected_tool_ids=(expected_id,),
            skeleton=cast(Any, object()),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
        )


def test_tool_batch_preflight_aggregates_findings_across_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_ids = ("hotel.search", "hotel.reserve")

    def item(tool_id: str) -> ToolSemanticSourceDraft:
        shard = SimpleNamespace(tool_id=tool_id)
        return ToolSemanticSourceDraft.model_construct(
            tool_id=tool_id,
            conditions=shard,
            state_transition=shard,
            errors=shard,
            access_observation=shard,
            reliability=shard,
        )

    batch = ToolSemanticsBatchSourceDraft.model_construct(
        tools=tuple(item(tool_id) for tool_id in tool_ids)
    )
    skeleton = SimpleNamespace(
        tool_surfaces=tuple(
            SimpleNamespace(
                surface=SimpleNamespace(
                    tool_id=tool_id,
                    observation_schema={"type": "object", "properties": {"result": {}}},
                )
            )
            for tool_id in tool_ids
        )
    )
    designer = EnvironmentDesigner.__new__(EnvironmentDesigner)
    for name in (
        "_compile_tool_conditions_source",
        "_compile_tool_state_transition_source",
        "_compile_tool_errors_source",
        "_compile_tool_access_observation_source",
        "_compile_tool_reliability_source",
    ):
        monkeypatch.setattr(designer, name, lambda source, **_kwargs: source)
    monkeypatch.setattr(
        designer,
        "_compose_tool_behavior",
        lambda conditions, transition, errors: SimpleNamespace(
            tool_id=conditions.tool_id,
            conditions=conditions,
            transition=transition,
            errors=errors,
        ),
    )

    def reject_conditions(_value: object, *, expected_tool_id: str, **_kwargs: object) -> None:
        raise StructuredSemanticError(
            (
                StructuredSemanticIssue(
                    code="condition_contract",
                    location=("preconditions",),
                    message=f"{expected_tool_id} conditions are invalid.",
                ),
            )
        )

    monkeypatch.setattr(designer, "_validate_tool_conditions_draft", reject_conditions)
    monkeypatch.setattr(designer, "_validate_tool_state_transition_draft", lambda *_a, **_k: None)
    monkeypatch.setattr(designer, "_validate_tool_errors_draft", lambda *_a, **_k: None)
    monkeypatch.setattr(designer, "_validate_tool_behavior_draft", lambda *_a, **_k: None)
    monkeypatch.setattr(designer, "_validate_tool_access_observation_draft", lambda *_a, **_k: None)
    monkeypatch.setattr(designer, "_validate_tool_reliability_draft", lambda *_a, **_k: None)

    with pytest.raises(StructuredValidationError) as captured:
        designer._compile_tool_semantics_batch(
            batch,
            expected_tool_ids=tool_ids,
            skeleton=cast(Any, skeleton),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
        )

    assert {issue.location[:2] for issue in captured.value.diagnostic.issues} == {
        ("tools", 0),
        ("tools", 1),
    }


def test_reliability_reports_the_complete_closed_error_reference_graph() -> None:
    reliability = SimpleNamespace(
        tool_id="hotel.reserve",
        retry=SimpleNamespace(
            retryable_error_codes=("error:timeout", "error:not-retryable")
        ),
        timeout=SimpleNamespace(timeout_error_code="error:timeout"),
        rollback=SimpleNamespace(
            rollback_trigger_codes=("error:rollback",),
            compensation_tools=("hotel.cancel-missing",),
        ),
        concurrency=SimpleNamespace(conflict_error_code="error:conflict"),
    )
    behavior = SimpleNamespace(
        errors=(SimpleNamespace(error_code="error:not-retryable", retryable=False),)
    )
    skeleton = SimpleNamespace(
        tool_surfaces=(SimpleNamespace(surface=SimpleNamespace(tool_id="hotel.reserve")),)
    )

    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_tool_reliability_draft(
            cast(Any, reliability),
            expected_tool_id="hotel.reserve",
            skeleton=cast(Any, skeleton),
            behavior=cast(Any, behavior),
        )

    assert {issue.code for issue in captured.value.issues} == {
        "reliability_retry_error_unknown",
        "reliability_retryability_mismatch",
        "reliability_timeout_error_unknown",
        "reliability_rollback_error_unknown",
        "reliability_conflict_error_unknown",
        "reliability_compensation_tool_unknown",
    }


def test_error_reference_failure_authorizes_errors_and_reliability_only() -> None:
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="tool_semantics_batch_preflight",
        frontier_ordinal=30,
        issues=(
            SafeValidationIssue(
                "reliability_timeout_error_unknown",
                ("tools", 2, "reliability", "timeout", "timeout_error_code"),
                "timeout_error_code must be declared by this tool's errors section.",
            ),
        ),
    )

    assert ToolSemanticsRepairProjection().roots(diagnostic) == (
        "tools/2/errors",
        "tools/2/reliability",
    )


def test_tool_repair_projection_rejects_shortened_correction_safely() -> None:
    baseline = _ProjectionBatch(
        tools=(
            _ProjectionTool(tool_id="hotel.search", errors={}, reliability={}),
            _ProjectionTool(tool_id="hotel.reserve", errors={}, reliability={}),
        )
    )
    correction = _ProjectionBatch(
        tools=(_ProjectionTool(tool_id="hotel.search", errors={}, reliability={}),)
    )

    with pytest.raises(StructuredValidationError) as captured:
        ToolSemanticsRepairProjection().merge(
            baseline,
            correction,
            roots=("tools/1/reliability",),
        )

    assert captured.value.diagnostic.issue_codes == ("tool_batch_identity_drift@tools",)


def test_repair_projection_cannot_exceed_durable_target_authority() -> None:
    target = RepairTargetRef(
        target_id="repair:hotel",
        component="design",
        artifact_slot="tool_semantics_batch",
        lineage_id="hotel.tool-semantics",
        allowed_mutation_paths=("/tools",),
    )

    EnvironmentDesigner._assert_repair_projection_authorized(
        ("tools/1/errors",),
        repair_target=target,
    )
    with pytest.raises(DesignerError, match="exceeds the target mutation authority"):
        EnvironmentDesigner._assert_repair_projection_authorized(
            ("boundary",),
            repair_target=target,
        )


def test_architecture_contract_keeps_mechanical_schema_graph_out_of_agent_output() -> None:
    schema = WorldArchitectureSourceDraft.model_json_schema()

    assert len(json.dumps(schema)) < 15_000
    assert "state_entities" in schema["properties"]
    assert "state_inventory" not in schema["properties"]
    assert "state_entity_fields" not in schema["properties"]
    assert "tool_interfaces" not in schema["properties"]
    assert "state_entity_schemas" not in schema["properties"]
    assert "tool_schemas" not in schema["properties"]
    assert "tool_id" not in schema["$defs"]["ToolSurfaceSourceDraft"]["properties"]
    assert "tool_id" not in schema["$defs"]["ToolInterfaceSourceDraft"]["properties"]
    assert "interface" in schema["$defs"]["ToolSurfaceSourceDraft"]["properties"]
    assert "core_resources" not in schema["$defs"]["WorldBoundarySourceDraft"]["properties"]
    assert "visibility" not in schema["$defs"]["ActorAuthoritySourceDraft"]["properties"]
    assert "owned_resource_ids" in schema["$defs"]["StateEntitySourceDraft"]["properties"]
    assert "visible_to_actor_ids" in schema["$defs"]["StateEntitySourceDraft"]["properties"]


def test_framework_derives_canonical_tool_id_from_namespace_and_name() -> None:
    architecture = WorldArchitectureSourceDraft.model_construct(
        tool_inventory=WorldToolSourceInventoryDraft(
            tools=(
                ToolSurfaceSourceDraft(
                    namespace="hotel_booking",
                    name="search_hotels",
                    description="Search inventory without mutating it.",
                    transport="runtime",
                    reads_state_entities=("hotel_inventory",),
                    evidence_claim_ids=("claim:hotel",),
                    interface=ToolInterfaceSourceDraft(
                        observation_fields=(
                            CompactFieldSemanticDraft(
                                name="hotels",
                                value_type="string",
                                description="Visible hotel results.",
                                repeated=True,
                            ),
                        )
                    ),
                ),
            )
        )
    )

    compiled = EnvironmentDesigner._compile_architecture_tool_inventory(architecture)

    assert compiled.tools[0].tool_id == "hotel_booking.search_hotels"


def test_architecture_entity_identity_repair_includes_tool_footprint_dependency() -> None:
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="world_architecture_topology",
        frontier_ordinal=15,
        issues=(
            SafeValidationIssue(
                "architecture_entity_duplicate",
                ("state_entities", 1, "entity"),
                "Each state entity identifier must be unique.",
            ),
        ),
    )

    assert EnvironmentDesigner._architecture_repair_roots(diagnostic) == (
        "state_entities",
        "tool_inventory",
    )


def test_compact_business_fields_compile_to_closed_schema_ir() -> None:
    fields = (
        CompactFieldSemanticDraft(
            name="booking_id",
            value_type="string",
            description="Stable booking identifier.",
        ),
        CompactFieldSemanticDraft(
            name="nightly_price",
            value_type="number",
            description="Nightly price in the configured currency.",
            nullable=True,
            minimum=0,
        ),
        CompactFieldSemanticDraft(
            name="guest_names",
            value_type="string",
            description="Guests attached to the booking.",
            repeated=True,
        ),
    )

    nodes = EnvironmentDesigner._compact_fields_to_schema_nodes(fields)
    compiled = EnvironmentDesigner._compile_schema_ir(root_node_id="root", nodes=nodes)

    assert compiled["additionalProperties"] is False
    assert compiled["required"] == ["booking_id", "nightly_price", "guest_names"]
    properties = cast(dict[str, Any], compiled["properties"])
    assert properties["booking_id"]["type"] == "string"
    assert properties["nightly_price"]["anyOf"][0]["minimum"] == 0
    assert properties["guest_names"]["type"] == "array"

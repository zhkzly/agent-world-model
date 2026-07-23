from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel, JsonValue
from v3_fixture import portable_counter_contracts

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    ArtifactRef,
    EvidenceGraph,
    IdempotencySemantics,
    StateEntitySchema,
    StateSchema,
    ToolSurface,
)
from agent_world.control.feedback import RepairTargetRef
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
)
from agent_world.designer.compact_rule_protocol import (
    COMPACT_RULE_PROTOCOL_VERSION,
    tool_semantics_batch_protocol,
    tool_semantics_batch_protocol_schema,
)
from agent_world.designer.final_design_compiler import compile_tool_semantics_batch
from agent_world.designer.final_design_leaves import (
    _shared_prompt,
    _tool_batch_prompt,
    _tool_batch_rule_contexts,
)
from agent_world.designer.models import (
    CompactFieldSemanticDraft,
    PermissionRuleSourceDraft,
    RuleDraft,
    SharedAtomicityDomainSourceDraft,
    SharedConcurrencyDomainSourceDraft,
    SharedErrorPolicySourceDraft,
    SharedIdempotencyDomainSourceDraft,
    SharedToolSemanticsContract,
    SharedToolSemanticsSourceDraft,
    ToolAccessObservationSourceDraft,
    ToolBehaviorDraft,
    ToolConditionsDraft,
    ToolConditionsSourceDraft,
    ToolErrorSourceDraft,
    ToolErrorsSourceDraft,
    ToolInterfaceSourceDraft,
    ToolSemanticsBatchSourceDraft,
    ToolSemanticSourceDraft,
    ToolStateTransitionSourceDraft,
    ToolSurfaceDraft,
    ToolSurfacePlan,
    ToolSurfaceSourceDraft,
    WorldArchitectureSourceDraft,
    WorldSkeletonDraft,
    WorldToolPlanInventoryDraft,
    WorldToolSourceInventoryDraft,
)
from agent_world.designer.rule_context import RuleContextCatalog
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


def test_tool_batch_derives_rule_identity_before_source_artifact_can_be_written() -> None:
    """Rule namespace is framework mechanics, not an Engineer repair burden."""

    def rule(family: str, supplied_id: str) -> RuleDraft:
        return RuleDraft.model_construct(
            rule_id=supplied_id,
            family=family,
            description="A typed business relation.",
            boolean_operator="all",
            clauses=(),
            case_sensitivity="positive_only",
            evidence_claim_ids=(),
        )

    tool_id = "hotel.reserve"
    source = ToolSemanticSourceDraft.model_construct(
        tool_id=tool_id,
        conditions=ToolConditionsSourceDraft.model_construct(
            tool_id=tool_id,
            preconditions=(rule("precondition", "agent-chosen-pre"),),
            postconditions=(rule("postcondition", "agent-chosen-post"),),
        ),
        state_transition=ToolStateTransitionSourceDraft.model_construct(
            tool_id=tool_id,
            transition=(rule("transition", "agent-chosen-transition"),),
        ),
        errors=ToolErrorsSourceDraft.model_construct(
            tool_id=tool_id,
            errors=(
                ToolErrorSourceDraft.model_construct(
                    when=rule("error_condition", "agent-chosen-error"),
                ),
            ),
        ),
        access_observation=ToolAccessObservationSourceDraft.model_construct(
            tool_id=tool_id,
            permission=PermissionRuleSourceDraft.model_construct(
                condition=rule("permission", "agent-chosen-permission"),
            ),
            observation=SimpleNamespace(),
        ),
        reliability=SimpleNamespace(),
    )

    batch = ToolSemanticsBatchSourceDraft(tools=(source,))
    canonical = batch.tools[0]

    assert canonical.conditions.preconditions[0].rule_id == "rule:hotel.reserve:precondition:0"
    assert canonical.conditions.postconditions[0].rule_id == "rule:hotel.reserve:postcondition:0"
    assert canonical.state_transition.transition[0].rule_id == "rule:hotel.reserve:transition:0"
    assert canonical.errors.errors[0].when.rule_id == "rule:hotel.reserve:error:0"
    assert (
        canonical.access_observation.permission.condition.rule_id
        == "rule:hotel.reserve:permission:0"
    )


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
        _plan(index, namespace="hotel", reads=("inventory", "reservations")) for index in range(5)
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
                source.atomicity_domains[0].model_copy(update={"member_tool_ids": (tool_ids[0],)}),
            )
        }
    )
    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_shared_tool_semantics_source(
            invalid,
            group=cast(Any, group),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
        )
    issue = next(
        item for item in captured.value.issues if item.code == "shared_contract_partition"
    )
    assert issue.violated_condition == "shared domains omit or duplicate a frozen group tool"
    assert issue.expected_category is not None
    assert all(tool_id in issue.expected_category for tool_id in tool_ids)


def test_shared_tool_prompt_requires_a_complete_frozen_tool_partition() -> None:
    """BC-33: the Agent receives a generic construction rule, not a hotel fixture."""

    tool_ids = ("hotel.search", "hotel.reserve")
    prompt = _shared_prompt(
        cast(Any, SimpleNamespace(request=SimpleNamespace(need="用户预订宾馆"))),
        cast(Any, SimpleNamespace(model_dump=lambda **_kwargs: {"tools": []})),
        {
            "group_id": "group:hotel",
            "ordered_tool_ids": tool_ids,
            "mode": "multi_batch",
        },
        EvidenceGraph(graph_id="evidence:hotel", revision=1),
    )

    assert "exact non-overlapping partition" in prompt
    assert "one domain containing the complete frozen list" in prompt
    assert "collectively cover every frozen tool ID" in prompt
    assert all(tool_id in prompt for tool_id in tool_ids)


def test_tool_batch_prompt_discloses_only_the_target_tool_state_footprint() -> None:
    """BC-42: a batch cannot repeat unrelated world state for every tool."""

    booking_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"booking_id": {"type": "string"}, "status": {"type": "string"}},
        "required": ["booking_id", "status"],
        "additionalProperties": False,
    }
    private_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"secret_id": {"type": "string"}},
        "required": ["secret_id"],
        "additionalProperties": False,
    }
    state = StateSchema(
        entities=(
            StateEntitySchema(
                entity="booking",
                json_schema=booking_schema,
                primary_key_fields=("booking_id",),
            ),
            StateEntitySchema(
                entity="private_record",
                json_schema=private_schema,
                primary_key_fields=("secret_id",),
            ),
        ),
        root_state_schema={
            "$defs": {"booking": booking_schema, "private_record": private_schema},
            "type": "object",
            "properties": {
                "bookings": {"type": "array", "items": {"$ref": "#/$defs/booking"}},
                "private_records": {
                    "type": "array",
                    "items": {"$ref": "#/$defs/private_record"},
                },
            },
            "required": ["bookings", "private_records"],
            "additionalProperties": False,
        },
    )
    target_surface = ToolSurface(
        tool_id="hotel.booking.get",
        namespace="hotel.booking",
        name="get",
        description="Get one hotel booking.",
        transport="runtime",
        input_schema={
            "type": "object",
            "properties": {"booking_id": {"type": "string"}},
            "required": ["booking_id"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        observation_schema={
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
    )
    unrelated_surface = target_surface.model_copy(
        update={
            "tool_id": "hotel.private.list",
            "namespace": "hotel.private",
            "name": "list",
            "description": "List private records.",
        }
    )
    architecture = SimpleNamespace(
        boundary=SimpleNamespace(
            primary_domain="hotel",
            actors_and_authority=(
                SimpleNamespace(model_dump=lambda **_kwargs: {"actor": "guest"}),
            ),
            systems_of_record=("hotel_system",),
            transition_authorities=("hotel",),
            core_invariants=("Bookings remain attributable.",),
        ),
        state_entities=(
            SimpleNamespace(entity="booking", root_field="bookings"),
            SimpleNamespace(entity="private_record", root_field="private_records"),
        ),
        tool_inventory=SimpleNamespace(
            tools=(
                SimpleNamespace(
                    tool_id="hotel.booking.get",
                    reads_state_entities=("booking",),
                    writes_state_entities=(),
                ),
                SimpleNamespace(
                    tool_id="hotel.private.list",
                    reads_state_entities=("private_record",),
                    writes_state_entities=(),
                ),
            )
        ),
    )
    skeleton = SimpleNamespace(
        state=state,
        tool_surfaces=(
            SimpleNamespace(surface=target_surface),
            SimpleNamespace(surface=unrelated_surface),
        ),
    )
    tool_ids = ("hotel.booking.get",)
    contexts = _tool_batch_rule_contexts(cast(Any, architecture), cast(Any, skeleton), tool_ids)
    prompt = _tool_batch_prompt(
        cast(Any, SimpleNamespace(request=SimpleNamespace(need="retrieve a booking"))),
        cast(Any, architecture),
        cast(Any, skeleton),
        tool_ids,
        (),
        EvidenceGraph(graph_id="evidence:hotel", revision=1),
        contexts,
    )
    frozen = json.loads(prompt.split("Frozen context:\n", maxsplit=1)[1])

    assert "architecture" not in frozen
    assert "world_skeleton" not in frozen
    assert [item["tool_id"] for item in frozen["target_tools"]] == ["hotel.booking.get"]
    assert "private_records" not in prompt
    catalog = frozen["rule_context_catalogs"]["hotel.booking.get"]
    assert catalog["collections"] == [
        {
            "collection_pointer": "/bookings",
            "primary_key_fields": ["booking_id"],
            "item_fields": ["booking_id", "status"],
        }
    ]
    assert all(
        item["source"] not in {"pre_state", "post_state"}
        or item["pointer"].startswith("/bookings")
        for item in catalog["reference_bindings"]
    )


def test_restricted_rule_catalog_keeps_tool_io_but_removes_unowned_state_bindings() -> None:
    state = StateSchema(
        entities=(
            StateEntitySchema(
                entity="booking",
                json_schema={
                    "type": "object",
                    "properties": {"booking_id": {"type": "string"}},
                    "required": ["booking_id"],
                    "additionalProperties": False,
                },
                primary_key_fields=("booking_id",),
            ),
            StateEntitySchema(
                entity="private_record",
                json_schema={
                    "type": "object",
                    "properties": {"secret_id": {"type": "string"}},
                    "required": ["secret_id"],
                    "additionalProperties": False,
                },
                primary_key_fields=("secret_id",),
            ),
        ),
        root_state_schema={
            "type": "object",
            "properties": {
                "bookings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"booking_id": {"type": "string"}},
                    },
                },
                "private_records": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"secret_id": {"type": "string"}},
                    },
                },
            },
            "required": ["bookings", "private_records"],
            "additionalProperties": False,
        },
    )
    surface = ToolSurface(
        tool_id="hotel.booking.get",
        namespace="hotel.booking",
        name="get",
        description="Get one booking.",
        transport="runtime",
        input_schema={"type": "object", "properties": {"booking_id": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        observation_schema={"type": "object", "properties": {"status": {"type": "string"}}},
    )

    catalog = RuleContextCatalog.for_tool(state=state, surface=surface).restricted_to_state_roots(
        frozenset({"bookings"})
    )
    projection = catalog.prompt_projection()

    collections = cast(list[dict[str, object]], projection["collections"])
    reference_bindings = cast(list[dict[str, str]], projection["reference_bindings"])
    assert collections == [
        {
            "collection_pointer": "/bookings",
            "primary_key_fields": [],
            "item_fields": ["booking_id"],
        }
    ]
    assert any(item["source"] == "args" for item in reference_bindings)
    assert all(
        item["source"] not in {"pre_state", "post_state"}
        or item["pointer"].startswith("/bookings")
        for item in reference_bindings
    )


def test_compact_tool_rule_protocol_parses_and_compiles_only_frozen_bindings(
    tmp_path: Path,
) -> None:
    """BC-42: a compact provider prompt still reaches the original compiler."""

    world = portable_counter_contracts(ArtifactStore(tmp_path / "artifacts")).design.world_spec
    tool = world.tools[0]
    skeleton = WorldSkeletonDraft(
        boundary=world.boundary,
        state=world.state,
        tool_surfaces=(
            ToolSurfaceDraft(surface=tool.surface, evidence_claim_ids=("claim:counter",)),
        ),
        task_dimensions=world.task_dimensions,
        fidelity=world.fidelity,
    )
    catalog = RuleContextCatalog.for_tool(
        state=skeleton.state,
        surface=tool.surface,
    ).restricted_to_state_roots(frozenset({"counter"}))

    def binding(source: str, pointer: str) -> str:
        return next(
            item.binding_id
            for item in catalog.reference_bindings.values()
            if item.source == source and item.pointer == pointer
        )

    def reference(source: str, pointer: str) -> dict[str, str]:
        return {"kind": "bound_reference", "binding_id": binding(source, pointer)}

    def rule(
        *,
        family: str,
        clause_id: str,
        left: dict[str, object],
        operator: str,
        right: dict[str, object],
        ordering: str | None = None,
        case_sensitivity: str = "positive_only",
    ) -> dict[str, object]:
        clause: dict[str, object] = {
            "clause_id": clause_id,
            "operator": operator,
            "left": left,
            "right": right,
            "negate": False,
        }
        if ordering is not None:
            clause["ordering"] = ordering
        return {
            "family": family,
            "description": f"A {family} rule for the frozen counter tool.",
            "boolean_operator": "all",
            "clauses": [clause],
            "case_sensitivity": case_sensitivity,
            "evidence_claim_ids": [],
        }

    amount = reference("args", "/amount")
    pre_value = reference("pre_state", "/counter/value")
    post_value = reference("post_state", "/counter/value")
    result_value = reference("tool_result", "/value")
    zero: dict[str, object] = {"kind": "constant", "value_type": "number", "value": 0}
    source_document: dict[str, object] = {
        "tools": [
            {
                "tool_id": tool.surface.tool_id,
                "conditions": {
                    "tool_id": tool.surface.tool_id,
                    "preconditions": [
                        rule(
                            family="precondition",
                            clause_id="positive_amount",
                            left=amount,
                            operator="greater_than",
                            right=zero,
                            ordering="number",
                            case_sensitivity="positive_and_negative",
                        )
                    ],
                    "postconditions": [
                        rule(
                            family="postcondition",
                            clause_id="result_matches_state",
                            left=result_value,
                            operator="equal",
                            right=post_value,
                        )
                    ],
                },
                "state_transition": {
                    "tool_id": tool.surface.tool_id,
                    "transition": [
                        rule(
                            family="transition",
                            clause_id="incremented_state",
                            left=post_value,
                            operator="equal",
                            right={
                                "kind": "arithmetic",
                                "operator": "add",
                                "left": pre_value,
                                "right": amount,
                            },
                        )
                    ],
                },
                "errors": {
                    "tool_id": tool.surface.tool_id,
                    "errors": [
                        {
                            "error_code": "invalid_amount",
                            "when": rule(
                                family="error_condition",
                                clause_id="non_positive_amount",
                                left=amount,
                                operator="less_or_equal",
                                right=zero,
                                ordering="number",
                                case_sensitivity="positive_and_negative",
                            ),
                            "observation": "amount must be positive",
                            "state_effect": "none",
                            "retryable": False,
                            "evidence_claim_ids": [],
                        }
                    ],
                },
                "access_observation": {
                    "tool_id": tool.surface.tool_id,
                    "permission": {
                        "permission_id": "permission:counter",
                        "allowed_actors": ["user"],
                        "required_scopes_by_actor": {"user": ["counter.write"]},
                        "condition": None,
                        "denied_observation": "Permission denied.",
                    },
                    "observation": {
                        "visible_fields_by_actor": {"user": ["counter"], "auditor": []},
                        "consistency": "strong",
                        "staleness_bound_seconds": None,
                    },
                },
                "reliability": {
                    "tool_id": tool.surface.tool_id,
                    "idempotency": {
                        "mode": "idempotency_key",
                        "key_field": "idempotency_key",
                        "retention_seconds": 3600,
                        "duplicate_observation": "Return the original result.",
                    },
                    "retry": {
                        "maximum_attempts": 1,
                        "backoff": "none",
                        "retryable_error_codes": [],
                        "requires_same_idempotency_key": True,
                    },
                    "timeout": {
                        "operation_timeout_seconds": 5,
                        "timeout_error_code": "invalid_amount",
                        "cancellation_effect": "no_effect",
                    },
                    "transaction": {
                        "atomicity": "atomic",
                        "commit_point": "After input validation.",
                        "partial_commit_observable": False,
                    },
                    "rollback": {
                        "supported": True,
                        "rollback_trigger_codes": ["invalid_amount"],
                        "compensation_tools": [],
                        "guarantees": "Invalid updates preserve state.",
                    },
                    "concurrency": {
                        "isolation": "serializable",
                        "conflict_detection": "The runtime serializes updates.",
                        "conflict_error_code": None,
                        "ordering_guarantee": "Committed updates are ordered.",
                    },
                },
            }
        ]
    }

    protocol = tool_semantics_batch_protocol()
    assert COMPACT_RULE_PROTOCOL_VERSION in protocol
    assert "bound_lookup_by_key" in protocol
    assert "Never emit reference, lookup_by_key" in protocol
    protocol_validator = Draft202012Validator(tool_semantics_batch_protocol_schema())
    assert not tuple(protocol_validator.iter_errors(source_document))

    source = ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(source_document))
    compiled = compile_tool_semantics_batch(
        source,
        expected_tool_ids=(tool.surface.tool_id,),
        skeleton=skeleton,
        evidence_graph=EvidenceGraph(graph_id="evidence:counter", revision=1),
        contracts=(),
        rule_contexts_by_tool={tool.surface.tool_id: catalog},
    )
    assert compiled[0].tool_id == tool.surface.tool_id

    raw_reference = json.loads(json.dumps(source_document))
    transition = raw_reference["tools"][0]["state_transition"]["transition"][0]
    transition["clauses"][0]["left"] = {
        "kind": "reference",
        "source": "post_state",
        "pointer": "/counter/value",
        "value_type": "number",
    }
    assert tuple(protocol_validator.iter_errors(raw_reference))
    with pytest.raises(StructuredValidationError) as captured:
        compile_tool_semantics_batch(
            ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(raw_reference)),
            expected_tool_ids=(tool.surface.tool_id,),
            skeleton=skeleton,
            evidence_graph=EvidenceGraph(graph_id="evidence:counter", revision=1),
            contracts=(),
            rule_contexts_by_tool={tool.surface.tool_id: catalog},
        )
    assert any(
        issue_code.startswith("tool_rule_binding_required@")
        for issue_code in captured.value.diagnostic.issue_codes
    )


def test_shared_idempotency_uses_the_exact_downstream_tool_vocabulary() -> None:
    valid = SharedIdempotencyDomainSourceDraft.model_validate_json(
        json.dumps(
            {
                "domain_id": "idempotency:hotel",
                "member_tool_ids": ["hotel.search"],
                "mode": "not_supported",
                "rationale": "The tool does not expose duplicate suppression.",
            }
        )
    )

    shared_mode_schema = SharedIdempotencyDomainSourceDraft.model_json_schema()["properties"][
        "mode"
    ]
    runtime_mode_schema = IdempotencySemantics.model_json_schema()["properties"]["mode"]
    assert shared_mode_schema == runtime_mode_schema
    assert valid.mode == "not_supported"
    with pytest.raises(ValueError, match="not_supported"):
        SharedIdempotencyDomainSourceDraft.model_validate_json(
            json.dumps(
                {
                    **valid.model_dump(mode="json"),
                    "mode": "none",
                }
            )
        )


def test_shared_policy_failures_are_visible_before_rule_compilation() -> None:
    tool_ids = ("hotel.search", "hotel.reserve")
    shared_source = SharedToolSemanticsSourceDraft(
        atomicity_domains=(
            SharedAtomicityDomainSourceDraft(
                domain_id="atomicity:hotel",
                member_tool_ids=tool_ids,
                atomicity="atomic",
                rationale="The tools share one reservation workflow.",
            ),
        ),
        concurrency_domains=(
            SharedConcurrencyDomainSourceDraft(
                domain_id="concurrency:hotel",
                member_tool_ids=tool_ids,
                isolation="serializable",
                rationale="Inventory writes must serialize.",
            ),
        ),
        idempotency_domains=(
            SharedIdempotencyDomainSourceDraft(
                domain_id="idempotency:hotel",
                member_tool_ids=tool_ids,
                mode="natural",
                rationale="Duplicate calls observe the same result.",
            ),
        ),
        error_policies=(
            SharedErrorPolicySourceDraft(
                policy_id="error-policy:timeout",
                member_tool_ids=tool_ids,
                required_error_suffix="timeout",
                retryable=True,
                rationale="Transient provider timeouts are retryable.",
            ),
        ),
    )
    contract = SharedToolSemanticsContract(
        contract_id="shared-contract:hotel",
        group_id="group:hotel",
        member_tool_ids=tool_ids,
        source=shared_source,
    )

    def tool(tool_id: str, *, include_timeout: bool) -> SimpleNamespace:
        errors = (
            # The real bad case used dot-separated tool identifiers.
            (SimpleNamespace(error_code=f"{tool_id}.timeout", retryable=True),)
            if include_timeout
            else (SimpleNamespace(error_code=f"{tool_id}:invalid", retryable=False),)
        )
        return SimpleNamespace(
            tool_id=tool_id,
            # Deliberately unusable: the shared boundary must not need Rule compilation.
            state_transition=SimpleNamespace(transition=None),
            errors=SimpleNamespace(errors=errors),
            reliability=SimpleNamespace(
                transaction=SimpleNamespace(atomicity="atomic"),
                concurrency=SimpleNamespace(isolation="serializable"),
                idempotency=SimpleNamespace(mode="natural"),
                rollback=SimpleNamespace(compensation_tools=()),
            ),
        )

    invalid = ToolSemanticsBatchSourceDraft.model_construct(
        tools=(tool(tool_ids[0], include_timeout=False), tool(tool_ids[1], include_timeout=True))
    )
    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_tool_source_batch_against_shared_contracts(
            invalid,
            contracts=(contract,),
        )

    assert tuple((issue.code, issue.location) for issue in captured.value.issues) == (
        ("shared_error_policy_mismatch", ("tools", 0, "errors")),
    )


@pytest.mark.parametrize("separator", [".", ":", "_", "-"])
def test_identifier_suffix_matching_accepts_contract_identifier_separators(
    separator: str,
) -> None:
    assert EnvironmentDesigner._identifier_has_suffix(
        f"hotel.search{separator}timeout",
        "timeout",
    )
    assert not EnvironmentDesigner._identifier_has_suffix("hotel.search.notimeout", "timeout")


def test_tool_batch_preflight_aggregates_independent_shared_and_rule_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_shared(
        _source: object,
        *,
        contracts: object,
    ) -> None:
        del contracts
        raise StructuredSemanticError(
            (
                StructuredSemanticIssue(
                    code="shared_error_policy_mismatch",
                    location=("tools", 0, "errors"),
                    message="The frozen timeout policy is missing.",
                ),
            )
        )

    def fail_rules(
        _self: object,
        _source: object,
        *,
        expected_tool_ids: object,
        skeleton: object,
        evidence_graph: object,
    ) -> None:
        del expected_tool_ids, skeleton, evidence_graph
        raise StructuredValidationError(
            ValidationDiagnostic(
                owner_component="design",
                validation_phase="tool_semantics_batch_preflight",
                frontier_ordinal=30,
                issues=(
                    SafeValidationIssue(
                        "rule_ordering_type_mismatch",
                        ("tools", 1, "state_transition", "transition", 0, "clauses", 1),
                        "The ordering and term types disagree.",
                    ),
                ),
            )
        )

    monkeypatch.setattr(
        EnvironmentDesigner,
        "_validate_tool_source_batch_against_shared_contracts",
        staticmethod(fail_shared),
    )
    monkeypatch.setattr(EnvironmentDesigner, "_compile_tool_semantics_batch", fail_rules)
    designer = object.__new__(EnvironmentDesigner)

    with pytest.raises(StructuredValidationError) as captured:
        designer._compile_and_validate_tool_semantics_batch(
            ToolSemanticsBatchSourceDraft.model_construct(tools=()),
            expected_tool_ids=(),
            skeleton=WorldSkeletonDraft.model_construct(),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
            contracts=(),
        )

    assert captured.value.diagnostic.validation_phase == "tool_semantics_batch_preflight"
    assert captured.value.diagnostic.frontier_ordinal == 30
    assert captured.value.diagnostic.issue_codes == (
        "shared_error_policy_mismatch@tools.0.errors",
        "rule_ordering_type_mismatch@tools.1.state_transition.transition.0.clauses.1",
    )


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
        designer._compile_and_validate_tool_semantics_batch(
            batch,
            expected_tool_ids=(expected_id,),
            skeleton=cast(Any, object()),
            evidence_graph=EvidenceGraph(graph_id="evidence:hotel", revision=1),
            contracts=(),
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
        state=object(),
        tool_surfaces=tuple(
            SimpleNamespace(
                surface=SimpleNamespace(
                    tool_id=tool_id,
                    observation_schema={"type": "object", "properties": {"result": {}}},
                )
            )
            for tool_id in tool_ids
        ),
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
        "_compile_tool_conditions_source",
        lambda source, **_kwargs: ToolConditionsDraft.model_construct(
            tool_id=source.tool_id,
            preconditions=(object(),),
            postconditions=(),
        ),
    )
    monkeypatch.setattr(
        designer,
        "_compose_tool_behavior",
        lambda conditions, transition, errors: ToolBehaviorDraft.model_construct(
            tool_id=conditions.tool_id,
            preconditions=(object(),),
            transition=(),
            postconditions=(),
            errors=(),
        ),
    )
    monkeypatch.setattr(
        "agent_world.designer.service.RuleContextCatalog.for_tool",
        classmethod(lambda _cls, **_kwargs: object()),
    )
    monkeypatch.setattr(
        "agent_world.designer.service.validate_rule_context",
        lambda *_args, **_kwargs: (
            SafeValidationIssue(
                code="rule_pointer_unreachable",
                location=("clauses", 0, "left", "pointer"),
                message="the referenced schema path does not exist",
            ),
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
    assert {issue.code for issue in captured.value.diagnostic.issues} == {
        "condition_contract",
        "rule_pointer_unreachable",
    }


def test_reliability_reports_the_complete_closed_error_reference_graph() -> None:
    reliability = SimpleNamespace(
        tool_id="hotel.reserve",
        retry=SimpleNamespace(retryable_error_codes=("error:timeout", "error:not-retryable")),
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

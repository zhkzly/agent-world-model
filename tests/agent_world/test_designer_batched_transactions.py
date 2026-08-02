from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel, JsonValue, ValidationError
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
    pydantic_validation_diagnostic,
)
from agent_world.designer.compact_rule_protocol import (
    COMPACT_RULE_PROTOCOL_VERSION,
    tool_semantics_batch_protocol,
    tool_semantics_batch_protocol_schema,
    tool_semantics_representation_audit,
)
from agent_world.designer.final_design_compiler import compile_tool_semantics_batch
from agent_world.designer.final_design_leaves import (
    _shared_prompt,
    _tool_batch_prompt,
    _tool_batch_rule_contexts,
)
from agent_world.designer.models import (
    CompactFieldSemanticDraft,
    RuleDraft,
    SharedAtomicityDomainSourceDraft,
    SharedCompensationEdgeSourceDraft,
    SharedConcurrencyDomainSourceDraft,
    SharedErrorPolicySourceDraft,
    SharedIdempotencyDomainSourceDraft,
    SharedToolSemanticsContract,
    SharedToolSemanticsSourceDraft,
    ToolBehaviorDraft,
    ToolConditionsDraft,
    ToolInterfaceSourceDraft,
    ToolRuleDraft,
    ToolSemanticsBatchSourceDraft,
    ToolSemanticSourceDraft,
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


def test_tool_batch_derives_rule_identity_and_family_before_source_artifact_can_be_written() -> (
    None
):
    """Rule namespace and section family are absent from the Agent wire."""

    schema = ToolRuleDraft.model_json_schema()
    assert "rule_id" not in schema["properties"]
    assert "family" not in schema.get("required", ())


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


def test_tool_semantics_eight_tools_compile_to_eight_stable_singleton_shards() -> None:
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

    assert len(batches) == 8
    assert all(len(batch) == 1 for batch in batches)
    assert ToolSemanticsBatchSourceDraft.model_json_schema()["properties"]["tools"]["maxItems"] == 1
    assert tool_semantics_batch_protocol_schema()["properties"]["tools"]["maxItems"] == 1
    assert tuple(tool_id for batch in batches for tool_id in batch) == tuple(
        item.tool_id for item in plans
    )


def test_five_coupled_tools_keep_one_shared_group_and_singleton_execution_shards() -> None:
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
    expected_batches = tuple((f"hotel.tool-{index}",) for index in range(5))
    assert plan.groups[0].batches == expected_batches
    assert plan.execution_batches == expected_batches


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
    issue = next(item for item in captured.value.issues if item.code == "shared_contract_partition")
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
                SimpleNamespace(
                    actor="guest",
                    authorities=("read_booking",),
                    model_dump=lambda **_kwargs: {
                        "actor": "guest",
                        "authorities": ["read_booking"],
                    },
                ),
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

    instruction, _separator, _context = prompt.partition("Frozen context:\n")
    assert "compact ToolSemantics output protocol appended after this Prompt" in instruction
    assert "target_tools for each exact surface and state footprint" in instruction
    assert (
        "rule_context_catalogs and permission_rule_context_catalogs for permitted Rule"
        in instruction
    )
    assert "actor_authorities_by_actor as the exact permission-scope lookup" in instruction
    assert "infer a missing state root or binding" in instruction
    assert "never extrapolate, renumber, or cross term kinds" not in instruction
    assert "reliability.tool_id" not in instruction
    assert "architecture" not in frozen
    assert "world_skeleton" not in frozen
    assert [item["tool_id"] for item in frozen["target_tools"]] == ["hotel.booking.get"]
    assert frozen["target_tools"][0]["actor_authorities_by_actor"] == {
        "guest": ["read_booking"]
    }
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
        item["source"] not in {"pre_state", "post_state"} or item["pointer"].startswith("/bookings")
        for item in catalog["reference_bindings"]
    )
    assert set(catalog["term_binding_aliases"]) == {
        "bound_reference",
        "bound_lookup_by_constant",
        "bound_lookup_by_reference",
    }
    assert set(catalog["ordered_term_binding_aliases"]) == {"number", "string"}
    permission_catalog = frozen["permission_rule_context_catalogs"]["hotel.booking.get"]
    assert all(
        item["source"] in {"args", "pre_state"}
        for item in permission_catalog["reference_bindings"]
    )
    assert all(
        group["source"] in {"args", "pre_state"}
        for group in permission_catalog["lookup_binding_groups"]
    )
    assert all(
        group["source"] in {"args", "pre_state"}
        and all(
            item["key_source"] in {"args", "pre_state"}
            for item in group["reference_key_bindings"]
        )
        for group in permission_catalog["lookup_reference_binding_groups"]
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
        item["source"] not in {"pre_state", "post_state"} or item["pointer"].startswith("/bookings")
        for item in reference_bindings
    )


def test_targeted_tool_semantics_protocol_repeats_the_exact_singleton_at_the_final_gate() -> None:
    """The late protocol tells a stateless model which one frozen tool it owns."""

    generic = tool_semantics_batch_protocol()
    targeted = tool_semantics_batch_protocol(target_tool_ids=("todo.localstorage.add_task",))

    assert "Invocation-specific final completion gate" not in generic
    assert "Invocation-specific final completion gate" in targeted
    assert '["todo.localstorage.add_task"]' in targeted
    assert "Return exactly one tool in this order" in targeted
    assert "conditions, state_transition,\nerrors, access_observation, and reliability" in targeted
    assert tool_semantics_representation_audit() in targeted
    assert "reliability.tool_id is required" in targeted
    assert "rollback.guarantees is one non-empty\nJSON string" in targeted
    assert "maximum_attempts is an integer greater\nthan or equal to 1" in targeted
    assert "maximum_attempts=1 and an empty retryable_error_codes list" in " ".join(
        targeted.split()
    )

    with pytest.raises(ValueError, match="one exact unique target tool"):
        tool_semantics_batch_protocol(target_tool_ids=())
    with pytest.raises(ValueError, match="one exact unique target tool"):
        tool_semantics_batch_protocol(target_tool_ids=("tool:a", "tool:a"))
    with pytest.raises(ValueError, match="one exact unique target tool"):
        tool_semantics_batch_protocol(target_tool_ids=("tool:a", "tool:b"))


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
    assert "bound_lookup_by_reference" in protocol
    assert "bound_lookup_by_constant" in protocol
    assert "not emit allowed_actors; framework code derives" in protocol
    assert "they MUST omit `ordering`" in protocol
    assert "never emit a nested `key` object" in protocol
    assert "group's key_value_type byte-for-byte" in protocol
    assert "not the key type; never substitute it" in protocol
    assert "Omit rule_id and family" in protocol
    assert "state_transition.transition => transition" in protocol
    assert "Never emit key_binding_id" in protocol
    assert "Never emit reference, lookup_by_key" in protocol
    assert "term_binding_aliases as the final" in protocol
    assert "do not infer a missing alias" in protocol
    assert "ordered_term_binding_aliases by returned value type" in protocol
    assert "generic strings or temporal ordering to identifiers/statuses" in protocol
    assert "permission_rule_context_catalogs" in protocol
    assert "set condition to null rather than inventing a Rule" in protocol
    assert "keys exactly equal to every\nfrozen boundary actor" in protocol
    assert "frozen observation_schema only" in protocol
    assert "each scope must\nbe copied exactly from that actor's authorities" in protocol
    assert "must be an error_code declared in this\nsame TOOL's errors.errors list" in protocol
    assert "Pre-serialization representation audit" in protocol
    assert "rollback.guarantees" in protocol
    assert "concurrency.conflict_error_code is either null or one identifier string" in protocol
    protocol_schema = tool_semantics_batch_protocol_schema()
    permission_schema = cast(dict[str, Any], protocol_schema["$defs"])["permission"]
    assert "allowed_actors" not in permission_schema["required"]
    assert "allowed_actors" not in permission_schema["properties"]
    assert permission_schema["properties"]["required_scopes_by_actor"]["minProperties"] == 1
    protocol_validator = Draft202012Validator(protocol_schema)
    assert not tuple(protocol_validator.iter_errors(source_document))

    source = ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(source_document))
    assert source.tools[0].conditions.preconditions[0].family == "precondition"
    assert source.tools[0].state_transition.transition[0].family == "transition"
    assert source.tools[0].errors.errors[0].when.family == "error_condition"
    redundant_family_document = json.loads(json.dumps(source_document))
    redundant_family_document["tools"][0]["state_transition"]["transition"][0]["family"] = (
        "postcondition"
    )
    redundant_family = ToolSemanticsBatchSourceDraft.model_validate_json(
        json.dumps(redundant_family_document)
    )
    assert redundant_family.tools[0].state_transition.transition[0].family == "transition"
    compiled = compile_tool_semantics_batch(
        source,
        expected_tool_ids=(tool.surface.tool_id,),
        skeleton=skeleton,
        evidence_graph=EvidenceGraph(graph_id="evidence:counter", revision=1),
        contracts=(),
        rule_contexts_by_tool={tool.surface.tool_id: catalog},
    )
    assert compiled[0].tool_id == tool.surface.tool_id
    assert compiled[0].semantics.preconditions[0].rule_id.endswith(":precondition:0")
    assert compiled[0].semantics.transition[0].rule_id.endswith(":transition:0")
    assert compiled[0].semantics.permission.allowed_actors == ("user",)

    invalid_equal_ordering = json.loads(json.dumps(source_document))
    invalid_equal_ordering["tools"][0]["conditions"]["postconditions"][0]["clauses"][0][
        "ordering"
    ] = "number"
    assert tuple(protocol_validator.iter_errors(invalid_equal_ordering))
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(invalid_equal_ordering))

    invalid_nested_lookup = json.loads(json.dumps(source_document))
    invalid_nested_lookup["tools"][0]["state_transition"]["transition"][0]["clauses"][0][
        "right"
    ] = {
        "kind": "bound_lookup_by_key",
        "binding_id": "lookup:counter",
        "key": {
            "kind": "arithmetic",
            "operator": "add",
            "left": zero,
            "right": zero,
        },
    }
    assert tuple(protocol_validator.iter_errors(invalid_nested_lookup))
    with pytest.raises(ValidationError) as invalid_lookup:
        ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(invalid_nested_lookup))
    lookup_diagnostic = pydantic_validation_diagnostic(
        invalid_lookup.value,
        owner_component="design",
        validation_phase="tool_semantics_wire",
        frontier_ordinal=10,
    )
    assert lookup_diagnostic.issue_codes[0].startswith("schema_union_tag_invalid@")
    assert any(code.startswith("schema_too_short@") for code in lookup_diagnostic.issue_codes)

    invalid_split_lookup = json.loads(json.dumps(source_document))
    invalid_split_lookup["tools"][0]["state_transition"]["transition"][0]["clauses"][0]["right"] = {
        "kind": "bound_lookup_by_reference",
        "binding_id": "lookup-ref-1",
        "key_binding_id": "ref-1",
    }
    assert tuple(protocol_validator.iter_errors(invalid_split_lookup))
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(invalid_split_lookup))

    invalid_zero_divisor = json.loads(json.dumps(source_document))
    invalid_transition = invalid_zero_divisor["tools"][0]["state_transition"]["transition"][0]
    invalid_transition["clauses"][0]["right"] = {
        "kind": "arithmetic",
        "operator": "divide",
        "left": pre_value,
        "right": zero,
    }
    assert not tuple(protocol_validator.iter_errors(invalid_zero_divisor))
    with pytest.raises(StructuredValidationError) as captured:
        compile_tool_semantics_batch(
            ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(invalid_zero_divisor)),
            expected_tool_ids=(tool.surface.tool_id,),
            skeleton=skeleton,
            evidence_graph=EvidenceGraph(graph_id="evidence:counter", revision=1),
            contracts=(),
            rule_contexts_by_tool={tool.surface.tool_id: catalog},
        )
    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "rule_arithmetic_zero_divisor"
    assert issue.location == (
        "tools",
        0,
        "state_transition",
        "transition",
        0,
        "clauses",
        0,
        "right",
        "right",
    )
    assert issue.retryable is True
    assert issue.violated_condition == "semantic contract rule_arithmetic_zero_divisor"
    assert issue.expected_category == "a value satisfying the named semantic contract"
    assert issue.code != "framework_diagnostic_incomplete"

    raw_reference = json.loads(json.dumps(source_document))
    transition = raw_reference["tools"][0]["state_transition"]["transition"][0]
    transition["clauses"][0]["left"] = {
        "kind": "reference",
        "source": "post_state",
        "pointer": "/counter/value",
        "value_type": "number",
    }
    assert tuple(protocol_validator.iter_errors(raw_reference))
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        ToolSemanticsBatchSourceDraft.model_validate_json(json.dumps(raw_reference))

    raw_lookup = {
        "rule_id": "rule:generic:lookup",
        "family": "invariant",
        "description": "A generic world rule may use a raw closed-schema lookup.",
        "boolean_operator": "all",
        "clauses": [
            {
                "clause_id": "raw_lookup_is_still_supported",
                "operator": "equal",
                "left": {
                    "kind": "lookup_by_key",
                    "source": "post_state",
                    "collection_pointer": "/bookings",
                    "key_field": "booking_id",
                    "key": {
                        "kind": "reference",
                        "source": "args",
                        "pointer": "/booking_id",
                        "value_type": "string",
                    },
                    "value_pointer": "/status",
                    "value_type": "string",
                },
                "right": {"kind": "constant", "value_type": "string", "value": "confirmed"},
                "negate": False,
            }
        ],
        "case_sensitivity": "positive_only",
        "evidence_claim_ids": [],
    }
    generic_rule = RuleDraft.model_validate_json(json.dumps(raw_lookup))
    assert generic_rule.clauses[0].left.kind == "lookup_by_key"


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
        compensation_edges=(
            SharedCompensationEdgeSourceDraft(
                failure_tool_id="hotel.search",
                compensation_tool_id="hotel.reserve",
                rationale="A failed search rolls back its provisional reservation hold.",
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
                transaction=SimpleNamespace(
                    atomicity="atomic" if include_timeout else "best_effort"
                ),
                concurrency=SimpleNamespace(
                    isolation="serializable" if include_timeout else "read_committed"
                ),
                idempotency=SimpleNamespace(mode="natural" if include_timeout else "not_supported"),
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
        (
            "shared_atomicity_mismatch",
            ("tools", 0, "reliability", "transaction", "atomicity"),
        ),
        (
            "shared_isolation_mismatch",
            ("tools", 0, "reliability", "concurrency", "isolation"),
        ),
        (
            "shared_idempotency_mismatch",
            ("tools", 0, "reliability", "idempotency", "mode"),
        ),
        ("shared_error_policy_mismatch", ("tools", 0, "errors")),
        (
            "shared_compensation_mismatch",
            ("tools", 0, "reliability", "rollback"),
        ),
    )
    issues = {issue.code: issue for issue in captured.value.issues}
    assert issues["shared_atomicity_mismatch"].expected_category == (
        "transaction.atomicity=`atomic`"
    )
    assert issues["shared_isolation_mismatch"].expected_category == (
        "concurrency.isolation=`serializable`"
    )
    assert issues["shared_idempotency_mismatch"].expected_category == ("idempotency.mode=`natural`")
    assert "error-policy:timeout" in issues["shared_error_policy_mismatch"].message
    assert "`timeout`" in issues["shared_error_policy_mismatch"].expected_category
    assert issues["shared_compensation_mismatch"].expected_category == (
        "rollback.compensation_tools containing `hotel.reserve`"
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

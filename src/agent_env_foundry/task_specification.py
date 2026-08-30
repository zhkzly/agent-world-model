"""Candidate proposal normalization, semantic freeze, and bounded V0 compilation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, cast

import rfc8785

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.requirement_obligations import (
    FacetOperator,
    ObligationKind,
    RequirementObligation,
)
from agent_env_foundry.semantics import CapabilitySpec, GoalKind

SamplerKind = Literal["direct", "graph", "programmatic"]
SlotCardinality = Literal["one", "many"]
VerifierAxis = Literal[
    "applicability",
    "required_effects",
    "collateral",
    "answer",
    "process",
    "initial_non_vacuity",
]

_SAMPLER_KINDS = frozenset({"direct", "graph", "programmatic"})
_GOAL_SHAPES = frozenset({"atom", "all", "if", "foreach"})
_CARDINALITIES = frozenset({"one", "many"})
_FACET_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte", "min", "max"})
_HEX = frozenset("0123456789abcdef")


class TaskSpecificationError(ValueError):
    """A Candidate proposal cannot freeze into one anchored Task specification."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class SamplerDescriptor:
    kind: SamplerKind
    version: str

    def __post_init__(self) -> None:
        if self.kind not in _SAMPLER_KINDS:
            raise TaskSpecificationError("sampler_kind_invalid", "sampler kind is invalid")
        _identifier(self.version, "sampler version")

    def to_document(self) -> JSONObject:
        return {"kind": self.kind, "version": self.version}


@dataclass(frozen=True, slots=True)
class PublicEvidenceRef:
    kind: str
    digest: str

    def __post_init__(self) -> None:
        _identifier(self.kind, "public evidence kind")
        _digest_value(self.digest, "public evidence digest")

    def to_document(self) -> JSONObject:
        return {"kind": self.kind, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class PublicSlotProposal:
    slot_id: str
    capability_id: str
    cardinality: SlotCardinality
    facet_constraints: tuple[JSONObject, ...]

    def __post_init__(self) -> None:
        _identifier(self.slot_id, "public slot_id")
        _identifier(self.capability_id, "public slot capability_id")
        if self.cardinality not in _CARDINALITIES:
            raise TaskSpecificationError(
                "slot_cardinality_invalid",
                "public slot cardinality is invalid",
            )
        normalized = tuple(_facet_constraint(item) for item in self.facet_constraints)
        identities = tuple(_hash(item) for item in normalized)
        if len(identities) != len(set(identities)):
            raise TaskSpecificationError(
                "slot_facet_constraint_duplicated",
                "public slot facet constraints are duplicated",
            )

    def to_document(self) -> JSONObject:
        return {
            "slot_id": self.slot_id,
            "capability_id": self.capability_id,
            "cardinality": self.cardinality,
            "facet_constraints": [
                _facet_constraint(item)
                for item in sorted(self.facet_constraints, key=lambda value: _hash(value))
            ],
        }


@dataclass(frozen=True, slots=True)
class CandidateTaskProposal:
    sampler: SamplerDescriptor
    release_id: str
    requirement_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    objective: str
    goal_shape: GoalKind
    capability_ids: tuple[str, ...]
    composition_rule_id: str | None
    condition_id: str | None
    public_slots: tuple[PublicSlotProposal, ...]
    public_evidence_refs: tuple[PublicEvidenceRef, ...]

    def __post_init__(self) -> None:
        _digest_value(self.release_id, "proposal release_id")
        for values, role in (
            (self.requirement_ids, "proposal requirement_ids"),
            (self.obligation_ids, "proposal obligation_ids"),
            (self.capability_ids, "proposal capability_ids"),
        ):
            _identifiers(values, role)
        for value in self.obligation_ids:
            _digest_value(value, "proposal obligation_id")
        if not self.objective.strip():
            raise TaskSpecificationError(
                "proposal_objective_missing",
                "Candidate proposal objective must be non-empty",
            )
        if self.goal_shape not in _GOAL_SHAPES:
            raise TaskSpecificationError(
                "proposal_goal_shape_invalid",
                "Candidate proposal Goal shape is invalid",
            )
        if self.composition_rule_id is not None:
            _identifier(self.composition_rule_id, "proposal composition_rule_id")
        if self.condition_id is not None:
            _identifier(self.condition_id, "proposal condition_id")
        slot_ids = tuple(item.slot_id for item in self.public_slots)
        _identifiers(slot_ids, "proposal public slot IDs")
        if not self.public_evidence_refs:
            raise TaskSpecificationError(
                "proposal_public_evidence_missing",
                "Candidate proposal requires public evidence",
            )

    @property
    def proposal_id(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return _object(
            {
                "format": "candidate-task-proposal/1",
                "sampler": self.sampler.to_document(),
                "release_id": self.release_id,
                "requirement_ids": sorted(self.requirement_ids),
                "obligation_ids": sorted(self.obligation_ids),
                "objective": self.objective,
                "goal_shape": self.goal_shape,
                "capability_ids": sorted(self.capability_ids),
                "composition_rule_id": self.composition_rule_id,
                "condition_id": self.condition_id,
                "public_slots": [
                    item.to_document()
                    for item in sorted(self.public_slots, key=lambda value: value.slot_id)
                ],
                "public_evidence_refs": [
                    item.to_document()
                    for item in sorted(
                        self.public_evidence_refs,
                        key=lambda value: (value.kind, value.digest),
                    )
                ],
            },
            "CandidateTaskProposal",
        )


@dataclass(frozen=True, slots=True)
class TaskSemanticSection:
    release_id: str
    requirement_ids: tuple[str, ...]
    obligation_ids: tuple[str, ...]
    objective: str
    goal_shape: GoalKind
    capability_ids: tuple[str, ...]
    composition_rule_id: str | None
    condition_id: str | None
    public_slots: tuple[PublicSlotProposal, ...]
    answer_schema: JSONObject
    answer_operation_ids: tuple[str, ...]

    @property
    def semantic_digest(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return _object(
            {
                "format": "task-semantic-section/1",
                "release_id": self.release_id,
                "requirement_ids": list(self.requirement_ids),
                "obligation_ids": list(self.obligation_ids),
                "objective": self.objective,
                "goal_shape": self.goal_shape,
                "capability_ids": list(self.capability_ids),
                "composition_rule_id": self.composition_rule_id,
                "condition_id": self.condition_id,
                "public_slots": [item.to_document() for item in self.public_slots],
                "answer_schema": _object(self.answer_schema, "semantic answer_schema"),
                "answer_operation_ids": list(self.answer_operation_ids),
            },
            "TaskSemanticSection",
        )


@dataclass(frozen=True, slots=True)
class VerifierStep:
    axis: VerifierAxis
    obligation_ids: tuple[str, ...]
    qualified_operation_ids: tuple[str, ...]

    def to_document(self) -> JSONObject:
        return _object(
            {
                "axis": self.axis,
                "obligation_ids": list(self.obligation_ids),
                "qualified_operation_ids": list(self.qualified_operation_ids),
            },
            "VerifierStep",
        )


@dataclass(frozen=True, slots=True)
class VerifierBundle:
    semantic_digest: str
    steps: tuple[VerifierStep, ...]

    @property
    def verifier_id(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return {
            "format": "verifier-bundle/1",
            "semantic_digest": self.semantic_digest,
            "steps": [item.to_document() for item in self.steps],
        }


def compile_direct_proposals(
    *,
    release_id: str,
    capabilities: tuple[CapabilitySpec, ...],
    obligations: tuple[RequirementObligation, ...],
    task_goals: JSONObject,
) -> tuple[CandidateTaskProposal, ...]:
    """Compile the deterministic qualified-capability baseline into the common boundary."""

    _digest_value(release_id, "direct proposal release_id")
    capability_ids = {item.capability_id for item in capabilities}
    if set(task_goals) != capability_ids:
        raise TaskSpecificationError(
            "direct_goal_catalog_mismatch",
            "direct proposal goals differ from the qualified capability catalog",
        )
    proposals: list[CandidateTaskProposal] = []
    for capability in sorted(capabilities, key=lambda item: item.capability_id):
        objective = task_goals[capability.capability_id]
        if not isinstance(objective, str) or not objective.strip():
            raise TaskSpecificationError(
                "direct_goal_invalid",
                "direct proposal objective must be a non-empty string",
            )
        selected = (capability,)
        obligation_ids = tuple(
            sorted(
                item.obligation_id
                for item in obligations
                if item.requirement_id in capability.requirement_ids
                and _potentially_applies(item, selected, None)
            )
        )
        capability_digest = _hash(
            {
                "format": "qualified-capability-evidence/1",
                "release_id": release_id,
                "capability": capability.to_document(),
            }
        )
        proposals.append(
            CandidateTaskProposal(
                sampler=SamplerDescriptor("direct", "1"),
                release_id=release_id,
                requirement_ids=capability.requirement_ids,
                obligation_ids=obligation_ids,
                objective=objective,
                goal_shape="atom",
                capability_ids=(capability.capability_id,),
                composition_rule_id=None,
                condition_id=None,
                public_slots=(PublicSlotProposal("target", capability.capability_id, "one", ()),),
                public_evidence_refs=(
                    PublicEvidenceRef("qualified_capability", capability_digest),
                ),
            )
        )
    return tuple(proposals)


def compile_task_semantic_section(
    proposal: CandidateTaskProposal,
    *,
    capabilities: tuple[CapabilitySpec, ...],
    obligations: tuple[RequirementObligation, ...],
) -> TaskSemanticSection:
    capability_index = {item.capability_id: item for item in capabilities}
    selected = _selected_capabilities(proposal, capability_index)
    expected_requirements = tuple(
        sorted({item for capability in selected for item in capability.requirement_ids})
    )
    if tuple(sorted(proposal.requirement_ids)) != expected_requirements:
        raise TaskSpecificationError(
            "proposal_requirement_coverage_mismatch",
            "Candidate proposal does not cover the selected capabilities' Requirements",
            expected_requirement_ids=list(expected_requirements),
            actual_requirement_ids=sorted(proposal.requirement_ids),
        )
    _validate_composition(proposal, selected)
    _validate_slots(proposal, selected)

    applicable = tuple(
        item
        for item in obligations
        if item.requirement_id in expected_requirements
        and _potentially_applies(item, selected, proposal.condition_id)
    )
    expected_obligation_ids = {item.obligation_id for item in applicable}
    actual_obligation_ids = set(proposal.obligation_ids)
    missing = sorted(expected_obligation_ids - actual_obligation_ids)
    unexpected = sorted(actual_obligation_ids - expected_obligation_ids)
    if missing or unexpected:
        raise TaskSpecificationError(
            "applicable_obligation_coverage_mismatch",
            "Candidate proposal obligation coverage differs from sealed S1 authority",
            missing_obligation_ids=missing,
            unexpected_obligation_ids=unexpected,
        )

    answer_fields = tuple(field for capability in selected for field in capability.answer_fields)
    answer_ids = tuple(field.field_id for field in answer_fields)
    if len(answer_ids) != len(set(answer_ids)):
        raise TaskSpecificationError(
            "answer_field_collision",
            "selected capabilities contain colliding answer field IDs",
        )
    answer_schema = _object(
        {
            "type": "object",
            "properties": {
                field.field_id: _object(field.schema, "answer field schema")
                for field in answer_fields
            },
            "required": sorted(answer_ids),
            "additionalProperties": False,
        },
        "compiled answer schema",
    )
    answer_operations = tuple(
        sorted(
            f"{capability.capability_id}:answer:{field.field_id}"
            for capability in selected
            for field in capability.answer_fields
        )
    )
    return TaskSemanticSection(
        release_id=proposal.release_id,
        requirement_ids=expected_requirements,
        obligation_ids=tuple(sorted(expected_obligation_ids)),
        objective=proposal.objective,
        goal_shape=proposal.goal_shape,
        capability_ids=tuple(sorted(proposal.capability_ids)),
        composition_rule_id=proposal.composition_rule_id,
        condition_id=proposal.condition_id,
        public_slots=tuple(sorted(proposal.public_slots, key=lambda item: item.slot_id)),
        answer_schema=answer_schema,
        answer_operation_ids=answer_operations,
    )


def compile_verifier_bundle(
    semantic: TaskSemanticSection,
    *,
    capabilities: tuple[CapabilitySpec, ...],
    obligations: tuple[RequirementObligation, ...],
) -> VerifierBundle:
    capability_index = {item.capability_id: item for item in capabilities}
    if any(item not in capability_index for item in semantic.capability_ids):
        raise TaskSpecificationError(
            "verifier_capability_missing",
            "Verifier compilation is missing a selected capability",
        )
    obligation_index = {item.obligation_id: item for item in obligations}
    if any(item not in obligation_index for item in semantic.obligation_ids):
        raise TaskSpecificationError(
            "verifier_obligation_missing",
            "Verifier compilation is missing a frozen obligation",
        )
    selected = tuple(obligation_index[item] for item in semantic.obligation_ids)
    steps: list[VerifierStep] = [
        VerifierStep("applicability", semantic.obligation_ids, ()),
    ]
    axes: tuple[tuple[VerifierAxis, frozenset[ObligationKind]], ...] = (
        ("required_effects", frozenset({"effect"})),
        ("collateral", frozenset({"collateral"})),
        ("answer", frozenset({"answer"})),
        ("process", frozenset({"process", "refusal"})),
    )
    for axis, kinds in axes:
        ids = tuple(item.obligation_id for item in selected if item.kind in kinds)
        operations = semantic.answer_operation_ids if axis == "answer" else ()
        if ids or operations:
            steps.append(VerifierStep(axis, ids, operations))
    non_vacuity_operations = tuple(
        f"{capability_id}:initial_non_vacuity" for capability_id in semantic.capability_ids
    )
    steps.append(VerifierStep("initial_non_vacuity", (), non_vacuity_operations))
    return VerifierBundle(semantic.semantic_digest, tuple(steps))


def _selected_capabilities(
    proposal: CandidateTaskProposal,
    capability_index: dict[str, CapabilitySpec],
) -> tuple[CapabilitySpec, ...]:
    missing = sorted(set(proposal.capability_ids) - set(capability_index))
    if missing:
        raise TaskSpecificationError(
            "proposal_capability_unknown",
            "Candidate proposal cites unknown capabilities",
            capability_ids=missing,
        )
    return tuple(capability_index[item] for item in sorted(proposal.capability_ids))


def _validate_composition(
    proposal: CandidateTaskProposal,
    selected: tuple[CapabilitySpec, ...],
) -> None:
    if len(selected) == 1:
        if proposal.composition_rule_id is not None:
            raise TaskSpecificationError(
                "composition_rule_unexpected",
                "single-capability proposal must not cite a CompositionRule",
            )
        return
    if proposal.composition_rule_id is None:
        raise TaskSpecificationError(
            "composition_rule_missing",
            "multi-capability proposal requires a sealed CompositionRule",
        )
    matching = {
        rule.rule_id: rule
        for capability in selected
        for rule in capability.composition_rules
        if rule.rule_id == proposal.composition_rule_id
    }
    rule = matching.get(proposal.composition_rule_id)
    if rule is None or set(rule.capability_ids) != set(proposal.capability_ids):
        raise TaskSpecificationError(
            "composition_rule_mismatch",
            "CompositionRule does not license the selected capabilities",
        )


def _validate_slots(
    proposal: CandidateTaskProposal,
    selected: tuple[CapabilitySpec, ...],
) -> None:
    selected_ids = {item.capability_id for item in selected}
    slot_capabilities = {item.capability_id for item in proposal.public_slots}
    if slot_capabilities != selected_ids:
        raise TaskSpecificationError(
            "proposal_slot_coverage_mismatch",
            "public slots do not cover exactly the selected capabilities",
        )


def _potentially_applies(
    obligation: RequirementObligation,
    selected: tuple[CapabilitySpec, ...],
    proposal_condition_id: str | None,
) -> bool:
    handle = obligation.applicability
    selected_ids = {item.capability_id for item in selected}
    if handle.kind in {"always", "start_case"}:
        return True
    if handle.kind in {"binding_eligible", "facet_predicate"}:
        return handle.capability_id in selected_ids
    condition_ids = {
        condition.condition_id for capability in selected for condition in capability.conditions
    }
    return handle.condition_id in condition_ids or handle.condition_id == proposal_condition_id


def _facet_constraint(value: Any) -> JSONObject:
    if not is_json_object(value) or set(value) != {"facet_name", "operator", "public_literal"}:
        raise TaskSpecificationError(
            "facet_constraint_shape_invalid",
            "facet constraint has invalid fields",
        )
    facet_name = value["facet_name"]
    operator = value["operator"]
    literal = value["public_literal"]
    if not isinstance(facet_name, str) or not facet_name:
        raise TaskSpecificationError(
            "facet_constraint_name_invalid",
            "facet constraint name is invalid",
        )
    if operator not in _FACET_OPERATORS:
        raise TaskSpecificationError(
            "facet_constraint_operator_invalid",
            "facet constraint operator is invalid",
        )
    if not is_json_value(literal) or isinstance(literal, (dict, list)):
        raise TaskSpecificationError(
            "facet_constraint_literal_invalid",
            "facet constraint literal must be a JSON scalar",
        )
    return {
        "facet_name": facet_name,
        "operator": cast(FacetOperator, operator),
        "public_literal": cast(JSONValue, literal),
    }


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise TaskSpecificationError("task_value_not_object", f"{role} must be an object")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _hash(value: Any) -> str:
    try:
        payload = rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise TaskSpecificationError(
            "task_identity_not_json",
            "Task identity value is not canonical JSON",
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _digest_value(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise TaskSpecificationError("task_digest_invalid", f"{role} must be a sha256 digest")


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise TaskSpecificationError(
            "task_identifier_invalid",
            f"{role} must be a non-empty whitespace-free string",
        )


def _identifiers(values: tuple[str, ...], role: str) -> None:
    if not values:
        raise TaskSpecificationError("task_identifiers_missing", f"{role} must not be empty")
    for value in values:
        _identifier(value, role)
    if len(values) != len(set(values)):
        raise TaskSpecificationError("task_identifiers_duplicated", f"{role} must be unique")


__all__ = [
    "CandidateTaskProposal",
    "PublicEvidenceRef",
    "PublicSlotProposal",
    "SamplerDescriptor",
    "TaskSemanticSection",
    "TaskSpecificationError",
    "VerifierBundle",
    "VerifierStep",
    "compile_direct_proposals",
    "compile_task_semantic_section",
    "compile_verifier_bundle",
]

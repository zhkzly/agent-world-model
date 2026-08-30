"""Concrete public binding, canonical instruction, and PublicClosureEvidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import OpenPreparedRelease, OpenPreparedSession
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.requirement_obligations import (
    ObligationApplicability,
    RequirementObligation,
)
from agent_env_foundry.semantics import (
    BindingCandidate,
    CapabilitySpec,
    ConditionCheckRequest,
    StartCase,
)
from agent_env_foundry.task_specification import (
    TaskSemanticSection,
    VerifierBundle,
)

_CONDITION_STATUSES = frozenset({"true", "false", "abstain"})


class TaskBindingError(ValueError):
    """A frozen semantic section cannot bind to the supplied public Start."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class PublicSlotBinding:
    slot_id: str
    bindings: tuple[BindingCandidate, ...]

    def __post_init__(self) -> None:
        _identifier(self.slot_id, "slot binding slot_id")
        if not self.bindings or any(not item.eligible for item in self.bindings):
            raise TaskBindingError(
                "slot_binding_ineligible",
                "public slot binding requires non-empty eligible bindings",
            )
        keys = tuple(item.semantic_key for item in self.bindings)
        if len(keys) != len(set(keys)):
            raise TaskBindingError(
                "slot_binding_duplicated",
                "public slot binding contains duplicate semantic keys",
            )

    def to_document(self) -> JSONObject:
        return _object(
            {
                "slot_id": self.slot_id,
                "bindings": [item.to_document() for item in self.bindings],
            },
            "PublicSlotBinding",
        )


@dataclass(frozen=True, slots=True)
class TaskBindingSection:
    semantic_digest: str
    start_case: StartCase
    reset_observation_digest: str
    slot_bindings: tuple[PublicSlotBinding, ...]
    condition_statuses: JSONObject
    obligation_dispositions: tuple[JSONObject, ...]

    @property
    def binding_digest(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return _object(
            {
                "format": "task-binding-section/1",
                "semantic_digest": self.semantic_digest,
                "start_case": self.start_case.to_document(),
                "reset_observation_digest": self.reset_observation_digest,
                "slot_bindings": [item.to_document() for item in self.slot_bindings],
                "condition_statuses": _object(
                    self.condition_statuses,
                    "binding condition_statuses",
                ),
                "obligation_dispositions": [
                    _object(item, "obligation disposition") for item in self.obligation_dispositions
                ],
            },
            "TaskBindingSection",
        )


@dataclass(frozen=True, slots=True)
class PublicClosureEvidence:
    semantic_digest: str
    constraint_disclosures: tuple[JSONObject, ...]
    operand_sources: tuple[JSONObject, ...]
    answer_opacity: tuple[JSONObject, ...]

    @property
    def evidence_id(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return _object(
            {
                "format": "public-closure-evidence/1",
                "semantic_digest": self.semantic_digest,
                "constraint_disclosures": [
                    _object(item, "constraint disclosure") for item in self.constraint_disclosures
                ],
                "operand_sources": [
                    _object(item, "operand source") for item in self.operand_sources
                ],
                "answer_opacity": [_object(item, "answer opacity") for item in self.answer_opacity],
            },
            "PublicClosureEvidence",
        )


@dataclass(frozen=True, slots=True)
class TaskSpecification:
    semantic: TaskSemanticSection
    verifier: VerifierBundle
    binding: TaskBindingSection
    instruction: str
    instruction_digest: str
    public_closure: PublicClosureEvidence

    def __post_init__(self) -> None:
        semantic_digest = self.semantic.semantic_digest
        if {
            self.verifier.semantic_digest,
            self.binding.semantic_digest,
            self.public_closure.semantic_digest,
        } != {semantic_digest}:
            raise TaskBindingError(
                "task_specification_semantic_mismatch",
                "Task specification sections bind different semantic digests",
            )
        if (
            not self.instruction.strip()
            or _text_digest(self.instruction) != self.instruction_digest
        ):
            raise TaskBindingError(
                "instruction_identity_mismatch",
                "Task instruction is empty or differs from its digest",
            )
        dispositions = {
            cast(str, item["obligation_id"]): cast(bool, item["applicable"])
            for item in self.binding.obligation_dispositions
        }
        applicable_ids = {item for item, applicable in dispositions.items() if applicable}
        disclosure_ids = {
            cast(str, item["obligation_id"]) for item in self.public_closure.constraint_disclosures
        }
        if disclosure_ids != applicable_ids:
            raise TaskBindingError(
                "constraint_disclosures_incomplete",
                "Public constraint disclosures differ from applicable obligations",
            )
        expected_source_keys = {
            f"slot:{slot.slot_id}:{source.field_pointer}"
            for slot in self.binding.slot_bindings
            for binding in slot.bindings
            for source in binding.public_sources
        } | {
            f"answer:{operation.replace(':answer:', ':')}"
            for operation in self.semantic.answer_operation_ids
        }
        actual_source_keys = {
            cast(str, item["source_key"]) for item in self.public_closure.operand_sources
        }
        if actual_source_keys != expected_source_keys:
            raise TaskBindingError(
                "operand_sources_incomplete",
                "Public operand sources differ from frozen slot/answer operands",
            )
        opacity_ids = {
            cast(str, item["answer_operation_id"]) for item in self.public_closure.answer_opacity
        }
        if opacity_ids != set(self.semantic.answer_operation_ids):
            raise TaskBindingError(
                "answer_opacity_incomplete",
                "Answer opacity decisions differ from the frozen answer contract",
            )

    @property
    def specification_id(self) -> str:
        return _hash(self.to_document())

    def to_document(self) -> JSONObject:
        return _object(
            {
                "format": "task-specification/1",
                "semantic_section": self.semantic.to_document(),
                "verifier_bundle": self.verifier.to_document(),
                "binding_section": self.binding.to_document(),
                "instruction": self.instruction,
                "instruction_digest": self.instruction_digest,
                "public_closure": self.public_closure.to_document(),
            },
            "TaskSpecification",
        )


def materialize_task_specification(
    prepared: OpenPreparedRelease,
    semantic: TaskSemanticSection,
    verifier: VerifierBundle,
    instance_root: Path,
    *,
    start_case_id: str,
) -> TaskSpecification:
    """Reset once, resolve public bindings, evaluate S1 handles, and freeze one Task."""

    if semantic.release_id != prepared.identity.release_id:
        raise TaskBindingError(
            "task_release_mismatch",
            "Task semantic section belongs to another EnvironmentRelease",
        )
    starts = {item.case_id: item for item in prepared.start_cases}
    start_case = starts.get(start_case_id)
    if start_case is None:
        raise TaskBindingError(
            "task_start_case_missing",
            "Task materialization cites an unsealed StartCase",
        )
    root = Path(instance_root)
    with prepared.open(root) as session:
        reset_observation = session.actor.reset(start_case.reset_input)
        before_facts = session.trusted.inspect(root)
        capabilities = session.trusted.capabilities()
        slot_bindings = _resolve_slot_bindings(
            session,
            semantic,
            capabilities,
            before_facts,
        )
        condition_statuses = _evaluate_condition_statuses(
            session,
            semantic,
            capabilities,
            slot_bindings,
            before_facts,
            prepared.requirement_obligations,
        )
    return _bind_task_specification(
        semantic,
        verifier,
        start_case=start_case,
        reset_observation=reset_observation,
        slot_bindings=slot_bindings,
        condition_statuses=condition_statuses,
        capabilities=capabilities,
        obligations=prepared.requirement_obligations,
    )


def _bind_task_specification(
    semantic: TaskSemanticSection,
    verifier: VerifierBundle,
    *,
    start_case: StartCase,
    reset_observation: JSONValue,
    slot_bindings: tuple[PublicSlotBinding, ...],
    condition_statuses: JSONObject,
    capabilities: tuple[CapabilitySpec, ...],
    obligations: tuple[RequirementObligation, ...],
) -> TaskSpecification:
    if verifier.semantic_digest != semantic.semantic_digest:
        raise TaskBindingError(
            "verifier_semantic_mismatch",
            "VerifierBundle belongs to another semantic section",
        )
    if not is_json_value(reset_observation):
        raise TaskBindingError(
            "reset_observation_not_json",
            "binding reset observation must be JSON",
        )
    slot_index = {item.slot_id: item for item in slot_bindings}
    if set(slot_index) != {item.slot_id for item in semantic.public_slots}:
        raise TaskBindingError(
            "slot_binding_coverage_mismatch",
            "concrete slot bindings differ from frozen public slots",
        )
    for slot in semantic.public_slots:
        concrete = slot_index[slot.slot_id]
        if slot.cardinality == "one" and len(concrete.bindings) != 1:
            raise TaskBindingError(
                "slot_binding_cardinality_mismatch",
                "one-cardinality public slot requires exactly one binding",
            )
    capability_index = {item.capability_id: item for item in capabilities}
    obligation_index = {item.obligation_id: item for item in obligations}
    selected_obligations: list[RequirementObligation] = []
    dispositions: list[JSONObject] = []
    for obligation_id in semantic.obligation_ids:
        obligation = obligation_index.get(obligation_id)
        if obligation is None:
            raise TaskBindingError(
                "binding_obligation_missing",
                "binding is missing a frozen Requirement obligation",
            )
        applicable, decisive = _evaluate_applicability(
            obligation.applicability,
            start_case=start_case,
            slot_bindings=slot_bindings,
            condition_statuses=condition_statuses,
            semantic=semantic,
        )
        dispositions.append(
            {
                "obligation_id": obligation_id,
                "applicable": applicable,
                "evaluation_digest": _hash(decisive),
            }
        )
        if applicable:
            selected_obligations.append(obligation)
    if len({item.canonical_text_digest for item in selected_obligations}) != len(
        selected_obligations
    ):
        raise TaskBindingError(
            "applicable_obligation_text_duplicated",
            "applicable obligations contain duplicate canonical constraints",
        )
    instruction, disclosures = _render_instruction(
        semantic,
        slot_bindings,
        selected_obligations,
        capability_index,
    )
    operand_sources, opacity = _public_source_evidence(
        semantic,
        slot_bindings,
        capability_index,
    )
    selected_capabilities = tuple(capability_index[item] for item in semantic.capability_ids)
    if selected_capabilities and all(item.task_kind == "query" for item in selected_capabilities):
        if opacity and all(cast(bool, item["available_before_act"]) for item in opacity):
            raise TaskBindingError(
                "query_answer_already_available",
                "query answer contract is fully available before public acting",
            )
    binding = TaskBindingSection(
        semantic.semantic_digest,
        start_case,
        _hash(reset_observation),
        tuple(sorted(slot_bindings, key=lambda item: item.slot_id)),
        _object(condition_statuses, "condition statuses"),
        tuple(sorted(dispositions, key=lambda item: cast(str, item["obligation_id"]))),
    )
    closure = PublicClosureEvidence(
        semantic.semantic_digest,
        tuple(disclosures),
        tuple(operand_sources),
        tuple(opacity),
    )
    return TaskSpecification(
        semantic,
        verifier,
        binding,
        instruction,
        _text_digest(instruction),
        closure,
    )


def _resolve_slot_bindings(
    session: OpenPreparedSession,
    semantic: TaskSemanticSection,
    capabilities: tuple[CapabilitySpec, ...],
    before_facts: JSONValue,
) -> tuple[PublicSlotBinding, ...]:
    capability_index = {item.capability_id: item for item in capabilities}
    resolved: list[PublicSlotBinding] = []
    for slot in semantic.public_slots:
        if slot.capability_id not in capability_index:
            raise TaskBindingError(
                "task_slot_capability_missing",
                "live release no longer exposes a frozen slot capability",
            )
        candidates = session.trusted.enumerate_bindings(slot.capability_id, before_facts)
        eligible = tuple(
            sorted(
                (
                    item
                    for item in candidates
                    if item.eligible and _matches_facet_constraints(item, slot.facet_constraints)
                ),
                key=lambda item: item.semantic_key,
            )
        )
        if not eligible:
            raise TaskBindingError(
                "task_slot_no_public_binding",
                "frozen public slot has no eligible binding on this Start",
                slot_id=slot.slot_id,
            )
        selected = eligible[:1] if slot.cardinality == "one" else eligible
        resolved.append(PublicSlotBinding(slot.slot_id, selected))
    return tuple(resolved)


def _evaluate_condition_statuses(
    session: OpenPreparedSession,
    semantic: TaskSemanticSection,
    capabilities: tuple[CapabilitySpec, ...],
    slot_bindings: tuple[PublicSlotBinding, ...],
    before_facts: JSONValue,
    obligations: tuple[RequirementObligation, ...],
) -> JSONObject:
    obligation_index = {item.obligation_id: item for item in obligations}
    condition_ids = {
        cast(str, obligation_index[item].applicability.condition_id)
        for item in semantic.obligation_ids
        if item in obligation_index
        and obligation_index[item].applicability.kind == "condition_branch"
    }
    if semantic.condition_id is not None:
        condition_ids.add(semantic.condition_id)
    if not condition_ids:
        return {}
    condition_index = {
        condition.condition_id: (capability.capability_id, condition)
        for capability in capabilities
        for condition in capability.conditions
    }
    slot_index = {item.slot_id: item for item in slot_bindings}
    slot_specs = {item.slot_id: item for item in semantic.public_slots}
    statuses: JSONObject = {}
    for condition_id in sorted(condition_ids):
        entry = condition_index.get(condition_id)
        if entry is None:
            raise TaskBindingError(
                "task_condition_missing",
                "live release no longer exposes a frozen condition",
                condition_id=condition_id,
            )
        capability_id, _ = entry
        candidate = next(
            (
                slot_index[slot_id].bindings[0]
                for slot_id, spec in slot_specs.items()
                if spec.capability_id == capability_id
            ),
            next(iter(slot_bindings)).bindings[0],
        )
        result = session.trusted.evaluate_condition(
            ConditionCheckRequest(
                condition_id,
                before_facts,
                candidate.protected_binding,
                (),
            )
        )
        if result.status == "abstain":
            raise TaskBindingError(
                "task_condition_unresolved",
                "S1 TaskSemantics abstained on a binding-time applicability condition",
                condition_id=condition_id,
                failure_codes=list(result.failure_codes),
            )
        statuses[condition_id] = result.status
    return statuses


def _matches_facet_constraints(
    binding: BindingCandidate,
    constraints: tuple[JSONObject, ...],
) -> bool:
    return all(
        _compare(
            binding.facets.get(cast(str, constraint["facet_name"])),
            constraint["operator"],
            constraint["public_literal"],
        )
        for constraint in constraints
    )


def _evaluate_applicability(
    handle: ObligationApplicability,
    *,
    start_case: StartCase,
    slot_bindings: tuple[PublicSlotBinding, ...],
    condition_statuses: JSONObject,
    semantic: TaskSemanticSection,
) -> tuple[bool, JSONObject]:
    if handle.kind == "always":
        decisive: JSONObject = {"kind": "always"}
        return True, decisive
    if handle.kind == "start_case":
        decisive = {
            "kind": "start_case",
            "expected_case_id": handle.case_id,
            "actual_case_id": start_case.case_id,
        }
        return handle.case_id == start_case.case_id, decisive
    if handle.kind == "condition_branch":
        status = condition_statuses.get(cast(str, handle.condition_id))
        if status not in _CONDITION_STATUSES:
            raise TaskBindingError(
                "condition_status_missing",
                "binding lacks a deterministic condition status",
                condition_id=handle.condition_id,
            )
        decisive = {
            "kind": "condition_branch",
            "condition_id": handle.condition_id,
            "expected_branch": handle.branch,
            "actual_status": status,
        }
        return status == handle.branch, decisive
    selected = [
        binding
        for slot, slot_spec in (
            (slot, next(item for item in semantic.public_slots if item.slot_id == slot.slot_id))
            for slot in slot_bindings
        )
        if slot_spec.capability_id == handle.capability_id
        for binding in slot.bindings
    ]
    if not selected:
        raise TaskBindingError(
            "applicability_capability_unbound",
            "applicability handle capability has no concrete public binding",
        )
    if handle.kind == "binding_eligible":
        decisive = {
            "kind": "binding_eligible",
            "capability_id": handle.capability_id,
            "semantic_keys": [item.semantic_key for item in selected],
            "eligible": [item.eligible for item in selected],
        }
        return all(item.eligible for item in selected), decisive
    if handle.operator in {"min", "max"}:
        raise TaskBindingError(
            "facet_extremum_requires_binding_universe",
            "facet min/max applicability requires a qualified binding universe",
        )
    values = [item.facets.get(cast(str, handle.facet_name)) for item in selected]
    results = [_compare(value, handle.operator, handle.public_literal) for value in values]
    decisive = {
        "kind": "facet_predicate",
        "capability_id": handle.capability_id,
        "facet_name": handle.facet_name,
        "operator": handle.operator,
        "public_literal": handle.public_literal,
        "selected_values": cast(JSONValue, values),
        "results": cast(JSONValue, results),
    }
    return any(results), decisive


def _render_instruction(
    semantic: TaskSemanticSection,
    slots: tuple[PublicSlotBinding, ...],
    obligations: list[RequirementObligation],
    capabilities: dict[str, CapabilitySpec],
) -> tuple[str, list[JSONObject]]:
    public_targets = {
        slot.slot_id: [item.public_document() for item in slot.bindings]
        for slot in sorted(slots, key=lambda item: item.slot_id)
    }
    lines = [
        semantic.objective.strip(),
        "Selected public targets: "
        + json.dumps(public_targets, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "Required constraints:",
    ]
    disclosures: list[JSONObject] = []
    for obligation in sorted(obligations, key=lambda item: item.obligation_id):
        span = f"- {obligation.canonical_text}"
        lines.append(span)
        disclosures.append(
            {
                "obligation_id": obligation.obligation_id,
                "instruction_span_digest": _text_digest(span),
            }
        )
    lines.append("Return one JSON object with these exact fields:")
    for operation in semantic.answer_operation_ids:
        capability_id, _, field_id = operation.partition(":answer:")
        capability = capabilities[capability_id]
        field = next(item for item in capability.answer_fields if item.field_id == field_id)
        lines.append(f"- {field.field_id}: {field.public_label}")
    lines.append("Use exact public values; do not paraphrase identifiers or content.")
    return "\n".join(lines), disclosures


def _public_source_evidence(
    semantic: TaskSemanticSection,
    slots: tuple[PublicSlotBinding, ...],
    capabilities: dict[str, CapabilitySpec],
) -> tuple[list[JSONObject], list[JSONObject]]:
    operands: list[JSONObject] = []
    for slot in sorted(slots, key=lambda item: item.slot_id):
        for binding in slot.bindings:
            for item in binding.public_sources:
                operands.append(
                    {
                        "source_key": f"slot:{slot.slot_id}:{item.field_pointer}",
                        "source": item.source.to_document(),
                    }
                )
    opacity: list[JSONObject] = []
    for operation in semantic.answer_operation_ids:
        capability_id, _, field_id = operation.partition(":answer:")
        field = next(
            item for item in capabilities[capability_id].answer_fields if item.field_id == field_id
        )
        operands.append(
            {
                "source_key": f"answer:{capability_id}:{field_id}",
                "source": field.public_source.to_document(),
            }
        )
        opacity.append(
            {
                "answer_operation_id": operation,
                "source_kind": field.public_source.kind,
                "available_before_act": field.public_source.kind != "tool_observation",
            }
        )
    return operands, opacity


def _compare(left: JSONValue | None, operator: Any, right: JSONValue | None) -> bool:
    if operator == "eq":
        return left == right
    if operator == "neq":
        return left != right
    try:
        if operator == "lt":
            return bool(left < right)  # type: ignore[operator]
        if operator == "lte":
            return bool(left <= right)  # type: ignore[operator]
        if operator == "gt":
            return bool(left > right)  # type: ignore[operator]
        if operator == "gte":
            return bool(left >= right)  # type: ignore[operator]
    except TypeError:
        return False
    raise TaskBindingError("facet_operator_invalid", "facet applicability operator is invalid")


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise TaskBindingError("task_binding_not_object", f"{role} must be an object")
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise TaskBindingError(
            "task_binding_identifier_invalid",
            f"{role} must be a non-empty whitespace-free string",
        )


__all__ = [
    "PublicClosureEvidence",
    "PublicSlotBinding",
    "TaskBindingError",
    "TaskBindingSection",
    "TaskSpecification",
    "materialize_task_specification",
]

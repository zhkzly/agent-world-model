"""Candidate-blind expected TaskSemantics freeze for S1 Qualification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from agent_env_foundry.agents import (
    AgentRoute,
    ClientFactory,
    _default_client_factory,
    _ProviderTurnBudget,
    _run_fresh_json_turn,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.research import BuilderProjection, ResearchFailure

EXPECTED_TASK_SEMANTICS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "requirement_id": {"type": "string"},
                    "disposition": {
                        "type": "string",
                        "enum": ["Taskable", "NotTaskable", "Unsupported"],
                    },
                    "rationale": {"type": "string"},
                    "preconditions": {"type": "array", "items": {"type": "string"}},
                    "outcomes": {"type": "array", "items": {"type": "string"}},
                    "refusals": {"type": "array", "items": {"type": "string"}},
                    "collateral_constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "workflow_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "requirement_id",
                    "disposition",
                    "rationale",
                    "preconditions",
                    "outcomes",
                    "refusals",
                    "collateral_constraints",
                    "workflow_ids",
                ],
                "additionalProperties": False,
            },
        },
        "capabilities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "capability_id": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "workflow_ids": {"type": "array", "items": {"type": "string"}},
                    "actor_role": {"type": "string"},
                    "task_kind": {
                        "type": "string",
                        "enum": ["query", "state_change", "process"],
                    },
                    "intent_label": {"type": "string"},
                    "answer_fields": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field_id": {"type": "string"},
                                "public_label": {"type": "string"},
                            },
                            "required": ["field_id", "public_label"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "capability_id",
                    "requirement_ids",
                    "workflow_ids",
                    "actor_role",
                    "task_kind",
                    "intent_label",
                    "answer_fields",
                ],
                "additionalProperties": False,
            },
        },
        "composition_rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "workflow_id": {"type": "string"},
                    "capability_ids": {"type": "array", "items": {"type": "string"}},
                    "max_occurrences": {"type": "integer", "minimum": 1},
                },
                "required": [
                    "rule_id",
                    "workflow_id",
                    "capability_ids",
                    "max_occurrences",
                ],
                "additionalProperties": False,
            },
        },
        "conditions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "condition_id": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "workflow_ids": {"type": "array", "items": {"type": "string"}},
                    "observable_relation": {"type": "string"},
                    "public_label": {"type": "string"},
                    "visibility": {"type": "string", "enum": ["reset", "public_tool"]},
                    "binding_scope": {
                        "type": "string",
                        "enum": ["world", "selected_binding"],
                    },
                    "true_capability_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "false_capability_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "report_field_id": {"type": "string"},
                },
                "required": [
                    "condition_id",
                    "requirement_ids",
                    "workflow_ids",
                    "observable_relation",
                    "public_label",
                    "visibility",
                    "binding_scope",
                    "true_capability_ids",
                    "false_capability_ids",
                    "report_field_id",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "requirements",
        "capabilities",
        "composition_rules",
        "conditions",
    ],
    "additionalProperties": False,
}


class ExpectedSemanticsError(ValueError):
    """Expected TaskSemantics is incomplete or contradicts the Brief projection."""

    def __init__(self, findings: str | Sequence[str]) -> None:
        normalized = (findings,) if isinstance(findings, str) else tuple(findings)
        self.findings = normalized
        super().__init__("; ".join(normalized))


@dataclass(frozen=True, slots=True)
class ExpectedTaskSemantics:
    canonical_payload: bytes
    digest: str

    def to_document(self) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self.canonical_payload))


def freeze_expected_task_semantics(
    projection: BuilderProjection,
    document: Mapping[str, Any],
) -> ExpectedTaskSemantics:
    expected_ids = _projection_requirement_ids(projection)
    expected_id_set = set(expected_ids)
    root = _exact(
        document,
        {"requirements", "capabilities", "composition_rules", "conditions"},
        "expected semantics",
    )
    requirements = [_requirement(item) for item in _array(root["requirements"], "requirements")]
    by_id = _unique_index(requirements, "requirement_id", "Requirement")
    taskable_ids = {
        item["requirement_id"] for item in requirements if item["disposition"] == "Taskable"
    }
    initial_ids = {cast(str, item.get("id")) for item in projection.initial_world_relations}
    capabilities = [_capability(item) for item in _array(root["capabilities"], "capabilities")]
    capability_index = _unique_index(capabilities, "capability_id", "capability")
    rules = [_composition(item) for item in _array(root["composition_rules"], "composition_rules")]
    _unique_index(rules, "rule_id", "composition rule")
    conditions = [_condition(item) for item in _array(root["conditions"], "conditions")]
    _unique_index(conditions, "condition_id", "condition")

    findings: list[str] = []
    if set(by_id) != expected_id_set:
        findings.append(
            "$.requirements: Requirement coverage mismatch: "
            f"expected {list(expected_ids)}, got {sorted(by_id)}"
        )
    taskable_initial = taskable_ids & initial_ids
    if taskable_initial:
        findings.append(
            "$.requirements: initial-world Requirements define StartCases/setup and cannot be "
            f"Taskable; got {sorted(taskable_initial)}"
        )
    for index, item in enumerate(requirements):
        findings.extend(_requirement_findings(item, f"$.requirements[{index}]"))

    mapped_taskable: set[str] = set()
    for index, capability in enumerate(capabilities):
        path = f"$.capabilities[{index}]"
        refs = set(capability["requirement_ids"])
        unknown = refs - expected_id_set
        if unknown:
            findings.append(f"{path}.requirement_ids: unknown Requirement {sorted(unknown)}")
        if not refs:
            findings.append(f"{path}.requirement_ids: capability must reference a Requirement")
        non_taskable = refs & expected_id_set - taskable_ids
        if non_taskable:
            findings.append(
                f"{path}.requirement_ids: capability may reference only Taskable Requirements; "
                f"got {sorted(non_taskable)}"
            )
        known_taskable = refs & taskable_ids
        mapped_taskable.update(known_taskable)
        requirement_workflows = {
            workflow
            for requirement_id in refs & set(by_id)
            for workflow in by_id[requirement_id]["workflow_ids"]
        }
        unlicensed_workflows = set(capability["workflow_ids"]) - requirement_workflows
        if unlicensed_workflows:
            findings.append(
                f"{path}.workflow_ids: unlicensed workflow {sorted(unlicensed_workflows)}"
            )
        if capability["task_kind"] == "query" and not capability["answer_fields"]:
            findings.append(f"{path}: query capability requires answer_fields")
    if mapped_taskable != taskable_ids:
        findings.append(
            "$.capabilities: every Taskable Requirement must map to a capability; "
            f"unmapped {sorted(taskable_ids - mapped_taskable)}"
        )

    for index, rule in enumerate(rules):
        path = f"$.composition_rules[{index}]"
        refs = set(rule["capability_ids"])
        unknown = refs - set(capability_index)
        if len(refs) < 2:
            findings.append(f"{path}.capability_ids: at least two capabilities are required")
        if unknown:
            findings.append(f"{path}.capability_ids: unknown capability {sorted(unknown)}")
        known = refs & set(capability_index)
        if known and any(
            rule["workflow_id"] not in capability_index[reference]["workflow_ids"]
            for reference in known
        ):
            findings.append(
                f"{path}.workflow_id: workflow is not shared by every referenced capability"
            )

    for index, condition in enumerate(conditions):
        path = f"$.conditions[{index}]"
        requirement_refs = set(condition["requirement_ids"])
        unknown_requirements = requirement_refs - expected_id_set
        if not requirement_refs:
            findings.append(f"{path}.requirement_ids: condition must be Requirement-anchored")
        if unknown_requirements:
            findings.append(
                f"{path}.requirement_ids: unknown Requirement {sorted(unknown_requirements)}"
            )
        unsupported = {
            reference
            for reference in requirement_refs & set(by_id)
            if by_id[reference]["disposition"] == "Unsupported"
        }
        if unsupported:
            findings.append(
                f"{path}.requirement_ids: Unsupported Requirements cannot license a condition; "
                f"got {sorted(unsupported)}"
            )
        condition_workflows = set(condition["workflow_ids"])
        requirement_workflows = {
            workflow
            for reference in requirement_refs & set(by_id)
            for workflow in by_id[reference]["workflow_ids"]
        }
        if not condition_workflows:
            findings.append(f"{path}.workflow_ids: condition must be workflow-anchored")
        unlicensed = condition_workflows - requirement_workflows
        if unlicensed:
            findings.append(f"{path}.workflow_ids: unlicensed workflow {sorted(unlicensed)}")

        true_refs = set(condition["true_capability_ids"])
        false_refs = set(condition["false_capability_ids"])
        branch_refs = true_refs | false_refs
        unknown_true = true_refs - set(capability_index)
        unknown_false = false_refs - set(capability_index)
        if unknown_true:
            findings.append(
                f"{path}.true_capability_ids: unknown capability {sorted(unknown_true)}"
            )
        if unknown_false:
            findings.append(
                f"{path}.false_capability_ids: unknown capability {sorted(unknown_false)}"
            )
        overlap = true_refs & false_refs
        if overlap:
            findings.append(
                f"{path}: the same capability cannot be licensed in both branches; "
                f"got {sorted(overlap)}"
            )
        if not branch_refs and not condition["report_field_id"]:
            findings.append(f"{path}: condition licenses neither a branch nor a report")
        for reference in branch_refs & set(capability_index):
            if not condition_workflows.intersection(capability_index[reference]["workflow_ids"]):
                findings.append(f"{path}: capability {reference!r} shares no condition workflow")

    if findings:
        raise ExpectedSemanticsError(findings)

    canonical = {
        "format": "expected-task-semantics/1",
        "requirements": sorted(requirements, key=lambda item: item["requirement_id"]),
        "capabilities": sorted(capabilities, key=lambda item: item["capability_id"]),
        "composition_rules": sorted(rules, key=lambda item: item["rule_id"]),
        "conditions": sorted(conditions, key=lambda item: item["condition_id"]),
    }
    payload = canonical_bytes(canonical)
    return ExpectedTaskSemantics(
        payload,
        hashlib.sha256(payload).hexdigest(),
    )


def generate_expected_task_semantics(
    projection: BuilderProjection,
    *,
    route: AgentRoute | None = None,
    client_factory: ClientFactory | None = None,
) -> ExpectedTaskSemantics:
    selected = route or AgentRoute()

    def validate(document: dict[str, Any]) -> None:
        try:
            freeze_expected_task_semantics(projection, document)
        except ExpectedSemanticsError as exc:
            raise ResearchFailure(
                phase="expected_semantics",
                code="expected_semantics_invalid",
                message=str(exc),
                details={
                    "required_requirement_ids": list(_projection_requirement_ids(projection)),
                    "findings": list(exc.findings),
                },
            ) from exc

    projection_document = projection.to_document()
    provider_input = {
        "builder_projection": {
            "frozen_need": projection_document["frozen_need"],
            "selected_world": projection_document["selected_world"],
            "requirements": projection_document["requirements"],
            "initial_world_relations": projection_document["initial_world_relations"],
        },
        "host_contract": {
            "required_requirement_ids": list(_projection_requirement_ids(projection)),
            "dispositions": {
                "Taskable": (
                    "a meaningful user goal with deterministic state, answer, or process truth"
                ),
                "NotTaskable": (
                    "a supporting invariant, refusal, or initial relation that is not a "
                    "standalone user goal"
                ),
                "Unsupported": (
                    "a required relation that this bounded world cannot expose deterministically"
                ),
            },
            "rules": [
                "Disposition every required Requirement exactly once.",
                "Every Taskable Requirement must be mapped by at least one capability.",
                "Initial-world Requirements define StartCases/setup and are never Taskable.",
                "Capabilities may reference only Taskable Requirements and their workflows.",
                "Composition requires an explicit rule over at least two capabilities that "
                "all declare its workflow.",
                "Each condition must cite Requirement and workflow anchors, state the public "
                "observable relation, and license only known capability branches.",
                "Every query capability must declare one or more answer field IDs and public "
                "labels. These names are semantic contracts; do not include native paths or "
                "reference answers.",
                "Use empty composition_rules or conditions arrays when none are justified.",
            ],
        },
    }
    document = _run_fresh_json_turn(
        route=selected,
        client_factory=client_factory or _default_client_factory,
        instructions=(
            "Independently derive complete release-local task semantics from the accepted Need, "
            "world choice and frozen Requirement relations. Treat the supplied Host contract as "
            "mandatory. Preconditions, outcomes, refusals and collateral constraints describe "
            "business truth, not tool call recipes. A shared workflow alone does not justify "
            "composition. Environment reset/reconstruction is StartCase setup, not a user Task "
            "capability. A condition is legal only when its truth is publicly observable. Do "
            "not assume candidate source, native fields, implementation details, Tasks, traces, "
            "answers or verdicts. Return the complete replacement document in one response."
        ),
        input_text=json.dumps(provider_input, ensure_ascii=False, sort_keys=True),
        schema_name="expected_task_semantics",
        schema=EXPECTED_TASK_SEMANTICS_SCHEMA,
        final_validator=validate,
        provider_budget=_ProviderTurnBudget(selected.max_provider_turns),
        failure_phase="expected_semantics",
        feedback_subject="Expected TaskSemantics",
        feedback_instruction=(
            "Return a complete corrected Expected TaskSemantics document that fixes every "
            "finding above; preserve still-valid relations and do not emit a patch."
        ),
    )
    return freeze_expected_task_semantics(projection, document)


def _projection_requirement_ids(projection: BuilderProjection) -> tuple[str, ...]:
    values = [*projection.requirements, *projection.initial_world_relations]
    ids = [item.get("id") for item in values]
    if any(not isinstance(value, str) or not value for value in ids):
        raise ExpectedSemanticsError("projection Requirement IDs are invalid")
    string_ids = [str(value) for value in ids]
    if len(string_ids) != len(set(string_ids)):
        raise ExpectedSemanticsError("projection Requirement IDs are duplicated")
    return tuple(sorted(string_ids))


def _requirement_findings(item: dict[str, Any], path: str) -> list[str]:
    findings: list[str] = []
    if not item["rationale"].strip():
        findings.append(f"{path}.rationale: every Requirement disposition needs rationale")
    if item["disposition"] == "Taskable":
        required = {
            "preconditions": item["preconditions"],
            "outcomes": item["outcomes"],
            "workflow_ids": item["workflow_ids"],
        }
        missing = sorted(field for field, value in required.items() if not value)
        if missing:
            findings.append(
                f"{path}: Taskable Requirement is semantically incomplete; empty {missing}"
            )
    return findings


def _requirement(value: Any) -> dict[str, Any]:
    keys = {
        "requirement_id",
        "disposition",
        "rationale",
        "preconditions",
        "outcomes",
        "refusals",
        "collateral_constraints",
        "workflow_ids",
    }
    item = _exact(value, keys, "Requirement disposition")
    if item["disposition"] not in {"Taskable", "NotTaskable", "Unsupported"}:
        raise ExpectedSemanticsError("Requirement disposition is invalid")
    _identifier(item["requirement_id"], "requirement_id")
    _string(item["rationale"], "rationale")
    for field in (
        "preconditions",
        "outcomes",
        "refusals",
        "collateral_constraints",
        "workflow_ids",
    ):
        item[field] = _strings(item[field], field)
    return item


def _capability(value: Any) -> dict[str, Any]:
    keys = {
        "capability_id",
        "requirement_ids",
        "workflow_ids",
        "actor_role",
        "task_kind",
        "intent_label",
        "answer_fields",
    }
    item = _exact(value, keys, "capability")
    _identifier(item["capability_id"], "capability_id")
    for field in ("actor_role", "intent_label"):
        _text(item[field], field)
    _string(item["task_kind"], "task_kind")
    if item["task_kind"] not in {"query", "state_change", "process"}:
        raise ExpectedSemanticsError("capability task_kind is invalid")
    item["requirement_ids"] = _strings(item["requirement_ids"], "requirement_ids")
    item["workflow_ids"] = _strings(item["workflow_ids"], "workflow_ids")
    answer_fields = [
        _answer_field(field) for field in _array(item["answer_fields"], "answer_fields")
    ]
    _unique_index(answer_fields, "field_id", "answer field")
    item["answer_fields"] = sorted(answer_fields, key=lambda field: field["field_id"])
    return item


def _answer_field(value: Any) -> dict[str, str]:
    item = _exact(value, {"field_id", "public_label"}, "answer field")
    return {
        "field_id": _identifier(item["field_id"], "answer field_id"),
        "public_label": _text(item["public_label"], "answer public_label"),
    }


def _composition(value: Any) -> dict[str, Any]:
    item = _exact(
        value,
        {"rule_id", "workflow_id", "capability_ids", "max_occurrences"},
        "composition rule",
    )
    _identifier(item["rule_id"], "rule_id")
    _identifier(item["workflow_id"], "workflow_id")
    item["capability_ids"] = _strings(item["capability_ids"], "capability_ids")
    if (
        not isinstance(item["max_occurrences"], int)
        or isinstance(item["max_occurrences"], bool)
        or item["max_occurrences"] <= 0
    ):
        raise ExpectedSemanticsError("composition max_occurrences must be positive integer")
    return item


def _condition(value: Any) -> dict[str, Any]:
    keys = {
        "condition_id",
        "requirement_ids",
        "workflow_ids",
        "observable_relation",
        "public_label",
        "visibility",
        "binding_scope",
        "true_capability_ids",
        "false_capability_ids",
        "report_field_id",
    }
    item = _exact(value, keys, "condition")
    _identifier(item["condition_id"], "condition_id")
    for field in ("observable_relation", "public_label"):
        _text(item[field], field)
    for field in ("visibility", "binding_scope", "report_field_id"):
        _string(item[field], field)
    if item["report_field_id"]:
        _identifier(item["report_field_id"], "report_field_id")
    if item["visibility"] not in {"reset", "public_tool"} or item["binding_scope"] not in {
        "world",
        "selected_binding",
    }:
        raise ExpectedSemanticsError("condition visibility/scope is invalid")
    item["requirement_ids"] = _strings(item["requirement_ids"], "requirement_ids")
    item["workflow_ids"] = _strings(item["workflow_ids"], "workflow_ids")
    item["true_capability_ids"] = _strings(item["true_capability_ids"], "true_capability_ids")
    item["false_capability_ids"] = _strings(item["false_capability_ids"], "false_capability_ids")
    return item


def _exact(value: Any, keys: set[str], role: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ExpectedSemanticsError(f"{role} has invalid fields")
    return dict(value)


def _array(value: Any, role: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExpectedSemanticsError(f"{role} must be an array")
    return value


def _string(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise ExpectedSemanticsError(f"{role} must be a string")
    return value


def _identifier(value: Any, role: str) -> str:
    text = _string(value, role)
    if not text or text.strip() != text or any(character.isspace() for character in text):
        raise ExpectedSemanticsError(f"{role} must be a non-empty whitespace-free string")
    return text


def _text(value: Any, role: str) -> str:
    text = _string(value, role)
    if not text.strip():
        raise ExpectedSemanticsError(f"{role} must be non-empty")
    return text


def _strings(value: Any, role: str) -> list[str]:
    values = _array(value, role)
    if any(not isinstance(item, str) or not item for item in values):
        raise ExpectedSemanticsError(f"{role} must contain non-empty strings")
    if len(values) != len(set(values)):
        raise ExpectedSemanticsError(f"{role} must be unique")
    return sorted(values)


def _unique_index(values: list[dict[str, Any]], key: str, role: str) -> dict[str, dict[str, Any]]:
    result = {str(item[key]): item for item in values}
    if len(result) != len(values):
        raise ExpectedSemanticsError(f"duplicate {role} ID")
    return result

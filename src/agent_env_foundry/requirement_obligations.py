"""Sealed S1 Requirement obligations and finite applicability handles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, cast

import rfc8785

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.jsonvalue import is_json_object, is_json_value

ObligationKind = Literal[
    "precondition",
    "effect",
    "answer",
    "process",
    "refusal",
    "collateral",
]
ApplicabilityKind = Literal[
    "always",
    "start_case",
    "binding_eligible",
    "condition_branch",
    "facet_predicate",
]
ConditionBranch = Literal["true", "false"]
FacetOperator = Literal["eq", "neq", "lt", "lte", "gt", "gte", "min", "max"]

_OBLIGATION_KINDS = frozenset(
    {"precondition", "effect", "answer", "process", "refusal", "collateral"}
)
_APPLICABILITY_KINDS = frozenset(
    {"always", "start_case", "binding_eligible", "condition_branch", "facet_predicate"}
)
_FACET_OPERATORS = frozenset({"eq", "neq", "lt", "lte", "gt", "gte", "min", "max"})
_CLAUSE_KINDS: dict[str, ObligationKind] = {
    "preconditions": "precondition",
    "outcomes": "effect",
    "refusals": "refusal",
    "collateral_constraints": "collateral",
    "process_constraints": "process",
}


class RequirementObligationError(ValueError):
    """A sealed obligation or applicability handle is malformed."""


@dataclass(frozen=True, slots=True)
class ObligationApplicability:
    kind: ApplicabilityKind
    case_id: str | None = None
    capability_id: str | None = None
    condition_id: str | None = None
    branch: ConditionBranch | None = None
    facet_name: str | None = None
    operator: FacetOperator | None = None
    public_literal: JSONValue | None = None

    def __post_init__(self) -> None:
        if self.kind not in _APPLICABILITY_KINDS:
            raise RequirementObligationError("applicability kind is invalid")
        for value, role in (
            (self.case_id, "case_id"),
            (self.capability_id, "capability_id"),
            (self.condition_id, "condition_id"),
            (self.facet_name, "facet_name"),
        ):
            if value is not None:
                _identifier(value, role)
        if self.branch is not None and self.branch not in {"true", "false"}:
            raise RequirementObligationError("condition branch is invalid")
        if self.operator is not None and self.operator not in _FACET_OPERATORS:
            raise RequirementObligationError("facet operator is invalid")
        if not is_json_value(self.public_literal):
            raise RequirementObligationError("facet public_literal must be JSON")
        if isinstance(self.public_literal, (dict, list)):
            raise RequirementObligationError("facet public_literal must be a JSON scalar")

        populated = {
            "case_id": self.case_id is not None,
            "capability_id": self.capability_id is not None,
            "condition_id": self.condition_id is not None,
            "branch": self.branch is not None,
            "facet_name": self.facet_name is not None,
            "operator": self.operator is not None,
        }
        required: dict[ApplicabilityKind, frozenset[str]] = {
            "always": frozenset(),
            "start_case": frozenset({"case_id"}),
            "binding_eligible": frozenset({"capability_id"}),
            "condition_branch": frozenset({"condition_id", "branch"}),
            "facet_predicate": frozenset({"capability_id", "facet_name", "operator"}),
        }
        actual = frozenset(name for name, present in populated.items() if present)
        if actual != required[self.kind]:
            raise RequirementObligationError(
                f"{self.kind} applicability fields must be exactly {sorted(required[self.kind])}"
            )
        if self.kind != "facet_predicate" and self.public_literal is not None:
            raise RequirementObligationError(
                "only facet_predicate applicability may declare public_literal"
            )

    def to_document(self) -> JSONObject:
        return {
            "kind": self.kind,
            "case_id": self.case_id,
            "capability_id": self.capability_id,
            "condition_id": self.condition_id,
            "branch": self.branch,
            "facet_name": self.facet_name,
            "operator": self.operator,
            "public_literal": self.public_literal,
        }


@dataclass(frozen=True, slots=True)
class RequirementObligation:
    requirement_id: str
    kind: ObligationKind
    canonical_text: str
    applicability: ObligationApplicability

    def __post_init__(self) -> None:
        _identifier(self.requirement_id, "requirement_id")
        if self.kind not in _OBLIGATION_KINDS:
            raise RequirementObligationError("obligation kind is invalid")
        if not self.canonical_text.strip():
            raise RequirementObligationError("obligation canonical_text must be non-empty")

    @property
    def canonical_text_digest(self) -> str:
        return _digest(self.canonical_text)

    @property
    def obligation_id(self) -> str:
        return _digest(
            {
                "format": "requirement-obligation/1",
                "requirement_id": self.requirement_id,
                "kind": self.kind,
                "canonical_text_digest": self.canonical_text_digest,
                "applicability_handle": self.applicability.to_document(),
            }
        )

    def to_document(self) -> JSONObject:
        return {
            "obligation_id": self.obligation_id,
            "requirement_id": self.requirement_id,
            "kind": self.kind,
            "canonical_text_digest": self.canonical_text_digest,
            "applicability_handle": self.applicability.to_document(),
        }

    def to_clause_document(self) -> JSONObject:
        return {
            "obligation_id": self.obligation_id,
            "canonical_text": self.canonical_text,
            "canonical_text_digest": self.canonical_text_digest,
            "applicability_handle": self.applicability.to_document(),
        }


def applicability_from_document(value: Any) -> ObligationApplicability:
    keys = {
        "kind",
        "case_id",
        "capability_id",
        "condition_id",
        "branch",
        "facet_name",
        "operator",
        "public_literal",
    }
    document = _exact(value, keys, "applicability handle")
    return ObligationApplicability(
        kind=cast(ApplicabilityKind, _string(document["kind"], "applicability kind")),
        case_id=_optional_string(document["case_id"], "case_id"),
        capability_id=_optional_string(document["capability_id"], "capability_id"),
        condition_id=_optional_string(document["condition_id"], "condition_id"),
        branch=cast(
            ConditionBranch | None,
            _optional_string(document["branch"], "condition branch"),
        ),
        facet_name=_optional_string(document["facet_name"], "facet_name"),
        operator=cast(
            FacetOperator | None,
            _optional_string(document["operator"], "facet operator"),
        ),
        public_literal=cast(JSONValue | None, document["public_literal"]),
    )


def requirement_obligation_from_clause(
    *,
    requirement_id: str,
    kind: ObligationKind,
    value: Any,
) -> RequirementObligation:
    document = _exact(
        value,
        {
            "obligation_id",
            "canonical_text",
            "canonical_text_digest",
            "applicability_handle",
        },
        "Requirement obligation clause",
    )
    obligation = RequirementObligation(
        requirement_id=requirement_id,
        kind=kind,
        canonical_text=_string(document["canonical_text"], "obligation canonical_text"),
        applicability=applicability_from_document(document["applicability_handle"]),
    )
    if document["canonical_text_digest"] != obligation.canonical_text_digest:
        raise RequirementObligationError("obligation canonical text digest mismatch")
    if document["obligation_id"] != obligation.obligation_id:
        raise RequirementObligationError("obligation identity mismatch")
    return obligation


def background_clause_document(canonical_text: str) -> JSONObject:
    if not canonical_text.strip():
        raise RequirementObligationError("background clause text must be non-empty")
    return {
        "obligation_id": None,
        "canonical_text": canonical_text,
        "canonical_text_digest": _digest(canonical_text),
        "applicability_handle": None,
    }


def requirement_obligations_from_expected_document(
    value: Any,
) -> tuple[RequirementObligation, ...]:
    root = _exact(
        value,
        {"format", "requirements", "capabilities", "composition_rules", "conditions"},
        "Expected TaskSemantics",
    )
    if root["format"] != "expected-task-semantics/2":
        raise RequirementObligationError(
            "Expected TaskSemantics format must be expected-task-semantics/2"
        )
    requirements = root["requirements"]
    if not isinstance(requirements, list):
        raise RequirementObligationError("Expected TaskSemantics requirements must be an array")

    obligations: list[RequirementObligation] = []
    for raw_requirement in requirements:
        requirement = _exact(
            raw_requirement,
            {
                "requirement_id",
                "disposition",
                "rationale",
                "preconditions",
                "outcomes",
                "refusals",
                "collateral_constraints",
                "process_constraints",
                "workflow_ids",
            },
            "Expected Requirement",
        )
        requirement_id = _string(requirement["requirement_id"], "requirement_id")
        taskable = requirement["disposition"] == "Taskable"
        for field, kind in _CLAUSE_KINDS.items():
            clauses = requirement[field]
            if not isinstance(clauses, list):
                raise RequirementObligationError(f"Requirement {field} must be an array")
            for clause in clauses:
                if taskable:
                    obligations.append(
                        requirement_obligation_from_clause(
                            requirement_id=requirement_id,
                            kind=kind,
                            value=clause,
                        )
                    )
                    continue
                document = _exact(
                    clause,
                    {
                        "obligation_id",
                        "canonical_text",
                        "canonical_text_digest",
                        "applicability_handle",
                    },
                    "background Requirement clause",
                )
                expected = background_clause_document(
                    _string(document["canonical_text"], "background canonical_text")
                )
                if document != expected:
                    raise RequirementObligationError(
                        "non-Taskable Requirement clause must not carry an obligation"
                    )
    ids = tuple(item.obligation_id for item in obligations)
    if len(ids) != len(set(ids)):
        raise RequirementObligationError("Requirement obligation identities must be unique")
    return tuple(sorted(obligations, key=lambda item: item.obligation_id))


def _digest(value: Any) -> str:
    try:
        payload = rfc8785.dumps(value)
    except (TypeError, ValueError) as exc:
        raise RequirementObligationError("obligation identity value is not canonical JSON") from exc
    return hashlib.sha256(payload).hexdigest()


def _exact(value: Any, keys: set[str], role: str) -> dict[str, Any]:
    if not is_json_object(value) or set(value) != keys:
        raise RequirementObligationError(f"{role} has invalid fields")
    return cast(dict[str, Any], value)


def _string(value: Any, role: str) -> str:
    if not isinstance(value, str):
        raise RequirementObligationError(f"{role} must be a string")
    return value


def _optional_string(value: Any, role: str) -> str | None:
    return None if value is None else _string(value, role)


def _identifier(value: str, role: str) -> None:
    if not value or value.strip() != value or any(character.isspace() for character in value):
        raise RequirementObligationError(f"{role} must be a non-empty whitespace-free string")


__all__ = [
    "ApplicabilityKind",
    "ConditionBranch",
    "FacetOperator",
    "ObligationApplicability",
    "ObligationKind",
    "RequirementObligation",
    "RequirementObligationError",
    "applicability_from_document",
    "background_clause_document",
    "requirement_obligation_from_clause",
    "requirement_obligations_from_expected_document",
]

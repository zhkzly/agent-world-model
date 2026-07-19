"""Safe cross-component validation diagnostics and monotonic repair frontiers.

Raw exception text is not a control-plane contract: it may contain rejected
model values, filesystem paths, credentials, or Judge-private identifiers.  A
component therefore translates failures into this framework-authored record
before asking the global RepairLedger for another real Agent turn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError

ValidationOwner = Literal["design", "verifier", "build", "judge"]

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_SAFE_LOCATION_PART = re.compile(r"[^A-Za-z0-9_-]")
_SAFE_PYDANTIC_MESSAGES = {
    "assumption_needs_human_payload_forbidden": (
        "Set both claim and fidelity to null for needs_human."
    ),
    "assumption_closure_payload_required": (
        "Provide both claim and fidelity for a closed assumption."
    ),
    "assumption_claim_disposition_mismatch": (
        "Use the claim kind/status required by the selected disposition."
    ),
    "assumption_fidelity_level_mismatch": (
        "Use the fidelity level required by the selected disposition."
    ),
    "assumption_fidelity_claim_missing": (
        "Include the new closure claim id in fidelity evidence_claim_ids."
    ),
    "assumption_known_divergence_required": (
        "Provide a non-empty known_divergence for bounded_out_of_scope."
    ),
    "rule_constant_any_forbidden": "Use one concrete JSON value_type for a constant.",
    "rule_constant_type_mismatch": "The constant value must match its declared value_type.",
    "rule_constant_non_finite": "Rule constants must use finite JSON numbers.",
    "rule_arithmetic_operand_type": "Arithmetic operands must declare number value_type.",
    "rule_arithmetic_zero_divisor": "Division and modulo cannot use a constant zero divisor.",
    "rule_unary_clause_shape": "Unary clauses cannot carry right, json_schema, or ordering.",
    "rule_schema_clause_shape": "schema_valid requires only a non-empty json_schema operand.",
    "rule_schema_empty": "schema_valid cannot use the tautological empty JSON Schema.",
    "rule_schema_invalid": "Provide a valid Draft 2020-12 JSON Schema.",
    "rule_binary_clause_shape": "Binary clauses require right and cannot carry json_schema.",
    "rule_ordering_required": "Ordered comparisons require an explicit ordering domain.",
    "rule_ordering_type_mismatch": "Ordered terms must match the declared ordering domain.",
    "rule_ordering_forbidden": "This clause operator cannot carry an ordering domain.",
    "rule_contains_left_not_container": (
        "Contains requires an array, object, string, or any left term."
    ),
    "rule_clause_id_duplicate": "Every clause_id inside one Rule must be unique.",
    "rule_pointer_not_absolute": "Use an empty pointer or an absolute RFC 6901 pointer.",
    "rule_pointer_limit": "Keep the RFC 6901 pointer within framework limits.",
    "rule_pointer_escape": "Use only ~0 and ~1 RFC 6901 escape sequences.",
}
_GENERIC_NON_ACTIONABLE_CODES = frozenset(
    {
        "semantic_contract_violation",
        "schema_validation_error",
        "schema_value_error",
        "schema_value_error_root",
        "validation_error",
        "framework_diagnostic_incomplete",
    }
)
_SAFE_EXPECTED_CATEGORIES = {
    "missing": "a required field matching the closed output schema",
    "string_type": "a string value",
    "int_type": "an integer value",
    "float_type": "a numeric value",
    "bool_type": "a boolean value",
    "list_type": "an array value",
    "tuple_type": "an array with the declared fixed shape",
    "dict_type": "an object value",
    "literal_error": "one of the closed literal alternatives",
    "enum": "one of the closed enum alternatives",
    "extra_forbidden": "only fields declared by the closed output schema",
    "rule_constant_any_forbidden": "a concrete JSON value_type",
    "rule_constant_type_mismatch": "a constant matching its declared JSON value_type",
    "rule_constant_non_finite": "a finite JSON number",
    "rule_arithmetic_operand_type": "number-typed arithmetic operands",
    "rule_arithmetic_zero_divisor": "a non-zero constant divisor",
    "rule_unary_clause_shape": "the closed unary clause shape",
    "rule_schema_clause_shape": "the closed schema_valid clause shape",
    "rule_schema_empty": "a non-empty JSON Schema",
    "rule_schema_invalid": "a valid Draft 2020-12 JSON Schema",
    "rule_binary_clause_shape": "the closed binary clause shape",
    "rule_ordering_required": "one explicit number, date, or date-time ordering",
    "rule_ordering_type_mismatch": "terms compatible with the ordering domain",
    "rule_ordering_forbidden": "no ordering field for this operator",
    "rule_contains_left_not_container": "an array, object, string, or any left term",
    "rule_clause_id_duplicate": "unique clause_id values within the Rule",
    "rule_pointer_not_absolute": "an empty or absolute RFC 6901 pointer",
    "rule_pointer_limit": "an RFC 6901 pointer within framework limits",
    "rule_pointer_escape": "valid RFC 6901 escape sequences",
}


@dataclass(frozen=True, slots=True)
class SafeValidationIssue:
    """One non-secret, field-addressable issue authored by framework code."""

    code: str
    location: tuple[str | int, ...]
    message: str
    retryable: bool = True
    violated_condition: str | None = None
    expected_category: str | None = None

    def __post_init__(self) -> None:
        if _SAFE_IDENTIFIER.fullmatch(self.code) is None:
            raise ValueError("validation issue code must be a safe identifier")
        if not self.location:
            raise ValueError("validation issue location cannot be empty")
        if not self.message or len(self.message) > 512:
            raise ValueError("validation issue message must contain at most 512 characters")
        for field_name, value in (
            ("violated_condition", self.violated_condition),
            ("expected_category", self.expected_category),
        ):
            if value is not None and (not value or len(value) > 512):
                raise ValueError(f"{field_name} must contain at most 512 characters")

    @property
    def issue_code(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"{self.code}@{location}"[:320]

    @property
    def feedback(self) -> str:
        location = ".".join(str(part) for part in self.location)
        detail = f"- {self.code} at {location}: {self.message}"
        if self.violated_condition is not None:
            detail += f" Violated condition: {self.violated_condition}."
        if self.expected_category is not None:
            detail += f" Expected: {self.expected_category}."
        return detail

    @property
    def actionable_for_agent(self) -> bool:
        """Whether this issue can safely justify spending a semantic repair turn.

        Precise legacy framework issues remain actionable while validators migrate
        to explicit condition/expectation fields.  Generic catch-all identities do
        not become actionable merely because they carry a field path.
        """

        return self.retryable and self.code not in _GENERIC_NON_ACTIONABLE_CODES

    def persistence_projection(self) -> dict[str, object]:
        value: dict[str, object] = {
            "code": self.code,
            "location": list(self.location),
            "message": self.message,
            "retryable": self.retryable,
        }
        if self.violated_condition is not None:
            value["violated_condition"] = self.violated_condition
        if self.expected_category is not None:
            value["expected_category"] = self.expected_category
        return value


@dataclass(frozen=True, slots=True)
class ValidationDiagnostic:
    """A complete issue set at one framework-owned validation frontier."""

    owner_component: ValidationOwner
    validation_phase: str
    frontier_ordinal: int
    issues: tuple[SafeValidationIssue, ...]

    def __post_init__(self) -> None:
        if _SAFE_IDENTIFIER.fullmatch(self.validation_phase) is None:
            raise ValueError("validation phase must be a safe identifier")
        if self.frontier_ordinal < 0:
            raise ValueError("validation frontier cannot be negative")
        if not self.issues:
            raise ValueError("validation diagnostic requires at least one issue")
        object.__setattr__(self, "issues", tuple(dict.fromkeys(self.issues)))

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(issue.issue_code for issue in self.issues)

    @property
    def feedback(self) -> str:
        visible = self.issues[:32]
        text = "\n".join(issue.feedback for issue in visible)
        omitted = len(self.issues) - len(visible)
        if omitted:
            text += f"\n- diagnostics_overflow at root: {omitted} additional safe issues"
        return text[:8_192]

    @property
    def actionable_for_agent(self) -> bool:
        """True only when every blocker has a specific repairable identity."""

        return all(issue.actionable_for_agent for issue in self.issues)

    def persistence_projection(self) -> dict[str, object]:
        return {
            "owner_component": self.owner_component,
            "validation_phase": self.validation_phase,
            "frontier_ordinal": self.frontier_ordinal,
            "issues": [issue.persistence_projection() for issue in self.issues],
        }


class StructuredValidationError(ValueError):
    """Raise one complete safe diagnostic set from a semantic validator."""

    def __init__(self, diagnostic: ValidationDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(diagnostic.feedback)


def pydantic_validation_diagnostic(
    exc: ValidationError,
    *,
    owner_component: ValidationOwner,
    validation_phase: str,
    frontier_ordinal: int,
) -> ValidationDiagnostic:
    """Translate Pydantic errors without copying rejected inputs or messages."""

    issues: list[SafeValidationIssue] = []
    for item in exc.errors(include_url=False, include_context=False, include_input=False)[:64]:
        raw_error_type = str(item.get("type", "invalid"))
        error_type = re.sub(r"[^A-Za-z0-9._:-]", "-", raw_error_type)
        location = tuple(
            part
            if isinstance(part, int)
            else (_SAFE_LOCATION_PART.sub("-", str(part))[:80] or "field")
            for part in item.get("loc", ())
        ) or ("root",)
        if raw_error_type in {"value_error", "assertion_error"}:
            issues.append(
                SafeValidationIssue(
                    code="framework_diagnostic_incomplete",
                    location=location,
                    message=(
                        "A semantic validator raised an untyped error; framework code must "
                        "provide a safe condition before an Agent can repair it."
                    ),
                    retryable=False,
                    violated_condition="the validator emitted no typed semantic issue",
                    expected_category="a StructuredValidationError with a stable safe issue",
                )
            )
            continue
        expected = _SAFE_EXPECTED_CATEGORIES.get(
            raw_error_type,
            "a value satisfying the named closed-schema constraint",
        )
        issue_code = error_type if raw_error_type.startswith("rule_") else f"schema_{error_type}"
        issues.append(
            SafeValidationIssue(
                code=issue_code[:160],
                location=location,
                message=_SAFE_PYDANTIC_MESSAGES.get(
                    raw_error_type,
                    "Value does not satisfy the closed structured-output schema at this field.",
                ),
                violated_condition=f"closed schema constraint {raw_error_type}",
                expected_category=expected,
            )
        )
    if not issues:
        issues.append(
            SafeValidationIssue(
                code="schema_validation_error",
                location=("root",),
                message=(
                    "Schema validation failed without a typed field error; framework code "
                    "must disclose a safe condition before repair."
                ),
                retryable=False,
                violated_condition="the schema engine emitted no field-addressable issue",
                expected_category="at least one typed closed-schema issue",
            )
        )
    return ValidationDiagnostic(
        owner_component=owner_component,
        validation_phase=validation_phase,
        frontier_ordinal=frontier_ordinal,
        issues=tuple(issues),
    )


__all__ = [
    "SafeValidationIssue",
    "StructuredValidationError",
    "ValidationDiagnostic",
    "ValidationOwner",
    "pydantic_validation_diagnostic",
]

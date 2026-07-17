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
}


@dataclass(frozen=True, slots=True)
class SafeValidationIssue:
    """One non-secret, field-addressable issue authored by framework code."""

    code: str
    location: tuple[str | int, ...]
    message: str
    retryable: bool = True

    def __post_init__(self) -> None:
        if _SAFE_IDENTIFIER.fullmatch(self.code) is None:
            raise ValueError("validation issue code must be a safe identifier")
        if not self.location:
            raise ValueError("validation issue location cannot be empty")
        if not self.message or len(self.message) > 512:
            raise ValueError("validation issue message must contain at most 512 characters")

    @property
    def issue_code(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"{self.code}@{location}"[:320]

    @property
    def feedback(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"- {self.code} at {location}: {self.message}"

    def persistence_projection(self) -> dict[str, object]:
        return {
            "code": self.code,
            "location": list(self.location),
            "message": self.message,
            "retryable": self.retryable,
        }


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
        issues.append(
            SafeValidationIssue(
                code=f"schema_{error_type}"[:160],
                location=location,
                message=_SAFE_PYDANTIC_MESSAGES.get(
                    raw_error_type,
                    "Value does not satisfy the closed structured-output schema at this field.",
                ),
            )
        )
    if not issues:
        issues.append(
            SafeValidationIssue(
                code="schema_validation_error",
                location=("root",),
                message="Structured output does not satisfy the closed schema.",
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

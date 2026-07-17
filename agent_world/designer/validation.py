"""Safe, field-addressable semantic feedback for structured Designer outputs.

Pydantic owns shape validation.  Framework semantic validators use these types
when they need to report several cross-reference failures at once.  The issue
contract deliberately contains only framework-authored codes, paths and
messages; rejected model values are never copied into durable feedback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SAFE_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


@dataclass(frozen=True, slots=True)
class StructuredSemanticIssue:
    """One safe semantic contract failure at an exact output field."""

    code: str
    location: tuple[str | int, ...]
    message: str

    def __post_init__(self) -> None:
        if _SAFE_CODE.fullmatch(self.code) is None:
            raise ValueError("semantic issue code must be a safe identifier")
        if not self.location:
            raise ValueError("semantic issue location cannot be empty")
        if not self.message or len(self.message) > 512:
            raise ValueError("semantic issue message must contain at most 512 characters")

    @property
    def issue_code(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"{self.code}@{location}"[:320]

    @property
    def feedback(self) -> str:
        location = ".".join(str(part) for part in self.location)
        return f"- {self.code} at {location}: {self.message}"


class StructuredSemanticError(ValueError):
    """Aggregate independent semantic failures so one repair can fix them all."""

    def __init__(self, issues: tuple[StructuredSemanticIssue, ...]) -> None:
        if not issues:
            raise ValueError("structured semantic error requires at least one issue")
        self.issues = tuple(dict.fromkeys(issues))
        visible = self.issues[:32]
        omitted = len(self.issues) - len(visible)
        message = "\n".join(issue.feedback for issue in visible)
        if omitted:
            message += f"\n- diagnostics_overflow at <root>: {omitted} additional safe issues"
        super().__init__(message[:8_192])


__all__ = ["StructuredSemanticError", "StructuredSemanticIssue"]

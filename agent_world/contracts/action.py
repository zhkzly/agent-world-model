"""Neutral, closed Runtime action contract shared by verifier and reachability."""

from __future__ import annotations

from pydantic import Field, JsonValue, model_validator

from .base import Identifier, NonEmptyStr, V2Contract

_EVALUATOR_ONLY_KEYS = frozenset(
    {
        "case_id",
        "case_label",
        "evaluator_goal",
        "expected_answer",
        "expected_state",
        "framework_private",
        "release_decision",
        "verifier_ir",
    }
)


def reject_evaluator_only_values(value: JsonValue) -> None:
    """Reject framework-private authority recursively at the Runtime boundary."""

    if isinstance(value, dict):
        for key, child in value.items():
            if key.strip().lower() in _EVALUATOR_ONLY_KEYS:
                raise ValueError(f"evaluator-only field cannot cross Runtime boundary: {key}")
            reject_evaluator_only_values(child)
    elif isinstance(value, list):
        for child in value:
            reject_evaluator_only_values(child)


class RuntimeAction(V2Contract):
    tool_id: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    idempotency_key: NonEmptyStr | None = None

    @model_validator(mode="after")
    def reject_evaluator_values(self) -> RuntimeAction:
        reject_evaluator_only_values(self.arguments)
        return self

    def runtime_payload(self, *, generated_idempotency_key: NonEmptyStr) -> dict[str, JsonValue]:
        return {
            "tool": self.tool_id,
            "args": self.arguments,
            "idempotency_key": self.idempotency_key or generated_idempotency_key,
        }


__all__ = ["RuntimeAction", "reject_evaluator_only_values"]

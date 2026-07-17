"""Portable framework validation of one WorldSpec tool execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import JsonValue

from agent_world.contracts import Rule, ToolContract, WorldSpec

from .rules import RuleExecutionContext, evaluate_rule


class ToolSemanticValidationError(ValueError):
    """Observed Runtime behavior violated the portable WorldSpec."""


@dataclass(frozen=True, slots=True)
class ToolExecutionEvidence:
    response_ok: bool
    result_present: bool
    error_code: str | None
    error_message: str | None
    error_details: Mapping[str, JsonValue]
    pre_state_digest: str
    post_state_digest: str


def validate_tool_execution(
    *,
    world_spec: WorldSpec,
    rules: Mapping[str, Rule],
    tool: ToolContract,
    context: RuleExecutionContext,
    evidence: ToolExecutionEvidence,
) -> None:
    """Apply schemas, permissions, errors, transitions, and invariants fail-closed."""

    def require_true(rule_set: tuple[Rule, ...], label: str) -> None:
        failed = [
            rule.rule_id
            for rule in rule_set
            if not evaluate_rule(rules[rule.rule_id], context).result
        ]
        if failed:
            raise ToolSemanticValidationError(
                f"{tool.surface.tool_id} violates {label} Rules: {sorted(failed)}"
            )

    if tuple(Draft202012Validator(tool.surface.input_schema).iter_errors(context.args)):
        raise ToolSemanticValidationError(
            f"{tool.surface.tool_id} arguments violate its WorldSpec schema"
        )
    _reject_redacted_fields(
        context.observation,
        frozenset(tool.semantics.observation.redacted_fields_by_actor[context.actor]),
    )
    if evidence.response_ok:
        if evidence.error_code is not None:
            raise ToolSemanticValidationError("successful Runtime response contains an error")
        if tuple(Draft202012Validator(tool.surface.output_schema).iter_errors(context.tool_result)):
            raise ToolSemanticValidationError(
                f"{tool.surface.tool_id} tool_result violates its WorldSpec schema"
            )

    condition = tool.semantics.permission.condition
    condition_allowed = (
        True if condition is None else evaluate_rule(rules[condition.rule_id], context).result
    )
    permission_allowed = (
        context.actor in tool.semantics.permission.allowed_actors and condition_allowed
    )
    if not permission_allowed:
        if evidence.response_ok or evidence.error_code != "permission_denied":
            raise ToolSemanticValidationError(
                f"{tool.surface.tool_id} did not enforce its framework-computed permission"
            )
        if evidence.error_message != tool.semantics.permission.denied_observation:
            raise ToolSemanticValidationError(
                f"{tool.surface.tool_id} permission denial differs from WorldSpec"
            )
        if evidence.error_details:
            raise ToolSemanticValidationError("permission denial disclosed unmodeled error details")
        retryable = context.error.get("retryable") if isinstance(context.error, dict) else None
        if retryable is not False:
            raise ToolSemanticValidationError("permission denial must not be retryable")
        if evidence.pre_state_digest != evidence.post_state_digest:
            raise ToolSemanticValidationError("permission denial changed program state")
        require_true(tuple(world_spec.invariants), "invariant")
        return

    if evidence.error_code == "permission_denied":
        raise ToolSemanticValidationError(
            f"{tool.surface.tool_id} denied a framework-authorized actor {context.actor}"
        )
    if evidence.error_code is not None:
        declared = {item.error_code: item for item in tool.semantics.errors}
        error = declared.get(evidence.error_code)
        if error is None:
            raise ToolSemanticValidationError(
                f"Runtime emitted undeclared error {evidence.error_code} for {tool.surface.tool_id}"
            )
        if not evidence.result_present:
            raise ToolSemanticValidationError(
                "failed invoke omitted its observation/reward result envelope"
            )
        if evidence.error_message != error.observation:
            raise ToolSemanticValidationError(
                f"Runtime error {evidence.error_code} observation differs from WorldSpec"
            )
        if evidence.error_details:
            raise ToolSemanticValidationError("Runtime error disclosed unmodeled details")
        error_retryable = bool(
            context.error.get("retryable") if isinstance(context.error, dict) else False
        )
        if error.retryable is not error_retryable:
            raise ToolSemanticValidationError("Runtime error retryability differs from WorldSpec")
        state_changed = evidence.pre_state_digest != evidence.post_state_digest
        if error.state_effect in {"none", "rolled_back"} and state_changed:
            raise ToolSemanticValidationError("error promised no effect/rollback but state changed")
        if error.state_effect == "partial" and not state_changed:
            raise ToolSemanticValidationError(
                "error promised an observable partial effect but state did not change"
            )
        if evidence.error_code in tool.semantics.rollback.rollback_trigger_codes and state_changed:
            raise ToolSemanticValidationError(
                "rollback trigger did not restore the pre-action state"
            )
        if not evaluate_rule(rules[error.when.rule_id], context).result:
            raise ToolSemanticValidationError(
                f"Runtime emitted {evidence.error_code} while its declared Rule is false"
            )
    elif not evidence.response_ok:
        raise ToolSemanticValidationError("Runtime failed without a declared error code")
    else:
        require_true(tuple(tool.semantics.preconditions), "precondition")
        if condition is not None:
            require_true((condition,), "permission")
        require_true(tuple(tool.semantics.transition), "transition")
        require_true(tuple(tool.semantics.postconditions), "postcondition")

    require_true(tuple(world_spec.invariants), "invariant")


def _reject_redacted_fields(value: Any, redacted: frozenset[str]) -> None:
    if isinstance(value, dict):
        leaked = redacted & set(value)
        if leaked:
            raise ToolSemanticValidationError(
                f"Runtime observation disclosed redacted fields: {sorted(leaked)}"
            )
        for child in value.values():
            _reject_redacted_fields(child, redacted)
    elif isinstance(value, list):
        for child in value:
            _reject_redacted_fields(child, redacted)


__all__ = [
    "ToolExecutionEvidence",
    "ToolSemanticValidationError",
    "validate_tool_execution",
]

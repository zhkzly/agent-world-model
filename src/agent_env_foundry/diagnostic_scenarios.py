"""Task-free diagnostic scenarios authored by Builder and executed by Host."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.environment import JSONObject
from agent_env_foundry.jsonvalue import is_json_object

DIAGNOSTIC_SCENARIOS_PATH = Path("docs/conformance/scenarios.json")
DIAGNOSTIC_FORMAT = "environment-diagnostics/1"
StateEffect = Literal["changed", "unchanged"]

_DOCUMENT_KEYS = frozenset({"format", "scenarios"})
_SCENARIO_KEYS = frozenset({"scenario_id", "reset", "steps"})
_STEP_KEYS = frozenset({"tool", "arguments", "expected_ok", "state_effect", "expected_error_code"})
_SCENARIO_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class DiagnosticContractError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DiagnosticStep:
    tool: str
    arguments: JSONObject
    expected_ok: bool
    state_effect: StateEffect
    expected_error_code: str | None

    def to_document(self) -> JSONObject:
        return {
            "tool": self.tool,
            "arguments": _json_copy(self.arguments),
            "expected_ok": self.expected_ok,
            "state_effect": self.state_effect,
            "expected_error_code": self.expected_error_code,
        }


@dataclass(frozen=True, slots=True)
class DiagnosticScenario:
    scenario_id: str
    reset: JSONObject | None
    steps: tuple[DiagnosticStep, ...]

    def to_document(self) -> JSONObject:
        return {
            "scenario_id": self.scenario_id,
            "reset": _json_copy(self.reset) if self.reset is not None else None,
            "steps": [step.to_document() for step in self.steps],
        }


@dataclass(frozen=True, slots=True)
class DiagnosticSuite:
    format: str
    scenarios: tuple[DiagnosticScenario, ...]

    def to_document(self) -> JSONObject:
        return {
            "format": self.format,
            "scenarios": [scenario.to_document() for scenario in self.scenarios],
        }


def parse_diagnostic_suite(
    document: Any,
    *,
    tool_names: tuple[str, ...],
) -> DiagnosticSuite:
    """Decode exact diagnostic cases and require success coverage for every tool."""

    if not is_json_object(document) or set(document) != _DOCUMENT_KEYS:
        raise DiagnosticContractError(
            f"diagnostic document must contain exactly {sorted(_DOCUMENT_KEYS)}"
        )
    if document["format"] != DIAGNOSTIC_FORMAT:
        raise DiagnosticContractError(f"diagnostic format must be {DIAGNOSTIC_FORMAT!r}")
    if not tool_names or len(set(tool_names)) != len(tool_names):
        raise DiagnosticContractError("diagnostic tool catalog must be non-empty and unique")
    raw_scenarios = document["scenarios"]
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise DiagnosticContractError("diagnostic scenarios must be a non-empty array")
    scenarios: list[DiagnosticScenario] = []
    scenario_ids: set[str] = set()
    success_tools: set[str] = set()
    refusal_count = 0
    changed_count = 0
    for position, raw_scenario in enumerate(raw_scenarios):
        if not isinstance(raw_scenario, dict) or set(raw_scenario) != _SCENARIO_KEYS:
            raise DiagnosticContractError(
                f"diagnostic scenario {position} must contain exactly {sorted(_SCENARIO_KEYS)}"
            )
        scenario_id = raw_scenario["scenario_id"]
        if (
            not isinstance(scenario_id, str)
            or _SCENARIO_ID.fullmatch(scenario_id) is None
            or scenario_id in scenario_ids
        ):
            raise DiagnosticContractError("diagnostic scenario IDs must be non-empty and unique")
        scenario_ids.add(scenario_id)
        reset = raw_scenario["reset"]
        if reset is not None and not is_json_object(reset):
            raise DiagnosticContractError(f"diagnostic scenario {scenario_id!r} reset is invalid")
        raw_steps = raw_scenario["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise DiagnosticContractError(
                f"diagnostic scenario {scenario_id!r} steps must be non-empty"
            )
        steps: list[DiagnosticStep] = []
        for step_position, raw_step in enumerate(raw_steps):
            step = _parse_step(raw_step, scenario_id=scenario_id, position=step_position)
            if step.tool not in tool_names:
                raise DiagnosticContractError(
                    f"diagnostic scenario {scenario_id!r} cites unknown tool {step.tool!r}"
                )
            if step.expected_ok:
                success_tools.add(step.tool)
            else:
                refusal_count += 1
            if step.state_effect == "changed":
                changed_count += 1
            steps.append(step)
        scenarios.append(
            DiagnosticScenario(
                scenario_id,
                _json_copy(reset) if reset is not None else None,
                tuple(steps),
            )
        )
    missing_success = set(tool_names) - success_tools
    if missing_success:
        raise DiagnosticContractError(
            f"diagnostic success coverage missing tools {sorted(missing_success)}"
        )
    if not refusal_count:
        raise DiagnosticContractError("diagnostic suite must contain a refusal case")
    if not changed_count:
        raise DiagnosticContractError("diagnostic suite must contain a changed-state success")
    return DiagnosticSuite(DIAGNOSTIC_FORMAT, tuple(scenarios))


def _parse_step(raw: Any, *, scenario_id: str, position: int) -> DiagnosticStep:
    if not isinstance(raw, dict) or set(raw) != _STEP_KEYS:
        raise DiagnosticContractError(
            f"diagnostic step {scenario_id!r}/{position} must contain exactly {sorted(_STEP_KEYS)}"
        )
    tool = raw["tool"]
    arguments = raw["arguments"]
    expected_ok = raw["expected_ok"]
    state_effect = raw["state_effect"]
    expected_error_code = raw["expected_error_code"]
    if not isinstance(tool, str) or not tool or not is_json_object(arguments):
        raise DiagnosticContractError(f"diagnostic step {scenario_id!r}/{position} is invalid")
    if not isinstance(expected_ok, bool) or state_effect not in {"changed", "unchanged"}:
        raise DiagnosticContractError(f"diagnostic step {scenario_id!r}/{position} is invalid")
    if expected_ok:
        if expected_error_code is not None:
            raise DiagnosticContractError("diagnostic success cannot declare an error code")
    else:
        if not isinstance(expected_error_code, str) or not expected_error_code:
            raise DiagnosticContractError("diagnostic refusal requires a stable error code")
        if expected_error_code.startswith("contract."):
            raise DiagnosticContractError("diagnostic refusal must use a domain error code")
        if state_effect != "unchanged":
            raise DiagnosticContractError("diagnostic refusal must declare unchanged state")
    return DiagnosticStep(
        tool,
        _json_copy(arguments),
        expected_ok,
        cast(StateEffect, state_effect),
        expected_error_code,
    )


def _json_copy(value: JSONObject) -> JSONObject:
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


__all__ = [
    "DIAGNOSTIC_FORMAT",
    "DIAGNOSTIC_SCENARIOS_PATH",
    "DiagnosticContractError",
    "DiagnosticScenario",
    "DiagnosticStep",
    "DiagnosticSuite",
    "parse_diagnostic_suite",
]

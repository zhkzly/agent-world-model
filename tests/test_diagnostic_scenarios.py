from __future__ import annotations

from copy import deepcopy

import pytest

from agent_env_foundry.diagnostic_scenarios import (
    DiagnosticContractError,
    parse_diagnostic_suite,
)


def _document() -> dict:
    return {
        "format": "environment-diagnostics/1",
        "scenarios": [
            {
                "scenario_id": "read-and-change",
                "reset": None,
                "steps": [
                    {
                        "tool": "inspect",
                        "arguments": {},
                        "expected_ok": True,
                        "state_effect": "unchanged",
                        "expected_error_code": None,
                    },
                    {
                        "tool": "increment",
                        "arguments": {"amount": 1},
                        "expected_ok": True,
                        "state_effect": "changed",
                        "expected_error_code": None,
                    },
                    {
                        "tool": "increment",
                        "arguments": {"amount": 0},
                        "expected_ok": False,
                        "state_effect": "unchanged",
                        "expected_error_code": "invalid_amount",
                    },
                ],
            }
        ],
    }


def test_diagnostic_suite_seals_success_refusal_effect_and_tool_coverage() -> None:
    suite = parse_diagnostic_suite(_document(), tool_names=("inspect", "increment"))

    assert suite.format == "environment-diagnostics/1"
    assert suite.scenarios[0].scenario_id == "read-and-change"
    assert suite.scenarios[0].steps[1].state_effect == "changed"
    assert suite.scenarios[0].steps[2].expected_error_code == "invalid_amount"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda document: document.update(extra=True), "exactly"),
        (
            lambda document: document["scenarios"][0].update(scenario_id="../escape"),
            "scenario IDs",
        ),
        (
            lambda document: document["scenarios"][0]["steps"][2].update(state_effect="changed"),
            "refusal",
        ),
        (
            lambda document: document["scenarios"][0]["steps"][2].update(expected_error_code=None),
            "error code",
        ),
        (
            lambda document: document["scenarios"][0]["steps"].__setitem__(
                2,
                {
                    "tool": "inspect",
                    "arguments": {},
                    "expected_ok": True,
                    "state_effect": "unchanged",
                    "expected_error_code": None,
                },
            ),
            "refusal",
        ),
        (
            lambda document: document["scenarios"][0]["steps"].__setitem__(
                1,
                {
                    "tool": "inspect",
                    "arguments": {},
                    "expected_ok": True,
                    "state_effect": "unchanged",
                    "expected_error_code": None,
                },
            ),
            "success coverage",
        ),
    ],
)
def test_diagnostic_suite_rejects_weak_or_ambiguous_cases(mutate, message: str) -> None:
    document = deepcopy(_document())
    mutate(document)

    with pytest.raises(DiagnosticContractError, match=message):
        parse_diagnostic_suite(document, tool_names=("inspect", "increment"))

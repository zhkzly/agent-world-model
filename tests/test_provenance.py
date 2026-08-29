from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.environment import ToolSpec
from agent_env_foundry.provenance import (
    ProvenanceError,
    resolve_argument_provenance,
    validate_argument_provenance,
)
from agent_env_foundry.semantics import TraceEvent


def _tools() -> tuple[ToolSpec, ...]:
    return (
        {
            "name": "submit",
            "description": "Submit an item.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "account_reference": {"type": "string"},
                    "charge_reference": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["account_reference", "charge_reference", "reason"],
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
        },
        {
            "name": "inspect",
            "description": "Inspect an item.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "dispute_reference": {"type": "string"},
                    "mode": {"type": "string", "enum": ["full"]},
                },
                "required": ["dispute_reference", "mode"],
                "additionalProperties": False,
            },
            "output_schema": {"type": "object"},
        },
    )


def test_resolves_every_argument_leaf_to_an_exact_public_occurrence() -> None:
    trace = (
        TraceEvent(
            1,
            "submit",
            {
                "account_reference": "ACC-1",
                "charge_reference": "CHG-1",
                "reason": "incorrect charge",
            },
            {
                "ok": True,
                "data": {"dispute_reference": "DSP-1"},
                "error": None,
            },
        ),
        TraceEvent(
            2,
            "inspect",
            {"dispute_reference": "DSP-1", "mode": "full"},
            {"ok": True, "data": {"status": "submitted"}, "error": None},
        ),
    )

    provenance = resolve_argument_provenance(
        trace=trace,
        instruction_values={"charge_reference": "CHG-1"},
        reset_observation={"account_reference": "ACC-1"},
        tool_specs=_tools(),
    )

    by_argument = {(item.event_seq, item.argument_pointer): item for item in provenance}
    assert by_argument[(1, "/charge_reference")].source_kind == "task_literal"
    assert by_argument[(1, "/account_reference")].source_kind == "reset"
    assert by_argument[(1, "/reason")].source_kind == "agent_choice"
    dynamic = by_argument[(2, "/dispute_reference")]
    assert (dynamic.source_kind, dynamic.source_event_seq, dynamic.source_pointer) == (
        "tool_observation",
        1,
        "/data/dispute_reference",
    )
    constant = by_argument[(2, "/mode")]
    assert (constant.source_kind, constant.source_tool_name, constant.source_pointer) == (
        "tool_schema_constant",
        "inspect",
        "/mode",
    )
    validate_argument_provenance(trace, provenance)

    with pytest.raises(ProvenanceError, match="cover every argument leaf"):
        validate_argument_provenance(trace, provenance[:-1])


def test_failure_error_text_is_not_a_tool_observation_source() -> None:
    trace = (
        TraceEvent(
            1,
            "submit",
            {
                "account_reference": "ACC-1",
                "charge_reference": "CHG-1",
                "reason": "incorrect charge",
            },
            {
                "ok": False,
                "data": None,
                "error": {"code": "rejected", "message": "DSP-HIDDEN"},
            },
        ),
        TraceEvent(
            2,
            "inspect",
            {"dispute_reference": "DSP-HIDDEN", "mode": "full"},
            {"ok": True, "data": {"status": "missing"}, "error": None},
        ),
    )
    provenance = resolve_argument_provenance(
        trace=trace,
        instruction_values={"charge_reference": "CHG-1"},
        reset_observation={"account_reference": "ACC-1"},
        tool_specs=_tools(),
    )
    hidden = next(
        item
        for item in provenance
        if item.event_seq == 2 and item.argument_pointer == "/dispute_reference"
    )
    assert hidden.source_kind == "agent_choice"

    forged = replace(
        hidden,
        source_kind="tool_observation",
        source_event_seq=1,
        source_tool_name="submit",
        source_pointer="/error/message",
    )
    with pytest.raises(ProvenanceError):
        validate_argument_provenance(trace, (*provenance[:-2], forged, provenance[-1]))

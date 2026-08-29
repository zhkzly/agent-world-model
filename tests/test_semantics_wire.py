from __future__ import annotations

from copy import deepcopy

from agent_env_foundry.semantics import (
    atom_result_from_document,
    binding_from_document,
    capability_from_document,
    condition_result_from_document,
    start_case_from_document,
)
from agent_env_foundry.semantics_wire import (
    semantics_wire_document,
    validate_semantics_wire_items,
)


def test_wire_examples_pass_machine_schema_and_exact_host_decoders() -> None:
    wire = semantics_wire_document()
    examples = wire["examples"]

    assert not validate_semantics_wire_items("start_case", [examples["start_case"]])
    assert not validate_semantics_wire_items("capability", [examples["capability"]])
    assert not validate_semantics_wire_items("binding", [examples["binding"]])
    assert not validate_semantics_wire_items("atom_result", [examples["atom_result"]])
    assert not validate_semantics_wire_items("condition_result", [examples["condition_result"]])
    start_case_from_document(examples["start_case"])
    capability_from_document(examples["capability"])
    binding_from_document(examples["binding"])
    atom_result_from_document(examples["atom_result"])
    condition_result_from_document(examples["condition_result"])


def test_wire_schema_reports_all_nested_paths_in_one_pass() -> None:
    capability = deepcopy(semantics_wire_document()["examples"]["capability"])
    capability["conditions"] = [
        {
            "condition_id": "available",
            "public_label": "Available",
            "binding_scope": "selected_binding",
            "true_capability_ids": ["inspect-item"],
            "false_capability_ids": [],
            "report_field": "status",
            "public_source": {
                "kind": "reset",
                "tool_name": None,
                "json_pointer": "/items/0/available",
                "value": None,
            },
        }
    ]
    capability["answer_fields"] = ["value"]

    findings = validate_semantics_wire_items("capability", [capability])

    assert any("$[0]['answer_fields'][0]" in item for item in findings)
    assert any("$[0]['conditions'][0]['report_field']" in item for item in findings)

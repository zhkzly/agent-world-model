from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.conformance_v3 import (
    ConformanceContractError,
    conformance_receipt_from_document,
    make_conformance_receipt,
)
from agent_env_foundry.release import canonical_bytes, sha256_hex


def _receipt():
    return make_conformance_receipt(
        actor_project_digest="1" * 64,
        actor_factory="generated_environment.release:make_environment",
        state_reader_factory="generated_environment.release:read_state",
        start_schema={"type": "object"},
        reset_observation_schema={"type": "object"},
        state_schema={"type": "object"},
        tool_specs=(
            {
                "name": "inspect",
                "description": "Inspect public state.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
                "output_schema": {"type": "object"},
            },
        ),
        evidence={"format": "environment-conformance-evidence/3", "checks": ["passed"]},
    )


def test_conformance_receipt_binds_actor_schemas_tools_and_evidence() -> None:
    receipt = _receipt()

    assert receipt.format == "environment-conformance/3"
    assert receipt.verdict == "passed"
    assert receipt.receipt_id
    assert conformance_receipt_from_document(receipt.to_document()) == receipt
    assert receipt.actor_project_digest == "1" * 64
    assert receipt.start_schema_digest == sha256_hex(canonical_bytes({"type": "object"}))
    assert receipt.reset_observation_schema_digest == sha256_hex(
        canonical_bytes({"type": "object"})
    )
    assert receipt.state_schema_digest == sha256_hex(canonical_bytes({"type": "object"}))
    assert receipt.tool_catalog_digest == sha256_hex(
        canonical_bytes(
            {
                "tools": [
                    {
                        "name": "inspect",
                        "description": "Inspect public state.",
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "required": [],
                        },
                        "output_schema": {"type": "object"},
                    }
                ]
            }
        )
    )
    assert receipt.evidence_digest == sha256_hex(
        canonical_bytes({"format": "environment-conformance-evidence/3", "checks": ["passed"]})
    )

    for field in (
        "actor_project_digest",
        "start_schema_digest",
        "reset_observation_schema_digest",
        "state_schema_digest",
        "tool_catalog_digest",
        "evidence_digest",
    ):
        changed = replace(receipt, **{field: "0" * 64})
        assert changed.receipt_id != receipt.receipt_id


def test_conformance_receipt_rejects_extra_or_nonpassed_authority() -> None:
    document = _receipt().to_document()
    document["generated_verdict"] = True
    with pytest.raises(ConformanceContractError, match="exactly"):
        conformance_receipt_from_document(document)

    document = _receipt().to_document()
    document["verdict"] = "failed"
    with pytest.raises(ConformanceContractError, match="passed"):
        conformance_receipt_from_document(document)

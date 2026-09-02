from __future__ import annotations

import hashlib

import pytest
import rfc8785

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.release_v3_contract import (
    DESCRIPTOR_FORMAT_V3,
    descriptor_release_id_v3,
    parse_descriptor_v3,
    validate_payload_paths_v3,
)


def _descriptor() -> dict[str, str]:
    return {
        "format": DESCRIPTOR_FORMAT_V3,
        "canonicalization": "rfc8785",
        "hash": "sha256",
        "payload_manifest": "payload-manifest.json",
        "payload_digest": "1" * 64,
        "conformance": "conformance/receipt.json",
        "conformance_digest": "2" * 64,
        "actor_project": "actor",
        "actor_project_digest": "3" * 64,
        "actor_factory": "generated_environment.release:make_environment",
        "state_reader_factory": "generated_environment.release:read_state",
        "start_schema": "docs/schemas/start.json",
        "reset_observation_schema": "docs/schemas/reset.json",
        "state_schema": "docs/schemas/state.json",
    }


def test_v3_descriptor_binds_only_environment_authority() -> None:
    document = _descriptor()

    descriptor = parse_descriptor_v3(document)

    assert descriptor.format == "environment-release/3"
    assert descriptor.actor_project.as_posix() == "actor"
    assert descriptor.state_reader_factory.endswith(":read_state")
    assert descriptor.state_schema.as_posix() == "docs/schemas/state.json"
    assert descriptor_release_id_v3(document) == hashlib.sha256(rfc8785.dumps(document)).hexdigest()


@pytest.mark.parametrize(
    "old_field",
    (
        "semantics_project",
        "semantics_project_digest",
        "semantics_factory",
        "expected_semantics_digest",
        "qualified_catalog_digest",
        "qualified_start_cases_digest",
        "verifier_project_digest",
        "task_goals",
    ),
)
def test_v3_descriptor_rejects_old_task_authority_fields(old_field: str) -> None:
    document = _descriptor()
    document[old_field] = "old-authority"

    with pytest.raises(EnvironmentContractError, match="exactly"):
        parse_descriptor_v3(document)


@pytest.mark.parametrize(
    "field,value",
    (
        ("actor_project", "candidate"),
        ("start_schema", "schemas/start.json"),
        ("reset_observation_schema", "docs/reset.json"),
        ("state_schema", "docs/schemas/world.json"),
        ("conformance", "qualification/receipt.json"),
    ),
)
def test_v3_descriptor_requires_canonical_environment_paths(field: str, value: str) -> None:
    document = _descriptor()
    document[field] = value

    with pytest.raises(EnvironmentContractError, match=field):
        parse_descriptor_v3(document)


def test_v3_payload_rejects_task_semantics_and_unknown_roots() -> None:
    accepted = validate_payload_paths_v3(
        (
            "actor/pyproject.toml",
            "actor/uv.lock",
            "conformance/receipt.json",
            "conformance/evidence/reset.json",
            "docs/schemas/start.json",
            "docs/schemas/reset.json",
            "docs/schemas/state.json",
            "dist/environment.whl",
            "licenses/NOTICE",
            "payload-manifest.json",
            "release.json",
        )
    )
    assert len(accepted) == 11

    for prohibited in (
        "semantics/pyproject.toml",
        "qualification/verifier/pyproject.toml",
        "tasks/catalog.json",
        "checker/release.py",
        "world/task-semantics.json",
        "../escape",
    ):
        with pytest.raises(EnvironmentContractError, match="payload|path"):
            validate_payload_paths_v3((prohibited,))

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_env_foundry.conformance_v3 import make_conformance_receipt
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.release import canonical_bytes, compute_payload_digest, sha256_hex
from agent_env_foundry.release_v3 import (
    publish_release_v3_internal,
    verify_release_v3_internal,
)
from v3_release_factory import build_v3_release


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o644)


def _actor(root: Path) -> Path:
    _write(
        root / "pyproject.toml",
        """[project]
name = "fixture-environment"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
""",
    )
    _write(
        root / "uv.lock",
        """version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "fixture-environment"
version = "0.1.0"
source = { editable = "." }
""",
    )
    _write(
        root / "src/generated_environment/release.py",
        "def make_environment(path):\n    return object()\n\n"
        "def read_state(path):\n    return {'count': 0}\n",
    )
    return root


def _schemas() -> tuple[dict, dict, dict]:
    return (
        {"type": "object", "properties": {}, "additionalProperties": False},
        {"type": "object"},
        {
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
        },
    )


def _publish(tmp_path: Path):
    return build_v3_release(tmp_path), tmp_path / "actor-project"


def _publish_physical_only(tmp_path: Path):
    actor = _actor(tmp_path / "actor-project")
    actor_digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    start, reset, state = _schemas()
    tools = (
        {
            "name": "inspect",
            "description": "Inspect state.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "output_schema": {"type": "object"},
        },
    )
    evidence = {"format": "environment-conformance-evidence/3", "checks": ["passed"]}
    receipt = make_conformance_receipt(
        actor_project_digest=actor_digest,
        actor_factory="generated_environment.release:make_environment",
        state_reader_factory="generated_environment.release:read_state",
        start_schema=start,
        reset_observation_schema=reset,
        state_schema=state,
        tool_specs=tools,
        evidence=evidence,
    )
    released = publish_release_v3_internal(
        tmp_path / "EnvironmentRelease",
        actor_project=actor,
        receipt=receipt,
        evidence=evidence,
        start_schema=start,
        reset_observation_schema=reset,
        state_schema=state,
    )
    return released, actor


def test_internal_v3_publication_rejects_physical_only_self_evidence(
    tmp_path: Path,
) -> None:
    with pytest.raises(EnvironmentContractError, match="semantic qualification"):
        _publish_physical_only(tmp_path)


def test_internal_v3_publication_contains_no_task_authority(tmp_path: Path) -> None:
    released, _actor_root = _publish(tmp_path)
    verified = verify_release_v3_internal(released.root)

    assert verified.release_id == released.release_id
    assert verified.descriptor.format == "environment-release/3"
    assert verified.descriptor.actor_project.as_posix() == "actor"
    assert verified.receipt.verdict == "passed"
    paths = {record.path.as_posix() for record in verified.records}
    assert "docs/schemas/state.json" in paths
    assert "conformance/evidence/report.json" in paths
    assert not any(
        token in path
        for path in paths
        for token in ("semantics", "verifier", "task", "checker", "reward")
    )


def test_internal_v3_verifier_rejects_actor_schema_evidence_and_receipt_tamper(
    tmp_path: Path,
) -> None:
    released, _actor_root = _publish(tmp_path)
    actor_source = released.root / "actor/src/generated_environment/release.py"
    actor_source.write_text("TAMPERED = True\n")
    with pytest.raises(EnvironmentContractError, match="actor project digest|payload member"):
        verify_release_v3_internal(released.root)

    released, _actor_root = _publish(tmp_path / "schema-case")
    state_path = released.root / "docs/schemas/state.json"
    state_path.write_text(json.dumps({"type": "string"}))
    with pytest.raises(EnvironmentContractError, match="state_schema|payload member"):
        verify_release_v3_internal(released.root)

    released, _actor_root = _publish(tmp_path / "evidence-case")
    evidence_path = released.root / "conformance/evidence/report.json"
    evidence_path.write_text(json.dumps({"checks": ["tampered"]}))
    with pytest.raises(EnvironmentContractError, match="evidence|payload member"):
        verify_release_v3_internal(released.root)

    released, _actor_root = _publish(tmp_path / "receipt-case")
    receipt_path = released.root / "conformance/receipt.json"
    receipt_path.write_text("{}")
    with pytest.raises(EnvironmentContractError, match="conformance"):
        verify_release_v3_internal(released.root)


def test_internal_v3_verifier_rejects_extra_member_and_mode_drift(tmp_path: Path) -> None:
    released, _actor_root = _publish(tmp_path / "extra-case")
    extra = released.root / "actor/extra.py"
    extra.write_text("EXTRA = True\n")
    with pytest.raises(EnvironmentContractError, match="closure"):
        verify_release_v3_internal(released.root)

    released, _actor_root = _publish(tmp_path / "mode-case")
    actor_source = released.root / "actor/src/generated_environment/release.py"
    actor_source.chmod(0o600)
    with pytest.raises(EnvironmentContractError, match="mode"):
        verify_release_v3_internal(released.root)


def test_internal_v3_receipt_rejects_self_consistent_evidence_replacement(
    tmp_path: Path,
) -> None:
    released, _actor_root = _publish(tmp_path)
    evidence_path = released.root / "conformance/evidence/report.json"
    replacement = {"format": "environment-conformance-evidence/3", "checks": ["replaced"]}
    evidence_path.write_bytes(canonical_bytes(replacement))

    manifest_path = released.root / "payload-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for record in manifest["files"]:
        if record["path"] == "conformance/evidence/report.json":
            record["digest"] = sha256_hex(evidence_path.read_bytes())
            break
    manifest_path.write_bytes(canonical_bytes(manifest))
    descriptor_path = released.root / "release.json"
    descriptor = json.loads(descriptor_path.read_bytes())
    descriptor["payload_digest"] = compute_payload_digest(manifest)
    descriptor_path.write_bytes(canonical_bytes(descriptor))

    with pytest.raises(EnvironmentContractError, match="evidence digest"):
        verify_release_v3_internal(released.root)

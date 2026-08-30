from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from agent_env_foundry.builder import compute_candidate_digest
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.semantics_inputs import ViewFile
from agent_env_foundry.verifier_inputs import (
    ACTOR_VIEW_MANIFEST_NAME,
    ACTOR_VIEW_NAME,
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    QUALIFICATION_VERIFIER_CONTRACT_NAME,
    ActorViewManifest,
    PreparedVerifierAuthorWorkspace,
    VerifierInputError,
    prepare_verifier_author_workspace,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _surface() -> PublicSurfaceManifest:
    return PublicSurfaceManifest(
        start_schema={"type": "object"},
        reset_observation_schema={"type": "object"},
        tool_specs=(),
        public_documents_digest="b" * 64,
    )


def _workspace(tmp_path: Path) -> PreparedVerifierAuthorWorkspace:
    root = tmp_path / "verifier-author"
    root.mkdir()
    view = root / ACTOR_VIEW_NAME
    actor_source = view / "src/generated_environment/storage.py"
    actor_source.parent.mkdir(parents=True)
    actor_source.write_text("STATE_FILE = 'state.json'\n")
    actor_source.chmod(0o444)
    for directory in (actor_source.parent, actor_source.parent.parent, view / "src", view):
        directory.chmod(0o555)
    view_file = ViewFile(
        "src/generated_environment/storage.py",
        _sha(actor_source.read_bytes()),
    )
    manifest = ActorViewManifest("a" * 64, (view_file,), _sha(b"actor-view"))

    documents = {
        EXPECTED_TASK_SEMANTICS_NAME: {
            "format": "expected-task-semantics/1",
            "requirements": [],
            "capabilities": [],
            "composition_rules": [],
            "conditions": [],
        },
        PUBLIC_SURFACE_NAME: _surface().to_document(),
        ACTOR_VIEW_MANIFEST_NAME: manifest.to_document(),
    }
    input_digests: dict[str, str] = {}
    for name, document in documents.items():
        payload = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        input_digests[name] = _sha(payload)
    contract = root / QUALIFICATION_VERIFIER_CONTRACT_NAME
    contract.write_text("fixed verifier contract\n")
    contract.chmod(0o444)
    input_digests[QUALIFICATION_VERIFIER_CONTRACT_NAME] = _sha(contract.read_bytes())
    return PreparedVerifierAuthorWorkspace(root, input_digests, manifest)


def test_verifier_workspace_is_mutually_blind_and_immutable(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    workspace.verify_inputs()
    assert not (workspace.root / "TASK_SEMANTICS_PROJECT").exists()
    assert set(workspace.input_digests) == {
        EXPECTED_TASK_SEMANTICS_NAME,
        PUBLIC_SURFACE_NAME,
        QUALIFICATION_VERIFIER_CONTRACT_NAME,
        ACTOR_VIEW_MANIFEST_NAME,
    }

    expected = workspace.root / EXPECTED_TASK_SEMANTICS_NAME
    expected.chmod(0o644)
    expected.write_text("{}")
    with pytest.raises(VerifierInputError, match="changed after Host staging"):
        workspace.verify_inputs()


def test_verifier_workspace_rejects_view_members_or_modes_not_in_manifest(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    view = workspace.root / ACTOR_VIEW_NAME
    view.chmod(0o755)
    with pytest.raises(VerifierInputError, match="directories.*read-only"):
        workspace.verify_inputs()
    view.chmod(0o555)

    extra = view / "unexpected.py"
    view.chmod(0o755)
    extra.write_text("LEAK = True\n")
    extra.chmod(0o444)
    view.chmod(0o555)
    with pytest.raises(VerifierInputError, match="members differ"):
        workspace.verify_inputs()


def test_verifier_skill_and_contract_define_one_audit_only_role() -> None:
    root = Path(__file__).resolve().parents[1] / "src/agent_env_foundry/runtime_skills"
    skill = (root / "qualification-verifier-codegen/SKILL.md").read_text()
    contract = (
        root / "qualification-verifier-codegen/QUALIFICATION_VERIFIER_CONTRACT.md"
    ).read_text()
    combined = f"{skill}\n{contract}"
    assert "generated_qualification_verifier.release:make_verifier" in combined
    assert "verify_transition" in combined
    assert "`seq`, `tool_name`, `arguments`" in combined
    assert "required_effects_ok" in combined
    assert "collateral_ok" in combined
    assert "must not become a second public-answer" in combined
    assert "final answers" in combined
    assert "TaskSemantics source" in combined
    assert "must not" in combined
    assert "receipt" in combined
    assert "verdict" in combined
    assert "public_probe.py" not in combined
    assert "negative_setup.py" not in combined
    assert "native_probe.py" not in combined


def test_host_stages_actor_bytes_without_semantics_or_model_authored_metadata(
    tmp_path: Path,
) -> None:
    actor = tmp_path / "actor"
    (actor / "src/generated_environment").mkdir(parents=True)
    (actor / "pyproject.toml").write_text("[project]\nname='actor'\nversion='0.1.0'\n")
    (actor / "uv.lock").write_text("version = 1\n")
    (actor / "src/generated_environment/storage.py").write_text("STATE='state.json'\n")
    actor_digest = compute_candidate_digest(actor)
    expected = b'{"format":"expected-task-semantics/1"}'
    prepared = prepare_verifier_author_workspace(
        tmp_path / "prepared",
        actor_root=actor,
        actor_digest=actor_digest,
        expected_semantics_payload=expected,
        expected_semantics_digest=_sha(expected),
        public_surface=_surface(),
    )

    prepared.verify_inputs()
    assert json.loads((prepared.root / PUBLIC_SURFACE_NAME).read_text()) == (
        _surface().to_document()
    )
    assert (prepared.root / ACTOR_VIEW_NAME / "src/generated_environment/storage.py").is_file()
    assert not (prepared.root / ACTOR_VIEW_NAME / EXPECTED_TASK_SEMANTICS_NAME).exists()
    with pytest.raises(VerifierInputError, match="Actor project digest"):
        prepare_verifier_author_workspace(
            tmp_path / "bad-prepared",
            actor_root=actor,
            actor_digest="0" * 64,
            expected_semantics_payload=expected,
            expected_semantics_digest=_sha(expected),
            public_surface=_surface(),
        )

    with pytest.raises(VerifierInputError, match="public-surface/2"):
        prepare_verifier_author_workspace(
            tmp_path / "legacy-surface",
            actor_root=actor,
            actor_digest=actor_digest,
            expected_semantics_payload=expected,
            expected_semantics_digest=_sha(expected),
            public_surface=cast(Any, {"format": "public-surface/1"}),
        )

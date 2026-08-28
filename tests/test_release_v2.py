from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import rfc8785

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.release import verify_release_v2
from release_factory import build_release
from v2_release_factory import build_v2_release


def test_v2_descriptor_binds_actor_semantics_and_rejects_v1(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "v2")
    verified = verify_release_v2(root)
    assert verified.identity.format == "environment-release/2"
    assert verified.identity.release_id == verified.release_id
    assert verified.identity.actor_digest == verified.descriptor.actor_project_digest
    assert verified.identity.semantics_digest == verified.descriptor.semantics_project_digest

    v1 = build_release(tmp_path / "v1")
    v1_descriptor = json.loads((v1 / "release.json").read_text())
    (v1 / "release.json").write_bytes(rfc8785.dumps(v1_descriptor))
    with pytest.raises(EnvironmentContractError, match="environment-release/2"):
        verify_release_v2(v1)


def test_v2_tamper_mode_extra_member_and_symlink_fail_closed(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "content")
    (root / "actor/src/shared_actor/__init__.py").write_text("TAMPERED = True\n")
    with pytest.raises(EnvironmentContractError, match="digest mismatch"):
        verify_release_v2(root)

    root = build_v2_release(tmp_path / "mode")
    member = root / "semantics/src/shared_semantics/__init__.py"
    member.chmod(0o600)
    with pytest.raises(EnvironmentContractError, match="mode mismatch"):
        verify_release_v2(root)

    root = build_v2_release(tmp_path / "extra")
    (root / "actor/extra.py").write_text("EXTRA = True\n")
    with pytest.raises(EnvironmentContractError, match="unlisted|closure"):
        verify_release_v2(root)

    root = build_v2_release(tmp_path / "symlink")
    target = root / "actor/uv.lock"
    target.unlink()
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(EnvironmentContractError, match="symlink"):
        verify_release_v2(root)


def test_v2_descriptor_is_canonical_and_project_digest_is_independent(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "v2")
    descriptor = json.loads((root / "release.json").read_text())
    (root / "release.json").write_text(json.dumps(descriptor, indent=2))
    with pytest.raises(EnvironmentContractError, match="canonical"):
        verify_release_v2(root)

    first = build_v2_release(tmp_path / "first", behavior="first")
    second = build_v2_release(tmp_path / "second", behavior="second")
    left = verify_release_v2(first)
    right = verify_release_v2(second)
    assert left.release_id != right.release_id
    assert left.descriptor.actor_project_digest != right.descriptor.actor_project_digest
    assert stat.S_IMODE((first / "actor/uv.lock").stat().st_mode) == 0o644
    assert (
        rfc8785.dumps(json.loads((first / "release.json").read_text()))
        == (first / "release.json").read_bytes()
    )


def test_v2_project_and_qualification_bindings_fail_closed(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "project")
    descriptor = json.loads((root / "release.json").read_text())
    descriptor["actor_project_digest"] = "0" * 64
    (root / "release.json").write_bytes(rfc8785.dumps(descriptor))
    with pytest.raises(EnvironmentContractError, match="actor project digest"):
        verify_release_v2(root)

    root = build_v2_release(tmp_path / "qualification")
    (root / "qualification.json").write_bytes(
        rfc8785.dumps({"format": "environment-qualification/2", "verdict": "tampered"})
    )
    with pytest.raises(EnvironmentContractError, match="qualification digest"):
        verify_release_v2(root)

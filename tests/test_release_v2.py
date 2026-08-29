from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import rfc8785

import agent_env_foundry.preparation as preparation_module
import agent_env_foundry.release as release_module
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.release import (
    _verify_release_layout_v2,
    verify_release_v2,
    write_release_zip_v2,
)
from v2_release_factory import build_v2_release


def test_v2_descriptor_binds_actor_semantics_and_rejects_other_formats(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "v2")
    verified = _verify_release_layout_v2(root)
    assert verified.identity.format == "environment-release/2"
    assert verified.identity.release_id == verified.release_id
    assert verified.identity.actor_digest == verified.descriptor.actor_project_digest
    assert verified.identity.semantics_digest == verified.descriptor.semantics_project_digest

    descriptor = json.loads((root / "release.json").read_text())
    descriptor["format"] = "environment-release/unsupported"
    (root / "release.json").write_bytes(rfc8785.dumps(descriptor))
    with pytest.raises(EnvironmentContractError, match="environment-release/2"):
        _verify_release_layout_v2(root)


def test_product_admission_rejects_mechanical_fixture(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "mechanical")
    with pytest.raises(EnvironmentContractError, match="strict Qualification receipt"):
        verify_release_v2(root)


def test_layout_verifier_resolves_relative_release_root(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "relative")
    relative = Path(os.path.relpath(root, Path.cwd()))
    verified = _verify_release_layout_v2(relative)
    assert verified.root == root.resolve()
    assert verified.root.is_absolute()


def test_v2_tamper_mode_extra_member_and_symlink_fail_closed(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "content")
    (root / "actor/src/shared_actor/__init__.py").write_text("TAMPERED = True\n")
    with pytest.raises(EnvironmentContractError, match="digest mismatch"):
        _verify_release_layout_v2(root)

    root = build_v2_release(tmp_path / "mode")
    member = root / "semantics/src/shared_semantics/__init__.py"
    member.chmod(0o600)
    with pytest.raises(EnvironmentContractError, match="mode mismatch"):
        _verify_release_layout_v2(root)

    root = build_v2_release(tmp_path / "extra")
    (root / "actor/extra.py").write_text("EXTRA = True\n")
    with pytest.raises(EnvironmentContractError, match="unlisted|closure"):
        _verify_release_layout_v2(root)

    root = build_v2_release(tmp_path / "symlink")
    target = root / "actor/uv.lock"
    target.unlink()
    target.symlink_to(tmp_path / "outside")
    with pytest.raises(EnvironmentContractError, match="symlink"):
        _verify_release_layout_v2(root)


def test_v2_descriptor_is_canonical_and_project_digest_is_independent(tmp_path: Path) -> None:
    root = build_v2_release(tmp_path / "v2")
    descriptor = json.loads((root / "release.json").read_text())
    (root / "release.json").write_text(json.dumps(descriptor, indent=2))
    with pytest.raises(EnvironmentContractError, match="canonical"):
        _verify_release_layout_v2(root)

    first = build_v2_release(tmp_path / "first", behavior="first")
    second = build_v2_release(tmp_path / "second", behavior="second")
    left = _verify_release_layout_v2(first)
    right = _verify_release_layout_v2(second)
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
        _verify_release_layout_v2(root)

    root = build_v2_release(tmp_path / "qualification")
    (root / "qualification.json").write_bytes(
        rfc8785.dumps({"format": "environment-qualification/2", "verdict": "tampered"})
    )
    with pytest.raises(EnvironmentContractError, match="qualification digest"):
        _verify_release_layout_v2(root)


def test_release_zip_round_trip_preserves_empty_directory_and_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = tmp_path / "release"
    empty = release / "qualification/evidence/instances/native/.git/refs/tags"
    empty.mkdir(parents=True)
    empty.chmod(0o750)
    (release / "release.json").write_text("{}")
    monkeypatch.setattr(
        release_module,
        "verify_release_v2",
        lambda _path: SimpleNamespace(root=release),
    )

    archive = write_release_zip_v2(release, tmp_path / "release.zip")
    with zipfile.ZipFile(archive) as package:
        info = package.getinfo("qualification/evidence/instances/native/.git/refs/tags/")
        assert info.is_dir()
        assert stat.S_IMODE(info.external_attr >> 16) == 0o750

    monkeypatch.setattr(
        preparation_module,
        "verify_release_v2",
        lambda path: SimpleNamespace(root=Path(path)),
    )
    staged, ephemeral = preparation_module._stage_release(archive, tmp_path / "cache")
    restored = staged / "qualification/evidence/instances/native/.git/refs/tags"
    assert ephemeral is True
    assert restored.is_dir()
    assert stat.S_IMODE(restored.stat().st_mode) == 0o750

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agent_env_foundry.preparation_v3 import (
    PreparationExecutionErrorV3,
    PreparationSettingsV3,
    prepare_release_v3_internal,
)
from agent_env_foundry.release_v3 import write_release_zip_v3_internal
from v3_release_factory import build_v3_release


def _settings() -> PreparationSettingsV3:
    return PreparationSettingsV3(
        Path(os.environ.get("UV_CACHE_DIR", "/tmp/foundry-v3-runtime-uv-cache")),
        120.0,
    )


def test_internal_v3_directory_zip_relocation_and_protected_state(tmp_path: Path) -> None:
    release = build_v3_release(tmp_path / "source")
    archive = write_release_zip_v3_internal(release.root, tmp_path / "EnvironmentRelease.zip")
    relocated_archive = tmp_path / "relocated/release.zip"
    relocated_archive.parent.mkdir()
    shutil.copyfile(archive, relocated_archive)

    directory = prepare_release_v3_internal(
        release.root,
        tmp_path / "directory-cache",
        settings=_settings(),
    )
    zipped = prepare_release_v3_internal(
        relocated_archive,
        tmp_path / "zip-cache",
        settings=_settings(),
    )
    assert directory.identity == zipped.identity
    assert zipped.semantic_qualification.passed
    assert (
        zipped.identity.builder_projection_digest
        == zipped.semantic_qualification.builder_projection_digest
    )
    assert zipped.builder_projection.to_document()["requirements"][0]["id"] == "REQ-001"

    instance = tmp_path / "instance"
    with zipped.open(instance) as session:
        assert not hasattr(session, "trusted")
        assert not hasattr(session.actor, "read_state")
        assert not hasattr(session.actor, "builder_projection")
        assert session.actor.reset({"seed": 2}) == {"count": 2}
        assert session.actor.invoke("increment", {"amount": 3}) == {
            "ok": True,
            "data": {"count": 5},
            "error": None,
        }

    assert zipped.read_state(instance) == {"count": 5}
    assert len(zipped.state_events) == 2
    assert all(event.unchanged for event in zipped.state_events)
    with zipped.open(instance) as reopened:
        assert reopened.actor.tools()[0]["name"] == "increment"
    assert zipped.read_state(instance) == {"count": 5}


def test_internal_v3_prepared_actor_tamper_fails_before_open(tmp_path: Path) -> None:
    release = build_v3_release(tmp_path / "source")
    prepared = prepare_release_v3_internal(
        release.root,
        tmp_path / "cache",
        settings=_settings(),
    )
    source = (
        tmp_path
        / "cache/runtimes"
        / prepared.identity.release_id
        / "actor/project/src/generated_environment/release.py"
    )
    source.write_text("TAMPERED = True\n", encoding="utf-8")

    with pytest.raises(PreparationExecutionErrorV3) as caught:
        prepared.open(tmp_path / "instance")
    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "prepared_project_tampered"


def test_internal_v3_live_tools_must_match_host_receipt(tmp_path: Path) -> None:
    wrong_tools = (
        {
            "name": "different",
            "description": "A catalog the actor does not expose.",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        },
    )
    release = build_v3_release(tmp_path / "source", receipt_tools=wrong_tools)

    with pytest.raises(PreparationExecutionErrorV3) as caught:
        prepare_release_v3_internal(
            release.root,
            tmp_path / "cache",
            settings=_settings(),
        )
    assert caught.value.kind == "EnvironmentDefect"
    assert caught.value.code == "sealed_tool_catalog_mismatch"

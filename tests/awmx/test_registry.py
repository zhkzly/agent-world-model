from __future__ import annotations

import json
from pathlib import Path

import pytest

from awmx.artifacts.registry import ArtifactRegistry
from awmx.artifacts.schemas import ScenarioSpec, ValidationError


def _artifact_payload(**overrides):
    payload = {
        "id": "artifact.demo",
        "version": "0.1.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source": {"kind": "fixture", "uri": "tests/awmx/test_registry.py"},
        "metadata": {"suite": "foundation"},
    }
    payload.update(overrides)
    return payload


def test_registry_roundtrip_persists_artifact_by_type(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path / "registry")
    scenario = ScenarioSpec(
        **_artifact_payload(id="scenario.ticketing"),
        name="ticketing",
        description="Ticketing workflow scenario.",
    )

    artifact_path = registry.write(scenario)
    loaded = registry.read("scenario", "scenario.ticketing")

    assert artifact_path == tmp_path / "registry" / "scenarios" / "scenario.ticketing.json"
    assert artifact_path.exists()
    assert loaded == scenario


def test_registry_rejects_unknown_artifact_types(tmp_path: Path):
    registry = ArtifactRegistry(tmp_path / "registry")

    with open(tmp_path / "unknown.json", "w", encoding="utf-8") as handle:
        json.dump({"artifact_type": "unknown"}, handle)

    try:
        registry.read("unknown", "artifact.demo")
    except ValidationError as exc:
        assert "unknown artifact type" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


@pytest.mark.parametrize("bad_id", ["../escape", "/tmp/escape", "scenario..ticketing"])
def test_registry_rejects_path_like_artifact_ids(tmp_path: Path, bad_id: str):
    registry = ArtifactRegistry(tmp_path / "registry")
    scenario = ScenarioSpec(
        **_artifact_payload(id=bad_id),
        name="ticketing",
        description="Ticketing workflow scenario.",
    )

    try:
        registry.write(scenario)
    except ValidationError as exc:
        assert "path" in str(exc) or "separator" in str(exc)
    else:
        raise AssertionError("expected ValidationError")

    try:
        registry.read("scenario", bad_id)
    except ValidationError as exc:
        assert "path" in str(exc) or "separator" in str(exc)
    else:
        raise AssertionError("expected ValidationError")

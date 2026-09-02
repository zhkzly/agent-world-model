from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_env_foundry.builder import CandidateBuild, CommandResult
from agent_env_foundry.environment_conformance_v3 import (
    _replay_projection,
    run_environment_conformance_v3_internal,
)
from agent_env_foundry.preparation_v3 import (
    PreparationExecutionErrorV3,
    PreparationSettingsV3,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from v3_release_factory import build_actor_project


def _settings() -> PreparationSettingsV3:
    return PreparationSettingsV3(
        Path(os.environ.get("UV_CACHE_DIR", "/tmp/foundry-v3-runtime-uv-cache")),
        120.0,
    )


def _candidate(root: Path, *, phases: tuple[str, ...] | None = None) -> CandidateBuild:
    actor = build_actor_project(root)
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    selected = phases or (
        "lock",
        "sync",
        "build",
        "tests",
        "public_contract",
        "live_contract",
    )
    checks = tuple(CommandResult(phase, ("physical", phase), 0, "passed", "") for phase in selected)
    return CandidateBuild(actor, "fixture-thread", digest, "fixture", checks)


def test_v3_conformance_issues_host_receipt_from_physical_actor(tmp_path: Path) -> None:
    conformed = run_environment_conformance_v3_internal(
        _candidate(tmp_path / "actor"),
        tmp_path / "runtime",
        settings=_settings(),
    )

    assert conformed.receipt.verdict == "passed"
    assert conformed.receipt.actor_project_digest
    assert conformed.receipt.evidence_digest
    assert tuple(item["name"] for item in conformed.tool_specs) == ("increment",)
    host = conformed.evidence["host_checks"]
    assert isinstance(host, dict)
    assert host["reopen_persistence"] is True
    assert host["controlled_reset_replay"] is True
    assert host["instance_isolation"] is True


def test_v3_conformance_rejects_incomplete_builder_evidence(tmp_path: Path) -> None:
    with pytest.raises(PreparationExecutionErrorV3) as caught:
        run_environment_conformance_v3_internal(
            _candidate(tmp_path / "actor", phases=("tests",)),
            tmp_path / "runtime",
            settings=_settings(),
        )
    assert caught.value.code == "builder_evidence_incomplete"


def test_replay_projection_normalizes_only_the_host_instance_locator(tmp_path: Path) -> None:
    instance = tmp_path / "instance-a"
    value = {
        "root": str(instance),
        "file": str(instance / "src/app.py"),
        "similar_but_external": str(tmp_path / "instance-ab/file.txt"),
        "nested": [str(instance / "README.md"), 3],
    }

    assert _replay_projection(value, instance) == {
        "root": "<INSTANCE_ROOT>",
        "file": "<INSTANCE_ROOT>/src/app.py",
        "similar_but_external": str(tmp_path / "instance-ab/file.txt"),
        "nested": ["<INSTANCE_ROOT>/README.md", 3],
    }

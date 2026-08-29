from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from agent_env_foundry.builder import ACTOR_FACTORY
from agent_env_foundry.preparation import (
    PreparationExecutionError,
    PreparationSettings,
    ProjectMaterializationInput,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.qualification_v2 import (
    FrozenCoreInputs,
    QualificationV2Error,
    derive_qualification_core,
    materialize_qualification_core,
)
from agent_env_foundry.semantics_author import SEMANTICS_FACTORY
from agent_env_foundry.semantics_inputs import prepare_semantics_author_workspace
from agent_env_foundry.verifier_author import VERIFIER_FACTORY
from agent_env_foundry.verifier_inputs import prepare_verifier_author_workspace


def _write_project(root: Path, distribution: str, module: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'''[project]
name = "{distribution}"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
'''
    )
    (root / "uv.lock").write_text(
        f'''version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "{distribution}"
version = "0.1.0"
source = {{ editable = "." }}
'''
    )
    source = root / f"src/{module}/__init__.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n")


def _inputs(tmp_path: Path) -> FrozenCoreInputs:
    actor = tmp_path / "actor"
    _write_project(actor, "generated-environment", "generated_environment")
    actor_digest = compute_authored_project_digest(
        actor,
        "actor",
        require_locked_project=True,
    )
    expected = b'{"format":"expected-task-semantics/1"}'
    expected_digest = hashlib.sha256(expected).hexdigest()
    surface = PublicSurfaceManifest(
        start_schema={"type": "object"},
        reset_observation_schema={"type": "object"},
        tool_specs=(),
        public_documents_digest="a" * 64,
    )
    semantics_inputs = prepare_semantics_author_workspace(
        tmp_path / "semantics",
        actor_root=actor,
        actor_digest=actor_digest,
        expected_semantics_payload=expected,
        expected_semantics_digest=expected_digest,
        public_surface=surface,
    )
    verifier_inputs = prepare_verifier_author_workspace(
        tmp_path / "verifier",
        actor_root=actor,
        actor_digest=actor_digest,
        expected_semantics_payload=expected,
        expected_semantics_digest=expected_digest,
        public_surface=surface,
    )
    semantics = semantics_inputs.root
    verifier = verifier_inputs.root
    _write_project(semantics, "generated-task-semantics", "generated_task_semantics")
    _write_project(
        verifier,
        "generated-qualification-verifier",
        "generated_qualification_verifier",
    )
    return FrozenCoreInputs(
        expected_semantics_payload=expected,
        expected_semantics_digest=expected_digest,
        public_surface=surface,
        semantics_author_inputs=semantics_inputs,
        verifier_author_inputs=verifier_inputs,
        actor_project=ProjectMaterializationInput(
            actor,
            actor_digest,
            "generated_environment",
            (
                "generated_task_semantics",
                "generated_qualification_verifier",
                "agent_env_foundry",
            ),
            "actor",
        ),
        actor_factory=ACTOR_FACTORY,
        semantics_project=ProjectMaterializationInput(
            semantics,
            compute_authored_project_digest(
                semantics,
                "semantics",
                require_locked_project=True,
            ),
            "generated_task_semantics",
            (
                "generated_environment",
                "generated_qualification_verifier",
                "agent_env_foundry",
            ),
            "semantics",
        ),
        semantics_factory=SEMANTICS_FACTORY,
        verifier_project=ProjectMaterializationInput(
            verifier,
            compute_authored_project_digest(
                verifier,
                "verifier",
                require_locked_project=True,
            ),
            "generated_qualification_verifier",
            (
                "generated_environment",
                "generated_task_semantics",
                "agent_env_foundry",
            ),
            "verifier",
        ),
        verifier_factory=VERIFIER_FACTORY,
    )


def _settings(tmp_path: Path) -> PreparationSettings:
    return PreparationSettings(tmp_path / "uv-cache", 120.0)


def test_core_derivation_and_three_runtime_materialization_are_exact(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    core = derive_qualification_core(inputs)

    runtimes = materialize_qualification_core(
        inputs,
        core,
        tmp_path / "cache",
        settings=_settings(tmp_path),
    )

    assert runtimes.core == core
    assert runtimes.core.core_id == core.core_id
    assert (runtimes.actor.role, runtimes.semantics.role, runtimes.verifier.role) == (
        "actor",
        "semantics",
        "verifier",
    )
    assert (
        len(
            {
                runtimes.actor.project_root,
                runtimes.semantics.project_root,
                runtimes.verifier.project_root,
            }
        )
        == 3
    )
    assert "release_id" not in core.to_document()


def test_core_rejects_weakened_visibility_or_changed_project(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    weakened_projects = (
        ("actor_project", ("generated_task_semantics", "agent_env_foundry")),
        ("semantics_project", ("generated_environment", "agent_env_foundry")),
        ("verifier_project", ("generated_environment",)),
    )
    for field, forbidden in weakened_projects:
        weakened = replace(
            inputs,
            **{
                field: replace(
                    getattr(inputs, field),
                    forbidden_modules=forbidden,
                )
            },
        )
        with pytest.raises(ValueError, match="forbidden_modules"):
            derive_qualification_core(weakened)

    core = derive_qualification_core(inputs)
    (inputs.semantics_project.source_root / "src/generated_task_semantics/__init__.py").write_text(
        "VALUE = 2\n"
    )
    with pytest.raises(PreparationExecutionError) as caught:
        materialize_qualification_core(
            inputs,
            core,
            tmp_path / "cache",
            settings=_settings(tmp_path),
        )
    assert caught.value.kind == "SemanticsDefect"
    assert caught.value.code == "source_project_digest_mismatch"


def test_core_derivation_rejects_project_drift_and_materialization_rejects_other_core(
    tmp_path: Path,
) -> None:
    drifted = _inputs(tmp_path / "drifted")
    (drifted.actor_project.source_root / "src/generated_environment/__init__.py").write_text(
        "VALUE = 2\n"
    )
    with pytest.raises(QualificationV2Error) as drift_error:
        derive_qualification_core(drifted)
    assert drift_error.value.code == "core_project_digest_mismatch"
    assert drift_error.value.details["role"] == "actor"

    inputs = _inputs(tmp_path / "mismatch")
    core = derive_qualification_core(inputs)
    wrong_core = replace(core, expected_semantics_digest="f" * 64)
    cache = tmp_path / "mismatch/cache"
    with pytest.raises(QualificationV2Error) as core_error:
        materialize_qualification_core(
            inputs,
            wrong_core,
            cache,
            settings=_settings(tmp_path / "mismatch"),
        )
    assert core_error.value.code == "qualification_core_mismatch"
    assert not cache.exists()


def test_materialization_cache_cannot_overlap_frozen_project_roots(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    core = derive_qualification_core(inputs)
    projects = (
        inputs.actor_project,
        inputs.semantics_project,
        inputs.verifier_project,
    )
    before = {
        project.role: compute_authored_project_digest(
            project.source_root,
            project.role,
            require_locked_project=True,
        )
        for project in projects
    }

    with pytest.raises(QualificationV2Error) as caught:
        materialize_qualification_core(
            inputs,
            core,
            inputs.actor_project.source_root,
            settings=_settings(tmp_path),
        )

    assert caught.value.code == "qualification_cache_overlaps_source"
    assert not (inputs.actor_project.source_root / "qualification-cores").exists()
    after = {
        project.role: compute_authored_project_digest(
            project.source_root,
            project.role,
            require_locked_project=True,
        )
        for project in projects
    }
    assert after == before


def test_core_rejects_nested_peer_project_roots_before_derivation(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    nested = replace(
        inputs,
        semantics_project=replace(
            inputs.semantics_project,
            source_root=inputs.actor_project.source_root / "nested-semantics",
        ),
    )

    with pytest.raises(QualificationV2Error) as caught:
        derive_qualification_core(nested)

    assert caught.value.code == "core_project_roots_nested"


def test_core_binds_exact_bytes_both_authors_received(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    other_expected = b'{"format":"expected-task-semantics/1","other":true}'
    changed_expected = replace(
        inputs,
        expected_semantics_payload=other_expected,
        expected_semantics_digest=hashlib.sha256(other_expected).hexdigest(),
    )
    with pytest.raises(QualificationV2Error) as expected_error:
        derive_qualification_core(changed_expected)
    assert expected_error.value.code == "author_expected_semantics_mismatch"

    changed_surface = replace(
        inputs,
        public_surface=PublicSurfaceManifest(
            start_schema=inputs.public_surface.start_schema,
            reset_observation_schema=inputs.public_surface.reset_observation_schema,
            tool_specs=inputs.public_surface.tool_specs,
            public_documents_digest="b" * 64,
        ),
    )
    with pytest.raises(QualificationV2Error) as surface_error:
        derive_qualification_core(changed_surface)
    assert surface_error.value.code == "author_public_surface_mismatch"

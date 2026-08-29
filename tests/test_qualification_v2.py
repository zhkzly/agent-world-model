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
    seal_qualification_evidence,
    verify_qualification_evidence,
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


def _result(*, satisfied: bool) -> dict[str, object]:
    return {
        "initially_satisfied": False,
        "satisfied": satisfied,
        "required_effects_ok": satisfied,
        "collateral_ok": True,
        "answer_ok": None,
        "process_ok": satisfied,
        "report_values": {},
        "failure_codes": [] if satisfied else ["LOCAL_DIAGNOSTIC"],
    }


def _case(
    category: str,
    root: Path,
    *,
    capability_id: str = "cap-1",
) -> dict[str, object]:
    satisfied = category in {"positive", "alternative_route", "fresh_replay"}
    semantics = _result(satisfied=satisfied)
    if category == "wrong_answer":
        semantics.update(
            required_effects_ok=True,
            answer_ok=False,
            process_ok=True,
        )
    elif category == "collateral":
        semantics.update(
            required_effects_ok=True,
            collateral_ok=False,
            process_ok=True,
        )
    elif category == "missing_process":
        semantics.update(required_effects_ok=True, process_ok=False)
    verifier = {**semantics, "failure_codes": [] if satisfied else ["OTHER_DIAGNOSTIC"]}
    before = root / f"{capability_id}-{category}-before"
    after = root / f"{capability_id}-{category}-after"
    before.mkdir(parents=True, exist_ok=True)
    after.mkdir(parents=True, exist_ok=True)
    (before / "state.json").write_text('{"count":0}')
    (after / "state.json").write_text('{"count":1}')
    return {
        "category": category,
        "capability_id": capability_id,
        "start_case_id": "case-1",
        "semantic_key": "counter",
        "public_descriptor": {"name": "counter"},
        "before_instance_directory": str(before),
        "after_instance_directory": str(after),
        "axis_agreement": True,
        "readers_unchanged": True,
        "trace": [],
        "final_answer": {},
        "semantics_result": semantics,
        "verifier_result": verifier,
    }


def _cases(root: Path) -> tuple[dict[str, object], ...]:
    return tuple(
        _case(category, root)
        for category in (
            "positive",
            "no_op",
            "wrong_target",
            "near_miss",
            "wrong_answer",
            "collateral",
            "missing_process",
            "alternative_route",
            "fresh_replay",
        )
    )


def _mutants() -> tuple[dict[str, object], ...]:
    return (
        {
            "mutant_id": "semantics-effects",
            "target_role": "semantics",
            "killed": True,
            "killed_by": "generated_project_tests",
            "evidence": {"test": "failed"},
        },
        {
            "mutant_id": "verifier-collateral",
            "target_role": "verifier",
            "killed": True,
            "killed_by": "physical_axis_comparison",
            "evidence": {"axis": "collateral_ok"},
        },
    )


def test_evidence_sealing_requires_complete_physical_matrix(tmp_path: Path) -> None:
    core = derive_qualification_core(_inputs(tmp_path / "inputs"))
    destination = tmp_path / "evidence"
    manifest = seal_qualification_evidence(
        core,
        destination,
        case_records=_cases(tmp_path / "case-inputs"),
        mutation_records=_mutants(),
        required_capability_ids=("cap-1",),
    )

    assert manifest["format"] == "qualification-evidence/2"
    assert manifest["core_id"] == core.core_id
    assert len(manifest["cases"]) == 9
    assert len(manifest["mutations"]) == 2
    assert (destination / "evidence-manifest.json").is_file()
    for entry in (*manifest["cases"], *manifest["mutations"]):
        assert (destination / entry["path"]).is_file()
    assert (
        verify_qualification_evidence(
            core,
            destination,
            required_capability_ids=("cap-1",),
        )
        == manifest
    )

    without_alternative = tuple(
        item
        for item in _cases(tmp_path / "no-alternative-inputs")
        if item["category"] not in {"alternative_route", "near_miss"}
    )
    no_alternative_manifest = seal_qualification_evidence(
        core,
        tmp_path / "no-alternative",
        case_records=without_alternative,
        mutation_records=_mutants(),
        required_capability_ids=("cap-1",),
    )
    assert len(no_alternative_manifest["cases"]) == 7

    query_wrong_target = list(_cases(tmp_path / "query-wrong-target-inputs"))
    wrong_target_index = next(
        index for index, item in enumerate(query_wrong_target) if item["category"] == "wrong_target"
    )
    wrong_target = query_wrong_target[wrong_target_index]
    query_result = {
        **wrong_target["semantics_result"],
        "required_effects_ok": True,
        "answer_ok": False,
        "process_ok": False,
    }
    query_wrong_target[wrong_target_index] = {
        **wrong_target,
        "semantics_result": query_result,
        "verifier_result": {
            **query_result,
            "failure_codes": ["INDEPENDENT_WRONG_TARGET"],
        },
    }
    query_manifest = seal_qualification_evidence(
        core,
        tmp_path / "query-wrong-target",
        case_records=tuple(query_wrong_target),
        mutation_records=_mutants(),
        required_capability_ids=("cap-1",),
    )
    assert len(query_manifest["cases"]) == 9

    first = destination / manifest["cases"][0]["path"]
    first.write_bytes(b"{}")
    with pytest.raises(QualificationV2Error) as caught:
        verify_qualification_evidence(
            core,
            destination,
            required_capability_ids=("cap-1",),
        )
    assert caught.value.code == "qualification_evidence_digest_mismatch"

    missing = _cases(tmp_path / "missing-inputs")[:-1]
    with pytest.raises(QualificationV2Error) as caught:
        seal_qualification_evidence(
            core,
            tmp_path / "missing",
            case_records=missing,
            mutation_records=_mutants(),
            required_capability_ids=("cap-1",),
        )
    assert caught.value.code == "qualification_evidence_categories_missing"


def test_evidence_sealing_rejects_disagreement_or_surviving_mutant(tmp_path: Path) -> None:
    core = derive_qualification_core(_inputs(tmp_path / "inputs"))
    disagreeing = list(_cases(tmp_path / "disagreeing-inputs"))
    disagreeing[0] = {
        **disagreeing[0],
        "verifier_result": _result(satisfied=False),
    }
    with pytest.raises(QualificationV2Error) as caught:
        seal_qualification_evidence(
            core,
            tmp_path / "disagreement",
            case_records=tuple(disagreeing),
            mutation_records=_mutants(),
            required_capability_ids=("cap-1",),
        )
    assert caught.value.code == "qualification_reader_disagreement"

    surviving = list(_mutants())
    surviving[0] = {**surviving[0], "killed": False}
    with pytest.raises(QualificationV2Error) as caught:
        seal_qualification_evidence(
            core,
            tmp_path / "surviving",
            case_records=_cases(tmp_path / "surviving-inputs"),
            mutation_records=tuple(surviving),
            required_capability_ids=("cap-1",),
        )
    assert caught.value.code == "qualification_mutant_survived"


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

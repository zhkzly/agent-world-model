from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agent_world.builder import (
    BuilderError,
    CandidateCompletion,
    CandidateFileDeclaration,
    CandidatePublicSelfCheckDeclaration,
    CandidateRuntimeDeclaration,
    CandidateTaskMaterializerDeclaration,
    CandidateWorkspaceError,
    CandidateWorkspaceValidator,
    EnvironmentBuilder,
    normalize_candidate_completion_output,
)
from agent_world.control import ValidationDiagnostic


def _completed_values() -> dict[str, object]:
    return {
        "status": "completed",
        "project_root": "candidate",
        "root_project_mode": "virtual-read-only-source-tree",
        "dependency_install_mode": "offline-wheel-only",
        "runtime": CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "environment.runtime"),
            entry_path="src/environment/runtime.py",
        ),
        "task_materializer": CandidateTaskMaterializerDeclaration(
            entrypoint="environment.tasks:materialize",
            entry_path="src/environment/tasks.py",
        ),
        "public_self_check": CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "environment.public_check"),
            entry_path="src/environment/public_check.py",
        ),
        "public_test_paths": ("tests/test_public.py",),
        "files": (
            CandidateFileDeclaration(path="LICENSE", role="license"),
            CandidateFileDeclaration(path="pyproject.toml", role="configuration"),
            CandidateFileDeclaration(path="uv.lock", role="dependency_lock"),
            CandidateFileDeclaration(path="src/environment/runtime.py", role="runtime"),
            CandidateFileDeclaration(
                path="src/environment/tasks.py",
                role="task_materializer",
            ),
            CandidateFileDeclaration(
                path="src/environment/public_check.py",
                role="public_verifier",
            ),
            CandidateFileDeclaration(path="tests/test_public.py", role="public_test"),
        ),
    }


def test_completed_candidate_requires_materializer_v3_and_supply_chain_echo() -> None:
    completion = CandidateCompletion.model_validate(_completed_values())

    assert completion.task_materializer is not None
    assert completion.task_materializer.protocol == "python-callable-v3"
    assert completion.root_project_mode == "virtual-read-only-source-tree"
    assert completion.dependency_install_mode == "offline-wheel-only"


def test_completed_candidate_requires_a_real_license_role_file() -> None:
    values = _completed_values()
    files = values["files"]
    assert isinstance(files, tuple)
    values["files"] = tuple(
        item
        for item in files
        if not isinstance(item, CandidateFileDeclaration) or item.path != "LICENSE"
    )

    with pytest.raises(ValidationError, match="required component path"):
        CandidateCompletion.model_validate(values)


def test_builder_diagnostic_uses_validation_frontier_without_rejected_values() -> None:
    values = _completed_values()
    values["files"] = ()
    try:
        CandidateCompletion.model_validate(values)
    except ValidationError as validation_error:
        try:
            raise BuilderError(
                "agent.output",
                "raw rejected value /private/workspace/secret",
            ) from validation_error
        except BuilderError as builder_error:
            diagnostic = EnvironmentBuilder._validation_diagnostic(  # noqa: SLF001
                builder_error
            )
    else:  # pragma: no cover - the contract deliberately rejects this payload
        raise AssertionError("invalid CandidateCompletion unexpectedly passed")

    assert diagnostic.validation_phase == "completion_declarations"
    assert diagnostic.frontier_ordinal == 20
    assert diagnostic.issue_codes == ("completion_files_missing@root",)
    assert "/private/workspace/secret" not in diagnostic.feedback
    assert all(not code.startswith("builder_agent.output:") for code in diagnostic.issue_codes)


def test_builder_workspace_progress_records_counts_without_file_names(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    source = candidate / "src" / "private_business_name.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")
    state = SimpleNamespace(
        run_id="run:heartbeat",
        attempt_id="attempt:build:1",
        workspace=tmp_path,
        lineage_id="lineage:heartbeat",
    )

    progress = EnvironmentBuilder._workspace_progress(  # type: ignore[arg-type]  # noqa: SLF001
        state,
        "changed",
    )

    assert progress.file_count == 1
    assert progress.run_id == "run:heartbeat"
    assert progress.attempt_id == "attempt:build:1"
    assert progress.total_bytes == len("value = 1\n")
    assert progress.metadata_digest is not None
    assert "private_business_name" not in str(progress.model_dump(mode="json"))


def test_builder_precommit_removes_only_derived_candidate_ephemera(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate"
    package = candidate / "environment"
    cache = package / "__pycache__"
    cache.mkdir(parents=True)
    source = package / "runtime.py"
    source.write_text("value = 1\n", encoding="utf-8")
    (cache / "runtime.cpython-312.pyc").write_bytes(b"derived")
    loose_bytecode = package / "orphan.pyc"
    loose_bytecode.write_bytes(b"derived")
    ordinary_build_named_file = candidate / "build"
    ordinary_build_named_file.write_text("must remain for validator", encoding="utf-8")

    EnvironmentBuilder._remove_derived_candidate_ephemera(candidate)  # noqa: SLF001

    assert source.is_file()
    assert ordinary_build_named_file.is_file()
    assert not cache.exists()
    assert not loose_bytecode.exists()


def test_builder_precommit_never_follows_cache_symlink(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    external = tmp_path / "external-cache"
    external.mkdir()
    marker = external / "keep.pyc"
    marker.write_bytes(b"outside")
    cache_link = candidate / "__pycache__"
    cache_link.symlink_to(external, target_is_directory=True)

    EnvironmentBuilder._remove_derived_candidate_ephemera(candidate)  # noqa: SLF001

    assert cache_link.is_symlink()
    assert marker.read_bytes() == b"outside"


def test_workspace_validation_rejects_a_declared_but_missing_license(tmp_path: Path) -> None:
    completion = CandidateCompletion.model_validate(_completed_values())
    for declaration in completion.files:
        if declaration.path == "LICENSE":
            continue
        path = tmp_path / declaration.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("pass\n", encoding="utf-8")

    with pytest.raises(CandidateWorkspaceError, match="declared files are missing.*LICENSE"):
        CandidateWorkspaceValidator().validate(tmp_path, completion)


@pytest.mark.parametrize("field", ("root_project_mode", "dependency_install_mode"))
def test_completed_candidate_cannot_omit_supply_chain_contract(field: str) -> None:
    values = _completed_values()
    values.pop(field)

    with pytest.raises(ValidationError) as captured:
        CandidateCompletion.model_validate(values)

    assert captured.value.errors(include_url=False)[0]["type"] == (
        "completion_missing_declarations"
    )


def test_candidate_completion_has_no_consumer_adapter_or_task_generator_fields() -> None:
    values = _completed_values()
    values["consumer_adapter_path"] = "src/environment/adapter.py"
    values["task_generator"] = {
        "entrypoint": "environment.tasks:generate",
        "entry_path": "src/environment/tasks.py",
    }

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CandidateCompletion.model_validate(values)


def test_task_materializer_entrypoint_is_exact() -> None:
    with pytest.raises(ValidationError, match="package.module:materialize"):
        CandidateTaskMaterializerDeclaration(
            entrypoint="environment.tasks:generate",
            entry_path="src/environment/tasks.py",
        )


def _diagnostic_for_invalid_completion(
    values: dict[str, object],
) -> ValidationDiagnostic:
    try:
        CandidateCompletion.model_validate(values)
    except ValidationError as validation_error:
        try:
            raise BuilderError("agent.output", "private raw output") from validation_error
        except BuilderError as builder_error:
            return EnvironmentBuilder._validation_diagnostic(builder_error)  # noqa: SLF001
    raise AssertionError("invalid CandidateCompletion unexpectedly passed")


def test_builder_distinguishes_entrypoint_format_from_module_binding() -> None:
    format_values = _completed_values()
    format_values["task_materializer"] = {
        "entrypoint": "candidate/materializer.py:materialize",
        "entry_path": "candidate/materializer.py",
    }
    format_diagnostic = _diagnostic_for_invalid_completion(format_values)

    binding_values = _completed_values()
    binding_values["task_materializer"] = {
        "entrypoint": "materializer:materialize",
        "entry_path": "candidate/materializer.py",
    }
    binding_diagnostic = _diagnostic_for_invalid_completion(binding_values)

    assert format_diagnostic.validation_phase == "completion_entrypoint_format"
    assert format_diagnostic.frontier_ordinal == 15
    assert format_diagnostic.issue_codes == (
        "task_materializer_entrypoint_format@task_materializer.entrypoint",
    )
    assert "package.module:materialize" in format_diagnostic.feedback

    assert binding_diagnostic.validation_phase == "completion_entrypoint_binding"
    assert binding_diagnostic.frontier_ordinal == 16
    assert binding_diagnostic.issue_codes == (
        "task_materializer_binding_mismatch@task_materializer",
    )
    assert "replacing `/` with `.`" in binding_diagnostic.feedback


def test_task_materializer_binding_supports_src_and_main_mapping() -> None:
    declaration = CandidateTaskMaterializerDeclaration(
        entrypoint="environment.tasks:materialize",
        entry_path="src/environment/tasks/__main__.py",
    )

    assert declaration.entrypoint == "environment.tasks:materialize"


def _outer_prefixed_completion_output() -> dict[str, object]:
    return {
        "status": "completed",
        "project_root": "candidate",
        "root_project_mode": "virtual-read-only-source-tree",
        "dependency_install_mode": "offline-wheel-only",
        "runtime": {
            "argv": [".venv/bin/python", "-m", "candidate.runtime"],
            "entry_path": "candidate/runtime.py",
        },
        "task_materializer": {
            "entrypoint": "materialize",
            "entry_path": "candidate/materializer.py",
        },
        "public_self_check": {
            "argv": [".venv/bin/python", "-m", "candidate.self_check"],
            "entry_path": "candidate/self_check.py",
        },
        "public_test_paths": ["public_tests/test_runtime.py"],
        "files": [
            {"path": "candidate/LICENSE", "role": "license"},
            {"path": "candidate/pyproject.toml", "role": "configuration"},
            {"path": "candidate/uv.lock", "role": "dependency_lock"},
            {"path": "candidate/candidate/runtime.py", "role": "runtime"},
            {
                "path": "candidate/candidate/materializer.py",
                "role": "task_materializer",
            },
            {
                "path": "candidate/candidate/self_check.py",
                "role": "public_verifier",
            },
            {
                "path": "candidate/public_tests/test_runtime.py",
                "role": "public_test",
            },
        ],
    }


def _parse_json_completion(value: object) -> CandidateCompletion:
    return CandidateCompletion.model_validate_json(json.dumps(value))


def test_framework_normalizes_one_witnessed_outer_candidate_namespace() -> None:
    raw = _outer_prefixed_completion_output()

    normalized = normalize_candidate_completion_output(raw)
    completion = _parse_json_completion(normalized)

    assert raw["files"][0]["path"] == "candidate/LICENSE"  # type: ignore[index]
    assert tuple(item.path for item in completion.files) == (
        "LICENSE",
        "pyproject.toml",
        "uv.lock",
        "candidate/runtime.py",
        "candidate/materializer.py",
        "candidate/self_check.py",
        "public_tests/test_runtime.py",
    )
    assert completion.runtime is not None
    assert completion.runtime.entry_path == "candidate/runtime.py"
    assert completion.runtime.argv[-1] == "candidate.runtime"
    assert completion.task_materializer is not None
    assert completion.task_materializer.entrypoint == "candidate.materializer:materialize"


def test_framework_preserves_legitimate_nested_candidate_package() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"

    normalized = normalize_candidate_completion_output(raw)

    assert normalized == raw
    assert _parse_json_completion(normalized).runtime is not None


def test_framework_does_not_guess_mixed_candidate_namespaces() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    license_declaration = files[0]
    assert isinstance(license_declaration, dict)
    license_declaration["path"] = "LICENSE"

    normalized = normalize_candidate_completion_output(raw)

    normalized_files = normalized["files"]  # type: ignore[index]
    assert normalized_files[1]["path"] == "candidate/pyproject.toml"  # type: ignore[index]
    with pytest.raises(ValidationError):
        _parse_json_completion(normalized)


def test_framework_does_not_rewrite_arbitrary_materializer_callable() -> None:
    raw = _outer_prefixed_completion_output()
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "wrong.module:materialize"

    normalized = normalize_candidate_completion_output(raw)

    with pytest.raises(ValidationError, match="does not match entry_path"):
        _parse_json_completion(normalized)


def test_framework_normalizes_roles_fixed_by_component_path_claims() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"
    for item in files:
        assert isinstance(item, dict)
        item["role"] = "documentation"
    files.append(
        {
            "path": "public_tests/test_runtime_launch.py",
            "role": "documentation",
        }
    )
    public_tests = raw["public_test_paths"]
    assert isinstance(public_tests, list)
    public_tests.append("public_tests/test_runtime_launch.py")

    completion = _parse_json_completion(normalize_candidate_completion_output(raw))
    roles = {item.path: item.role for item in completion.files}

    assert roles["pyproject.toml"] == "configuration"
    assert roles["uv.lock"] == "dependency_lock"
    assert roles["LICENSE"] == "license"
    assert roles["candidate/runtime.py"] == "runtime"
    assert roles["candidate/materializer.py"] == "task_materializer"
    assert roles["candidate/self_check.py"] == "public_verifier"
    assert roles["public_tests/test_runtime.py"] == "public_test"
    assert roles["public_tests/test_runtime_launch.py"] == "public_test"


def test_framework_does_not_normalize_conflicting_component_role_claims() -> None:
    raw = _outer_prefixed_completion_output()
    files = raw["files"]
    assert isinstance(files, list)
    for item in files:
        assert isinstance(item, dict)
        path = item["path"]
        assert isinstance(path, str)
        item["path"] = path.removeprefix("candidate/")
    task = raw["task_materializer"]
    assert isinstance(task, dict)
    task["entrypoint"] = "candidate.materializer:materialize"
    raw["public_test_paths"] = ["candidate/runtime.py"]

    normalized = normalize_candidate_completion_output(raw)

    with pytest.raises(ValidationError, match="public test path"):
        _parse_json_completion(normalized)


def test_unknown_framework_value_error_is_not_actionable() -> None:
    values = _completed_values()
    values["runtime"] = {
        "argv": (".venv/bin/python", "-m", "wrong.module"),
        "entry_path": "src/environment/runtime.py",
    }

    diagnostic = _diagnostic_for_invalid_completion(values)

    assert diagnostic.validation_phase == "framework_diagnostic"
    assert diagnostic.issue_codes == ("framework_diagnostic_incomplete@runtime",)
    assert diagnostic.issues[0].retryable is False

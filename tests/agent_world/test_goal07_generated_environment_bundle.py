import hashlib
from pathlib import Path

import pytest

from agent_world.artifacts import validate_artifact
from agent_world.fixtures.project_board_lite_codegen import (
    check_project_board_generated_bundle,
    project_board_generated_implementation_record,
    write_project_board_generated_files,
)
from agent_world.generated_bundle import run_packaged_generated_bundle_check
from agent_world.pipeline import PipelineNode, PipelineRunConfig, PipelineRunner, project_board_lite_node_registry


def test_goal07_project_board_pipeline_releases_verified_generated_bundle(tmp_path):
    record, context = PipelineRunner(project_board_lite_node_registry()).run(
        PipelineRunConfig(output_dir=tmp_path, raw_request="Generate project-board-lite.")
    )

    bundle = context.artifacts["GeneratedEnvironmentBundle"]
    package_plan = context.artifacts["EnvironmentPackagePlan"]
    release = context.artifacts["ReleaseManifest"]

    assert record.status == "pass"
    assert bundle["id"] == "bundle-project-board-lite-generated"
    assert bundle["status"] == "accepted"
    validate_artifact("GeneratedEnvironmentBundle", bundle)
    assert package_plan["generated_bundle_ref"] == bundle["id"]
    assert release["generated_bundle_ref"] == bundle["id"]
    assert release["artifact_hashes"]["GeneratedEnvironmentBundle"] == bundle["hash"]

    build_dir = Path(bundle["build_dir"])
    expected_files = {
        "runtime.py": "runtime_code",
        "seed_state.json": "seed_fixture",
        "verifier.py": "verifier_code",
        "surface_descriptor.json": "surface_descriptor",
        "check_replay.py": "test_or_check",
        "build_manifest.yaml": "build_manifest",
    }
    files_by_name = {Path(item["path"]).name: item for item in bundle["generated_files"]}
    assert {name: files_by_name[name]["kind"] for name in expected_files} == expected_files
    for generated_file in bundle["generated_files"]:
        path = Path(generated_file["path"])
        assert path.exists()
        assert generated_file["sha256"] == _sha256(path)
        assert generated_file["source_refs"]
    assert "agent_world.fixtures.project_board_lite" not in (build_dir / "runtime.py").read_text(encoding="utf-8")

    check = check_project_board_generated_bundle(build_dir)
    assert check["success"] is True
    independent = check["independent_verification_record"]
    assert set(independent["verified_task_ids"]) == {"pb-task-1", "pb-task-2", "pb-task-3"}
    assert {record["task_id"] for record in independent["task_records"]} == {"pb-task-1", "pb-task-2", "pb-task-3"}
    assert check["positive_verifier_result"]["success"] is True
    assert check["negative_verifier_result"]["success"] is False
    assert context.build_check_replay_records[-1]["generated_bundle_id"] == bundle["id"]

    package_dir = tmp_path / "envpkg"
    runtime_dir = package_dir / "runtime" / "generated" / bundle["id"]
    runtime_index = package_dir / "release" / "generated-runtime-index.yaml"
    packaged_release = package_dir / "release" / "release-manifest.yaml"
    assert runtime_index.is_file()
    assert packaged_release.is_file()
    for filename in expected_files:
        assert (runtime_dir / filename).is_file()
        assert _sha256(runtime_dir / filename) == _sha256(build_dir / filename)
    packaged_check = run_packaged_generated_bundle_check(package_dir)
    assert packaged_check["success"] is True
    assert packaged_check["positive_verifier_result"]["success"] is True
    assert packaged_check["negative_verifier_result"]["success"] is False


def test_goal07_forged_check_replay_stdout_is_rejected(tmp_path):
    build_dir = tmp_path / "generated"
    write_project_board_generated_files(build_dir)
    (build_dir / "check_replay.py").write_text(
        "import json\n"
        "print(json.dumps({\n"
        "    'success': True,\n"
        "    'positive_verifier_result': {'success': True},\n"
        "    'negative_verifier_result': {'success': False},\n"
        "}, indent=2))\n",
        encoding="utf-8",
    )

    check = check_project_board_generated_bundle(build_dir)

    assert check["success"] is False
    assert check["failure_class"] == "independent_generated_bundle_verification_failed"
    prerequisite_checks = check["independent_verification_record"]["prerequisite_checks"]
    assert any(item["name"] == "check_replay_imports_runtime" and item["passed"] is False for item in prerequisite_checks)


def test_goal07_forged_check_replay_cannot_reach_release(tmp_path):
    registry = project_board_lite_node_registry()
    registry.register(
        PipelineNode(
            node_id="project-board-forged-check-replay",
            stage="IMPLEMENT",
            artifact_type="CodeImplementation",
            input_artifact_types=["ImplementationRequest"],
            output_artifact_type="CodeImplementation",
            allowed_agent_backend=True,
            factory=lambda context: project_board_generated_implementation_record(context, forge_check_success=True),
        )
    )

    record, context = PipelineRunner(registry).run(PipelineRunConfig(output_dir=tmp_path, raw_request="Generate project-board-lite."))

    assert record.status == "fail"
    assert record.failure_class == "independent_generated_bundle_verification_failed"
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert "ReleaseManifest" not in context.artifacts


@pytest.mark.parametrize("filename", ["runtime.py", "verifier.py", "check_replay.py"])
def test_goal07_broken_generated_file_fails_before_release(tmp_path, filename):
    registry = project_board_lite_node_registry()
    registry.register(
        PipelineNode(
            node_id=f"project-board-broken-{filename}",
            stage="IMPLEMENT",
            artifact_type="CodeImplementation",
            input_artifact_types=["ImplementationRequest"],
            output_artifact_type="CodeImplementation",
            allowed_agent_backend=True,
            factory=lambda context: project_board_generated_implementation_record(context, break_generated_file=filename),
        )
    )

    record, context = PipelineRunner(registry).run(PipelineRunConfig(output_dir=tmp_path, raw_request="Generate project-board-lite."))

    assert record.status == "fail"
    assert record.node_results[-1].stage == "IMPLEMENT"
    assert context.artifacts["GeneratedEnvironmentBundle"]["status"] == "fail"
    assert context.build_check_replay_records[-1]["status"] == "fail"
    assert context.build_check_replay_records[-1]["build_check_replay_records"][0]["success"] is False
    assert "ReleaseManifest" not in context.artifacts


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

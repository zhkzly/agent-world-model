from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_world.artifacts import stable_json
from agent_world.independent_verifier import verify_generated_project_independent


@dataclass(frozen=True)
class GeneratedProjectPackageResult:
    package_dir: Path
    runtime_dir: Path
    runtime_index_path: Path
    check_record: dict[str, Any]


def assemble_generated_project_package(
    *,
    package_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    gate_records: list[dict[str, Any]],
    review_records: list[dict[str, Any]],
    agent_invocations: list[dict[str, Any]],
    implementation_check_records: list[dict[str, Any]],
) -> GeneratedProjectPackageResult:
    if "GeneratedEnvironmentProject" not in artifacts:
        raise ValueError("GeneratedEnvironmentProject is required for generated project packaging")
    if "ReleaseManifest" not in artifacts:
        raise ValueError("ReleaseManifest is required for generated project packaging")
    project = artifacts["GeneratedEnvironmentProject"]
    release = artifacts["ReleaseManifest"]
    if project["status"] != "accepted":
        raise ValueError("Only accepted GeneratedEnvironmentProject artifacts can be packaged")

    package_dir = Path(package_dir)
    if package_dir.exists():
        shutil.rmtree(package_dir)
    runtime_dir = package_dir / "runtime" / "project"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    for dirname in ["release", "checks", "spec"]:
        (package_dir / dirname).mkdir(parents=True, exist_ok=True)

    source_dir = Path(project["build_dir"])
    _copy_project_tree(source_dir, runtime_dir)
    copied_files = _runtime_file_records(runtime_dir, runtime_dir_ref="runtime/project")
    runtime_index = _runtime_index(release=release, project=project, copied_files=copied_files)
    runtime_index_path = package_dir / "runtime" / "runtime_index.json"
    _write_json(runtime_index_path, runtime_index)
    _write_json(package_dir / "release" / "runtime_index.json", runtime_index)
    _write_json(package_dir / "release" / "release_manifest.json", release)
    _write_portable_specs(package_dir, artifacts)
    _write_json(package_dir / "checks" / "independent_verification_report.json", artifacts["IndependentVerificationReport"])
    _write_jsonl(package_dir / "checks" / "gate_records.jsonl", gate_records)
    _write_jsonl(package_dir / "checks" / "review_records.jsonl", review_records)
    _write_jsonl(package_dir / "checks" / "agent_invocations.jsonl", agent_invocations)
    _write_jsonl(package_dir / "checks" / "implementation_check_records.jsonl", implementation_check_records)

    check_record = run_packaged_generated_project_check(package_dir)
    _write_json(package_dir / "checks" / "generated_project_package_check.json", check_record)
    if not check_record["success"]:
        raise ValueError(check_record["recovery_suggestion"])

    manifest = _publishable_manifest(release=release, project=project, runtime_index=runtime_index)
    _write_json(package_dir / "manifest.json", manifest)
    return GeneratedProjectPackageResult(package_dir=package_dir, runtime_dir=runtime_dir, runtime_index_path=runtime_index_path, check_record=check_record)


def run_packaged_generated_project_check(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    try:
        runtime_index = _read_json(package_dir / "runtime" / "runtime_index.json")
        runtime_dir = package_dir / str(runtime_index.get("runtime_dir_ref", "runtime/project"))
        release = _read_json(package_dir / "release" / "release_manifest.json")
        tasks = _read_jsonl(package_dir / "spec" / "tasks.jsonl")
        generated_check = _run_runtime_command(runtime_dir, runtime_index.get("check", {}).get("command", []))
        independent = verify_generated_project_independent(str(release["environment_id"]), runtime_dir, accepted_tasks=tasks)
        success = generated_check["success"] and independent.get("success") is True
        if not generated_check["success"]:
            failure_class = generated_check.get("failure_class", "packaged_generated_project_self_check_failed")
            recovery = "Run the package self-check command and inspect runtime/project."
        elif not independent.get("success"):
            failure_class = independent.get("failure_class", "packaged_independent_generated_project_check_failed")
            recovery = independent.get("recovery_suggestion", "Packaged generated project failed independent framework verification.")
        else:
            failure_class = ""
            recovery = ""
        return {
            "check_id": "packaged-generated-project-check",
            "success": success,
            "runtime_dir_ref": runtime_index.get("runtime_dir_ref", ""),
            "generated_check_record": generated_check,
            "independent_verification_record": independent,
            "framework_check_observation": independent.get("framework_check_observation", {}),
            "independent_task_records": independent.get("task_records", []),
            "failure_class": failure_class,
            "recovery_suggestion": recovery,
        }
    except Exception as exc:
        return {
            "check_id": "packaged-generated-project-check",
            "success": False,
            "runtime_dir_ref": "",
            "generated_check_record": {},
            "independent_verification_record": {},
            "framework_check_observation": {},
            "independent_task_records": [],
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": str(exc),
        }


def _runtime_index(*, release: dict[str, Any], project: dict[str, Any], copied_files: list[dict[str, Any]]) -> dict[str, Any]:
    command = project.get("self_check_commands", [[]])[0] if project.get("self_check_commands") else []
    return {
        "schema_version": "agent-world.runtime-index.v1",
        "environment_id": release["environment_id"],
        "version": release.get("version", "0.1.0"),
        "project_id": project["id"],
        "release_id": release["release_id"],
        "runtime_dir_ref": "runtime/project",
        "contract_ref": "runtime/project/contract.json",
        "runtime_abi_version": project["runtime_abi_version"],
        "interfaces": project["contract"]["interfaces"],
        "generated_files": copied_files,
        "check": {"cwd_ref": "runtime/project", "command": command},
        "replay": {
            "cwd_ref": "runtime/project",
            "command_template": ["framework-abi-replay", "{task_id}"],
            "commands": [["framework-abi-replay", task_id] for task_id in release.get("task_index", [])],
        },
        "consumer_contract": {
            "kind": "contract_project",
            "load_strategy": "load runtime/project/contract.json and call declared runtime ABI interfaces",
            "package_relative_refs_only": True,
        },
        "status": "packaged",
    }


def _publishable_manifest(*, release: dict[str, Any], project: dict[str, Any], runtime_index: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "agent-world.envpkg.v1",
        "environment_id": release["environment_id"],
        "version": release.get("version", "0.1.0"),
        "implementation_id": project["id"],
        "project_id": project["id"],
        "runtime_root": "runtime/project",
        "contract_ref": "runtime/project/contract.json",
        "runtime_index_ref": "runtime/runtime_index.json",
        "runtime_abi_version": project["runtime_abi_version"],
        "surfaces": project["contract"].get("surfaces", []),
        "dependencies": project["contract"].get("dependencies", {}),
        "bootstrap": {
            "setup": {"interface": "setup"},
            "health": {"interface": "health"},
            "reset": {"interface": "reset"},
            "invoke": {"interface": "invoke"},
            "verify": {"interface": "verify"},
            "export_trace": {"interface": "export_trace"},
            "teardown": {"interface": "teardown"},
            "check": runtime_index["check"],
            "replay": runtime_index["replay"],
        },
        "files": runtime_index["generated_files"],
        "spec_refs": {
            "need": "spec/need.json",
            "environment": "spec/environment.json",
            "tool_graph": "spec/tool_graph.json",
            "tasks": "spec/tasks.jsonl",
            "verifiers": "spec/verifiers.jsonl",
        },
        "check_refs": {
            "independent_verification_report": "checks/independent_verification_report.json",
            "generated_project_package_check": "checks/generated_project_package_check.json",
        },
        "release_refs": {
            "release_manifest": "release/release_manifest.json",
            "runtime_index": "release/runtime_index.json",
        },
        "source_artifact_refs": list(project.get("source_artifact_ids", [])),
        "release_id": release["release_id"],
        "status": "packaged",
    }


def _copy_project_tree(source_dir: Path, runtime_dir: Path) -> None:
    for child in source_dir.iterdir():
        target = runtime_dir / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target)
        elif child.is_file():
            shutil.copy2(child, target)


def _runtime_file_records(runtime_dir: Path, *, runtime_dir_ref: str) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in runtime_dir.rglob("*") if item.is_file()):
        rel = path.relative_to(runtime_dir).as_posix()
        if "/__pycache__/" in f"/{rel}" or rel.endswith((".pyc", ".pyo")):
            continue
        records.append({"path": f"{runtime_dir_ref}/{rel}", "kind": _kind_for_runtime_path(rel), "sha256": file_sha256(path), "source_refs": []})
    return records


def _kind_for_runtime_path(path: str) -> str:
    if path == "contract.json":
        return "contract"
    first = path.split("/", 1)[0]
    return {
        "source": "source",
        "state": "state",
        "adapters": "adapter",
        "scripts": "script",
        "spec": "spec",
    }.get(first, "other")


def _write_portable_specs(package_dir: Path, artifacts: dict[str, dict[str, Any]]) -> None:
    json_specs = {
        "NeedSpec": "spec/need.json",
        "SourceEvidenceIndex": "spec/source_evidence.json",
        "KnowledgePack": "spec/knowledge_pack.json",
        "EnvironmentSpec": "spec/environment.json",
        "LogicalToolGraph": "spec/tool_graph.json",
        "SurfacePlan": "spec/surfaces.json",
        "FeasibilityReport": "spec/feasibility.json",
        "ImplementationRequest": "spec/implementation_request.json",
        "GeneratedEnvironmentProject": "runtime/generated_project.json",
    }
    for artifact_type, relative_path in json_specs.items():
        if artifact_type in artifacts:
            _write_json(package_dir / relative_path, artifacts[artifact_type])
    if "TaskSet" in artifacts:
        _write_json(package_dir / "spec" / "tasks.json", artifacts["TaskSet"])
        _write_jsonl(package_dir / "spec" / "tasks.jsonl", artifacts["TaskSet"].get("tasks", []))
    if "VerifierPlan" in artifacts:
        _write_json(package_dir / "spec" / "verifiers.json", artifacts["VerifierPlan"])
        _write_jsonl(package_dir / "spec" / "verifiers.jsonl", artifacts["VerifierPlan"].get("verifiers", []))


def _run_runtime_command(cwd: Path, command: list[Any]) -> dict[str, Any]:
    if not command:
        return {"success": False, "command": [], "exit_code": None, "stdout": "", "stderr": "missing command", "failure_class": "missing_runtime_command"}
    argv = [sys.executable if str(part) == "python" else str(part) for part in command]
    try:
        completed = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=15, check=False)
    except Exception as exc:
        return {"success": False, "command": argv, "exit_code": None, "stdout": "", "stderr": str(exc), "failure_class": exc.__class__.__name__}
    parsed = _parse_json_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {"success": success, "command": argv, "exit_code": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr, "parsed": parsed, "failure_class": "" if success else "portable_runtime_command_failed"}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json(value) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return value


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(stable_json(row) + "\n" for row in rows), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object: {path}")
        rows.append(value)
    return rows


def _parse_json_stdout(stdout: str) -> dict[str, Any]:
    try:
        value = json.loads(stdout)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, dict):
        return value
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
    return {}

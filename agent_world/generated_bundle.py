from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_world.artifacts import read_yaml, write_jsonl, write_yaml
from agent_world.independent_verifier import verify_generated_bundle_independent
from agent_world.package import file_sha256


GENERATED_RUNTIME_INDEX_REF = "release/generated-runtime-index.yaml"


@dataclass(frozen=True)
class GeneratedBundlePackageResult:
    package_dir: Path
    runtime_dir: Path
    runtime_index_path: Path
    check_record: dict[str, Any]


def assemble_generated_bundle_package(
    *,
    package_dir: Path,
    artifacts: dict[str, dict[str, Any]],
    gate_records: list[dict[str, Any]],
    review_records: list[dict[str, Any]],
    agent_invocations: list[dict[str, Any]],
    build_check_replay_records: list[dict[str, Any]],
) -> GeneratedBundlePackageResult:
    """Copy a verified GeneratedEnvironmentBundle into a stable package layout."""
    if "GeneratedEnvironmentBundle" not in artifacts:
        raise ValueError("GeneratedEnvironmentBundle is required for generated bundle packaging")
    if "ReleaseManifest" not in artifacts:
        raise ValueError("ReleaseManifest is required for generated bundle packaging")
    bundle = artifacts["GeneratedEnvironmentBundle"]
    release = artifacts["ReleaseManifest"]
    if bundle["status"] != "accepted":
        raise ValueError("Only accepted GeneratedEnvironmentBundle artifacts can be packaged")

    package_dir = Path(package_dir)
    runtime_dir_ref = f"runtime/generated/{bundle['id']}"
    runtime_dir = package_dir / runtime_dir_ref
    if runtime_dir.exists():
        shutil.rmtree(runtime_dir)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "release").mkdir(parents=True, exist_ok=True)
    (package_dir / "checks").mkdir(parents=True, exist_ok=True)
    (package_dir / "spec").mkdir(parents=True, exist_ok=True)

    copied_files = _copy_generated_files(bundle, runtime_dir=runtime_dir, runtime_dir_ref=runtime_dir_ref)
    runtime_index = _runtime_index(release=release, bundle=bundle, runtime_dir_ref=runtime_dir_ref, copied_files=copied_files)
    runtime_index_path = package_dir / GENERATED_RUNTIME_INDEX_REF
    write_yaml(runtime_index_path, runtime_index)
    write_yaml(package_dir / "release" / "release-manifest.yaml", release)
    write_yaml(package_dir / "package.yaml", artifacts["EnvironmentPackagePlan"])
    _write_optional_package_specs(package_dir, artifacts)
    write_jsonl(package_dir / "checks" / "agent-invocations.jsonl", agent_invocations)
    write_jsonl(package_dir / "checks" / "build-check-replay-records.jsonl", build_check_replay_records)
    write_yaml(package_dir / "checks" / "gate-records.yaml", {"gate_records": gate_records})
    write_yaml(package_dir / "checks" / "review-records.yaml", {"review_records": review_records})

    check_record = run_packaged_generated_bundle_check(package_dir)
    write_yaml(package_dir / "checks" / "generated-bundle-package-check.yaml", check_record)
    if not check_record["success"]:
        raise ValueError(check_record["recovery_suggestion"])
    return GeneratedBundlePackageResult(
        package_dir=package_dir,
        runtime_dir=runtime_dir,
        runtime_index_path=runtime_index_path,
        check_record=check_record,
    )


def run_packaged_generated_bundle_check(package_dir: Path) -> dict[str, Any]:
    package_dir = Path(package_dir)
    runtime_index = read_yaml(package_dir / GENERATED_RUNTIME_INDEX_REF)
    runtime_dir = package_dir / runtime_index["runtime_dir_ref"]
    command = [sys.executable, "check_replay.py"]
    try:
        completed = subprocess.run(
            command,
            cwd=runtime_dir,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        return {
            "check_id": "packaged-generated-bundle-check",
            "success": False,
            "runtime_dir_ref": runtime_index.get("runtime_dir_ref", ""),
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "positive_verifier_result": {},
            "negative_verifier_result": {},
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": "Packaged generated runtime check could not be executed.",
        }
    parsed = _parse_check_stdout(completed.stdout)
    generated_success = completed.returncode == 0 and parsed.get("success") is True
    release = read_yaml(package_dir / "release" / "release-manifest.yaml")
    accepted_tasks = _packaged_task_set(package_dir)
    independent = verify_generated_bundle_independent(
        str(release.get("environment_id", "")),
        runtime_dir,
        accepted_tasks=accepted_tasks,
        runtime_entrypoint=str(runtime_index.get("runtime_entrypoint") or ""),
        verifier_entrypoint=str(runtime_index.get("verifier_entrypoint") or "verifier.verify_task_completion"),
    )
    success = generated_success and independent.get("success") is True
    if not generated_success:
        failure_class = "packaged_generated_bundle_check_failed"
        recovery = "Inspect release/generated-runtime-index.yaml and runtime/generated files."
    elif not independent.get("success"):
        failure_class = independent.get("failure_class", "packaged_independent_generated_bundle_check_failed")
        recovery = independent.get("recovery_suggestion", "Packaged generated runtime failed independent framework verification.")
    else:
        failure_class = ""
        recovery = ""
    return {
        "check_id": "packaged-generated-bundle-check",
        "success": success,
        "runtime_dir_ref": runtime_index["runtime_dir_ref"],
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "generated_check_record": {
            "success": generated_success,
            "positive_verifier_result": parsed.get("positive_verifier_result", {}),
            "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        },
        "independent_verification_record": independent,
        "framework_check_observation": independent.get("framework_check_observation", {}),
        "independent_task_records": independent.get("task_records", []),
        "positive_verifier_result": _first_task_result(independent, "positive_verifier_result") or parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": _first_task_result(independent, "negative_verifier_result") or parsed.get("negative_verifier_result", {}),
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def _copy_generated_files(bundle: dict[str, Any], *, runtime_dir: Path, runtime_dir_ref: str) -> list[dict[str, Any]]:
    copied = []
    observed_names: set[str] = set()
    for item in bundle["generated_files"]:
        source = Path(item["path"])
        if not source.is_file():
            raise FileNotFoundError(source)
        if file_sha256(source) != item["sha256"]:
            raise ValueError(f"Generated file hash mismatch before packaging: {source}")
        target = runtime_dir / source.name
        shutil.copy2(source, target)
        copied_hash = file_sha256(target)
        if copied_hash != item["sha256"]:
            raise ValueError(f"Generated file hash mismatch after packaging: {source.name}")
        observed_names.add(source.name)
        copied.append(
            {
                "path": f"{runtime_dir_ref}/{source.name}",
                "kind": item["kind"],
                "sha256": copied_hash,
                "source_refs": list(item.get("source_refs", [])),
            }
        )
    required = {"runtime.py", "seed_state.json", "verifier.py", "surface_descriptor.json", "check_replay.py", "build_manifest.yaml"}
    missing = sorted(required - observed_names)
    if missing:
        raise ValueError(f"Generated bundle is missing required files before packaging: {missing}")
    return copied


def _runtime_index(*, release: dict[str, Any], bundle: dict[str, Any], runtime_dir_ref: str, copied_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "index_id": f"generated-runtime-index-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "generated_bundle_ref": bundle["id"],
        "runtime_dir_ref": runtime_dir_ref,
        "runtime_entrypoint": bundle["runtime_entrypoint"],
        "verifier_entrypoint": bundle["verifier_entrypoint"],
        "surface_descriptors": list(bundle.get("surface_descriptors", [])),
        "generated_files": copied_files,
        "check": {
            "cwd_ref": runtime_dir_ref,
            "command": ["python", "check_replay.py"],
        },
        "replay": {
            "cwd_ref": runtime_dir_ref,
            "commands": [["python", "check_replay.py", "--task", task_id] for task_id in release.get("task_index", [])],
        },
        "consumer_contract": {
            "kind": "generated_python_bundle",
            "load_strategy": "prepend runtime_dir_ref to sys.path and import runtime/verifier entrypoints",
            "package_relative_refs_only": True,
        },
        "status": "packaged",
    }


def _write_optional_package_specs(package_dir: Path, artifacts: dict[str, dict[str, Any]]) -> None:
    spec_paths = {
        "NeedSpec": "spec/need.yaml",
        "SourceEvidenceIndex": "sources/evidence-index.yaml",
        "KnowledgePack": "spec/knowledge-pack.yaml",
        "EnvironmentSpec": "spec/environment.yaml",
        "LogicalToolGraph": "spec/tool-graph.yaml",
        "TaskSet": "spec/tasks.yaml",
        "SurfacePlan": "spec/surfaces.yaml",
        "VerifierPlan": "spec/verifiers.yaml",
        "FeasibilityReport": "spec/feasibility.yaml",
        "ImplementationRequest": "spec/implementation-request.yaml",
        "GeneratedEnvironmentBundle": "runtime/generated-bundle.yaml",
        "IndependentVerificationReport": "checks/independent-verification-report.yaml",
    }
    for artifact_type, relative_path in spec_paths.items():
        if artifact_type not in artifacts:
            continue
        path = package_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        write_yaml(path, artifacts[artifact_type])


def _parse_check_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _packaged_task_set(package_dir: Path) -> list[dict[str, Any]]:
    task_path = package_dir / "spec" / "tasks.yaml"
    if not task_path.is_file():
        return []
    task_set = read_yaml(task_path)
    tasks = task_set.get("tasks", []) if isinstance(task_set, dict) else []
    return tasks if isinstance(tasks, list) else []


def _first_task_result(independent_record: dict[str, Any], field: str) -> dict[str, Any]:
    for record in independent_record.get("task_records", []):
        value = record.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}

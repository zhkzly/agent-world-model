from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import yaml

from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, make_artifact, stable_json
from agent_world.independent_verifier import verify_project_board_generated_bundle_independent


GENERATED_FILE_KINDS = dict(GENERATED_BUNDLE_FILE_KINDS)
DETERMINISTIC_BUNDLE_ID = "bundle-project-board-lite-generated"
AGENT_GENERATED_BUNDLE_ID = "bundle-project-board-lite-agent-generated"
DISALLOWED_FIXTURE_IMPORT = "agent_world.fixtures.project_board_lite"
PROJECT_BOARD_TASK_IDS = ["pb-task-1", "pb-task-2", "pb-task-3"]


def write_project_board_generated_files(build_dir: Path) -> None:
    _write_generated_files(Path(build_dir))


def write_project_board_agent_candidate_files(
    build_dir: Path,
    *,
    source_refs: list[str] | None = None,
    implementation_request_id: str = "impl-project-board-lite-first-slice",
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    source_refs = source_refs or ["agent-codegen-candidate"]
    _write_generated_files(build_dir)
    build_manifest = {
        "bundle_id": AGENT_GENERATED_BUNDLE_ID,
        "environment_id": "project-board-lite",
        "source_artifact_ids": source_refs,
        "implementation_request_id": implementation_request_id,
        "build_dir": ".",
        "generated_files": _generated_file_records_relative(build_dir, source_refs=source_refs, include_manifest=False),
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": _relative_replay_commands(PROJECT_BOARD_TASK_IDS),
    }
    _write_yaml(build_dir / "build_manifest.yaml", build_manifest)
    return {
        "candidate_dir": ".",
        "bundle_id": AGENT_GENERATED_BUNDLE_ID,
        "environment_id": "project-board-lite",
        "generated_files": _generated_file_records_relative(build_dir, source_refs=source_refs, include_manifest=True),
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": _relative_replay_commands(PROJECT_BOARD_TASK_IDS),
    }


def project_board_generated_implementation_record(context: Any, *, break_generated_file: str = "", forge_check_success: bool = False) -> dict[str, Any]:
    build_dir = _build_dir(context)
    task_ids = _accepted_task_ids(context)
    _write_generated_files(build_dir)
    if forge_check_success:
        _write_forged_check_replay(build_dir / "check_replay.py")
    elif break_generated_file:
        _break_generated_file(build_dir / break_generated_file)
    generated_files_without_manifest = _generated_file_records(
        build_dir,
        source_refs=_source_refs(context),
        include_manifest=False,
    )
    build_manifest = {
        "bundle_id": DETERMINISTIC_BUNDLE_ID,
        "environment_id": "project-board-lite",
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "generated_files": generated_files_without_manifest,
        "runtime_entrypoint": "runtime.ProjectBoardLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(build_dir, task_ids),
    }
    _write_yaml(build_dir / "build_manifest.yaml", build_manifest)
    generated_files = _generated_file_records(build_dir, source_refs=_source_refs(context), include_manifest=True)
    check_record = check_project_board_generated_bundle(build_dir, accepted_tasks=context.artifact("TaskSet")["tasks"], secret_values=_secret_values(context))
    build_check_replay_records = _bundle_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    bundle_artifact = make_artifact(
        "GeneratedEnvironmentBundle",
        source_stage="IMPLEMENT",
        producer="project-board-deterministic-template-codegen",
        artifact_id=DETERMINISTIC_BUNDLE_ID,
        inputs=[context.artifact("ImplementationRequest")["id"]],
        status="accepted" if status == "pass" else "fail",
        fields={
            "bundle_id": DETERMINISTIC_BUNDLE_ID,
            "environment_id": "project-board-lite",
            "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
            "implementation_request_id": context.artifact("ImplementationRequest")["id"],
            "build_dir": str(build_dir),
            "generated_files": generated_files,
            "runtime_entrypoint": "runtime.ProjectBoardLite",
            "seed_fixture_ref": "seed_state.json",
            "verifier_entrypoint": "verifier.verify_task_completion",
            "surface_descriptors": ["surface_descriptor.json"],
            "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
            "replay_commands": _absolute_replay_commands(build_dir, task_ids),
            "build_check_replay_records": build_check_replay_records,
            "implementation_mode": "deterministic_template_codegen",
        },
    )
    return {
        "implementation_id": "implementation-project-board-lite-generated",
        "mode": "deterministic_template_codegen",
        "environment_id": "project-board-lite",
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "generated_bundle_id": bundle_artifact["id"],
        "generated_environment_bundle": bundle_artifact,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "static_check_command": "validate generated bundle artifact and generated file hashes",
        "test_command": f"{sys.executable} {build_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {build_dir / 'check_replay.py'} --task pb-task-1",
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(build_dir, task_ids),
        "build_check_replay_records": build_check_replay_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Fix generated files before release planning."),
    }


def project_board_agent_generated_implementation_record(context: Any, *, agent_invocation: dict[str, Any], agent_result: Any, work_dir: Path) -> dict[str, Any]:
    work_dir = Path(work_dir)
    task_ids = _accepted_task_ids(context)
    base = {
        "implementation_id": "implementation-project-board-lite-agent-generated",
        "mode": "agent_backed_codegen",
        "environment_id": "project-board-lite",
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "agent_invocation_id": agent_invocation["id"],
        "agent_work_dir": str(work_dir),
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "static_check_command": "validate agent candidate manifest, path boundaries, generated file hashes, and fixture-import ban",
        "test_command": f"{sys.executable} {work_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {work_dir / 'check_replay.py'} --task pb-task-1",
        "check_commands": [[sys.executable, str(work_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(work_dir, task_ids),
    }
    if agent_result.status != "pass":
        return _agent_failure_record(
            base,
            status=agent_result.status,
            failure_class=agent_result.failure_class or "agent_backend_failed",
            recovery_suggestion=agent_result.recovery_suggestion or "Fix or reconfigure the code agent backend.",
        )
    manifest, manifest_error = _agent_candidate_manifest(agent_result.text, work_dir)
    if manifest_error:
        return _agent_failure_record(base, failure_class=manifest_error["failure_class"], recovery_suggestion=manifest_error["recovery_suggestion"])
    validation_error = _validate_agent_candidate_files(work_dir, manifest)
    if validation_error:
        return _agent_failure_record(base, failure_class=validation_error["failure_class"], recovery_suggestion=validation_error["recovery_suggestion"])
    bundle_dir = _agent_candidate_root(work_dir, manifest)
    if isinstance(bundle_dir, dict):
        return _agent_failure_record(base, failure_class=bundle_dir["failure_class"], recovery_suggestion=bundle_dir["recovery_suggestion"])
    generated_files = _bundle_records_from_agent_manifest(bundle_dir, manifest, fallback_source_refs=_source_refs(context))
    check_record = check_project_board_generated_bundle(bundle_dir, accepted_tasks=context.artifact("TaskSet")["tasks"], secret_values=_secret_values(context))
    build_check_replay_records = _bundle_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    check_commands = [[sys.executable, str(bundle_dir / "check_replay.py")]]
    replay_commands = _absolute_replay_commands(bundle_dir, task_ids)
    bundle_artifact = make_artifact(
        "GeneratedEnvironmentBundle",
        source_stage="IMPLEMENT",
        producer="project-board-agent-codegen",
        artifact_id=AGENT_GENERATED_BUNDLE_ID,
        inputs=[context.artifact("ImplementationRequest")["id"], agent_invocation["id"]],
        status="accepted" if status == "pass" else "fail",
        fields={
            "bundle_id": AGENT_GENERATED_BUNDLE_ID,
            "environment_id": "project-board-lite",
            "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
            "implementation_request_id": context.artifact("ImplementationRequest")["id"],
            "build_dir": str(bundle_dir),
            "generated_files": generated_files,
            "runtime_entrypoint": manifest.get("runtime_entrypoint") or "runtime.ProjectBoardLite",
            "seed_fixture_ref": manifest.get("seed_fixture_ref") or "seed_state.json",
            "verifier_entrypoint": manifest.get("verifier_entrypoint") or "verifier.verify_task_completion",
            "surface_descriptors": manifest.get("surface_descriptors") or ["surface_descriptor.json"],
            "check_commands": check_commands,
            "replay_commands": replay_commands,
            "build_check_replay_records": build_check_replay_records,
            "implementation_mode": "agent_backed_codegen",
            "agent_invocation_ref": agent_invocation["id"],
        },
    )
    return {
        **base,
        "generated_bundle_id": bundle_artifact["id"],
        "generated_environment_bundle": bundle_artifact,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "agent_candidate_dir": str(bundle_dir),
        "test_command": f"{sys.executable} {bundle_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {bundle_dir / 'check_replay.py'} --task pb-task-1",
        "check_commands": check_commands,
        "replay_commands": replay_commands,
        "build_check_replay_records": build_check_replay_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Fix agent-generated files before release planning."),
    }


def check_project_board_generated_bundle(
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    secret_values: list[str] | None = None,
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    command = [sys.executable, str(build_dir / "check_replay.py")]
    generated_check = _run_generated_check(command, build_dir)
    generated_check["stdout"] = _redact_text(generated_check.get("stdout", ""), secret_values or [])
    generated_check["stderr"] = _redact_text(generated_check.get("stderr", ""), secret_values or [])
    independent = verify_project_board_generated_bundle_independent(build_dir, accepted_tasks=accepted_tasks)
    positive = _first_task_result(independent, "positive_verifier_result")
    negative = _first_task_result(independent, "negative_verifier_result")
    success = generated_check["success"] and independent["success"]
    if not generated_check["success"]:
        failure_class = generated_check.get("failure_class", "generated_bundle_check_failed")
        recovery = generated_check.get("recovery_suggestion", "Regenerate or fix runtime/verifier/check files before release.")
    elif not independent["success"]:
        failure_class = independent.get("failure_class", "independent_generated_bundle_verification_failed")
        recovery = independent.get("recovery_suggestion", "Regenerate or repair generated runtime/verifier files before release.")
    else:
        failure_class = ""
        recovery = ""
    return {
        "check_id": "project-board-generated-check",
        "success": success,
        "command": command,
        "exit_code": generated_check.get("exit_code"),
        "stdout": generated_check.get("stdout", ""),
        "stderr": generated_check.get("stderr", ""),
        "generated_check_record": generated_check,
        "independent_verification_record": independent,
        "framework_check_observation": independent.get("framework_check_observation", {}),
        "independent_task_records": independent.get("task_records", []),
        "positive_verifier_result": positive,
        "negative_verifier_result": negative,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def _run_generated_check(command: list[str], build_dir: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=build_dir,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {
            "check_id": "project-board-generated-check",
            "success": False,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": "Generated check entrypoint could not be executed.",
        }
    parsed = _parse_check_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {
        "check_id": "project-board-generated-check",
        "success": success,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "positive_verifier_result": parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        "failure_class": "" if success else "generated_bundle_check_failed",
        "recovery_suggestion": "" if success else "Regenerate or fix runtime/verifier/check files before release.",
    }


def _accepted_task_ids(context: Any) -> list[str]:
    if "TaskSet" not in getattr(context, "artifacts", {}):
        return list(PROJECT_BOARD_TASK_IDS)
    task_ids = [str(task["task_id"]) for task in context.artifact("TaskSet").get("tasks", [])]
    return task_ids or list(PROJECT_BOARD_TASK_IDS)


def _absolute_replay_commands(build_dir: Path, task_ids: list[str]) -> list[list[str]]:
    return [[sys.executable, str(Path(build_dir) / "check_replay.py"), "--task", task_id] for task_id in task_ids]


def _relative_replay_commands(task_ids: list[str]) -> list[list[str]]:
    return [["python", "check_replay.py", "--task", task_id] for task_id in task_ids]


def _bundle_check_records(check_record: dict[str, Any]) -> list[dict[str, Any]]:
    return [check_record] + list(check_record.get("independent_task_records", []))


def _first_task_result(independent_record: dict[str, Any], field: str) -> dict[str, Any]:
    for record in independent_record.get("task_records", []):
        value = record.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}


def _secret_values(context: Any) -> list[str]:
    config = context.artifacts.get("AgentBackendConfig", {}) if hasattr(context, "artifacts") else {}
    auth = config.get("auth", {}) if isinstance(config, dict) else {}
    names = set(auth.get("auth_env_refs", []))
    if auth.get("api_key_env"):
        names.add(str(auth["api_key_env"]))
    values = []
    env = getattr(getattr(context, "config", None), "env", None) or {}
    for name in names:
        value = env.get(name) or os.environ.get(name)
        if value:
            values.append(value)
    return values


def _redact_text(text: str, secret_values: list[str]) -> str:
    redacted = text
    for value in secret_values:
        if value:
            redacted = redacted.replace(value, "[REDACTED_SECRET]")
    return redacted


def _build_dir(context: Any) -> Path:
    if context.store.root:
        return context.store.root / "build" / "generated" / "project-board-lite"
    return Path(tempfile.mkdtemp(prefix="agent-world-project-board-generated-"))


def _write_generated_files(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "runtime.py").write_text(_runtime_py(), encoding="utf-8")
    (build_dir / "seed_state.json").write_text(stable_json(_seed_state()), encoding="utf-8")
    (build_dir / "verifier.py").write_text(_verifier_py(), encoding="utf-8")
    (build_dir / "surface_descriptor.json").write_text(stable_json(_surface_descriptor()), encoding="utf-8")
    (build_dir / "check_replay.py").write_text(_check_replay_py(), encoding="utf-8")


def _generated_file_records(build_dir: Path, *, source_refs: list[str], include_manifest: bool) -> list[dict[str, Any]]:
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        if filename == "build_manifest.yaml" and not include_manifest:
            continue
        path = build_dir / filename
        records.append(
            {
                "path": str(path),
                "kind": kind,
                "sha256": _sha256(path),
                "source_refs": source_refs,
            }
        )
    return records


def _generated_file_records_relative(build_dir: Path, *, source_refs: list[str], include_manifest: bool) -> list[dict[str, Any]]:
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        if filename == "build_manifest.yaml" and not include_manifest:
            continue
        path = build_dir / filename
        records.append(
            {
                "path": filename,
                "kind": kind,
                "sha256": _sha256(path),
                "source_refs": source_refs,
            }
        )
    return records


def _agent_candidate_manifest(text: str, work_dir: Path) -> tuple[dict[str, Any], dict[str, str] | None]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}, {
            "failure_class": "malformed_agent_output",
            "recovery_suggestion": "Agent output must be a JSON candidate manifest.",
        }
    if not isinstance(parsed, dict):
        return {}, {
            "failure_class": "malformed_agent_output",
            "recovery_suggestion": "Agent output must be a JSON object.",
        }
    if "candidate_manifest_ref" in parsed and "generated_files" not in parsed:
        ref = str(parsed.get("candidate_manifest_ref") or "")
        path_error = _candidate_path_error(ref)
        if path_error:
            return {}, path_error
        root = Path(work_dir).resolve()
        manifest_path = (root / ref).resolve()
        if not _inside(manifest_path, root):
            return {}, {
                "failure_class": "path_traversal_rejected",
                "recovery_suggestion": "Agent candidate_manifest_ref must resolve inside the isolated workdir.",
            }
        if not manifest_path.is_file():
            return {}, {
                "failure_class": "missing_candidate_manifest",
                "recovery_suggestion": "Agent candidate_manifest_ref does not point to a file in the isolated workdir.",
            }
        loaded = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            return {}, {
                "failure_class": "malformed_candidate_manifest",
                "recovery_suggestion": "Agent candidate manifest file must contain an object.",
            }
        parsed = loaded
    if not isinstance(parsed.get("generated_files"), list):
        return {}, {
            "failure_class": "missing_candidate_files",
            "recovery_suggestion": "Agent candidate manifest must declare generated_files.",
        }
    return parsed, None


def _validate_agent_candidate_files(work_dir: Path, manifest: dict[str, Any]) -> dict[str, str] | None:
    candidate_root = _agent_candidate_root(work_dir, manifest)
    if isinstance(candidate_root, dict):
        return candidate_root
    root = candidate_root.resolve()
    declared: set[str] = set()
    for item in manifest.get("generated_files", []):
        if not isinstance(item, dict):
            return {
                "failure_class": "malformed_candidate_manifest",
                "recovery_suggestion": "Each generated_files item must be an object.",
            }
        rel_text = str(item.get("path") or "")
        path_error = _candidate_path_error(rel_text)
        if path_error:
            return path_error
        rel = Path(rel_text)
        rel_name = rel.as_posix()
        if rel_name in declared:
            return {
                "failure_class": "duplicate_candidate_file",
                "recovery_suggestion": "Agent candidate manifest declares the same generated file more than once.",
            }
        expected_kind = GENERATED_FILE_KINDS.get(rel_name)
        if not expected_kind:
            return {
                "failure_class": "unexpected_candidate_file",
                "recovery_suggestion": "Agent candidate may only declare runtime.py, seed_state.json, verifier.py, surface_descriptor.json, check_replay.py, and build_manifest.yaml.",
            }
        if item.get("kind") != expected_kind:
            return {
                "failure_class": "candidate_file_kind_mismatch",
                "recovery_suggestion": f"Agent candidate file {rel_name} has the wrong kind.",
            }
        actual = (candidate_root / rel).resolve()
        if not _inside(actual, root):
            return {
                "failure_class": "symlink_escape",
                "recovery_suggestion": "Agent candidate file resolves outside the candidate bundle directory.",
            }
        if not actual.is_file():
            return {
                "failure_class": "missing_generated_file",
                "recovery_suggestion": f"Agent candidate file is missing: {rel_name}",
            }
        expected_hash = str(item.get("sha256") or "")
        if len(expected_hash) != 64 or any(char not in "0123456789abcdef" for char in expected_hash):
            return {
                "failure_class": "invalid_candidate_hash",
                "recovery_suggestion": f"Agent candidate file {rel_name} must declare a lowercase sha256 hex digest.",
            }
        if expected_hash != _sha256(actual):
            return {
                "failure_class": "hash_mismatch",
                "recovery_suggestion": f"Agent candidate file hash mismatch: {rel_name}",
            }
        declared.add(rel_name)
    missing = sorted(set(GENERATED_FILE_KINDS) - declared)
    if missing:
        return {
            "failure_class": "missing_generated_file",
            "recovery_suggestion": f"Agent candidate is missing required files: {missing}",
        }
    observed = {
        path.relative_to(candidate_root).as_posix()
        for path in candidate_root.rglob("*")
        if path.is_file() and not _is_python_cache_file(path)
    }
    extra = sorted(observed - declared)
    if extra:
        return {
            "failure_class": "undeclared_generated_file",
            "recovery_suggestion": f"Agent wrote files that were not declared in the candidate manifest: {extra}",
        }
    for filename in ["runtime.py", "verifier.py", "check_replay.py"]:
        text = (candidate_root / filename).read_text(encoding="utf-8")
        if DISALLOWED_FIXTURE_IMPORT in text:
            return {
                "failure_class": "fixture_runtime_import",
                "recovery_suggestion": "Agent-generated runtime/verifier/check files must not import agent_world.fixtures.project_board_lite.",
            }
    return None


def _is_python_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _agent_candidate_root(work_dir: Path, manifest: dict[str, Any]) -> Path | dict[str, str]:
    work_root = Path(work_dir).resolve()
    candidate_dir = str(manifest.get("candidate_dir") or ".")
    if candidate_dir == ".":
        candidate_root = work_root
    else:
        path_error = _candidate_path_error(candidate_dir)
        if path_error:
            return path_error
        candidate_root = (work_root / candidate_dir).resolve()
    if not _inside(candidate_root, work_root):
        return {
            "failure_class": "path_traversal_rejected",
            "recovery_suggestion": "Agent candidate_dir must resolve inside the isolated workdir.",
        }
    if not candidate_root.is_dir():
        return {
            "failure_class": "missing_candidate_dir",
            "recovery_suggestion": "Agent candidate_dir does not exist in the isolated workdir.",
        }
    return candidate_root


def _candidate_path_error(path_text: str) -> dict[str, str] | None:
    if not path_text:
        return {
            "failure_class": "invalid_candidate_path",
            "recovery_suggestion": "Agent candidate paths must be non-empty relative paths.",
        }
    if "\\" in path_text:
        return {
            "failure_class": "invalid_candidate_path",
            "recovery_suggestion": "Agent candidate paths must use POSIX-style relative paths.",
        }
    path = Path(path_text)
    if path.is_absolute() or path_text.startswith("~"):
        return {
            "failure_class": "absolute_path_rejected",
            "recovery_suggestion": "Agent candidate paths must not be absolute or home-relative.",
        }
    if any(part in {"", ".", ".."} for part in path.parts):
        return {
            "failure_class": "path_traversal_rejected",
            "recovery_suggestion": "Agent candidate paths must not contain empty, current-directory, or parent-directory segments.",
        }
    return None


def _bundle_records_from_agent_manifest(bundle_dir: Path, manifest: dict[str, Any], *, fallback_source_refs: list[str]) -> list[dict[str, Any]]:
    by_path = {str(item["path"]): item for item in manifest["generated_files"]}
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        path = bundle_dir / filename
        source_refs = by_path.get(filename, {}).get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            source_refs = fallback_source_refs
        records.append(
            {
                "path": str(path),
                "kind": kind,
                "sha256": _sha256(path),
                "source_refs": source_refs,
            }
        )
    return records


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _agent_failure_record(base: dict[str, Any], *, failure_class: str, recovery_suggestion: str, status: str = "fail") -> dict[str, Any]:
    return {
        **base,
        "generated_paths": [],
        "generated_file_hashes": {},
        "build_check_replay_records": [],
        "verifier_result": {},
        "negative_verifier_result": {},
        "status": status,
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
    }


def _source_refs(context: Any) -> list[str]:
    refs = []
    for artifact_type in ["SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "VerifierPlan"]:
        if artifact_type in context.artifacts:
            refs.append(context.artifact(artifact_type)["id"])
    return refs


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _break_generated_file(path: Path) -> None:
    if not path.exists():
        return
    path.write_text("raise RuntimeError('generated file intentionally broken for test')\n", encoding="utf-8")


def _write_forged_check_replay(path: Path) -> None:
    path.write_text(
        "import json\n"
        "print(json.dumps({\n"
        "    'success': True,\n"
        "    'positive_verifier_result': {'success': True},\n"
        "    'negative_verifier_result': {'success': False},\n"
        "}, indent=2))\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _seed_state() -> dict[str, Any]:
    return {
        "board": [
            {"id": "board-alpha", "name": "Launch Board", "workflow_statuses": ["todo", "in_progress", "blocked", "in_review", "done"]},
        ],
        "card": [
            {"id": "C-10", "board_id": "board-alpha", "title": "Checkout bug", "status": "todo", "priority": "high", "assignee": "unassigned"},
            {"id": "C-11", "board_id": "board-alpha", "title": "Payment API failing", "status": "blocked", "priority": "urgent", "assignee": "mei"},
            {"id": "C-12", "board_id": "board-alpha", "title": "Settings page polish", "status": "in_progress", "priority": "medium", "assignee": "eve"},
        ],
        "comment": [],
        "audit_event": [],
    }


def _surface_descriptor() -> dict[str, Any]:
    return {
        "environment_id": "project-board-lite",
        "implemented_surfaces": {
            "python": {
                "status": "implemented",
                "entrypoint": "runtime.ProjectBoardLite",
                "verified_by": "check_replay.py",
            },
            "cli": {"status": "deferred", "reason": "CLI help is source evidence only for Goal 07."},
            "http": {"status": "deferred"},
            "mcp": {"status": "deferred"},
        },
    }


def _runtime_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import copy
        import hashlib
        import json
        from pathlib import Path
        from typing import Any


        def load_seed_state(seed_path: Path) -> dict[str, Any]:
            return json.loads(Path(seed_path).read_text(encoding="utf-8"))


        def reset_environment(seed_state: dict[str, Any]) -> dict[str, Any]:
            return copy.deepcopy(seed_state)


        class ProjectBoardLite:
            def __init__(self, state: dict[str, Any], *, trace_path: Path | None = None, task_id: str | None = None, call_group: str | None = None):
                self.state = state
                self.trace_path = Path(trace_path) if trace_path else None
                self.task_id = task_id
                self.call_group = call_group or task_id or "ad-hoc"

            def card_list(self, *, status: str | None = None, assignee: str | None = None, priority: str | None = None) -> list[dict[str, Any]]:
                cards = [
                    copy.deepcopy(card)
                    for card in self.state["card"]
                    if (status is None or card["status"] == status)
                    and (assignee is None or card["assignee"] == assignee)
                    and (priority is None or card["priority"] == priority)
                ]
                self._trace("card_list", {"status": status, "assignee": assignee, "priority": priority}, cards)
                return cards

            def card_get(self, card_id: str) -> dict[str, Any]:
                result = _card_detail(self.state, card_id)
                self._trace("card_get", {"card_id": card_id}, {"card_id": card_id})
                return result

            def card_move(self, *, card_id: str, status: str, note: str) -> dict[str, Any]:
                _ensure_status(self.state, status)
                card = _card(self.state, card_id)
                old = card["status"]
                card["status"] = status
                _audit(self.state, card_id, "card_moved", "status", old, status, note)
                result = _card_detail(self.state, card_id)
                self._trace("card_move", {"card_id": card_id, "status": status, "note": note}, {"card_id": card_id, "status": status})
                return result

            def card_assign(self, *, card_id: str, assignee: str, note: str) -> dict[str, Any]:
                card = _card(self.state, card_id)
                old = card["assignee"]
                card["assignee"] = assignee
                _audit(self.state, card_id, "card_assigned", "assignee", old, assignee, note)
                result = _card_detail(self.state, card_id)
                self._trace("card_assign", {"card_id": card_id, "assignee": assignee, "note": note}, {"card_id": card_id, "assignee": assignee})
                return result

            def comment_add(self, *, card_id: str, body: str) -> dict[str, Any]:
                _card(self.state, card_id)
                comment = {"card_id": card_id, "body": body, "created_by": "agent"}
                self.state["comment"].append(comment)
                _audit(self.state, card_id, "comment_added", "comment", "", body, body)
                self._trace("comment_add", {"card_id": card_id, "body": body}, comment)
                return copy.deepcopy(comment)

            def _trace(self, tool: str, inputs: dict[str, Any], output: Any) -> None:
                if not self.trace_path:
                    return
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                record = {
                    "tool": tool,
                    "task_id": self.task_id,
                    "call_group": self.call_group,
                    "inputs": inputs,
                    "output_preview": str(output)[:500],
                    "snapshot_hash": snapshot_hash(self.state),
                }
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True))
                    handle.write("\n")


        def snapshot_hash(state: dict[str, Any]) -> str:
            return hashlib.sha256(json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


        def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
            for card in state["card"]:
                if card["id"] == card_id:
                    return card
            raise KeyError(f"Unknown card: {card_id}")


        def _card_detail(state: dict[str, Any], card_id: str) -> dict[str, Any]:
            card = copy.deepcopy(_card(state, card_id))
            card["comments"] = [copy.deepcopy(comment) for comment in state["comment"] if comment["card_id"] == card_id]
            card["audit_events"] = [copy.deepcopy(event) for event in state["audit_event"] if event["card_id"] == card_id]
            return card


        def _ensure_status(state: dict[str, Any], status: str) -> None:
            statuses = state["board"][0]["workflow_statuses"]
            if status not in statuses:
                raise ValueError(f"status must be one of {statuses}")


        def _audit(state: dict[str, Any], card_id: str, event_type: str, field: str, old_value: str, new_value: str, note: str) -> None:
            state["audit_event"].append(
                {
                    "card_id": card_id,
                    "event_type": event_type,
                    "field": field,
                    "old_value": old_value,
                    "new_value": new_value,
                    "note": note,
                }
            )
        '''
    ).lstrip()


def _verifier_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any


        def verify_task_completion(
            task_id: str,
            initial_state: dict[str, Any],
            final_state: dict[str, Any],
            final_answer: Any = None,
            surface_trace_path: Path | None = None,
            expected_dependency_path: list[str] | None = None,
            trace_call_group: str | None = None,
        ) -> dict[str, Any]:
            checks: list[dict[str, Any]] = []

            def add(name: str, passed: bool, detail: Any) -> None:
                checks.append({"name": name, "passed": bool(passed), "detail": detail})

            expected_dependency_path = expected_dependency_path or _expected_dependency_path(task_id)
            add(
                "dependency_path_trace_matches",
                bool(surface_trace_path and expected_dependency_path and _trace_matches(surface_trace_path, task_id, expected_dependency_path, trace_call_group)),
                {"trace_path": str(surface_trace_path) if surface_trace_path else "", "expected": expected_dependency_path},
            )
            if task_id == "pb-task-1":
                add("target_card_moved", _card(final_state, "C-11")["status"] == "in_review", _card(final_state, "C-11"))
                add("audit_written", _has_audit(final_state, "C-11", "card_moved", "status", "in_review"), final_state["audit_event"])
                add("non_target_cards_preserved", _non_target_cards_preserved(initial_state, final_state, {"C-11"}), "")
            elif task_id == "pb-task-2":
                add("target_card_assigned", _card(final_state, "C-10")["assignee"] == "sam", _card(final_state, "C-10"))
                add("target_comment_added", any(comment["card_id"] == "C-10" and "triage" in comment["body"].lower() for comment in final_state["comment"]), final_state["comment"])
                add("audit_written", _has_audit(final_state, "C-10", "card_assigned", "assignee", "sam"), final_state["audit_event"])
                add("non_target_cards_preserved", _non_target_cards_preserved(initial_state, final_state, {"C-10"}), "")
            elif task_id == "pb-task-3":
                expected = {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"}
                add("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer})
                add("state_unchanged", initial_state == final_state, "")
            else:
                add("known_task", False, task_id)
            return {"task_id": task_id, "success": all(check["passed"] for check in checks), "checks": checks}


        def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
            for card in state["card"]:
                if card["id"] == card_id:
                    return card
            raise KeyError(f"Unknown card: {card_id}")


        def _has_audit(state: dict[str, Any], card_id: str, event_type: str, field: str, new_value: str) -> bool:
            return any(
                event["card_id"] == card_id
                and event["event_type"] == event_type
                and event["field"] == field
                and event["new_value"] == new_value
                for event in state["audit_event"]
            )


        def _non_target_cards_preserved(initial: dict[str, Any], final: dict[str, Any], target_ids: set[str]) -> bool:
            initial_cards = {card["id"]: card for card in initial["card"] if card["id"] not in target_ids}
            final_cards = {card["id"]: card for card in final["card"] if card["id"] not in target_ids}
            return initial_cards == final_cards


        def _expected_dependency_path(task_id: str) -> list[str]:
            return {
                "pb-task-1": ["card_list", "card_get", "card_move"],
                "pb-task-2": ["card_list", "card_assign", "comment_add"],
                "pb-task-3": ["card_list"],
            }.get(task_id, [])


        def _trace_matches(trace_path: Path, task_id: str, expected: list[str], call_group: str | None) -> bool:
            if not trace_path.exists():
                return False
            records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            filtered = [
                record
                for record in records
                if record.get("task_id") == task_id and (call_group is None or record.get("call_group") == call_group)
            ]
            return [record["tool"] for record in filtered] == expected
        '''
    ).lstrip()


def _check_replay_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        from runtime import ProjectBoardLite, load_seed_state, reset_environment
        from verifier import verify_task_completion


        ROOT = Path(__file__).resolve().parent
        TASK_IDS = ["pb-task-1", "pb-task-2", "pb-task-3"]


        def main(argv: list[str] | None = None) -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("--task", choices=TASK_IDS)
            args = parser.parse_args(argv)
            seed = load_seed_state(ROOT / "seed_state.json")
            task_ids = [args.task] if args.task else TASK_IDS
            task_results = [run_task(seed, task_id) for task_id in task_ids]
            summary = {
                "success": all(item["success"] for item in task_results),
                "task_results": task_results,
                "positive_verifier_result": task_results[0]["positive_verifier_result"] if task_results else {},
                "negative_verifier_result": task_results[0]["negative_verifier_result"] if task_results else {},
            }
            print(json.dumps(summary, sort_keys=True))
            return 0 if summary["success"] else 1


        def run_task(seed: dict, task_id: str) -> dict:
            initial = reset_environment(seed)
            final = reset_environment(seed)
            trace = ROOT / f"{task_id}-positive-trace.jsonl"
            if trace.exists():
                trace.unlink()
            final_answer = execute_positive(surface=ProjectBoardLite(final, trace_path=trace, task_id=task_id, call_group="positive"), task_id=task_id)
            positive = verify_task_completion(task_id, initial, final, final_answer=final_answer, surface_trace_path=trace, trace_call_group="positive")

            negative_initial = reset_environment(seed)
            negative_final = reset_environment(seed)
            negative_trace = ROOT / f"{task_id}-negative-trace.jsonl"
            if negative_trace.exists():
                negative_trace.unlink()
            negative_answer = {"status": "in_progress", "assignee": "eve", "card_count": 0, "highest_priority": "none"} if task_id == "pb-task-3" else None
            negative = verify_task_completion(task_id, negative_initial, negative_final, final_answer=negative_answer, surface_trace_path=negative_trace, trace_call_group="negative")
            return {
                "task_id": task_id,
                "success": positive["success"] is True and negative["success"] is False,
                "positive_verifier_result": positive,
                "negative_verifier_result": negative,
            }


        def execute_positive(surface: ProjectBoardLite, task_id: str):
            if task_id == "pb-task-1":
                surface.card_list(status="blocked")
                surface.card_get("C-11")
                surface.card_move(card_id="C-11", status="in_review", note="Ready for review after checking the blocker.")
                return None
            if task_id == "pb-task-2":
                surface.card_list(priority="high")
                surface.card_assign(card_id="C-10", assignee="sam", note="Sam is taking triage.")
                surface.comment_add(card_id="C-10", body="Triage comment added for Sam.")
                return None
            cards = surface.card_list(status="in_progress", assignee="eve")
            return {
                "status": "in_progress",
                "assignee": "eve",
                "card_count": len(cards),
                "highest_priority": "medium" if cards else "none",
            }


        if __name__ == "__main__":
            sys.exit(main())
        '''
    ).lstrip()

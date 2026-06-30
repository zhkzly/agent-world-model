from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_world.artifacts import GENERATED_PROJECT_FILE_KINDS, RUNTIME_ABI_INTERFACES


FRAMEWORK_REPLAY_CONTRACT_SCHEMA_VERSION = "agent-world.framework-replay-contract.v1"
FRAMEWORK_CHECK_OBSERVATION_SCHEMA_VERSION = "agent-world.framework-check-observation.v1"


def build_framework_replay_contract(artifacts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the machine-readable replay contract given to code-agent runners."""
    implementation = artifacts.get("ImplementationRequest", {})
    environment = artifacts.get("EnvironmentSpec", {})
    surface = artifacts.get("SurfacePlan", {})
    task_set = artifacts.get("TaskSet", {})
    verifier_plan = artifacts.get("VerifierPlan", {})
    environment_id = str(implementation.get("environment_id") or environment.get("environment_id") or "")
    runtime_contract = runtime_contract_from_artifacts(surface)
    tasks = list(task_set.get("tasks", []))
    return {
        "schema_version": FRAMEWORK_REPLAY_CONTRACT_SCHEMA_VERSION,
        "environment_id": environment_id,
        "candidate_dir": "generated",
        "source_artifact_ids": _artifact_ids(artifacts),
        "project_layout": {
            "candidate_dir": "generated",
            "required_refs": ["contract.json", "source/", "state/", "adapters/", "scripts/", "spec/"],
            "file_kinds": sorted(GENERATED_PROJECT_FILE_KINDS),
        },
        "manifest_contract": {
            "candidate_dir": "generated",
            "contract_ref": "contract.json",
            "generated_file_kinds": sorted(GENERATED_PROJECT_FILE_KINDS),
            "path_rule": "generated_files[].path is relative to candidate_dir; use source/app.py, not generated/source/app.py and not an absolute path.",
            "required_fields_per_generated_file": ["path", "kind", "sha256", "source_refs"],
        },
        "runtime_contract": runtime_contract,
        "trace_contract": {
            "format": "json object returned by export_trace",
            "required_event_fields": ["episode_id", "tool_id", "step_index"],
            "order_must_match_dependency_path": True,
        },
        "replay_cases": [_replay_case(task) for task in tasks],
        "verifier_plan_refs": [verifier.get("verifier_id", "") for verifier in verifier_plan.get("verifiers", [])],
        "framework_check": {
            "kind": "framework_owned_candidate_check",
            "command": ["uv", "run", "--offline", "python", "-m", "agent_world.candidate_check", "--environment-id", environment_id, "--candidate-dir", "<agent-workspace>/generated"],
            "execution_context": "framework-owned gate; run from the project repository after the runner exits, or by a runner only if it can import agent_world safely",
            "release_authority": "Final release is decided by the framework after the runner exits, not by runner stdout or generated self-check.",
        },
    }


def runtime_contract_from_artifacts(surface_plan: dict[str, Any]) -> dict[str, Any]:
    bindings = [
        binding
        for binding in surface_plan.get("bindings", [])
        if binding.get("logical_tool_id")
    ]
    return {
        "runtime_abi_version": "agent-world.runtime-abi.v1",
        "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
        "interface_entrypoint_shape": "contract.json interfaces.<name>.entrypoint, usually module:function relative to generated/",
        "logical_tool_ids": [str(binding["logical_tool_id"]) for binding in bindings],
        "invoke_contract": {
            "input_keys": ["episode_id", "task", "task_id", "tool_id", "arguments", "step_index"],
            "trace_requirement": "invoke must create export_trace evidence in dependency_path order",
        },
        "verify_contract": {
            "positive_result": {"success": True},
            "negative_result": {"success": False},
        },
    }


def observation_from_independent_report(
    report: dict[str, Any],
    *,
    candidate_dir: Path | None = None,
    candidate_dir_ref: str = "generated",
) -> dict[str, Any]:
    prereq = [
        _prerequisite_observation(item, candidate_dir=candidate_dir)
        for item in report.get("prerequisite_checks", [])
    ]
    tasks = [
        _task_observation_from_record(item, candidate_dir=candidate_dir)
        for item in report.get("task_records", [])
    ]
    failed_tasks = [item for item in tasks if item.get("success") is False]
    failed_prereq = [item for item in prereq if item.get("passed") is False]
    exception = _first_exception(failed_tasks) or _first_exception(failed_prereq)
    return {
        "schema_version": FRAMEWORK_CHECK_OBSERVATION_SCHEMA_VERSION,
        "check_id": report.get("check_id", ""),
        "status": "pass" if report.get("success") is True else "fail",
        "success": report.get("success") is True,
        "environment_id": report.get("environment_id", ""),
        "candidate_dir_ref": candidate_dir_ref,
        "failure_class": report.get("failure_class", ""),
        "recovery_suggestion": report.get("recovery_suggestion", ""),
        "accepted_task_ids": list(report.get("accepted_task_ids", [])),
        "verified_task_ids": list(report.get("verified_task_ids", [])),
        "failed_task_ids": [item.get("task_id", "") for item in failed_tasks if item.get("task_id")],
        "prerequisite_observations": prereq,
        "task_observations": tasks,
        "exception": exception or {},
        "summary": {
            "prerequisite_failures": len(failed_prereq),
            "task_failures": len(failed_tasks),
            "unsupported_task_ids": list(report.get("unsupported_task_ids", [])),
        },
    }


def exception_payload(exc: BaseException, *, phase: str = "", traceback_text: str = "") -> dict[str, Any]:
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "phase": phase,
        "traceback": traceback_text,
    }


def _artifact_ids(artifacts: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        name: str(artifact.get("id", ""))
        for name, artifact in artifacts.items()
        if isinstance(artifact, dict) and artifact.get("id")
    }


def _replay_case(task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id", ""))
    replay = task.get("framework_replay", {}) if isinstance(task.get("framework_replay"), dict) else {}
    tool_calls = replay.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        tool_calls = [{"tool": tool, "kwargs": {}} for tool in task.get("dependency_path") or task.get("allowed_logical_tool_ids", [])]
    return {
        "case_id": f"framework-replay-{task_id}",
        "task_id": task_id,
        "kind": "tool_call_replay",
        "natural_request": task.get("natural_request", ""),
        "expected_dependency_path": list(task.get("dependency_path") or task.get("allowed_logical_tool_ids", [])),
        "tool_calls": tool_calls,
        "expected_state_or_answer": {
            "expected_state_delta": task.get("expected_state_delta", {}),
            "expected_answer": task.get("expected_answer", ""),
            "expected_final_answer": replay.get("expected_final_answer", task.get("expected_answer", "")),
        },
        "negative_case": {
            "must_return_success": False,
            "description": "Verifier must reject missing or wrong state/action/answer evidence.",
        },
    }


def _prerequisite_observation(item: dict[str, Any], *, candidate_dir: Path | None) -> dict[str, Any]:
    return {
        "name": item.get("name", ""),
        "passed": item.get("passed") is True,
        "phase": "prerequisite",
        "detail": _sanitize_value(item.get("detail", {}), candidate_dir=candidate_dir),
        "exception": _sanitize_value(item.get("exception", {}), candidate_dir=candidate_dir),
    }


def _task_observation_from_record(item: dict[str, Any], *, candidate_dir: Path | None) -> dict[str, Any]:
    if isinstance(item.get("task_observation"), dict):
        return _sanitize_value(item["task_observation"], candidate_dir=candidate_dir)
    evidence = item.get("framework_evidence", {}) if isinstance(item.get("framework_evidence"), dict) else {}
    trace_evidence = evidence.get("dependency_trace", {}) if isinstance(evidence.get("dependency_trace"), dict) else {}
    state_evidence = evidence.get("expected_state_or_answer", {}) if isinstance(evidence.get("expected_state_or_answer"), dict) else {}
    positive = item.get("positive_verifier_result", {}) if isinstance(item.get("positive_verifier_result"), dict) else {}
    negative = item.get("negative_verifier_result", {}) if isinstance(item.get("negative_verifier_result"), dict) else {}
    exception = item.get("exception", {})
    if not exception and isinstance(positive.get("exception"), dict):
        exception = positive["exception"]
    if not exception and isinstance(negative.get("exception"), dict):
        exception = negative["exception"]
    return _sanitize_value(
        {
            "task_id": item.get("task_id", ""),
            "case_id": f"framework-replay-{item.get('task_id', '')}",
            "success": item.get("success") is True,
            "phase": item.get("phase", "task_replay"),
            "failure_class": item.get("failure_class", ""),
            "stderr": item.get("stderr", ""),
            "expected": {
                "dependency_trace": trace_evidence.get("expected", []),
                "state_or_answer": state_evidence.get("expected", state_evidence.get("kind", "")),
            },
            "actual": {
                "dependency_trace": trace_evidence.get("actual", []),
                "state_or_answer": state_evidence.get("actual", state_evidence),
            },
            "positive_verifier_result": positive,
            "negative_verifier_result": negative,
            "trace_evidence": trace_evidence,
            "state_or_answer_evidence": state_evidence,
            "exception": exception,
            "recovery_suggestion": item.get("recovery_suggestion", ""),
        },
        candidate_dir=candidate_dir,
    )


def _first_exception(items: list[dict[str, Any]]) -> dict[str, Any]:
    for item in items:
        exception = item.get("exception")
        if isinstance(exception, dict) and exception.get("type"):
            return exception
    return {}


def _sanitize_value(value: Any, *, candidate_dir: Path | None) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_value_for_key(key, item, candidate_dir=candidate_dir) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(item, candidate_dir=candidate_dir) for item in value]
    return value


def _sanitize_value_for_key(key: Any, value: Any, *, candidate_dir: Path | None) -> Any:
    if isinstance(value, str) and str(key) in {"path", "trace_path"}:
        return _sanitize_path(value, candidate_dir=candidate_dir)
    return _sanitize_value(value, candidate_dir=candidate_dir)


def _sanitize_path(value: str, *, candidate_dir: Path | None) -> str:
    path = Path(value)
    if candidate_dir is not None:
        try:
            return path.resolve().relative_to(candidate_dir.resolve()).as_posix()
        except (OSError, ValueError):
            pass
    if path.is_absolute():
        return f"<framework-temp>/{path.name}"
    return value

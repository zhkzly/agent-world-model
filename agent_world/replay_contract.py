from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS


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
        "bundle_files": [
            {"path": path, "kind": kind}
            for path, kind in GENERATED_BUNDLE_FILE_KINDS.items()
        ],
        "manifest_contract": {
            "candidate_dir": "generated",
            "generated_file_kinds": dict(GENERATED_BUNDLE_FILE_KINDS),
            "path_rule": "generated_files[].path is relative to candidate_dir; use runtime.py, not generated/runtime.py or an absolute path.",
            "required_fields_per_generated_file": ["path", "kind", "sha256", "source_refs"],
        },
        "runtime_contract": runtime_contract,
        "verifier_contract": {
            "entrypoint": "verifier.verify_task_completion",
            "signature": "verify_task_completion(task_id, initial_state, final_state, *, surface_trace_path, expected_dependency_path, trace_call_group, final_answer)",
            "required_kwargs": ["surface_trace_path", "expected_dependency_path", "trace_call_group", "final_answer"],
            "positive_result": {"success": True},
            "negative_result": {"success": False},
        },
        "trace_contract": {
            "format": "jsonl",
            "required_fields": ["tool", "task_id", "call_group"],
            "positive_call_group": "positive",
            "negative_call_group": "negative",
            "order_must_match_dependency_path": True,
        },
        "replay_cases": [_replay_case(environment_id, task) for task in tasks],
        "verifier_plan_refs": [verifier.get("verifier_id", "") for verifier in verifier_plan.get("verifiers", [])],
        "framework_check": {
            "kind": "framework_owned_candidate_check",
            "command": ["uv", "run", "--offline", "python", "-m", "agent_world.candidate_check", "--environment-id", environment_id, "--candidate-dir", "<agent-workspace>/generated"],
            "execution_context": "framework-owned gate; run from the project repository after the runner exits, or by a runner only if it can import agent_world safely",
            "release_authority": "Final release is decided by the framework after the runner exits, not by runner stdout or generated check_replay.py.",
        },
    }


def runtime_contract_from_artifacts(surface_plan: dict[str, Any]) -> dict[str, Any]:
    bindings = [
        binding
        for binding in surface_plan.get("bindings", [])
        if binding.get("surface") == "python" and binding.get("logical_tool_id")
    ]
    python_methods = [str(binding.get("method_name") or binding["logical_tool_id"]) for binding in bindings]
    runtime_class = ""
    for binding in bindings:
        exposure = str(binding.get("exposure_name") or "")
        if "." in exposure:
            runtime_class = exposure.split(".", 1)[0]
            break
    if not runtime_class:
        runtime_class = "GeneratedEnvironment"
    return {
        "entrypoint": f"runtime.{runtime_class}",
        "constructor": {
            "args": ["state"],
            "kwargs": ["trace_path", "task_id", "call_group"],
        },
        "helpers": [
            {"name": "runtime.load_seed_state", "signature": "load_seed_state(seed_path)"},
            {"name": "runtime.reset_environment", "signature": "reset_environment(seed_state)"},
        ],
        "required_methods": python_methods,
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


def _replay_case(environment_id: str, task: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id", ""))
    return {
        "case_id": f"framework-replay-{task_id}",
        "task_id": task_id,
        "kind": "tool_call_replay",
        "natural_request": task.get("natural_request", ""),
        "expected_dependency_path": list(task.get("dependency_path") or task.get("allowed_logical_tool_ids", [])),
        "tool_calls": _tool_calls(environment_id, task_id),
        "expected_state_or_answer": {
            "expected_state_delta": task.get("expected_state_delta", {}),
            "expected_answer": task.get("expected_answer", ""),
        },
        "negative_case": {
            "must_return_success": False,
            "description": "Verifier must reject missing or wrong state/action/answer evidence.",
        },
    }


def _tool_calls(environment_id: str, task_id: str) -> list[dict[str, Any]]:
    cases: dict[tuple[str, str], list[dict[str, Any]]] = {
        ("booking-service-lite", "booking-task-1"): [
            {"tool": "search_events", "kwargs": {"city": "Shanghai", "kind": "concert"}, "expects": {"type": "list", "first_item_fields": ["event_id"]}},
            {"tool": "check_availability", "kwargs_from": {"event_id": "search_events[0].event_id"}, "expects": {"fields": ["event_id", "available_seats", "price"]}},
            {"tool": "hold_seats", "kwargs_from": {"event_id": "search_events[0].event_id"}, "kwargs": {"quantity": 2, "customer_id": "C-1"}, "expects": {"fields": ["hold_id"]}},
            {"tool": "confirm_booking", "kwargs_from": {"hold_id": "hold_seats.hold_id"}, "kwargs": {"payment_status": "authorized"}},
        ],
        ("booking-service-lite", "booking-task-2"): [
            {"tool": "cancel_booking", "kwargs": {"booking_id": "B-200", "refund": True}},
        ],
        ("booking-service-lite", "booking-task-3"): [
            {"tool": "search_events", "kwargs": {"city": "Shanghai", "kind": "concert"}, "expects": {"type": "list", "first_item_fields": ["event_id"]}},
            {"tool": "check_availability", "kwargs_from": {"event_id": "search_events[0].event_id"}, "expects": {"fields": ["event_id", "available_seats", "price"]}},
        ],
        ("library-lending-lite", "library-task-1"): [
            {"tool": "search_books", "kwargs": {"keyword": "distributed"}, "expects": {"type": "list", "first_item_fields": ["book_id"]}},
            {"tool": "check_availability", "kwargs_from": {"book_id": "search_books[0].book_id"}, "expects": {"fields": ["book_id", "available_copies", "title"]}},
            {"tool": "borrow_book", "kwargs_from": {"book_id": "search_books[0].book_id"}, "kwargs": {"patron_id": "P-1"}},
        ],
        ("library-lending-lite", "library-task-2"): [
            {"tool": "return_book", "kwargs": {"loan_id": "L-200", "days_late": 2}},
        ],
        ("library-lending-lite", "library-task-3"): [
            {"tool": "search_books", "kwargs": {"keyword": "distributed"}, "expects": {"type": "list", "first_item_fields": ["book_id"]}},
            {"tool": "check_availability", "kwargs_from": {"book_id": "search_books[0].book_id"}, "expects": {"fields": ["book_id", "available_copies", "title"]}},
        ],
        ("project-board-lite", "pb-task-1"): [
            {"tool": "card_list", "kwargs": {"status": "blocked"}, "expects": {"type": "list"}},
            {"tool": "card_get", "args": ["C-11"], "expects": {"type": "object"}},
            {"tool": "card_move", "kwargs": {"card_id": "C-11", "status": "in_review", "note": "Ready for review after checking the blocker."}},
        ],
        ("project-board-lite", "pb-task-2"): [
            {"tool": "card_list", "kwargs": {"priority": "high"}, "expects": {"type": "list"}},
            {"tool": "card_assign", "kwargs": {"card_id": "C-10", "assignee": "sam", "note": "Sam is taking triage."}},
            {"tool": "comment_add", "kwargs": {"card_id": "C-10", "body": "Triage comment added for Sam."}},
        ],
        ("project-board-lite", "pb-task-3"): [
            {"tool": "card_list", "kwargs": {"status": "in_progress", "assignee": "eve"}, "expects": {"type": "list"}},
        ],
    }
    return cases.get((environment_id, task_id), [])


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

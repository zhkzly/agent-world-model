from __future__ import annotations

import importlib
import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

from agent_world.artifacts import RUNTIME_ABI_INTERFACES
from agent_world.replay_contract import exception_payload, normalise_framework_replay_calls, observation_from_independent_report


def verify_generated_project_independent(
    environment_id: str,
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    contract_ref: str = "contract.json",
) -> dict[str, Any]:
    """Framework-owned verifier for contract-project generated environments."""
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_contract_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    original_path = list(sys.path)
    original_modules = dict(sys.modules)
    teardown_fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    try:
        sys.path.insert(0, str(build_dir))
        source_dir = build_dir / "source"
        if source_dir.is_dir():
            sys.path.insert(0, str(source_dir))
        contract_path = (build_dir / contract_ref).resolve()
        if not _inside(contract_path, build_dir) or not contract_path.is_file():
            raise FileNotFoundError(contract_path)
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        prereq_checks.extend(_contract_static_checks(contract, environment_id=environment_id, contract_ref=contract_ref))
        interfaces = _load_interfaces(contract, build_dir)
        prereq_checks.extend(
            [
                _check(f"interface_{name}_loadable", callable(interfaces.get(name)), {"interface": name})
                for name in sorted(RUNTIME_ABI_INTERFACES)
            ]
        )
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated project prerequisite checks failed")
        teardown_fn = interfaces["teardown"]
        setup_result = _call_interface(interfaces["setup"], {"environment_id": environment_id, "candidate_dir": str(build_dir)}, "setup")
        prereq_checks.append(_check("setup_passed", _status_ok(setup_result), {"result": setup_result}))
        health_result = _call_interface(interfaces["health"], {"environment_id": environment_id}, "health")
        prereq_checks.append(_check("health_passed", _status_ok(health_result), {"result": health_result}))
        if not tasks:
            prereq_checks.append(_check("accepted_tasks_present", False, {"accepted_task_count": 0}))
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated project setup or health checks failed")
        for task in tasks:
            try:
                task_records.append(_verify_contract_task(environment_id, task, interfaces=interfaces))
            except Exception as exc:
                task_records.append(
                    _task_exception_record(
                        environment_id,
                        task["task_id"],
                        exception_payload(exc, phase="task_replay", traceback_text=traceback.format_exc()),
                        phase="task_replay",
                    )
                )
    except Exception as exc:
        exc_info = exception_payload(exc, phase="prerequisite", traceback_text=traceback.format_exc())
        if not prereq_checks:
            failed = _check("independent_verifier_prerequisites", False, {"error": f"{exc.__class__.__name__}: {exc}"})
            failed["exception"] = exc_info
            prereq_checks.append(failed)
        for task in tasks:
            if any(record.get("task_id") == task["task_id"] for record in task_records):
                continue
            task_records.append(
                _task_exception_record(
                    environment_id,
                    task["task_id"],
                    exc_info,
                    phase="prerequisite",
                    prerequisite_checks=prereq_checks,
                )
            )
    finally:
        try:
            if teardown_fn is not None:
                _call_interface(teardown_fn, {"environment_id": environment_id}, "teardown")
        except Exception:
            pass
        sys.path[:] = original_path
        _restore_modules(original_modules)

    accepted_task_ids = [task["task_id"] for task in tasks]
    verified_task_ids = [record["task_id"] for record in task_records if record.get("success") is True]
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and bool(accepted_task_ids)
    failure_class = "" if success else "independent_generated_project_verification_failed"
    recovery = "" if success else "Regenerate or repair the generated project so contract, runtime ABI, traces, and deterministic verification pass independently."
    report = {
        "check_id": "contract-independent-generated-project-verifier",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_project",
        "environment_id": environment_id,
        "command": "framework load contract.json and exercise describe/setup/reset/health/invoke/verify/export_trace/teardown",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "accepted_task_ids": accepted_task_ids,
        "verified_task_ids": verified_task_ids,
        "unsupported_task_ids": [],
        "prerequisite_checks": prereq_checks,
        "task_records": task_records,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }
    report["framework_check_observation"] = observation_from_independent_report(report, candidate_dir=build_dir)
    return report


def _contract_static_checks(contract: dict[str, Any], *, environment_id: str, contract_ref: str) -> list[dict[str, Any]]:
    interfaces = contract.get("interfaces", {})
    observed = set(interfaces) if isinstance(interfaces, dict) else set()
    return [
        _check("contract_ref_loaded", True, {"contract_ref": contract_ref}),
        _check("contract_environment_id_matches", str(contract.get("environment_id", "")) == environment_id, {"expected": environment_id, "actual": contract.get("environment_id", "")}),
        _check("contract_runtime_abi_version", contract.get("runtime_abi_version") == "agent-world.runtime-abi.v1", {"actual": contract.get("runtime_abi_version", "")}),
        _check("contract_required_interfaces", observed == set(RUNTIME_ABI_INTERFACES), {"expected": sorted(RUNTIME_ABI_INTERFACES), "actual": sorted(observed)}),
    ]


def _load_interfaces(contract: dict[str, Any], build_dir: Path) -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    interface_specs = contract.get("interfaces", {})
    if not isinstance(interface_specs, dict):
        return {}
    top_names = set()
    for spec in interface_specs.values():
        entrypoint = spec if isinstance(spec, str) else str(spec.get("entrypoint") or "") if isinstance(spec, dict) else ""
        module_name = entrypoint.split(":", 1)[0] if ":" in entrypoint else entrypoint.rpartition(".")[0]
        if module_name:
            top_names.add(module_name.split(".", 1)[0])
    for top_name in top_names:
        for name in list(sys.modules):
            if name == top_name or name.startswith(f"{top_name}."):
                sys.modules.pop(name, None)
    importlib.invalidate_caches()
    loaded: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
    for name in RUNTIME_ABI_INTERFACES:
        spec = interface_specs.get(name)
        if isinstance(spec, str):
            entrypoint = spec
            kind = "python_callable"
        elif isinstance(spec, dict):
            entrypoint = str(spec.get("entrypoint") or "")
            kind = str(spec.get("kind") or "python_callable")
        else:
            continue
        if kind not in {"python_callable", "python"}:
            continue
        fn = _load_entrypoint(entrypoint, build_dir)
        if callable(fn):
            loaded[name] = fn
    return loaded


def _load_entrypoint(entrypoint: str, build_dir: Path) -> Any:
    if not entrypoint or "/" in entrypoint or "\\" in entrypoint:
        return None
    if ":" in entrypoint:
        module_name, attr_path = entrypoint.split(":", 1)
    else:
        module_name, _, attr_path = entrypoint.rpartition(".")
    if not module_name or not attr_path:
        return None
    module = importlib.import_module(module_name)
    value: Any = module
    for part in attr_path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _verify_contract_task(
    environment_id: str,
    task: dict[str, Any],
    *,
    interfaces: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
) -> dict[str, Any]:
    task_id = task["task_id"]
    reset = _call_interface(interfaces["reset"], {"environment_id": environment_id, "task": task, "task_id": task_id, "case": "positive"}, "reset")
    episode_id = str(reset.get("episode_id") or f"{task_id}-positive")
    expected_path = list(task.get("dependency_path", []))
    invoked_tools = []
    for step_index, call in enumerate(normalise_framework_replay_calls(task)):
        tool_id = str(call.get("tool") or "")
        kwargs = call.get("kwargs", {})
        if not isinstance(kwargs, dict):
            kwargs = {}
        invoke_result = _call_interface(
            interfaces["invoke"],
            {
                "environment_id": environment_id,
                "episode_id": episode_id,
                "task": task,
                "task_id": task_id,
                "tool_id": tool_id,
                "arguments": kwargs,
                "step_index": step_index,
            },
            "invoke",
        )
        invoked_tools.append(str(invoke_result.get("tool_id") or tool_id))
    positive = _call_interface(
        interfaces["verify"],
        {
            "environment_id": environment_id,
            "episode_id": episode_id,
            "task": task,
            "task_id": task_id,
            "case": "positive",
            "expected_dependency_path": expected_path,
            "expected_answer": task.get("expected_answer"),
            "expected_state_delta": task.get("expected_state_delta", {}),
        },
        "verify",
    )
    trace = _call_interface(
        interfaces["export_trace"],
        {"environment_id": environment_id, "episode_id": episode_id, "task": task, "task_id": task_id},
        "export_trace",
    )
    trace_tools = _trace_tools(trace) or invoked_tools

    negative_reset = _call_interface(interfaces["reset"], {"environment_id": environment_id, "task": task, "task_id": task_id, "case": "negative"}, "reset")
    negative_episode_id = str(negative_reset.get("episode_id") or f"{task_id}-negative")
    negative = _call_interface(
        interfaces["verify"],
        {
            "environment_id": environment_id,
            "episode_id": negative_episode_id,
            "task": task,
            "task_id": task_id,
            "case": "negative",
            "expected_dependency_path": expected_path,
            "expected_answer": task.get("expected_answer"),
            "expected_state_delta": task.get("expected_state_delta", {}),
        },
        "verify",
    )

    trace_evidence = {"expected": expected_path, "actual": trace_tools, "success": trace_tools == expected_path}
    positive_success = positive.get("success") is True
    negative_success = negative.get("success") is False
    success = positive_success and negative_success and trace_evidence["success"]
    return {
        "check_id": f"contract-project-independent-{task_id}",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_project",
        "environment_id": environment_id,
        "task_id": task_id,
        "command": "framework ABI reset/invoke/verify/export_trace",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "positive_verifier_result": positive,
        "negative_verifier_result": negative,
        "framework_evidence": {
            "dependency_trace": trace_evidence,
            "positive_case_success": positive_success,
            "negative_case_failed": negative_success,
            "reset": {"episode_id": episode_id, "result": reset},
            "export_trace": trace,
        },
        "failure_class": "" if success else "independent_task_verification_failed",
        "recovery_suggestion": "" if success else "Generated project ABI did not satisfy the framework replay contract for this accepted task.",
    }


def _call_interface(fn: Callable[[dict[str, Any]], Any], payload: dict[str, Any], name: str) -> dict[str, Any]:
    result = fn(payload)
    if not isinstance(result, dict):
        return {"status": "fail", "success": False, "error": {"code": "non_object_result", "interface": name}, "result": result}
    return result


def _status_ok(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or "pass")
    return status in {"pass", "ok", "accepted"} and result.get("success", True) is not False


def _trace_tools(trace: dict[str, Any]) -> list[str]:
    events = trace.get("events")
    if not isinstance(events, list):
        return []
    tools = []
    for event in events:
        if not isinstance(event, dict):
            continue
        tool_id = event.get("tool_id", event.get("tool"))
        if tool_id:
            tools.append(str(tool_id))
    return tools


def _normalise_contract_tasks(accepted_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    tasks = []
    for item in accepted_tasks or []:
        task = dict(item)
        if "dependency_path" not in task:
            task["dependency_path"] = list(task.get("allowed_logical_tool_ids", []))
        replay = task.get("framework_replay")
        replay_base = replay if isinstance(replay, dict) else {}
        task["framework_replay"] = {**replay_base, "tool_calls": normalise_framework_replay_calls(task)}
        tasks.append(task)
    return tasks


def _task_exception_record(
    environment_id: str,
    task_id: str,
    exc_info: dict[str, Any],
    *,
    phase: str,
    prerequisite_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    observation = {
        "task_id": task_id,
        "case_id": f"framework-replay-{task_id}",
        "success": False,
        "phase": phase,
        "failure_class": "independent_task_replay_exception" if phase != "prerequisite" else "independent_verifier_prerequisite_failed",
        "expected": {},
        "actual": {},
        "positive_verifier_result": {},
        "negative_verifier_result": {},
        "trace_evidence": {},
        "state_or_answer_evidence": {},
        "exception": exc_info,
        "recovery_suggestion": "Fix generated contract.json or ABI adapter implementation before release.",
    }
    stderr = f"{exc_info.get('type', 'Exception')}: {exc_info.get('message', '')}"
    if exc_info.get("traceback"):
        stderr = f"{stderr}\n{exc_info['traceback']}"
    return {
        "check_id": f"contract-project-independent-{task_id}",
        "success": False,
        "status": "fail",
        "verifier_kind": "framework_independent_generated_project",
        "environment_id": environment_id,
        "task_id": task_id,
        "phase": phase,
        "command": "framework ABI reset/invoke/verify/export_trace",
        "exit_code": None,
        "stdout": "",
        "stderr": stderr,
        "positive_verifier_result": {},
        "negative_verifier_result": {},
        "framework_evidence": {},
        "failure_class": observation["failure_class"],
        "recovery_suggestion": observation["recovery_suggestion"],
        "exception": exc_info,
        "prerequisite_checks": prerequisite_checks or [],
        "task_observation": observation,
    }


def _restore_modules(original_modules: dict[str, Any]) -> None:
    for name in list(sys.modules):
        if name not in original_modules:
            sys.modules.pop(name, None)
    for name, module in original_modules.items():
        sys.modules[name] = module


def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

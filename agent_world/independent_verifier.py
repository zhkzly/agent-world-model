from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
import tempfile
import traceback
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from agent_world.replay_contract import exception_payload, observation_from_independent_report


def verify_generated_bundle_independent(
    environment_id: str,
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    seed_fixture_ref: str = "seed_state.json",
    check_replay_ref: str = "check_replay.py",
) -> dict[str, Any]:
    return verify_contract_generated_bundle_independent(
        environment_id,
        build_dir,
        accepted_tasks=accepted_tasks or [],
        runtime_entrypoint=runtime_entrypoint or "runtime.GeneratedEnvironment",
        verifier_entrypoint=verifier_entrypoint,
        seed_fixture_ref=seed_fixture_ref,
        check_replay_ref=check_replay_ref,
    )


def verify_contract_generated_bundle_independent(
    environment_id: str,
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "runtime.GeneratedEnvironment",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    seed_fixture_ref: str = "seed_state.json",
    check_replay_ref: str = "check_replay.py",
) -> dict[str, Any]:
    """Framework-owned verifier driven only by accepted replay contracts."""
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_contract_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    original_modules = {name: sys.modules.get(name) for name in ["runtime", "verifier"]}
    original_path = list(sys.path)
    try:
        sys.path.insert(0, str(build_dir))
        runtime_module = _load_named_module("runtime", build_dir / "runtime.py")
        verifier_module = _load_named_module("verifier", build_dir / "verifier.py")
        prereq_checks.extend(
            [
                _check("runtime_importable", True, {"path": str(build_dir / "runtime.py")}),
                _check("verifier_importable", True, {"path": str(build_dir / "verifier.py")}),
            ]
        )
        runtime_class = _resolve_entrypoint(runtime_module, runtime_entrypoint, expected_module_name="runtime")
        verifier_fn = _resolve_entrypoint(verifier_module, verifier_entrypoint, expected_module_name="verifier")
        load_seed = getattr(runtime_module, "load_seed_state", None)
        reset_environment = getattr(runtime_module, "reset_environment", None)
        prereq_checks.extend(
            [
                _check("runtime_entrypoint_exists", inspect.isclass(runtime_class), {"entrypoint": runtime_entrypoint}),
                _check("verifier_entrypoint_exists", callable(verifier_fn), {"entrypoint": verifier_entrypoint}),
                _check("load_seed_state_exists", callable(load_seed), {"entrypoint": "runtime.load_seed_state"}),
                _check("reset_environment_exists", callable(reset_environment), {"entrypoint": "runtime.reset_environment"}),
            ]
        )
        seed_path = (build_dir / seed_fixture_ref).resolve()
        if not _inside(seed_path, build_dir) or not seed_path.is_file():
            raise FileNotFoundError(seed_path)
        seed = load_seed(seed_path) if callable(load_seed) else json.loads(seed_path.read_text(encoding="utf-8"))
        prereq_checks.append(_check("seed_loads", isinstance(seed, dict), {"seed_fixture_ref": seed_fixture_ref}))
        prereq_checks.extend(_check_replay_static(build_dir / check_replay_ref))
        prereq_checks.extend(_runtime_tool_checks(runtime_class, tasks, runtime_entrypoint=runtime_entrypoint))
        if not tasks:
            prereq_checks.append(_check("accepted_tasks_present", False, {"accepted_task_count": 0}))
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated bundle prerequisite checks failed")
        for task in tasks:
            try:
                record = _verify_contract_task(
                    environment_id,
                    task,
                    runtime_class=runtime_class,
                    reset_environment=reset_environment,
                    verifier_fn=verifier_fn,
                    seed=seed,
                )
            except Exception as exc:
                record = _task_exception_record(
                    environment_id,
                    task["task_id"],
                    exception_payload(exc, phase="task_replay", traceback_text=traceback.format_exc()),
                    phase="task_replay",
                )
            task_records.append(record)
    except Exception as exc:
        exc_info = exception_payload(exc, phase="prerequisite", traceback_text=traceback.format_exc())
        if not prereq_checks:
            failed = _check("independent_verifier_prerequisites", False, {"error": f"{exc.__class__.__name__}: {exc}"})
            failed["exception"] = exc_info
            prereq_checks.append(failed)
        for task in tasks:
            if any(record.get("task_id") == task["task_id"] for record in task_records):
                continue
            task_records.append(_task_exception_record(environment_id, task["task_id"], exc_info, phase="prerequisite", prerequisite_checks=prereq_checks))
    finally:
        sys.path[:] = original_path
        for name, previous in original_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    accepted_task_ids = [task["task_id"] for task in tasks]
    verified_task_ids = [record["task_id"] for record in task_records if record.get("success") is True]
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and bool(accepted_task_ids)
    failure_class = "" if success else "independent_generated_bundle_verification_failed"
    recovery = "" if success else "Regenerate or repair the generated bundle so runtime, verifier, seed, and replay evidence pass independently."
    report = {
        "check_id": "contract-independent-generated-bundle-verifier",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": environment_id,
        "command": "framework import runtime.py/verifier.py/seed_state.json and replay accepted task contracts",
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


def _normalise_contract_tasks(accepted_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    tasks = []
    for item in accepted_tasks or []:
        task = dict(item)
        if "dependency_path" not in task:
            task["dependency_path"] = list(task.get("allowed_logical_tool_ids", []))
        replay = task.get("framework_replay")
        if not isinstance(replay, dict):
            replay = {}
        calls = replay.get("tool_calls")
        if not isinstance(calls, list) or not calls:
            calls = [{"tool": tool, "kwargs": {}} for tool in task.get("dependency_path", [])]
        task["framework_replay"] = {**replay, "tool_calls": calls}
        tasks.append(task)
    return tasks


def _load_named_module(name: str, path: Path) -> ModuleType:
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load generated module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_entrypoint(module: ModuleType, entrypoint: str, *, expected_module_name: str) -> Any:
    module_name, _, attr_path = entrypoint.partition(".")
    if module_name != expected_module_name or not attr_path:
        return None
    value: Any = module
    for part in attr_path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _check_replay_static(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return [_check("check_replay_exists", False, {"path": str(path)})]
    text = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [_check("check_replay_parseable", False, {"error": str(exc)})]
    imports_runtime = False
    imports_verifier = False
    has_main = False
    mentions_seed = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports_runtime = imports_runtime or alias.name == "runtime"
                imports_verifier = imports_verifier or alias.name == "verifier"
        elif isinstance(node, ast.ImportFrom):
            imports_runtime = imports_runtime or node.module == "runtime"
            imports_verifier = imports_verifier or node.module == "verifier"
        elif isinstance(node, ast.FunctionDef):
            has_main = has_main or node.name == "main"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            mentions_seed = mentions_seed or "seed_state.json" in node.value
    return [
        _check("check_replay_parseable", True, {"path": str(path)}),
        _check("check_replay_imports_runtime", imports_runtime, {"path": str(path)}),
        _check("check_replay_imports_verifier", imports_verifier, {"path": str(path)}),
        _check("check_replay_has_main", has_main, {"path": str(path)}),
        _check("check_replay_loads_seed", mentions_seed, {"path": str(path)}),
    ]


def _runtime_tool_checks(runtime_class: Any, tasks: list[dict[str, Any]], *, runtime_entrypoint: str) -> list[dict[str, Any]]:
    required_tools = sorted({str(tool) for task in tasks for tool in task.get("dependency_path", [])})
    return [
        _check(
            f"runtime_tool_{tool}_exists",
            callable(getattr(runtime_class, tool, None)),
            {"tool": tool, "entrypoint": f"{runtime_entrypoint}.{tool}"},
        )
        for tool in required_tools
    ]


def _verify_contract_task(
    environment_id: str,
    task: dict[str, Any],
    *,
    runtime_class: Any,
    reset_environment: Callable[[dict[str, Any]], dict[str, Any]],
    verifier_fn: Callable[..., dict[str, Any]],
    seed: dict[str, Any],
) -> dict[str, Any]:
    task_id = task["task_id"]
    with tempfile.TemporaryDirectory(prefix="agent-world-contract-independent-verifier-") as td:
        root = Path(td)
        positive_trace = root / f"{task_id}-positive.jsonl"
        initial = reset_environment(seed)
        final = reset_environment(seed)
        final_answer = _execute_contract_positive_case(task, runtime_class, final, positive_trace)
        positive = _call_verifier(verifier_fn, task, initial, final, final_answer, positive_trace, "positive")

        negative_initial = reset_environment(seed)
        negative_final = reset_environment(seed)
        negative_trace = root / f"{task_id}-negative.jsonl"
        negative = _call_verifier(verifier_fn, task, negative_initial, negative_final, _contract_negative_answer(task), negative_trace, "negative")

        trace_tools = _trace_tools(positive_trace, task_id=task_id, call_group="positive")
        expected_path = list(task.get("dependency_path", []))
        trace_evidence = {
            "expected": expected_path,
            "actual": trace_tools,
            "success": trace_tools == expected_path,
            "trace_path": str(positive_trace),
        }
        state_evidence = _contract_expected_state_or_answer_evidence(task, initial, final, final_answer)
    positive_success = positive.get("success") is True
    negative_success = negative.get("success") is False
    success = positive_success and negative_success and trace_evidence["success"] and state_evidence["success"]
    return {
        "check_id": f"contract-independent-{task_id}",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": environment_id,
        "task_id": task_id,
        "command": "framework import runtime.py/verifier.py and execute replay contract",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "positive_verifier_result": positive,
        "negative_verifier_result": negative,
        "framework_evidence": {
            "dependency_trace": trace_evidence,
            "expected_state_or_answer": state_evidence,
            "positive_case_success": positive_success,
            "negative_case_failed": negative_success,
        },
        "failure_class": "" if success else "independent_task_verification_failed",
        "recovery_suggestion": "" if success else "Generated runtime/verifier did not satisfy the framework replay contract for this accepted task.",
    }


def _execute_contract_positive_case(task: dict[str, Any], runtime_class: Any, state: dict[str, Any], trace_path: Path) -> Any:
    env = runtime_class(state, trace_path=trace_path, task_id=task["task_id"], call_group="positive")
    answer = None
    for call in task.get("framework_replay", {}).get("tool_calls", []):
        tool = str(call.get("tool", ""))
        kwargs = call.get("kwargs", {})
        if not isinstance(kwargs, dict):
            kwargs = {}
        answer = getattr(env, tool)(**kwargs)
    return answer


def _contract_negative_answer(task: dict[str, Any]) -> Any:
    expected = task.get("expected_answer")
    if expected not in (None, "", {}):
        return {"accepted": False, "reason": "negative replay"}
    return None


def _contract_expected_state_or_answer_evidence(task: dict[str, Any], initial: dict[str, Any], final: dict[str, Any], final_answer: Any) -> dict[str, Any]:
    expected_answer = task.get("expected_answer")
    if expected_answer not in (None, "", {}):
        success = final_answer == expected_answer and initial == final
        return {
            "kind": "expected_answer",
            "expected": expected_answer,
            "actual": final_answer,
            "state_unchanged": initial == final,
            "success": success,
        }
    expected_delta = task.get("expected_state_delta", {})
    if expected_delta:
        success = initial != final
        return {
            "kind": "expected_state_delta",
            "expected": expected_delta,
            "actual": {"state_changed": initial != final},
            "success": success,
        }
    success = final_answer not in (None, "", {})
    return {
        "kind": "answer_present",
        "expected": "non-empty final answer",
        "actual": final_answer,
        "success": success,
    }


def _call_verifier(
    verifier_fn: Callable[..., dict[str, Any]],
    task: dict[str, Any],
    initial: dict[str, Any],
    final: dict[str, Any],
    final_answer: Any,
    trace_path: Path,
    call_group: str,
) -> dict[str, Any]:
    try:
        result = verifier_fn(
            task["task_id"],
            initial,
            final,
            surface_trace_path=trace_path,
            expected_dependency_path=list(task.get("dependency_path", [])),
            trace_call_group=call_group,
            final_answer=final_answer,
        )
        return result if isinstance(result, dict) else {"success": False, "result": result}
    except Exception as exc:
        return {
            "success": False,
            "exception": exception_payload(exc, phase="verifier_call", traceback_text=traceback.format_exc()),
        }


def _trace_tools(path: Path, *, task_id: str, call_group: str) -> list[str]:
    if not path.is_file():
        return []
    tools = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("task_id") == task_id and record.get("call_group") in {call_group, None, ""}:
            tools.append(str(record.get("tool", "")))
    return tools


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
        "recovery_suggestion": "Fix generated runtime.py, verifier.py, seed_state.json, or check_replay.py before release.",
    }
    stderr = f"{exc_info.get('type', 'Exception')}: {exc_info.get('message', '')}"
    if exc_info.get("traceback"):
        stderr = f"{stderr}\n{exc_info['traceback']}"
    return {
        "check_id": f"contract-independent-{task_id}",
        "success": False,
        "status": "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": environment_id,
        "task_id": task_id,
        "phase": phase,
        "command": "framework import runtime.py/verifier.py and execute replay contract",
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


def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False

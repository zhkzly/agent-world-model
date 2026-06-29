from __future__ import annotations

import ast
import copy
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


def default_project_board_tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "pb-task-1",
            "expected_state_delta": {"card": "C-11 status=in_review", "audit_event": "card_moved"},
            "expected_answer": "",
            "dependency_path": ["card_list", "card_get", "card_move"],
        },
        {
            "task_id": "pb-task-2",
            "expected_state_delta": {"card": "C-10 assignee=sam", "comment": "triage comment added", "audit_event": "card_assigned"},
            "expected_answer": "",
            "dependency_path": ["card_list", "card_assign", "comment_add"],
        },
        {
            "task_id": "pb-task-3",
            "expected_state_delta": {},
            "expected_answer": {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"},
            "dependency_path": ["card_list"],
        },
    ]


def default_booking_tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "booking-task-1",
            "expected_state_delta": {"booking": "confirmed event=EVT-100 customer=C-1 quantity=2", "seat_inventory": "EVT-100 available decreases by 2", "payment": "authorized"},
            "expected_answer": "",
            "dependency_path": ["search_events", "check_availability", "hold_seats", "confirm_booking"],
        },
        {
            "task_id": "booking-task-2",
            "expected_state_delta": {"booking": "B-200 status=canceled", "seat_inventory": "EVT-200 available increases by 1", "payment": "refunded"},
            "expected_answer": "",
            "dependency_path": ["cancel_booking"],
        },
        {
            "task_id": "booking-task-3",
            "expected_state_delta": {},
            "expected_answer": {"event_id": "EVT-100", "available_seats": 4, "price": 120},
            "dependency_path": ["search_events", "check_availability"],
        },
    ]


def default_library_tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "library-task-1",
            "expected_state_delta": {"loan": "active book=BK-100 patron=P-1", "book_inventory": "BK-100 available decreases by 1"},
            "expected_answer": "",
            "dependency_path": ["search_books", "check_availability", "borrow_book"],
        },
        {
            "task_id": "library-task-2",
            "expected_state_delta": {"loan": "L-200 status=returned", "book_inventory": "BK-200 available increases by 1", "fine": "assessed amount=10"},
            "expected_answer": "",
            "dependency_path": ["return_book"],
        },
        {
            "task_id": "library-task-3",
            "expected_state_delta": {},
            "expected_answer": {"book_id": "BK-100", "available_copies": 2, "title": "Distributed Systems"},
            "dependency_path": ["search_books", "check_availability"],
        },
    ]


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
    if accepted_tasks and _has_framework_replay_tasks(accepted_tasks):
        return verify_contract_generated_bundle_independent(
            environment_id,
            build_dir,
            accepted_tasks=accepted_tasks,
            runtime_entrypoint=runtime_entrypoint or "runtime.GeneratedEnvironment",
            verifier_entrypoint=verifier_entrypoint,
            seed_fixture_ref=seed_fixture_ref,
            check_replay_ref=check_replay_ref,
        )
    if environment_id == "project-board-lite":
        return verify_project_board_generated_bundle_independent(
            build_dir,
            accepted_tasks=accepted_tasks,
            runtime_entrypoint=runtime_entrypoint or "runtime.ProjectBoardLite",
            verifier_entrypoint=verifier_entrypoint,
            seed_fixture_ref=seed_fixture_ref,
            check_replay_ref=check_replay_ref,
        )
    if environment_id == "booking-service-lite":
        return verify_booking_generated_bundle_independent(
            build_dir,
            accepted_tasks=accepted_tasks,
            runtime_entrypoint=runtime_entrypoint or "runtime.BookingServiceLite",
            verifier_entrypoint=verifier_entrypoint,
            seed_fixture_ref=seed_fixture_ref,
            check_replay_ref=check_replay_ref,
        )
    if environment_id == "library-lending-lite":
        return verify_library_generated_bundle_independent(
            build_dir,
            accepted_tasks=accepted_tasks,
            runtime_entrypoint=runtime_entrypoint or "runtime.LibraryLendingLite",
            verifier_entrypoint=verifier_entrypoint,
            seed_fixture_ref=seed_fixture_ref,
            check_replay_ref=check_replay_ref,
        )
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
    """Framework-owned generic verifier driven by task replay contracts."""
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_contract_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    unsupported_task_ids: list[str] = []
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
            if record.get("unsupported"):
                unsupported_task_ids.append(record["task_id"])
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
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and bool(accepted_task_ids) and not unsupported_task_ids
    if success:
        failure_class = ""
        recovery = ""
    elif unsupported_task_ids:
        failure_class = "unsupported_generated_bundle_task"
        recovery = "Release is blocked until every accepted task has a framework replay record."
    else:
        failure_class = "independent_generated_bundle_verification_failed"
        recovery = "Regenerate or repair the generated bundle so runtime, verifier, seed, and replay evidence pass independently."
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
        "unsupported_task_ids": unsupported_task_ids,
        "prerequisite_checks": prereq_checks,
        "task_records": task_records,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }
    report["framework_check_observation"] = observation_from_independent_report(report, candidate_dir=build_dir)
    return report


def verify_project_board_generated_bundle_independent(
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "runtime.ProjectBoardLite",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    seed_fixture_ref: str = "seed_state.json",
    check_replay_ref: str = "check_replay.py",
) -> dict[str, Any]:
    """Framework-owned verifier for project-board-lite generated bundles.

    This deliberately imports and executes generated runtime/verifier files itself.
    It treats generated check_replay.py as an artifact to sanity-check, not as the
    authority for bundle acceptance.
    """
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    unsupported_task_ids: list[str] = []
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
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated bundle prerequisite checks failed")
        for task in tasks:
            try:
                record = _verify_task(
                    task,
                    runtime_class=runtime_class,
                    reset_environment=reset_environment,
                    verifier_fn=verifier_fn,
                    seed=seed,
                )
            except Exception as exc:
                record = _task_exception_record(
                    "project-board-lite",
                    task["task_id"],
                    exception_payload(exc, phase="task_replay", traceback_text=traceback.format_exc()),
                    phase="task_replay",
                )
            task_records.append(record)
            if record.get("unsupported"):
                unsupported_task_ids.append(record["task_id"])
    except Exception as exc:
        exc_info = exception_payload(exc, phase="prerequisite", traceback_text=traceback.format_exc())
        if not prereq_checks:
            failed = _check("independent_verifier_prerequisites", False, {"error": f"{exc.__class__.__name__}: {exc}"})
            failed["exception"] = exc_info
            prereq_checks.append(failed)
        for task in tasks:
            if any(record.get("task_id") == task["task_id"] for record in task_records):
                continue
            task_records.append(_task_exception_record("project-board-lite", task["task_id"], exc_info, phase="prerequisite", prerequisite_checks=prereq_checks))
    finally:
        sys.path[:] = original_path
        for name, previous in original_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    accepted_task_ids = [task["task_id"] for task in tasks]
    verified_task_ids = [record["task_id"] for record in task_records if record.get("success") is True]
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and not unsupported_task_ids
    if success:
        failure_class = ""
        recovery = ""
    elif unsupported_task_ids:
        failure_class = "unsupported_generated_bundle_task"
        recovery = "Release is blocked until every accepted task has an independent generated-bundle replay record."
    else:
        failure_class = "independent_generated_bundle_verification_failed"
        recovery = "Regenerate or repair the generated bundle so runtime, verifier, seed, and task evidence pass independently."
    report = {
        "check_id": "project-board-independent-generated-bundle-verifier",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "project-board-lite",
        "command": "framework import runtime.py/verifier.py/seed_state.json and replay accepted tasks",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "accepted_task_ids": accepted_task_ids,
        "verified_task_ids": verified_task_ids,
        "unsupported_task_ids": unsupported_task_ids,
        "prerequisite_checks": prereq_checks,
        "task_records": task_records,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }
    report["framework_check_observation"] = observation_from_independent_report(report, candidate_dir=build_dir)
    return report


def verify_booking_generated_bundle_independent(
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "runtime.BookingServiceLite",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    seed_fixture_ref: str = "seed_state.json",
    check_replay_ref: str = "check_replay.py",
) -> dict[str, Any]:
    """Framework-owned verifier for booking-service-lite generated bundles."""
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_booking_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    unsupported_task_ids: list[str] = []
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
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated bundle prerequisite checks failed")
        for task in tasks:
            try:
                record = _verify_booking_task(
                    task,
                    runtime_class=runtime_class,
                    reset_environment=reset_environment,
                    verifier_fn=verifier_fn,
                    seed=seed,
                )
            except Exception as exc:
                record = _task_exception_record(
                    "booking-service-lite",
                    task["task_id"],
                    exception_payload(exc, phase="task_replay", traceback_text=traceback.format_exc()),
                    phase="task_replay",
                )
            task_records.append(record)
            if record.get("unsupported"):
                unsupported_task_ids.append(record["task_id"])
    except Exception as exc:
        exc_info = exception_payload(exc, phase="prerequisite", traceback_text=traceback.format_exc())
        if not prereq_checks:
            failed = _check("independent_verifier_prerequisites", False, {"error": f"{exc.__class__.__name__}: {exc}"})
            failed["exception"] = exc_info
            prereq_checks.append(failed)
        for task in tasks:
            if any(record.get("task_id") == task["task_id"] for record in task_records):
                continue
            task_records.append(_task_exception_record("booking-service-lite", task["task_id"], exc_info, phase="prerequisite", prerequisite_checks=prereq_checks))
    finally:
        sys.path[:] = original_path
        for name, previous in original_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    accepted_task_ids = [task["task_id"] for task in tasks]
    verified_task_ids = [record["task_id"] for record in task_records if record.get("success") is True]
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and not unsupported_task_ids
    if success:
        failure_class = ""
        recovery = ""
    elif unsupported_task_ids:
        failure_class = "unsupported_generated_bundle_task"
        recovery = "Release is blocked until every accepted booking task has an independent generated-bundle replay record."
    else:
        failure_class = "independent_generated_bundle_verification_failed"
        recovery = "Regenerate or repair the generated booking bundle so runtime, verifier, seed, and task evidence pass independently."
    report = {
        "check_id": "booking-independent-generated-bundle-verifier",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "booking-service-lite",
        "command": "framework import runtime.py/verifier.py/seed_state.json and replay accepted tasks",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "accepted_task_ids": accepted_task_ids,
        "verified_task_ids": verified_task_ids,
        "unsupported_task_ids": unsupported_task_ids,
        "prerequisite_checks": prereq_checks,
        "task_records": task_records,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }
    report["framework_check_observation"] = observation_from_independent_report(report, candidate_dir=build_dir)
    return report


def verify_library_generated_bundle_independent(
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "runtime.LibraryLendingLite",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    seed_fixture_ref: str = "seed_state.json",
    check_replay_ref: str = "check_replay.py",
) -> dict[str, Any]:
    """Framework-owned verifier for library-lending-lite generated bundles."""
    build_dir = Path(build_dir).resolve()
    tasks = _normalise_library_tasks(accepted_tasks)
    prereq_checks: list[dict[str, Any]] = []
    task_records: list[dict[str, Any]] = []
    unsupported_task_ids: list[str] = []
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
        if not all(item["passed"] for item in prereq_checks):
            raise RuntimeError("generated bundle prerequisite checks failed")
        for task in tasks:
            try:
                record = _verify_library_task(
                    task,
                    runtime_class=runtime_class,
                    reset_environment=reset_environment,
                    verifier_fn=verifier_fn,
                    seed=seed,
                )
            except Exception as exc:
                record = _task_exception_record(
                    "library-lending-lite",
                    task["task_id"],
                    exception_payload(exc, phase="task_replay", traceback_text=traceback.format_exc()),
                    phase="task_replay",
                )
            task_records.append(record)
            if record.get("unsupported"):
                unsupported_task_ids.append(record["task_id"])
    except Exception as exc:
        exc_info = exception_payload(exc, phase="prerequisite", traceback_text=traceback.format_exc())
        if not prereq_checks:
            failed = _check("independent_verifier_prerequisites", False, {"error": f"{exc.__class__.__name__}: {exc}"})
            failed["exception"] = exc_info
            prereq_checks.append(failed)
        for task in tasks:
            if any(record.get("task_id") == task["task_id"] for record in task_records):
                continue
            task_records.append(_task_exception_record("library-lending-lite", task["task_id"], exc_info, phase="prerequisite", prerequisite_checks=prereq_checks))
    finally:
        sys.path[:] = original_path
        for name, previous in original_modules.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous

    accepted_task_ids = [task["task_id"] for task in tasks]
    verified_task_ids = [record["task_id"] for record in task_records if record.get("success") is True]
    success = all(item["passed"] for item in prereq_checks) and set(verified_task_ids) == set(accepted_task_ids) and not unsupported_task_ids
    if success:
        failure_class = ""
        recovery = ""
    elif unsupported_task_ids:
        failure_class = "unsupported_generated_bundle_task"
        recovery = "Release is blocked until every accepted library task has an independent generated-bundle replay record."
    else:
        failure_class = "independent_generated_bundle_verification_failed"
        recovery = "Regenerate or repair the generated library bundle so runtime, verifier, seed, and task evidence pass independently."
    report = {
        "check_id": "library-independent-generated-bundle-verifier",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "library-lending-lite",
        "command": "framework import runtime.py/verifier.py/seed_state.json and replay accepted tasks",
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "accepted_task_ids": accepted_task_ids,
        "verified_task_ids": verified_task_ids,
        "unsupported_task_ids": unsupported_task_ids,
        "prerequisite_checks": prereq_checks,
        "task_records": task_records,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }
    report["framework_check_observation"] = observation_from_independent_report(report, candidate_dir=build_dir)
    return report


def _normalise_tasks(accepted_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    source = accepted_tasks if accepted_tasks is not None else default_project_board_tasks()
    tasks = []
    defaults = {task["task_id"]: task for task in default_project_board_tasks()}
    for item in source:
        task_id = str(item.get("task_id", ""))
        base = dict(defaults.get(task_id, {}))
        base.update(item)
        if "dependency_path" not in base:
            base["dependency_path"] = list(item.get("allowed_logical_tool_ids", []))
        tasks.append(base)
    return tasks


def _normalise_booking_tasks(accepted_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    source = accepted_tasks if accepted_tasks is not None else default_booking_tasks()
    tasks = []
    defaults = {task["task_id"]: task for task in default_booking_tasks()}
    for item in source:
        task_id = str(item.get("task_id", ""))
        base = dict(defaults.get(task_id, {}))
        base.update(item)
        if "dependency_path" not in base:
            base["dependency_path"] = list(item.get("allowed_logical_tool_ids", []))
        tasks.append(base)
    return tasks


def _normalise_library_tasks(accepted_tasks: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    source = accepted_tasks if accepted_tasks is not None else default_library_tasks()
    tasks = []
    defaults = {task["task_id"]: task for task in default_library_tasks()}
    for item in source:
        task_id = str(item.get("task_id", ""))
        base = dict(defaults.get(task_id, {}))
        base.update(item)
        if "dependency_path" not in base:
            base["dependency_path"] = list(item.get("allowed_logical_tool_ids", []))
        tasks.append(base)
    return tasks


def _has_framework_replay_tasks(tasks: list[dict[str, Any]]) -> bool:
    return any(isinstance(task.get("framework_replay"), dict) and task["framework_replay"].get("tool_calls") for task in tasks)


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
    checks: list[dict[str, Any]] = []
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
    checks.extend(
        [
            _check("check_replay_parseable", True, {"path": str(path)}),
            _check("check_replay_imports_runtime", imports_runtime, {"path": str(path)}),
            _check("check_replay_imports_verifier", imports_verifier, {"path": str(path)}),
            _check("check_replay_has_main", has_main, {"path": str(path)}),
            _check("check_replay_loads_seed", mentions_seed, {"path": str(path)}),
        ]
    )
    return checks


def _runtime_tool_checks(runtime_class: Any, tasks: list[dict[str, Any]], *, runtime_entrypoint: str = "runtime.ProjectBoardLite") -> list[dict[str, Any]]:
    required_tools = sorted({tool for task in tasks for tool in task.get("dependency_path", [])})
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
    replay = task.get("framework_replay", {}) if isinstance(task.get("framework_replay"), dict) else {}
    tool_calls = replay.get("tool_calls", [])
    if not tool_calls:
        return {
            "check_id": f"contract-independent-{task_id}",
            "success": False,
            "status": "fail",
            "verifier_kind": "framework_independent_generated_bundle",
            "environment_id": environment_id,
            "task_id": task_id,
            "unsupported": True,
            "command": "framework import runtime.py/verifier.py and execute replay contract",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "positive_verifier_result": {},
            "negative_verifier_result": {},
            "framework_evidence": {},
            "failure_class": "missing_framework_replay_contract",
            "recovery_suggestion": "Task must include framework_replay.tool_calls or dependency_path-derived calls.",
        }
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
        negative_answer = _contract_negative_answer(task)
        negative = _call_verifier(verifier_fn, task, negative_initial, negative_final, negative_answer, negative_trace, "negative")

        trace_tools = _trace_tools(positive_trace, task_id=task_id, call_group="positive")
        expected_path = list(task.get("dependency_path", [])) or [str(call.get("tool", "")) for call in tool_calls]
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


def _verify_task(
    task: dict[str, Any],
    *,
    runtime_class: Any,
    reset_environment: Callable[[dict[str, Any]], dict[str, Any]],
    verifier_fn: Callable[..., dict[str, Any]],
    seed: dict[str, Any],
) -> dict[str, Any]:
    task_id = task["task_id"]
    if task_id not in {"pb-task-1", "pb-task-2", "pb-task-3"}:
        return {
            "check_id": f"project-board-independent-{task_id}",
            "success": False,
            "status": "fail",
            "verifier_kind": "framework_independent_generated_bundle",
            "environment_id": "project-board-lite",
            "task_id": task_id,
            "unsupported": True,
            "command": "framework import runtime.py/verifier.py and execute generated runtime",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "positive_verifier_result": {},
            "negative_verifier_result": {},
            "framework_evidence": {},
            "failure_class": "unsupported_generated_bundle_task",
            "recovery_suggestion": "No independent project-board-lite replay case exists for this accepted task.",
        }
    with tempfile.TemporaryDirectory(prefix="agent-world-independent-verifier-") as td:
        root = Path(td)
        positive_trace = root / f"{task_id}-positive.jsonl"
        initial = reset_environment(seed)
        final = reset_environment(seed)
        final_answer = _execute_positive_case(task_id, runtime_class, final, positive_trace)
        positive = _call_verifier(verifier_fn, task, initial, final, final_answer, positive_trace, "positive")

        negative_initial = reset_environment(seed)
        negative_final = reset_environment(seed)
        negative_trace = root / f"{task_id}-negative.jsonl"
        negative_answer = _negative_answer(task_id)
        negative = _call_verifier(verifier_fn, task, negative_initial, negative_final, negative_answer, negative_trace, "negative")

        trace_tools = _trace_tools(positive_trace, task_id=task_id, call_group="positive")
        trace_evidence = {
            "expected": list(task.get("dependency_path", [])),
            "actual": trace_tools,
            "success": trace_tools == list(task.get("dependency_path", [])),
            "trace_path": str(positive_trace),
        }
        state_evidence = _expected_state_or_answer_evidence(task_id, initial, final, final_answer)
    positive_success = positive.get("success") is True
    negative_success = negative.get("success") is False
    success = positive_success and negative_success and trace_evidence["success"] and state_evidence["success"]
    return {
        "check_id": f"project-board-independent-{task_id}",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "project-board-lite",
        "task_id": task_id,
        "command": "framework import runtime.py/verifier.py and execute generated runtime",
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
        "recovery_suggestion": "" if success else "Generated runtime/verifier did not satisfy the framework replay for this accepted task.",
    }


def _verify_booking_task(
    task: dict[str, Any],
    *,
    runtime_class: Any,
    reset_environment: Callable[[dict[str, Any]], dict[str, Any]],
    verifier_fn: Callable[..., dict[str, Any]],
    seed: dict[str, Any],
) -> dict[str, Any]:
    task_id = task["task_id"]
    if task_id not in {"booking-task-1", "booking-task-2", "booking-task-3"}:
        return {
            "check_id": f"booking-independent-{task_id}",
            "success": False,
            "status": "fail",
            "verifier_kind": "framework_independent_generated_bundle",
            "environment_id": "booking-service-lite",
            "task_id": task_id,
            "unsupported": True,
            "command": "framework import runtime.py/verifier.py and execute generated runtime",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "positive_verifier_result": {},
            "negative_verifier_result": {},
            "framework_evidence": {},
            "failure_class": "unsupported_generated_bundle_task",
            "recovery_suggestion": "No independent booking-service-lite replay case exists for this accepted task.",
        }
    with tempfile.TemporaryDirectory(prefix="agent-world-booking-independent-verifier-") as td:
        root = Path(td)
        positive_trace = root / f"{task_id}-positive.jsonl"
        initial = reset_environment(seed)
        final = reset_environment(seed)
        final_answer = _execute_booking_positive_case(task_id, runtime_class, final, positive_trace)
        positive = _call_verifier(verifier_fn, task, initial, final, final_answer, positive_trace, "positive")

        negative_initial = reset_environment(seed)
        negative_final = reset_environment(seed)
        negative_trace = root / f"{task_id}-negative.jsonl"
        negative_answer = {"event_id": "EVT-100", "available_seats": 0, "price": 120} if task_id == "booking-task-3" else None
        negative = _call_verifier(verifier_fn, task, negative_initial, negative_final, negative_answer, negative_trace, "negative")

        trace_tools = _trace_tools(positive_trace, task_id=task_id, call_group="positive")
        trace_evidence = {
            "expected": list(task.get("dependency_path", [])),
            "actual": trace_tools,
            "success": trace_tools == list(task.get("dependency_path", [])),
            "trace_path": str(positive_trace),
        }
        state_evidence = _booking_expected_state_or_answer_evidence(task_id, initial, final, final_answer)
    positive_success = positive.get("success") is True
    negative_success = negative.get("success") is False
    success = positive_success and negative_success and trace_evidence["success"] and state_evidence["success"]
    return {
        "check_id": f"booking-independent-{task_id}",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "booking-service-lite",
        "task_id": task_id,
        "command": "framework import runtime.py/verifier.py and execute generated runtime",
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
        "recovery_suggestion": "" if success else "Generated booking runtime/verifier did not satisfy the framework replay for this accepted task.",
    }


def _verify_library_task(
    task: dict[str, Any],
    *,
    runtime_class: Any,
    reset_environment: Callable[[dict[str, Any]], dict[str, Any]],
    verifier_fn: Callable[..., dict[str, Any]],
    seed: dict[str, Any],
) -> dict[str, Any]:
    task_id = task["task_id"]
    if task_id not in {"library-task-1", "library-task-2", "library-task-3"}:
        return {
            "check_id": f"library-independent-{task_id}",
            "success": False,
            "status": "fail",
            "verifier_kind": "framework_independent_generated_bundle",
            "environment_id": "library-lending-lite",
            "task_id": task_id,
            "unsupported": True,
            "command": "framework import runtime.py/verifier.py and execute generated runtime",
            "exit_code": None,
            "stdout": "",
            "stderr": "",
            "positive_verifier_result": {},
            "negative_verifier_result": {},
            "framework_evidence": {},
            "failure_class": "unsupported_generated_bundle_task",
            "recovery_suggestion": "No independent library-lending-lite replay case exists for this accepted task.",
        }
    with tempfile.TemporaryDirectory(prefix="agent-world-library-independent-verifier-") as td:
        root = Path(td)
        positive_trace = root / f"{task_id}-positive.jsonl"
        initial = reset_environment(seed)
        final = reset_environment(seed)
        final_answer = _execute_library_positive_case(task_id, runtime_class, final, positive_trace)
        positive = _call_verifier(verifier_fn, task, initial, final, final_answer, positive_trace, "positive")

        negative_initial = reset_environment(seed)
        negative_final = reset_environment(seed)
        negative_trace = root / f"{task_id}-negative.jsonl"
        negative_answer = {"book_id": "BK-100", "available_copies": 0, "title": "Distributed Systems"} if task_id == "library-task-3" else None
        negative = _call_verifier(verifier_fn, task, negative_initial, negative_final, negative_answer, negative_trace, "negative")

        trace_tools = _trace_tools(positive_trace, task_id=task_id, call_group="positive")
        trace_evidence = {
            "expected": list(task.get("dependency_path", [])),
            "actual": trace_tools,
            "success": trace_tools == list(task.get("dependency_path", [])),
            "trace_path": str(positive_trace),
        }
        state_evidence = _library_expected_state_or_answer_evidence(task_id, initial, final, final_answer)
    positive_success = positive.get("success") is True
    negative_success = negative.get("success") is False
    success = positive_success and negative_success and trace_evidence["success"] and state_evidence["success"]
    return {
        "check_id": f"library-independent-{task_id}",
        "success": success,
        "status": "pass" if success else "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": "library-lending-lite",
        "task_id": task_id,
        "command": "framework import runtime.py/verifier.py and execute generated runtime",
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
        "recovery_suggestion": "" if success else "Generated library runtime/verifier did not satisfy the framework replay for this accepted task.",
    }


def _execute_contract_positive_case(task: dict[str, Any], runtime_class: Any, state: dict[str, Any], trace_path: Path) -> Any:
    task_id = task["task_id"]
    env = _instantiate_runtime(runtime_class, state, trace_path=trace_path, task_id=task_id, call_group="positive")
    replay = task.get("framework_replay", {}) if isinstance(task.get("framework_replay"), dict) else {}
    results: dict[str, Any] = {}
    last_result: Any = None
    for call in replay.get("tool_calls", []):
        tool = str(call.get("tool") or "")
        if not tool:
            continue
        method = getattr(env, tool)
        args = [_resolve_contract_value(value, results) for value in call.get("args", [])]
        kwargs = {str(key): _resolve_contract_value(value, results) for key, value in dict(call.get("kwargs", {})).items()}
        for key, value in dict(call.get("kwargs_from", {})).items():
            kwargs[str(key)] = _resolve_contract_value(value, results)
        last_result = method(*args, **kwargs)
        results[tool] = last_result
    return last_result


def _resolve_contract_value(value: Any, results: dict[str, Any]) -> Any:
    if not isinstance(value, str):
        return value
    if value in results:
        return results[value]
    if "." in value:
        root, _, path = value.partition(".")
        current = results.get(root)
        for part in path.split("."):
            if isinstance(current, list) and part.endswith("]") and "[" in part:
                name, _, raw_index = part.partition("[")
                if name:
                    current = current.get(name) if isinstance(current, dict) else None
                try:
                    current = current[int(raw_index.rstrip("]"))]
                except Exception:
                    return value
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return value
        return current
    return value


def _contract_negative_answer(task: dict[str, Any]) -> Any:
    expected = task.get("expected_answer")
    if expected not in (None, "", {}):
        return {"accepted": False, "reason": "negative replay"}
    return None


def _contract_expected_state_or_answer_evidence(task: dict[str, Any], initial: dict[str, Any], final: dict[str, Any], final_answer: Any) -> dict[str, Any]:
    expected_answer = task.get("expected_answer")
    if expected_answer not in (None, "", {}):
        return {
            "kind": "expected_answer",
            "success": final_answer == expected_answer,
            "expected": expected_answer,
            "actual": final_answer,
        }
    expected_delta = task.get("expected_state_delta", {})
    if expected_delta:
        return {
            "kind": "expected_state_delta",
            "success": initial != final,
            "expected": expected_delta,
            "actual": {"initial_equals_final": initial == final},
        }
    return {
        "kind": "state_or_answer_presence",
        "success": final_answer not in (None, "", {}),
        "expected": "non-empty final answer or explicit state delta",
        "actual": final_answer,
    }


def _execute_positive_case(task_id: str, runtime_class: Any, state: dict[str, Any], trace_path: Path) -> Any:
    env = _instantiate_runtime(runtime_class, state, trace_path=trace_path, task_id=task_id, call_group="positive")
    if task_id == "pb-task-1":
        env.card_list(status="blocked")
        env.card_get("C-11")
        env.card_move(card_id="C-11", status="in_review", note="Ready for review after checking the blocker.")
        return None
    if task_id == "pb-task-2":
        env.card_list(priority="high")
        env.card_assign(card_id="C-10", assignee="sam", note="Sam is taking triage.")
        env.comment_add(card_id="C-10", body="Triage comment added for Sam.")
        return None
    cards = env.card_list(status="in_progress", assignee="eve")
    return {
        "status": "in_progress",
        "assignee": "eve",
        "card_count": len(cards),
        "highest_priority": _highest_priority(cards),
    }


def _execute_booking_positive_case(task_id: str, runtime_class: Any, state: dict[str, Any], trace_path: Path) -> Any:
    env = _instantiate_runtime(runtime_class, state, trace_path=trace_path, task_id=task_id, call_group="positive")
    if task_id == "booking-task-1":
        events = env.search_events(city="Shanghai", kind="concert")
        event_id = events[0]["event_id"]
        env.check_availability(event_id)
        hold = env.hold_seats(event_id=event_id, quantity=2, customer_id="C-1")
        env.confirm_booking(hold_id=hold["hold_id"], payment_status="authorized")
        return None
    if task_id == "booking-task-2":
        env.cancel_booking(booking_id="B-200", refund=True)
        return None
    events = env.search_events(city="Shanghai", kind="concert")
    availability = env.check_availability(events[0]["event_id"])
    return {"event_id": availability["event_id"], "available_seats": availability["available_seats"], "price": availability["price"]}


def _execute_library_positive_case(task_id: str, runtime_class: Any, state: dict[str, Any], trace_path: Path) -> Any:
    env = _instantiate_runtime(runtime_class, state, trace_path=trace_path, task_id=task_id, call_group="positive")
    if task_id == "library-task-1":
        books = env.search_books(keyword="distributed")
        book_id = books[0]["book_id"]
        env.check_availability(book_id)
        env.borrow_book(book_id=book_id, patron_id="P-1")
        return None
    if task_id == "library-task-2":
        env.return_book(loan_id="L-200", days_late=2)
        return None
    books = env.search_books(keyword="distributed")
    availability = env.check_availability(books[0]["book_id"])
    return {"book_id": availability["book_id"], "available_copies": availability["available_copies"], "title": availability["title"]}


def _instantiate_runtime(runtime_class: Any, state: dict[str, Any], *, trace_path: Path, task_id: str, call_group: str) -> Any:
    try:
        return runtime_class(state, trace_path=trace_path, task_id=task_id, call_group=call_group)
    except TypeError:
        return runtime_class(state, trace_path=trace_path, task_id=task_id)


def _call_verifier(
    verifier_fn: Callable[..., dict[str, Any]],
    task: dict[str, Any],
    initial: dict[str, Any],
    final: dict[str, Any],
    final_answer: Any,
    trace_path: Path,
    call_group: str,
) -> dict[str, Any]:
    task_id = task["task_id"]
    try:
        signature = inspect.signature(verifier_fn)
        params = signature.parameters
        accepts_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        kwargs = {
            "surface_trace_path": trace_path,
            "expected_dependency_path": list(task.get("dependency_path", [])),
            "trace_call_group": call_group,
            "final_answer": final_answer,
        }
        filtered = {
            name: value
            for name, value in kwargs.items()
            if accepts_var_kwargs or name in params
        }
        result = verifier_fn(task_id, copy.deepcopy(initial), copy.deepcopy(final), **filtered)
    except Exception as exc:
        exc_info = exception_payload(exc, phase="call_verifier", traceback_text=traceback.format_exc())
        return {
            "task_id": task_id,
            "success": False,
            "checks": [{"name": "verifier_exception", "passed": False, "detail": f"{exc.__class__.__name__}: {exc}"}],
            "exception": exc_info,
        }
    if not isinstance(result, dict):
        return {"task_id": task_id, "success": False, "checks": [{"name": "verifier_result_is_object", "passed": False, "detail": type(result).__name__}]}
    result.setdefault("task_id", task_id)
    result.setdefault("checks", [])
    return result


def _negative_answer(task_id: str) -> Any:
    if task_id == "pb-task-3":
        return {"status": "in_progress", "assignee": "eve", "card_count": 0, "highest_priority": "none"}
    return None


def _expected_state_or_answer_evidence(task_id: str, initial: dict[str, Any], final: dict[str, Any], final_answer: Any) -> dict[str, Any]:
    if task_id == "pb-task-1":
        card = _card(final, "C-11")
        success = card.get("status") == "in_review" and _has_audit(final, "C-11", "card_moved", "status", "in_review") and _non_target_cards_preserved(initial, final, {"C-11"})
        return {"kind": "expected_state_delta", "success": success, "card": card, "audit_events": final.get("audit_event", [])}
    if task_id == "pb-task-2":
        card = _card(final, "C-10")
        has_comment = any(comment.get("card_id") == "C-10" and "triage" in str(comment.get("body", "")).lower() for comment in final.get("comment", []))
        success = card.get("assignee") == "sam" and has_comment and _has_audit(final, "C-10", "card_assigned", "assignee", "sam") and _non_target_cards_preserved(initial, final, {"C-10"})
        return {"kind": "expected_state_delta", "success": success, "card": card, "comments": final.get("comment", []), "audit_events": final.get("audit_event", [])}
    expected = {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"}
    return {"kind": "expected_answer", "success": final_answer == expected and initial == final, "expected": expected, "actual": final_answer}


def _booking_expected_state_or_answer_evidence(task_id: str, initial: dict[str, Any], final: dict[str, Any], final_answer: Any) -> dict[str, Any]:
    if task_id == "booking-task-1":
        booking = _matching_booking(final, event_id="EVT-100", customer_id="C-1", quantity=2)
        payment = _payment_for_booking(final, booking.get("booking_id", ""))
        inventory_success = _booking_inventory(final, "EVT-100").get("available") == _booking_inventory(initial, "EVT-100").get("available") - 2
        success = booking.get("status") == "confirmed" and payment.get("status") == "authorized" and inventory_success and _has_booking_audit(final, "booking_confirmed")
        return {"kind": "expected_state_delta", "success": success, "booking": booking, "payment": payment, "inventory": _booking_inventory(final, "EVT-100"), "audit_events": final.get("audit_event", [])}
    if task_id == "booking-task-2":
        booking = _booking(final, "B-200")
        payment = _payment_for_booking(final, "B-200")
        inventory_success = _booking_inventory(final, "EVT-200").get("available") == _booking_inventory(initial, "EVT-200").get("available") + 1
        success = booking.get("status") == "canceled" and payment.get("status") == "refunded" and inventory_success and _has_booking_audit(final, "booking_canceled") and _has_booking_audit(final, "seats_released")
        return {"kind": "expected_state_delta", "success": success, "booking": booking, "payment": payment, "inventory": _booking_inventory(final, "EVT-200"), "audit_events": final.get("audit_event", [])}
    expected = {"event_id": "EVT-100", "available_seats": 4, "price": 120}
    return {"kind": "expected_answer", "success": final_answer == expected and initial == final, "expected": expected, "actual": final_answer}


def _library_expected_state_or_answer_evidence(task_id: str, initial: dict[str, Any], final: dict[str, Any], final_answer: Any) -> dict[str, Any]:
    if task_id == "library-task-1":
        loan = _matching_loan(final, book_id="BK-100", patron_id="P-1")
        inventory_success = _library_inventory(final, "BK-100").get("available") == _library_inventory(initial, "BK-100").get("available") - 1
        success = loan.get("status") == "active" and inventory_success and _has_library_audit(final, "loan_created")
        return {"kind": "expected_state_delta", "success": success, "loan": loan, "inventory": _library_inventory(final, "BK-100"), "audit_events": final.get("audit_event", [])}
    if task_id == "library-task-2":
        loan = _library_loan(final, "L-200")
        fine = _fine_for_loan(final, "L-200")
        inventory_success = _library_inventory(final, "BK-200").get("available") == _library_inventory(initial, "BK-200").get("available") + 1
        success = loan.get("status") == "returned" and fine.get("amount") == 10 and inventory_success and _has_library_audit(final, "loan_returned")
        return {"kind": "expected_state_delta", "success": success, "loan": loan, "fine": fine, "inventory": _library_inventory(final, "BK-200"), "audit_events": final.get("audit_event", [])}
    expected = {"book_id": "BK-100", "available_copies": 2, "title": "Distributed Systems"}
    return {"kind": "expected_answer", "success": final_answer == expected and initial == final, "expected": expected, "actual": final_answer}


def _trace_tools(path: Path, *, task_id: str, call_group: str) -> list[str]:
    if not path.exists():
        return []
    tools = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("task_id") != task_id:
            continue
        if record.get("call_group") not in {call_group, None, ""}:
            continue
        if "tool" in record:
            tools.append(str(record["tool"]))
    return tools


def _highest_priority(cards: list[dict[str, Any]]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "urgent": 3}
    if not cards:
        return "none"
    return max((str(card.get("priority", "none")) for card in cards), key=lambda item: order.get(item, -1))


def _card(state: dict[str, Any], card_id: str) -> dict[str, Any]:
    for card in state.get("card", []):
        if card.get("id") == card_id:
            return card
    return {}


def _booking(state: dict[str, Any], booking_id: str) -> dict[str, Any]:
    for booking in state.get("booking", []):
        if booking.get("booking_id") == booking_id:
            return booking
    return {}


def _matching_booking(state: dict[str, Any], *, event_id: str, customer_id: str, quantity: int) -> dict[str, Any]:
    for booking in state.get("booking", []):
        if booking.get("event_id") == event_id and booking.get("customer_id") == customer_id and booking.get("quantity") == quantity:
            return booking
    return {}


def _booking_inventory(state: dict[str, Any], event_id: str) -> dict[str, Any]:
    for inventory in state.get("seat_inventory", []):
        if inventory.get("event_id") == event_id:
            return inventory
    return {}


def _payment_for_booking(state: dict[str, Any], booking_id: str) -> dict[str, Any]:
    for payment in state.get("payment", []):
        if payment.get("booking_id") == booking_id:
            return payment
    return {}


def _has_booking_audit(state: dict[str, Any], event_type: str) -> bool:
    return any(event.get("event_type") == event_type for event in state.get("audit_event", []))


def _library_inventory(state: dict[str, Any], book_id: str) -> dict[str, Any]:
    for inventory in state.get("book_inventory", []):
        if inventory.get("book_id") == book_id:
            return inventory
    return {}


def _library_loan(state: dict[str, Any], loan_id: str) -> dict[str, Any]:
    for loan in state.get("loan", []):
        if loan.get("loan_id") == loan_id:
            return loan
    return {}


def _matching_loan(state: dict[str, Any], *, book_id: str, patron_id: str) -> dict[str, Any]:
    for loan in state.get("loan", []):
        if loan.get("book_id") == book_id and loan.get("patron_id") == patron_id:
            return loan
    return {}


def _fine_for_loan(state: dict[str, Any], loan_id: str) -> dict[str, Any]:
    for fine in state.get("fine", []):
        if fine.get("loan_id") == loan_id:
            return fine
    return {}


def _has_library_audit(state: dict[str, Any], event_type: str) -> bool:
    return any(event.get("event_type") == event_type for event in state.get("audit_event", []))


def _has_audit(state: dict[str, Any], card_id: str, event_type: str, field: str, new_value: str) -> bool:
    for event in state.get("audit_event", []):
        observed_new = event.get("new_value", event.get("new", ""))
        if event.get("card_id") == card_id and event.get("event_type") == event_type and event.get("field") == field and observed_new == new_value:
            return True
    return False


def _non_target_cards_preserved(initial: dict[str, Any], final: dict[str, Any], target_ids: set[str]) -> bool:
    initial_cards = {card["id"]: card for card in initial.get("card", []) if card.get("id") not in target_ids}
    final_cards = {card["id"]: card for card in final.get("card", []) if card.get("id") not in target_ids}
    return initial_cards == final_cards


def _task_exception_record(
    environment_id: str,
    task_id: str,
    exc_info: dict[str, Any],
    *,
    phase: str,
    prerequisite_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    prefix = {
        "project-board-lite": "project-board",
        "booking-service-lite": "booking",
        "library-lending-lite": "library",
    }.get(environment_id, environment_id)
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
        "check_id": f"{prefix}-independent-{task_id}",
        "success": False,
        "status": "fail",
        "verifier_kind": "framework_independent_generated_bundle",
        "environment_id": environment_id,
        "task_id": task_id,
        "phase": phase,
        "command": "framework import runtime.py/verifier.py and execute generated runtime",
        "exit_code": None,
        "stdout": "",
        "stderr": stderr,
        "positive_verifier_result": {},
        "negative_verifier_result": {},
        "framework_evidence": {"prerequisite_checks": prerequisite_checks or []},
        "exception": exc_info,
        "task_observation": observation,
        "failure_class": observation["failure_class"],
        "recovery_suggestion": observation["recovery_suggestion"],
    }


def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True

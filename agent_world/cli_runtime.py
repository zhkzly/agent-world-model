from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from agent_world.artifacts import read_yaml, stable_json, write_jsonl
from agent_world.online_runtime import (
    RuntimeAction,
    SupportDeskLiteOnlineSession,
    load_online_runtime,
    validate_online_step_record,
    validate_surface_runtime_index,
)
from agent_world.training import read_jsonl


SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")
STDIO_PREVIEW_LIMIT = 500


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    package_dir = Path(args.package)
    command_argv = _command_argv(args)
    try:
        _validate_cli_command(package_dir, args.command, command_argv, getattr(args, "tool", ""))
        if args.command == "health":
            return _emit({"status": "ok", "surface": "runtime_control_cli", "package_dir": str(package_dir), "descriptor": _cli_descriptor(package_dir)})
        if args.command == "reset":
            return _reset(package_dir, args.task, args.run, command_argv)
        if args.command == "observe":
            return _observe(package_dir, args.session)
        if args.command == "step":
            return _step(package_dir, args.session, args.tool, args.args_json, command_argv)
        if args.command == "finalize":
            return _finalize(package_dir, args.session, args.answer, args.answer_json)
        raise ValueError(f"Unsupported CLI runtime command: {args.command}")
    except Exception as exc:
        payload = {"status": "error", "error": exc.__class__.__name__, "message": str(exc)}
        sys.stderr.write(stable_json(payload))
        sys.stderr.write("\n")
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m agent_world.cli_runtime")
    parser.add_argument("--package", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health")

    reset = subparsers.add_parser("reset")
    reset.add_argument("--task", required=True)
    reset.add_argument("--run", default=None)

    observe = subparsers.add_parser("observe")
    observe.add_argument("--session", required=True)

    step = subparsers.add_parser("step")
    step.add_argument("--session", required=True)
    step.add_argument("--tool", required=True)
    step.add_argument("--args-json", default="{}")

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--session", required=True)
    finalize.add_argument("--answer", default=None)
    finalize.add_argument("--answer-json", default=None)
    return parser


def _reset(package_dir: Path, task_id: str, run_id: str | None, command_argv: list[str]) -> int:
    runtime = load_online_runtime(package_dir)
    runtime.start()
    try:
        session = runtime.reset(task_id, run_id=run_id)
        observation = session.observe()
        _write_session_state(package_dir, session)
        payload = {
            "status": "ok",
            "session_id": session.session_id,
            "task_id": task_id,
            "run_id": session.run_id,
            "command": _command_record(command_argv, 0, "", "", "reset"),
            "observation": observation.to_dict(),
        }
        return _emit(payload)
    finally:
        runtime.close()


def _observe(package_dir: Path, session_id: str) -> int:
    runtime, session = _load_session(package_dir, session_id)
    try:
        payload = {"status": "ok", "session_id": session_id, "observation": session.observe().to_dict()}
        _write_session_state(package_dir, session)
        return _emit(payload)
    finally:
        runtime.close()


def _step(package_dir: Path, session_id: str, tool_name: str, args_json: str, command_argv: list[str]) -> int:
    arguments = _parse_json_object(args_json, "--args-json")
    runtime, session = _load_session(package_dir, session_id)
    try:
        template_id = f"runtime-control-cli-step-{tool_name}"
        action = RuntimeAction(
            action_id=f"{template_id}-{session._step_index}",
            kind="tool_call",
            tool_name=tool_name,
            arguments=arguments,
            metadata={"surface": "runtime_control_cli", "command_template_id": template_id},
        )
        step = session.step(action)
        base_payload = {"status": "ok", "session_id": session_id, "step": step.to_dict()}
        command = _command_record(command_argv, 0, stable_json(base_payload), "", template_id)
        _attach_command_to_observation(package_dir, step.observation.trace_ref, command)
        _attach_command_to_step_records(package_dir, step, command)
        payload = {"status": "ok", "session_id": session_id, "command": command, "step": step.to_dict()}
        payload["step"]["observation"]["command"] = command
        _write_session_state(package_dir, session)
        return _emit(payload)
    finally:
        runtime.close()


def _finalize(package_dir: Path, session_id: str, answer: str | None, answer_json: str | None) -> int:
    runtime, session = _load_session(package_dir, session_id)
    try:
        final_answer: str | dict[str, Any] | None = answer
        if answer_json is not None:
            final_answer = _parse_json_value(answer_json, "--answer-json")
        final = session.finalize(final_answer)
        _write_session_state(package_dir, session)
        return _emit({"status": "ok", "session_id": session_id, "final": final.to_dict()})
    finally:
        runtime.close()


def _load_session(package_dir: Path, session_id: str) -> tuple[Any, SupportDeskLiteOnlineSession]:
    state = _read_session_state(package_dir, session_id)
    runtime = load_online_runtime(package_dir)
    runtime.start()
    task = runtime.tasks_by_id[state["task_id"]]
    db_path = package_dir / state["db_ref"]
    trace_path = package_dir / state["surface_trace_ref"]
    step_records_path = package_dir / state["step_records_ref"]
    final_records_path = package_dir / state["final_records_ref"]
    surface = runtime.surface_class(db_path, trace_path=trace_path, task_id=state["task_id"], call_group=session_id)
    session = SupportDeskLiteOnlineSession(
        runtime=runtime,
        task=task,
        run_id=state["run_id"],
        session_id=session_id,
        session_dir=package_dir / state["session_dir_ref"],
        db_path=db_path,
        trace_path=trace_path,
        step_records_path=step_records_path,
        final_records_path=final_records_path,
        surface=surface,
        initial_snapshot_hash=state["initial_snapshot_hash"],
    )
    session._step_index = int(state.get("next_step_index", 0))
    session._finalized = bool(state.get("finalized", False))
    session._final_answer = state.get("final_answer")
    return runtime, session


def _write_session_state(package_dir: Path, session: SupportDeskLiteOnlineSession) -> None:
    state = {
        "session_id": session.session_id,
        "run_id": session.run_id,
        "task_id": session.task_id,
        "session_dir_ref": _relative_ref(session.session_dir, package_dir),
        "db_ref": _relative_ref(session.db_path, package_dir),
        "surface_trace_ref": _relative_ref(session.trace_path, package_dir),
        "step_records_ref": _relative_ref(session.step_records_path, package_dir),
        "final_records_ref": _relative_ref(session.final_records_path, package_dir),
        "initial_snapshot_hash": session.initial_snapshot_hash,
        "next_step_index": session._step_index,
        "finalized": session._finalized,
        "final_answer": session._final_answer,
    }
    state_path = _session_state_path(package_dir, session.session_id)
    session_path = session.session_dir / "session-state.json"
    _write_json(state_path, state)
    _write_json(session_path, state)


def _read_session_state(package_dir: Path, session_id: str) -> dict[str, Any]:
    _validate_session_id(session_id)
    path = _session_state_path(package_dir, session_id)
    if not path.exists():
        raise KeyError(f"Unknown CLI runtime session: {session_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _session_state_path(package_dir: Path, session_id: str) -> Path:
    _validate_session_id(session_id)
    return package_dir / "online_rollouts" / "_sessions" / f"{session_id}.json"


def _validate_session_id(session_id: str) -> None:
    if not SESSION_ID_RE.match(session_id):
        raise ValueError("Session id contains unsupported characters")


def _validate_cli_command(package_dir: Path, command: str, argv: list[str], tool_name: str) -> None:
    descriptor = _cli_descriptor(package_dir)
    if descriptor.get("status") != "implemented":
        raise ValueError("CLI surface descriptor is not implemented")
    if command not in descriptor.get("allowed_subcommands", []):
        raise ValueError(f"CLI command is not allowlisted: {command}")
    _reject_shell_features(argv, descriptor)
    if command == "step":
        allowed_tools = set(descriptor.get("allowed_runtime_tools", []))
        if tool_name not in allowed_tools:
            raise ValueError(f"CLI tool is not allowlisted: {tool_name}")


def _cli_descriptor(package_dir: Path) -> dict[str, Any]:
    index = read_yaml(package_dir / "release" / "surface-runtime-index.yaml")
    validate_surface_runtime_index(package_dir, index)
    for descriptor in index["descriptors"]:
        if descriptor.get("kind") == "runtime_control_cli":
            return descriptor
    raise ValueError("surface-runtime-index.yaml lacks runtime_control_cli descriptor")


def _reject_shell_features(argv: list[str], descriptor: dict[str, Any]) -> None:
    forbidden = set(descriptor.get("forbidden_shell_features", []))
    shell_words = {"bash", "sh", "zsh", "fish", "cmd", "powershell", "pwsh"}
    shell_operators = {"|", ">", "<", "&&", "||", ";", "$("}
    skip_next_for = {"--package", "--task", "--run", "--session", "--args-json", "--answer", "--answer-json"}
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token in skip_next_for:
            skip_next = True
            continue
        if token in shell_words:
            raise ValueError(f"Forbidden shell executable in CLI argv: {token}")
        if token == "-c":
            raise ValueError("Forbidden shell -c flag in CLI argv")
        for marker in forbidden & shell_operators:
            if marker and marker in token:
                raise ValueError(f"Forbidden shell feature in CLI argv: {marker}")


def _attach_command_to_step_records(package_dir: Path, step: Any, command: dict[str, Any]) -> None:
    record_id = f"online-step-{step.run_id}-{step.task_id}-{step.step_index}"
    updates = {
        "command": command,
        "surface_kind": "runtime_control_cli",
        "command_argv": command["argv"],
        "rendered_argv": command["argv"],
        "exit_code": command["exit_code"],
        "stdout_preview": command["stdout_preview"],
        "stderr_preview": command["stderr_preview"],
        "parsed_output_preview": command["stdout_preview"],
        "command_template_id": command["template_id"],
        "command_descriptor_ref": command["descriptor_ref"],
    }
    for path in [package_dir / step.observation.trace_ref.split("/observations/", 1)[0] / "step-records.jsonl", package_dir / "checks" / "online-step-records.jsonl"]:
        _update_jsonl_record(path, record_id, updates)


def _attach_command_to_observation(package_dir: Path, observation_ref: str, command: dict[str, Any]) -> None:
    path = package_dir / observation_ref
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["command"] = command
    _write_json(path, payload)


def _update_jsonl_record(path: Path, record_id: str, updates: dict[str, Any]) -> None:
    rows = read_jsonl(path)
    replaced = False
    for row in rows:
        if row.get("record_id") == record_id:
            row.update(updates)
            validate_online_step_record(row)
            replaced = True
    if not replaced:
        raise KeyError(f"Step record not found: {record_id}")
    write_jsonl(path, rows)


def _command_record(command_argv: list[str], exit_code: int, stdout: str, stderr: str, template_id: str) -> dict[str, Any]:
    return {
        "argv": list(command_argv),
        "exit_code": int(exit_code),
        "stdout_preview": stdout[:STDIO_PREVIEW_LIMIT],
        "stderr_preview": stderr[:STDIO_PREVIEW_LIMIT],
        "template_id": template_id,
        "descriptor_ref": "release/surface-runtime-index.yaml#runtime-control-cli-support-desk-lite",
    }


def _command_argv(args: argparse.Namespace) -> list[str]:
    argv = ["python", "-m", "agent_world.cli_runtime", "--package", str(args.package), args.command]
    if args.command == "reset":
        argv.extend(["--task", args.task])
        if args.run:
            argv.extend(["--run", args.run])
    elif args.command == "observe":
        argv.extend(["--session", args.session])
    elif args.command == "step":
        argv.extend(["--session", args.session, "--tool", args.tool, "--args-json", args.args_json])
    elif args.command == "finalize":
        argv.extend(["--session", args.session])
        if args.answer is not None:
            argv.extend(["--answer", args.answer])
        if args.answer_json is not None:
            argv.extend(["--answer-json", args.answer_json])
    return argv


def _parse_json_object(raw: str, flag: str) -> dict[str, Any]:
    value = _parse_json_value(raw, flag)
    if not isinstance(value, dict):
        raise ValueError(f"{flag} must decode to a JSON object")
    return value


def _parse_json_value(raw: str, flag: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{flag} is not valid JSON: {exc}") from exc


def _emit(payload: dict[str, Any]) -> int:
    sys.stdout.write(stable_json(payload))
    sys.stdout.write("\n")
    return 0


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")


def _relative_ref(path: Path, package_dir: Path) -> str:
    return Path(path).relative_to(package_dir).as_posix()


if __name__ == "__main__":
    raise SystemExit(main())

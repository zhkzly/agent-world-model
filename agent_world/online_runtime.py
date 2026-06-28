from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from agent_world.artifacts import read_yaml, stable_json, write_jsonl
from agent_world.fixtures.support_desk_lite import snapshot_hash
from agent_world.rollout import FIXED_CREATED_AT, REWARD_SOURCE, validate_no_secret_material
from agent_world.training import read_jsonl


DEFAULT_ONLINE_RUN_ID = "online-run-support-desk-lite-001"
ONLINE_RUNTIME_CONTRACT_VERSION = "0.1.0"
STDIO_PREVIEW_LIMIT = 500
FORBIDDEN_SHELL_FEATURES = ["bash", "sh", "-c", "|", ">", "<", "&&", "||", ";", "$("]


@dataclass(frozen=True)
class RuntimeAction:
    action_id: str
    kind: str
    tool_name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    raw_model_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeObservation:
    task_id: str
    natural_request: str
    observation_text: str
    available_tools: list[str]
    last_tool_result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    done: bool = False
    trace_ref: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeStepResult:
    task_id: str
    run_id: str
    session_id: str
    step_index: int
    action: RuntimeAction
    observation: RuntimeObservation
    tool_result: Any
    done: bool
    error: dict[str, Any] | None
    trace_ref: str
    state_snapshot_hash: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.to_dict()
        payload["observation"] = self.observation.to_dict()
        return payload


@dataclass(frozen=True)
class RuntimeFinalResult:
    task_id: str
    run_id: str
    session_id: str
    success: bool
    reward: float
    reward_source: str
    verifier_result: dict[str, Any]
    surface_trace_ref: str
    step_trace_ref: str
    initial_snapshot_hash: str
    final_snapshot_hash: str
    failure_class: str
    recovery_suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OnlineEnvSession(Protocol):
    def observe(self) -> RuntimeObservation:
        ...

    def step(self, action: RuntimeAction) -> RuntimeStepResult:
        ...

    def finalize(self, answer: str | dict[str, Any] | None = None) -> RuntimeFinalResult:
        ...


class OnlineEnvRuntime(Protocol):
    def start(self) -> None:
        ...

    def reset(self, task_id: str, *, run_id: str | None = None) -> OnlineEnvSession:
        ...

    def close(self) -> None:
        ...


class SupportDeskLiteOnlineRuntime:
    """Online runtime bridge for the hardcoded support-desk-lite release package."""

    def __init__(self, package_dir: Path):
        self.package_dir = Path(package_dir)
        self.release: dict[str, Any] = {}
        self.runtime_index: dict[str, Any] = {}
        self.surface_runtime_index: dict[str, Any] = {}
        self.environment_cli_descriptor: dict[str, Any] = {}
        self.tasks_by_id: dict[str, dict[str, Any]] = {}
        self.surface_class: Any = None
        self.reset_function: Any = None
        self.verifier_function: Any = None
        self.started = False

    def start(self) -> None:
        self.release = read_yaml(self.package_dir / "release" / "release-manifest.yaml")
        self.runtime_index = read_yaml(self.package_dir / "release" / "runtime-index.yaml")
        self.surface_runtime_index = read_yaml(self.package_dir / "release" / "surface-runtime-index.yaml")
        validate_runtime_index(self.package_dir, self.runtime_index)
        validate_surface_runtime_index(self.package_dir, self.surface_runtime_index)
        if self.release["environment_id"] != "support-desk-lite":
            raise ValueError("SupportDeskLiteOnlineRuntime only supports support-desk-lite")
        self.environment_cli_descriptor = _environment_cli_descriptor(self.surface_runtime_index)

        tasks = read_yaml(self.package_dir / "spec" / "tasks.yaml")["tasks"]
        self.tasks_by_id = {task["task_id"]: task for task in tasks}
        descriptor = _python_surface_descriptor(self.surface_runtime_index)
        self.surface_class = _load_ref(descriptor["surface_class"])
        _load_ref(descriptor["seed_function"])
        self.reset_function = _load_ref(descriptor["reset_function"])
        self.verifier_function = _load_ref(descriptor["verifier_function"])
        for binding in descriptor["tool_bindings"]:
            if not hasattr(self.surface_class, binding["exposure_name"]):
                raise AttributeError(f"Python surface lacks tool binding: {binding['exposure_name']}")
        self.started = True

    def reset(self, task_id: str, *, run_id: str | None = None) -> OnlineEnvSession:
        if not self.started:
            raise RuntimeError("Online runtime must be started before reset")
        if task_id not in self.tasks_by_id:
            raise ValueError(f"Unknown task_id: {task_id}")
        run_id = run_id or DEFAULT_ONLINE_RUN_ID
        session_id = f"session-{run_id}-{task_id}"
        session_dir = self.package_dir / "online_rollouts" / run_id / task_id
        state_dir = session_dir / "state"
        if session_dir.exists():
            _remove_tree(session_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        seed = self.package_dir / "fixtures" / "seed" / "support-desk-lite.sqlite"
        db_path = self.reset_function(seed, state_dir)
        trace_path = session_dir / "surface-trace.jsonl"
        step_records_path = session_dir / "step-records.jsonl"
        final_records_path = session_dir / "final-records.jsonl"
        write_jsonl(step_records_path, [])
        write_jsonl(final_records_path, [])
        surface = self.surface_class(db_path, trace_path=trace_path, task_id=task_id, call_group=session_id)
        return SupportDeskLiteOnlineSession(
            runtime=self,
            task=self.tasks_by_id[task_id],
            run_id=run_id,
            session_id=session_id,
            session_dir=session_dir,
            db_path=db_path,
            trace_path=trace_path,
            step_records_path=step_records_path,
            final_records_path=final_records_path,
            surface=surface,
            initial_snapshot_hash=snapshot_hash(db_path),
        )

    def close(self) -> None:
        self.started = False


class SupportDeskLiteOnlineSession:
    def __init__(
        self,
        *,
        runtime: SupportDeskLiteOnlineRuntime,
        task: dict[str, Any],
        run_id: str,
        session_id: str,
        session_dir: Path,
        db_path: Path,
        trace_path: Path,
        step_records_path: Path,
        final_records_path: Path,
        surface: Any,
        initial_snapshot_hash: str,
    ):
        self.runtime = runtime
        self.task = task
        self.task_id = task["task_id"]
        self.run_id = run_id
        self.session_id = session_id
        self.session_dir = session_dir
        self.db_path = db_path
        self.trace_path = trace_path
        self.step_records_path = step_records_path
        self.final_records_path = final_records_path
        self.surface = surface
        self.initial_snapshot_hash = initial_snapshot_hash
        self._step_index = 0
        self._finalized = False
        self._final_answer: str | dict[str, Any] | None = None

    def observe(self) -> RuntimeObservation:
        return self._observation(label=f"observe-{self._step_index}", last_tool_result=None, error=None, done=self._finalized)

    def step(self, action: RuntimeAction) -> RuntimeStepResult:
        if self._finalized:
            raise RuntimeError("Session is already finalized")
        tool_result: Any = None
        error: dict[str, Any] | None = None
        command_evidence: dict[str, Any] | None = None
        done = False
        if action.kind == "tool_call":
            if action.tool_name not in self.task["allowed_logical_tool_ids"]:
                error = {"type": "invalid_tool", "message": f"Tool is not allowed for task: {action.tool_name}"}
            elif _requested_surface_kind(action) == "environment_cli":
                try:
                    tool_result, error, command_evidence = self._execute_environment_cli_action(action)
                except Exception as exc:  # pragma: no cover - validation errors are surfaced in records.
                    error = {"type": exc.__class__.__name__, "message": str(exc)}
            elif _requested_surface_kind(action) not in {"python_callable", "python", "runtime_control_cli", "cli"}:
                error = {
                    "type": "unsupported_surface",
                    "message": f"Unsupported runtime surface: {_requested_surface_kind(action)}",
                }
            elif not hasattr(self.surface, action.tool_name):
                error = {"type": "unknown_tool", "message": f"Unknown runtime tool: {action.tool_name}"}
            else:
                try:
                    tool_result = getattr(self.surface, action.tool_name)(**action.arguments)
                except Exception as exc:  # pragma: no cover - exact exception type is surfaced in records.
                    error = {"type": exc.__class__.__name__, "message": str(exc)}
        elif action.kind == "final_answer":
            self._final_answer = action.arguments.get("answer", action.raw_model_output)
            done = True
        elif action.kind == "noop":
            tool_result = {"status": "noop"}
        else:
            error = {"type": "invalid_action_kind", "message": f"Unsupported action kind: {action.kind}"}

        snapshot = snapshot_hash(self.db_path)
        observation = self._observation(
            label=f"step-{self._step_index}",
            last_tool_result=tool_result,
            error=error,
            done=done,
        )
        result = RuntimeStepResult(
            task_id=self.task_id,
            run_id=self.run_id,
            session_id=self.session_id,
            step_index=self._step_index,
            action=action,
            observation=observation,
            tool_result=tool_result,
            done=done,
            error=error,
            trace_ref=_relative_ref(self.trace_path, self.runtime.package_dir),
            state_snapshot_hash=snapshot,
        )
        record = self._step_record(result)
        if command_evidence:
            record.update(command_evidence)
        validate_online_step_record(record)
        _append_jsonl(self.step_records_path, record)
        _append_jsonl(self.runtime.package_dir / "checks" / "online-step-records.jsonl", record)
        self._step_index += 1
        return result

    def _execute_environment_cli_action(self, action: RuntimeAction) -> tuple[Any, dict[str, Any] | None, dict[str, Any]]:
        descriptor = self.runtime.environment_cli_descriptor
        template = _environment_cli_template(descriptor, action.tool_name)
        _validate_environment_cli_arguments(template, action.arguments)
        rendered_argv = _render_environment_cli_argv(
            template,
            action.arguments,
            package_dir=self.runtime.package_dir,
            db_path=self.db_path,
            trace_path=self.trace_path,
            task_id=self.task_id,
            session_id=self.session_id,
        )
        _reject_shell_features(rendered_argv, descriptor["forbidden_shell_features"])
        timeout_seconds = float(template.get("timeout_ms", descriptor["timeout_ms"])) / 1000.0
        completed = subprocess.run(
            rendered_argv,
            check=False,
            capture_output=True,
            text=True,
            shell=False,
            timeout=timeout_seconds,
            cwd=self.runtime.package_dir,
            env=_subprocess_env(),
        )
        parsed_output: Any = {}
        parse_error: dict[str, Any] | None = None
        if completed.stdout.strip():
            try:
                parsed_output = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                parse_error = {"type": "invalid_cli_json", "message": str(exc)}
        error: dict[str, Any] | None = parse_error
        if completed.returncode not in template["allowed_exit_codes"]:
            error = {
                "type": "environment_cli_exit_code",
                "message": f"Environment CLI exited with {completed.returncode}",
            }
        tool_result = parsed_output.get("result") if isinstance(parsed_output, dict) and "result" in parsed_output else parsed_output
        command = _environment_cli_command_evidence(
            descriptor=descriptor,
            template=template,
            rendered_argv=rendered_argv,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            parsed_output=parsed_output,
        )
        return tool_result, error, command

    def finalize(self, answer: str | dict[str, Any] | None = None) -> RuntimeFinalResult:
        if self._finalized:
            raise RuntimeError("Session is already finalized")
        final_answer = answer if answer is not None else self._final_answer
        verifier_result = self.runtime.verifier_function(
            self.task_id,
            self.runtime.package_dir / "fixtures" / "seed" / "support-desk-lite.sqlite",
            self.db_path,
            final_answer=final_answer,
            surface_trace_path=self.trace_path,
            expected_dependency_path=self.task["dependency_path"],
            trace_call_group=self.session_id,
        )
        verifier_result = _sanitize_verifier_result(verifier_result, self.runtime.package_dir)
        success = bool(verifier_result["success"])
        failure_class = "" if success else "deterministic_verifier_failed"
        recovery = "" if success else "Inspect verifier_result.checks and step_trace_ref, then retry with the required tool sequence and arguments."
        result = RuntimeFinalResult(
            task_id=self.task_id,
            run_id=self.run_id,
            session_id=self.session_id,
            success=success,
            reward=1.0 if success else 0.0,
            reward_source=REWARD_SOURCE,
            verifier_result=verifier_result,
            surface_trace_ref=_relative_ref(self.trace_path, self.runtime.package_dir),
            step_trace_ref=_relative_ref(self.step_records_path, self.runtime.package_dir),
            initial_snapshot_hash=self.initial_snapshot_hash,
            final_snapshot_hash=snapshot_hash(self.db_path),
            failure_class=failure_class,
            recovery_suggestion=recovery,
        )
        record = self._final_record(result)
        validate_online_final_record(record)
        _append_jsonl(self.final_records_path, record)
        _append_jsonl(self.runtime.package_dir / "checks" / "online-final-records.jsonl", record)
        self._finalized = True
        return result

    def _observation(
        self,
        *,
        label: str,
        last_tool_result: Any,
        error: dict[str, Any] | None,
        done: bool,
    ) -> RuntimeObservation:
        observation_dir = self.session_dir / "observations"
        path = observation_dir / f"{label}.json"
        if error:
            text = "The last tool call failed. Use the error field to decide the next action."
        elif done:
            text = "The session is ready for final verification."
        elif last_tool_result is None:
            text = f"User request: {self.task['natural_request']}"
        else:
            text = "The last tool call completed. Continue with the user request or finalize."
        observation = RuntimeObservation(
            task_id=self.task_id,
            natural_request=self.task["natural_request"],
            observation_text=text,
            available_tools=list(self.task["allowed_logical_tool_ids"]),
            last_tool_result={"preview": _preview(last_tool_result)} if last_tool_result is not None else None,
            error=error,
            done=done,
            trace_ref=_relative_ref(path, self.runtime.package_dir),
        )
        _write_json(path, observation.to_dict())
        return observation

    def _step_record(self, result: RuntimeStepResult) -> dict[str, Any]:
        record = {
            "record_id": f"online-step-{self.run_id}-{self.task_id}-{result.step_index}",
            "record_type": "online_step",
            "environment_id": self.runtime.release["environment_id"],
            "release_id": self.runtime.release["release_id"],
            "task_id": self.task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "step_index": result.step_index,
            "surface_kind": _requested_surface_kind(result.action),
            "action_kind": result.action.kind,
            "tool_name": result.action.tool_name,
            "argument_keys": sorted(result.action.arguments),
            "action": {
                "action_id": result.action.action_id,
                "kind": result.action.kind,
                "tool_name": result.action.tool_name,
                "argument_keys": sorted(result.action.arguments),
                "raw_model_output_preview": result.action.raw_model_output[:200],
                "metadata": result.action.metadata,
            },
            "observation_ref": result.observation.trace_ref,
            "tool_result_preview": _preview(result.tool_result),
            "state_snapshot_hash": result.state_snapshot_hash,
            "trace_ref": result.trace_ref,
            "error": result.error or {},
            "created_at": FIXED_CREATED_AT,
        }
        return record

    def _final_record(self, result: RuntimeFinalResult) -> dict[str, Any]:
        return {
            "record_id": f"online-final-{self.run_id}-{self.task_id}",
            "record_type": "online_final",
            "environment_id": self.runtime.release["environment_id"],
            "release_id": self.runtime.release["release_id"],
            "task_id": self.task_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "success": result.success,
            "reward": result.reward,
            "reward_source": result.reward_source,
            "verifier_result": result.verifier_result,
            "initial_snapshot_hash": result.initial_snapshot_hash,
            "final_snapshot_hash": result.final_snapshot_hash,
            "surface_trace_ref": result.surface_trace_ref,
            "step_trace_ref": result.step_trace_ref,
            "failure_class": result.failure_class,
            "recovery_suggestion": result.recovery_suggestion,
            "created_at": FIXED_CREATED_AT,
        }


def load_online_runtime(package_dir: Path) -> SupportDeskLiteOnlineRuntime:
    return SupportDeskLiteOnlineRuntime(package_dir)


def runtime_index_for_release(*, release: dict[str, Any] | None = None) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    return {
        "runtime_index_id": f"runtime-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "contract": "OnlineEnvRuntime",
        "contract_version": ONLINE_RUNTIME_CONTRACT_VERSION,
        "runtime_module": "agent_world.online_runtime",
        "runtime_loader": "agent_world.online_runtime.load_online_runtime",
        "runtime_class": "agent_world.online_runtime.SupportDeskLiteOnlineRuntime",
        "lifecycle": ["start", "reset", "observe", "step", "finalize", "close"],
        "default_surface": "python_callable",
        "surface_runtime_index_ref": "release/surface-runtime-index.yaml",
        "online_records": {
            "step_records_ref": "checks/online-step-records.jsonl",
            "final_records_ref": "checks/online-final-records.jsonl",
            "run_records_dir": "online_rollouts/",
        },
        "reward": {
            "reward_source": REWARD_SOURCE,
            "success_reward": 1.0,
            "failure_reward": 0.0,
            "verifier_bridge": "agent_world.fixtures.support_desk_lite.verify_task_completion",
        },
        "known_limits": [
            "The support-desk-lite Python callable, runtime_control_cli, environment_cli, and HTTP surfaces are executable in Goal 04.",
            "MCP remains descriptor-only.",
            "No trainer, verl, Ray, vLLM, or SGLang dependency is required.",
        ],
    }


def surface_runtime_index_for_release(
    *,
    release: dict[str, Any] | None = None,
    surface_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    release = release or {"environment_id": "support-desk-lite", "release_id": "release-support-desk-lite"}
    bindings = []
    if surface_plan:
        bindings = [
            {
                "logical_tool_id": binding["logical_tool_id"],
                "exposure_name": binding["logical_tool_id"],
                "callable": f"agent_world.fixtures.support_desk_lite.SupportDeskLite.{binding['logical_tool_id']}",
            }
            for binding in surface_plan["bindings"]
            if binding["surface"] == "python"
        ]
    if not bindings:
        bindings = [
            {
                "logical_tool_id": tool_id,
                "exposure_name": tool_id,
                "callable": f"agent_world.fixtures.support_desk_lite.SupportDeskLite.{tool_id}",
            }
            for tool_id in ["search_tickets", "get_ticket", "add_ticket_note", "update_ticket_priority", "assign_ticket", "resolve_ticket"]
        ]
    return {
        "surface_runtime_index_id": f"surface-runtime-{release['environment_id']}",
        "environment_id": release["environment_id"],
        "release_id": release["release_id"],
        "default_surface": "python_callable",
        "descriptors": [
            {
                "surface_id": "python-support-desk-lite",
                "kind": "python_callable",
                "status": "implemented",
                "surface_class": "agent_world.fixtures.support_desk_lite.SupportDeskLite",
                "seed_function": "agent_world.fixtures.support_desk_lite.create_seed_db",
                "reset_function": "agent_world.fixtures.support_desk_lite.reset_environment",
                "verifier_function": "agent_world.fixtures.support_desk_lite.verify_task_completion",
                "tool_bindings": bindings,
                "health_check": {
                    "import_check": "import agent_world.fixtures.support_desk_lite",
                    "callable_existence_check": [
                        "SupportDeskLite.search_tickets",
                        "SupportDeskLite.get_ticket",
                        "SupportDeskLite.add_ticket_note",
                        "SupportDeskLite.update_ticket_priority",
                        "SupportDeskLite.assign_ticket",
                        "SupportDeskLite.resolve_ticket",
                    ],
                },
            },
            {
                "surface_id": "mcp-support-desk-lite",
                "kind": "mcp_server",
                "status": "descriptor_only_deferred",
                "launch_command": [],
                "transport": "stdio",
                "host": "",
                "port": None,
                "health_check": "not_implemented",
                "list_tools_check": "not_implemented",
                "tool_schema_ref": "spec/surfaces.yaml",
                "shutdown_policy": "not_started",
            },
            {
                "surface_id": "runtime-control-cli-support-desk-lite",
                "kind": "runtime_control_cli",
                "status": "implemented",
                "purpose": "harness_control",
                "mode": "one_shot",
                "module": "agent_world.cli_runtime",
                "allowed_subcommands": ["health", "reset", "observe", "step", "finalize"],
                "allowed_runtime_tools": [binding["exposure_name"] for binding in bindings],
                "launch_command": ["python", "-m", "agent_world.cli_runtime", "--package", "."],
                "health_check_command": ["python", "-m", "agent_world.cli_runtime", "--package", ".", "health"],
                "reset_command": ["python", "-m", "agent_world.cli_runtime", "--package", ".", "reset", "--task", "{task_id}", "--run", "{run_id}"],
                "observe_command": ["python", "-m", "agent_world.cli_runtime", "--package", ".", "observe", "--session", "{session_id}"],
                "step_command": [
                    "python",
                    "-m",
                    "agent_world.cli_runtime",
                    "--package",
                    ".",
                    "step",
                    "--session",
                    "{session_id}",
                    "--tool",
                    "{tool_name}",
                    "--args-json",
                    "{args_json}",
                ],
                "finalize_command": ["python", "-m", "agent_world.cli_runtime", "--package", ".", "finalize", "--session", "{session_id}"],
                "command_templates": [
                    {"template_id": "runtime-control-cli-health", "subcommand": "health", "argv": ["python", "-m", "agent_world.cli_runtime", "--package", "{package_dir}", "health"]},
                    {
                        "template_id": "runtime-control-cli-reset",
                        "subcommand": "reset",
                        "argv": ["python", "-m", "agent_world.cli_runtime", "--package", "{package_dir}", "reset", "--task", "{task_id}", "--run", "{run_id}"],
                    },
                    {
                        "template_id": "runtime-control-cli-observe",
                        "subcommand": "observe",
                        "argv": ["python", "-m", "agent_world.cli_runtime", "--package", "{package_dir}", "observe", "--session", "{session_id}"],
                    },
                    {
                        "template_id": "runtime-control-cli-finalize",
                        "subcommand": "finalize",
                        "argv": ["python", "-m", "agent_world.cli_runtime", "--package", "{package_dir}", "finalize", "--session", "{session_id}"],
                    },
                ],
                "forbidden_shell_features": FORBIDDEN_SHELL_FEATURES,
                "timeout_ms": 1000,
                "working_dir_policy": "package_scoped",
                "stdout_schema": "JSON object with status and command-specific payload.",
                "stderr_schema": "JSON error object on command validation failure.",
            },
            {
                "surface_id": "environment-cli-support-desk-lite",
                "kind": "environment_cli",
                "status": "implemented",
                "purpose": "agent_tool_surface",
                "mode": "one_shot",
                "module": "agent_world.fixtures.support_desk_lite_cli",
                "discovery": {
                    "help_command": ["python", "-m", "agent_world.fixtures.support_desk_lite_cli", "--help"],
                    "schema_ref": "spec/surfaces.yaml",
                    "source_kind": "cli_help",
                },
                "allowed_tool_names": [binding["exposure_name"] for binding in bindings],
                "tool_command_templates": _environment_cli_tool_templates(bindings),
                "forbidden_shell_features": FORBIDDEN_SHELL_FEATURES,
                "timeout_ms": 1000,
                "state_scope": "session",
                "working_dir_policy": "package_scoped",
            },
            {
                "surface_id": "http-support-desk-lite",
                "kind": "http_service",
                "status": "implemented",
                "launch_command": ["python", "-m", "agent_world.http_runtime", "--package", ".", "--host", "127.0.0.1", "--port", "8000"],
                "base_url": "http://127.0.0.1:8000",
                "health_endpoint": "/health",
                "runtime_endpoint": "/runtime",
                "reset_endpoint": "/reset",
                "observe_endpoint": "/observe",
                "step_endpoint": "/step",
                "finalize_endpoint": "/finalize",
                "verify_endpoint": "",
                "auth_policy": "none",
                "timeout_ms": 1000,
            },
        ],
    }


def _environment_cli_tool_templates(bindings: list[dict[str, str]]) -> list[dict[str, Any]]:
    schema_by_tool = {
        "search_tickets": {
            "required": [],
            "properties": {
                "status": {"type": "string"},
                "customer_tier": {"type": "string"},
                "keyword": {"type": "string"},
                "queue": {"type": "string"},
            },
        },
        "get_ticket": {
            "required": ["ticket_id"],
            "properties": {"ticket_id": {"type": "string"}},
        },
        "add_ticket_note": {
            "required": ["ticket_id", "visibility", "body"],
            "properties": {
                "ticket_id": {"type": "string"},
                "visibility": {"type": "string", "enum": ["internal", "customer"]},
                "body": {"type": "string"},
            },
        },
        "update_ticket_priority": {
            "required": ["ticket_id", "priority", "note"],
            "properties": {
                "ticket_id": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
                "note": {"type": "string"},
            },
        },
        "assign_ticket": {
            "required": ["ticket_id", "queue", "assignee", "note"],
            "properties": {
                "ticket_id": {"type": "string"},
                "queue": {"type": "string"},
                "assignee": {"type": "string"},
                "note": {"type": "string"},
            },
        },
        "resolve_ticket": {
            "required": ["ticket_id", "resolution_note"],
            "properties": {
                "ticket_id": {"type": "string"},
                "resolution_note": {"type": "string"},
            },
        },
    }
    argv_by_tool = {
        "search_tickets": [
            "search-tickets",
            "--status",
            "{status}",
            "--customer-tier",
            "{customer_tier}",
            "--keyword",
            "{keyword}",
            "--queue",
            "{queue}",
        ],
        "get_ticket": ["get-ticket", "--ticket-id", "{ticket_id}"],
        "add_ticket_note": ["add-ticket-note", "--ticket-id", "{ticket_id}", "--visibility", "{visibility}", "--body", "{body}"],
        "update_ticket_priority": ["update-ticket-priority", "--ticket-id", "{ticket_id}", "--priority", "{priority}", "--note", "{note}"],
        "assign_ticket": ["assign-ticket", "--ticket-id", "{ticket_id}", "--queue", "{queue}", "--assignee", "{assignee}", "--note", "{note}"],
        "resolve_ticket": ["resolve-ticket", "--ticket-id", "{ticket_id}", "--resolution-note", "{resolution_note}"],
    }
    templates: list[dict[str, Any]] = []
    for binding in bindings:
        tool_name = binding["exposure_name"]
        if tool_name not in schema_by_tool:
            continue
        templates.append(
            {
                "template_id": f"environment-cli-{tool_name}",
                "tool_name": tool_name,
                "logical_tool_id": binding["logical_tool_id"],
                "argv_template": [
                    "{python_executable}",
                    "-m",
                    "agent_world.fixtures.support_desk_lite_cli",
                    "--db",
                    "{session_db}",
                    "--trace",
                    "{trace_path}",
                    "--task-id",
                    "{task_id}",
                    "--call-group",
                    "{session_id}",
                    *argv_by_tool[tool_name],
                ],
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    **schema_by_tool[tool_name],
                },
                "output_parser": "json_stdout",
                "allowed_exit_codes": [0],
                "timeout_ms": 1000,
                "state_scope": "session",
            }
        )
    return templates


def validate_runtime_index(package_dir: Path, index: dict[str, Any]) -> None:
    required = [
        "runtime_index_id",
        "environment_id",
        "release_id",
        "contract",
        "contract_version",
        "runtime_loader",
        "lifecycle",
        "surface_runtime_index_ref",
        "online_records",
        "reward",
    ]
    _require(index, required, "RuntimeIndex")
    if index["contract"] != "OnlineEnvRuntime":
        raise ValueError("RuntimeIndex.contract must be OnlineEnvRuntime")
    for method in ["start", "reset", "observe", "step", "finalize", "close"]:
        if method not in index["lifecycle"]:
            raise ValueError(f"RuntimeIndex.lifecycle missing {method}")
    for ref in [
        index["surface_runtime_index_ref"],
        index["online_records"]["step_records_ref"],
        index["online_records"]["final_records_ref"],
    ]:
        _validate_package_ref(package_dir, ref)
    if index["reward"]["reward_source"] != REWARD_SOURCE:
        raise ValueError("RuntimeIndex.reward.reward_source must be deterministic_verifier")
    _load_ref(index["runtime_loader"])
    validate_no_secret_material(index)


def validate_surface_runtime_index(package_dir: Path, index: dict[str, Any]) -> None:
    _require(index, ["surface_runtime_index_id", "environment_id", "release_id", "default_surface", "descriptors"], "SurfaceRuntimeIndex")
    kinds = {descriptor["kind"] for descriptor in index["descriptors"]}
    if "cli" in kinds:
        raise ValueError("SurfaceRuntimeIndex must split CLI descriptors into runtime_control_cli and environment_cli")
    for expected in {"python_callable", "mcp_server", "runtime_control_cli", "environment_cli", "http_service"}:
        if expected not in kinds:
            raise ValueError(f"SurfaceRuntimeIndex missing {expected} descriptor")
    python_descriptor = _python_surface_descriptor(index)
    for field_name in ["surface_class", "seed_function", "reset_function", "verifier_function", "tool_bindings", "health_check"]:
        if field_name not in python_descriptor:
            raise ValueError(f"Python surface descriptor missing {field_name}")
    surface_class = _load_ref(python_descriptor["surface_class"])
    for ref in [python_descriptor["seed_function"], python_descriptor["reset_function"], python_descriptor["verifier_function"]]:
        if not callable(_load_ref(ref)):
            raise ValueError(f"Python surface descriptor ref is not callable: {ref}")
    for binding in python_descriptor["tool_bindings"]:
        _require(binding, ["logical_tool_id", "exposure_name", "callable"], "PythonToolBinding")
        if not hasattr(surface_class, binding["exposure_name"]):
            raise ValueError(f"Python surface class lacks binding: {binding['exposure_name']}")
    _validate_runtime_control_cli_descriptor(_descriptor(index, "runtime_control_cli"))
    _validate_environment_cli_descriptor(_environment_cli_descriptor(index))
    validate_no_secret_material(index)


def validate_online_step_record(record: dict[str, Any]) -> None:
    required = [
        "record_id",
        "record_type",
        "environment_id",
        "release_id",
        "task_id",
        "run_id",
        "session_id",
        "step_index",
        "action_kind",
        "tool_name",
        "argument_keys",
        "action",
        "observation_ref",
        "tool_result_preview",
        "state_snapshot_hash",
        "trace_ref",
        "error",
        "created_at",
    ]
    _require(record, required, "OnlineStepRecord")
    if record["record_type"] != "online_step":
        raise ValueError("OnlineStepRecord.record_type must be online_step")
    if record["action_kind"] not in {"tool_call", "final_answer", "noop"}:
        raise ValueError("OnlineStepRecord.action_kind is unsupported")
    if not isinstance(record["step_index"], int):
        raise ValueError("OnlineStepRecord.step_index must be an integer")
    if not isinstance(record["argument_keys"], list):
        raise ValueError("OnlineStepRecord.argument_keys must be a list")
    for ref_field in ["observation_ref", "trace_ref"]:
        if Path(str(record[ref_field]).split("#", 1)[0]).is_absolute():
            raise ValueError(f"OnlineStepRecord.{ref_field} must be package-relative")
    encoded = stable_json(record).lower()
    if "db_path" in encoded:
        raise ValueError("OnlineStepRecord must not expose runtime database paths")
    if "command" in record:
        _require(record["command"], ["argv", "exit_code", "stdout_preview", "stderr_preview", "template_id", "descriptor_ref"], "OnlineStepRecord.command")
        if not isinstance(record["command"]["argv"], list):
            raise ValueError("OnlineStepRecord.command.argv must be a list")
        if record.get("command_argv") != record["command"]["argv"]:
            raise ValueError("OnlineStepRecord.command_argv must match command.argv")
        if record.get("exit_code") != record["command"]["exit_code"]:
            raise ValueError("OnlineStepRecord.exit_code must match command.exit_code")
    if record.get("surface_kind") == "environment_cli" and (not record.get("error") or "command" in record):
        _require(
            record,
            [
                "command_descriptor_ref",
                "command_template_id",
                "rendered_argv",
                "exit_code",
                "stdout_preview",
                "stderr_preview",
                "parsed_output_preview",
                "state_snapshot_hash",
                "trace_ref",
                "error",
            ],
            "EnvironmentCliOnlineStepRecord",
        )
        if not isinstance(record["rendered_argv"], list):
            raise ValueError("EnvironmentCliOnlineStepRecord.rendered_argv must be a list")
        if not str(record["command_descriptor_ref"]).startswith("release/surface-runtime-index.yaml#environment-cli-"):
            raise ValueError("EnvironmentCliOnlineStepRecord.command_descriptor_ref must reference the environment_cli descriptor")
    validate_no_secret_material(record)


def validate_online_final_record(record: dict[str, Any]) -> None:
    required = [
        "record_id",
        "record_type",
        "environment_id",
        "release_id",
        "task_id",
        "run_id",
        "session_id",
        "success",
        "reward",
        "reward_source",
        "verifier_result",
        "initial_snapshot_hash",
        "final_snapshot_hash",
        "surface_trace_ref",
        "step_trace_ref",
        "failure_class",
        "recovery_suggestion",
        "created_at",
    ]
    _require(record, required, "OnlineFinalRecord")
    if record["record_type"] != "online_final":
        raise ValueError("OnlineFinalRecord.record_type must be online_final")
    if not isinstance(record["success"], bool):
        raise ValueError("OnlineFinalRecord.success must be boolean")
    if record["reward_source"] != REWARD_SOURCE:
        raise ValueError("OnlineFinalRecord.reward_source must be deterministic_verifier")
    if record["reward"] != (1.0 if record["success"] else 0.0):
        raise ValueError("OnlineFinalRecord.reward must be derived from verifier success")
    if not record["success"] and (not record["failure_class"] or not record["recovery_suggestion"]):
        raise ValueError("Failed OnlineFinalRecord needs failure_class and recovery_suggestion")
    for ref_field in ["surface_trace_ref", "step_trace_ref"]:
        if Path(str(record[ref_field]).split("#", 1)[0]).is_absolute():
            raise ValueError(f"OnlineFinalRecord.{ref_field} must be package-relative")
    validate_no_secret_material(record)


def validate_online_records(package_dir: Path) -> dict[str, int]:
    package_dir = Path(package_dir)
    step_records = read_jsonl(package_dir / "checks" / "online-step-records.jsonl")
    final_records = read_jsonl(package_dir / "checks" / "online-final-records.jsonl")
    for record in step_records:
        validate_online_step_record(record)
    for record in final_records:
        validate_online_final_record(record)
    return {"online_step_records": len(step_records), "online_final_records": len(final_records)}


def _python_surface_descriptor(index: dict[str, Any]) -> dict[str, Any]:
    return _descriptor(index, "python_callable")


def _environment_cli_descriptor(index: dict[str, Any]) -> dict[str, Any]:
    return _descriptor(index, "environment_cli")


def _descriptor(index: dict[str, Any], kind: str) -> dict[str, Any]:
    for descriptor in index["descriptors"]:
        if descriptor.get("kind") == kind:
            return descriptor
    raise ValueError(f"SurfaceRuntimeIndex lacks {kind} descriptor")


def _validate_runtime_control_cli_descriptor(descriptor: dict[str, Any]) -> None:
    required = [
        "surface_id",
        "kind",
        "status",
        "purpose",
        "mode",
        "module",
        "allowed_subcommands",
        "allowed_runtime_tools",
        "launch_command",
        "health_check_command",
        "reset_command",
        "observe_command",
        "step_command",
        "finalize_command",
        "command_templates",
        "forbidden_shell_features",
        "timeout_ms",
        "working_dir_policy",
    ]
    _require(descriptor, required, "RuntimeControlCliDescriptor")
    if descriptor["kind"] != "runtime_control_cli":
        raise ValueError("Runtime control CLI descriptor must use kind=runtime_control_cli")
    if descriptor["purpose"] != "harness_control":
        raise ValueError("Runtime control CLI descriptor purpose must be harness_control")
    if descriptor["status"] != "implemented":
        raise ValueError("Runtime control CLI descriptor must be implemented")
    if descriptor["mode"] not in {"one_shot", "json_stdin_stdout", "daemon"}:
        raise ValueError("Runtime control CLI descriptor has invalid mode")
    expected = {"health", "reset", "observe", "step", "finalize"}
    if set(descriptor["allowed_subcommands"]) != expected:
        raise ValueError("Runtime control CLI descriptor allowed_subcommands must cover lifecycle commands")
    _load_ref("agent_world.cli_runtime.main")
    for command_field in ["launch_command", "health_check_command", "reset_command", "observe_command", "step_command", "finalize_command"]:
        _validate_cli_argv_template(descriptor[command_field], descriptor["forbidden_shell_features"])
    for template in descriptor["command_templates"]:
        _require(template, ["template_id", "subcommand", "argv"], "CliCommandTemplate")
        if template["subcommand"] not in expected:
            raise ValueError("CLI command template uses non-allowlisted subcommand")
        _validate_cli_argv_template(template["argv"], descriptor["forbidden_shell_features"])


def _validate_environment_cli_descriptor(descriptor: dict[str, Any]) -> None:
    required = [
        "surface_id",
        "kind",
        "status",
        "purpose",
        "mode",
        "module",
        "discovery",
        "allowed_tool_names",
        "tool_command_templates",
        "forbidden_shell_features",
        "timeout_ms",
        "state_scope",
        "working_dir_policy",
    ]
    _require(descriptor, required, "EnvironmentCliDescriptor")
    if descriptor["kind"] != "environment_cli":
        raise ValueError("Environment CLI descriptor must use kind=environment_cli")
    if descriptor["purpose"] != "agent_tool_surface":
        raise ValueError("Environment CLI descriptor purpose must be agent_tool_surface")
    if descriptor["status"] != "implemented":
        raise ValueError("Environment CLI descriptor must be implemented")
    if descriptor["mode"] not in {"one_shot", "json_stdin_stdout", "daemon"}:
        raise ValueError("Environment CLI descriptor has invalid mode")
    _require(descriptor["discovery"], ["help_command", "schema_ref"], "EnvironmentCliDiscovery")
    _validate_cli_argv_template(descriptor["discovery"]["help_command"], descriptor["forbidden_shell_features"])
    _load_ref("agent_world.fixtures.support_desk_lite_cli.main")
    allowed_tool_names = set(descriptor["allowed_tool_names"])
    template_tool_names: set[str] = set()
    for template in descriptor["tool_command_templates"]:
        _require(
            template,
            [
                "template_id",
                "tool_name",
                "logical_tool_id",
                "argv_template",
                "input_schema",
                "output_parser",
                "allowed_exit_codes",
                "timeout_ms",
                "state_scope",
            ],
            "EnvironmentCliToolCommandTemplate",
        )
        if template["tool_name"] not in allowed_tool_names:
            raise ValueError(f"Environment CLI template uses non-allowlisted tool: {template['tool_name']}")
        if template["output_parser"] != "json_stdout":
            raise ValueError("Environment CLI output_parser must be json_stdout")
        if template["allowed_exit_codes"] != [0]:
            raise ValueError("Environment CLI allowed_exit_codes must be [0]")
        if template["state_scope"] != "session":
            raise ValueError("Environment CLI state_scope must be session")
        _validate_input_schema(template["input_schema"])
        _validate_cli_argv_template(template["argv_template"], descriptor["forbidden_shell_features"])
        template_tool_names.add(template["tool_name"])
    if template_tool_names != allowed_tool_names:
        raise ValueError("Environment CLI allowed_tool_names must match tool_command_templates")


def _validate_cli_argv_template(argv: Any, forbidden_features: list[str]) -> None:
    if not isinstance(argv, list) or not argv:
        raise ValueError("CLI command template argv must be a non-empty list")
    for token in argv:
        if not isinstance(token, str):
            raise ValueError("CLI command template argv tokens must be strings")
        if token in {"bash", "sh", "zsh", "fish", "cmd", "powershell", "pwsh"}:
            raise ValueError("CLI command template must not invoke a shell")
        if token == "-c":
            raise ValueError("CLI command template must not use shell -c")
        for marker in forbidden_features:
            if marker in {"bash", "sh", "-c"}:
                continue
            if marker and marker in token and token not in {"{args_json}", "{package_dir}", "{session_id}", "{task_id}", "{run_id}", "{tool_name}"}:
                raise ValueError(f"CLI command template contains forbidden shell feature: {marker}")


def _validate_input_schema(schema: dict[str, Any]) -> None:
    _require(schema, ["type", "additionalProperties", "required", "properties"], "EnvironmentCliInputSchema")
    if schema["type"] != "object":
        raise ValueError("Environment CLI input schema type must be object")
    if schema["additionalProperties"] is not False:
        raise ValueError("Environment CLI input schema must reject additional properties")
    if not isinstance(schema["required"], list):
        raise ValueError("Environment CLI input schema required must be a list")
    if not isinstance(schema["properties"], dict):
        raise ValueError("Environment CLI input schema properties must be an object")
    for name, property_schema in schema["properties"].items():
        if property_schema.get("type") != "string":
            raise ValueError(f"Environment CLI input property must be a string: {name}")
        if "enum" in property_schema and not isinstance(property_schema["enum"], list):
            raise ValueError(f"Environment CLI input property enum must be a list: {name}")


def _requested_surface_kind(action: RuntimeAction) -> str:
    surface = action.metadata.get("surface") if action.metadata else None
    return str(surface or "python_callable")


def _environment_cli_template(descriptor: dict[str, Any], tool_name: str) -> dict[str, Any]:
    for template in descriptor["tool_command_templates"]:
        if template["tool_name"] == tool_name:
            return template
    raise ValueError(f"Environment CLI tool is not allowlisted: {tool_name}")


def _validate_environment_cli_arguments(template: dict[str, Any], arguments: dict[str, Any]) -> None:
    schema = template["input_schema"]
    properties = schema["properties"]
    unknown = sorted(set(arguments) - set(properties))
    if unknown:
        raise ValueError(f"Environment CLI arguments contain undeclared keys: {unknown}")
    missing = [name for name in schema["required"] if name not in arguments]
    if missing:
        raise ValueError(f"Environment CLI arguments missing required keys: {missing}")
    for name, value in arguments.items():
        property_schema = properties[name]
        if not isinstance(value, str):
            raise ValueError(f"Environment CLI argument must be a string: {name}")
        allowed_values = property_schema.get("enum")
        if allowed_values and value not in allowed_values:
            raise ValueError(f"Environment CLI argument has unsupported value for {name}: {value}")


def _render_environment_cli_argv(
    template: dict[str, Any],
    arguments: dict[str, Any],
    *,
    package_dir: Path,
    db_path: Path,
    trace_path: Path,
    task_id: str,
    session_id: str,
) -> list[str]:
    context = {
        "python_executable": sys.executable,
        "session_db": _relative_ref(db_path, package_dir),
        "trace_path": _relative_ref(trace_path, package_dir),
        "task_id": task_id,
        "session_id": session_id,
    }
    for name in template["input_schema"]["properties"]:
        context[name] = ""
    context.update(arguments)
    rendered: list[str] = []
    for token in template["argv_template"]:
        rendered_token = token
        for key, value in context.items():
            rendered_token = rendered_token.replace("{" + key + "}", str(value))
        if "{" in rendered_token or "}" in rendered_token:
            raise ValueError(f"Environment CLI argv template has unresolved placeholder: {token}")
        rendered.append(rendered_token)
    return rendered


def _reject_shell_features(argv: list[str], forbidden_features: list[str]) -> None:
    shell_words = {"bash", "sh", "zsh", "fish", "cmd", "powershell", "pwsh"}
    shell_operators = {"|", ">", "<", "&&", "||", ";", "$("}
    forbidden = set(forbidden_features)
    for token in argv:
        token_parts = token.split()
        if token in shell_words or any(part in shell_words for part in token_parts):
            raise ValueError(f"Forbidden shell executable in environment CLI argv: {token}")
        if token == "-c" or "-c" in token_parts:
            raise ValueError("Forbidden shell -c flag in environment CLI argv")
        for marker in forbidden & shell_operators:
            if marker and marker in token:
                raise ValueError(f"Forbidden shell feature in environment CLI argv: {marker}")


def _environment_cli_command_evidence(
    *,
    descriptor: dict[str, Any],
    template: dict[str, Any],
    rendered_argv: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    parsed_output: Any,
) -> dict[str, Any]:
    command = {
        "argv": list(rendered_argv),
        "exit_code": int(exit_code),
        "stdout_preview": stdout[:STDIO_PREVIEW_LIMIT],
        "stderr_preview": stderr[:STDIO_PREVIEW_LIMIT],
        "template_id": template["template_id"],
        "descriptor_ref": f"release/surface-runtime-index.yaml#{descriptor['surface_id']}",
    }
    return {
        "surface_kind": "environment_cli",
        "command": command,
        "command_argv": command["argv"],
        "rendered_argv": command["argv"],
        "exit_code": command["exit_code"],
        "stdout_preview": command["stdout_preview"],
        "stderr_preview": command["stderr_preview"],
        "parsed_output_preview": _preview(parsed_output),
        "command_template_id": command["template_id"],
        "command_descriptor_ref": command["descriptor_ref"],
    }


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[1])
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_root if not existing else f"{repo_root}{os.pathsep}{existing}"
    return env


def _load_ref(dotted_ref: str) -> Any:
    module_name, _, attr_path = dotted_ref.partition(":")
    if not attr_path:
        module_name, _, attr_path = dotted_ref.rpartition(".")
    if not module_name or not attr_path:
        raise ValueError(f"Invalid dotted ref: {dotted_ref}")
    obj = importlib.import_module(module_name)
    for part in attr_path.split("."):
        obj = getattr(obj, part)
    return obj


def _relative_ref(path: Path, package_dir: Path) -> str:
    return Path(path).relative_to(package_dir).as_posix()


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json(record))
        handle.write("\n")


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2), encoding="utf-8")


def _preview(value: Any, *, limit: int = 500) -> str:
    if value is None:
        return ""
    try:
        text = stable_json(value)
    except TypeError:
        text = str(value)
    return text[:limit]


def _sanitize_verifier_result(result: dict[str, Any], package_dir: Path) -> dict[str, Any]:
    sanitized = copy.deepcopy(result)
    for check in sanitized.get("checks", []):
        detail = check.get("detail")
        if isinstance(detail, dict) and detail.get("trace_path"):
            try:
                detail["trace_path"] = _relative_ref(Path(detail["trace_path"]), package_dir)
            except ValueError:
                detail["trace_path"] = Path(detail["trace_path"]).name
    return sanitized


def _validate_package_ref(package_dir: Path, ref: str) -> None:
    if Path(str(ref).split("#", 1)[0]).is_absolute():
        raise ValueError(f"Package ref must be relative: {ref}")
    if not (Path(package_dir) / str(ref).split("#", 1)[0]).exists():
        raise FileNotFoundError(Path(package_dir) / str(ref).split("#", 1)[0])


def _require(record: dict[str, Any], fields: list[str], label: str) -> None:
    missing = [field for field in fields if field not in record]
    if missing:
        raise ValueError(f"{label} missing required fields: {missing}")


def _remove_tree(path: Path) -> None:
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()

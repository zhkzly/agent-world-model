from __future__ import annotations

import contextlib
import importlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Protocol

from agent_world.artifacts import make_artifact, stable_json
from agent_world.config import (
    InvocationProfileConfig,
    IMPLEMENTATION_INVOCATION_PROFILE,
    SEMANTIC_INVOCATION_PROFILE,
    load_agent_world_config,
)


CODEX_SDK_MODEL_PROVIDER_ID = "agent_world_openai"


class CodexSdkContinuationUnavailable(RuntimeError):
    """Raised when an IMPLEMENT repair requested Codex SDK continuation that cannot be resumed."""


@dataclass(frozen=True)
class InvocationRequest:
    stage: str
    node_purpose: str
    instruction: str
    input_artifact_ids: list[str]
    invocation_id: str = ""
    allowed_tool_access: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=lambda: {"network": False, "filesystem": "artifact_context", "auth": False, "sandbox": False})
    budget: dict[str, Any] = field(default_factory=lambda: {"tokens": 0, "time_ms": 5000, "cost_limit": 0})
    instruction_ref: str = "inline"
    parent_invocation_id: str = ""
    conversation_ref: str = ""
    continuation_mode: str = "stateless"


@dataclass(frozen=True)
class InvocationResult:
    text: str
    evidence_refs: list[str] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    trace_ref: str = ""
    status: str = "pass"
    failure_class: str = ""
    recovery_suggestion: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    conversation_ref: str = ""


class InvocationBackend(Protocol):
    backend_kind: str

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        ...


class MockInvocationBackend:
    backend_kind = "mock"

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        key = f"{request.stage}:{request.node_purpose}"
        if key not in self.responses:
            return InvocationResult(
                text="mock backend is not allowed to produce accepted invocation output",
                status="needs_human",
                failure_class="mock_backend_not_allowed",
                recovery_suggestion=f"Configure a real InvocationBackend or an explicit test response for {key}.",
            )
        text = self.responses[key]
        return InvocationResult(text=text, evidence_refs=[f"mock://{key}"], trace_ref=f"mock-trace:{key}")


class ManualInvocationBackend:
    backend_kind = "manual"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        responses = config.get("manual_responses", {})
        key = f"{request.stage}:{request.node_purpose}"
        if key not in responses:
            return InvocationResult(
                text="manual input required",
                status="needs_human",
                failure_class="manual_input_required",
                recovery_suggestion=f"Provide manual response for {key}",
            )
        return InvocationResult(text=responses[key], evidence_refs=[f"manual://{key}"], trace_ref=f"manual-trace:{key}")


class ProcessInvocationBackend:
    backend_kind = "process_agent"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        try:
            command = _command_argv(config)
            cwd = _safe_cwd(config)
        except ValueError as exc:
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_process_agent_config",
                recovery_suggestion="Use an allowlisted command without shell control operators or unsafe args",
            )
        if not command:
            return InvocationResult(
                text="process agent command is not configured",
                status="fail",
                failure_class="missing_process_command",
                recovery_suggestion="Configure command_value and allowlist_value in the selected YAML invocation profile.",
            )
        timeout_ms = int(config.get("timeouts", {}).get("run_ms") or request.budget.get("time_ms") or 5000)
        if request.permissions.get("network") and not config.get("permissions", {}).get("network"):
            return InvocationResult(
                text="process agent network permission denied",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Use a backend config that explicitly allows network access",
            )
        if request.permissions.get("auth"):
            return InvocationResult(
                text="process agent auth passthrough is disabled for the first slice",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Use an API-specific backend instead of passing secrets to a local process",
            )
        if self.backend_kind == "process_agent":
            if request.permissions.get("sandbox") or config.get("permissions", {}).get("sandbox"):
                return InvocationResult(
                    text="process_agent does not claim OS sandbox enforcement",
                    status="fail",
                    failure_class="invalid_process_agent_config",
                    recovery_suggestion="Record sandbox=false for process_agent or use codex_cli with explicit sandbox flags",
                )
        payload = {
            "stage": request.stage,
            "node_purpose": request.node_purpose,
            "instruction": request.instruction,
            "input_artifact_ids": request.input_artifact_ids,
            "allowed_tool_access": request.allowed_tool_access,
            "permissions": request.permissions,
            "budget": request.budget,
        }
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                input=stable_json(payload),
                text=True,
                capture_output=True,
                timeout=timeout_ms / 1000,
                check=False,
                cwd=cwd,
                env=_scrubbed_env(config, request),
            )
        except subprocess.TimeoutExpired:
            return InvocationResult(
                text="process agent timed out",
                status="fail",
                failure_class="process_timeout",
                recovery_suggestion="Increase timeout or use a cheaper deterministic backend",
            )
        if completed.returncode != 0:
            return InvocationResult(
                text=completed.stderr.strip() or completed.stdout.strip(),
                status="fail",
                failure_class="process_nonzero_exit",
                recovery_suggestion=f"Process exited with {completed.returncode}",
            )
        stdout = completed.stdout.strip()
        try:
            decoded = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            decoded = {"text": stdout}
        if not isinstance(decoded, dict):
            return InvocationResult(
                text="process invocation output is not an object",
                status="fail",
                failure_class="invalid_process_output",
                recovery_suggestion="Return a JSON object matching InvocationResult",
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return InvocationResult(
            text=str(decoded.get("text", stdout)),
            evidence_refs=list(decoded.get("evidence_refs", ["process://stdout"])),
            output_artifact_ids=list(decoded.get("output_artifact_ids", [])),
            trace_ref=str(decoded.get("trace_ref", f"process://stdout?elapsed_ms={elapsed_ms}&exit_code=0")),
            status=str(decoded.get("status", "pass")),
            failure_class=str(decoded.get("failure_class", "")),
            recovery_suggestion=str(decoded.get("recovery_suggestion", "")),
            usage={"tokens": None, "cost": None, "duration_ms": elapsed_ms, "exit_code": 0},
        )


class CodexCliInvocationBackend(ProcessInvocationBackend):
    backend_kind = "codex_cli"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        try:
            _validate_codex_cli_command(config)
        except ValueError as exc:
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_codex_cli_config",
                recovery_suggestion="Use Codex CLI with approval and sandbox flags fixed to non-bypass values",
            )
        return super().invoke(request, config)


class CodeAgentRunnerInvocationBackend:
    backend_kind = "code_agent_runner"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        try:
            command = _command_argv(config)
        except ValueError as exc:
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_code_agent_runner_config",
                recovery_suggestion="Use an allowlisted runner command without shell control operators or unsafe args.",
            )
        if not command:
            return InvocationResult(
                text="code agent runner command is not configured",
                status="fail",
                failure_class="missing_runner_command",
                recovery_suggestion="Configure command_value and allowlist_value in the selected YAML invocation profile.",
            )
        workspace_text = str(request.permissions.get("filesystem_root") or "")
        if not workspace_text:
            return InvocationResult(
                text="code agent runner requires filesystem_root",
                status="fail",
                failure_class="missing_runner_workspace",
                recovery_suggestion="Set request.permissions.filesystem_root to the isolated code-agent workspace.",
            )
        workspace = Path(workspace_text).resolve()
        if not workspace.is_dir():
            return InvocationResult(
                text="code agent runner workspace does not exist",
                status="fail",
                failure_class="missing_runner_workspace",
                recovery_suggestion="Create the code-agent workspace packet before invoking the runner.",
            )
        if request.permissions.get("network") and not config.get("permissions", {}).get("network"):
            return InvocationResult(
                text="code agent runner network permission denied",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Set network: true only for trusted live runners in the selected YAML invocation profile.",
            )
        if request.permissions.get("auth") and not config.get("permissions", {}).get("auth"):
            return InvocationResult(
                text="code agent runner auth permission denied",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Configure explicit auth env refs for trusted live runners.",
            )
        output_dir = workspace / "agent-output"
        output_dir.mkdir(parents=True, exist_ok=True)
        command_log = output_dir / "runner-command-log.jsonl"
        command_log_ref = "agent-workspace://agent-output/runner-command-log.jsonl"
        manifest_ref = "agent-workspace://agent-output/candidate_manifest.json"
        payload = {
            "stage": request.stage,
            "node_purpose": request.node_purpose,
            "instruction": request.instruction,
            "input_artifact_ids": request.input_artifact_ids,
            "allowed_tool_access": request.allowed_tool_access,
            "permissions": request.permissions,
            "budget": request.budget,
            "workspace": str(workspace),
            "generated_dir": str(workspace / "generated"),
            "agent_output_dir": str(output_dir),
        }
        timeout_ms = int(config.get("timeouts", {}).get("run_ms") or request.budget.get("time_ms") or 30000)
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                input=stable_json(payload),
                text=True,
                capture_output=True,
                timeout=timeout_ms / 1000,
                check=False,
                cwd=workspace,
                env=_runner_env(config, request, workspace),
            )
        except subprocess.TimeoutExpired:
            _append_command_log(command_log, command=command, exit_code=None, stdout="", stderr="timeout", duration_ms=timeout_ms)
            return InvocationResult(
                text="code agent runner timed out",
                status="fail",
                failure_class="runner_timeout",
                recovery_suggestion="Increase timeout or reduce runner task scope.",
                trace_ref=command_log_ref,
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        _append_command_log(
            command_log,
            command=command,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_ms=duration_ms,
        )
        if completed.returncode != 0:
            return InvocationResult(
                text=completed.stderr.strip() or completed.stdout.strip(),
                status="fail",
                failure_class="runner_nonzero_exit",
                recovery_suggestion=f"Runner exited with {completed.returncode}.",
                trace_ref=command_log_ref,
                usage={"tokens": None, "cost": None, "duration_ms": duration_ms, "exit_code": completed.returncode},
            )
        manifest_path = output_dir / "candidate_manifest.json"
        if not manifest_path.is_file():
            return InvocationResult(
                text="runner did not write agent-output/candidate_manifest.json",
                status="fail",
                failure_class="missing_runner_manifest",
                recovery_suggestion="Runner must write a candidate manifest after generating files.",
                evidence_refs=[command_log_ref],
                trace_ref=command_log_ref,
            )
        return InvocationResult(
            text=json.dumps({"candidate_manifest_ref": "agent-output/candidate_manifest.json"}, sort_keys=True),
            evidence_refs=[command_log_ref, manifest_ref],
            trace_ref=command_log_ref,
            usage={"tokens": None, "cost": None, "duration_ms": duration_ms, "exit_code": completed.returncode},
        )


class CodexCliRunnerInvocationBackend(CodeAgentRunnerInvocationBackend):
    backend_kind = "codex_cli_runner"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        try:
            _validate_codex_cli_command(config)
        except ValueError as exc:
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_codex_cli_runner_config",
                recovery_suggestion="Use Codex CLI with safe approval and sandbox flags.",
            )
        return super().invoke(request, config)


class CodexSdkInvocationBackend:
    backend_kind = "codex_sdk"

    def __init__(self) -> None:
        self._continued_threads: dict[str, dict[str, Any]] = {}

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        permission_error = _codex_sdk_permission_error(request, config)
        if permission_error:
            return permission_error
        model = config.get("smoke_model") or config.get("model") or ""
        if not model:
            return InvocationResult(
                text="Codex SDK model is not configured",
                status="needs_human",
                failure_class="missing_codex_model",
                recovery_suggestion="Configure model or smoke_model in the selected YAML codex_sdk profile.",
            )
        try:
            sdk_module = importlib.import_module("openai_codex")
        except ModuleNotFoundError:
            return InvocationResult(
                text="openai-codex Python SDK is not installed",
                status="needs_human",
                failure_class="missing_codex_sdk",
                recovery_suggestion="Install the official Codex SDK with `pip install openai-codex`, or use another configured InvocationBackend.",
            )
        Codex = getattr(sdk_module, "Codex", None)
        Sandbox = getattr(sdk_module, "Sandbox", None)
        if Codex is None or Sandbox is None:
            return InvocationResult(
                text="openai_codex module does not expose Codex and Sandbox",
                status="fail",
                failure_class="invalid_codex_sdk",
                recovery_suggestion="Use an official openai-codex build that exposes Codex and Sandbox.",
            )
        sandbox, sandbox_error = _codex_sdk_sandbox(Sandbox, config)
        if sandbox_error:
            return sandbox_error
        workspace, workspace_error = _codex_sdk_workspace(request)
        if workspace_error:
            return workspace_error
        output_dir = workspace / "agent-output" if workspace else None
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        conversation_ref = request.conversation_ref
        try:
            with _temporary_cwd(workspace):
                with _codex_sdk_environment(config, workspace):
                    sdk_result, conversation_ref = self._run_thread(
                        sdk_module,
                        Codex,
                        request,
                        model=model,
                        sandbox=sandbox,
                        workspace=workspace,
                        config=config,
                    )
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            if output_dir:
                _write_codex_sdk_result(output_dir / "codex-sdk-result.json", status="fail", duration_ms=duration_ms)
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class=exc.__class__.__name__,
                recovery_suggestion="Check Codex SDK auth, model access, sandbox permissions, and workspace state.",
                trace_ref=_codex_sdk_trace_ref(workspace),
                usage={"tokens": None, "cost": None, "duration_ms": duration_ms},
                conversation_ref=conversation_ref,
            )
        duration_ms = int((time.monotonic() - started) * 1000)
        response_text = _codex_sdk_result_text(sdk_result)
        usage = _codex_sdk_usage(sdk_result, duration_ms)
        if request.node_purpose == "implement":
            assert output_dir is not None
            _write_codex_sdk_result(output_dir / "codex-sdk-result.json", status="pass", duration_ms=duration_ms)
            manifest_path = output_dir / "candidate_manifest.json"
            command_log_ref = "agent-workspace://agent-output/codex-sdk-result.json"
            manifest_ref = "agent-workspace://agent-output/candidate_manifest.json"
            if not manifest_path.is_file():
                return InvocationResult(
                    text="Codex SDK did not write agent-output/candidate_manifest.json",
                    status="fail",
                    failure_class="missing_runner_manifest",
                    recovery_suggestion="Codex SDK implementation nodes must write agent-output/candidate_manifest.json after generating files.",
                    evidence_refs=[command_log_ref],
                    trace_ref=command_log_ref,
                    usage=usage,
                    conversation_ref=conversation_ref,
                )
            return InvocationResult(
                text=json.dumps({"candidate_manifest_ref": "agent-output/candidate_manifest.json"}, sort_keys=True),
                evidence_refs=[command_log_ref, manifest_ref],
                trace_ref=command_log_ref,
                usage=usage,
                conversation_ref=conversation_ref,
            )
        return InvocationResult(
            text=response_text,
            evidence_refs=["codex-sdk://thread"],
            trace_ref="codex-sdk://thread",
            usage=usage,
            conversation_ref=conversation_ref,
        )

    def _run_thread(
        self,
        sdk_module: Any,
        Codex: Any,
        request: InvocationRequest,
        *,
        model: str,
        sandbox: Any,
        workspace: Path | None,
        config: dict[str, Any],
    ) -> tuple[Any, str]:
        if _codex_sdk_should_continue(request):
            return self._run_continued_thread(sdk_module, Codex, request, model=model, sandbox=sandbox, workspace=workspace, config=config)
        with Codex() as codex:
            thread = codex.thread_start(**_codex_sdk_thread_kwargs(sdk_module, model=model, sandbox=sandbox, workspace=workspace, config=config))
            result = thread.run(request.instruction, **_codex_sdk_run_kwargs(sdk_module, sandbox=sandbox, workspace=workspace))
            return result, _codex_sdk_thread_ref(thread, "")

    def _run_continued_thread(
        self,
        sdk_module: Any,
        Codex: Any,
        request: InvocationRequest,
        *,
        model: str,
        sandbox: Any,
        workspace: Path | None,
        config: dict[str, Any],
    ) -> tuple[Any, str]:
        workspace_ref = str(workspace.resolve()) if workspace else ""
        if request.conversation_ref:
            session = self._continued_threads.get(request.conversation_ref)
            if session:
                if session.get("workspace_ref") != workspace_ref:
                    raise CodexSdkContinuationUnavailable("Codex SDK continuation workspace does not match the current isolated workdir")
                return session["thread"].run(request.instruction, **_codex_sdk_run_kwargs(sdk_module, sandbox=sandbox, workspace=workspace)), request.conversation_ref
            with Codex() as codex:
                thread = _codex_sdk_resume_thread(codex, request.conversation_ref)
                if thread is None:
                    raise CodexSdkContinuationUnavailable("Codex SDK continuation thread is not available; disable continuation or rerun the initial IMPLEMENT attempt")
                return thread.run(request.instruction, **_codex_sdk_run_kwargs(sdk_module, sandbox=sandbox, workspace=workspace)), request.conversation_ref

        codex_cm = Codex()
        codex = codex_cm.__enter__()
        conversation_ref = ""
        try:
            thread = codex.thread_start(**_codex_sdk_thread_kwargs(sdk_module, model=model, sandbox=sandbox, workspace=workspace, config=config))
            conversation_ref = _codex_sdk_thread_ref(thread, f"codex-sdk-thread:{request.invocation_id or id(thread)}")
            self._continued_threads[conversation_ref] = {
                "codex_cm": codex_cm,
                "thread": thread,
                "workspace_ref": workspace_ref,
                "model": model,
            }
            return thread.run(request.instruction, **_codex_sdk_run_kwargs(sdk_module, sandbox=sandbox, workspace=workspace)), conversation_ref
        except Exception:
            if conversation_ref:
                self._continued_threads.pop(conversation_ref, None)
            with contextlib.suppress(Exception):
                codex_cm.__exit__(*sys.exc_info())
            raise


class OpenAICompatibleBackend:
    backend_kind = "llm"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        if not request.permissions.get("network") or not config.get("permissions", {}).get("network"):
            return InvocationResult(
                text="OpenAI-compatible backend network permission denied",
                status="fail",
                failure_class="network_permission_denied",
                recovery_suggestion="Set request and backend network permissions explicitly for live smoke calls",
            )
        auth = config.get("auth", {})
        api_key_env = auth.get("api_key_env") or ""
        api_key = os.environ.get(api_key_env) if api_key_env else ""
        model = config.get("smoke_model") or config.get("model") or ""
        if not api_key or not model:
            return InvocationResult(
                text="OpenAI-compatible backend is not configured",
                status="needs_human",
                failure_class="missing_openai_configuration",
                recovery_suggestion="Set OPENAI_API_KEY and configure model/api_key_env in the selected YAML invocation profile.",
            )
        base_url = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "Return concise source-grounded workflow node output."},
                {"role": "user", "content": request.instruction},
            ],
            "max_tokens": int(config.get("budgets", {}).get("max_tokens") or 256),
        }
        http_request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        attempts = int(config.get("retries", {}).get("max_attempts", 3))
        last_exc: Exception | None = None
        for attempt in range(max(1, attempts)):
            try:
                with urllib.request.urlopen(http_request, timeout=int(config.get("timeouts", {}).get("run_ms", 5000)) / 1000) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_exc = exc
                if not _is_transient_openai_error(exc) or attempt == attempts - 1:
                    payload = None
                    break
                time.sleep(0.25 * (attempt + 1))
        if payload is None:
            exc = last_exc or RuntimeError("OpenAI-compatible backend request failed")
            return InvocationResult(
                text=str(exc),
                status="fail",
                failure_class=exc.__class__.__name__,
                recovery_suggestion="Skip live smoke test or check API credentials/network/model access",
            )
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return InvocationResult(
            text=text,
            evidence_refs=["openai-compatible://chat-completions"],
            trace_ref="openai-compatible://response",
            usage={"tokens": payload.get("usage"), "cost": None, "duration_ms": None},
        )


class LLMFileCodegenBackend:
    backend_kind = "llm_file_codegen"

    def invoke(self, request: InvocationRequest, config: dict[str, Any]) -> InvocationResult:
        if request.node_purpose != "implement":
            return InvocationResult(
                text="llm_file_codegen only supports implementation nodes",
                status="fail",
                failure_class="invalid_codegen_request",
                recovery_suggestion="Use llm_file_codegen only for node_purpose=implement.",
            )
        root_text = str(request.permissions.get("filesystem_root") or "")
        if not root_text:
            return InvocationResult(
                text="llm_file_codegen requires an isolated filesystem_root",
                status="fail",
                failure_class="missing_codegen_workdir",
                recovery_suggestion="Set request.permissions.filesystem_root to the isolated workdir.",
            )
        work_dir = PurePath(root_text)
        if work_dir.is_absolute() is False:
            return InvocationResult(
                text="llm_file_codegen filesystem_root must be absolute",
                status="fail",
                failure_class="invalid_codegen_workdir",
                recovery_suggestion="Use an absolute isolated workdir path.",
            )
        if not request.permissions.get("network") or not config.get("permissions", {}).get("network"):
            return InvocationResult(
                text="LLM file codegen backend network permission denied",
                status="fail",
                failure_class="network_permission_denied",
                recovery_suggestion="Set network: true for live codegen in the selected YAML invocation profile.",
            )
        if not request.permissions.get("auth") or not config.get("permissions", {}).get("auth"):
            return InvocationResult(
                text="LLM file codegen backend auth permission denied",
                status="fail",
                failure_class="auth_permission_denied",
                recovery_suggestion="Configure an API key env var and allow auth for llm_file_codegen.",
            )
        payload, error = _openai_chat_completion(
            request,
            config,
            system_message=(
                "You are an environment code generation backend. Return only a JSON object with a files array. "
                "Each file item must contain path and content. Generate a contract-project environment under generated/ "
                "with contract.json, source/, state/, adapters/, scripts/, and spec/. "
                "Do not include API keys, credentials, or text outside JSON."
            ),
            response_format={"type": "json_object"},
        )
        if error:
            return error
        response_text = _message_content(payload)
        candidate, parse_error = _parse_codegen_response(response_text)
        if parse_error:
            return parse_error
        write_result, write_error = _write_codegen_candidate(candidate, root_text, request, config)
        if write_error:
            return write_error
        return InvocationResult(
            text=stable_json(write_result),
            evidence_refs=list(candidate.get("evidence_refs", [])) + ["openai-compatible-codegen://chat-completions"],
            trace_ref="openai-compatible-codegen://response",
            usage={"tokens": payload.get("usage"), "cost": None, "duration_ms": None},
        )


CODEGEN_FILE_KINDS = {
    "contract",
    "source",
    "state",
    "adapter",
    "script",
    "spec",
    "manifest",
    "check_report",
    "lockfile",
    "config",
    "test",
    "documentation",
    "other",
}


def _openai_chat_completion(
    request: InvocationRequest,
    config: dict[str, Any],
    *,
    system_message: str,
    response_format: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], InvocationResult | None]:
    auth = config.get("auth", {})
    api_key_env = auth.get("api_key_env") or ""
    api_key = os.environ.get(api_key_env) if api_key_env else ""
    model = config.get("smoke_model") or config.get("model") or ""
    if not api_key or not model:
        return {}, InvocationResult(
            text="OpenAI-compatible backend is not configured",
            status="needs_human",
            failure_class="missing_openai_configuration",
            recovery_suggestion="Set OPENAI_API_KEY and configure model/api_key_env in the selected YAML invocation profile.",
        )
    base_url = (config.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": request.instruction},
        ],
        "max_tokens": int(config.get("budgets", {}).get("max_tokens") or 4096),
    }
    if response_format:
        body["response_format"] = response_format
    http_request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    attempts = int(config.get("retries", {}).get("max_attempts", 3))
    last_exc: Exception | None = None
    started = time.monotonic()
    for attempt in range(max(1, attempts)):
        try:
            with urllib.request.urlopen(http_request, timeout=int(config.get("timeouts", {}).get("run_ms", 5000)) / 1000) as response:
                payload = json.loads(response.read().decode("utf-8"))
            payload.setdefault("_agent_world_duration_ms", int((time.monotonic() - started) * 1000))
            return payload, None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc
            if not _is_transient_openai_error(exc) or attempt == attempts - 1:
                break
            time.sleep(0.25 * (attempt + 1))
    exc = last_exc or RuntimeError("OpenAI-compatible backend request failed")
    return {}, InvocationResult(
        text=str(exc),
        status="fail",
        failure_class=exc.__class__.__name__,
        recovery_suggestion="Skip live smoke test or check API credentials/network/model access",
    )


def _message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content", "")
    return content if isinstance(content, str) else ""


def _parse_codegen_response(text: str) -> tuple[dict[str, Any], InvocationResult | None]:
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            return {}, _codegen_failure(
                "malformed_codegen_response",
                "Model response must be a JSON object with a files array.",
            )
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {}, _codegen_failure(
                "malformed_codegen_response",
                "Model response must contain valid JSON.",
            )
    if not isinstance(parsed, dict):
        return {}, _codegen_failure("malformed_codegen_response", "Model response JSON must be an object.")
    files = parsed.get("files")
    if not isinstance(files, list):
        return {}, _codegen_failure("missing_codegen_files", "Model response must include files[].")
    return parsed, None


def _write_codegen_candidate(
    candidate: dict[str, Any],
    root_text: str,
    request: InvocationRequest,
    config: dict[str, Any],
) -> tuple[dict[str, Any], InvocationResult | None]:
    root = Path(root_text).resolve()
    root.mkdir(parents=True, exist_ok=True)
    declared: set[str] = set()
    files = candidate.get("files", [])
    secrets = _secret_values(config)
    for item in files:
        if not isinstance(item, dict):
            return {}, _codegen_failure("malformed_codegen_file", "Each codegen file item must be an object.")
        rel_text = str(item.get("path") or "")
        path_error = _codegen_path_error(rel_text)
        if path_error:
            return {}, path_error
        if not (rel_text.startswith("generated/") or rel_text.startswith("agent-output/")):
            return {}, _codegen_failure("unexpected_codegen_file", "LLM file codegen files must be under generated/ or agent-output/.")
        if rel_text in declared:
            return {}, _codegen_failure("duplicate_codegen_file", "Model declared the same file twice.")
        content = item.get("content")
        if not isinstance(content, str):
            return {}, _codegen_failure("malformed_codegen_file", "Each codegen file item must include string content.")
        if any(secret and secret in content for secret in secrets):
            return {}, _codegen_failure("secret_leak_in_codegen_file", "Generated files must not contain configured secret values.")
        target = (root / rel_text).resolve()
        if not _path_inside(target, root):
            return {}, _codegen_failure("path_traversal_rejected", "Generated file path escapes the isolated workdir.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        declared.add(rel_text)
    generated_root = root / "generated"
    for dirname in ["source", "state", "adapters", "scripts", "spec"]:
        (generated_root / dirname).mkdir(parents=True, exist_ok=True)
    if not (generated_root / "contract.json").is_file():
        return {}, _codegen_failure("missing_codegen_files", "Model response did not include generated/contract.json.")
    generated_files = [
        {
            "path": path.relative_to(generated_root).as_posix(),
            "kind": _codegen_kind(path.relative_to(generated_root).as_posix()),
            "sha256": _file_sha256(path),
            "source_refs": _file_source_refs(candidate, f"generated/{path.relative_to(generated_root).as_posix()}", request),
        }
        for path in sorted(generated_root.rglob("*"))
        if path.is_file() and not _is_python_cache_file(path)
    ]
    return {
        "candidate_dir": "generated",
        "implementation_id": str(candidate.get("implementation_id") or "project-openai-codegen-candidate"),
        "environment_id": str(candidate.get("environment_id") or "generated-environment"),
        "contract_ref": "contract.json",
        "generated_files": generated_files,
        "self_check": dict(candidate.get("self_check") or {"command": ["python", "scripts/self_check.py"]}),
        "replay_commands": list(candidate.get("replay_commands") or []),
    }, None


def _file_source_refs(candidate: dict[str, Any], filename: str, request: InvocationRequest) -> list[str]:
    for item in candidate.get("files", []):
        if isinstance(item, dict) and item.get("path") == filename and isinstance(item.get("source_refs"), list) and item["source_refs"]:
            return [str(ref) for ref in item["source_refs"]]
    return request.input_artifact_ids or ["openai-codegen-response"]


def _codegen_kind(relative_path: str) -> str:
    if relative_path == "contract.json":
        return "contract"
    first = relative_path.split("/", 1)[0]
    return {
        "source": "source",
        "state": "state",
        "adapters": "adapter",
        "scripts": "script",
        "spec": "spec",
    }.get(first, "other")


def _is_python_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _codegen_path_error(path_text: str) -> InvocationResult | None:
    if not path_text:
        return _codegen_failure("invalid_codegen_path", "Generated file paths must be non-empty relative paths.")
    if "\\" in path_text:
        return _codegen_failure("invalid_codegen_path", "Generated file paths must use POSIX-style relative paths.")
    path = PurePath(path_text)
    if path.is_absolute() or path_text.startswith("~"):
        return _codegen_failure("absolute_path_rejected", "Generated file paths must not be absolute or home-relative.")
    if any(part in {"", ".", ".."} for part in path.parts):
        return _codegen_failure("path_traversal_rejected", "Generated file paths must not contain current or parent directory segments.")
    return None


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _codegen_failure(failure_class: str, recovery_suggestion: str) -> InvocationResult:
    return InvocationResult(
        text=recovery_suggestion,
        status="fail",
        failure_class=failure_class,
        recovery_suggestion=recovery_suggestion,
    )


class InvocationBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, InvocationBackend] = {}

    def register(self, backend: InvocationBackend) -> None:
        self._backends[backend.backend_kind] = backend

    def get(self, backend_kind: str) -> InvocationBackend:
        if backend_kind not in self._backends:
            raise KeyError(f"Invocation backend is not registered: {backend_kind}")
        return self._backends[backend_kind]


def default_invocation_backend_registry() -> InvocationBackendRegistry:
    registry = InvocationBackendRegistry()
    registry.register(MockInvocationBackend())
    registry.register(ManualInvocationBackend())
    registry.register(ProcessInvocationBackend())
    registry.register(CodexCliInvocationBackend())
    registry.register(CodeAgentRunnerInvocationBackend())
    registry.register(CodexCliRunnerInvocationBackend())
    registry.register(CodexSdkInvocationBackend())
    registry.register(OpenAICompatibleBackend())
    registry.register(LLMFileCodegenBackend())
    return registry


def load_invocation_backend_config_from_env(
    env: dict[str, str] | None = None,
    *,
    source_stage: str = "config",
    profile_id: str = SEMANTIC_INVOCATION_PROFILE,
) -> dict[str, Any]:
    world_config = load_agent_world_config(env)
    profile = world_config.invocation_profiles[profile_id]
    return invocation_backend_config_from_profile(profile, source_stage=source_stage)


def load_stage_invocation_backend_config_from_env(stage: str, env: dict[str, str] | None = None, *, source_stage: str = "config") -> dict[str, Any]:
    world_config = load_agent_world_config(env)
    return invocation_backend_config_from_profile(world_config.profile_for_stage(stage), source_stage=source_stage)


def load_implementation_invocation_backend_config_from_env(env: dict[str, str] | None = None, *, source_stage: str = "config") -> dict[str, Any]:
    return load_invocation_backend_config_from_env(env, source_stage=source_stage, profile_id=IMPLEMENTATION_INVOCATION_PROFILE)


def invocation_backend_config_from_profile(profile: InvocationProfileConfig, *, source_stage: str = "config") -> dict[str, Any]:
    backend_kind = profile.backend_kind
    command_argv = shlex.split(profile.command_value) if profile.command_value else []
    allowlist = shlex.split(profile.allowlist_value) if profile.allowlist_value else []
    if backend_kind in {"code_agent_runner", "codex_cli_runner", "codex_sdk"}:
        command_filesystem = "isolated_agent_workspace"
    elif backend_kind in {"process_agent", "codex_cli"}:
        command_filesystem = "controlled_process_cwd"
    else:
        command_filesystem = "artifact_context"
    command_sandbox = backend_kind in {"codex_cli", "codex_cli_runner", "codex_sdk"}
    auth_permission = (bool(profile.api_key_env) or profile.backend_auth) and backend_kind in {"llm", "llm_file_codegen", "code_agent_runner", "codex_cli_runner", "codex_sdk"}
    command = (
        {
            "argv": command_argv,
            "fixed_args": [],
            "forbidden_args": ["--dangerously-bypass-approvals-and-sandbox", "--force", "--unsafe"],
            "allowlist_executables": allowlist,
            "cwd": profile.command_cwd,
        }
        if profile.command_value
        else {"argv": [], "fixed_args": [], "forbidden_args": [], "allowlist_executables": [], "cwd": "."}
    )
    profile_ref = _safe_profile_ref(profile.profile_id)
    fields = {
        "backend_id": f"{profile_ref}-invocation-backend",
        "profile_id": profile.profile_id,
        "backend_kind": backend_kind,
        "provider": profile.provider,
        "model": profile.model,
        "smoke_model": profile.smoke_model,
        "model_candidates": profile.model_candidates,
        "base_url": profile.base_url,
        "api_version": profile.api_version,
        "auth": {
            "api_key_env": profile.api_key_env,
            "auth_env_refs": profile.auth_env_refs,
            "requires_auth": backend_kind in {"llm", "llm_file_codegen", "code_agent_runner", "codex_cli_runner", "codex_sdk"},
        },
        "command": command,
        "timeouts": {"connect_ms": 1000, "run_ms": int(profile.timeout_ms)},
        "retries": {"max_attempts": int(profile.max_attempts)},
        "budgets": {"max_tokens": int(profile.max_tokens), "max_cost": 0, "max_tool_calls": 0},
        "permissions": {
            "network": bool(profile.network),
            "filesystem": command_filesystem,
            "auth": auth_permission,
            "sandbox": command_sandbox,
        },
        "codex": {"sandbox": profile.codex_sandbox},
        "code_repair": {"thread_mode": profile.code_repair_thread_mode},
        "output_schema_ref": "InvocationResult",
        "redaction_policy": {"secret_env_names_only": True, "redact_values": True},
    }
    return make_artifact(
        "InvocationBackendConfig",
        source_stage=source_stage,
        producer="invocation-backend-config-loader",
        fields=fields,
        artifact_id=f"invocation-backend-config-{profile_ref}",
        status="accepted",
    )


def invoke_backend(
    registry: InvocationBackendRegistry,
    request: InvocationRequest,
    config: dict[str, Any],
    *,
    producer: str = "invocation-runtime",
) -> tuple[dict[str, Any], InvocationResult]:
    backend = registry.get(config["backend_kind"])
    result = backend.invoke(request, config)
    fields = {
        "invocation_id": request.invocation_id or f"invoke-{request.stage.lower()}-{request.node_purpose.replace('_', '-')}",
        "stage": request.stage,
        "node_purpose": request.node_purpose,
        "backend_kind": config["backend_kind"],
        "backend_ref": config["backend_id"],
        "config_ref": config["id"],
        "model_or_runtime": config.get("smoke_model") or config.get("model") or _runtime_name(config),
        "instruction_ref": request.instruction_ref,
        "instruction_text": request.instruction,
        "input_artifact_ids": request.input_artifact_ids,
        "allowed_tool_access": request.allowed_tool_access,
        "permissions": request.permissions,
        "budget": request.budget,
        "parent_invocation_id": request.parent_invocation_id,
        "conversation_ref": result.conversation_ref or request.conversation_ref,
        "continuation_mode": request.continuation_mode,
        "output_artifact_ids": result.output_artifact_ids,
        "evidence_refs": result.evidence_refs,
        "trace_ref": result.trace_ref,
        "result_preview": result.text[:500],
        "usage": _json_safe(result.usage or {"tokens": None, "cost": None, "duration_ms": None}),
        "failure_class": result.failure_class,
        "recovery_suggestion": result.recovery_suggestion,
    }
    fields = _redact_record_fields(fields, config)
    record = make_artifact(
        "InvocationRecord",
        source_stage=request.stage,
        producer=producer,
        fields=fields,
        artifact_id=fields["invocation_id"],
        inputs=request.input_artifact_ids + [config["id"]],
        status=result.status,
    )
    return record, result


def _code_repair_thread_mode(raw: str) -> str:
    mode = str(raw or "stateless").strip().lower()
    return mode if mode in {"stateless", "continue"} else "stateless"


def _safe_profile_ref(profile_id: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in profile_id.strip().lower())
    return cleaned or "default"


def _codex_sdk_permission_error(request: InvocationRequest, config: dict[str, Any]) -> InvocationResult | None:
    permissions = config.get("permissions", {})
    if request.permissions.get("network") and not permissions.get("network"):
        return InvocationResult(
            text="Codex SDK network permission denied",
            status="fail",
            failure_class="network_permission_denied",
            recovery_suggestion="Set network: true only for trusted live Codex SDK runs in the selected YAML invocation profile.",
        )
    if request.permissions.get("auth") and not permissions.get("auth"):
        return InvocationResult(
            text="Codex SDK auth permission denied",
            status="fail",
            failure_class="auth_permission_denied",
            recovery_suggestion="Configure api_key_env/auth_env_refs in YAML for trusted Codex SDK runs.",
        )
    if request.permissions.get("sandbox") and not permissions.get("sandbox"):
        return InvocationResult(
            text="Codex SDK sandbox permission denied",
            status="fail",
            failure_class="sandbox_permission_denied",
            recovery_suggestion="Use codex_sdk only with an explicit sandbox policy.",
        )
    return None


def _codex_sdk_should_continue(request: InvocationRequest) -> bool:
    return request.stage == "IMPLEMENT" and request.node_purpose == "implement" and request.continuation_mode == "continue"


def _codex_sdk_thread_ref(thread: Any, fallback: str) -> str:
    for attr in ["id", "thread_id", "threadId"]:
        value = getattr(thread, attr, "")
        if value:
            return str(value)
    return fallback


def _codex_sdk_resume_thread(codex: Any, conversation_ref: str) -> Any | None:
    for method_name in ["thread_resume", "resume_thread", "resumeThread"]:
        method = getattr(codex, method_name, None)
        if callable(method):
            return method(conversation_ref)
    return None


def _codex_sdk_sandbox(Sandbox: Any, config: dict[str, Any]) -> tuple[Any, InvocationResult | None]:
    raw = str((config.get("codex") or {}).get("sandbox") or "workspace-write")
    normalized = raw.strip().lower().replace("_", "-")
    if normalized in {"workspace-write", "workspace"}:
        attr = "workspace_write"
    elif normalized in {"read-only", "readonly", "read"}:
        attr = "read_only"
    elif normalized == "full-access":
        return None, InvocationResult(
            text="Codex SDK full-access sandbox is not allowed by this framework",
            status="fail",
            failure_class="invalid_codex_sdk_sandbox",
            recovery_suggestion="Use codex_sandbox: workspace-write or read-only in YAML.",
        )
    else:
        return None, InvocationResult(
            text=f"Unsupported Codex SDK sandbox: {raw}",
            status="fail",
            failure_class="invalid_codex_sdk_sandbox",
            recovery_suggestion="Use codex_sandbox: workspace-write or read-only in YAML.",
        )
    if not hasattr(Sandbox, attr):
        return None, InvocationResult(
            text=f"Codex SDK Sandbox does not expose {attr}",
            status="fail",
            failure_class="invalid_codex_sdk",
            recovery_suggestion="Use an official openai-codex build with Sandbox presets.",
        )
    return getattr(Sandbox, attr), None


def _codex_sdk_thread_kwargs(
    sdk_module: Any,
    *,
    model: str,
    sandbox: Any,
    workspace: Path | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model, "sandbox": sandbox}
    if workspace:
        kwargs["cwd"] = str(workspace)
    if config.get("base_url"):
        kwargs["model_provider"] = CODEX_SDK_MODEL_PROVIDER_ID
    approval_mode = _codex_sdk_auto_review_approval_mode(sdk_module)
    if approval_mode is not None:
        kwargs["approval_mode"] = approval_mode
    return kwargs


def _codex_sdk_run_kwargs(sdk_module: Any, *, sandbox: Any, workspace: Path | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"sandbox": sandbox}
    if workspace:
        kwargs["cwd"] = str(workspace)
    approval_mode = _codex_sdk_auto_review_approval_mode(sdk_module)
    if approval_mode is not None:
        kwargs["approval_mode"] = approval_mode
    return kwargs


def _codex_sdk_auto_review_approval_mode(sdk_module: Any) -> Any | None:
    approval_mode = getattr(sdk_module, "ApprovalMode", None)
    return getattr(approval_mode, "auto_review", None) if approval_mode is not None else None


def _codex_sdk_workspace(request: InvocationRequest) -> tuple[Path | None, InvocationResult | None]:
    if request.node_purpose != "implement":
        root = str(request.permissions.get("filesystem_root") or "")
        if not root:
            return None, None
    else:
        root = str(request.permissions.get("filesystem_root") or "")
        if not root:
            return None, InvocationResult(
                text="Codex SDK implementation requires filesystem_root",
                status="fail",
                failure_class="missing_runner_workspace",
                recovery_suggestion="Set request.permissions.filesystem_root to the isolated Codex SDK workspace.",
            )
    workspace = Path(root).resolve()
    if not workspace.is_dir():
        return None, InvocationResult(
            text="Codex SDK workspace does not exist",
            status="fail",
            failure_class="missing_runner_workspace",
            recovery_suggestion="Create the isolated Codex SDK workspace before invoking the backend.",
        )
    return workspace, None


@contextlib.contextmanager
def _temporary_cwd(path: Path | None) -> Any:
    if path is None:
        yield
        return
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextlib.contextmanager
def _codex_sdk_environment(config: dict[str, Any], workspace: Path | None) -> Any:
    if workspace is not None:
        codex_home = workspace / "agent-output" / "codex-home"
        codex_home.mkdir(parents=True, exist_ok=True)
        with _codex_sdk_home_environment(config, codex_home):
            yield
        return
    with tempfile.TemporaryDirectory(prefix="agent-world-codex-home-") as temp_dir:
        with _codex_sdk_home_environment(config, Path(temp_dir)):
            yield


@contextlib.contextmanager
def _codex_sdk_home_environment(config: dict[str, Any], codex_home: Path) -> Any:
    config_text = _codex_sdk_config_text(config)
    if config_text:
        (codex_home / "config.toml").write_text(config_text, encoding="utf-8")
    updates = {
        "CODEX_HOME": str(codex_home),
        "HOME": str(codex_home),
    }
    auth = config.get("auth", {})
    for name in set(auth.get("auth_env_refs", [])) | ({auth.get("api_key_env")} if auth.get("api_key_env") else set()):
        value = os.environ.get(str(name))
        if value:
            updates[str(name)] = value
    previous = {name: os.environ.get(name) for name in updates}
    try:
        os.environ.update(updates)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _codex_sdk_config_text(config: dict[str, Any]) -> str:
    lines = []
    model = str(config.get("smoke_model") or config.get("model") or "")
    base_url = str(config.get("base_url") or "")
    auth = config.get("auth", {})
    api_key_env = str(auth.get("api_key_env") or "")
    if model:
        lines.append(f"model = {_toml_string(model)}")
    if base_url:
        provider_id = CODEX_SDK_MODEL_PROVIDER_ID
        lines.append(f"model_provider = {_toml_string(provider_id)}")
        lines.append("")
        lines.append(f"[model_providers.{provider_id}]")
        lines.append('name = "Agent World OpenAI-compatible provider"')
        lines.append(f"base_url = {_toml_string(base_url)}")
        lines.append('wire_api = "responses"')
        if api_key_env:
            lines.append(f"env_key = {_toml_string(api_key_env)}")
    return "\n".join(lines) + ("\n" if lines else "")


def _codex_sdk_result_text(result: Any) -> str:
    final_response = getattr(result, "final_response", None)
    if isinstance(final_response, str):
        return final_response
    if final_response is not None:
        return str(final_response)
    if isinstance(result, str):
        return result
    return str(result)


def _codex_sdk_usage(result: Any, duration_ms: int) -> dict[str, Any]:
    usage = getattr(result, "usage", None)
    return {"tokens": _json_safe(usage), "cost": None, "duration_ms": duration_ms}


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _json_safe(model_dump(mode="json"))
        except TypeError:
            return _json_safe(model_dump())
    if hasattr(value, "__dict__"):
        return _json_safe(vars(value))
    return str(value)


def _write_codex_sdk_result(path: Path, *, status: str, duration_ms: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json({"status": status, "duration_ms": duration_ms}), encoding="utf-8")


def _codex_sdk_trace_ref(workspace: Path | None) -> str:
    if workspace:
        return "agent-workspace://agent-output/codex-sdk-result.json"
    return "codex-sdk://thread"


def _is_transient_openai_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, urllib.error.URLError)


def _infer_api_version(base_url: str, backend_kind: str) -> str:
    if backend_kind in {"llm", "llm_file_codegen"} and base_url.rstrip("/").endswith("/v1"):
        return "v1"
    return ""


def _command_argv(config: dict[str, Any]) -> list[str]:
    command = config.get("command") or {}
    argv = list(command.get("argv") or [])
    fixed_args = list(command.get("fixed_args") or [])
    full = argv + fixed_args
    forbidden = set(command.get("forbidden_args") or [])
    if any(arg in forbidden for arg in full):
        raise ValueError("Process agent command contains forbidden arguments")
    for arg in full:
        if any(arg.startswith(prefix) for prefix in ["--dangerously-", "--unsafe", "--force", "--no-sandbox"]):
            raise ValueError("Process agent command contains unsafe argument prefix")
    if any(_has_shell_control(arg) for arg in full):
        raise ValueError("Process agent command arguments may not contain shell control operators")
    allowlist = set(command.get("allowlist_executables") or [])
    if full and not allowlist:
        raise ValueError("Process agent executable allowlist is required")
    if full and allowlist and full[0] not in allowlist:
        raise ValueError("Process agent executable is not allowlisted")
    return full


def _validate_codex_cli_command(config: dict[str, Any]) -> None:
    argv = _command_argv(config)
    if not argv:
        raise ValueError("Codex CLI command is empty")
    executable = PurePath(argv[0]).name
    if "codex" not in executable:
        raise ValueError("codex_cli backend executable must look like codex")
    joined = " ".join(argv)
    denied_fragments = [
        "--dangerously-bypass-approvals-and-sandbox",
        "--approval-mode=never",
        "--approval-mode never",
        "--sandbox=off",
        "--sandbox off",
        "--sandbox-mode=off",
        "--sandbox-mode off",
        "--no-sandbox",
        "--force",
    ]
    if any(fragment in joined for fragment in denied_fragments):
        raise ValueError("Codex CLI command contains denied approval/sandbox option")
    _reject_codex_config_overrides(argv)
    approval = _option_value(argv, "--approval-mode") or _option_value(argv, "--ask-for-approval")
    sandbox = _option_value(argv, "--sandbox") or _option_value(argv, "--sandbox-mode")
    allowed_approval = {"on-request", "on-failure", "untrusted"}
    allowed_sandbox = {"workspace-write", "read-only"}
    if approval not in allowed_approval:
        raise ValueError("Codex CLI command must explicitly set a safe approval mode")
    if sandbox not in allowed_sandbox:
        raise ValueError("Codex CLI command must explicitly set a safe sandbox mode")


def _option_value(argv: list[str], name: str) -> str | None:
    for index, arg in enumerate(argv):
        if arg == name and index + 1 < len(argv):
            return argv[index + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def _reject_codex_config_overrides(argv: list[str]) -> None:
    for index, arg in enumerate(argv):
        if arg == "-c":
            value = argv[index + 1] if index + 1 < len(argv) else ""
            if "approval" in value.lower() or "sandbox" in value.lower():
                raise ValueError("Codex CLI -c approval/sandbox overrides are not allowed")
        if arg.startswith("-c") and ("approval" in arg.lower() or "sandbox" in arg.lower()):
            raise ValueError("Codex CLI -c approval/sandbox overrides are not allowed")


def _runtime_name(config: dict[str, Any]) -> str:
    argv = list((config.get("command") or {}).get("argv") or [])
    return argv[0] if argv else config.get("backend_kind", "unknown")


def _has_shell_control(arg: str) -> bool:
    return any(token in arg for token in [";", "|", "&&", "||", "$(", "`", ">", "<"])


def _safe_cwd(config: dict[str, Any]) -> str | None:
    cwd = (config.get("command") or {}).get("cwd")
    if not cwd:
        return None
    if cwd != ".":
        raise ValueError("Process agent cwd must be the current workspace directory for the first slice")
    if ".." in str(cwd).split("/"):
        raise ValueError("Process agent cwd may not traverse upward")
    return cwd


def _scrubbed_env(config: dict[str, Any], request: InvocationRequest) -> dict[str, str]:
    allowed_names = {"PATH", "TMPDIR", "TEMP", "TMP"}
    child_env = {name: value for name, value in os.environ.items() if name in allowed_names}
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["AGENT_WORLD_BACKEND_KIND"] = config.get("backend_kind", "")
    child_env["AGENT_WORLD_INVOCATION_STAGE"] = request.stage
    return child_env


def _runner_env(config: dict[str, Any], request: InvocationRequest, workspace: Path) -> dict[str, str]:
    child_env = _scrubbed_env(config, request)
    child_env["AGENT_WORLD_CODE_AGENT_WORKSPACE"] = str(workspace)
    child_env["AGENT_WORLD_CODE_AGENT_GENERATED_DIR"] = str(workspace / "generated")
    child_env["AGENT_WORLD_CODE_AGENT_OUTPUT_DIR"] = str(workspace / "agent-output")
    if request.permissions.get("auth") and config.get("permissions", {}).get("auth"):
        auth = config.get("auth", {})
        for name in set(auth.get("auth_env_refs", [])) | ({auth.get("api_key_env")} if auth.get("api_key_env") else set()):
            value = os.environ.get(name)
            if value:
                child_env[name] = value
    _configure_codex_runner_env(config, child_env, workspace)
    return child_env


def _configure_codex_runner_env(config: dict[str, Any], child_env: dict[str, str], workspace: Path) -> None:
    if config.get("backend_kind") != "codex_cli_runner":
        return
    codex_home = workspace / "agent-output" / "codex-home"
    codex_home.mkdir(parents=True, exist_ok=True)
    child_env["CODEX_HOME"] = str(codex_home)
    child_env["HOME"] = str(codex_home)
    auth = config.get("auth", {})
    api_key_env = str(auth.get("api_key_env") or "")
    api_key = child_env.get(api_key_env) or (os.environ.get(api_key_env) if api_key_env else "")
    if api_key:
        child_env["CODEX_API_KEY"] = api_key
    config_lines = []
    base_url = str(config.get("base_url") or "")
    model = str(config.get("smoke_model") or config.get("model") or "")
    if base_url:
        config_lines.append(f"openai_base_url = {_toml_string(base_url)}")
    if model:
        config_lines.append(f"model = {_toml_string(model)}")
    if config_lines:
        (codex_home / "config.toml").write_text("\n".join(config_lines) + "\n", encoding="utf-8")


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _append_command_log(
    path: Path,
    *,
    command: list[str],
    exit_code: int | None,
    stdout: str,
    stderr: str,
    duration_ms: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "command": command,
        "exit_code": exit_code,
        "stdout_preview": stdout[:4000],
        "stderr_preview": stderr[:4000],
        "duration_ms": duration_ms,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(stable_json(record))
        handle.write("\n")


def _redact_record_fields(value: Any, config: dict[str, Any]) -> Any:
    secrets = _secret_values(config)
    if not secrets:
        return value
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        return redacted
    if isinstance(value, list):
        return [_redact_record_fields(item, config) for item in value]
    if isinstance(value, dict):
        return {key: _redact_record_fields(item, config) for key, item in value.items()}
    return value


def _secret_values(config: dict[str, Any]) -> list[str]:
    auth = config.get("auth", {})
    names = set(auth.get("auth_env_refs", []))
    if auth.get("api_key_env"):
        names.add(auth["api_key_env"])
    values = []
    for name in names:
        value = os.environ.get(name)
        if value and len(value) >= 4:
            values.append(value)
    return values

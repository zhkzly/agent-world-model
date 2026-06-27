from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any, Protocol

from agent_world.artifacts import make_artifact, stable_json


@dataclass(frozen=True)
class AgentRequest:
    stage: str
    node_purpose: str
    instruction: str
    input_artifact_ids: list[str]
    invocation_id: str = ""
    allowed_tool_access: list[str] = field(default_factory=list)
    permissions: dict[str, Any] = field(default_factory=lambda: {"network": False, "filesystem": "artifact_context", "auth": False, "sandbox": False})
    budget: dict[str, Any] = field(default_factory=lambda: {"tokens": 0, "time_ms": 5000, "cost_limit": 0})
    instruction_ref: str = "inline"


@dataclass(frozen=True)
class AgentResult:
    text: str
    evidence_refs: list[str] = field(default_factory=list)
    output_artifact_ids: list[str] = field(default_factory=list)
    trace_ref: str = ""
    status: str = "pass"
    failure_class: str = ""
    recovery_suggestion: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


class AgentBackend(Protocol):
    backend_kind: str

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        ...


class MockAgentBackend:
    backend_kind = "mock"

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.responses = responses or {}

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        key = f"{request.stage}:{request.node_purpose}"
        if request.node_purpose == "review":
            artifact_id = request.input_artifact_ids[0] if request.input_artifact_ids else ""
            text = json.dumps(
                {
                    "alignment_status": "pass",
                    "reviewed_artifact_ids": [artifact_id],
                    "drift_findings": [],
                    "required_fixes": [],
                    "waived_risks": [],
                    "reviewer_note": f"mock independent review for {request.stage}",
                },
                sort_keys=True,
            )
            return AgentResult(text=text, evidence_refs=[f"mock://{key}"], trace_ref=f"mock-trace:{key}")
        text = self.responses.get(key, f"mock output for {key}")
        return AgentResult(text=text, evidence_refs=[f"mock://{key}"], trace_ref=f"mock-trace:{key}")


class ManualAgentBackend:
    backend_kind = "manual"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        responses = config.get("manual_responses", {})
        key = f"{request.stage}:{request.node_purpose}"
        if key not in responses:
            return AgentResult(
                text="manual input required",
                status="needs_human",
                failure_class="manual_input_required",
                recovery_suggestion=f"Provide manual response for {key}",
            )
        return AgentResult(text=responses[key], evidence_refs=[f"manual://{key}"], trace_ref=f"manual-trace:{key}")


class ProcessAgentBackend:
    backend_kind = "process_agent"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        try:
            command = _command_argv(config)
            cwd = _safe_cwd(config)
        except ValueError as exc:
            return AgentResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_process_agent_config",
                recovery_suggestion="Use an allowlisted command without shell control operators or unsafe args",
            )
        if not command:
            return AgentResult(
                text="process agent command is not configured",
                status="fail",
                failure_class="missing_process_command",
                recovery_suggestion="Set AGENT_WORLD_CODEX_CMD or configure AgentBackendConfig.command.argv",
            )
        timeout_ms = int(config.get("timeouts", {}).get("run_ms") or request.budget.get("time_ms") or 5000)
        if request.permissions.get("network") and not config.get("permissions", {}).get("network"):
            return AgentResult(
                text="process agent network permission denied",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Use a backend config that explicitly allows network access",
            )
        if request.permissions.get("auth"):
            return AgentResult(
                text="process agent auth passthrough is disabled for the first slice",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Use an API-specific backend instead of passing secrets to a local process",
            )
        if self.backend_kind == "process_agent":
            if request.permissions.get("sandbox") or config.get("permissions", {}).get("sandbox"):
                return AgentResult(
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
            return AgentResult(
                text="process agent timed out",
                status="fail",
                failure_class="process_timeout",
                recovery_suggestion="Increase timeout or use a cheaper deterministic backend",
            )
        if completed.returncode != 0:
            return AgentResult(
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
            return AgentResult(
                text="process agent output is not an object",
                status="fail",
                failure_class="invalid_process_output",
                recovery_suggestion="Return a JSON object matching AgentResult",
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return AgentResult(
            text=str(decoded.get("text", stdout)),
            evidence_refs=list(decoded.get("evidence_refs", ["process://stdout"])),
            output_artifact_ids=list(decoded.get("output_artifact_ids", [])),
            trace_ref=str(decoded.get("trace_ref", f"process://stdout?elapsed_ms={elapsed_ms}&exit_code=0")),
            status=str(decoded.get("status", "pass")),
            failure_class=str(decoded.get("failure_class", "")),
            recovery_suggestion=str(decoded.get("recovery_suggestion", "")),
            usage={"tokens": None, "cost": None, "duration_ms": elapsed_ms, "exit_code": 0},
        )


class CodexCliAgentBackend(ProcessAgentBackend):
    backend_kind = "codex_cli"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        try:
            _validate_codex_cli_command(config)
        except ValueError as exc:
            return AgentResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_codex_cli_config",
                recovery_suggestion="Use Codex CLI with approval and sandbox flags fixed to non-bypass values",
            )
        return super().invoke(request, config)


class OpenAICompatibleBackend:
    backend_kind = "llm"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        if not request.permissions.get("network") or not config.get("permissions", {}).get("network"):
            return AgentResult(
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
            return AgentResult(
                text="OpenAI-compatible backend is not configured",
                status="needs_human",
                failure_class="missing_openai_configuration",
                recovery_suggestion="Set AGENT_WORLD_OPENAI_API_KEY and AGENT_WORLD_OPENAI_MODEL, or use AGENT_WORLD_AGENT_BACKEND=mock",
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
            return AgentResult(
                text=str(exc),
                status="fail",
                failure_class=exc.__class__.__name__,
                recovery_suggestion="Skip live smoke test or check API credentials/network/model access",
            )
        text = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        return AgentResult(
            text=text,
            evidence_refs=["openai-compatible://chat-completions"],
            trace_ref="openai-compatible://response",
            usage={"tokens": payload.get("usage"), "cost": None, "duration_ms": None},
        )


class AgentBackendRegistry:
    def __init__(self) -> None:
        self._backends: dict[str, AgentBackend] = {}

    def register(self, backend: AgentBackend) -> None:
        self._backends[backend.backend_kind] = backend

    def get(self, backend_kind: str) -> AgentBackend:
        if backend_kind not in self._backends:
            raise KeyError(f"Agent backend is not registered: {backend_kind}")
        return self._backends[backend_kind]


def default_agent_backend_registry() -> AgentBackendRegistry:
    registry = AgentBackendRegistry()
    registry.register(MockAgentBackend())
    registry.register(ManualAgentBackend())
    registry.register(ProcessAgentBackend())
    registry.register(CodexCliAgentBackend())
    registry.register(OpenAICompatibleBackend())
    return registry


def load_agent_backend_config_from_env(env: dict[str, str] | None = None, *, source_stage: str = "config") -> dict[str, Any]:
    env = os.environ if env is None else env
    backend_kind = env.get("AGENT_WORLD_AGENT_BACKEND", "mock")
    provider = _provider_for_backend(backend_kind)
    base_url = env.get("AGENT_WORLD_OPENAI_BASE_URL") or env.get("OPENAI_BASE_URL") or ""
    api_key_env = "AGENT_WORLD_OPENAI_API_KEY" if env.get("AGENT_WORLD_OPENAI_API_KEY") else ("OPENAI_API_KEY" if env.get("OPENAI_API_KEY") else "")
    model = env.get("AGENT_WORLD_OPENAI_MODEL") or env.get("OPENAI_MODEL") or ""
    smoke_model = env.get("AGENT_WORLD_SMOKE_OPENAI_MODEL") or model
    api_version = env.get("AGENT_WORLD_OPENAI_API_VERSION") or _infer_api_version(base_url, backend_kind)
    command_value = env.get("AGENT_WORLD_CODEX_CMD") or ""
    command_argv = shlex.split(command_value) if command_value else []
    allowlist_value = env.get("AGENT_WORLD_PROCESS_AGENT_ALLOWLIST") or env.get("AGENT_WORLD_CODEX_ALLOWLIST") or ""
    allowlist = shlex.split(allowlist_value) if allowlist_value else []
    command_filesystem = "controlled_process_cwd" if backend_kind in {"process_agent", "codex_cli"} else "artifact_context"
    command_sandbox = backend_kind == "codex_cli"
    auth_permission = bool(api_key_env) and backend_kind == "llm"
    command = (
        {
            "argv": command_argv,
            "fixed_args": [],
            "forbidden_args": ["--dangerously-bypass-approvals-and-sandbox", "--force", "--unsafe"],
            "allowlist_executables": allowlist,
            "cwd": env.get("AGENT_WORLD_PROCESS_AGENT_CWD", "."),
        }
        if command_value
        else {"argv": [], "fixed_args": [], "forbidden_args": [], "allowlist_executables": [], "cwd": "."}
    )
    fields = {
        "backend_id": "default-agent-backend",
        "backend_kind": backend_kind,
        "provider": provider,
        "model": model,
        "smoke_model": smoke_model,
        "base_url": base_url,
        "api_version": api_version,
        "auth": {
            "api_key_env": api_key_env,
            "auth_env_refs": [name for name in ["AGENT_WORLD_OPENAI_API_KEY", "OPENAI_API_KEY"] if env.get(name)],
            "requires_auth": backend_kind in {"llm", "codex_sdk"},
        },
        "command": command,
        "timeouts": {"connect_ms": 1000, "run_ms": int(env.get("AGENT_WORLD_AGENT_TIMEOUT_MS", "5000"))},
        "retries": {"max_attempts": int(env.get("AGENT_WORLD_AGENT_MAX_ATTEMPTS", "3"))},
        "budgets": {"max_tokens": int(env.get("AGENT_WORLD_AGENT_MAX_TOKENS", "0")), "max_cost": 0, "max_tool_calls": 0},
        "permissions": {
            "network": env.get("AGENT_WORLD_AGENT_NETWORK", "0") in {"1", "true", "True"},
            "filesystem": command_filesystem,
            "auth": auth_permission,
            "sandbox": command_sandbox,
        },
        "output_schema_ref": "AgentResult",
        "redaction_policy": {"secret_env_names_only": True, "redact_values": True},
    }
    return make_artifact(
        "AgentBackendConfig",
        source_stage=source_stage,
        producer="agent-backend-config-loader",
        fields=fields,
        artifact_id="agent-backend-config-default",
        status="accepted",
    )


def invoke_agent(
    registry: AgentBackendRegistry,
    request: AgentRequest,
    config: dict[str, Any],
    *,
    producer: str = "agent-invocation-runtime",
) -> tuple[dict[str, Any], AgentResult]:
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
        "output_artifact_ids": result.output_artifact_ids,
        "evidence_refs": result.evidence_refs,
        "trace_ref": result.trace_ref,
        "result_preview": result.text[:500],
        "usage": result.usage or {"tokens": None, "cost": None, "duration_ms": None},
        "failure_class": result.failure_class,
        "recovery_suggestion": result.recovery_suggestion,
    }
    fields = _redact_record_fields(fields, config)
    record = make_artifact(
        "AgentInvocationRecord",
        source_stage=request.stage,
        producer=producer,
        fields=fields,
        artifact_id=fields["invocation_id"],
        inputs=request.input_artifact_ids + [config["id"]],
        status=result.status,
    )
    return record, result


def _provider_for_backend(backend_kind: str) -> str:
    if backend_kind in {"process_agent"}:
        return "local_process"
    if backend_kind == "codex_cli":
        return "codex"
    if backend_kind == "manual":
        return "manual"
    if backend_kind == "mock":
        return "mock"
    if backend_kind == "llm":
        return "openai_compatible"
    return "custom"


def _is_transient_openai_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, urllib.error.URLError)


def _infer_api_version(base_url: str, backend_kind: str) -> str:
    if backend_kind == "llm" and base_url.rstrip("/").endswith("/v1"):
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


def _scrubbed_env(config: dict[str, Any], request: AgentRequest) -> dict[str, str]:
    allowed_names = {"PATH", "TMPDIR", "TEMP", "TMP"}
    child_env = {name: value for name, value in os.environ.items() if name in allowed_names}
    child_env["AGENT_WORLD_BACKEND_KIND"] = config.get("backend_kind", "")
    child_env["AGENT_WORLD_INVOCATION_STAGE"] = request.stage
    return child_env


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

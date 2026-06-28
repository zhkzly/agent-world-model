from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import urllib.error
import urllib.request
import hashlib
from dataclasses import dataclass, field
from pathlib import Path, PurePath
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
                recovery_suggestion="Set AGENT_WORLD_CODE_AGENT_CMD or configure AgentBackendConfig.command.argv",
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


class CodeAgentRunnerBackend:
    backend_kind = "code_agent_runner"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        try:
            command = _command_argv(config)
        except ValueError as exc:
            return AgentResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_code_agent_runner_config",
                recovery_suggestion="Use an allowlisted runner command without shell control operators or unsafe args.",
            )
        if not command:
            return AgentResult(
                text="code agent runner command is not configured",
                status="fail",
                failure_class="missing_runner_command",
                recovery_suggestion="Set AGENT_WORLD_CODE_AGENT_CMD or configure AgentBackendConfig.command.argv.",
            )
        workspace_text = str(request.permissions.get("filesystem_root") or "")
        if not workspace_text:
            return AgentResult(
                text="code agent runner requires filesystem_root",
                status="fail",
                failure_class="missing_runner_workspace",
                recovery_suggestion="Set request.permissions.filesystem_root to the isolated code-agent workspace.",
            )
        workspace = Path(workspace_text).resolve()
        if not workspace.is_dir():
            return AgentResult(
                text="code agent runner workspace does not exist",
                status="fail",
                failure_class="missing_runner_workspace",
                recovery_suggestion="Create the code-agent workspace packet before invoking the runner.",
            )
        if request.permissions.get("network") and not config.get("permissions", {}).get("network"):
            return AgentResult(
                text="code agent runner network permission denied",
                status="fail",
                failure_class="permission_denied",
                recovery_suggestion="Set AGENT_WORLD_AGENT_NETWORK=1 only for trusted live runners.",
            )
        if request.permissions.get("auth") and not config.get("permissions", {}).get("auth"):
            return AgentResult(
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
            return AgentResult(
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
            return AgentResult(
                text=completed.stderr.strip() or completed.stdout.strip(),
                status="fail",
                failure_class="runner_nonzero_exit",
                recovery_suggestion=f"Runner exited with {completed.returncode}.",
                trace_ref=command_log_ref,
                usage={"tokens": None, "cost": None, "duration_ms": duration_ms, "exit_code": completed.returncode},
            )
        manifest_path = output_dir / "candidate_manifest.json"
        if not manifest_path.is_file():
            return AgentResult(
                text="runner did not write agent-output/candidate_manifest.json",
                status="fail",
                failure_class="missing_runner_manifest",
                recovery_suggestion="Runner must write a candidate manifest after generating files.",
                evidence_refs=[command_log_ref],
                trace_ref=command_log_ref,
            )
        return AgentResult(
            text=json.dumps({"candidate_manifest_ref": "agent-output/candidate_manifest.json"}, sort_keys=True),
            evidence_refs=[command_log_ref, manifest_ref],
            trace_ref=command_log_ref,
            usage={"tokens": None, "cost": None, "duration_ms": duration_ms, "exit_code": completed.returncode},
        )


class CodexCliRunnerBackend(CodeAgentRunnerBackend):
    backend_kind = "codex_cli_runner"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        try:
            _validate_codex_cli_command(config)
        except ValueError as exc:
            return AgentResult(
                text=str(exc),
                status="fail",
                failure_class="invalid_codex_cli_runner_config",
                recovery_suggestion="Use Codex CLI with safe approval and sandbox flags.",
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


class OpenAICompatibleCodegenBackend:
    backend_kind = "openai_codegen"

    def invoke(self, request: AgentRequest, config: dict[str, Any]) -> AgentResult:
        if request.node_purpose != "implement":
            return AgentResult(
                text="openai_codegen only supports implementation nodes",
                status="fail",
                failure_class="invalid_codegen_request",
                recovery_suggestion="Use openai_codegen only for node_purpose=implement.",
            )
        root_text = str(request.permissions.get("filesystem_root") or "")
        if not root_text:
            return AgentResult(
                text="openai_codegen requires an isolated filesystem_root",
                status="fail",
                failure_class="missing_codegen_workdir",
                recovery_suggestion="Set request.permissions.filesystem_root to the isolated workdir.",
            )
        work_dir = PurePath(root_text)
        if work_dir.is_absolute() is False:
            return AgentResult(
                text="openai_codegen filesystem_root must be absolute",
                status="fail",
                failure_class="invalid_codegen_workdir",
                recovery_suggestion="Use an absolute isolated workdir path.",
            )
        if not request.permissions.get("network") or not config.get("permissions", {}).get("network"):
            return AgentResult(
                text="OpenAI-compatible codegen backend network permission denied",
                status="fail",
                failure_class="network_permission_denied",
                recovery_suggestion="Set AGENT_WORLD_AGENT_NETWORK=1 for live codegen.",
            )
        if not request.permissions.get("auth") or not config.get("permissions", {}).get("auth"):
            return AgentResult(
                text="OpenAI-compatible codegen backend auth permission denied",
                status="fail",
                failure_class="auth_permission_denied",
                recovery_suggestion="Configure an API key env var and allow auth for openai_codegen.",
            )
        payload, error = _openai_chat_completion(
            request,
            config,
            system_message=(
                "You are an environment code generation backend. Return only a JSON object with a files array. "
                "Each file item must contain path and content. Generate exactly the files requested by the user. "
                "Do not include API keys, credentials, or text outside JSON."
            ),
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
        return AgentResult(
            text=stable_json(write_result),
            evidence_refs=list(candidate.get("evidence_refs", [])) + ["openai-compatible-codegen://chat-completions"],
            trace_ref="openai-compatible-codegen://response",
            usage={"tokens": payload.get("usage"), "cost": None, "duration_ms": None},
        )


CODEGEN_FILE_KINDS = {
    "runtime.py": "runtime_code",
    "seed_state.json": "seed_fixture",
    "verifier.py": "verifier_code",
    "surface_descriptor.json": "surface_descriptor",
    "check_replay.py": "test_or_check",
    "build_manifest.yaml": "build_manifest",
}


def _openai_chat_completion(
    request: AgentRequest,
    config: dict[str, Any],
    *,
    system_message: str,
) -> tuple[dict[str, Any], AgentResult | None]:
    auth = config.get("auth", {})
    api_key_env = auth.get("api_key_env") or ""
    api_key = os.environ.get(api_key_env) if api_key_env else ""
    model = config.get("smoke_model") or config.get("model") or ""
    if not api_key or not model:
        return {}, AgentResult(
            text="OpenAI-compatible backend is not configured",
            status="needs_human",
            failure_class="missing_openai_configuration",
            recovery_suggestion="Set AGENT_WORLD_OPENAI_API_KEY and AGENT_WORLD_OPENAI_MODEL, or use AGENT_WORLD_AGENT_BACKEND=mock",
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
    return {}, AgentResult(
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


def _parse_codegen_response(text: str) -> tuple[dict[str, Any], AgentResult | None]:
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
    request: AgentRequest,
    config: dict[str, Any],
) -> tuple[dict[str, Any], AgentResult | None]:
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
        if rel_text not in CODEGEN_FILE_KINDS:
            return {}, _codegen_failure(
                "unexpected_codegen_file",
                "OpenAI-compatible codegen may only write the declared generated bundle files.",
            )
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
        target.write_text(content, encoding="utf-8")
        declared.add(rel_text)
    missing = sorted(set(CODEGEN_FILE_KINDS) - declared)
    if missing:
        return {}, _codegen_failure("missing_codegen_files", f"Model response did not include required files: {missing}")
    generated_files = [
        {
            "path": filename,
            "kind": kind,
            "sha256": _file_sha256(root / filename),
            "source_refs": _file_source_refs(candidate, filename, request),
        }
        for filename, kind in CODEGEN_FILE_KINDS.items()
    ]
    return {
        "candidate_dir": ".",
        "bundle_id": str(candidate.get("bundle_id") or "bundle-openai-codegen-candidate"),
        "environment_id": str(candidate.get("environment_id") or "generated-environment"),
        "generated_files": generated_files,
        "runtime_entrypoint": str(candidate.get("runtime_entrypoint") or "runtime.ProjectBoardLite"),
        "seed_fixture_ref": str(candidate.get("seed_fixture_ref") or "seed_state.json"),
        "verifier_entrypoint": str(candidate.get("verifier_entrypoint") or "verifier.verify_task_completion"),
        "surface_descriptors": list(candidate.get("surface_descriptors") or ["surface_descriptor.json"]),
        "check_commands": list(candidate.get("check_commands") or [["python", "check_replay.py"]]),
        "replay_commands": list(candidate.get("replay_commands") or [["python", "check_replay.py", "--task", "pb-task-1"]]),
    }, None


def _file_source_refs(candidate: dict[str, Any], filename: str, request: AgentRequest) -> list[str]:
    for item in candidate.get("files", []):
        if isinstance(item, dict) and item.get("path") == filename and isinstance(item.get("source_refs"), list) and item["source_refs"]:
            return [str(ref) for ref in item["source_refs"]]
    return request.input_artifact_ids or ["openai-codegen-response"]


def _codegen_path_error(path_text: str) -> AgentResult | None:
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


def _codegen_failure(failure_class: str, recovery_suggestion: str) -> AgentResult:
    return AgentResult(
        text=recovery_suggestion,
        status="fail",
        failure_class=failure_class,
        recovery_suggestion=recovery_suggestion,
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
    registry.register(CodeAgentRunnerBackend())
    registry.register(CodexCliRunnerBackend())
    registry.register(OpenAICompatibleBackend())
    registry.register(OpenAICompatibleCodegenBackend())
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
    if backend_kind in {"codex_cli", "codex_cli_runner"}:
        command_value = env.get("AGENT_WORLD_CODEX_CMD") or ""
    else:
        command_value = env.get("AGENT_WORLD_CODE_AGENT_CMD") or env.get("AGENT_WORLD_CODEX_CMD") or ""
    command_argv = shlex.split(command_value) if command_value else []
    allowlist_value = env.get("AGENT_WORLD_PROCESS_AGENT_ALLOWLIST") or env.get("AGENT_WORLD_CODEX_ALLOWLIST") or ""
    allowlist = shlex.split(allowlist_value) if allowlist_value else []
    if backend_kind in {"code_agent_runner", "codex_cli_runner"}:
        command_filesystem = "isolated_agent_workspace"
    elif backend_kind in {"process_agent", "codex_cli"}:
        command_filesystem = "controlled_process_cwd"
    else:
        command_filesystem = "artifact_context"
    command_sandbox = backend_kind in {"codex_cli", "codex_cli_runner"}
    auth_permission = bool(api_key_env) and backend_kind in {"llm", "openai_codegen", "code_agent_runner", "codex_cli_runner"}
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
            "requires_auth": backend_kind in {"llm", "openai_codegen", "code_agent_runner", "codex_cli_runner", "codex_sdk"},
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
    if backend_kind in {"process_agent", "code_agent_runner"}:
        return "local_process"
    if backend_kind in {"codex_cli", "codex_cli_runner"}:
        return "codex"
    if backend_kind == "manual":
        return "manual"
    if backend_kind == "mock":
        return "mock"
    if backend_kind in {"llm", "openai_codegen"}:
        return "openai_compatible"
    return "custom"


def _is_transient_openai_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code >= 500 or exc.code == 429
    return isinstance(exc, urllib.error.URLError)


def _infer_api_version(base_url: str, backend_kind: str) -> str:
    if backend_kind in {"llm", "openai_codegen"} and base_url.rstrip("/").endswith("/v1"):
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
    child_env["PYTHONDONTWRITEBYTECODE"] = "1"
    child_env["AGENT_WORLD_BACKEND_KIND"] = config.get("backend_kind", "")
    child_env["AGENT_WORLD_INVOCATION_STAGE"] = request.stage
    return child_env


def _runner_env(config: dict[str, Any], request: AgentRequest, workspace: Path) -> dict[str, str]:
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

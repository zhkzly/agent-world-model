"""The two real model boundaries: Direct chat and the Codex SDK."""

from __future__ import annotations

import asyncio
import json
import shutil
import stat
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal, cast

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError, OpenAI
from openai_codex import AsyncCodex, CodexConfig, Sandbox

from agent_world.config import (
    AgentRoute,
    ChatRoute,
    ConfigurationError,
    credential_from_environment,
)
from agent_world.contracts import SafeFailure

DIRECT_TIMEOUT_SECONDS = 300
AGENT_TIMEOUT_SECONDS = 600
_PRIVATE_PROVIDER_ID = "foundry_private"
_PRIVATE_PROVIDER_NAME = "Foundry private"
_RUNTIME_SKILLS = Path(__file__).with_name("runtime_skills")


@dataclass(frozen=True, slots=True)
class InvocationResult:
    value: dict[str, Any]
    route_model: str
    usage: dict[str, int] | None = None
    skill_digest: str | None = None


@dataclass(frozen=True, slots=True)
class _DirectFormatCondition:
    """A closed, raw-content-free classification of a rejected Direct response."""

    kind: Literal[
        "markdown_fence",
        "outer_content",
        "non_object_root",
        "invalid_json_syntax",
    ]
    line: int | None = None
    column: int | None = None

    def violated_condition(self) -> str:
        if self.kind == "markdown_fence":
            return "response is wrapped in a Markdown code fence"
        if self.kind == "outer_content":
            return "response has non-JSON leading or trailing content, or extra JSON data"
        if self.kind == "non_object_root":
            return "top-level JSON value is not an object"
        if self.line is None or self.column is None:
            return "response has invalid JSON syntax"
        return f"response has invalid JSON syntax at line {self.line}, column {self.column}"


@dataclass(frozen=True, slots=True)
class _DirectFormatFailure:
    """A completed Direct response retained only for one in-memory Feedback turn."""

    raw_content: str
    route_model: str
    usage: dict[str, int] | None = None
    condition: _DirectFormatCondition = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition", _direct_format_condition(self.raw_content))


class InvocationError(RuntimeError):
    def __init__(self, failure: SafeFailure) -> None:
        super().__init__(failure.code)
        self.failure = failure


def _json_object(text: str, code: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", maxsplit=1)[-1].rsplit("```", maxsplit=1)[0].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvocationError(SafeFailure(code, "rejected")) from exc
    if not isinstance(value, dict):
        raise InvocationError(SafeFailure(code, "rejected"))
    return value


def _direct_format_condition(text: str) -> _DirectFormatCondition:
    """Classify a strict-parser rejection without extracting or retaining its content."""

    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        return _DirectFormatCondition("markdown_fence")
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        if exc.msg == "Extra data" or (exc.pos == 0 and ("{" in stripped or "[" in stripped)):
            return _DirectFormatCondition("outer_content")
        return _DirectFormatCondition("invalid_json_syntax", exc.lineno, exc.colno)
    if not isinstance(value, dict):
        return _DirectFormatCondition("non_object_root")
    raise ValueError("direct_format_condition_requires_rejection")


def _direct_usage(raw_usage: object) -> dict[str, int] | None:
    fields = {
        provider: (
            raw_usage.get(provider)
            if isinstance(raw_usage, Mapping)
            else getattr(raw_usage, provider, None)
        )
        for provider in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    usage = {
        canonical: value
        for provider, canonical in {
            "prompt_tokens": "input_tokens",
            "completion_tokens": "output_tokens",
            "total_tokens": "total_tokens",
        }.items()
        if type(value := fields[provider]) is int and value >= 0
    }
    return usage or None


def _toml_string(value: str) -> str:
    """Return a TOML-compatible basic string without interpolating route data."""

    return json.dumps(value, ensure_ascii=True)


def _private_provider_overrides(route: AgentRoute) -> tuple[str, ...]:
    provider = f"model_providers.{_PRIVATE_PROVIDER_ID}"
    return (
        f"{provider}.name = {_toml_string(_PRIVATE_PROVIDER_NAME)}",
        f"{provider}.base_url = {_toml_string(route.base_url)}",
        f"{provider}.env_key = {_toml_string(route.api_key_env)}",
        f'{provider}.wire_api = "responses"',
        "request_max_retries = 0",
        "stream_max_retries = 0",
        "skills.bundled.enabled = false",
        "features.plugins = false",
    )


class DirectChatBackend:
    """One direct route and one retryable-failure fallback, nothing more."""

    def __init__(self, primary: ChatRoute, fallback: ChatRoute) -> None:
        self.primary = primary
        self.fallback = fallback

    def invoke_json(
        self,
        *,
        system: str,
        user: str,
        previous_assistant: str | None = None,
        feedback: str | None = None,
    ) -> InvocationResult | _DirectFormatFailure:
        try:
            return self._call(self.primary, system, user, previous_assistant, feedback)
        except InvocationError as exc:
            if not exc.failure.retryable:
                raise
        return self._call(self.fallback, system, user, previous_assistant, feedback)

    def _call(
        self,
        route: ChatRoute,
        system: str,
        user: str,
        previous_assistant: str | None,
        feedback: str | None,
    ) -> InvocationResult | _DirectFormatFailure:
        try:
            key = credential_from_environment(route.api_key_env)
        except ConfigurationError as exc:
            raise InvocationError(SafeFailure(str(exc), "needs_human")) from exc
        if (previous_assistant is None) != (feedback is None):
            raise ValueError("direct_feedback_turn_invalid")
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if previous_assistant is not None and feedback is not None:
            messages.extend(
                (
                    {"role": "assistant", "content": previous_assistant},
                    {"role": "user", "content": feedback},
                )
            )
        try:
            with OpenAI(
                base_url=route.base_url,
                api_key=key or "",
                timeout=DIRECT_TIMEOUT_SECONDS,
                max_retries=0,
            ) as client:
                response = client.chat.completions.create(
                    model=route.model,
                    messages=cast(Any, messages),
                    temperature=0,
                    response_format={"type": "json_object"},
                )
        except (APIConnectionError, APITimeoutError, OSError) as exc:
            raise InvocationError(SafeFailure("direct_transport_failure", "error", True)) from exc
        except APIStatusError as exc:
            raise InvocationError(
                SafeFailure(
                    "direct_http_failure",
                    "error",
                    getattr(exc, "status_code", None) in {408, 429, 500, 502, 503, 504},
                )
            ) from exc
        except APIError as exc:
            raise InvocationError(SafeFailure("direct_response_invalid", "rejected")) from exc
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise InvocationError(SafeFailure("direct_response_invalid", "rejected"))
        choice = choices[0]
        message = getattr(choice, "message", None)
        if getattr(message, "refusal", None) is not None:
            raise InvocationError(SafeFailure("direct_response_refusal", "rejected"))
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason != "stop":
            code = (
                "direct_response_truncated"
                if finish_reason == "length"
                else "direct_response_refusal"
                if finish_reason == "content_filter"
                else "direct_response_invalid"
            )
            raise InvocationError(SafeFailure(code, "rejected"))
        content = getattr(message, "content", None)
        if not isinstance(content, str) or not content.strip():
            raise InvocationError(SafeFailure("direct_response_empty", "rejected"))
        usage = _direct_usage(getattr(response, "usage", None))
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        if not isinstance(parsed, dict):
            return _DirectFormatFailure(content, route.model, usage)
        return InvocationResult(parsed, route.model, usage)


class CodexAgentBackend:
    """A real Agent invocation with exactly one explicit Skill file per work.

    Every work gets its own disposable directory. Only CandidateBuild's
    directory is later scanned as candidate source; all access decisions stay
    explicit at the SDK adapter boundary.
    """

    def __init__(self, primary: AgentRoute, fallback: AgentRoute) -> None:
        self.primary = primary
        self.fallback = fallback

    def invoke_json(
        self,
        *,
        work: str,
        skill_name: str,
        workspace: Path,
        instruction: str,
        writable: bool = False,
        require_json: bool = True,
    ) -> InvocationResult:
        try:
            return self._call(
                self.primary,
                work,
                skill_name,
                workspace,
                instruction,
                writable,
                require_json,
            )
        except InvocationError as exc:
            if not exc.failure.retryable:
                raise
        return self._call(
            self.fallback,
            work,
            skill_name,
            workspace,
            instruction,
            writable,
            require_json,
        )

    def _call(
        self,
        route: AgentRoute,
        work: str,
        skill_name: str,
        workspace: Path,
        instruction: str,
        writable: bool,
        require_json: bool,
    ) -> InvocationResult:
        del writable  # The approved SDK adapter always selects explicit full access.
        try:
            api_key = credential_from_environment(route.api_key_env)
        except ConfigurationError as exc:
            raise InvocationError(SafeFailure(str(exc), "needs_human")) from exc
        codex_home: Path | None = None
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            # A runtime Agent gets a fresh Codex discovery root with exactly one
            # mounted Skill. Project .agents assets and user rules are never an
            # implicit part of a product invocation.
            codex_home = Path(tempfile.mkdtemp(prefix=".foundry-codex-home-", dir=workspace.parent))
            source = _runtime_skill_root(skill_name)
            source_digest = _bundle_digest(source)
            mounted = codex_home / "skills" / skill_name
            shutil.copytree(source, mounted)
            before = _bundle_digest(mounted)
            if before != source_digest or _mounted_skill_names(codex_home) != (skill_name,):
                raise InvocationError(SafeFailure("agent_skill_surface_unverified", "error"))
            prompt = (
                f"You are {work}. Use the only available Runtime Skill named {skill_name}. "
                f"{instruction}\n"
                "Return exactly one JSON object; never claim hashes, gates, manifests, "
                "Judge, or release."
            )
            environment = {"CODEX_HOME": str(codex_home), "HOME": str(codex_home)}
            if route.api_key_env:
                environment[route.api_key_env] = api_key or ""
            config = CodexConfig(
                config_overrides=_private_provider_overrides(route),
                cwd=str(workspace),
                env=environment,
            )
            output, usage = asyncio.run(
                asyncio.wait_for(
                    self._run_sdk_turn(config, route, workspace, prompt),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
            )
            after = _bundle_digest(mounted)
            if after != before or _mounted_skill_names(codex_home) != (skill_name,):
                raise InvocationError(SafeFailure("agent_skill_surface_unverified", "error"))
        except FileNotFoundError as exc:
            raise InvocationError(SafeFailure("agent_command_missing", "needs_human")) from exc
        except TimeoutError as exc:
            raise InvocationError(SafeFailure("agent_timeout", "error", True)) from exc
        except OSError as exc:
            raise InvocationError(SafeFailure("agent_launch_failure", "error", True)) from exc
        except InvocationError:
            raise
        except Exception as exc:
            raise InvocationError(SafeFailure("agent_execution_failure", "error", True)) from exc
        finally:
            if codex_home is not None:
                shutil.rmtree(codex_home, ignore_errors=True)
        if not isinstance(output, str) or not output.strip():
            raise InvocationError(SafeFailure("agent_output_missing", "error", True))
        value = _json_object(output, "agent_response_not_json") if require_json else {}
        return InvocationResult(value, route.model, usage, f"sha256:{after}")

    async def _run_sdk_turn(
        self,
        config: CodexConfig,
        route: AgentRoute,
        workspace: Path,
        prompt: str,
    ) -> tuple[str | None, dict[str, int] | None]:
        session = AsyncCodex(config)
        try:
            thread = await session.thread_start(
                model_provider=_PRIVATE_PROVIDER_ID,
                model=route.model,
                cwd=str(workspace),
                ephemeral=True,
                sandbox=Sandbox.full_access,
            )
            turn = await thread.run(
                prompt,
                cwd=str(workspace),
                model=route.model,
                sandbox=Sandbox.full_access,
            )
            status = getattr(turn.status, "value", turn.status)
            if status != "completed":
                raise RuntimeError("agent turn did not complete")
            return turn.final_response, _sdk_usage(turn)
        finally:
            await session.close()


def _bundle_digest(root: Path) -> str:
    if root.is_symlink() or not root.is_dir() or not (root / "SKILL.md").is_file():
        raise InvocationError(SafeFailure("agent_runtime_skill_invalid", "error"))
    entries: list[tuple[str, str, int, str | None]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise InvocationError(SafeFailure("agent_runtime_skill_invalid", "error"))
        mode = stat.S_IMODE(path.stat().st_mode)
        if path.is_file():
            entries.append(("file", relative, mode, sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            entries.append(("directory", relative, mode, None))
        else:
            raise InvocationError(SafeFailure("agent_runtime_skill_invalid", "error"))
    return sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()


def _mounted_skill_names(codex_home: Path) -> tuple[str, ...]:
    skills = codex_home / "skills"
    if not skills.is_dir():
        return ()
    entries = list(skills.iterdir())
    if any(not entry.is_dir() or entry.is_symlink() for entry in entries):
        return ()
    return tuple(sorted(entry.name for entry in entries))


def _runtime_skill_root(skill_name: str) -> Path:
    root = _RUNTIME_SKILLS / skill_name
    if root.parent != _RUNTIME_SKILLS or root.is_symlink() or not root.is_dir():
        raise InvocationError(SafeFailure("agent_runtime_skill_missing", "error"))
    return root


def _sdk_usage(turn: object) -> dict[str, int] | None:
    """Project one SDK-reported turn total without inventing unavailable usage."""

    raw_usage = getattr(turn, "usage", None)
    total = getattr(raw_usage, "total", None)
    fields = {
        "cached_input_tokens": getattr(total, "cached_input_tokens", None),
        "input_tokens": getattr(total, "input_tokens", None),
        "output_tokens": getattr(total, "output_tokens", None),
        "reasoning_output_tokens": getattr(total, "reasoning_output_tokens", None),
        "total_tokens": getattr(total, "total_tokens", None),
    }
    if not all(type(value) is int and value >= 0 for value in fields.values()):
        return None
    return {name: cast(int, value) for name, value in fields.items()}


def runtime_skill_digest(skill_name: str) -> str:
    """Return the exact product-owned Runtime Skill closure commitment."""

    return f"sha256:{_bundle_digest(_runtime_skill_root(skill_name))}"

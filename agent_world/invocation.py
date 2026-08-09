"""The two real model boundaries: Direct chat and the Codex SDK."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openai_codex import AsyncCodex, CodexConfig, Sandbox

from agent_world.config import (
    AgentRoute,
    ChatRoute,
    ConfigurationError,
    credential_from_environment,
)
from agent_world.contracts import SafeFailure

DIRECT_TIMEOUT_SECONDS = 120
AGENT_TIMEOUT_SECONDS = 600
_PRIVATE_PROVIDER_ID = "foundry_private"
_PRIVATE_PROVIDER_NAME = "Foundry private"


@dataclass(frozen=True, slots=True)
class InvocationResult:
    value: dict[str, Any]
    route_model: str


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


def _chat_endpoint(route: ChatRoute) -> str:
    return (
        route.base_url
        if route.base_url.endswith("/chat/completions")
        else f"{route.base_url}/chat/completions"
    )


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
    )


class DirectChatBackend:
    """One direct route and one retryable-failure fallback, nothing more."""

    def __init__(self, primary: ChatRoute, fallback: ChatRoute) -> None:
        self.primary = primary
        self.fallback = fallback

    def invoke_json(self, *, system: str, user: str) -> InvocationResult:
        try:
            return self._call(self.primary, system, user)
        except InvocationError as exc:
            if not exc.failure.retryable:
                raise
        return self._call(self.fallback, system, user)

    def _call(self, route: ChatRoute, system: str, user: str) -> InvocationResult:
        try:
            key = credential_from_environment(route.api_key_env)
        except ConfigurationError as exc:
            raise InvocationError(SafeFailure(str(exc), "needs_human")) from exc
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        body = json.dumps(
            {
                "model": route.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": 4096,
            }
        ).encode("utf-8")
        try:
            with urlopen(  # noqa: S310 - strict config permits only HTTP(S) endpoints
                Request(_chat_endpoint(route), data=body, headers=headers),  # noqa: S310
                timeout=DIRECT_TIMEOUT_SECONDS,
            ) as response:  # noqa: S310 - URL came from strict config
                response_body = response.read()
        except HTTPError as exc:
            raise InvocationError(
                SafeFailure(
                    "direct_http_failure", "error", exc.code in {408, 429, 500, 502, 503, 504}
                )
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise InvocationError(SafeFailure("direct_transport_failure", "error", True)) from exc
        try:
            message = json.loads(response_body)["choices"][0]["message"]
            content = message["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise InvocationError(SafeFailure("direct_response_invalid", "rejected")) from exc
        if not isinstance(content, str) or not content.strip():
            raise InvocationError(SafeFailure("direct_response_empty", "rejected"))
        return InvocationResult(_json_object(content, "direct_response_not_json"), route.model)


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
        skill_body: str,
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
                skill_body,
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
            skill_body,
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
        skill_body: str,
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
            skill_file = codex_home / "skills" / skill_name / "SKILL.md"
            skill_file.parent.mkdir(parents=True, exist_ok=True)
            skill_file.write_text(skill_body, encoding="utf-8")
            prompt = (
                f"You are {work}. Use the only available Runtime Skill named {skill_name}. "
                f"{instruction}\n"
                "Return exactly one JSON object; never claim hashes, gates, manifests, "
                "Judge, or release."
            )
            environment = {"CODEX_HOME": str(codex_home)}
            if route.api_key_env:
                environment[route.api_key_env] = api_key or ""
            config = CodexConfig(
                config_overrides=_private_provider_overrides(route),
                cwd=str(workspace),
                env=environment,
            )
            output = asyncio.run(
                asyncio.wait_for(
                    self._run_sdk_turn(config, route, workspace, prompt),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
            )
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
        return InvocationResult(value, route.model)

    async def _run_sdk_turn(
        self,
        config: CodexConfig,
        route: AgentRoute,
        workspace: Path,
        prompt: str,
    ) -> str | None:
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
            return turn.final_response
        finally:
            await session.close()

from __future__ import annotations

import asyncio
import json
from dataclasses import fields
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai_codex import AsyncCodex, CodexConfig

from agent_world.config import AgentRoute, ChatRoute, ConfigurationError, load_settings
from agent_world.contracts import SafeFailure
from agent_world.invocation import (
    CodexAgentBackend,
    DirectChatBackend,
    InvocationError,
    InvocationResult,
    Sandbox,
    _DirectFormatFailure,
    _private_provider_overrides,
    runtime_skill_digest,
)


def _settings_text(*, primary: str, fallback: str) -> str:
    return f"""[foundry]
state_root = ".agent-world-runs"

[direct.primary]
model = "direct-primary"
base_url = "https://direct-primary.invalid/v1"
api_key_env = ""

[direct.fallback]
model = "direct-fallback"
base_url = "https://direct-fallback.invalid/v1"
api_key_env = ""

[agent.primary]
{primary}

[agent.fallback]
{fallback}

[research]
search_url = "https://search.invalid"
reader_url = "https://reader.invalid"
api_key_env = ""
"""


def _valid_agent_route(model: str) -> str:
    return f'''model = "{model}"
base_url = "http://localhost:8317/v1"
api_key_env = "TEST_AGENT_KEY"'''


def test_agent_routes_match_the_strict_chat_route_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    credential = "test-agent-credential"
    monkeypatch.setenv("TEST_AGENT_KEY", credential)
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        _settings_text(
            primary=_valid_agent_route("agent-primary"),
            fallback=_valid_agent_route("agent-fallback"),
        ),
        encoding="utf-8",
    )

    settings = load_settings(settings_path)

    assert tuple(field.name for field in fields(AgentRoute)) == (
        "model",
        "base_url",
        "api_key_env",
    )
    assert settings.agent_primary == AgentRoute(
        model="agent-primary",
        base_url="http://localhost:8317/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    assert settings.agent_fallback == AgentRoute(
        model="agent-fallback",
        base_url="http://localhost:8317/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    assert credential not in repr(settings)


def test_checked_in_example_selects_the_direct_luna_spark_routes() -> None:
    settings = load_settings(Path("config/agent-world.example.toml"))

    expected = ChatRoute(
        model="gpt-5.6-luna",
        base_url="http://localhost:8317/v1",
        api_key_env="OPENAI_API_KEY",
    )
    assert settings.direct_primary == expected
    assert settings.direct_fallback == ChatRoute(
        model="gpt-5.3-codex-spark",
        base_url="http://localhost:8317/v1",
        api_key_env="OPENAI_API_KEY",
    )


def test_direct_routes_require_an_openai_api_root(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(
        _settings_text(
            primary=_valid_agent_route("agent-primary"),
            fallback=_valid_agent_route("agent-fallback"),
        ).replace(
            "https://direct-primary.invalid/v1",
            "https://direct-primary.invalid/v1/chat/completions",
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ConfigurationError, match="config_direct_primary_base_url_api_root_required"
    ):
        load_settings(settings_path)


def _direct_completion(
    content: str,
    usage: object,
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content=content, refusal=refusal),
            )
        ],
        usage=usage,
    )


def _install_direct_client(
    monkeypatch: pytest.MonkeyPatch, response: object, captured: dict[str, object]
) -> None:
    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured["client"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def __enter__(self) -> FakeOpenAI:
            return self

        def __exit__(self, *_args: object) -> None:
            captured["closed"] = True

        def create(self, **kwargs: object) -> object:
            captured["request"] = kwargs
            return response

    monkeypatch.setattr("agent_world.invocation.OpenAI", FakeOpenAI)


@pytest.mark.parametrize(
    ("raw_usage", "expected_usage"),
    [
        (
            {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18, "ignored": 99},
            {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
        ),
        ({"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "18"}, None),
    ],
)
def test_direct_chat_normalizes_only_valid_provider_usage(
    monkeypatch: pytest.MonkeyPatch,
    raw_usage: dict[str, object],
    expected_usage: dict[str, int] | None,
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    _install_direct_client(
        monkeypatch,
        _direct_completion('{"ok": true}', raw_usage),
        captured,
    )

    assert backend.invoke_json(system="safe", user="safe") == InvocationResult(
        {"ok": True}, route.model, expected_usage
    )
    assert captured["closed"] is True


def test_direct_chat_requests_the_fixed_json_object_response_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    _install_direct_client(monkeypatch, _direct_completion('{"ok": true}', None), captured)

    assert backend.invoke_json(system="system", user="user").value == {"ok": True}
    assert captured["client"] == {
        "base_url": route.base_url,
        "api_key": "",
        "timeout": 300,
        "max_retries": 0,
    }
    assert captured["request"] == {
        "model": route.model,
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "user"},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    assert captured["closed"] is True


def test_direct_chat_reconstructs_only_the_format_feedback_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    _install_direct_client(monkeypatch, _direct_completion('{"ok": true}', None), captured)

    assert backend.invoke_json(
        system="system",
        user="original-user",
        previous_assistant="not a JSON object",
        feedback="format-feedback",
    ).value == {"ok": True}
    request = captured["request"]
    assert isinstance(request, dict)
    assert request["messages"] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "original-user"},
        {"role": "assistant", "content": "not a JSON object"},
        {"role": "user", "content": "format-feedback"},
    ]
    assert "max_tokens" not in request
    assert "max_completion_tokens" not in request


@pytest.mark.parametrize(
    ("content", "kind", "condition"),
    [
        (
            '```json\n{"ok": true}\n```',
            "markdown_fence",
            "response is wrapped in a Markdown code fence",
        ),
        (
            'Here is {"ok": true}',
            "outer_content",
            "response has non-JSON leading or trailing content, or extra JSON data",
        ),
        (
            '{"ok": true} and another explanation',
            "outer_content",
            "response has non-JSON leading or trailing content, or extra JSON data",
        ),
        (
            '["not", "an", "object"]',
            "non_object_root",
            "top-level JSON value is not an object",
        ),
        (
            '{"ok":',
            "invalid_json_syntax",
            "response has invalid JSON syntax at line 1, column 7",
        ),
    ],
)
def test_direct_chat_rejects_every_safe_format_category(
    monkeypatch: pytest.MonkeyPatch, content: str, kind: str, condition: str
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    _install_direct_client(monkeypatch, _direct_completion(content, {"total_tokens": 4}), captured)

    result = backend.invoke_json(system="system", user="user")

    assert isinstance(result, _DirectFormatFailure)
    assert result.route_model == route.model
    assert result.usage == {"total_tokens": 4}
    assert result.condition.kind == kind
    assert result.condition.violated_condition() == condition
    assert captured["closed"] is True


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            _direct_completion('{"ok": true}', None, finish_reason="length"),
            "direct_response_truncated",
        ),
        (_direct_completion("", None), "direct_response_empty"),
        (_direct_completion('{"ok": true}', None, refusal="refused"), "direct_response_refusal"),
    ],
)
def test_direct_chat_rejects_non_format_terminals_without_feedback(
    monkeypatch: pytest.MonkeyPatch, response: object, expected: str
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    _install_direct_client(monkeypatch, response, captured)

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(system="system", user="user")

    assert raised.value.failure == SafeFailure(expected, "rejected")
    assert captured["closed"] is True


def test_direct_chat_uses_only_the_configured_credential_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = ChatRoute("direct-test", "http://direct.invalid/v1", "DIRECT_TEST_KEY")
    backend = DirectChatBackend(route, route)
    captured: dict[str, object] = {}
    monkeypatch.setenv("DIRECT_TEST_KEY", "configured-direct-credential")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-direct-credential")
    _install_direct_client(monkeypatch, _direct_completion('{"ok": true}', None), captured)

    assert backend.invoke_json(system="system", user="user").value == {"ok": True}
    client = captured["client"]
    assert isinstance(client, dict)
    assert client["api_key"] == "configured-direct-credential"

    monkeypatch.delenv("DIRECT_TEST_KEY")
    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(system="system", user="user")

    assert raised.value.failure == SafeFailure("credential_missing", "needs_human")


def test_direct_chat_maps_retryable_transport_failure_without_provider_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary = ChatRoute("direct-primary", "http://primary.invalid/v1", "")
    fallback = ChatRoute("direct-fallback", "http://fallback.invalid/v1", "")
    backend = DirectChatBackend(primary, fallback)
    client_calls: list[dict[str, object]] = []

    class BrokenOpenAI:
        def __init__(self, **kwargs: object) -> None:
            client_calls.append(kwargs)

        def __enter__(self) -> BrokenOpenAI:
            raise OSError("private provider transport detail")

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr("agent_world.invocation.OpenAI", BrokenOpenAI)

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(system="system", user="user")

    assert raised.value.failure == SafeFailure("direct_transport_failure", "error", True)
    assert [call["base_url"] for call in client_calls] == [primary.base_url, fallback.base_url]
    assert "private provider transport detail" not in str(raised.value)


@pytest.mark.parametrize(
    ("primary", "fallback", "error"),
    [
        (
            _valid_agent_route("agent-primary") + '\nunexpected = "field"',
            _valid_agent_route("agent-fallback"),
            "config_agent_primary_unknown_field",
        ),
        (
            _valid_agent_route("agent-primary"),
            'model = "agent-fallback"\napi_key_env = "TEST_AGENT_KEY"',
            "config_agent_fallback_base_url_required",
        ),
        (
            'model = "agent-primary"\nbase_url = "ftp://invalid"\napi_key_env = "TEST_AGENT_KEY"',
            _valid_agent_route("agent-fallback"),
            "config_agent_primary_base_url_invalid_url",
        ),
    ],
)
def test_agent_routes_reject_unknown_missing_or_invalid_fields(
    tmp_path: Path, primary: str, fallback: str, error: str
) -> None:
    settings_path = tmp_path / "settings.toml"
    settings_path.write_text(_settings_text(primary=primary, fallback=fallback), encoding="utf-8")

    with pytest.raises(ConfigurationError, match=error):
        load_settings(settings_path)


def test_codex_agent_sdk_session_is_isolated_and_not_persisted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credential = "test-agent-credential"
    route = AgentRoute(
        model="agent-test-model",
        base_url="http://configured-agent.invalid/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    backend = CodexAgentBackend(route, route)
    workspace = tmp_path / "workspace"
    captured: dict[str, object] = {}
    monkeypatch.setenv("TEST_AGENT_KEY", credential)
    monkeypatch.setenv("OPENAI_BASE_URL", "http://ambient-agent.invalid/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-agent-credential")
    monkeypatch.setenv("CODEX_HOME", "/ambient-codex-home")
    monkeypatch.setenv("HOME", "/ambient-user-home")

    class FakeThread:
        async def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
            captured["prompt"] = prompt
            captured["run_kwargs"] = kwargs
            return SimpleNamespace(
                status="completed",
                final_response='{"ok": true}',
                usage=SimpleNamespace(
                    total=SimpleNamespace(
                        cached_input_tokens=3,
                        input_tokens=11,
                        output_tokens=7,
                        reasoning_output_tokens=5,
                        total_tokens=23,
                    )
                ),
            )

    class FakeAsyncCodex:
        def __init__(self, config: CodexConfig) -> None:
            captured["config"] = config

        async def thread_start(self, **kwargs: object) -> FakeThread:
            captured["thread_kwargs"] = kwargs
            config = captured["config"]
            assert isinstance(config, CodexConfig)
            environment = config.env
            assert environment is not None
            codex_home = Path(environment["CODEX_HOME"])
            captured["codex_home"] = codex_home
            skills = codex_home / "skills"
            captured["skill_names"] = [entry.name for entry in skills.iterdir()]
            captured["skill_body"] = (skills / "research-world-evidence" / "SKILL.md").read_text(
                encoding="utf-8"
            )
            return FakeThread()

        async def close(self) -> None:
            closed = captured.get("closed", 0)
            assert isinstance(closed, int)
            captured["closed"] = closed + 1

    monkeypatch.setattr("agent_world.invocation.AsyncCodex", FakeAsyncCodex)

    result = backend.invoke_json(
        work="researcher",
        skill_name="research-world-evidence",
        workspace=workspace,
        instruction="Return a safe test object.",
        writable=False,
    )

    config = captured["config"]
    thread_kwargs = captured["thread_kwargs"]
    run_kwargs = captured["run_kwargs"]
    assert isinstance(config, CodexConfig)
    assert isinstance(thread_kwargs, dict)
    assert isinstance(run_kwargs, dict)
    assert result.value == {"ok": True}
    assert result.route_model == route.model
    assert result.usage == {
        "cached_input_tokens": 3,
        "input_tokens": 11,
        "output_tokens": 7,
        "reasoning_output_tokens": 5,
        "total_tokens": 23,
    }
    assert config.cwd == str(workspace)
    assert config.config_overrides == (
        'model_providers.foundry_private.name = "Foundry private"',
        f"model_providers.foundry_private.base_url = {json.dumps(route.base_url)}",
        f"model_providers.foundry_private.env_key = {json.dumps(route.api_key_env)}",
        'model_providers.foundry_private.wire_api = "responses"',
        "request_max_retries = 0",
        "stream_max_retries = 0",
        "skills.bundled.enabled = false",
        "features.plugins = false",
    )
    assert config.env is not None
    assert set(config.env) == {"CODEX_HOME", "HOME", "TEST_AGENT_KEY"}
    assert config.env["HOME"] == config.env["CODEX_HOME"]
    assert config.env["HOME"] != "/ambient-user-home"
    assert config.env["TEST_AGENT_KEY"] == credential
    assert "OPENAI_BASE_URL" not in config.env
    assert "OPENAI_API_KEY" not in config.env
    assert thread_kwargs == {
        "model_provider": "foundry_private",
        "model": route.model,
        "cwd": str(workspace),
        "ephemeral": True,
        "sandbox": Sandbox.full_access,
    }
    assert run_kwargs == {
        "cwd": str(workspace),
        "model": route.model,
        "sandbox": Sandbox.full_access,
    }
    assert captured["skill_names"] == ["research-world-evidence"]
    assert isinstance(captured["skill_body"], str)
    assert "citation-backed research" in captured["skill_body"]
    assert captured["closed"] == 1
    assert result.skill_digest == runtime_skill_digest("research-world-evidence")

    codex_home = captured["codex_home"]
    assert isinstance(codex_home, Path)
    assert codex_home.parent == workspace.parent
    assert codex_home != Path("/ambient-codex-home")
    assert not codex_home.exists()
    assert list(workspace.iterdir()) == []

    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert credential.encode() not in persisted
    assert route.base_url.encode() not in persisted


def test_codex_agent_uses_only_the_configured_credential_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = AgentRoute(
        model="agent-test-model",
        base_url="http://configured-agent.invalid/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    backend = CodexAgentBackend(route, route)
    workspace = tmp_path / "workspace"
    monkeypatch.delenv("TEST_AGENT_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-agent-credential")

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(
            work="researcher",
            skill_name="research-world-evidence",
            workspace=workspace,
            instruction="Return a safe test object.",
        )

    assert raised.value.failure == SafeFailure("credential_missing", "needs_human")
    assert not workspace.exists()


def test_codex_agent_reports_missing_bundled_sdk_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = AgentRoute(
        model="agent-test-model",
        base_url="http://configured-agent.invalid/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    backend = CodexAgentBackend(route, route)
    monkeypatch.setenv("TEST_AGENT_KEY", "test-agent-credential")

    class MissingBundledRuntime:
        def __init__(self, _config: CodexConfig) -> None:
            raise FileNotFoundError("bundled runtime missing")

    monkeypatch.setattr("agent_world.invocation.AsyncCodex", MissingBundledRuntime)

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(
            work="researcher",
            skill_name="research-world-evidence",
            workspace=tmp_path / "workspace",
            instruction="Return a safe test object.",
        )

    assert raised.value.failure == SafeFailure("agent_command_missing", "needs_human")


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("timeout", SafeFailure("agent_timeout", "error", True)),
        ("execution", SafeFailure("agent_execution_failure", "error", True)),
        ("provider_terminal", SafeFailure("agent_execution_failure", "error", True)),
        ("output", SafeFailure("agent_output_missing", "error", True)),
    ],
)
def test_codex_agent_sdk_terminal_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    expected: SafeFailure,
) -> None:
    route = AgentRoute(
        model="agent-test-model",
        base_url="http://configured-agent.invalid/v1",
        api_key_env="TEST_AGENT_KEY",
    )
    backend = CodexAgentBackend(route, route)
    monkeypatch.setenv("TEST_AGENT_KEY", "test-agent-credential")

    class FakeThread:
        async def run(self, _prompt: str, **_kwargs: object) -> SimpleNamespace:
            if mode == "timeout":
                raise TimeoutError("timed out")
            if mode == "execution":
                raise RuntimeError("turn failed")
            if mode == "provider_terminal":
                return SimpleNamespace(status="failed", final_response='{"provider": "text"}')
            return SimpleNamespace(status="completed", final_response=None)

    class FakeAsyncCodex:
        def __init__(self, _config: CodexConfig) -> None:
            pass

        async def thread_start(self, **_kwargs: object) -> FakeThread:
            return FakeThread()

        async def close(self) -> None:
            return None

    monkeypatch.setattr("agent_world.invocation.AsyncCodex", FakeAsyncCodex)

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(
            work="researcher",
            skill_name="research-world-evidence",
            workspace=tmp_path / "workspace",
            instruction="Return a safe test object.",
        )

    assert raised.value.failure == expected
    assert not list(tmp_path.glob(".foundry-codex-home-*"))


def test_codex_agent_rejects_invalid_json_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = AgentRoute("primary", "http://primary.invalid/v1", "PRIMARY_KEY")
    fallback = AgentRoute("fallback", "http://fallback.invalid/v1", "FALLBACK_KEY")
    backend = CodexAgentBackend(primary, fallback)
    monkeypatch.setenv("PRIMARY_KEY", "primary-credential")
    monkeypatch.setenv("FALLBACK_KEY", "fallback-credential")
    calls: list[str] = []

    class FakeThread:
        async def run(self, _prompt: str, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status="completed", final_response="not-json")

    class FakeAsyncCodex:
        def __init__(self, config: CodexConfig) -> None:
            assert config.env is not None
            calls.append("PRIMARY_KEY" if "PRIMARY_KEY" in config.env else "FALLBACK_KEY")

        async def thread_start(self, **_kwargs: object) -> FakeThread:
            return FakeThread()

        async def close(self) -> None:
            return None

    monkeypatch.setattr("agent_world.invocation.AsyncCodex", FakeAsyncCodex)

    with pytest.raises(InvocationError) as raised:
        backend.invoke_json(
            work="researcher",
            skill_name="research-world-evidence",
            workspace=tmp_path / "workspace",
            instruction="Return a safe test object.",
        )

    assert raised.value.failure == SafeFailure("agent_response_not_json", "rejected")
    assert calls == ["PRIMARY_KEY"]


def test_codex_agent_preserves_require_json_false_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = AgentRoute("primary", "http://primary.invalid/v1", "PRIMARY_KEY")
    backend = CodexAgentBackend(route, route)
    monkeypatch.setenv("PRIMARY_KEY", "primary-credential")

    class FakeThread:
        async def run(self, _prompt: str, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(status="completed", final_response="plain completion")

    class FakeAsyncCodex:
        def __init__(self, _config: CodexConfig) -> None:
            pass

        async def thread_start(self, **_kwargs: object) -> FakeThread:
            return FakeThread()

        async def close(self) -> None:
            return None

    monkeypatch.setattr("agent_world.invocation.AsyncCodex", FakeAsyncCodex)

    result = backend.invoke_json(
        work="candidate_build",
        skill_name="engineer-environment-codegen",
        workspace=tmp_path / "workspace",
        instruction="Write the requested files.",
        writable=True,
        require_json=False,
    )

    assert result == InvocationResult(
        {}, route.model, None, runtime_skill_digest("engineer-environment-codegen")
    )


def test_codex_agent_does_not_fallback_after_a_non_retryable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = AgentRoute("primary", "http://primary.invalid/v1", "PRIMARY_KEY")
    fallback = AgentRoute("fallback", "http://fallback.invalid/v1", "FALLBACK_KEY")
    backend = CodexAgentBackend(primary, fallback)
    calls: list[AgentRoute] = []

    def fail_non_retryable(route: AgentRoute, *_: object) -> InvocationResult:
        calls.append(route)
        raise InvocationError(SafeFailure("agent_rejected", "rejected"))

    monkeypatch.setattr(backend, "_call", fail_non_retryable)

    with pytest.raises(InvocationError, match="agent_rejected"):
        backend.invoke_json(
            work="researcher",
            skill_name="research-world-evidence",
            workspace=tmp_path / "workspace",
            instruction="Return a safe test object.",
        )

    assert calls == [primary]


def test_codex_agent_falls_back_once_after_a_retryable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = AgentRoute("primary", "http://primary.invalid/v1", "PRIMARY_KEY")
    fallback = AgentRoute("fallback", "http://fallback.invalid/v1", "FALLBACK_KEY")
    backend = CodexAgentBackend(primary, fallback)
    calls: list[AgentRoute] = []

    def fail_then_succeed(route: AgentRoute, *_: object) -> InvocationResult:
        calls.append(route)
        if route == primary:
            raise InvocationError(SafeFailure("agent_execution_failure", "error", True))
        return InvocationResult({"ok": True}, fallback.model)

    monkeypatch.setattr(backend, "_call", fail_then_succeed)

    result = backend.invoke_json(
        work="researcher",
        skill_name="research-world-evidence",
        workspace=tmp_path / "workspace",
        instruction="Return a safe test object.",
    )

    assert result == InvocationResult({"ok": True}, fallback.model)
    assert calls == [primary, fallback]


def test_bundled_sdk_initializes_complete_private_provider_mapping_without_provider_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    route = AgentRoute(
        model="agent-test-model",
        base_url="http://127.0.0.1:9/v1",
        api_key_env="NO_CREDENTIAL_FOR_PARSE_TEST",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.delenv(route.api_key_env, raising=False)
    config = CodexConfig(
        config_overrides=_private_provider_overrides(route),
        cwd=str(workspace),
        env={"CODEX_HOME": str(codex_home)},
    )

    async def initialize_only() -> None:
        async with AsyncCodex(config):
            pass

    asyncio.run(initialize_only())

    persisted = b"".join(path.read_bytes() for path in tmp_path.rglob("*") if path.is_file())
    assert route.base_url.encode() not in persisted
    assert b"NO_CREDENTIAL_FOR_PARSE_TEST" not in persisted

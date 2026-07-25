from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.control.telemetry import TelemetryStore
from agent_world.invocation import (
    DirectLlmBackend,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
    RoutedInvocationBackend,
)


class _FakeResponses:
    def __init__(self, *, output_text: str | None = None) -> None:
        self.requests: list[dict[str, object]] = []
        self.output_text = output_text or json.dumps(
            {"artifact_json": json.dumps({"title": "Hotel booking"})}
        )

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return SimpleNamespace(
            status="completed",
            output_text=self.output_text,
            usage=SimpleNamespace(
                input_tokens=13,
                input_tokens_details=SimpleNamespace(cached_tokens=2),
                output_tokens=5,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3),
                total_tokens=18,
            ),
        )


class _FakeClient:
    def __init__(self, *, output_text: str | None = None) -> None:
        self.responses = _FakeResponses(output_text=output_text)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _RecordingBackend:
    def __init__(self, name: str, revisions: tuple[str, ...]) -> None:
        self.name = name
        self.supported_executor_revision_ids = revisions
        self.requests: list[InvocationRequest] = []
        self.cancelled: list[str] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=None,
            final_text=None,
            structured_output={"backend": self.name},
            usage=None,
            events=(),
            error=None,
            duration_ms=1,
            backend_version=self.name,
        )

    async def cancel(self, invocation_id: str) -> bool:
        self.cancelled.append(invocation_id)
        return self.name == "direct"


def _request(tmp_path: Path) -> tuple[InvocationRequest, str, str]:
    # Values are generated at test runtime, never committed as fixture
    # material. The production contract exposes only their environment names.
    credential = uuid4().hex
    base_url = f"https://{uuid4().hex}.invalid/v1"
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="direct-structured-test-model",
            api_key_environment="OPENAI_API_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
            structured_output_transport="json_envelope",
        ),
        source_environment={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "OPENAI_API_KEY": credential,
            "OPENAI_BASE_URL": base_url,
        },
    )
    profile = provider.resolve(
        role="researcher",
        lineage_id="direct-structured-test",
        workspace=tmp_path / "researcher",
        output_schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="researcher.direct-structured-test",
            role="researcher",
        ),
        rollout_token_limit=333,
    )
    return (
        InvocationRequest(
            invocation_id="direct-structured-test-invocation",
            prompt="Return the title artifact.",
            profile=profile,
            execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
        ),
        credential,
        base_url,
    )


def _tree_contains(root: Path, value: str) -> bool:
    needle = value.encode("utf-8")
    for path in root.rglob("*"):
        if path.is_file() and needle in path.read_bytes():
            return True
    return False


@pytest.mark.asyncio
async def test_direct_backend_uses_responses_json_schema_without_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, credential, base_url = _request(tmp_path)
    client = _FakeClient()
    factory_observations: list[tuple[bool, bool, float, int]] = []

    def client_factory(
        *,
        api_key: str,
        base_url: str,
        timeout: float,
        max_retries: int,
    ) -> _FakeClient:
        factory_observations.append((bool(api_key), bool(base_url), timeout, max_retries))
        return client

    async def unexpected_subprocess(*args: object, **kwargs: object) -> object:
        raise AssertionError("DirectLlmBackend must not create a subprocess")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unexpected_subprocess)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    try:
        result = await DirectLlmBackend(
            client_factory=client_factory,
            telemetry=telemetry,
        ).invoke(request)
    finally:
        telemetry.close()

    assert result.status is InvocationStatus.COMPLETED
    assert result.structured_output == {"title": "Hotel booking"}
    assert result.session is None
    assert result.final_text is None
    assert result.events[0].method == "direct.response.completed"
    assert result.events[0].payload == {"backend": "direct_llm"}
    assert result.usage is not None
    assert result.usage.turn is not None
    assert result.usage.turn.total_tokens == 18
    assert factory_observations == [(True, True, request.profile.limits.timeout_seconds, 0)]
    assert client.closed

    assert len(client.responses.requests) == 1
    provider_request = client.responses.requests[0]
    assert provider_request["model"] == request.profile.model
    assert provider_request["input"] == request.prompt
    assert provider_request["max_output_tokens"] == 333
    assert provider_request["store"] is False
    assert provider_request["reasoning"] == {
        "effort": request.profile.reasoning_effort.value,
    }
    assert "tools" not in provider_request
    assert provider_request["text"] == {
        "format": {
            "type": "json_schema",
            "name": "agent_world_structured_output",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"artifact_json": {"type": "string"}},
                "required": ["artifact_json"],
                "additionalProperties": False,
            },
        }
    }
    with sqlite3.connect(tmp_path / "telemetry" / "telemetry.sqlite") as connection:
        attributes_json = connection.execute(
            "SELECT attributes_json FROM spans WHERE operation = 'agent.invoke'"
        ).fetchone()[0]
    assert json.loads(attributes_json)["backend"] == "direct_llm"
    assert not _tree_contains(tmp_path, credential)
    assert not _tree_contains(tmp_path, base_url)


@pytest.mark.asyncio
async def test_direct_backend_rejects_implicit_agentic_execution(tmp_path: Path) -> None:
    request, _, _ = _request(tmp_path)
    invoked = False

    def client_factory(**_: object) -> object:
        nonlocal invoked
        invoked = True
        raise AssertionError("ineligible Direct request must not construct a client")

    result = await DirectLlmBackend(client_factory=client_factory).invoke(
        replace(request, execution_mode=InvocationExecutionMode.AGENTIC)
    )

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_execution_mode_ineligible"
    assert invoked is False


@pytest.mark.asyncio
async def test_direct_backend_reports_non_json_without_retaining_provider_text(
    tmp_path: Path,
) -> None:
    request, _, _ = _request(tmp_path)
    client = _FakeClient(output_text="not-json")

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_structured_output_invalid_json"
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed


@pytest.mark.asyncio
async def test_direct_backend_reports_invalid_envelope_without_retaining_provider_text(
    tmp_path: Path,
) -> None:
    request, _, _ = _request(tmp_path)
    client = _FakeClient(output_text=json.dumps({"artifact_json": "not-json"}))

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_structured_output_transport_invalid"
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed


@pytest.mark.asyncio
async def test_router_selects_direct_only_for_explicit_one_shot(tmp_path: Path) -> None:
    direct_request, _, _ = _request(tmp_path)
    agentic_request = replace(
        direct_request,
        invocation_id="direct-structured-test-agentic",
        execution_mode=InvocationExecutionMode.AGENTIC,
    )
    codex = _RecordingBackend("codex", ("framework.executor.v1", "codex.v2"))
    direct = _RecordingBackend("direct", ("framework.executor.v1",))
    backend = RoutedInvocationBackend(
        codex_backend=codex,
        direct_backend=direct,
        max_concurrent_invocations=1,
    )

    direct_result = await backend.invoke(direct_request)
    agentic_result = await backend.invoke(agentic_request)

    assert direct_result.backend_version == "direct"
    assert agentic_result.backend_version == "codex"
    assert direct.requests == [direct_request]
    assert codex.requests == [agentic_request]
    assert backend.supported_executor_revision_ids == ("framework.executor.v1", "codex.v2")
    assert await backend.cancel("direct-structured-test-cancel")
    assert codex.cancelled == ["direct-structured-test-cancel"]
    assert direct.cancelled == ["direct-structured-test-cancel"]

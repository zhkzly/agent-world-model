from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.control.telemetry import TelemetryStore
from agent_world.designer.models import TrainingSemanticSourceDraft
from agent_world.invocation import (
    DirectLlmBackend,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
    RoutedInvocationBackend,
)
from agent_world.invocation.codex_sdk import _transport_output_schema


class _FakeResponses:
    def __init__(
        self,
        *,
        output_text: str | None = None,
        status: str = "completed",
        incomplete_reason: str | None = None,
    ) -> None:
        self.requests: list[dict[str, object]] = []
        self.status = status
        self.incomplete_reason = incomplete_reason
        self.output_text = output_text or json.dumps(
            {"artifact_json": json.dumps({"title": "Hotel booking"})}
        )

    def _response(self) -> SimpleNamespace:
        return SimpleNamespace(
            status=self.status,
            incomplete_details=(
                SimpleNamespace(reason=self.incomplete_reason)
                if self.incomplete_reason is not None
                else None
            ),
            output_text=self.output_text,
            usage=SimpleNamespace(
                input_tokens=13,
                input_tokens_details=SimpleNamespace(cached_tokens=2),
                output_tokens=5,
                output_tokens_details=SimpleNamespace(reasoning_tokens=3),
                total_tokens=18,
            ),
        )

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return _FakeResponseStream(self._response())


class _FakeResponseStream:
    """Small async stream that mirrors the Direct Responses terminal shape."""

    def __init__(self, response: SimpleNamespace) -> None:
        self._events = iter(
            (
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.output_text.delta", delta=response.output_text),
                SimpleNamespace(type=f"response.{response.status}", response=response),
            )
        )

    def __aiter__(self) -> _FakeResponseStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _TerminalEventStream:
    """A Direct stream with an explicit Provider terminal event."""

    def __init__(self, *events: SimpleNamespace) -> None:
        self._events = iter(events)

    def __aiter__(self) -> _TerminalEventStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _TerminalEventResponses(_FakeResponses):
    def __init__(self, *events: SimpleNamespace) -> None:
        super().__init__()
        self._events = events

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return _TerminalEventStream(*self._events)


class _FakeClient:
    def __init__(
        self,
        *,
        output_text: str | None = None,
        responses: _FakeResponses | None = None,
    ) -> None:
        self.responses = responses or _FakeResponses(output_text=output_text)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _BlockingResponses(_FakeResponses):
    """Block after the adapter has dispatched one SDK request."""

    def __init__(self) -> None:
        super().__init__()
        self.request_dispatched = asyncio.Event()
        self.release_response = asyncio.Event()

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        self.request_dispatched.set()
        await self.release_response.wait()
        return _FakeResponseStream(self._response())


class _StallingResponseStream:
    """Emit Provider lifecycle events, then wait without a terminal event."""

    def __init__(self, response: SimpleNamespace) -> None:
        self._events = iter(
            (
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.in_progress"),
            )
        )
        self.waiting_for_next_event = asyncio.Event()
        self.release = asyncio.Event()
        self._response = response

    def __aiter__(self) -> _StallingResponseStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        try:
            return next(self._events)
        except StopIteration:
            self.waiting_for_next_event.set()
            await self.release.wait()
            raise StopAsyncIteration from None


class _StallingStreamResponses(_FakeResponses):
    def __init__(self) -> None:
        super().__init__()
        self.stream = _StallingResponseStream(self._response())

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return self.stream


class _FirstEventStallingResponseStream:
    """Wait before the first Provider event, then complete normally."""

    def __init__(self, response: SimpleNamespace) -> None:
        self._events = iter(
            (
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.output_text.delta", delta=response.output_text),
                SimpleNamespace(type="response.completed", response=response),
            )
        )
        self.waiting_for_first_event = asyncio.Event()
        self.release = asyncio.Event()
        self._first_event_pending = True

    def __aiter__(self) -> _FirstEventStallingResponseStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if self._first_event_pending:
            self._first_event_pending = False
            self.waiting_for_first_event.set()
            await self.release.wait()
        try:
            return next(self._events)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FirstEventStallingStreamResponses(_FakeResponses):
    def __init__(self) -> None:
        super().__init__()
        self.stream = _FirstEventStallingResponseStream(self._response())

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        return self.stream


class _FakeDirectProviderError(Exception):
    """Mimic the closed attributes exposed by an OpenAI status exception."""

    def __init__(self, *, status_code: int, body: object) -> None:
        super().__init__("provider request rejected")
        self.status_code = status_code
        self.body = body


class _RejectingResponses(_FakeResponses):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        raise self.error


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


def _request(
    tmp_path: Path,
    *,
    transport: str = "json_envelope",
) -> tuple[InvocationRequest, str, str]:
    # Values are generated at test runtime, never committed as fixture
    # material. The production contract exposes only their environment names.
    credential = uuid4().hex
    base_url = f"https://{uuid4().hex}.invalid/v1"
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="direct-structured-test-model",
            api_key_environment="OPENAI_API_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
            structured_output_transport=transport,
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


def test_provider_schema_preserves_task_curriculum_required_rule_lists() -> None:
    """A direct route can enforce the logical curriculum shape, not just an envelope."""

    logical_schema = TrainingSemanticSourceDraft.model_json_schema(mode="validation")
    provider_schema = _transport_output_schema(logical_schema, transport="provider_schema")

    definitions = provider_schema["$defs"]
    assert isinstance(definitions, dict)
    task_schema = definitions["TaskRequirementSourceDraft"]
    assert isinstance(task_schema, dict)
    required = task_schema["required"]
    assert isinstance(required, list)
    assert {
        "initial_state_constraints",
        "success_conditions",
        "failure_conditions",
        "terminal_conditions",
    }.issubset(required)


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
    instructions = provider_request["instructions"]
    assert isinstance(instructions, str)
    assert "Logical structured output contract" in instructions
    assert "artifact_json" in instructions
    logical_schema = instructions.split("<logical_output_schema_json>\n", 1)[1].split(
        "\n</logical_output_schema_json>",
        1,
    )[0]
    assert json.loads(logical_schema) == request.profile.output_schema
    assert provider_request["max_output_tokens"] == 333
    assert provider_request["store"] is False
    assert provider_request["stream"] is True
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
        metric_rows = connection.execute(
            "SELECT name, SUM(value_integer) FROM metrics "
            "WHERE name IN (?, ?, ?) GROUP BY name ORDER BY name",
            (
                "invocation.events.observed_delta",
                "invocation.activity.agent_message_event_delta",
                "invocation.activity.other_event_delta",
            ),
        ).fetchall()
    assert json.loads(attributes_json)["backend"] == "direct_llm"
    assert metric_rows == [
        ("invocation.activity.agent_message_event_delta", 1),
        ("invocation.activity.other_event_delta", 2),
        ("invocation.events.observed_delta", 3),
    ]
    assert not _tree_contains(tmp_path, credential)
    assert not _tree_contains(tmp_path, base_url)


@pytest.mark.asyncio
async def test_direct_backend_uses_direct_json_object_without_an_inner_envelope(
    tmp_path: Path,
) -> None:
    """A compatible Direct route can remove fragile double serialization."""

    request, _, _ = _request(tmp_path, transport="json_object")
    client = _FakeClient(output_text=json.dumps({"title": "Hotel booking"}))

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.COMPLETED
    assert result.structured_output == {"title": "Hotel booking"}
    assert client.responses.requests[0]["text"] == {"format": {"type": "json_object"}}
    instructions = client.responses.requests[0]["instructions"]
    assert isinstance(instructions, str)
    assert "Return one direct JSON value satisfying the logical schema below." in instructions
    assert "<logical_output_schema_json>" in instructions


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
    provider_output_canary = f"provider-output-{uuid4().hex}"
    output_text = f"Gateway diagnostic: {provider_output_canary}"
    client = _FakeClient(output_text=output_text)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    try:
        result = await DirectLlmBackend(
            client_factory=lambda **_: client,
            telemetry=telemetry,
        ).invoke(request)
    finally:
        telemetry.close()

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_structured_output_invalid_json"
    assert result.error.retryable is False
    assert result.error.details == {
        "response_shape": "non_json",
        "parse_failure": "syntax",
        "parse_offset": 0,
        "response_characters": len(output_text),
    }
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_output_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_output_canary)


@pytest.mark.asyncio
async def test_direct_backend_reports_invalid_envelope_without_retaining_provider_text(
    tmp_path: Path,
) -> None:
    request, _, _ = _request(tmp_path)
    provider_output_canary = f"provider-output-{uuid4().hex}"
    encoded = f"Gateway diagnostic: {provider_output_canary}"
    client = _FakeClient(output_text=json.dumps({"artifact_json": encoded}))

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_structured_output_transport_invalid"
    assert result.error.retryable is False
    assert result.error.details == {
        "transport": "json_envelope",
        "envelope_shape": "artifact_json_string",
        "response_shape": "non_json",
        "parse_failure": "syntax",
        "parse_offset": 0,
        "response_characters": len(encoded),
    }
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_output_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_output_canary)


@pytest.mark.asyncio
async def test_direct_backend_projects_safe_rejected_schema_fingerprint(
    tmp_path: Path,
) -> None:
    """A pre-model 400 must name its safe request component, never provider prose."""

    request, _, _ = _request(tmp_path)
    provider_message_canary = f"provider-message-{uuid4().hex}"
    error = _FakeDirectProviderError(
        status_code=400,
        body={
            "message": provider_message_canary,
            "type": "invalid_request_error",
            "code": "invalid_json_schema",
            "param": "text.format.schema",
        },
    )
    client = _FakeClient(responses=_RejectingResponses(error))

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_invalid_request"
    assert result.error.retryable is False
    assert result.error.details == {
        "http_status": 400,
        "provider_error_shape": "object",
        "provider_error_type": "invalid_request",
        "provider_error_code": "structured_output_schema",
        "provider_error_param": "structured_output_schema",
    }
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_message_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_message_canary)


@pytest.mark.asyncio
async def test_direct_backend_projects_safe_stream_error_as_retryable_unavailable(
    tmp_path: Path,
) -> None:
    """A top-level streamed error retains its closed retry category, never prose."""

    request, _, _ = _request(tmp_path)
    provider_message_canary = f"provider-message-{uuid4().hex}"
    provider_param_canary = f"provider-param-{uuid4().hex}"
    responses = _TerminalEventResponses(
        SimpleNamespace(type="response.created"),
        SimpleNamespace(
            type="error",
            code="server_error",
            param=provider_param_canary,
            message=provider_message_canary,
        ),
    )
    client = _FakeClient(responses=responses)

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_provider_unavailable"
    assert result.error.retryable is True
    assert result.error.details == {
        "provider_error_shape": "object",
        "provider_error_type": "absent",
        "provider_error_code": "provider_unavailable",
        "provider_error_param": "other",
    }
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_message_canary not in repr(result)
    assert provider_param_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_message_canary)
    assert not _tree_contains(tmp_path, provider_param_canary)


@pytest.mark.asyncio
async def test_direct_backend_projects_safe_response_failed_error_as_rate_limited(
    tmp_path: Path,
) -> None:
    """A response.failed error follows the exact same terminal classifier."""

    request, _, _ = _request(tmp_path)
    provider_message_canary = f"provider-message-{uuid4().hex}"
    response = _FakeResponses(status="failed")._response()
    response.error = SimpleNamespace(
        code="rate_limit_exceeded",
        message=provider_message_canary,
    )
    responses = _TerminalEventResponses(
        SimpleNamespace(type="response.created"),
        SimpleNamespace(type="response.failed", response=response),
    )
    client = _FakeClient(responses=responses)

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_rate_limited"
    assert result.error.retryable is True
    assert result.error.details == {
        "provider_error_shape": "object",
        "provider_error_type": "absent",
        "provider_error_code": "rate_limited",
        "provider_error_param": "absent",
    }
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_message_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_message_canary)


@pytest.mark.asyncio
async def test_direct_backend_does_not_mark_dispatch_as_provider_progress(
    tmp_path: Path,
) -> None:
    """Request dispatch alone is not evidence that the Provider is progressing."""

    request, _, _ = _request(tmp_path)
    responses = _BlockingResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    task = asyncio.create_task(
        DirectLlmBackend(client_factory=lambda **_: client, telemetry=telemetry).invoke(request)
    )
    try:
        await asyncio.wait_for(responses.request_dispatched.wait(), timeout=1)
        with sqlite3.connect(tmp_path / "telemetry" / "telemetry.sqlite") as connection:
            row = connection.execute(
                "SELECT status, first_progress_at_ns, ended_at_ns, "
                "last_heartbeat_at_ns, last_heartbeat_phase "
                "FROM spans WHERE operation = 'agent.invoke'"
            ).fetchone()
        assert row is not None
        assert row[0] == "running"
        assert row[1] is None
        assert row[2] is None
        assert row[3] is not None
        assert row[4] == "direct_request_dispatched"
    finally:
        responses.release_response.set()
        await task
        telemetry.close()


@pytest.mark.asyncio
async def test_direct_backend_does_not_apply_idle_liveness_before_first_provider_event(
    tmp_path: Path,
) -> None:
    """The post-progress idle bound must not fire before any Provider event exists.

    Boundary: DirectLlmBackend -> stream that withholds its first event.
    The idle interval answers "did a live stream go quiet mid-response"; with
    zero events there is no progress to have lost, so first-event liveness (a
    separate, explicitly disabled bound here) is the only thing entitled to end
    this wait.  Failing this test means an idle timeout is being charged for
    latency it cannot observe.
    """

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(
                request.profile.limits,
                direct_stream_idle_timeout_seconds=0.02,
                direct_first_event_timeout_seconds=None,
            ),
        ),
    )
    responses = _FirstEventStallingStreamResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    task = asyncio.create_task(
        DirectLlmBackend(
            client_factory=lambda **_: client,
            telemetry=telemetry,
            liveness_heartbeat_seconds=0.005,
        ).invoke(request)
    )
    try:
        await asyncio.wait_for(responses.stream.waiting_for_first_event.wait(), timeout=1)
        await asyncio.sleep(0.04)
        assert not task.done()
    finally:
        responses.stream.release.set()
        result = await asyncio.wait_for(task, timeout=1)
        telemetry.close()

    assert result.status is InvocationStatus.COMPLETED
    assert result.error is None
    assert client.closed


@pytest.mark.asyncio
async def test_direct_backend_terminalizes_a_stream_that_never_emits_a_first_event(
    tmp_path: Path,
) -> None:
    """An opened stream that never speaks must become a retryable terminal.

    Boundary: DirectLlmBackend -> real stream object that yields nothing.
    Frozen input: one resolved tool-free structured profile whose declared
    logical wall is far larger than its first-event bound -- the exact shape of
    the real run where a Direct attempt held a node for its full 8-hour wall
    with ``provider_progress_count = 0`` and no terminal any policy could act
    on.  The one poisoned condition is time-to-first-event.

    Expected: FAILED / ``direct_no_first_provider_event`` / retryable, carrying
    the safe waiting phase and a zero event count.  A ``direct_timeout`` here
    would mean the declared wall was spent and would send attribution toward
    model latency instead of transport liveness.
    """

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(
                request.profile.limits,
                timeout_seconds=30.0,
                direct_stream_idle_timeout_seconds=300.0,
                direct_first_event_timeout_seconds=0.05,
            ),
        ),
    )
    responses = _FirstEventStallingStreamResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    started = time.monotonic()
    try:
        result = await asyncio.wait_for(
            DirectLlmBackend(
                client_factory=lambda **_: client,
                telemetry=telemetry,
                liveness_heartbeat_seconds=0.01,
            ).invoke(request),
            timeout=5,
        )
    finally:
        responses.stream.release.set()
        telemetry.close()
    elapsed = time.monotonic() - started

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_no_first_provider_event"
    assert result.error.retryable is True
    assert result.error.details == {
        "waiting_phase": "direct_awaiting_stream_event",
        "first_event_timeout_seconds": 0.05,
        "observed_provider_event_count": 0,
    }
    # The bound, not the declared wall, ended this attempt.
    assert elapsed < 5
    assert client.closed


@pytest.mark.asyncio
async def test_direct_backend_terminalizes_a_request_that_never_returns_a_stream(
    tmp_path: Path,
) -> None:
    """The first-event bound also covers the wait for the stream itself.

    Boundary: DirectLlmBackend -> ``responses.create`` that never returns.
    The two waits before a first event (opening the stream, reading from it)
    share one deadline, so a request that never gets a stream is bounded too --
    and its safe waiting phase must say ``direct_awaiting_response`` so the next
    read distinguishes "request never left" from "stream opened and stayed
    silent".
    """

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(
                request.profile.limits,
                timeout_seconds=30.0,
                direct_first_event_timeout_seconds=0.05,
            ),
        ),
    )
    responses = _BlockingResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    try:
        result = await asyncio.wait_for(
            DirectLlmBackend(
                client_factory=lambda **_: client,
                telemetry=telemetry,
                liveness_heartbeat_seconds=0.01,
            ).invoke(request),
            timeout=5,
        )
    finally:
        responses.release_response.set()
        telemetry.close()

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_no_first_provider_event"
    assert result.error.retryable is True
    assert result.error.details["waiting_phase"] == "direct_awaiting_response"


@pytest.mark.asyncio
async def test_direct_first_event_bound_does_not_curtail_a_slow_but_live_stream(
    tmp_path: Path,
) -> None:
    """One real Provider event must retire the first-event bound entirely.

    Boundary: DirectLlmBackend -> stream that emits events, then stalls longer
    than the first-event bound before completing.  This is the guard against
    the bound degenerating into a short death clock on model reasoning: once the
    transport has proven itself, only the (much larger) idle interval and the
    declared wall may end the attempt.
    """

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(
                request.profile.limits,
                direct_stream_idle_timeout_seconds=None,
                direct_first_event_timeout_seconds=0.02,
            ),
        ),
    )
    responses = _StallingStreamResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    task = asyncio.create_task(
        DirectLlmBackend(
            client_factory=lambda **_: client,
            telemetry=telemetry,
            liveness_heartbeat_seconds=0.005,
        ).invoke(request)
    )
    try:
        await asyncio.wait_for(responses.stream.waiting_for_next_event.wait(), timeout=1)
        # Well past the first-event bound; real events already retired it.
        await asyncio.sleep(0.08)
        assert not task.done()
    finally:
        responses.stream.release.set()
        result = await asyncio.wait_for(task, timeout=1)
        telemetry.close()

    assert result.error is not None
    assert result.error.code != "direct_no_first_provider_event"


@pytest.mark.asyncio
async def test_direct_backend_records_local_waiting_without_faking_provider_progress(
    tmp_path: Path,
) -> None:
    """Exercise Direct adapter -> live telemetry while a stream stays open."""

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(request.profile.limits, direct_stream_idle_timeout_seconds=None),
        ),
    )
    responses = _StallingStreamResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    task = asyncio.create_task(
        DirectLlmBackend(
            client_factory=lambda **_: client,
            telemetry=telemetry,
            liveness_heartbeat_seconds=0.01,
        ).invoke(request)
    )
    try:
        await asyncio.wait_for(responses.stream.waiting_for_next_event.wait(), timeout=1)
        await asyncio.sleep(0.03)
        with sqlite3.connect(tmp_path / "telemetry" / "telemetry.sqlite") as connection:
            row = connection.execute(
                "SELECT status, first_progress_at_ns, last_progress_at_ns, "
                "last_heartbeat_at_ns, last_heartbeat_phase "
                "FROM spans WHERE operation = 'agent.invoke'"
            ).fetchone()
        assert row is not None
        assert row[0] == "running"
        assert row[1] is not None
        assert row[2] is not None
        assert row[3] is not None
        assert row[4] == "direct_awaiting_stream_event"
    finally:
        responses.stream.release.set()
        result = await task
        telemetry.close()

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_stream_terminal_missing"


@pytest.mark.asyncio
async def test_direct_backend_terminalizes_a_started_silent_stream_with_safe_liveness_evidence(
    tmp_path: Path,
) -> None:
    """A post-progress stream stall is a typed transport terminal, not a semantic timeout."""

    request, _, _ = _request(tmp_path)
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=replace(
                request.profile.limits,
                direct_stream_idle_timeout_seconds=0.02,
            ),
        ),
    )
    responses = _StallingStreamResponses()
    client = _FakeClient(responses=responses)
    telemetry = TelemetryStore(tmp_path / "telemetry")
    try:
        result = await asyncio.wait_for(
            DirectLlmBackend(
                client_factory=lambda **_: client,
                telemetry=telemetry,
                liveness_heartbeat_seconds=0.005,
            ).invoke(request),
            timeout=1,
        )
        with sqlite3.connect(tmp_path / "telemetry" / "telemetry.sqlite") as connection:
            row = connection.execute(
                "SELECT status, error_code, first_progress_at_ns, last_progress_at_ns, "
                "last_heartbeat_at_ns, last_heartbeat_phase, ended_at_ns "
                "FROM spans WHERE operation = 'agent.invoke'"
            ).fetchone()
    finally:
        telemetry.close()

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_provider_stream_stalled"
    assert result.error.retryable is True
    assert result.error.details == {
        "waiting_phase": "direct_awaiting_stream_event",
        "idle_timeout_seconds": 0.02,
        "observed_provider_event_count": 2,
    }
    assert client.closed
    assert row is not None
    assert row[0] == "failed"
    assert row[1] == "direct_provider_stream_stalled"
    assert row[2] is not None
    assert row[3] is not None
    assert row[4] is not None
    assert row[5] == "direct_awaiting_stream_event"
    assert row[6] is not None


@pytest.mark.asyncio
async def test_direct_backend_reports_output_limit_without_retaining_provider_text(
    tmp_path: Path,
) -> None:
    """A provider output ceiling is safe feedback, not a semantic sample."""

    request, _, _ = _request(tmp_path)
    provider_output_canary = f"provider-output-{uuid4().hex}"
    client = _FakeClient(
        responses=_FakeResponses(
            output_text=provider_output_canary,
            status="incomplete",
            incomplete_reason="max_output_tokens",
        )
    )

    result = await DirectLlmBackend(client_factory=lambda **_: client).invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "direct_output_limit"
    assert result.error.retryable is False
    assert result.error.details == {
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
        "configured_max_output_tokens": 333,
    }
    assert result.usage is not None and result.usage.turn is not None
    assert result.usage.turn.total_tokens == 18
    assert result.final_text is None
    assert result.structured_output is None
    assert client.closed
    assert provider_output_canary not in repr(result)
    assert not _tree_contains(tmp_path, provider_output_canary)


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

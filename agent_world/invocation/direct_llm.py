"""One-shot structured responses through the official OpenAI Python SDK.

This backend is deliberately narrower than :class:`CodexSdkBackend`: it has no
tool surface, no Codex thread, and no continuation support.  It remains behind
``InvocationBackend`` so budgets, telemetry, redaction, and terminal evidence
stay at the same framework boundary as agentic turns.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import json
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_world.control.telemetry import TelemetryStore, WorkSpan

from .codex_sdk import _decode_provider_json_ir, _provider_output_schema
from .contracts import (
    InvocationError,
    InvocationEvent,
    InvocationExecutionMode,
    InvocationLifecyclePhase,
    InvocationLifecycleSupervision,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    JsonObject,
    TokenBreakdown,
    json_compatible,
)
from .liveness import ProviderFirstEventBudget
from .profiles import ProfileResolutionError, verify_resolved_profile
from .redaction import Redactor
from .structured_diagnostics import (
    advisory_provider_unavailable,
    direct_invalid_json_details,
    direct_no_first_provider_event_details,
    direct_output_limit_details,
    direct_provider_exception_details,
    direct_provider_response_error_details,
    direct_provider_stream_stalled_details,
)

_DIRECT_EVENT_METHOD = "direct.response.completed"
_DIRECT_STREAM_EVENT_METHOD = "direct.response.stream.event"
_DIRECT_SCHEMA_NAME = "agent_world_structured_output"
_DIRECT_LIVENESS_HEARTBEAT_SECONDS = 30.0


class _DirectStreamIdleTimeout(TimeoutError):
    """One started Direct stream stopped yielding Provider events."""

    def __init__(self, *, idle_timeout_seconds: float) -> None:
        self.idle_timeout_seconds = idle_timeout_seconds
        super().__init__("Direct Provider stream stopped yielding events")


class _DirectFirstEventTimeout(TimeoutError):
    """A Direct request never produced its first Provider event.

    This is a transport-liveness fact, not a statement about model latency: no
    Provider event has been observed at all, so nothing distinguishes a silent
    socket from a dropped one.  Without it, a stream that opens and never speaks
    consumed the entire declared logical wall and produced no retryable
    terminal, so policy could neither retry nor fall back.
    """

    def __init__(self, *, first_event_timeout_seconds: float, phase: str) -> None:
        self.first_event_timeout_seconds = first_event_timeout_seconds
        self.phase = phase
        super().__init__("Direct Provider produced no first event")


class DirectLlmBackend:
    """Execute one explicit, tool-free structured Responses API request.

    ``client_factory`` is an internal seam for deterministic tests.  Production
    construction leaves it unset and imports ``AsyncOpenAI`` only in this
    adapter, never in pipeline code.
    """

    supported_executor_revision_ids = ("framework.executor.v1",)

    def __init__(
        self,
        *,
        max_concurrent_invocations: int = 1,
        telemetry: TelemetryStore | None = None,
        client_factory: Callable[..., Any] | None = None,
        liveness_heartbeat_seconds: float = _DIRECT_LIVENESS_HEARTBEAT_SECONDS,
    ) -> None:
        if not 1 <= max_concurrent_invocations <= 32:
            raise ValueError("max_concurrent_invocations must be between 1 and 32")
        if liveness_heartbeat_seconds <= 0:
            raise ValueError("liveness_heartbeat_seconds must be positive")
        self._capacity = asyncio.Semaphore(max_concurrent_invocations)
        self._lock = asyncio.Lock()
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._telemetry = telemetry
        self._telemetry_failures = 0
        self._client_close_failures = 0
        self._client_factory = client_factory or _default_client_factory
        self._liveness_heartbeat_seconds = liveness_heartbeat_seconds

    @property
    def telemetry_failures(self) -> int:
        return self._telemetry_failures

    @property
    def client_close_failures(self) -> int:
        """Return safe cleanup failures that did not alter an HTTP result."""

        return self._client_close_failures

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        """Run one direct response, retaining no transcript or provider payload."""

        _emit_lifecycle(request, InvocationLifecyclePhase.QUEUED)
        telemetry_span: WorkSpan | None = None
        progress_disabled = False
        queue_started = time.perf_counter_ns()
        queue_duration_ms = 0.0
        if self._telemetry is not None:
            try:
                telemetry_span = self._telemetry.start_invocation(
                    request,
                    execution_backend="direct_llm",
                )
            except Exception:
                self._telemetry_failures += 1

        def mark_provider_progress(
            method: str,
            event_payload: Mapping[str, Any] | None = None,
        ) -> None:
            _emit_provider_progress(request, "direct_provider_event")
            nonlocal progress_disabled
            if telemetry_span is None or progress_disabled:
                return
            try:
                telemetry_span.progress(method, event_payload)
            except Exception:
                self._telemetry_failures += 1
                progress_disabled = True

        def mark_local_liveness(phase: str) -> None:
            _emit_lifecycle(request, _direct_lifecycle_phase(phase))
            nonlocal progress_disabled
            if telemetry_span is None or progress_disabled:
                return
            try:
                telemetry_span.heartbeat(phase)
            except Exception:
                self._telemetry_failures += 1
                progress_disabled = True

        task = asyncio.current_task()
        registered = False
        try:
            if task is None:  # pragma: no cover - asyncio always exposes the invoking Task
                result = _local_failure(
                    request,
                    status=InvocationStatus.FAILED,
                    code="direct_task_unavailable",
                    started=time.monotonic(),
                )
            else:
                async with self._lock:
                    duplicate = request.invocation_id in self._active
                    if not duplicate:
                        self._active[request.invocation_id] = task
                        registered = True
                if duplicate:
                    result = _local_failure(
                        request,
                        status=InvocationStatus.FAILED,
                        code="duplicate_invocation_id",
                        started=time.monotonic(),
                    )
                else:
                    async with self._capacity:
                        _emit_lifecycle(request, InvocationLifecyclePhase.ADMITTED)
                        queue_duration_ms = (time.perf_counter_ns() - queue_started) / 1_000_000
                        result = await self._invoke_once(
                            request,
                            on_first_progress=mark_provider_progress,
                            on_liveness=mark_local_liveness,
                        )
        except asyncio.CancelledError:
            if telemetry_span is not None:
                try:
                    telemetry_span.finish(status="cancelled", error_code="cancelled")
                except Exception:
                    self._telemetry_failures += 1
            raise
        except Exception as exc:
            if telemetry_span is not None and not telemetry_span.closed:
                try:
                    telemetry_span.finish(status="error", error_code=type(exc).__name__)
                except Exception:
                    self._telemetry_failures += 1
            raise
        finally:
            if registered:
                async with self._lock:
                    if self._active.get(request.invocation_id) is task:
                        self._active.pop(request.invocation_id, None)

        if self._telemetry is not None and telemetry_span is not None:
            try:
                self._telemetry.finish_invocation(
                    telemetry_span,
                    request,
                    result,
                    queue_duration_ms=queue_duration_ms,
                )
            except Exception:
                self._telemetry_failures += 1
        return result

    async def cancel(self, invocation_id: str) -> bool:
        """Cancel a live direct request; the caller owns terminal settlement."""

        async with self._lock:
            task = self._active.get(invocation_id)
            if task is None:
                return False
            task.cancel()
            return True

    async def _invoke_once(
        self,
        request: InvocationRequest,
        *,
        on_first_progress: Callable[[str, Mapping[str, Any] | None], None] | None,
        on_liveness: Callable[[str], None] | None,
    ) -> InvocationResult:
        started = time.monotonic()
        profile = request.profile
        redactor = Redactor.from_values(profile.secret_values)
        # Route eligibility is a declaration-level fact. Classify a Direct
        # request that carries an Agent bundle or hidden instruction before
        # physical profile verification: otherwise a malformed bundle obscures
        # the actual Direct-vs-Agent error as generic profile integrity. A
        # request that passes this closed gate is still fully verified before
        # any credential or Provider interaction.
        ineligible = _direct_ineligibility_code(request)
        if ineligible is not None:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code=ineligible,
                started=started,
            )
        _emit_lifecycle(request, InvocationLifecyclePhase.PROFILE_VERIFYING)
        try:
            verify_resolved_profile(profile)
        except ProfileResolutionError:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="profile_integrity_error",
                started=started,
            )
        except OSError:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="profile_io_error",
                started=started,
                retryable=True,
            )
        _emit_lifecycle(request, InvocationLifecyclePhase.PROFILE_VERIFIED)

        assert profile.output_schema is not None
        if profile.rollout_token_limit is None:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_rollout_limit_required",
                started=started,
            )
        authentication_environment = profile.authentication_environment
        base_url_environment = profile.openai_base_url_environment
        if authentication_environment != "OPENAI_API_KEY":
            return _local_failure(
                request,
                status=InvocationStatus.NEEDS_HUMAN,
                code="direct_authentication_configuration_invalid",
                started=started,
            )
        if base_url_environment != "OPENAI_BASE_URL":
            return _local_failure(
                request,
                status=InvocationStatus.NEEDS_HUMAN,
                code="direct_routing_configuration_invalid",
                started=started,
            )
        environment = profile.worker_environment()
        api_key = environment.get(authentication_environment)
        base_url = environment.get(base_url_environment)
        if not api_key:
            return _local_failure(
                request,
                status=InvocationStatus.NEEDS_HUMAN,
                code="authentication_missing",
                started=started,
            )
        if not base_url:
            return _local_failure(
                request,
                status=InvocationStatus.NEEDS_HUMAN,
                code="routing_environment_missing",
                started=started,
            )

        try:
            text_format = _direct_text_format(profile.output_schema)
        except (TypeError, ValueError):
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_output_schema_invalid",
                started=started,
            )

        client = None
        response: Any | None = None
        observed_provider_event_count = 0
        try:
            client = self._client_factory(
                api_key=api_key,
                base_url=base_url,
                timeout=profile.limits.timeout_seconds,
                # Bounded pre-first-event transport retry only.  The SDK retries
                # connection failures / 429 / >=500 with backoff and never
                # resumes a stream that already emitted content, so this smooths
                # an intermittent relay without hiding a turn failure from the
                # Scheduler.  ``0`` restores the prior Scheduler-owns-every-retry
                # policy.  See ``AgentConfig.provider_transport_max_retries``.
                max_retries=profile.limits.provider_transport_max_retries,
            )
            # A request inside the Invocation Control Plane has exactly one
            # parent-side wall supervisor.  Keep this adapter-local wall only
            # for intentionally standalone adapter use; the client transport
            # still has the profile's declared timeout for its own I/O.
            adapter_timeout = (
                None
                if request.lifecycle_supervision is InvocationLifecycleSupervision.CONTROL_PLANE
                else profile.limits.timeout_seconds
            )
            # Time-to-first-Provider-event spans BOTH waits below: opening the
            # stream and reading its first event.  A single shared deadline is
            # what makes "the transport is alive" falsifiable; two independent
            # ones would let a request idle twice as long, and none at all is the
            # defect that let a silent stream consume an 8-hour logical wall.
            first_event_budget = ProviderFirstEventBudget(
                profile.limits.provider_first_event_timeout_seconds
            )
            provider_request: dict[str, Any] = {
                "model": profile.model,
                "input": request.prompt,
                "reasoning": {"effort": profile.reasoning_effort.value},
                "store": False,
                "stream": True,
                "text": {"format": text_format},
            }
            # Do not smuggle the framework rollout budget into the Provider
            # request.  The former is scheduler accounting; the latter is an
            # optional physical cap and is omitted by default.
            if profile.direct_provider_max_output_tokens is not None:
                provider_request["max_output_tokens"] = (
                    profile.direct_provider_max_output_tokens
                )
            async with asyncio.timeout(adapter_timeout):
                if on_liveness is not None:
                    on_liveness("direct_request_dispatched")
                stream = await _await_with_liveness_heartbeats(
                    client.responses.create(**provider_request),
                    heartbeat_seconds=self._liveness_heartbeat_seconds,
                    on_liveness=on_liveness,
                    waiting_phase="direct_awaiting_response",
                    first_event_budget=first_event_budget,
                )
                if on_liveness is not None:
                    on_liveness("direct_stream_opened")
                iterator = aiter(stream)
                while True:
                    try:
                        event = await _await_with_liveness_heartbeats(
                            anext(iterator),
                            heartbeat_seconds=self._liveness_heartbeat_seconds,
                            on_liveness=on_liveness,
                            waiting_phase="direct_awaiting_stream_event",
                            # Two different silences, two different bounds.
                            # After real progress, the profile's idle interval
                            # governs a stream that goes quiet mid-response.
                            # Before any event, the shared first-event budget
                            # bounds transport liveness instead -- neither is a
                            # limit on how long the model may reason.
                            idle_timeout_seconds=(
                                profile.limits.provider_stream_idle_timeout_seconds
                                if observed_provider_event_count > 0
                                else None
                            ),
                            first_event_budget=(
                                None if observed_provider_event_count > 0 else first_event_budget
                            ),
                        )
                    except StopAsyncIteration:
                        break
                    except _DirectFirstEventTimeout as exc:
                        return _local_failure(
                            request,
                            status=InvocationStatus.FAILED,
                            code="direct_no_first_provider_event",
                            started=started,
                            retryable=True,
                            details=direct_no_first_provider_event_details(
                                first_event_timeout_seconds=exc.first_event_timeout_seconds,
                                last_local_phase=exc.phase,
                            ),
                        )
                    except _DirectStreamIdleTimeout as exc:
                        return _local_failure(
                            request,
                            status=InvocationStatus.FAILED,
                            code="direct_provider_stream_stalled",
                            started=started,
                            retryable=True,
                            details=direct_provider_stream_stalled_details(
                                idle_timeout_seconds=exc.idle_timeout_seconds,
                                observed_provider_event_count=observed_provider_event_count,
                            ),
                        )
                    event_type = _direct_stream_event_type(event)
                    observed_provider_event_count += 1
                    if on_first_progress is not None:
                        on_first_progress(
                            _DIRECT_STREAM_EVENT_METHOD,
                            _direct_stream_activity_payload(event_type),
                        )
                    if event_type == "error":
                        status, code, retryable, stream_error_details = (
                            _direct_response_error_terminal(event)
                        )
                        return _local_failure(
                            request,
                            status=status,
                            code=code,
                            started=started,
                            retryable=retryable,
                            details=stream_error_details,
                        )
                    if event_type in {
                        "response.completed",
                        "response.failed",
                        "response.incomplete",
                    }:
                        candidate = getattr(event, "response", None)
                        if candidate is not None:
                            response = candidate
                if response is None:
                    return _local_failure(
                        request,
                        status=InvocationStatus.FAILED,
                        code="direct_stream_terminal_missing",
                        started=started,
                    )
        except _DirectFirstEventTimeout as exc:
            # Raised while opening the stream, before the event loop above could
            # classify it.  It must not collapse into the generic
            # ``direct_timeout`` below: that code says the declared wall was
            # spent, which would send policy looking at model latency instead of
            # the transport that never spoke.
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_no_first_provider_event",
                started=started,
                retryable=True,
                details=direct_no_first_provider_event_details(
                    first_event_timeout_seconds=exc.first_event_timeout_seconds,
                    last_local_phase=exc.phase,
                ),
            )
        except TimeoutError:
            return _local_failure(
                request,
                status=InvocationStatus.TIMED_OUT,
                code="direct_timeout",
                started=started,
                retryable=True,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            status, code, retryable = _direct_exception_status(exc)
            return _local_failure(
                request,
                status=status,
                code=code,
                started=started,
                retryable=retryable,
                details=direct_provider_exception_details(exc),
            )
        finally:
            if client is not None:
                _emit_lifecycle(request, InvocationLifecyclePhase.CLEANUP_RUNNING)
                try:
                    await client.close()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # The HTTP request already has a terminal result. A close
                    # failure must not replace it with an opaque client error.
                    self._client_close_failures += 1
                finally:
                    _emit_lifecycle(request, InvocationLifecyclePhase.CLEANUP_FINISHED)

        response_status = _response_status(response)
        if response_status != "completed":
            status, code, retryable, terminal_details = _response_terminal_status(
                response_status,
                response,
            )
            if code == "direct_output_limit":
                terminal_details = direct_output_limit_details(
                    configured_max_output_tokens=profile.direct_provider_max_output_tokens,
                )
            return _local_failure(
                request,
                status=status,
                code=code,
                started=started,
                retryable=retryable,
                details=terminal_details,
                usage=_response_usage(response),
            )
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_structured_output_missing",
                started=started,
            )
        # A direct model response never becomes durable before its complete
        # text has been screened. Do not redact-and-continue: that could turn a
        # leaked credential into a superficially valid semantic proposal.
        if redactor.text(output_text) != output_text:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_sensitive_output_blocked",
                started=started,
            )
        try:
            decoded_output = json.loads(output_text, parse_constant=_reject_json_constant)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            # Keep this boundary precise without retaining provider text.  A
            # completed compatible-gateway response that is not JSON is a
            # transport failure, not an invitation to coerce prose into a
            # semantic proposal.
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_structured_output_invalid_json",
                started=started,
                details=direct_invalid_json_details(output_text, exc),
            )
        try:
            structured_output = _decode_provider_json_ir(json_compatible(decoded_output))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_structured_output_invalid_json",
                started=started,
                details=direct_invalid_json_details(output_text, exc),
            )

        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=None,
            final_text=None,
            structured_output=structured_output,
            usage=_response_usage(response),
            events=(
                InvocationEvent(
                    sequence=0,
                    method=_DIRECT_EVENT_METHOD,
                    payload={"backend": "direct_llm"},
                ),
            ),
            error=None,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
            backend_version=_openai_sdk_version(),
        )


def _default_client_factory(
    *,
    api_key: str,
    base_url: str,
    timeout: float,
    max_retries: int,
) -> Any:
    """Construct the official async SDK client only inside this adapter."""

    from openai import AsyncOpenAI

    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=max_retries,
    )


async def _await_with_liveness_heartbeats(
    operation: Any,
    *,
    heartbeat_seconds: float,
    on_liveness: Callable[[str], None] | None,
    waiting_phase: str,
    idle_timeout_seconds: float | None = None,
    first_event_budget: ProviderFirstEventBudget | None = None,
) -> Any:
    """Await one SDK boundary while truthfully reporting local waiting.

    Heartbeats are separate from Provider events. They neither reset a timeout
    nor consume retry authority; they only prove that this adapter task remains
    alive awaiting the next SDK result.

    At most one of ``idle_timeout_seconds`` (silence after real progress) and
    ``first_event_budget`` (silence before any progress) applies to a given
    wait; the caller selects which question this wait is answering.
    """

    bounded_first_event = first_event_budget is not None and first_event_budget.enabled
    if on_liveness is None and idle_timeout_seconds is None and not bounded_first_event:
        return await operation
    task = asyncio.ensure_future(operation)
    started = time.monotonic()

    def deadline_remaining() -> float | None:
        """Return seconds left on whichever bound governs this wait."""

        if idle_timeout_seconds is not None:
            return idle_timeout_seconds - (time.monotonic() - started)
        if first_event_budget is not None and first_event_budget.enabled:
            return first_event_budget.remaining()
        return None

    def expired() -> TimeoutError:
        if idle_timeout_seconds is not None:
            return _DirectStreamIdleTimeout(idle_timeout_seconds=idle_timeout_seconds)
        assert first_event_budget is not None
        assert first_event_budget.timeout_seconds is not None
        return _DirectFirstEventTimeout(
            first_event_timeout_seconds=first_event_budget.timeout_seconds,
            phase=waiting_phase,
        )

    try:
        while True:
            wait_seconds: float | None = heartbeat_seconds if on_liveness is not None else None
            remaining = deadline_remaining()
            if remaining is not None:
                if remaining <= 0:
                    raise expired()
                wait_seconds = remaining if wait_seconds is None else min(wait_seconds, remaining)
            done, _ = await asyncio.wait((task,), timeout=wait_seconds)
            if done:
                return task.result()
            remaining = deadline_remaining()
            if remaining is not None and remaining <= 0:
                raise expired()
            if on_liveness is not None:
                on_liveness(waiting_phase)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def _direct_text_format(schema: JsonObject) -> JsonObject:
    """Return the native strict schema contract for one Direct proposal."""

    return {
        "type": "json_schema",
        "name": _DIRECT_SCHEMA_NAME,
        "strict": True,
        "schema": _provider_output_schema(schema),
    }


def _direct_stream_event_type(event: object) -> str:
    """Return a closed safe event label without retaining Provider content."""

    event_type = getattr(event, "type", None)
    if not isinstance(event_type, str):
        return "unknown"
    return event_type


def _direct_stream_activity_payload(event_type: str) -> Mapping[str, Mapping[str, str]]:
    """Project a streamed protocol event to one content-free activity class."""

    if event_type.startswith("response.reasoning"):
        activity = "reasoning"
    elif event_type in {
        "response.created",
        "response.queued",
        "response.in_progress",
    }:
        activity = "lifecycle"
    elif event_type in {
        "response.completed",
        "response.failed",
        "response.incomplete",
        "error",
    }:
        # ``terminal`` would be classified as a shell/command activity by the
        # generic Codex-event classifier. A Direct response completion is only
        # a provider lifecycle fact, never evidence of a command.
        activity = "completion"
    elif event_type == "response.output_text.delta":
        activity = "output"
    else:
        activity = "unclassified"
    return {"item": {"type": f"direct_stream_{activity}"}}


def _direct_lifecycle_phase(phase: str) -> InvocationLifecyclePhase:
    """Map local Direct adapter facts onto the shared closed lifecycle vocabulary."""

    return {
        "direct_request_dispatched": InvocationLifecyclePhase.DIRECT_DISPATCHED,
        "direct_awaiting_response": InvocationLifecyclePhase.DIRECT_AWAITING_RESPONSE,
        "direct_stream_opened": InvocationLifecyclePhase.DIRECT_STREAM_OPENED,
        "direct_awaiting_stream_event": InvocationLifecyclePhase.DIRECT_AWAITING_STREAM_EVENT,
    }.get(phase, InvocationLifecyclePhase.DIRECT_AWAITING_STREAM_EVENT)


def _emit_lifecycle(request: InvocationRequest, phase: InvocationLifecyclePhase) -> None:
    """Keep optional control observation from changing the real adapter outcome."""

    sink = request.lifecycle_sink
    if sink is None:
        return
    try:
        sink.local(phase)
    except Exception:
        return


def _emit_provider_progress(request: InvocationRequest, activity: str) -> None:
    """Record only that a Provider event occurred, never its contents."""

    sink = request.lifecycle_sink
    if sink is None:
        return
    try:
        sink.provider_progress(activity)
    except Exception:
        return


def _direct_ineligibility_code(request: InvocationRequest) -> str | None:
    if request.execution_mode is not InvocationExecutionMode.SINGLE_SHOT_STRUCTURED:
        return "direct_execution_mode_ineligible"
    if request.profile.backend != "direct_llm":
        return "direct_profile_backend_ineligible"
    if request.session is not None:
        return "direct_session_ineligible"
    if request.profile.allowed_builtin_tools:
        return "direct_tools_ineligible"
    if request.profile.skills:
        return "direct_runtime_bundles_ineligible"
    if request.profile.allowed_network_domains or any(
        request.profile.effective_capability_plan.external.to_public_dict().values()
    ):
        return "direct_external_capabilities_ineligible"
    if request.profile.output_schema is None:
        return "direct_schema_required"
    return None


def _response_status(response: Any) -> str:
    status = getattr(response, "status", None)
    return status if isinstance(status, str) else "unknown"


def _response_terminal_status(
    status: str,
    response: Any,
) -> tuple[InvocationStatus, str, bool, JsonObject | None]:
    if status == "cancelled":
        return InvocationStatus.CANCELLED, "direct_response_cancelled", False, None
    reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
    if reason == "max_output_tokens":
        return InvocationStatus.FAILED, "direct_output_limit", False, None
    if reason == "content_filter":
        return InvocationStatus.FAILED, "direct_content_filtered", False, None
    if status == "failed":
        return _direct_response_error_terminal(getattr(response, "error", None))
    return InvocationStatus.FAILED, "direct_response_not_completed", False, None


def _direct_response_error_terminal(
    error: object | None,
) -> tuple[InvocationStatus, str, bool, JsonObject]:
    """Classify both Responses streamed error surfaces through one safe path."""

    details = direct_provider_response_error_details(error)
    provider_code = details.get("provider_error_code")
    if provider_code == "provider_unavailable":
        return InvocationStatus.FAILED, "direct_provider_unavailable", True, details
    if provider_code == "rate_limited":
        return InvocationStatus.FAILED, "direct_rate_limited", True, details
    if provider_code == "other" and advisory_provider_unavailable(details):
        return InvocationStatus.FAILED, "direct_provider_unavailable", True, details
    if provider_code in {"structured_output_schema", "request_parameter", "context_window"}:
        return InvocationStatus.FAILED, "direct_invalid_request", False, details
    if provider_code == "model_route":
        return InvocationStatus.FAILED, "direct_model_unavailable", False, details
    # A failed terminal whose error object is absent or not code-bearing carries
    # no Provider-supplied evidence of a request incompatibility. A genuine
    # request rejection (bad schema/param, context window, model route) always
    # arrives as a code-bearing ``object`` error, already routed above. An
    # empty/``non_object`` failed envelope is instead the signature of a
    # transport- or gateway-degraded terminal (the same class the
    # ``APIConnectionError`` and ``direct_no_first_provider_event`` paths treat
    # as transport-owned). Route it to a bounded retryable provider-unavailable
    # terminal rather than a non-retryable rejection, so one degenerate envelope
    # cannot kill an entire scope with ``no_repair_authority`` when a fresh
    # session or compatible-model fallback would have recovered it.
    if details.get("provider_error_shape") in {"missing", "non_object"}:
        return InvocationStatus.FAILED, "direct_provider_unavailable", True, details
    return InvocationStatus.FAILED, "direct_provider_rejected", False, details


def _direct_exception_status(exc: Exception) -> tuple[InvocationStatus, str, bool]:
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        if status_code in {401, 403}:
            return InvocationStatus.NEEDS_HUMAN, "direct_authentication_failed", False
        if status_code in {400, 413, 422}:
            return InvocationStatus.FAILED, "direct_invalid_request", False
        if status_code == 404:
            return InvocationStatus.FAILED, "direct_model_unavailable", False
        if status_code == 429:
            return InvocationStatus.FAILED, "direct_rate_limited", True
        if status_code in {408, 504}:
            return InvocationStatus.FAILED, "direct_provider_timeout", True
        if 500 <= status_code <= 599:
            return InvocationStatus.FAILED, "direct_provider_unavailable", True
    exception_name = type(exc).__name__
    if exception_name == "APITimeoutError":
        return InvocationStatus.FAILED, "direct_provider_timeout", True
    if exception_name == "APIConnectionError":
        return InvocationStatus.FAILED, "direct_provider_unavailable", True
    return InvocationStatus.FAILED, "direct_provider_rejected", False


def _response_usage(response: Any) -> InvocationUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    return InvocationUsage(
        turn=TokenBreakdown(
            cached_input_tokens=_nonnegative_int(getattr(input_details, "cached_tokens", 0)),
            input_tokens=_nonnegative_int(getattr(usage, "input_tokens", 0)),
            output_tokens=_nonnegative_int(getattr(usage, "output_tokens", 0)),
            reasoning_output_tokens=_nonnegative_int(
                getattr(output_details, "reasoning_tokens", 0)
            ),
            total_tokens=_nonnegative_int(getattr(usage, "total_tokens", 0)),
        )
    )


def _nonnegative_int(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return 0


def _openai_sdk_version() -> str:
    try:
        return f"openai-python-{importlib.metadata.version('openai')}"
    except importlib.metadata.PackageNotFoundError:
        return "openai-python-unknown"


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _local_failure(
    request: InvocationRequest,
    *,
    status: InvocationStatus,
    code: str,
    started: float,
    retryable: bool = False,
    details: JsonObject | None = None,
    usage: InvocationUsage | None = None,
) -> InvocationResult:
    return InvocationResult(
        invocation_id=request.invocation_id,
        status=status,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=usage,
        events=(),
        error=InvocationError(
            code=code,
            message=code,
            retryable=retryable,
            details=details or {},
        ),
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        backend_version=_openai_sdk_version(),
    )


__all__ = ["DirectLlmBackend"]

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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_world.control.telemetry import TelemetryStore, WorkSpan

from .codex_sdk import _decode_json_envelope, _decode_provider_json_ir, _transport_output_schema
from .contracts import (
    InvocationError,
    InvocationEvent,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
    json_compatible,
)
from .profiles import ProfileResolutionError, verify_resolved_profile
from .redaction import Redactor

_DIRECT_EVENT_METHOD = "direct.response.completed"
_DIRECT_SCHEMA_NAME = "agent_world_structured_output"
# Scheduler/RepairLedger owns retry admission and accounting.  The HTTP SDK
# must not make invisible transport retries beneath InvocationBackend.
_DIRECT_SDK_MAX_RETRIES = 0


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
    ) -> None:
        if not 1 <= max_concurrent_invocations <= 32:
            raise ValueError("max_concurrent_invocations must be between 1 and 32")
        self._capacity = asyncio.Semaphore(max_concurrent_invocations)
        self._lock = asyncio.Lock()
        self._active: dict[str, asyncio.Task[Any]] = {}
        self._telemetry = telemetry
        self._telemetry_failures = 0
        self._client_close_failures = 0
        self._client_factory = client_factory or _default_client_factory

    @property
    def telemetry_failures(self) -> int:
        return self._telemetry_failures

    @property
    def client_close_failures(self) -> int:
        """Return safe cleanup failures that did not alter an HTTP result."""

        return self._client_close_failures

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        """Run one direct response, retaining no transcript or provider payload."""

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

        def mark_provider_progress(_: str) -> None:
            nonlocal progress_disabled
            if telemetry_span is None or progress_disabled:
                return
            try:
                telemetry_span.progress(_DIRECT_EVENT_METHOD)
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
                        queue_duration_ms = (time.perf_counter_ns() - queue_started) / 1_000_000
                        result = await self._invoke_once(
                            request,
                            on_first_progress=mark_provider_progress,
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
        on_first_progress: Callable[[str], None] | None,
    ) -> InvocationResult:
        started = time.monotonic()
        profile = request.profile
        redactor = Redactor.from_values(profile.secret_values)
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

        ineligible = _direct_ineligibility_code(request)
        if ineligible is not None:
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code=ineligible,
                started=started,
            )
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
            text_format = {
                "type": "json_schema",
                "name": _DIRECT_SCHEMA_NAME,
                "strict": True,
                "schema": _transport_output_schema(
                    profile.output_schema,
                    transport=profile.structured_output_transport,
                ),
            }
        except (TypeError, ValueError):
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_output_schema_invalid",
                started=started,
            )

        client = None
        try:
            client = self._client_factory(
                api_key=api_key,
                base_url=base_url,
                timeout=profile.limits.timeout_seconds,
                max_retries=_DIRECT_SDK_MAX_RETRIES,
            )
            async with asyncio.timeout(profile.limits.timeout_seconds):
                response = await client.responses.create(
                    model=profile.model,
                    input=request.prompt,
                    instructions=_combined_instructions(
                        profile.base_instructions,
                        profile.developer_instructions,
                    ),
                    max_output_tokens=profile.rollout_token_limit,
                    reasoning={"effort": profile.reasoning_effort.value},
                    store=False,
                    text={"format": text_format},
                )
        except TimeoutError:
            return _local_failure(
                request,
                status=InvocationStatus.TIMED_OUT,
                code="direct_timeout",
                started=started,
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
            )
        finally:
            if client is not None:
                try:
                    await client.close()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    # The HTTP request already has a terminal result. A close
                    # failure must not replace it with an opaque client error.
                    self._client_close_failures += 1

        response_status = _response_status(response)
        if response_status != "completed":
            status, code = _response_terminal_status(response_status, response)
            return _local_failure(request, status=status, code=code, started=started)
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
        except (TypeError, ValueError, json.JSONDecodeError):
            # Keep this boundary precise without retaining provider text.  A
            # completed compatible-gateway response that is not JSON is a
            # transport failure, not an invitation to coerce prose into a
            # semantic proposal.
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_structured_output_invalid_json",
                started=started,
            )
        try:
            raw_output = json_compatible(decoded_output)
            if profile.structured_output_transport == "provider_schema":
                structured_output = _decode_provider_json_ir(raw_output)
            else:
                structured_output = _decode_json_envelope(raw_output)
        except (TypeError, ValueError, json.JSONDecodeError):
            return _local_failure(
                request,
                status=InvocationStatus.FAILED,
                code="direct_structured_output_transport_invalid",
                started=started,
            )

        if on_first_progress is not None:
            on_first_progress(_DIRECT_EVENT_METHOD)
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


def _combined_instructions(base: str, developer: str | None) -> str:
    return "\n\n".join(part for part in (base, developer) if part)


def _direct_ineligibility_code(request: InvocationRequest) -> str | None:
    if request.execution_mode is not InvocationExecutionMode.SINGLE_SHOT_STRUCTURED:
        return "direct_execution_mode_ineligible"
    if request.session is not None:
        return "direct_session_ineligible"
    if request.profile.allowed_builtin_tools:
        return "direct_tools_ineligible"
    if request.profile.output_schema is None:
        return "direct_schema_required"
    return None


def _response_status(response: Any) -> str:
    status = getattr(response, "status", None)
    return status if isinstance(status, str) else "unknown"


def _response_terminal_status(status: str, response: Any) -> tuple[InvocationStatus, str]:
    if status == "cancelled":
        return InvocationStatus.CANCELLED, "direct_response_cancelled"
    reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
    if reason == "max_output_tokens":
        return InvocationStatus.FAILED, "direct_output_limit"
    if reason == "content_filter":
        return InvocationStatus.FAILED, "direct_content_filtered"
    return InvocationStatus.FAILED, "direct_response_not_completed"


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
) -> InvocationResult:
    return InvocationResult(
        invocation_id=request.invocation_id,
        status=status,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=None,
        events=(),
        error=InvocationError(code=code, message=code, retryable=retryable),
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        backend_version=_openai_sdk_version(),
    )


__all__ = ["DirectLlmBackend"]

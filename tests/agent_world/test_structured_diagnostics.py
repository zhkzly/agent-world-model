from agent_world.invocation.contracts import InvocationError
from agent_world.invocation.structured_diagnostics import (
    direct_output_limit_details,
    safe_terminal_condition,
    safe_terminal_details,
    safe_terminal_expected_category,
    safe_terminal_remediation,
    terminal_failure_retryable,
)


def test_direct_output_limit_retains_an_explicit_five_million_budget() -> None:
    assert direct_output_limit_details(configured_max_output_tokens=5_000_000) == {
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
        "configured_max_output_tokens": 5_000_000,
    }


def test_codex_physical_output_ceiling_has_safe_continuation_feedback() -> None:
    error = InvocationError(
        code="turn_failed_output_limit",
        message="turn_failed_output_limit",
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:other",
            "terminal_status": "incomplete",
            "terminal_reason": "max_output_tokens",
            "diagnostic_error_excerpt": "must never reach normal feedback",
        },
    )

    assert safe_terminal_details(error) == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:other",
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
    }
    assert "physical turn" in safe_terminal_condition(error)
    assert "session-bound continuation" in (safe_terminal_expected_category(error) or "")
    assert "continuation checkpoint" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is False


def test_sdk_resume_exception_has_safe_session_lifecycle_feedback() -> None:
    error = InvocationError(
        code="sdk_execution_failed",
        message="SDK_PROVIDER_SECRET_MESSAGE",
        retryable=True,
        details={
            "worker_phase": "thread_resume",
            "opaque_exception": "SDK_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {"worker_phase": "thread_resume"}
    assert "restoring a prior thread" in safe_terminal_condition(error)
    assert "session-state/worker-lifecycle" in (safe_terminal_expected_category(error) or "")
    assert "thread persistence" in (safe_terminal_remediation(error) or "")


def test_direct_rejected_schema_has_safe_adapter_feedback() -> None:
    error = InvocationError(
        code="direct_invalid_request",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=False,
        details={
            "http_status": 400,
            "provider_error_shape": "object",
            "provider_error_type": "invalid_request",
            "provider_error_code": "structured_output_schema",
            "provider_error_param": "structured_output_schema",
            "message": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "http_status": 400,
        "provider_error_shape": "object",
        "provider_error_type": "invalid_request",
        "provider_error_code": "structured_output_schema",
        "provider_error_param": "structured_output_schema",
    }
    assert "structured-output schema" in safe_terminal_condition(error)
    assert "schema/transport" in (safe_terminal_expected_category(error) or "")
    assert "text.format schema" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is False


def test_direct_provider_unavailable_keeps_a_safe_liveness_fingerprint() -> None:
    error = InvocationError(
        code="direct_provider_unavailable",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=True,
        details={
            "http_status": 503,
            "provider_error_shape": "object",
            "provider_error_type": "other",
            "provider_error_code": "other",
            "provider_error_param": "absent",
            "message": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "http_status": 503,
        "provider_error_shape": "object",
        "provider_error_type": "other",
        "provider_error_code": "other",
        "provider_error_param": "absent",
    }
    assert "http_status=503" in safe_terminal_condition(error)
    assert "Provider liveness/route check" in (safe_terminal_expected_category(error) or "")
    assert "safe HTTP status" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is True


def test_direct_provider_stream_stall_routes_to_transport_liveness_not_prompt_repair() -> None:
    error = InvocationError(
        code="direct_provider_stream_stalled",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=True,
        details={
            "waiting_phase": "direct_awaiting_stream_event",
            "idle_timeout_seconds": 300,
            "observed_provider_event_count": 4,
            "provider_text": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "waiting_phase": "direct_awaiting_stream_event",
        "idle_timeout_seconds": 300,
        "observed_provider_event_count": 4,
    }
    assert "4 event(s)" in safe_terminal_condition(error)
    assert "Direct Provider liveness control" in (safe_terminal_expected_category(error) or "")
    assert "profile-matched Direct control" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is True


def test_direct_malformed_json_envelope_has_prompt_and_skill_feedback() -> None:
    error = InvocationError(
        code="direct_structured_output_transport_invalid",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=False,
        details={
            "transport": "json_envelope",
            "envelope_shape": "artifact_json_string",
            "response_shape": "object",
            "parse_failure": "syntax",
            "parse_offset": 916,
            "response_characters": 5558,
            "provider_text": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "transport": "json_envelope",
        "envelope_shape": "artifact_json_string",
        "response_shape": "object",
        "parse_failure": "syntax",
        "parse_offset": 916,
        "response_characters": 5558,
    }
    assert "transport=json_envelope" in safe_terminal_condition(error)
    assert "json-envelope instruction" in (safe_terminal_expected_category(error) or "")
    assert "JSON string escaping" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is False

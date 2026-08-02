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


def test_direct_output_limit_without_adapter_cap_retains_only_closed_provider_facts() -> None:
    assert direct_output_limit_details(configured_max_output_tokens=None) == {
        "terminal_status": "incomplete",
        "terminal_reason": "max_output_tokens",
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


def test_codex_no_first_event_keeps_provider_liveness_feedback_out_of_prompt_repair() -> None:
    error = InvocationError(
        code="codex_no_first_provider_event",
        message="private worker or Provider text must not persist",
        retryable=True,
        details={
            "waiting_phase": "parent_waiting",
            "first_event_timeout_seconds": 120,
            "observed_provider_event_count": 0,
            "private_detail": "must not persist",
        },
    )

    assert safe_terminal_details(error) == {
        "waiting_phase": "parent_waiting",
        "first_event_timeout_seconds": 120,
        "observed_provider_event_count": 0,
    }
    assert "no validated Provider event" in safe_terminal_condition(error)
    assert "Codex SDK/app-server liveness control" in (safe_terminal_expected_category(error) or "")
    assert "profile-matched Codex SDK/app-server control" in (
        safe_terminal_remediation(error) or ""
    )
    assert terminal_failure_retryable(error) is True


def test_codex_started_stream_stall_keeps_worker_topology_out_of_agent_repair() -> None:
    error = InvocationError(
        code="codex_provider_stream_stalled",
        message="private worker and Provider content must not persist",
        retryable=True,
        details={
            "waiting_phase": "parent_awaiting_worker_result",
            "idle_timeout_seconds": 300,
            "observed_provider_event_count": 59,
            "workspace": "/private/host/path",
            "provider_text": "must not persist",
        },
    )

    assert safe_terminal_details(error) == {
        "waiting_phase": "parent_awaiting_worker_result",
        "idle_timeout_seconds": 300,
        "observed_provider_event_count": 59,
    }
    assert "59 validated Provider event(s)" in safe_terminal_condition(error)
    expected = safe_terminal_expected_category(error) or ""
    assert "Codex SDK/app-server liveness control" in expected
    assert "Agent workspace mapping" in expected
    remediation = safe_terminal_remediation(error) or ""
    assert "profile-matched Codex SDK/app-server control" in remediation
    assert terminal_failure_retryable(error) is True


def test_codex_provider_unavailable_keeps_closed_capacity_class_in_feedback() -> None:
    provider_text_canary = "INTERNAL_PROVIDER_SECRET_MUST_NOT_ESCAPE"

    error = InvocationError(
        code="turn_failed_provider_unavailable",
        message=provider_text_canary,
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:internalservererror",
            "diagnostic_error_excerpt": provider_text_canary,
        },
    )

    assert safe_terminal_details(error) == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:internalservererror",
    }
    condition = safe_terminal_condition(error)
    assert (
        condition
        == "the Codex Provider returned an internal server error before a terminal response"
    )
    assert provider_text_canary not in condition
    assert terminal_failure_retryable(error) is True

    overloaded = InvocationError(
        code="turn_failed_provider_unavailable",
        message="opaque provider text",
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:serveroverloaded",
        },
    )
    assert (
        safe_terminal_condition(overloaded)
        == "the Codex Provider reported that it is overloaded before a terminal response"
    )


def test_opaque_retryable_codex_terminal_keeps_its_safe_classification_signal() -> None:
    """An ``enum:other`` retry remains diagnosable without Provider prose."""

    provider_text_canary = "OPAQUE_PROVIDER_TEXT_MUST_NOT_ESCAPE"
    error = InvocationError(
        code="turn_failed_provider_unavailable",
        message=provider_text_canary,
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:other",
            "advisory_text_signals": ["transport_or_connection"],
            "message": provider_text_canary,
        },
    )

    assert safe_terminal_details(error) == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:other",
        "advisory_text_signals": ["transport_or_connection"],
    }
    assert provider_text_canary not in repr(safe_terminal_details(error))


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
    assert "safe Provider fingerprint" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is True


def test_direct_provider_unavailable_keeps_a_safe_connection_class() -> None:
    error = InvocationError(
        code="direct_provider_unavailable",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=True,
        details={
            "provider_error_shape": "missing",
            "transport_exception_kind": "connection",
            "message": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "provider_error_shape": "missing",
        "transport_exception_kind": "connection",
    }
    assert "transport=connection" in safe_terminal_condition(error)
    assert "DIRECT_PROVIDER_SECRET_MESSAGE" not in safe_terminal_condition(error)


def test_direct_provider_rejected_keeps_only_advisory_text_signals() -> None:
    error = InvocationError(
        code="direct_provider_rejected",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=False,
        details={
            "provider_error_shape": "object",
            "provider_error_type": "absent",
            "provider_error_code": "other",
            "provider_error_param": "absent",
            "advisory_text_signals": ["context_or_token_limit"],
            "provider_message": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "provider_error_shape": "object",
        "provider_error_type": "absent",
        "provider_error_code": "other",
        "provider_error_param": "absent",
        "advisory_text_signals": ["context_or_token_limit"],
    }
    assert "context_or_token_limit" in safe_terminal_condition(error)
    assert "DIRECT_PROVIDER_SECRET_MESSAGE" not in safe_terminal_condition(error)
    assert terminal_failure_retryable(error) is False


def test_direct_streamed_provider_unavailable_keeps_a_safe_retry_route() -> None:
    provider_message_canary = "DIRECT_PROVIDER_STREAM_SECRET_MESSAGE"
    error = InvocationError(
        code="direct_provider_unavailable",
        message=provider_message_canary,
        retryable=True,
        details={
            "provider_error_shape": "object",
            "provider_error_type": "absent",
            "provider_error_code": "provider_unavailable",
            "provider_error_param": "other",
            "message": provider_message_canary,
        },
    )

    assert safe_terminal_details(error) == {
        "provider_error_shape": "object",
        "provider_error_type": "absent",
        "provider_error_code": "provider_unavailable",
        "provider_error_param": "other",
    }
    assert "code=provider_unavailable" in safe_terminal_condition(error)
    assert "safe Provider fingerprint" in (safe_terminal_expected_category(error) or "")
    assert "safe Provider fingerprint" in (safe_terminal_remediation(error) or "")
    assert provider_message_canary not in safe_terminal_condition(error)
    assert provider_message_canary not in (safe_terminal_expected_category(error) or "")
    assert provider_message_canary not in (safe_terminal_remediation(error) or "")
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


def test_direct_malformed_json_has_prompt_schema_and_adapter_feedback() -> None:
    error = InvocationError(
        code="direct_structured_output_invalid_json",
        message="DIRECT_PROVIDER_SECRET_MESSAGE",
        retryable=False,
        details={
            "response_shape": "object",
            "parse_failure": "syntax",
            "parse_offset": 916,
            "response_characters": 5558,
            "provider_text": "DIRECT_PROVIDER_SECRET_MESSAGE",
        },
    )

    assert safe_terminal_details(error) == {
        "response_shape": "object",
        "parse_failure": "syntax",
        "parse_offset": 916,
        "response_characters": 5558,
    }
    assert "parse=syntax" in safe_terminal_condition(error)
    assert "Direct Prompt, native schema" in (safe_terminal_expected_category(error) or "")
    assert "Runtime Skill" not in (safe_terminal_expected_category(error) or "")
    assert "native schema" in (safe_terminal_remediation(error) or "")
    assert terminal_failure_retryable(error) is False


def test_pure_opaque_codex_other_envelope_is_retryable() -> None:
    """A pure enum:other envelope (no signal/HTTP status) must be retryable.

    The recovery policy classifies it TRANSIENT_TRANSPORT; terminal_failure_retryable
    must agree or the bounded infrastructure retry is never granted and the
    opaque gateway degradation becomes fatal.
    """
    error = InvocationError(
        code="turn_failed_unclassified_codex_error",
        message="turn_failed_unclassified_codex_error",
        retryable=True,
        details={"terminal_error_shape": "object", "codex_error_info": "enum:other"},
    )
    assert terminal_failure_retryable(error) is True


def test_signal_bearing_codex_other_envelope_stays_non_retryable() -> None:
    """A mixed-signal enum:other envelope must NOT become retryable."""
    error = InvocationError(
        code="turn_failed_unclassified_codex_error",
        message="turn_failed_unclassified_codex_error",
        retryable=True,
        details={
            "terminal_error_shape": "object",
            "codex_error_info": "enum:other",
            "advisory_text_signals": ["some_semantic_signal"],
        },
    )
    assert terminal_failure_retryable(error) is False

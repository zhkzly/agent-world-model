from __future__ import annotations

from agent_world.invocation.recovery import (
    AttributionSupport,
    InvocationAttributionLens,
    InvocationFailureClass,
    InvocationRecoveryEvidence,
    InvocationRecoveryPolicy,
    InvocationRecoveryRoute,
)


def test_closed_capacity_terminal_routes_one_fresh_same_model_retry() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_unavailable",
            retryable=True,
            terminal_details={"codex_error_info": "enum:internalservererror"},
            current_model="gpt-5.3-codex-spark",
            compatible_fallback_models=("gpt-5.4-mini",),
        )
    )

    assert decision.route is InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY
    assert decision.failure_class is InvocationFailureClass.TRANSIENT_CAPACITY
    assert decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate
    assert (
        InvocationAttributionLens.PROMPT_INPUT,
        AttributionSupport.WEAKENED,
    ) in tuple((item.lens, item.support) for item in decision.assessments)


def test_codex_no_first_provider_event_routes_liveness_before_any_semantic_repair() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="codex_no_first_provider_event",
            retryable=True,
            terminal_details={
                "waiting_phase": "parent_waiting",
                "first_event_timeout_seconds": 120,
                "observed_provider_event_count": 0,
            },
            current_model="gpt-5.3-codex-spark",
            compatible_fallback_models=("gpt-5.4-mini",),
        )
    )

    assert decision.route is InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY
    assert decision.failure_class is InvocationFailureClass.TRANSIENT_TRANSPORT
    assert decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate
    supports = {item.lens: item.support for item in decision.assessments}
    assert supports[InvocationAttributionLens.CODE_PROVIDER_PROFILE] is AttributionSupport.SUPPORTED
    assert supports[InvocationAttributionLens.PROMPT_INPUT] is AttributionSupport.WEAKENED
    assert supports[InvocationAttributionLens.RUNTIME_SKILL] is AttributionSupport.WEAKENED


def test_codex_started_stream_stall_routes_liveness_before_any_semantic_repair() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="codex_provider_stream_stalled",
            retryable=True,
            terminal_details={
                "waiting_phase": "parent_awaiting_worker_result",
                "idle_timeout_seconds": 300,
                "observed_provider_event_count": 59,
            },
            current_model="gpt-5.4-mini",
            compatible_fallback_models=("gpt-5.3-codex-spark",),
        )
    )

    assert decision.route is InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY
    assert decision.failure_class is InvocationFailureClass.TRANSIENT_TRANSPORT
    assert decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate
    supports = {item.lens: item.support for item in decision.assessments}
    assert supports[InvocationAttributionLens.CODE_PROVIDER_PROFILE] is AttributionSupport.SUPPORTED
    assert supports[InvocationAttributionLens.PROMPT_INPUT] is AttributionSupport.WEAKENED
    assert supports[InvocationAttributionLens.RUNTIME_SKILL] is AttributionSupport.WEAKENED


def test_closed_capacity_terminal_with_private_draft_routes_fresh_workspace_recovery() -> None:
    """A written draft changes the retry's input, never its adoption authority."""

    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_unavailable",
            retryable=True,
            terminal_details={"codex_error_info": "enum:internalservererror"},
            private_workspace_recovery_available=True,
            current_model="grok-4.5",
            compatible_fallback_models=("gpt-5.3-codex-spark", "gpt-5.4-mini"),
        )
    )

    assert decision.route is InvocationRecoveryRoute.WORKSPACE_RECOVERY
    assert decision.failure_class is InvocationFailureClass.TRANSIENT_CAPACITY
    assert decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate
    assert decision.target_model is None


def test_closed_capacity_terminal_prefers_a_proved_same_session() -> None:
    """A usable Agent session is stronger continuity than an untrusted draft."""

    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_unavailable",
            retryable=True,
            terminal_details={"codex_error_info": "enum:internalservererror"},
            private_continuation_available=True,
            private_workspace_recovery_available=True,
            current_model="grok-4.5",
            compatible_fallback_models=("gpt-5.3-codex-spark", "gpt-5.4-mini"),
        )
    )

    assert decision.route is InvocationRecoveryRoute.SESSION_CONTINUATION
    assert not decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate
    assert decision.target_model is None


def test_second_transient_on_the_same_route_selects_declared_fallback_only() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_rejected",
            retryable=True,
            terminal_details={"codex_error_info": "enum:serveroverloaded"},
            prior_same_route_retry_count=1,
            current_model="gpt-5.3-codex-spark",
            compatible_fallback_models=("grok-4.5", "gpt-5.4-mini"),
        )
    )

    assert decision.route is InvocationRecoveryRoute.MODEL_FALLBACK
    assert decision.target_model == "grok-4.5"
    assert decision.requires_fresh_node_session
    assert not decision.requires_route_liveness_gate


def test_second_transient_retries_same_model_when_definition_allows_two() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_unavailable",
            retryable=True,
            terminal_details={"codex_error_info": "enum:internalservererror"},
            prior_same_route_retry_count=1,
            same_route_retry_limit=2,
            current_model="gpt-5.4-mini",
        )
    )

    assert decision.route is InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY
    assert decision.requires_fresh_node_session
    assert decision.requires_route_liveness_gate


def test_malformed_transport_is_an_explicit_attribution_audit_not_blind_retry() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="direct_structured_output_invalid_json",
            retryable=False,
            terminal_details={"response_shape": "markdown_fence"},
        )
    )

    assert decision.route is InvocationRecoveryRoute.ATTRIBUTION_AUDIT
    assert decision.failure_class is InvocationFailureClass.MALFORMED_TRANSPORT
    supports = {item.lens: item.support for item in decision.assessments}
    assert (
        supports[InvocationAttributionLens.FEEDBACK_OBSERVABILITY] is AttributionSupport.SUPPORTED
    )
    assert supports[InvocationAttributionLens.PROMPT_INPUT] is AttributionSupport.UNKNOWN
    assert supports[InvocationAttributionLens.RUNTIME_SKILL] is AttributionSupport.UNKNOWN
    assert supports[InvocationAttributionLens.CODE_PROVIDER_PROFILE] is AttributionSupport.UNKNOWN


def test_direct_output_ceiling_falls_back_once_without_repeating_the_same_route() -> None:
    """A closed Direct physical ceiling has no resumable session to retry."""

    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="direct_output_limit",
            retryable=False,
            terminal_details={"terminal_reason": "max_output_tokens"},
            current_model="gpt-5.3-codex-spark",
            compatible_fallback_models=("gpt-5.4-mini",),
        )
    )

    assert decision.route is InvocationRecoveryRoute.MODEL_FALLBACK
    assert decision.failure_class is InvocationFailureClass.OUTPUT_CEILING
    assert decision.target_model == "gpt-5.4-mini"
    assert decision.requires_fresh_node_session
    assert not decision.requires_route_liveness_gate


def test_parsed_semantic_failure_needs_precise_feedback_before_repair() -> None:
    policy = InvocationRecoveryPolicy()
    incomplete = policy.decide(
        InvocationRecoveryEvidence(
            terminal_code="semantic_contract_violation",
            retryable=False,
            terminal_details={},
            parsed_semantic_candidate=True,
            precise_semantic_feedback=False,
        )
    )
    actionable = policy.decide(
        InvocationRecoveryEvidence(
            terminal_code="semantic_contract_violation",
            retryable=False,
            terminal_details={},
            parsed_semantic_candidate=True,
            precise_semantic_feedback=True,
        )
    )

    assert incomplete.route is InvocationRecoveryRoute.ATTRIBUTION_AUDIT
    assert actionable.route is InvocationRecoveryRoute.SEMANTIC_REPAIR


def test_unsettled_physical_attempt_requires_reconciliation_before_any_retry() -> None:
    decision = InvocationRecoveryPolicy().decide(
        InvocationRecoveryEvidence(
            terminal_code="turn_failed_provider_unavailable",
            retryable=True,
            terminal_details={},
            physical_settled=False,
        )
    )

    assert decision.route is InvocationRecoveryRoute.RECONCILE_OBSERVATION
    assert decision.failure_class is InvocationFailureClass.LIFECYCLE_UNSETTLED

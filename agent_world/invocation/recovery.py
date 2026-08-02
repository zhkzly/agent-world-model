"""Evidence-first routing for one terminal Agent/LLM invocation.

This module is deliberately a *policy selector*, not an executor.  It turns
the small, redacted terminal facts produced by an :class:`InvocationBackend`
into one permitted next route.  Scheduler/WorkRuntime retain authority to
open a new WorkAttempt, charge a budget, or expose semantic feedback to a
runtime Agent.

Keeping the selection here avoids the historical drift where Builder,
Designer, Judge and diagnostic commands each interpreted a retryable bit as
permission for a different kind of retry.  It also keeps malformed transport
and weak-observation failures out of a blind "try the model again" path.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from .contracts import InvocationOwnerKind, JsonObject
from .control_store import InvocationControlStore, InvocationPhysicalStatus


class InvocationAttributionLens(StrEnum):
    """The five explicit places a project-execution Agent must consider."""

    AGENT_VIEW = "agent_view"
    PROMPT_INPUT = "prompt_input"
    RUNTIME_SKILL = "runtime_skill"
    CODE_PROVIDER_PROFILE = "code_provider_profile"
    FEEDBACK_OBSERVABILITY = "feedback_observability"


class AttributionSupport(StrEnum):
    """Evidence strength for one attribution lens; never a certainty claim."""

    SUPPORTED = "supported"
    WEAKENED = "weakened"
    UNKNOWN = "unknown"


class InvocationFailureClass(StrEnum):
    """Closed failure families that deliberately do not share a retry path."""

    TRANSIENT_CAPACITY = "transient_capacity"
    TRANSIENT_TRANSPORT = "transient_transport"
    OUTPUT_CEILING = "output_ceiling"
    MALFORMED_TRANSPORT = "malformed_transport"
    SEMANTIC_VALIDATION = "semantic_validation"
    LIFECYCLE_UNSETTLED = "lifecycle_unsettled"
    CONFIGURATION = "configuration"
    OBSERVATION_INSUFFICIENT = "observation_insufficient"
    UNKNOWN = "unknown"


class InvocationRecoveryRoute(StrEnum):
    """One permitted next action after an invocation terminal fact."""

    RECONCILE_OBSERVATION = "reconcile_observation"
    SAME_MODEL_FRESH_RETRY = "same_model_fresh_retry"
    WORKSPACE_RECOVERY = "workspace_recovery"
    MODEL_FALLBACK = "model_fallback"
    SESSION_CONTINUATION = "session_continuation"
    SEMANTIC_REPAIR = "semantic_repair"
    ATTRIBUTION_AUDIT = "attribution_audit"
    CONFIGURATION_REMEDIATION = "configuration_remediation"
    TERMINAL = "terminal"


@dataclass(frozen=True, slots=True)
class LensAssessment:
    """A compact non-secret attribution projection for one terminal fact."""

    lens: InvocationAttributionLens
    support: AttributionSupport


@dataclass(frozen=True, slots=True)
class InvocationRecoveryEvidence:
    """The safe facts needed to select a route.

    ``terminal_code`` and ``terminal_details`` must already have passed the
    adapter's closed-vocabulary redaction.  No prompt, model output, endpoint,
    private session identifier, or workspace path belongs here.
    """

    terminal_code: str | None
    retryable: bool
    terminal_details: JsonObject
    physical_settled: bool = True
    precise_semantic_feedback: bool = False
    parsed_semantic_candidate: bool = False
    private_continuation_available: bool = False
    # This is deliberately distinct from a Provider-thread continuation.  It
    # means the leaf has verified that a dedicated writable workspace contains
    # an uncommitted draft after a closed terminal.  The draft remains private
    # and untrusted; policy may authorize a *new* session to inspect it only
    # within the existing same-model infrastructure-retry budget.
    private_workspace_recovery_available: bool = False
    # The repair ledger proved that prior semantic corrections of this exact
    # (definition, input) closure made no progress.  A further same-model
    # correction would be blind repetition; the policy may instead route the
    # next compatible model on a fresh session carrying the same repair
    # context (``semantic_context_recovery``).
    semantic_no_progress: bool = False
    # A same-model fresh session is one route-local recovery sequence, not a
    # separate allowance for every transient terminal subclass. The limit is
    # frozen in the WorkDefinition and shared with the RepairLedger.
    prior_same_route_retry_count: int = 0
    same_route_retry_limit: int = 1
    current_model: str | None = None
    compatible_fallback_models: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.prior_same_route_retry_count < 0:
            raise ValueError("prior_same_route_retry_count cannot be negative")
        if self.same_route_retry_limit < 0:
            raise ValueError("same_route_retry_limit cannot be negative")
        if any(not model or model != model.strip() for model in self.compatible_fallback_models):
            raise ValueError("compatible fallback models must be non-empty canonical names")
        if len(set(self.compatible_fallback_models)) != len(self.compatible_fallback_models):
            raise ValueError("compatible fallback models must be unique")


@dataclass(frozen=True, slots=True)
class InvocationRecoveryDecision:
    """A selected route plus the evidence conditions it preserves.

    This record intentionally grants no execution authority.  In particular,
    ``MODEL_FALLBACK`` means that a controller may persist a visible fallback
    definition and ask WorkRuntime/its ledger to authorize a physical attempt;
    it is not a direct instruction to mutate a profile in-place.
    """

    route: InvocationRecoveryRoute
    failure_class: InvocationFailureClass
    assessments: tuple[LensAssessment, ...]
    requires_fresh_node_session: bool = False
    requires_route_liveness_gate: bool = False
    target_model: str | None = None

    def __post_init__(self) -> None:
        if self.route is InvocationRecoveryRoute.MODEL_FALLBACK:
            if not self.target_model:
                raise ValueError("a model fallback decision requires a target model")
            if not self.requires_fresh_node_session:
                raise ValueError("model fallback must start a fresh node-local session")
        elif self.target_model is not None:
            raise ValueError("only a model fallback decision may name a target model")
        if self.route is InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY and not (
            self.requires_fresh_node_session and self.requires_route_liveness_gate
        ):
            raise ValueError("same-model retry requires fresh-session and liveness gates")
        if self.route is InvocationRecoveryRoute.WORKSPACE_RECOVERY and not (
            self.requires_fresh_node_session and self.requires_route_liveness_gate
        ):
            raise ValueError("workspace recovery requires a fresh session and liveness gate")
        if len({item.lens for item in self.assessments}) != len(self.assessments):
            raise ValueError("each attribution lens may appear at most once")


def _codex_opaque_empty_envelope(evidence: InvocationRecoveryEvidence) -> bool:
    """True when a Codex terminal is a pure opaque ``enum:other`` envelope.

    ``_codex_worker`` reduces an unknown closed ``codexErrorInfo`` to
    ``turn_failed_unclassified_codex_error`` with ``terminal_error_shape: object``
    plus (when the provider message carried one) an advisory signal or HTTP
    status.  A *pure opaque* envelope has none of those — the gateway collapsed
    a transport disconnect or Provider 5xx into ``other`` with no observable
    signal.  This is the Codex analog of the direct lane's empty
    ``provider_error_shape in {missing, non_object}`` envelope; both should be
    retryable transport, not a semantic design defect.
    """

    details = evidence.terminal_details
    if details.get("terminal_error_shape") != "object":
        return False
    if details.get("advisory_text_signals"):
        return False
    if details.get("http_status") is not None:
        return False
    return True


class InvocationRecoveryPolicy:
    """Classify safe terminal facts without choosing semantic content.

    The policy is intentionally conservative.  A malformed structured response
    is not silently deemed a Prompt bug, a Runtime Skill bug, or an adapter
    bug: it produces an attribution-audit route.  A parsed semantic candidate
    may use a bounded repair only when its feedback is exact. A closed
    transient route failure may continue an already-proved Agent session;
    otherwise it selects the fresh-session retry/fallback branch.
    """

    def decide(self, evidence: InvocationRecoveryEvidence) -> InvocationRecoveryDecision:
        if not evidence.physical_settled:
            return self._decision(
                InvocationRecoveryRoute.RECONCILE_OBSERVATION,
                InvocationFailureClass.LIFECYCLE_UNSETTLED,
                (
                    (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.SUPPORTED),
                    (
                        InvocationAttributionLens.FEEDBACK_OBSERVABILITY,
                        AttributionSupport.SUPPORTED,
                    ),
                ),
            )

        failure_class = self.classify(evidence)
        if failure_class is InvocationFailureClass.OUTPUT_CEILING:
            if evidence.private_continuation_available:
                return self._decision(
                    InvocationRecoveryRoute.SESSION_CONTINUATION,
                    failure_class,
                    (
                        (
                            InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                            AttributionSupport.SUPPORTED,
                        ),
                        (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.UNKNOWN),
                        (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.UNKNOWN),
                    ),
                )
            # A Direct turn has no resumable Provider session or private draft
            # to continue. A ``max_output_tokens`` terminal is also not a
            # useful same-model retry: this exact physical route has already
            # exhausted its response envelope. If the graph declared a later
            # compatible model, make that one fresh, visible route change.
            # This is deliberately narrower than treating every malformed or
            # incomplete response as retryable.
            terminal_code = (
                (evidence.terminal_code or "")
                .removeprefix("agent_backend_")
                .removeprefix("verifier_backend_")
            )
            target = _next_fallback_model(evidence)
            if terminal_code == "direct_output_limit" and target is not None:
                return self._decision(
                    InvocationRecoveryRoute.MODEL_FALLBACK,
                    failure_class,
                    (
                        (
                            InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                            AttributionSupport.SUPPORTED,
                        ),
                        (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.UNKNOWN),
                        (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.UNKNOWN),
                        (
                            InvocationAttributionLens.FEEDBACK_OBSERVABILITY,
                            AttributionSupport.UNKNOWN,
                        ),
                    ),
                    requires_fresh_node_session=True,
                    target_model=target,
                )
            return self._decision(
                InvocationRecoveryRoute.ATTRIBUTION_AUDIT,
                failure_class,
                (
                    (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.SUPPORTED),
                    (InvocationAttributionLens.FEEDBACK_OBSERVABILITY, AttributionSupport.UNKNOWN),
                ),
            )

        if failure_class in {
            InvocationFailureClass.MALFORMED_TRANSPORT,
            InvocationFailureClass.OBSERVATION_INSUFFICIENT,
            InvocationFailureClass.UNKNOWN,
        }:
            return self._decision(
                InvocationRecoveryRoute.ATTRIBUTION_AUDIT,
                failure_class,
                (
                    (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.UNKNOWN),
                    (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.UNKNOWN),
                    (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.UNKNOWN),
                    (
                        InvocationAttributionLens.FEEDBACK_OBSERVABILITY,
                        AttributionSupport.SUPPORTED,
                    ),
                    (InvocationAttributionLens.AGENT_VIEW, AttributionSupport.UNKNOWN),
                ),
            )

        if failure_class is InvocationFailureClass.SEMANTIC_VALIDATION:
            # A node whose prior semantic corrections made no progress is
            # stuck on this model; the only bounded escape is the next
            # compatible model on a fresh session with the same repair
            # context.  Without this the node blocks permanently
            # (repair_no_progress_terminal) despite a fallback model that
            # could produce a different candidate.
            if evidence.semantic_no_progress:
                target = _next_fallback_model(evidence)
                if target is not None:
                    return self._decision(
                        InvocationRecoveryRoute.MODEL_FALLBACK,
                        failure_class,
                        (
                            (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.WEAKENED),
                            (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.WEAKENED),
                            (InvocationAttributionLens.FEEDBACK_OBSERVABILITY, AttributionSupport.SUPPORTED),
                            (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.SUPPORTED),
                        ),
                        requires_fresh_node_session=True,
                        target_model=target,
                    )
            route = (
                InvocationRecoveryRoute.SEMANTIC_REPAIR
                if evidence.parsed_semantic_candidate and evidence.precise_semantic_feedback
                else InvocationRecoveryRoute.ATTRIBUTION_AUDIT
            )
            return self._decision(
                route,
                failure_class,
                (
                    (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.SUPPORTED),
                    (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.UNKNOWN),
                    (
                        InvocationAttributionLens.FEEDBACK_OBSERVABILITY,
                        AttributionSupport.SUPPORTED,
                    ),
                    (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.UNKNOWN),
                ),
            )

        if failure_class in {
            InvocationFailureClass.TRANSIENT_CAPACITY,
            InvocationFailureClass.TRANSIENT_TRANSPORT,
        }:
            if not evidence.retryable:
                return self._decision(
                    InvocationRecoveryRoute.TERMINAL,
                    failure_class,
                    (
                        (
                            InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                            AttributionSupport.SUPPORTED,
                        ),
                    ),
                )
            if evidence.prior_same_route_retry_count < evidence.same_route_retry_limit:
                if evidence.private_continuation_available:
                    return self._decision(
                        InvocationRecoveryRoute.SESSION_CONTINUATION,
                        failure_class,
                        (
                            (
                                InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                                AttributionSupport.SUPPORTED,
                            ),
                            (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.WEAKENED),
                            (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.WEAKENED),
                        ),
                        requires_route_liveness_gate=True,
                    )
                return self._decision(
                    (
                        InvocationRecoveryRoute.WORKSPACE_RECOVERY
                        if evidence.private_workspace_recovery_available
                        else InvocationRecoveryRoute.SAME_MODEL_FRESH_RETRY
                    ),
                    failure_class,
                    (
                        (
                            InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                            AttributionSupport.SUPPORTED,
                        ),
                        (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.WEAKENED),
                        (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.WEAKENED),
                    ),
                    requires_fresh_node_session=True,
                    requires_route_liveness_gate=True,
                )
            target = _next_fallback_model(evidence)
            if target is not None:
                return self._decision(
                    InvocationRecoveryRoute.MODEL_FALLBACK,
                    failure_class,
                    (
                        (
                            InvocationAttributionLens.CODE_PROVIDER_PROFILE,
                            AttributionSupport.SUPPORTED,
                        ),
                        (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.WEAKENED),
                        (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.WEAKENED),
                    ),
                    requires_fresh_node_session=True,
                    target_model=target,
                )
            return self._decision(
                InvocationRecoveryRoute.TERMINAL,
                failure_class,
                ((InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.SUPPORTED),),
            )

        if failure_class is InvocationFailureClass.CONFIGURATION:
            return self._decision(
                InvocationRecoveryRoute.CONFIGURATION_REMEDIATION,
                failure_class,
                (
                    (InvocationAttributionLens.CODE_PROVIDER_PROFILE, AttributionSupport.SUPPORTED),
                    (InvocationAttributionLens.PROMPT_INPUT, AttributionSupport.WEAKENED),
                    (InvocationAttributionLens.RUNTIME_SKILL, AttributionSupport.WEAKENED),
                ),
            )

        return self._decision(
            InvocationRecoveryRoute.ATTRIBUTION_AUDIT,
            failure_class,
            ((InvocationAttributionLens.FEEDBACK_OBSERVABILITY, AttributionSupport.SUPPORTED),),
        )

    @staticmethod
    def classify(evidence: InvocationRecoveryEvidence) -> InvocationFailureClass:
        """Classify only closed safe terminal values; unknown stays unknown."""

        code = evidence.terminal_code
        if not code:
            return InvocationFailureClass.OBSERVATION_INSUFFICIENT
        normalized = code.removeprefix("agent_backend_").removeprefix("verifier_backend_")
        if normalized in {"declared_wall_expired", "owner_cancelled", "owner_process_interrupted"}:
            return InvocationFailureClass.LIFECYCLE_UNSETTLED
        if normalized in {"turn_failed_output_limit", "direct_output_limit"}:
            return InvocationFailureClass.OUTPUT_CEILING
        if normalized in {
            "direct_structured_output_invalid_json",
            "turn_failed_output_schema",
        }:
            return InvocationFailureClass.MALFORMED_TRANSPORT
        if normalized in {
            "turn_failed_authentication",
            "turn_failed_model_unavailable",
            "turn_failed_context_window",
            "turn_failed_invalid_request",
            "direct_authentication_failed",
            "direct_model_unavailable",
            "direct_invalid_request",
        }:
            return InvocationFailureClass.CONFIGURATION
        if normalized in {
            "turn_failed_provider_unavailable",
            "direct_provider_unavailable",
            "direct_rate_limited",
        }:
            return InvocationFailureClass.TRANSIENT_CAPACITY
        if normalized == "turn_failed_provider_rejected":
            info = evidence.terminal_details.get("codex_error_info")
            if info in {"enum:internalservererror", "enum:serveroverloaded"}:
                return InvocationFailureClass.TRANSIENT_CAPACITY
        if normalized in {
            "direct_provider_timeout",
            "direct_provider_stream_stalled",
            # No Provider event ever arrived, so the transport -- not the model
            # -- is the first credible owner.  Classifying it here is what gives
            # policy an authorized fresh-session retry and then an explicit
            # compatible-model fallback; left UNKNOWN it produced no route at
            # all and the attempt sat until its full declared wall expired.
            "direct_no_first_provider_event",
            # Codex has the same first-event transport question after its
            # worker/app-server starts. A safe local lifecycle frame does not
            # prove Prompt or Runtime Skill delivery; zero validated Provider
            # events therefore routes through the same recorded liveness gate.
            "codex_no_first_provider_event",
            # A started Codex worker can also stop emitting Provider events
            # mid-turn. This is adapter/route liveness evidence, not Agent
            # feedback: the parent records only a safe count and idle interval
            # before the Scheduler chooses one authorized fresh execution.
            "codex_provider_stream_stalled",
            # Older Scheduler leaves normalize a closed adapter transport
            # terminal under this framework-owned safe code. It is still not
            # a semantic model failure; retryability remains an independent
            # required fact below.
            "transport_failed",
        }:
            return InvocationFailureClass.TRANSIENT_TRANSPORT
        if (
            normalized == "turn_failed_unclassified_codex_error"
            and _codex_opaque_empty_envelope(evidence)
        ):
            # A closed ``enum:other`` envelope with NO advisory signal and NO
            # HTTP status is the Codex-gateway analog of the direct-lane empty
            # envelope (``provider_error_shape in {missing, non_object}``) that
            # ``direct_llm`` already classifies as retryable transport.  The
            # worker could not attribute a transport disconnect or Provider 5xx
            # to any signal (they collapse into ``other``), so the conservative
            # unclassified-fatal outcome mis-attributes a genuinely transient
            # gateway outage as a semantic design defect.  Treating the pure
            # opaque envelope as TRANSIENT_TRANSPORT keeps the failure honest
            # (bounded infra retry) while never authorizing semantic repair —
            # the worker still marks mixed-signal envelopes unclassified.
            return InvocationFailureClass.TRANSIENT_TRANSPORT
        if evidence.parsed_semantic_candidate:
            return InvocationFailureClass.SEMANTIC_VALIDATION
        return InvocationFailureClass.UNKNOWN

    @staticmethod
    def _decision(
        route: InvocationRecoveryRoute,
        failure_class: InvocationFailureClass,
        assessments: tuple[tuple[InvocationAttributionLens, AttributionSupport], ...],
        *,
        requires_fresh_node_session: bool = False,
        requires_route_liveness_gate: bool = False,
        target_model: str | None = None,
    ) -> InvocationRecoveryDecision:
        return InvocationRecoveryDecision(
            route=route,
            failure_class=failure_class,
            assessments=tuple(LensAssessment(lens, support) for lens, support in assessments),
            requires_fresh_node_session=requires_fresh_node_session,
            requires_route_liveness_gate=requires_route_liveness_gate,
            target_model=target_model,
        )


type RouteLivenessStatus = Literal["verified", "not_enforced", "rejected"]
type RouteLivenessSource = Literal["invocation_control", "constructed_runtime"]


@dataclass(frozen=True, slots=True)
class RouteLivenessCheck:
    """Safe pre-dispatch evidence for one authorized same-model retry.

    This is deliberately not a synthetic provider ``ping``. Such a ping would
    have a different profile, prompt and capability envelope, so it could not
    prove that the frozen node may run. The check instead proves that the exact
    prior physical attempt is settled under the same Work ownership and
    immutable closure; after the recorded backoff, the actual fresh node turn
    is the only meaningful route liveness observation.
    """

    status: RouteLivenessStatus
    source: RouteLivenessSource
    code: str
    route: Literal["codex_sdk", "direct_llm"] | None = None
    provider_progress_count: int = 0
    last_local_phase: str | None = None

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip() or len(self.code) > 160:
            raise ValueError("route liveness code must be a bounded safe identifier")
        if self.provider_progress_count < 0:
            raise ValueError("route liveness provider progress cannot be negative")


class RouteLivenessChecker(Protocol):
    """Verify the prior physical route before WorkRuntime opens a fresh retry."""

    def assess(
        self,
        *,
        invocation_id: str | None,
        expected_model: str | None,
        expected_scope_id: str,
        expected_coordinate: str,
        expected_input_closure_digest: str,
    ) -> RouteLivenessCheck: ...


class InvocationControlRouteLivenessChecker:
    """Use the durable control record, not transient process state, for the gate."""

    def __init__(self, store: InvocationControlStore) -> None:
        self._store = store

    def assess(
        self,
        *,
        invocation_id: str | None,
        expected_model: str | None,
        expected_scope_id: str,
        expected_coordinate: str,
        expected_input_closure_digest: str,
    ) -> RouteLivenessCheck:
        if invocation_id is None or expected_model is None:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_missing_agent_provenance",
            )
        try:
            # A dead owner is a lifecycle failure, not a reason to redispatch
            # a fresh session. Reconcile before the exact-record read.
            self._store.reconcile_owner_loss()
            record = self._store.read(invocation_id)
        except Exception:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_control_store_unavailable",
            )
        if record is None:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_prior_record_missing",
            )
        if record.status is not InvocationPhysicalStatus.SETTLED or record.terminal is None:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_prior_record_unsettled",
                route=record.route,
                provider_progress_count=record.provider_progress_count,
                last_local_phase=record.last_local_phase.value,
            )
        if record.model != expected_model:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_model_mismatch",
                route=record.route,
                provider_progress_count=record.provider_progress_count,
                last_local_phase=record.last_local_phase.value,
            )
        owner = record.owner
        if (
            owner.owner_kind is not InvocationOwnerKind.WORK_OPERATION
            or owner.scope_id != expected_scope_id
            or owner.coordinate != expected_coordinate
            or owner.immutable_input_closure_digest != expected_input_closure_digest
        ):
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_owner_closure_mismatch",
                route=record.route,
                provider_progress_count=record.provider_progress_count,
                last_local_phase=record.last_local_phase.value,
            )
        if not record.terminal.retryable:
            return RouteLivenessCheck(
                status="rejected",
                source="invocation_control",
                code="route_liveness_prior_terminal_not_retryable",
                route=record.route,
                provider_progress_count=record.provider_progress_count,
                last_local_phase=record.last_local_phase.value,
            )
        return RouteLivenessCheck(
            status="verified",
            source="invocation_control",
            code="route_liveness_prior_terminal_verified",
            route=record.route,
            provider_progress_count=record.provider_progress_count,
            last_local_phase=record.last_local_phase.value,
        )


def _next_fallback_model(evidence: InvocationRecoveryEvidence) -> str | None:
    """Choose only a predeclared compatible model; never invent a route."""

    for model in evidence.compatible_fallback_models:
        if model != evidence.current_model:
            return model
    return None


__all__ = [
    "AttributionSupport",
    "InvocationAttributionLens",
    "InvocationFailureClass",
    "InvocationRecoveryDecision",
    "InvocationRecoveryEvidence",
    "InvocationRecoveryPolicy",
    "InvocationRecoveryRoute",
    "InvocationControlRouteLivenessChecker",
    "LensAssessment",
    "RouteLivenessCheck",
    "RouteLivenessChecker",
    "RouteLivenessSource",
    "RouteLivenessStatus",
]

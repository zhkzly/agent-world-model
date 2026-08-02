"""One physical structured-Agent proposal for the Scheduler control plane.

This module is deliberately independent of :mod:`designer.service`.  The
legacy Designer combines profile resolution, invocation, validation,
FeedbackContract writes and a component-local retry loop in one method.  A
Scheduler leaf cannot safely call that method: one dispatch could otherwise
spend several model turns and make a repair decision before the WorkGraph sees
the first failure.

``invoke_structured_once`` is the replacement boundary.  It resolves one
least-privilege profile, invokes the real ``InvocationBackend`` at most once,
and returns either a typed proposal or a safe terminal leaf outcome.  It never
opens a continuation, asks for a correction, mutates a repair ledger, or
interprets semantic progress.  Those are Scheduler responsibilities.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ValidationError

from agent_world.contracts import BudgetUsage, PermissionScope, canonical_json_bytes, sha256_digest
from agent_world.control.leaf_executor import (
    AgentCorrectionBrief,
    AgentExecutionProvenance,
    LeafExecutionFailure,
    LeafSemanticRepairSeed,
    LeafSessionContinuation,
    LeafValidationFailure,
    append_authorized_semantic_repair_context,
    record_agent_proposal_outcome,
)
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
    pydantic_validation_diagnostic,
)
from agent_world.control.work import ValidationIssue, WorkAttempt, WorkDefinition
from agent_world.designer.validation import StructuredSemanticError
from agent_world.invocation import (
    AgentOutputAuthority,
    CapabilityResolutionError,
    InvocationBackend,
    InvocationExecutionMode,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    NodeCapabilityRequirement,
    ResolvedAgentProfile,
    assert_agent_output_advisory,
)
from agent_world.invocation.contracts import JsonValue
from agent_world.invocation.structured_diagnostics import (
    safe_terminal_code,
    safe_terminal_condition,
    safe_terminal_details,
    safe_terminal_expected_category,
    safe_terminal_remediation,
    terminal_failure_retryable,
)
from agent_world.invocation.structured_prompt import render_direct_structured_prompt

_SAFE_BACKEND_CODE = re.compile(r"[^A-Za-z0-9._:-]")

# WorkDefinition uses Python identifiers while the independently versioned
# capability/profile contracts use their established hyphenated role ids.  The
# translation belongs at this single SDK boundary: leaves must never invent a
# profile name or weaken the requirement just to make a dispatch run.
_PROFILE_ROLE_BY_WORK_ROLE = {
    "researcher": "researcher",
    "environment_engineer": "environment-engineer",
    "challenger": "challenger",
}


class StructuredProfileProvider(Protocol):
    """Minimal profile resolver surface needed by one Scheduler Agent leaf."""

    def resolve(
        self,
        *,
        role: str,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
        rollout_token_limit: int | None = None,
        invocation_timeout_seconds: float | None = None,
        model_override: str | None = None,
    ) -> ResolvedAgentProfile: ...


@dataclass(frozen=True, slots=True)
class StructuredTurnResult[TOutput: BaseModel]:
    """One successfully parsed advisory proposal and its measured provenance."""

    output: TOutput
    invocation: InvocationResult
    agent: AgentExecutionProvenance
    observed_actual: BudgetUsage
    unknown_upper_bound: BudgetUsage


async def invoke_structured_once[TOutput: BaseModel](
    *,
    backend: InvocationBackend,
    profiles: StructuredProfileProvider,
    definition: WorkDefinition,
    attempt: WorkAttempt,
    dispatch_id: str,
    lineage_id: str,
    workspace: Path,
    model: type[TOutput],
    prompt: str,
    permissions: PermissionScope,
    semantic_validator: Callable[[TOutput], None] | None = None,
    capability_requirement: NodeCapabilityRequirement | None = None,
    correction_brief: AgentCorrectionBrief | None = None,
    semantic_repair_seed: LeafSemanticRepairSeed | None = None,
    logical_output_protocol: str | None = None,
    session: InvocationSession | None = None,
    ownership: InvocationOwnership | None = None,
) -> StructuredTurnResult[TOutput]:
    """Run one real Agent turn and translate only safe terminal outcomes.

    ``LeafValidationFailure`` means an Agent proposal was actually returned but
    fails a deterministic contract; its exact field paths are preserved for a
    possible Scheduler-authorized correction.  ``LeafExecutionFailure`` means
    no candidate is available for semantic repair.  Neither result retries in
    this function.
    """

    policy = definition.proposal_policy
    if policy.executor != "agent":
        raise ValueError("invoke_structured_once requires one Agent WorkDefinition")
    if policy.agent_role is None:
        raise ValueError("Agent WorkDefinition must declare an agent role")
    if not prompt.strip():
        raise ValueError("structured Agent prompt must not be empty")
    if logical_output_protocol is not None and not logical_output_protocol.strip():
        raise ValueError("logical_output_protocol must not be empty when supplied")
    assert_agent_output_advisory(model, authority=AgentOutputAuthority.SEMANTIC_ADVISORY)
    work_role = policy.agent_role
    try:
        profile_role = _PROFILE_ROLE_BY_WORK_ROLE[work_role]
    except KeyError as exc:  # pragma: no cover - WorkDefinition has a closed role literal
        raise ValueError(f"unsupported WorkDefinition Agent role: {work_role}") from exc
    schema = model.model_json_schema(mode="validation")
    schema_digest = sha256_digest(canonical_json_bytes(schema))
    requirement = capability_requirement or NodeCapabilityRequirement.structured_output(
        node_id=f"{profile_role}.{definition.coordinate.stage}",
        role=profile_role,
    )
    if requirement.role != profile_role:
        raise ValueError("structured Agent capability role must match the resolved profile role")

    workspace.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded local setup
    try:
        if attempt.model_override is None:
            profile = profiles.resolve(
                role=profile_role,
                lineage_id=lineage_id,
                workspace=workspace,
                output_schema=schema,
                permissions=permissions,
                requirement=requirement,
                # The Scheduler budget is one observable physical Provider turn.
                # A declared logical session remains visible to the profile/SDK so
                # a later authorized continuation retains the user's full session
                # envelope rather than silently inheriting this turn's slice.
                rollout_token_limit=(policy.session_token_limit or policy.budget.llm_tokens)
                or None,
                # The profile's SDK timeout is part of the same bounded physical
                # operation as the Scheduler lease. Leaving it at a broader
                # role/config default would let the HTTP client outlive the
                # immutable node deadline and make timeout provenance depend on
                # which cancellation boundary happened to fire first.
                invocation_timeout_seconds=policy.budget.wall_seconds,
            )
        else:
            profile = profiles.resolve(
                role=profile_role,
                lineage_id=lineage_id,
                workspace=workspace,
                output_schema=schema,
                permissions=permissions,
                requirement=requirement,
                rollout_token_limit=(policy.session_token_limit or policy.budget.llm_tokens)
                or None,
                invocation_timeout_seconds=policy.budget.wall_seconds,
                model_override=attempt.model_override,
            )
    except CapabilityResolutionError as exc:
        raise LeafExecutionFailure(
            code="agent_capability_resolution_denied",
            category="the Agent profile lacks one declared capability",
        ) from exc
    except Exception as exc:
        raise LeafExecutionFailure(
            code="agent_profile_resolution_error",
            category="Agent profile resolution did not complete",
        ) from exc

    if semantic_repair_seed is not None:
        if (
            semantic_repair_seed.model != profile.model
            or semantic_repair_seed.profile_digest != f"sha256:{profile.profile_hash}"
            or semantic_repair_seed.output_schema_digest != schema_digest
        ):
            raise LeafExecutionFailure(
                code="preflight_semantic_repair_seed_binding_invalid",
                category=(
                    "the private parsed candidate does not bind the resolved model, profile, "
                    "and output schema"
                ),
                retryable=False,
            )
    prompt = append_authorized_semantic_repair_context(
        prompt,
        correction_brief=correction_brief,
        semantic_repair_seed=semantic_repair_seed,
    )

    if not profile.allowed_builtin_tools:
        prompt = render_direct_structured_prompt(
            prompt,
            logical_protocol=logical_output_protocol,
        )

    if session is not None:
        # A session-capable structured turn must remain on the Agentic Codex
        # route.  The Direct structured adapter has no same-thread semantics,
        # so treating its output limit as resumable would create a false
        # continuation path.
        if not profile.allowed_builtin_tools:
            raise LeafExecutionFailure(
                code="preflight_agent_session_continuation_unsupported",
                category=(
                    "the resolved structured profile has no Agentic same-session "
                    "continuation capability"
                ),
                retryable=False,
            )
        if (
            session.lineage_id != profile.lineage_id
            or session.workspace.resolve() != profile.workspace.resolve()
            or session.profile_hash != profile.profile_hash
            or session.codex_config_sha256 != profile.codex_config_sha256
        ):
            raise LeafExecutionFailure(
                code="preflight_agent_session_continuation_binding_invalid",
                category=(
                    "the resumed structured Agent session does not bind the exact "
                    "profile, workspace, and lineage"
                ),
                retryable=False,
            )

    request = InvocationRequest(
        # The Scheduler created this opaque dispatch id under the active
        # Proposal OperationRun.  Reusing it as the backend invocation id is
        # what binds a real model result to that durable operation; minting a
        # second id here would make the runtime correctly reject the proposal
        # as an untracked invocation.
        invocation_id=dispatch_id,
        prompt=prompt,
        profile=profile,
        session=session,
        ownership=ownership,
        metadata={
            "work_id": definition.work_id,
            "coordinate": definition.coordinate.coordinate_key,
            "attempt_ordinal": attempt.ordinal,
            "dispatch_id": dispatch_id,
            "work_role": work_role,
            "profile_role": profile_role,
            # The WorkAttempt is durable Scheduler state.  This label is
            # observational only: it cannot authorize a retry, but makes a
            # child invocation visibly distinct from an initial proposal.
            "repair_mode": (
                "process_recovery"
                if attempt.recovery_ordinal > 0
                else "authorized_repair"
                if attempt.repair_action_ref is not None
                else "initial"
            ),
            "repair_attempt_charge": attempt.repair_attempt_charge,
        },
        # This helper owns one physical proposal only: it never resumes a
        # session or authorizes an in-function correction. Tool-free profiles
        # can use the direct structured adapter, while declared read-only
        # shell access is a real Agent turn and must stay on the Codex route.
        execution_mode=(
            InvocationExecutionMode.AGENTIC
            if profile.allowed_builtin_tools
            else InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
        ),
    )
    # Dispatch identity and the resolved Agent profile are known *before* crossing
    # the provider boundary.  A timeout or transport exception therefore has
    # real invocation provenance even though no terminal provider envelope is
    # available.  Without this record the leaf kernel would correctly refuse
    # to invent provenance, but incorrectly strand an already-dispatched
    # non-replayable operation in ``running`` state.
    agent = AgentExecutionProvenance(
        invocation_id=request.invocation_id,
        provider=profile.model_provider or "openai",
        model=profile.model,
        profile_digest=f"sha256:{profile.profile_hash}",
        output_schema_digest=schema_digest,
    )
    uncertain_before_result = _reserved_invocation_usage(definition)
    output: TOutput | None = None
    try:
        # The Invocation Control Plane is the only backend a leaf receives, and
        # it owns the declared physical wall, liveness supervision, cancellation
        # and the durable terminal fact.  A second wall here would race it and
        # produce two disagreeing terminals for one physical attempt.
        result = await backend.invoke(request)
    except TimeoutError as exc:
        raise LeafExecutionFailure(
            code="agent_invocation_timeout",
            category="the real Agent invocation exceeded its Scheduler wall budget",
            unknown_upper_bound=uncertain_before_result,
            agent=agent,
        ) from exc
    except Exception as exc:
        raise LeafExecutionFailure(
            code="agent_invocation_execution_error",
            category="the real Agent backend raised before a terminal result",
            unknown_upper_bound=uncertain_before_result,
            agent=agent,
        ) from exc

    if result.invocation_id != request.invocation_id:
        raise LeafExecutionFailure(
            code="agent_invocation_identity_mismatch",
            category="the Agent backend returned a terminal result for another invocation",
            unknown_upper_bound=uncertain_before_result,
            agent=agent,
        )
    observed_actual, unknown_upper_bound = _usage_for_result(definition, result)
    if not result.succeeded:
        raw_code = safe_terminal_code(result.error) or result.status.value
        safe_code = _SAFE_BACKEND_CODE.sub("-", raw_code).strip("-.") or "terminal"
        session_continuation = None
        failure_code = f"agent_backend_{safe_code}"[:160]
        # The Scheduler recognizes only this exact closed adapter terminal as
        # a same-session continuation candidate.  Keep the opaque thread id
        # private; the leaf kernel will persist it only after the normal
        # Validation -> Feedback -> RepairAction authorization chain succeeds.
        if (
            raw_code == "turn_failed_output_limit"
            and result.session is not None
            and policy.session_token_limit is not None
            and policy.session_wall_seconds is not None
            and definition.repair_policy.maximum_session_continuations > 0
        ):
            failure_code = "turn_failed_output_limit"
            session_continuation = LeafSessionContinuation(
                session=result.session,
                model=agent.model,
                output_schema_digest=schema_digest,
            )
        raise LeafExecutionFailure(
            code=failure_code,
            category=safe_terminal_condition(result.error),
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            agent=agent,
            retryable=terminal_failure_retryable(result.error),
            expected_category=safe_terminal_expected_category(result.error),
            remediation=safe_terminal_remediation(result.error),
            terminal_details=safe_terminal_details(result.error),
            session_continuation=session_continuation,
        )

    try:
        if result.structured_output is None:
            raise StructuredValidationError(
                _diagnostic(
                    definition,
                    (
                        SafeValidationIssue(
                            "structured_output_missing",
                            ("structured_output",),
                            "the completed Agent invocation returned no structured artifact object",
                        ),
                    ),
                )
            )
        # Provider output is JSON, so keep Pydantic in JSON mode.  This is
        # important for closed contracts that intentionally use tuples while
        # their wire representation is a JSON array; Python-mode strict
        # validation would incorrectly reject a valid provider artifact.
        output = model.model_validate_json(canonical_json_bytes(result.structured_output))
        if semantic_validator is not None:
            semantic_validator(output)
    except StructuredValidationError as exc:
        _raise_validation_failure(
            diagnostic=_rebind_diagnostic(exc.diagnostic, definition),
            definition=definition,
            result=result,
            agent=agent,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            category="structured_output_semantic",
            previous_candidate=(output.model_dump(mode="json") if output is not None else None),
        )
    except StructuredSemanticError as exc:
        _raise_validation_failure(
            diagnostic=_diagnostic(
                definition,
                tuple(
                    SafeValidationIssue(
                        issue.code,
                        issue.location,
                        issue.message,
                        violated_condition=(issue.violated_condition or issue.message),
                        expected_category=(issue.expected_category or issue.message),
                    )
                    for issue in exc.issues
                ),
            ),
            definition=definition,
            result=result,
            agent=agent,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            category="structured_output_semantic",
            previous_candidate=(output.model_dump(mode="json") if output is not None else None),
        )
    except ValidationError as exc:
        _raise_validation_failure(
            diagnostic=pydantic_validation_diagnostic(
                exc,
                owner_component=definition.coordinate.component,
                validation_phase=definition.validation_policy.validation_phase,
                frontier_ordinal=definition.validation_policy.frontier_ordinal,
            ),
            definition=definition,
            result=result,
            agent=agent,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            category="structured_output_shape",
        )
    except ValueError:
        # Framework semantic validators must use StructuredValidationError or
        # StructuredSemanticError.  An untyped ValueError cannot safely tell an
        # Agent what to fix, so do not spend a correction turn on it.
        _raise_validation_failure(
            diagnostic=_diagnostic(
                definition,
                (
                    SafeValidationIssue(
                        "framework_diagnostic_incomplete",
                        ("semantic_output",),
                        (
                            "A semantic validator raised an untyped error; framework code "
                            "must provide a safe condition before an Agent can repair it."
                        ),
                        retryable=False,
                        violated_condition="the validator emitted no typed semantic issue",
                        expected_category="a StructuredValidationError with a stable safe issue",
                    ),
                ),
            ),
            definition=definition,
            result=result,
            agent=agent,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            category="framework_diagnostic_incomplete",
        )

    if output is None:  # pragma: no cover - guarded by the structured-output check above
        raise RuntimeError("parsed structured Agent output is unexpectedly absent")
    turn = StructuredTurnResult(
        output=output,
        invocation=result,
        agent=agent,
        observed_actual=observed_actual,
        unknown_upper_bound=unknown_upper_bound,
    )
    # Source compilation / immutable Artifact writes immediately follow this
    # real turn in the same one-attempt leaf. If they fail, the kernel must
    # settle the known Agent work rather than strand a dispatched operation.
    record_agent_proposal_outcome(
        agent=turn.agent,
        observed_actual=turn.observed_actual,
        unknown_upper_bound=turn.unknown_upper_bound,
    )
    return turn


def _reserved_invocation_usage(definition: WorkDefinition) -> BudgetUsage:
    budget = definition.proposal_policy.budget
    return BudgetUsage(llm_tokens=budget.llm_tokens, agent_turns=budget.agent_turns)


def _usage_for_result(
    definition: WorkDefinition,
    result: InvocationResult,
) -> tuple[BudgetUsage, BudgetUsage]:
    """Conservatively account for one terminal backend invocation.

    A completed or failed result proves that one Agent turn occurred.  Provider
    usage may omit tokens, in which case only the LLM-token portion remains
    unknown; the Scheduler's lease still protects the full declared maximum.
    """

    total_tokens = result.usage.turn.total_tokens if result.usage and result.usage.turn else None
    if total_tokens is None:
        return (
            BudgetUsage(agent_turns=1),
            BudgetUsage(llm_tokens=definition.proposal_policy.budget.llm_tokens),
        )
    observed_tokens = min(max(0, total_tokens), definition.proposal_policy.budget.llm_tokens)
    return (
        BudgetUsage(llm_tokens=observed_tokens, agent_turns=1),
        # A terminal Provider result with ``total_tokens`` is an observed cost,
        # not an unknown remainder of the physical turn envelope.  The full
        # envelope remains reserved while the call is active, but retaining
        # its unused portion after settlement makes a sequence of short,
        # successful calls exhaust the scope before an authorized repair can
        # run.  Keep the conservative full-envelope charge only when the
        # Provider supplied no token usage at all.
        BudgetUsage(),
    )


def _diagnostic(
    definition: WorkDefinition,
    issues: tuple[SafeValidationIssue, ...],
) -> ValidationDiagnostic:
    return ValidationDiagnostic(
        owner_component=definition.coordinate.component,
        validation_phase=definition.validation_policy.validation_phase,
        frontier_ordinal=definition.validation_policy.frontier_ordinal,
        issues=issues,
    )


def _rebind_diagnostic(
    diagnostic: ValidationDiagnostic,
    definition: WorkDefinition,
) -> ValidationDiagnostic:
    """Keep safe issue detail while binding it to the executing Work claim."""

    return _diagnostic(definition, diagnostic.issues)


def _raise_validation_failure(
    *,
    diagnostic: ValidationDiagnostic,
    definition: WorkDefinition,
    result: InvocationResult,
    agent: AgentExecutionProvenance,
    observed_actual: BudgetUsage,
    unknown_upper_bound: BudgetUsage,
    category: str,
    previous_candidate: JsonValue | None = None,
) -> None:
    """Raise the leaf-kernel's safe semantic result with no rejected payload."""

    issues = tuple(
        ValidationIssue(
            code=issue.code,
            path=issue.location,
            violated_condition=(
                issue.violated_condition
                or "the deterministic structured-output contract was violated"
            ),
            expected_category=(
                issue.expected_category or "a value satisfying the typed structured-output contract"
            ),
            remediation=issue.message,
            retryable=issue.retryable,
        )
        for issue in diagnostic.issues
    )
    output_commitment = sha256_digest(
        canonical_json_bytes(
            {
                "invocation_id": result.invocation_id,
                "definition_digest": definition.definition_digest,
                "diagnostic": diagnostic.persistence_projection(),
            }
        )
    )
    raise LeafValidationFailure(
        issues=issues,
        output_commitment=output_commitment,
        category=category,
        observed_actual=observed_actual,
        unknown_upper_bound=unknown_upper_bound,
        agent=agent,
        semantic_repair_seed=(
            LeafSemanticRepairSeed(
                model=agent.model,
                profile_digest=agent.profile_digest,
                output_schema_digest=agent.output_schema_digest,
                previous_candidate=previous_candidate,
            )
            if previous_candidate is not None
            else None
        ),
    )


__all__ = [
    "StructuredProfileProvider",
    "StructuredTurnResult",
    "invoke_structured_once",
]

"""Compile a Challenger proposal into framework-bound, Judge-private Verifier IR."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, NoReturn, Protocol, TypeVar, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import BaseModel, JsonValue, ValidationError

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    MAX_VERIFIER_CASES,
    ActorBoundary,
    ArtifactRef,
    Budget,
    EnvironmentDesign,
    Finding,
    PermissionScope,
    TaskRequirement,
    ToolContract,
    VerifierAssertion,
    VerifierCase,
    VerifierIR,
    VerifierProperty,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.contracts.reachability import (
    ParameterizedSolveRecipe,
    RecipeLiteral,
    RecipePointer,
)
from agent_world.control.decision import StructuredRepairMode
from agent_world.control.feedback import RepairTargetRef
from agent_world.control.leaf_executor import (
    AgentCorrectionBrief,
    LeafSemanticRepairSeed,
    append_authorized_semantic_repair_context,
)
from agent_world.control.repair import StructuredRepairAuthority, StructuredRepairDenied
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
    pydantic_validation_diagnostic,
)
from agent_world.invocation import (
    AgentOutputAuthority,
    CapabilityResolutionError,
    InvocationBackend,
    InvocationExecutionMode,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    NodeCapabilityRequirement,
    ProfileResolutionError,
    ResolvedAgentProfile,
    assert_agent_output_advisory,
    safe_profile_resolution_category,
    standalone_component_ownership,
)
from agent_world.invocation.structured_prompt import render_direct_structured_prompt

from .models import (
    BoundVerifierCaseIntent,
    VerifierBatchDraft,
    VerifierBatchPlan,
    VerifierBatchPlanItem,
    VerifierDraft,
    VerifierIntent,
    VerifierIntentCheckpoint,
)
from .rules import design_rule_index

_CANONICAL_PROPERTY_KIND = {
    "initial_state": "initial_state",
    "invariant": "invariant",
    "precondition": "precondition",
    "transition": "transition",
    "postcondition": "postcondition",
    "error_condition": "error_semantics",
    "permission": "permission",
    "task_success": "task_success",
    "task_failure": "task_failure",
    "task_terminal": "task_terminal",
    "sampling": "sampling",
}
_AUXILIARY_PROPERTY_RULE_FAMILIES = {
    "idempotency": {"transition", "postcondition", "invariant"},
    "rollback": {"transition", "error_condition", "invariant"},
    "concurrency": {"transition", "error_condition", "invariant"},
    "metamorphic": set(_CANONICAL_PROPERTY_KIND),
}


@dataclass(frozen=True, slots=True)
class _SemanticRequirement:
    """One model-visible selector bound to exactly one frozen Rule.

    The selector is opaque to the Challenger.  It preserves framework ownership
    of private Rule identities while keeping distinct semantic conditions from
    being collapsed into one generic property-family label.
    """

    requirement_id: str
    rule_id: str
    scope: str
    task_type: str | None
    property_kind: str
    tool_ids: tuple[str, ...]
    positive_and_negative: bool
    error_code: str | None
    summary: str


def _semantic_requirement_id(rule_id: str) -> str:
    """Derive one stable opaque selector for an exact frozen Rule."""

    digest = sha256_digest(
        canonical_json_bytes(
            {
                "binding_version": "agent-world.semantic-requirement.v1",
                "rule_id": rule_id,
            }
        )
    ).removeprefix("sha256:")
    return f"requirement:{digest[:24]}"


def _semantic_requirement_projection(
    requirement: _SemanticRequirement,
) -> dict[str, JsonValue]:
    """Render the complete, safe semantic requirement visible to Challenger."""

    projection: dict[str, JsonValue] = {
        "requirement_id": requirement.requirement_id,
        "scope": requirement.scope,
        "task_type": requirement.task_type,
        "property_kind": requirement.property_kind,
        "tool_ids": list(requirement.tool_ids),
        "positive_and_negative": requirement.positive_and_negative,
        "summary": requirement.summary,
    }
    if requirement.error_code is not None:
        projection["error_code"] = requirement.error_code
    return projection


def _semantic_requirement_summary(requirement: _SemanticRequirement) -> str:
    """Return only values already disclosed in the requirement catalog."""

    task_label = requirement.task_type or "world_shared"
    tools_label = ", ".join(requirement.tool_ids) or "any compatible task tool"
    polarity_label = (
        "positive_and_negative" if requirement.positive_and_negative else "positive_only"
    )
    error_label = f", error_code={requirement.error_code}" if requirement.error_code else ""
    return (
        f"scope={requirement.scope}, task_type={task_label}, "
        f"property_kind={requirement.property_kind}, tool_ids=[{tools_label}], "
        f"polarity={polarity_label}{error_label}: {requirement.summary}"
    )


class ChallengerProfileProvider(Protocol):
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
class _VerifierBatchAccountingSnapshot:
    invocation_results: tuple[InvocationResult, ...]
    unknown_token_upper_bounds: tuple[int, ...]
    checkpoint_refs: tuple[ArtifactRef, ...]


@dataclass(slots=True)
class _VerifierBatchAccounting:
    """Supervisor-visible accounting for one concurrent Verifier batch."""

    _invocation_results: dict[str, InvocationResult] = field(default_factory=dict)
    _active_token_upper_bounds: dict[str, int] = field(default_factory=dict)
    _unknown_token_upper_bounds: dict[str, int] = field(default_factory=dict)
    _anonymous_unknown_token_upper_bounds: list[int] = field(default_factory=list)
    _checkpoint_refs: dict[str, ArtifactRef] = field(default_factory=dict)

    def begin_invocation(self, invocation_id: str, token_upper_bound: int) -> None:
        if (
            invocation_id in self._invocation_results
            or invocation_id in self._active_token_upper_bounds
            or invocation_id in self._unknown_token_upper_bounds
        ):
            raise RuntimeError("Verifier batch reused an invocation id")
        self._active_token_upper_bounds[invocation_id] = max(1, token_upper_bound)

    def record_result(self, result: InvocationResult) -> None:
        invocation_id = result.invocation_id
        existing = self._invocation_results.get(invocation_id)
        if existing is not None and existing != result:
            raise RuntimeError("Verifier batch produced conflicting invocation results")
        self._active_token_upper_bounds.pop(invocation_id, None)
        self._unknown_token_upper_bounds.pop(invocation_id, None)
        self._invocation_results.setdefault(invocation_id, result)

    def record_results(self, results: Sequence[InvocationResult]) -> None:
        for result in results:
            self.record_result(result)

    def record_unknown_invocation(self, invocation_id: str, token_upper_bound: int) -> None:
        self._active_token_upper_bounds.pop(invocation_id, None)
        if invocation_id in self._invocation_results:
            return
        self._unknown_token_upper_bounds[invocation_id] = max(
            self._unknown_token_upper_bounds.get(invocation_id, 0),
            max(1, token_upper_bound),
        )

    def record_all_active_as_unknown(self) -> None:
        for invocation_id, token_upper_bound in tuple(self._active_token_upper_bounds.items()):
            self.record_unknown_invocation(invocation_id, token_upper_bound)

    def record_checkpoint(self, checkpoint_ref: ArtifactRef) -> None:
        self._checkpoint_refs.setdefault(checkpoint_ref.revision_id, checkpoint_ref)

    def absorb_error(self, error: BaseException) -> None:
        if not isinstance(error, VerifierCompilationError):
            return
        self.record_results(error.invocation_results)
        for checkpoint_ref in error.checkpoint_refs:
            self.record_checkpoint(checkpoint_ref)

        # Older/direct callers may provide bounds without invocation identities.
        # Preserve only the multiset not already represented by this batch.
        represented = Counter(self._unknown_token_upper_bounds.values())
        represented.update(self._anonymous_unknown_token_upper_bounds)
        incoming = Counter(error.unknown_token_upper_bounds)
        for token_upper_bound, count in (incoming - represented).items():
            self._anonymous_unknown_token_upper_bounds.extend([token_upper_bound] * count)

    def snapshot(self) -> _VerifierBatchAccountingSnapshot:
        return _VerifierBatchAccountingSnapshot(
            invocation_results=tuple(self._invocation_results.values()),
            unknown_token_upper_bounds=(
                *self._unknown_token_upper_bounds.values(),
                *self._anonymous_unknown_token_upper_bounds,
            ),
            checkpoint_refs=tuple(self._checkpoint_refs.values()),
        )


class VerifierCompilationError(RuntimeError):
    def __init__(
        self,
        message: str,
        result: InvocationResult | None = None,
        *,
        permission_denied: bool = False,
        invocation_results: Sequence[InvocationResult] = (),
        unknown_token_upper_bounds: Sequence[int] = (),
        checkpoint_refs: Sequence[ArtifactRef] = (),
        profile: ResolvedAgentProfile | None = None,
        safe_code: str = "verifier_compilation_error",
        safe_category: str = "VerifierCompilationError",
        retryable: bool = True,
        expected_category: str | None = None,
        remediation: str | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.permission_denied = permission_denied
        results = tuple(invocation_results)
        if result is not None and all(item is not result for item in results):
            results = (*results, result)
        self.invocation_results = results
        self.unknown_token_upper_bounds = tuple(unknown_token_upper_bounds)
        self.checkpoint_refs = tuple(checkpoint_refs)
        self.profile = profile
        self.safe_code = safe_code
        self.safe_category = safe_category
        self.retryable = retryable
        self.expected_category = expected_category
        self.remediation = remediation


@dataclass(frozen=True, slots=True)
class CompiledVerifier:
    verifier: VerifierIR
    verifier_ref: ArtifactRef
    invocation_results: tuple[InvocationResult, ...]
    checkpoint_refs: tuple[ArtifactRef, ...] = ()


@dataclass(frozen=True, slots=True)
class CompiledVerifierBatch:
    """Result of exactly one physical Challenger invocation.

    A semantic rejection is represented as a typed safe diagnostic instead of a
    compiler-owned retry.  The Scheduler leaf converts it to one
    ``ValidationReport`` and the global repair policy decides whether another
    physical WorkAttempt exists.
    """

    plan_ref: ArtifactRef
    plan: VerifierBatchPlan
    batch: VerifierBatchPlanItem
    profile: ResolvedAgentProfile
    invocation: InvocationResult
    draft: VerifierDraft | None = None
    checkpoint_ref: ArtifactRef | None = None
    draft_ref: ArtifactRef | None = None
    validation_diagnostic: ValidationDiagnostic | None = None
    # A parsed-but-rejected intent is private repair input only. It is never
    # persisted as a Judge Artifact unless the full semantic compilation passes.
    intent: VerifierIntent | None = None

    @property
    def succeeded(self) -> bool:
        return (
            self.invocation.succeeded
            and self.validation_diagnostic is None
            and self.draft is not None
            and self.checkpoint_ref is not None
            and self.draft_ref is not None
        )


TOutput = TypeVar("TOutput", bound=BaseModel)
type VerifierBatchResult = tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]


class VerifierCompiler:
    """Use an isolated Challenger, then enforce semantic coverage in framework code."""

    maximum_task_shards = 8

    def __init__(
        self,
        *,
        artifact_store: ArtifactWriter,
        invocation_backend: InvocationBackend,
        profile_provider: ChallengerProfileProvider,
        maximum_structured_reworks: int = 2,
        maximum_tasks_per_batch: int = 2,
        batch_failure_grace_seconds: float = 30.0,
        cancellation_timeout_seconds: float = 10.0,
    ) -> None:
        if maximum_structured_reworks < 0 or not (
            1 <= maximum_tasks_per_batch <= self.maximum_task_shards
        ):
            raise ValueError("Verifier rework and batch-capacity policy is invalid")
        if batch_failure_grace_seconds < 0 or cancellation_timeout_seconds <= 0:
            raise ValueError("Verifier cancellation policy is invalid")
        self.artifacts = artifact_store
        self.backend = invocation_backend
        self.profiles = profile_provider
        self.maximum_structured_reworks = maximum_structured_reworks
        self.maximum_tasks_per_batch = maximum_tasks_per_batch
        self.batch_failure_grace_seconds = batch_failure_grace_seconds
        self.cancellation_timeout_seconds = cancellation_timeout_seconds

    def maximum_invocation_turns(self, task_count: int) -> int:
        return self.minimum_invocation_turns(task_count) * (self.maximum_structured_reworks + 1)

    def minimum_invocation_turns(self, task_count: int) -> int:
        if task_count < 1 or task_count > self.maximum_task_shards:
            raise ValueError("task_count is outside Verifier task policy")
        return (task_count + self.maximum_tasks_per_batch - 1) // (self.maximum_tasks_per_batch)

    def build_batch_plan(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
    ) -> VerifierBatchPlan:
        """Freeze the exact physical Challenger partition for one Design revision.

        This is framework code, not a planning Agent: task order, Rule ownership,
        property coverage and semantic-case quota all derive from immutable Design
        bytes. Scheduler leaves consume the persisted plan instead of invoking a
        compiler-internal concurrent fan-out.
        """

        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self.artifacts.require_exact_json(
            world_spec_ref,
            design.world_spec,
            artifact_types=("design.world_spec", "expansion.world_spec"),
        )
        tasks = design.curriculum.task_types
        if len(tasks) > self.maximum_task_shards:
            raise VerifierCompilationError(
                f"Verifier compilation exceeds {self.maximum_task_shards} task shards"
            )
        task_batches = tuple(
            tasks[index : index + self.maximum_tasks_per_batch]
            for index in range(0, len(tasks), self.maximum_tasks_per_batch)
        )
        if not task_batches:
            raise VerifierCompilationError("Verifier compilation requires at least one task batch")
        rule_assignments = self._assign_required_rules(design)
        property_assignments = self._assign_required_property_families(design, rule_assignments)
        case_quotas = self._semantic_case_quotas(len(task_batches))
        batch_items: list[VerifierBatchPlanItem] = []
        for batch_index, task_batch in enumerate(task_batches):
            task_types = tuple(task.task_type for task in task_batch)
            required_rule_ids = tuple(
                rule_id for task in task_batch for rule_id in rule_assignments[task.task_type]
            )
            required_property_families = tuple(
                sorted(
                    {
                        family
                        for task in task_batch
                        for family in property_assignments[task.task_type]
                    }
                )
            )
            require_metamorphic = bool(design.verification.required_metamorphic_relations) and (
                batch_index == 0
            )
            context = self._challenger_context(
                design,
                task_types=task_types,
                required_rule_ids=required_rule_ids,
                required_property_families=required_property_families,
                require_metamorphic=require_metamorphic,
            )
            context["semantic_case_limit"] = case_quotas[batch_index]
            batch_items.append(
                VerifierBatchPlanItem(
                    batch_id=f"verifier-batch:{batch_index + 1}",
                    batch_index=batch_index,
                    task_types=task_types,
                    required_rule_ids=required_rule_ids,
                    required_property_families=required_property_families,
                    semantic_case_limit=case_quotas[batch_index],
                    require_metamorphic=require_metamorphic,
                    context_hash=sha256_digest(canonical_json_bytes(context)),
                )
            )
        plan_identity = sha256_digest(
            canonical_json_bytes(
                {
                    "design_ref": design_ref.revision_id,
                    "world_spec_ref": world_spec_ref.revision_id,
                    "maximum_tasks_per_batch": self.maximum_tasks_per_batch,
                    "batches": [item.model_dump(mode="json") for item in batch_items],
                }
            )
        ).removeprefix("sha256:")
        return VerifierBatchPlan(
            plan_id=f"verifier-plan:{plan_identity[:24]}",
            design_ref=design_ref,
            world_spec_ref=world_spec_ref,
            maximum_tasks_per_batch=self.maximum_tasks_per_batch,
            batches=tuple(batch_items),
        )

    def persist_batch_plan(self, plan: VerifierBatchPlan) -> ArtifactRef:
        """Persist one frozen plan for Scheduler recovery and shard input binding."""

        return self.artifacts.put_json(
            artifact_id=plan.plan_id,
            artifact_type="judge.verifier_batch_plan",
            value=plan,
            dependencies=(plan.design_ref, plan.world_spec_ref),
        )

    async def compile_batch_once(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
        plan: VerifierBatchPlan,
        plan_ref: ArtifactRef,
        batch_index: int,
        workspace: Path,
        lineage_id: str,
        budget: Budget,
        permissions: PermissionScope,
        invocation_id: str,
        invocation_ownership: InvocationOwnership | None = None,
        model_override: str | None = None,
        correction_brief: AgentCorrectionBrief | None = None,
        semantic_repair_seed: LeafSemanticRepairSeed | None = None,
    ) -> CompiledVerifierBatch:
        """Run exactly one planned Challenger turn; never authorize an internal retry.

        ``invocation_id`` is the Scheduler dispatch identity, so the durable
        OperationRun, backend request and eventual ProposalExecution all bind
        the same physical call.  Any semantic rejection returns a safe
        ``ValidationDiagnostic`` to the caller rather than starting a hidden
        continuation or choosing a repair route.
        """

        if budget.agent_turns != 1 or budget.llm_tokens < 1:
            raise ValueError("one-shot Verifier batch requires exactly one Agent turn")
        self.artifacts.require_exact_json(
            plan_ref,
            plan,
            artifact_types=("judge.verifier_batch_plan",),
        )
        if plan.design_ref != design_ref or plan.world_spec_ref != world_spec_ref:
            raise VerifierCompilationError("Verifier batch plan does not bind this frozen Design")
        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self.artifacts.require_exact_json(
            world_spec_ref,
            design.world_spec,
            artifact_types=("design.world_spec", "expansion.world_spec"),
        )
        if not 0 <= batch_index < len(plan.batches):
            raise VerifierCompilationError("Verifier batch index is outside the frozen plan")
        batch = plan.batches[batch_index]
        workspace = workspace.expanduser().resolve()  # noqa: ASYNC240 - bounded setup I/O
        workspace.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240 - bounded setup I/O
        context = self._challenger_context(
            design,
            task_types=batch.task_types,
            required_rule_ids=batch.required_rule_ids,
            required_property_families=batch.required_property_families,
            require_metamorphic=batch.require_metamorphic,
        )
        context["semantic_case_limit"] = batch.semantic_case_limit
        if sha256_digest(canonical_json_bytes(context)) != batch.context_hash:
            raise VerifierCompilationError(
                "Verifier batch plan context commitment mismatch",
                safe_code="verifier_batch_plan_context_commitment_mismatch",
                safe_category=(
                    "current Verifier compiler context differs from the frozen deterministic "
                    "VerifierPlan"
                ),
                retryable=False,
                expected_category=(
                    "a VerifierBatchPlan regenerated from the same frozen EnvironmentDesign "
                    "under the current compiler revision"
                ),
                remediation=(
                    "refresh the deterministic VerifierPlan before dispatching this Verifier batch"
                ),
            )
        self._write_json(workspace / "verifier-context.json", context)
        output_schema = VerifierIntent.model_json_schema(mode="validation")
        try:
            assert_agent_output_advisory(
                VerifierIntent,
                authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
            )
            if model_override is None:
                profile = self.profiles.resolve(
                    role="challenger",
                    lineage_id=f"{lineage_id}.batch.{batch_index}",
                    workspace=workspace,
                    output_schema=output_schema,
                    permissions=permissions,
                    requirement=NodeCapabilityRequirement.structured_output(
                        node_id="challenger.verifier-compile-batch",
                        role="challenger",
                    ),
                    rollout_token_limit=budget.llm_tokens,
                    invocation_timeout_seconds=budget.wall_seconds,
                )
            else:
                profile = self.profiles.resolve(
                    role="challenger",
                    lineage_id=f"{lineage_id}.batch.{batch_index}",
                    workspace=workspace,
                    output_schema=output_schema,
                    permissions=permissions,
                    requirement=NodeCapabilityRequirement.structured_output(
                        node_id="challenger.verifier-compile-batch",
                        role="challenger",
                    ),
                    rollout_token_limit=budget.llm_tokens,
                    invocation_timeout_seconds=budget.wall_seconds,
                    model_override=model_override,
                )
        except CapabilityResolutionError as exc:
            raise VerifierCompilationError(
                str(exc),
                permission_denied=True,
            ) from exc
        except ProfileResolutionError as exc:
            raise VerifierCompilationError(
                "Verifier Direct profile could not be materialized",
                safe_code="verifier_profile_resolution_error",
                safe_category=(
                    "Verifier Direct profile resolution category: "
                    f"{safe_profile_resolution_category(exc)}"
                ),
                retryable=False,
                expected_category=(
                    "a Direct Challenger profile with the reported profile-resolution "
                    "category corrected"
                ),
                remediation=(
                    "Inspect the safe Direct profile-resolution category and the shared "
                    "Agent/Direct profile construction path; do not edit the Prompt "
                    "or Runtime Skill."
                ),
            ) from exc
        ownership = invocation_ownership or standalone_component_ownership(
            invocation_id=invocation_id,
            component="judge",
            coordinate="judge:verifier_batch",
        )
        self._assert_semantic_repair_seed_binding(
            semantic_repair_seed,
            profile=profile,
        )
        direct_prompt = render_direct_structured_prompt(
            append_authorized_semantic_repair_context(
                self._prompt(context),
                correction_brief=correction_brief,
                semantic_repair_seed=semantic_repair_seed,
            ),
        )
        try:
            invocation = await self.backend.invoke(
                InvocationRequest(
                    invocation_id=invocation_id,
                    prompt=direct_prompt,
                    profile=profile,
                    session=None,
                    ownership=ownership,
                    metadata={
                        "role": "challenger",
                        "lineage_id": lineage_id,
                        "batch_id": batch.batch_id,
                        "batch_index": batch.batch_index,
                        "mode": "scheduler_one_shot",
                    },
                    execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise VerifierCompilationError(
                f"Verifier backend raised {type(exc).__name__}",
                unknown_token_upper_bounds=(budget.llm_tokens,),
            ) from exc
        if invocation.invocation_id != invocation_id:
            raise VerifierCompilationError(
                "Verifier backend returned a mismatched invocation id",
                result=invocation,
                profile=profile,
            )
        outcome = CompiledVerifierBatch(
            plan_ref=plan_ref,
            plan=plan,
            batch=batch,
            profile=profile,
            invocation=invocation,
        )
        if not invocation.succeeded:
            return outcome
        intent: VerifierIntent | None = None
        try:
            if invocation.structured_output is None:
                raise ValueError("Challenger returned no structured output")
            intent = VerifierIntent.model_validate_json(
                canonical_json_bytes(invocation.structured_output)
            )
            self._validate_planned_intent(intent, design=design, batch=batch)
        except (ValidationError, ValueError) as exc:
            return outcome.__class__(
                plan_ref=plan_ref,
                plan=plan,
                batch=batch,
                profile=profile,
                invocation=invocation,
                validation_diagnostic=self._validation_diagnostic(exc),
                intent=intent,
            )
        try:
            checkpoint_ref = self._persist_intent_checkpoint(
                lineage_id=lineage_id,
                batch_index=batch.batch_index,
                context=context,
                intent=intent,
                invocation_results=(invocation,),
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
                plan_ref=plan_ref,
            )
            draft = self._compile_intent(
                intent,
                design,
                allowed_task_types=batch.task_types,
                required_rule_ids=batch.required_rule_ids,
                required_property_families=batch.required_property_families,
                require_metamorphic=batch.require_metamorphic,
            )
            self._validate_draft(
                draft,
                design,
                allowed_task_types=batch.task_types,
                required_rule_ids=batch.required_rule_ids,
                required_property_families=batch.required_property_families,
                require_metamorphic=batch.require_metamorphic,
            )
            batch_draft = VerifierBatchDraft(
                draft_id=f"verifier-batch-draft:{lineage_id}:{batch.batch_id}",
                plan_ref=plan_ref,
                batch_id=batch.batch_id,
                checkpoint_ref=checkpoint_ref,
                draft=draft,
            )
            draft_ref = self.artifacts.put_json(
                artifact_id=batch_draft.draft_id,
                artifact_type="judge.verifier_batch_draft",
                value=batch_draft,
                dependencies=(plan_ref, checkpoint_ref, design_ref, world_spec_ref),
            )
        except Exception as exc:
            raise VerifierCompilationError(
                "framework failed to compile a validated one-shot Verifier batch",
                result=invocation,
                invocation_results=(invocation,),
                profile=profile,
            ) from exc
        return outcome.__class__(
            plan_ref=plan_ref,
            plan=plan,
            batch=batch,
            profile=profile,
            invocation=invocation,
            draft=draft,
            checkpoint_ref=checkpoint_ref,
            draft_ref=draft_ref,
            intent=intent,
        )

    @staticmethod
    def _assert_semantic_repair_seed_binding(
        seed: LeafSemanticRepairSeed | None,
        *,
        profile: ResolvedAgentProfile,
    ) -> None:
        if seed is None:
            return
        schema_digest = sha256_digest(
            canonical_json_bytes(VerifierIntent.model_json_schema(mode="validation"))
        )
        if (
            seed.model != profile.model
            or seed.profile_digest != f"sha256:{profile.profile_hash}"
            or seed.output_schema_digest != schema_digest
        ):
            raise VerifierCompilationError(
                "Verifier semantic repair seed does not bind the resolved Challenger profile"
            )

    @staticmethod
    def _validate_planned_intent(
        intent: VerifierIntent,
        *,
        design: EnvironmentDesign,
        batch: VerifierBatchPlanItem,
    ) -> None:
        if len(intent.cases) > batch.semantic_case_limit:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="intent_capacity",
                    frontier_ordinal=5,
                    issues=(
                        SafeValidationIssue(
                            "intent_case_capacity_exceeded",
                            ("cases",),
                            "Return no more semantic trajectories than the "
                            "framework-provided semantic_case_limit.",
                        ),
                    ),
                )
            )
        VerifierCompiler._validate_intent(
            intent,
            design,
            allowed_task_types=batch.task_types,
            required_rule_ids=batch.required_rule_ids,
            required_property_families=batch.required_property_families,
            require_metamorphic=batch.require_metamorphic,
        )

    async def compile(
        self,
        *,
        design: EnvironmentDesign,
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
        workspace: Path,
        lineage_id: str,
        budget: Budget,
        permissions: PermissionScope,
        repair_findings: Sequence[Finding] = (),
        repair_authority: StructuredRepairAuthority | None = None,
    ) -> CompiledVerifier:
        self.artifacts.require_exact_json(
            design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        self.artifacts.require_exact_json(
            world_spec_ref,
            design.world_spec,
            artifact_types=("design.world_spec", "expansion.world_spec"),
        )
        workspace = workspace.expanduser().resolve()  # noqa: ASYNC240 - bounded setup I/O
        workspace.mkdir(  # noqa: ASYNC240 - bounded setup I/O
            parents=True,
            exist_ok=True,
        )
        if any(finding.owner != "verifier" for finding in repair_findings):
            raise ValueError("Verifier repair accepts only verifier-owned Findings")
        tasks = design.curriculum.task_types
        if len(tasks) > self.maximum_task_shards:
            raise VerifierCompilationError(
                f"Verifier compilation exceeds {self.maximum_task_shards} task shards"
            )
        rule_assignments = self._assign_required_rules(design)
        property_assignments = self._assign_required_property_families(
            design,
            rule_assignments,
        )
        task_batches = tuple(
            tasks[index : index + self.maximum_tasks_per_batch]
            for index in range(0, len(tasks), self.maximum_tasks_per_batch)
        )
        batch_case_quotas = self._semantic_case_quotas(len(task_batches))
        batch_budgets = self._batch_budgets(budget, len(task_batches))
        batch_contexts: list[dict[str, JsonValue]] = []
        batch_rule_ids: list[tuple[str, ...]] = []
        batch_property_families: list[tuple[str, ...]] = []
        for batch_index, task_batch in enumerate(task_batches):
            task_types = tuple(task.task_type for task in task_batch)
            rule_ids = tuple(
                rule_id for task in task_batch for rule_id in rule_assignments[task.task_type]
            )
            property_families = tuple(
                sorted(
                    {
                        family
                        for task in task_batch
                        for family in property_assignments[task.task_type]
                    }
                )
            )
            batch_rule_ids.append(rule_ids)
            batch_property_families.append(property_families)
            context = self._challenger_context(
                design,
                task_types=task_types,
                required_rule_ids=rule_ids,
                required_property_families=property_families,
                require_metamorphic=(
                    bool(design.verification.required_metamorphic_relations) and batch_index == 0
                ),
            )
            context["semantic_case_limit"] = batch_case_quotas[batch_index]
            batch_contexts.append(context)
        self._write_json(
            workspace / "verifier-plan.json",
            {
                "schema_version": "agent-world.challenger-plan.v2",
                "strategy": "capacity_batches",
                "maximum_tasks_per_batch": self.maximum_tasks_per_batch,
                "batches": [
                    {
                        "index": batch_index,
                        "task_types": [task.task_type for task in task_batch],
                        "context_hash": sha256_digest(canonical_json_bytes(context)),
                        "required_rule_count": len(batch_rule_ids[batch_index]),
                        "required_property_families": list(batch_property_families[batch_index]),
                        "semantic_case_limit": batch_case_quotas[batch_index],
                    }
                    for batch_index, (task_batch, context) in enumerate(
                        zip(task_batches, batch_contexts, strict=True)
                    )
                ],
            },
        )

        repair_suffix = ""
        if repair_findings:
            summaries = "\n".join(
                f"- {finding.category}: {finding.summary}" for finding in repair_findings
            )
            repair_suffix = (
                "\nFramework Judge rejected the prior independent verifier proposal. "
                "Create a new verifier revision that addresses these safe summaries without "
                "reading Runtime source or inventing new WorldSpec rules:\n"
                f"{summaries}\n"
            )

        active_invocations: dict[int, set[str]] = {
            index: set() for index in range(len(task_batches))
        }
        batch_accounting = {index: _VerifierBatchAccounting() for index in range(len(task_batches))}

        async def compile_batch(
            batch_index: int,
            task_batch: Sequence[TaskRequirement],
            context: dict[str, JsonValue],
            batch_budget: Budget,
            accounting: _VerifierBatchAccounting,
        ) -> tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]:
            batch_workspace = workspace / "batches" / f"{batch_index:02d}"
            batch_workspace.mkdir(parents=True, exist_ok=True)
            self._write_json(batch_workspace / "verifier-context.json", context)
            allowed_task_types = tuple(task.task_type for task in task_batch)
            required_rule_ids = batch_rule_ids[batch_index]
            required_property_families = batch_property_families[batch_index]

            def validate_batch(intent: VerifierIntent) -> None:
                if len(intent.cases) > batch_case_quotas[batch_index]:
                    raise StructuredValidationError(
                        ValidationDiagnostic(
                            owner_component="verifier",
                            validation_phase="intent_capacity",
                            frontier_ordinal=5,
                            issues=(
                                SafeValidationIssue(
                                    "intent_case_capacity_exceeded",
                                    ("cases",),
                                    "Return no more semantic trajectories than the "
                                    "framework-provided semantic_case_limit.",
                                ),
                            ),
                        )
                    )
                self._validate_intent(
                    intent,
                    design,
                    allowed_task_types=allowed_task_types,
                    required_rule_ids=required_rule_ids,
                    required_property_families=required_property_families,
                    require_metamorphic=(
                        bool(design.verification.required_metamorphic_relations)
                        and batch_index == 0
                    ),
                )

            intent, invocation_results = await self._run_structured(
                lineage_id=f"{lineage_id}.batch.{batch_index}",
                workspace=batch_workspace,
                model=VerifierIntent,
                prompt=self._prompt(context) + repair_suffix,
                semantic_validator=validate_batch,
                budget=batch_budget,
                permissions=permissions,
                repair_authority=repair_authority,
                repair_target=RepairTargetRef(
                    target_id=sha256_digest(
                        canonical_json_bytes(
                            {
                                "lineage_id": lineage_id,
                                "batch_index": batch_index,
                                "slot": "verifier_intent_batch",
                            }
                        )
                    ),
                    component="verifier",
                    artifact_slot="verifier_intent_batch",
                    lineage_id=f"{lineage_id}.batch.{batch_index}",
                    batch_id=f"batch-{batch_index}",
                    immutable_input_refs=(design_ref, world_spec_ref),
                    allowed_mutation_paths=("/",),
                ),
                active_invocation_ids=active_invocations[batch_index],
                accounting=accounting,
            )
            checkpoint_ref = self._persist_intent_checkpoint(
                lineage_id=lineage_id,
                batch_index=batch_index,
                context=context,
                intent=intent,
                invocation_results=invocation_results,
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
            )
            accounting.record_checkpoint(checkpoint_ref)
            try:
                draft = self._compile_intent(
                    intent,
                    design,
                    allowed_task_types=allowed_task_types,
                    required_rule_ids=required_rule_ids,
                    required_property_families=required_property_families,
                    require_metamorphic=(
                        bool(design.verification.required_metamorphic_relations)
                        and batch_index == 0
                    ),
                )
                self._validate_draft(
                    draft,
                    design,
                    allowed_task_types=allowed_task_types,
                    required_rule_ids=required_rule_ids,
                    required_property_families=required_property_families,
                    require_metamorphic=(
                        bool(design.verification.required_metamorphic_relations)
                        and batch_index == 0
                    ),
                )
            except VerifierCompilationError:
                raise
            except Exception as exc:
                raise VerifierCompilationError(
                    "framework failed to compile a validated VerifierIntent batch",
                    invocation_results=invocation_results,
                    checkpoint_refs=(checkpoint_ref,),
                ) from exc
            return draft, invocation_results, checkpoint_ref

        batch_results: tuple[VerifierBatchResult, ...] = await self._supervise_capacity_batches(
            lineage_id=lineage_id,
            design_ref=design_ref,
            world_spec_ref=world_spec_ref,
            jobs=tuple(
                compile_batch(
                    batch_index,
                    task_batch,
                    context,
                    batch_budget,
                    batch_accounting[batch_index],
                )
                for batch_index, (task_batch, context, batch_budget) in enumerate(
                    zip(task_batches, batch_contexts, batch_budgets, strict=True)
                )
            ),
            active_invocations=active_invocations,
            batch_accounting=batch_accounting,
            turn_token_upper_bounds={
                index: max(1, item.llm_tokens // item.agent_turns)
                for index, item in enumerate(batch_budgets)
            },
        )
        successful = cast(
            tuple[tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef], ...],
            batch_results,
        )
        invocation_results = tuple(
            invocation for _draft, results, _checkpoint_ref in successful for invocation in results
        )
        checkpoint_refs = tuple(item[2] for item in successful)
        try:
            draft = self._merge_batch_drafts(tuple(item[0] for item in successful))
            self._validate_draft(draft, design)
            verifier = VerifierIR(
                verifier_ir_id=f"verifier:{uuid.uuid4().hex}",
                revision=1,
                world_spec_ref=world_spec_ref,
                design_ref=design_ref,
                properties=draft.properties,
                cases=draft.cases,
                solve_recipes=draft.solve_recipes,
            )
            projection = verifier.persistence_projection()
            verifier_ref = self.artifacts.put_json(
                artifact_id=f"{lineage_id}:verifier-ir-projection",
                artifact_type="judge.verifier_ir_projection",
                value=projection,
                dependencies=(design_ref, world_spec_ref, *checkpoint_refs),
            )
        except VerifierCompilationError as exc:
            aggregate = _VerifierBatchAccounting()
            for result in invocation_results:
                aggregate.record_result(result)
            for checkpoint_ref in checkpoint_refs:
                aggregate.record_checkpoint(checkpoint_ref)
            aggregate.absorb_error(exc)
            accounting_snapshot = aggregate.snapshot()
            raise VerifierCompilationError(
                str(exc),
                result=exc.result,
                permission_denied=exc.permission_denied,
                invocation_results=accounting_snapshot.invocation_results,
                unknown_token_upper_bounds=accounting_snapshot.unknown_token_upper_bounds,
                checkpoint_refs=accounting_snapshot.checkpoint_refs,
            ) from exc
        except Exception as exc:
            raise VerifierCompilationError(
                "framework failed after all Verifier batches completed",
                invocation_results=invocation_results,
                checkpoint_refs=checkpoint_refs,
            ) from exc
        return CompiledVerifier(
            verifier=verifier,
            verifier_ref=verifier_ref,
            invocation_results=invocation_results,
            checkpoint_refs=checkpoint_refs,
        )

    async def _supervise_capacity_batches(
        self,
        *,
        lineage_id: str,
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
        jobs: tuple[Coroutine[Any, Any, VerifierBatchResult], ...],
        active_invocations: Mapping[int, set[str]],
        batch_accounting: Mapping[int, _VerifierBatchAccounting] | None = None,
        turn_token_upper_bounds: Mapping[int, int],
    ) -> tuple[VerifierBatchResult, ...]:
        """Fail fast after a bounded checkpoint grace while cancelling real invocations."""

        tasks: dict[int, asyncio.Task[VerifierBatchResult]] = {
            index: asyncio.create_task(job, name=f"verifier-batch-{index}")
            for index, job in enumerate(jobs)
        }
        index_by_task = {task: index for index, task in tasks.items()}
        accounting_by_batch = {
            index: (
                batch_accounting[index]
                if batch_accounting is not None and index in batch_accounting
                else _VerifierBatchAccounting()
            )
            for index in tasks
        }
        pending: set[asyncio.Task[VerifierBatchResult]] = set(tasks.values())
        successful: dict[int, VerifierBatchResult] = {}
        fatal: tuple[int, BaseException] | None = None

        def observe_task(
            task: asyncio.Task[VerifierBatchResult],
        ) -> tuple[VerifierBatchResult | None, BaseException | None]:
            index = index_by_task[task]
            accounting = accounting_by_batch[index]
            try:
                result = task.result()
            except BaseException as exc:
                accounting.absorb_error(exc)
                return None, exc
            accounting.record_results(result[1])
            accounting.record_checkpoint(result[2])
            return result, None

        while pending and fatal is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                index = index_by_task[task]
                result, error = observe_task(task)
                if result is not None:
                    successful[index] = result
                elif error is not None and fatal is None:
                    fatal = (index, error)
        if fatal is None:
            return tuple(successful[index] for index in sorted(successful))

        fatal_index, fatal_error = fatal
        if pending and self.batch_failure_grace_seconds:
            grace_done, pending = await asyncio.wait(
                pending,
                timeout=self.batch_failure_grace_seconds,
            )
            for task in grace_done:
                index = index_by_task[task]
                result, error = observe_task(task)
                if result is not None:
                    successful[index] = result
                elif error is not None:
                    # The first observed fatal owns the terminal diagnostic;
                    # sibling failures still contribute their complete batch
                    # accounting without extending the critical path.
                    _ = error

        cancellation_started = monotonic()
        for task in tuple(pending):
            index = index_by_task[task]
            accounting = accounting_by_batch[index]
            for invocation_id in tuple(active_invocations[index]):
                accounting.record_unknown_invocation(
                    invocation_id,
                    turn_token_upper_bounds[index],
                )
            accounting.record_all_active_as_unknown()
            self._persist_batch_control(
                lineage_id=lineage_id,
                batch_index=index,
                status="cancel_requested",
                fatal_batch_index=fatal_index,
                elapsed_ms=0,
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
            )
        cancellation_calls = [
            asyncio.create_task(self.backend.cancel(invocation_id))
            for task in pending
            for invocation_id in tuple(active_invocations[index_by_task[task]])
        ]
        if cancellation_calls:
            cancel_done, still_cancelling = await asyncio.wait(
                cancellation_calls,
                timeout=self.cancellation_timeout_seconds,
            )
            for cancel_task in still_cancelling:
                cancel_task.cancel()
            if still_cancelling:
                await asyncio.gather(*still_cancelling, return_exceptions=True)
            for cancel_task in cancel_done:
                with suppress(BaseException):
                    cancel_task.result()
        for task in pending:
            task.cancel()
        if pending:
            cancelled, abandoned = await asyncio.wait(
                pending,
                timeout=self.cancellation_timeout_seconds,
            )
        else:
            cancelled, abandoned = set(), set()
        elapsed_ms = max(0, int((monotonic() - cancellation_started) * 1_000))
        for task in cancelled:
            index = index_by_task[task]
            observe_task(task)
            self._persist_batch_control(
                lineage_id=lineage_id,
                batch_index=index,
                status="cancelled",
                fatal_batch_index=fatal_index,
                elapsed_ms=elapsed_ms,
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
            )
        accounting_snapshots = tuple(
            accounting_by_batch[index].snapshot() for index in sorted(accounting_by_batch)
        )
        for task in abandoned:
            index = index_by_task[task]
            task.add_done_callback(self._consume_abandoned_task)
            self._persist_batch_control(
                lineage_id=lineage_id,
                batch_index=index,
                status="abandoned",
                fatal_batch_index=fatal_index,
                elapsed_ms=elapsed_ms,
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
            )
        accounted_results = tuple(
            result for snapshot in accounting_snapshots for result in snapshot.invocation_results
        )
        accounted_unknown_bounds = tuple(
            token_upper_bound
            for snapshot in accounting_snapshots
            for token_upper_bound in snapshot.unknown_token_upper_bounds
        )
        accounted_checkpoints = tuple(
            checkpoint_ref
            for snapshot in accounting_snapshots
            for checkpoint_ref in snapshot.checkpoint_refs
        )
        if isinstance(fatal_error, VerifierCompilationError):
            raise VerifierCompilationError(
                str(fatal_error),
                fatal_error.result,
                permission_denied=fatal_error.permission_denied,
                invocation_results=accounted_results,
                unknown_token_upper_bounds=accounted_unknown_bounds,
                checkpoint_refs=accounted_checkpoints,
            ) from fatal_error
        raise VerifierCompilationError(
            f"Verifier capacity batch {fatal_index} failed with {type(fatal_error).__name__}",
            invocation_results=accounted_results,
            unknown_token_upper_bounds=accounted_unknown_bounds,
            checkpoint_refs=accounted_checkpoints,
        ) from fatal_error

    @staticmethod
    def _consume_abandoned_task(task: asyncio.Task[object]) -> None:
        with suppress(BaseException):
            task.result()

    def _persist_batch_control(
        self,
        *,
        lineage_id: str,
        batch_index: int,
        status: str,
        fatal_batch_index: int,
        elapsed_ms: int,
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
    ) -> ArtifactRef:
        return self.artifacts.put_json(
            artifact_id=f"{lineage_id}:verifier-batch-control:{batch_index}",
            artifact_type="judge.verifier_batch_control",
            value={
                "schema_version": "agent-world.verifier-batch-control.v1",
                "batch_index": batch_index,
                "status": status,
                "fatal_batch_index": fatal_batch_index,
                "cancellation_elapsed_ms": elapsed_ms,
            },
            dependencies=(design_ref, world_spec_ref),
        )

    async def _run_structured(
        self,
        *,
        lineage_id: str,
        workspace: Path,
        model: type[TOutput],
        prompt: str,
        semantic_validator: Callable[[TOutput], None],
        budget: Budget,
        permissions: PermissionScope,
        repair_authority: StructuredRepairAuthority | None = None,
        repair_target: RepairTargetRef | None = None,
        active_invocation_ids: set[str] | None = None,
        accounting: _VerifierBatchAccounting | None = None,
    ) -> tuple[TOutput, tuple[InvocationResult, ...]]:
        try:
            assert_agent_output_advisory(
                model,
                authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
            )
            profile = self.profiles.resolve(
                role="challenger",
                lineage_id=lineage_id,
                workspace=workspace,
                output_schema=model.model_json_schema(mode="validation"),
                permissions=permissions,
                requirement=NodeCapabilityRequirement.structured_output(
                    node_id="challenger.verifier-compile",
                    role="challenger",
                ),
                rollout_token_limit=budget.llm_tokens // budget.agent_turns,
                invocation_timeout_seconds=budget.wall_seconds,
            )
        except CapabilityResolutionError as exc:
            raise VerifierCompilationError(
                str(exc),
                permission_denied=True,
            ) from exc
        except ProfileResolutionError as exc:
            raise VerifierCompilationError(
                "Verifier Direct profile could not be materialized",
                safe_code="verifier_profile_resolution_error",
                safe_category=(
                    "Verifier Direct profile resolution category: "
                    f"{safe_profile_resolution_category(exc)}"
                ),
                retryable=False,
                expected_category=(
                    "a Direct Challenger profile with the reported profile-resolution "
                    "category corrected"
                ),
                remediation=(
                    "Inspect the safe Direct profile-resolution category and the shared "
                    "Agent/Direct profile construction path; do not edit the Prompt "
                    "or Runtime Skill."
                ),
            ) from exc
        # Verifier semantics are prompt-only Direct LLM work. A correction is
        # a fresh physical request containing the immutable context plus its
        # authorized framework feedback, never a hidden Codex thread resume.
        session = None
        immutable_prompt = render_direct_structured_prompt(
            prompt,
        )
        current_prompt = immutable_prompt
        results: list[InvocationResult] = []
        batch_accounting = accounting or _VerifierBatchAccounting()
        active_repair_entry: str | None = None

        async def complete_repair(
            remaining_issue_codes: tuple[str, ...],
            diagnostic: ValidationDiagnostic | None = None,
        ) -> None:
            nonlocal active_repair_entry
            if active_repair_entry is None or repair_authority is None:
                active_repair_entry = None
                return
            try:
                await repair_authority.complete(
                    active_repair_entry,
                    remaining_issue_codes=remaining_issue_codes,
                    continued_session=False,
                    remaining_diagnostic=diagnostic,
                )
            except Exception as exc:
                raise VerifierCompilationError(
                    f"global RepairLedger completion failed: {type(exc).__name__}",
                    invocation_results=results,
                ) from exc
            active_repair_entry = None

        async def authorize_repair(
            issue_codes: tuple[str, ...],
            diagnostic: ValidationDiagnostic | None = None,
            *,
            repair_mode: StructuredRepairMode = StructuredRepairMode.CONTRACT_CORRECTION,
        ) -> None:
            nonlocal active_repair_entry
            if repair_authority is None:
                return
            try:
                if repair_target is None:
                    active_repair_entry = await repair_authority.authorize(
                        owner_node="verifier",
                        lineage_id=lineage_id,
                        role="challenger",
                        repair_mode=repair_mode,
                        issue_codes=issue_codes,
                        continued_session=False,
                        diagnostic=diagnostic,
                    )
                else:
                    active_repair_entry = await repair_authority.authorize(
                        owner_node="verifier",
                        lineage_id=lineage_id,
                        role="challenger",
                        repair_mode=repair_mode,
                        issue_codes=issue_codes,
                        continued_session=False,
                        diagnostic=diagnostic,
                        feedback_contract_id="feedback.verifier.intent",
                        repair_target=repair_target,
                    )
            except StructuredRepairDenied as exc:
                raise VerifierCompilationError(
                    "global RepairLedger rejected another Verifier correction",
                    invocation_results=results,
                ) from exc
            except Exception as exc:
                raise VerifierCompilationError(
                    f"global RepairLedger authorization failed: {type(exc).__name__}",
                    invocation_results=results,
                ) from exc

        for attempt in range(self.maximum_structured_reworks + 1):
            if attempt >= budget.agent_turns:
                await complete_repair(("verifier_budget_exhausted",))
                raise VerifierCompilationError(
                    "Verifier compilation exhausted its reserved Agent turns",
                    invocation_results=results,
                )
            try:
                invocation_id = f"inv-{uuid.uuid4().hex}"
                token_upper_bound = profile.rollout_token_limit or max(
                    1, budget.llm_tokens // budget.agent_turns
                )
                batch_accounting.begin_invocation(invocation_id, token_upper_bound)
                if active_invocation_ids is not None:
                    active_invocation_ids.add(invocation_id)
                try:
                    result = await self.backend.invoke(
                        InvocationRequest(
                            invocation_id=invocation_id,
                            prompt=current_prompt,
                            profile=profile,
                            session=session,
                            ownership=standalone_component_ownership(
                                invocation_id=invocation_id,
                                component="judge",
                                coordinate="judge:legacy_verifier",
                            ),
                            metadata={
                                "role": "challenger",
                                "lineage_id": lineage_id,
                                "attempt": attempt,
                            },
                            execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
                        )
                    )
                except asyncio.CancelledError:
                    batch_accounting.record_unknown_invocation(
                        invocation_id,
                        token_upper_bound,
                    )
                    raise
                except Exception:
                    batch_accounting.record_unknown_invocation(
                        invocation_id,
                        token_upper_bound,
                    )
                    raise
                else:
                    batch_accounting.record_result(result)
                finally:
                    if active_invocation_ids is not None:
                        active_invocation_ids.discard(invocation_id)
            except Exception as exc:
                await complete_repair(("verifier_backend_execution",))
                raise VerifierCompilationError(
                    f"Verifier backend raised {type(exc).__name__}",
                    invocation_results=results,
                    unknown_token_upper_bounds=(token_upper_bound,),
                ) from exc
            results.append(result)
            if not result.succeeded:
                backend_code = (
                    result.error.code if result.error is not None else result.status.value
                )
                backend_issue = f"verifier_backend:{backend_code}"
                await complete_repair((backend_issue,))
                # A physical provider/transport terminal is not retried here.
                # The Invocation Control Plane has already classified and
                # durably settled it, and Scheduler/WorkRuntime owns the one
                # authorized fresh-session retry plus the explicit model
                # fallback.  This loop spends Agent turns only on semantic
                # corrections against a parsed VerifierIR candidate.
                message = result.error.message if result.error else result.status.value
                raise VerifierCompilationError(
                    message,
                    result,
                    invocation_results=results,
                )
            try:
                if result.structured_output is None:
                    raise ValueError("Challenger returned no structured output")
                output = model.model_validate_json(canonical_json_bytes(result.structured_output))
                semantic_validator(output)
                await complete_repair(())
                return output, tuple(results)
            except (ValidationError, ValueError) as exc:
                diagnostic = self._validation_diagnostic(exc)
                issue_codes = diagnostic.issue_codes
                await complete_repair(issue_codes, diagnostic)
                if attempt >= self.maximum_structured_reworks:
                    raise VerifierCompilationError(
                        "Verifier IR remained invalid at framework phase "
                        f"{diagnostic.validation_phase}: {', '.join(issue_codes)}",
                        result,
                        invocation_results=results,
                    ) from exc
                if any(not issue.retryable for issue in diagnostic.issues):
                    raise VerifierCompilationError(
                        "Verifier IR reached a non-actionable framework diagnostic; "
                        "refusing to spend an Agent repair turn",
                        result,
                        invocation_results=results,
                    ) from exc
                await authorize_repair(issue_codes, diagnostic)
                current_prompt = (
                    immutable_prompt
                    + "\n\n"
                    + (
                        "The previous VerifierIntent violated the framework contract. Correct the "
                        "same artifact without reading or changing Runtime code. "
                        f"Framework-authored safe diagnostics:\n{diagnostic.feedback}"
                    )
                )
        raise AssertionError("unreachable verifier compilation state")

    @staticmethod
    def _validation_diagnostic(exc: ValidationError | ValueError) -> ValidationDiagnostic:
        """Map private Verifier failures to safe, stable semantic identities."""

        if isinstance(exc, StructuredValidationError):
            return exc.diagnostic
        if isinstance(exc, ValidationError):
            diagnostic = pydantic_validation_diagnostic(
                exc,
                owner_component="verifier",
                validation_phase="intent_schema",
                frontier_ordinal=10,
            )
            if any(issue.code == "schema_value_error" for issue in diagnostic.issues):
                return ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="framework_diagnostic",
                    frontier_ordinal=10,
                    issues=(
                        SafeValidationIssue(
                            "framework_diagnostic_incomplete",
                            ("intent",),
                            "A framework-authored semantic validator lacks a typed safe "
                            "diagnostic. Do not retry the Agent until the contract is fixed.",
                            retryable=False,
                        ),
                    ),
                )
            return diagnostic
        message = str(exc)
        mappings: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
            (
                "no structured output",
                "intent_output_missing",
                ("intent",),
                "Return one complete VerifierIntent object matching the output schema.",
            ),
            (
                "task scope is unknown",
                "intent_task_scope_unknown",
                ("intent", "cases"),
                "Every case must use a task type in the assigned batch.",
            ),
            (
                "case ids must be unique",
                "intent_case_id_duplicate",
                ("intent", "cases"),
                "Give every trajectory case a unique identifier.",
            ),
            (
                "requires public and sealed trajectories",
                "intent_partition_coverage",
                ("intent", "cases"),
                "Include both public and sealed trajectory partitions.",
            ),
            (
                "outside this task batch",
                "intent_task_outside_batch",
                ("intent", "cases"),
                "Use only task types assigned to this capacity batch.",
            ),
            (
                "uses a disallowed actor",
                "intent_actor_not_allowed",
                ("intent", "cases", "actor"),
                "Choose an actor allowed by the selected task requirement.",
            ),
            (
                "violates schema",
                "intent_value_schema_mismatch",
                ("intent", "cases"),
                "Make goal, reset, and action values satisfy their frozen closed schemas.",
            ),
            (
                "uses unknown tools",
                "intent_tool_unknown",
                ("intent", "cases", "actions"),
                "Use only tools from the frozen ToolContractSet.",
            ),
            (
                "requires a canonical expectation",
                "intent_expectation_missing",
                ("intent", "cases", "expectations"),
                "Attach at least one canonical framework property intention to every case.",
            ),
            (
                "omits tools",
                "intent_required_tool_coverage",
                ("intent", "cases", "actions"),
                "Cover every tool required by each task in at least one trajectory.",
            ),
            (
                "lacks a minimum-length trajectory",
                "intent_trajectory_too_short",
                ("intent", "cases", "actions"),
                "Include a trajectory meeting the task minimum tool-call length.",
            ),
            (
                "solve recipe ids must be unique",
                "intent_recipe_id_duplicate",
                ("intent", "solve_recipes"),
                "Give every solve recipe a unique identifier.",
            ),
            (
                "preferred solve recipe",
                "intent_recipe_preference_duplicate",
                ("intent", "solve_recipes"),
                "Mark at most one preferred solve recipe for each task type.",
            ),
            (
                "recipe",
                "intent_recipe_invalid",
                ("intent", "solve_recipes"),
                "Keep every recipe inside its task, tool, schema, and public visibility contract.",
            ),
            (
                "omits property intentions",
                "intent_property_family_coverage",
                ("intent", "cases", "expectations"),
                "Cover every property family assigned to this capacity batch.",
            ),
            (
                "requires a metamorphic trajectory intention",
                "intent_metamorphic_missing",
                ("intent", "cases", "expectations"),
                "Include the required metamorphic trajectory intention.",
            ),
        )
        for fragment, code, location, feedback in mappings:
            if fragment in message:
                phase = "solve_recipe" if "recipe" in code else "intent_semantics"
                frontier = 25 if phase == "solve_recipe" else 20
                return ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase=phase,
                    frontier_ordinal=frontier,
                    issues=(SafeValidationIssue(code, location, feedback),),
                )
        return ValidationDiagnostic(
            owner_component="verifier",
            validation_phase="rule_binding",
            frontier_ordinal=30,
            issues=(
                SafeValidationIssue(
                    "intent_rule_binding_invalid",
                    ("intent", "cases"),
                    "The proposal does not bind the complete assigned Rule closure to valid "
                    "public, sealed, and negative obligations.",
                ),
            ),
        )

    @staticmethod
    def _validate_intent(
        intent: VerifierIntent,
        design: EnvironmentDesign,
        *,
        allowed_task_types: Sequence[str],
        required_rule_ids: Sequence[str],
        required_property_families: Sequence[str],
        require_metamorphic: bool,
    ) -> None:
        """Validate compact trajectories before deterministic Rule expansion."""

        tasks = {
            item.task_type: item
            for item in design.curriculum.task_types
            if item.task_type in set(allowed_task_types)
        }
        tools = {item.surface.tool_id: item for item in design.world_spec.tools}
        error_codes_by_tool = {
            tool_id: tuple(error.error_code for error in tool.semantics.errors)
            for tool_id, tool in tools.items()
        }
        if len(tasks) != len(set(allowed_task_types)):
            raise ValueError("VerifierIntent task scope is unknown")
        requirements_by_id = {
            item.requirement_id: item
            for item in VerifierCompiler._semantic_requirements(design, required_rule_ids)
        }
        reference_issues: list[SafeValidationIssue] = []
        for case_index, case in enumerate(intent.cases):
            seen_expectations: dict[tuple[str, int], bool] = {}
            for expectation_index, expectation in enumerate(case.expectations):
                location = (
                    "cases",
                    case_index,
                    "expectations",
                    expectation_index,
                    "after_action_ordinal",
                )
                if expectation.after_action_ordinal > len(case.actions):
                    reference_issues.append(
                        SafeValidationIssue(
                            "intent_action_ordinal_out_of_range",
                            location,
                            "Use a one-based action ordinal between 1 and the number of "
                            f"actions in this case ({len(case.actions)}).",
                            violated_condition=(
                                "each expectation must point to an action in its own case"
                            ),
                            expected_category=(
                                "a one-based after_action_ordinal between 1 and the number of "
                                "actions in that case"
                            ),
                            remediation=(
                                "Point the expectation at an existing action in the same case."
                            ),
                        )
                    )
                key = (expectation.requirement_id, expectation.after_action_ordinal)
                previous_expected = seen_expectations.get(key)
                if key in seen_expectations and previous_expected == expectation.expected:
                    reference_issues.append(
                        SafeValidationIssue(
                            "intent_expectation_duplicate",
                            location,
                            "Each (requirement_id, after_action_ordinal, expected) combination may "
                            "appear only once in a case.",
                            violated_condition=(
                                "each case must contain at most one expectation with the same "
                                "requirement_id, after_action_ordinal, and expected value"
                            ),
                            expected_category=(
                                "one expectation for each unique (requirement_id, "
                                "after_action_ordinal, expected) combination"
                            ),
                            remediation=(
                                "Remove the duplicate expectation or target another requirement_id."
                            ),
                        )
                    )
                elif key in seen_expectations:
                    reference_issues.append(
                        SafeValidationIssue(
                            "intent_expectation_polarity_conflict",
                            (
                                "cases",
                                case_index,
                                "expectations",
                                expectation_index,
                                "expected",
                            ),
                            "One action point cannot be expected to both satisfy and violate "
                            "the same selected semantic requirement.",
                            violated_condition=(
                                "each semantic trajectory has one expected polarity for each "
                                "requirement_id and after_action_ordinal"
                            ),
                            expected_category=(
                                "one expected polarity per requirement/action ordinal; an opposite "
                                "polarity must use a separate negative trajectory"
                            ),
                            remediation=(
                                "Move the opposite expectation to a distinct trajectory whose "
                                "domain reset input or action can really produce the opposite "
                                "outcome; do not add true and false expectations to one action."
                            ),
                        )
                    )
                else:
                    seen_expectations[key] = expectation.expected
        if reference_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="intent_references",
                    frontier_ordinal=15,
                    issues=tuple(reference_issues),
                )
            )

        observed_kinds: set[str] = set()
        value_schema_issues: list[SafeValidationIssue] = []
        error_selector_issues: list[SafeValidationIssue] = []
        requirement_binding_issues: list[SafeValidationIssue] = []
        for case_index, case in enumerate(intent.cases):
            requirement = tasks.get(case.task_type)
            if requirement is None:
                raise ValueError(
                    f"VerifierIntent case at index {case_index} is outside this task batch"
                )
            if case.actor not in requirement.allowed_actor_ids:
                raise ValueError(
                    f"VerifierIntent case at index {case_index} uses a disallowed actor"
                )
            for label, schema, value in (
                ("evaluator_goal", requirement.evaluator_goal_schema, case.evaluator_goal),
                ("reset_config", requirement.initial_config_schema, case.reset_config),
            ):
                value_schema_issues.extend(
                    VerifierCompiler._json_schema_issues(
                        schema=schema,
                        value=value,
                        location=("cases", case_index, label),
                        code=f"intent_{label}_schema_mismatch",
                        value_label=label,
                    )
                )
            unknown_tools = {item.tool_id for item in case.actions} - set(tools)
            if unknown_tools:
                raise ValueError(
                    f"VerifierIntent case at index {case_index} uses unknown tools: "
                    f"{sorted(unknown_tools)}"
                )
            for action_index, action in enumerate(case.actions):
                tool = tools[action.tool_id]
                if case.actor not in tool.semantics.permission.allowed_actors:
                    requirement_binding_issues.append(
                        SafeValidationIssue(
                            "intent_action_actor_permission_denied",
                            ("cases", case_index, "actions", action_index, "tool_id"),
                            "The case actor is not permitted to invoke this frozen tool.",
                            violated_condition=(
                                "every action in a one-actor verifier case must be permitted "
                                "to that case actor"
                            ),
                            expected_category=(
                                "a tool permitted to the case actor, or a separate case for "
                                "another permitted actor"
                            ),
                            remediation=(
                                "Use only tools whose allowed_actor_ids include this case actor; "
                                "split a cross-role workflow into separate actor-bound cases."
                            ),
                        )
                    )
                value_schema_issues.extend(
                    VerifierCompiler._json_schema_issues(
                        schema=tool.surface.input_schema,
                        value=action.arguments,
                        location=("cases", case_index, "actions", action_index, "arguments"),
                        code="intent_action_input_schema_mismatch",
                        value_label="action input",
                    )
                )
            for expectation_index, expectation in enumerate(case.expectations):
                requirement_location = (
                    "cases",
                    case_index,
                    "expectations",
                    expectation_index,
                    "requirement_id",
                )
                semantic_requirement = requirements_by_id.get(expectation.requirement_id)
                # The reference pass has already emitted the actionable ordinal
                # diagnostic.  Do not turn that model-visible error into an
                # internal IndexError while collecting the other safe issues.
                if expectation.action_index >= len(case.actions):
                    continue
                action = case.actions[expectation.action_index]
                if semantic_requirement is None:
                    requirement_binding_issues.append(
                        SafeValidationIssue(
                            "intent_requirement_unknown",
                            requirement_location,
                            "requirement_id is not present in this frozen "
                            "semantic_requirements catalog.",
                            violated_condition=(
                                "every expectation must select one requirement_id from the current "
                                "frozen batch catalog"
                            ),
                            expected_category=(
                                "one requirement_id copied exactly from semantic_requirements"
                            ),
                            remediation=(
                                "Replace it with the matching requirement_id shown in the current "
                                "semantic_requirements catalog; do not invent selectors."
                            ),
                        )
                    )
                else:
                    if semantic_requirement.property_kind != expectation.kind:
                        requirement_binding_issues.append(
                            SafeValidationIssue(
                                "intent_requirement_kind_mismatch",
                                requirement_location,
                                "The selected requirement_id has a different property_kind.",
                                violated_condition=(
                                    "an expectation kind must equal its selected requirement's "
                                    "property_kind"
                                ),
                                expected_category=(
                                    f"kind={semantic_requirement.property_kind} for the selected "
                                    "requirement_id"
                                ),
                                remediation=(
                                    "Keep the selected requirement_id and use its property_kind, "
                                    "or "
                                    "select the requirement_id for this expectation kind."
                                ),
                            )
                        )
                    if (
                        semantic_requirement.task_type is not None
                        and semantic_requirement.task_type != case.task_type
                    ):
                        requirement_binding_issues.append(
                            SafeValidationIssue(
                                "intent_requirement_task_mismatch",
                                requirement_location,
                                "The selected requirement belongs to a different task type.",
                                violated_condition=(
                                    "a task-scoped requirement must be exercised by a case for its "
                                    "own task_type"
                                ),
                                expected_category=(
                                    f"task_type={semantic_requirement.task_type} for the selected "
                                    "requirement_id"
                                ),
                                remediation=(
                                    "Move this expectation to that task type or select a "
                                    "requirement "
                                    "from this case's task_type."
                                ),
                            )
                        )
                    if (
                        semantic_requirement.tool_ids
                        and action.tool_id not in semantic_requirement.tool_ids
                    ):
                        requirement_binding_issues.append(
                            SafeValidationIssue(
                                "intent_requirement_action_tool_mismatch",
                                requirement_location,
                                "The selected requirement is not evaluated at this action tool.",
                                violated_condition=(
                                    "an expectation's action must use one of the selected "
                                    "requirement's "
                                    "tool_ids"
                                ),
                                expected_category=(
                                    "an action using one of: "
                                    + ", ".join(semantic_requirement.tool_ids)
                                ),
                                remediation=(
                                    "Point after_action_ordinal at the compatible tool action, "
                                    "or select "
                                    "the requirement_id for this action tool."
                                ),
                            )
                        )
                selector_location = (
                    "cases",
                    case_index,
                    "expectations",
                    expectation_index,
                    "error_code",
                )
                if expectation.kind != "error_semantics":
                    if expectation.error_code is not None:
                        error_selector_issues.append(
                            SafeValidationIssue(
                                "intent_error_code_forbidden",
                                selector_location,
                                "error_code is allowed only for an error_semantics expectation.",
                                violated_condition=(
                                    "only an error_semantics expectation selects a Runtime "
                                    "error path"
                                ),
                                expected_category=(
                                    "no error_code for a non-error_semantics expectation"
                                ),
                                remediation=(
                                    "Remove error_code, or change this expectation kind to "
                                    "error_semantics when it deliberately exercises an error path."
                                ),
                            )
                        )
                    continue
                declared_codes = error_codes_by_tool[action.tool_id]
                if not declared_codes:
                    error_selector_issues.append(
                        SafeValidationIssue(
                            "intent_error_semantics_unsupported",
                            selector_location,
                            "This action tool declares no Runtime error paths to exercise.",
                            violated_condition=(
                                "an error_semantics expectation must target a tool with "
                                "declared errors"
                            ),
                            expected_category=(
                                "an error_semantics expectation for a tool with declared "
                                "error codes"
                            ),
                            remediation=(
                                "Choose a different action with declared errors, or use the "
                                "property family that describes this action."
                            ),
                        )
                    )
                elif expectation.error_code is None and len(declared_codes) > 1:
                    codes = ", ".join(declared_codes)
                    error_selector_issues.append(
                        SafeValidationIssue(
                            "intent_error_code_required",
                            selector_location,
                            "Select one declared error_code for this multi-error tool.",
                            violated_condition=(
                                "one Runtime action can exercise only one declared error path"
                            ),
                            expected_category=(
                                f"one declared error_code for {action.tool_id}: {codes}"
                            ),
                            remediation=(
                                "Set error_code to the one path this action and reset input are "
                                "intended to exercise; use a separate trajectory for another path."
                            ),
                        )
                    )
                elif (
                    expectation.error_code is not None
                    and expectation.error_code not in declared_codes
                ):
                    codes = ", ".join(declared_codes)
                    error_selector_issues.append(
                        SafeValidationIssue(
                            "intent_error_code_unknown",
                            selector_location,
                            "error_code is not declared by this action tool.",
                            violated_condition=(
                                "an error_semantics selector must name one error declared "
                                "by its action tool"
                            ),
                            expected_category=(
                                f"one declared error_code for {action.tool_id}: {codes}"
                            ),
                            remediation=(
                                "Choose one of the tool's declared error codes, or select the "
                                "tool whose error path this trajectory actually exercises."
                            ),
                        )
                    )
                if (
                    semantic_requirement is not None
                    and expectation.error_code is not None
                    and semantic_requirement.error_code != expectation.error_code
                ):
                    expected_error = semantic_requirement.error_code or "(no error code)"
                    requirement_binding_issues.append(
                        SafeValidationIssue(
                            "intent_requirement_error_code_mismatch",
                            requirement_location,
                            "The selected error requirement does not match error_code.",
                            violated_condition=(
                                "an error_semantics expectation must select the error_code "
                                "bound to its "
                                "requirement_id"
                            ),
                            expected_category=(
                                f"error_code={expected_error} for the selected requirement_id"
                            ),
                            remediation=(
                                "Use the selected requirement's error_code, or select the "
                                "requirement_id "
                                "for the error path this trajectory exercises."
                            ),
                        )
                    )
            canonical = {
                item.kind
                for item in case.expectations
                if item.kind in _CANONICAL_PROPERTY_KIND.values()
            }
            if not canonical:
                raise ValueError(
                    f"VerifierIntent case at index {case_index} requires a canonical expectation"
                )
            observed_kinds.update(str(item.kind) for item in case.expectations)

        if value_schema_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="intent_value_schemas",
                    frontier_ordinal=20,
                    issues=tuple(value_schema_issues),
                )
            )

        if error_selector_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="intent_error_semantics",
                    frontier_ordinal=20,
                    issues=tuple(error_selector_issues),
                )
            )

        if requirement_binding_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="intent_requirement_binding",
                    frontier_ordinal=22,
                    issues=tuple(requirement_binding_issues),
                )
            )

        for task_type, requirement in tasks.items():
            cases = [item for item in intent.cases if item.task_type == task_type]
            covered_tools = {action.tool_id for case in cases for action in case.actions}
            missing = set(requirement.required_tool_ids) - covered_tools
            if missing:
                raise ValueError(f"VerifierIntent task {task_type} omits tools: {sorted(missing)}")
            if not any(len(case.actions) >= requirement.minimum_tool_calls for case in cases):
                raise ValueError(
                    f"VerifierIntent task {task_type} lacks a minimum-length trajectory"
                )

        recipe_ids = [item.recipe_id for item in intent.solve_recipes]
        if len(set(recipe_ids)) != len(recipe_ids):
            raise ValueError("VerifierIntent solve recipe ids must be unique")
        preferred = [item.task_type for item in intent.solve_recipes if item.preferred]
        if len(set(preferred)) != len(preferred):
            raise ValueError("each task type may have at most one preferred solve recipe")
        for recipe_index, recipe in enumerate(intent.solve_recipes):
            requirement = tasks.get(recipe.task_type)
            if requirement is None:
                raise ValueError(
                    f"VerifierIntent recipe {recipe.recipe_id} is outside this task batch"
                )
            _validate_solve_recipe(
                recipe,
                requirement=requirement,
                design=design,
                location=("intent", "solve_recipes", recipe_index),
            )
        missing_preferred_recipes = set(tasks) - set(preferred)
        if missing_preferred_recipes:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="solve_recipe",
                    frontier_ordinal=25,
                    issues=(
                        SafeValidationIssue(
                            "intent_release_recipe_missing",
                            ("intent", "solve_recipes"),
                            "This release path has no interactive solver; each assigned task "
                            "needs one preferred ParameterizedSolveRecipe.",
                            violated_condition=(
                                "every assigned task type has exactly one preferred solve recipe"
                            ),
                            expected_category=(
                                "one preferred ParameterizedSolveRecipe for each assigned task type"
                            ),
                            remediation=(
                                "Add one public-input-only preferred recipe for every assigned "
                                "task. Use only declared tools, schema-valid arguments, public "
                                "goal/reset observation pointers, and earlier public results."
                            ),
                        ),
                    ),
                )
            )

        missing_kinds = set(required_property_families) - observed_kinds
        if missing_kinds:
            raise ValueError(f"VerifierIntent omits property intentions: {sorted(missing_kinds)}")
        if require_metamorphic and "metamorphic" not in observed_kinds:
            raise ValueError("VerifierIntent requires a metamorphic trajectory intention")
        # Compilation is also validation: every frozen Rule must have compatible
        # public/sealed/negative trajectory labels before any checkpoint is admitted.
        VerifierCompiler._compile_intent(
            intent,
            design,
            allowed_task_types=allowed_task_types,
            required_rule_ids=required_rule_ids,
            required_property_families=required_property_families,
            require_metamorphic=require_metamorphic,
        )

    @staticmethod
    def _json_schema_issues(
        *,
        schema: dict[str, JsonValue],
        value: JsonValue,
        location: tuple[str | int, ...],
        code: str,
        value_label: str,
    ) -> tuple[SafeValidationIssue, ...]:
        """Return field-addressable schema errors without echoing rejected values."""

        raw_properties = schema.get("properties")
        declared_fields = (
            tuple(str(field) for field in raw_properties)
            if isinstance(raw_properties, dict)
            else ()
        )
        declared_fields_text = ", ".join(declared_fields)[:320] or "(no fields)"
        issues: list[SafeValidationIssue] = []
        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda error: (
                tuple(str(part) for part in error.absolute_path),
                str(error.validator),
            ),
        )
        for error in errors[:64]:
            keyword = str(error.validator or "invalid")
            issue_location = (*location, *tuple(error.absolute_path))
            violated_condition: str | None = None
            expected_category: str | None = None
            remediation: str | None = None
            if keyword == "type":
                expected = error.validator_value
                expected_label = (
                    ", ".join(str(item) for item in expected)
                    if isinstance(expected, list)
                    else str(expected)
                )
                message = f"Use frozen schema type {expected_label} for this {value_label} field."
            elif keyword == "required":
                required = error.validator_value
                missing = (
                    [str(field) for field in required if field not in value]
                    if isinstance(required, list) and isinstance(value, dict)
                    else []
                )
                missing_text = ", ".join(missing)[:320]
                message = (
                    f"Add these fields required by the frozen {value_label} schema: {missing_text}."
                    if missing_text
                    else f"Add every field required by the frozen {value_label} schema here."
                )
            elif keyword == "additionalProperties":
                message = (
                    f"Remove fields not declared by the frozen closed {value_label} schema here. "
                    f"Its declared fields are: {declared_fields_text}."
                )
                violated_condition = (
                    f"this {value_label} is a closed object and permits only fields declared "
                    "by its frozen schema"
                )
                expected_category = (
                    f"a closed {value_label} object using only declared fields: "
                    f"{declared_fields_text}"
                )
                remediation = (
                    f"Remove undeclared {value_label} fields and use only: {declared_fields_text}"
                )
            elif keyword == "enum":
                message = f"Use a value allowed by the frozen {value_label} schema here."
            elif keyword == "format":
                message = f"Use the format declared by the frozen {value_label} schema here."
            elif keyword in {
                "minimum",
                "maximum",
                "minItems",
                "maxItems",
                "minLength",
                "maxLength",
            }:
                message = (
                    f"Satisfy the frozen {value_label} schema constraint "
                    f"{keyword}={error.validator_value} at this field."
                )
            else:
                message = (
                    f"Satisfy the frozen {value_label} schema keyword {keyword} at this field."
                )
            issues.append(
                SafeValidationIssue(
                    code=code,
                    location=issue_location,
                    message=message,
                    violated_condition=violated_condition,
                    expected_category=expected_category,
                    remediation=remediation,
                )
            )
        return tuple(issues)

    @staticmethod
    def _compile_intent(
        intent: VerifierIntent,
        design: EnvironmentDesign,
        *,
        allowed_task_types: Sequence[str],
        required_rule_ids: Sequence[str],
        required_property_families: Sequence[str],
        require_metamorphic: bool,
    ) -> VerifierDraft:
        """Bind selected semantic requirements into the exact trusted Rule closure."""

        bound_cases = VerifierCompiler._bind_intent_cases(intent)
        rules = design_rule_index(design)
        required = VerifierCompiler._runtime_case_rule_ids(
            design,
            required_rule_ids,
        )
        if not set(required) <= set(rules):
            raise ValueError("VerifierIntent compiler received an unknown Rule")
        allowed_tasks = set(allowed_task_types)
        semantic_requirements = VerifierCompiler._semantic_requirements(design, required)
        requirements_by_rule = {
            requirement.rule_id: requirement for requirement in semantic_requirements
        }
        if set(requirements_by_rule) != set(required):
            raise ValueError("VerifierIntent compiler could not bind every required Rule")

        case_assertions: dict[str, list[VerifierAssertion]] = {
            item.case_id: [] for item in bound_cases
        }
        property_cases: dict[str, set[str]] = {rule_id: set() for rule_id in required}
        binding_issues: list[SafeValidationIssue] = []
        for rule_id in required:
            rule = rules[rule_id]
            requirement = requirements_by_rule[rule_id]
            requirement_summary = _semantic_requirement_summary(requirement)
            if requirement.task_type is not None and requirement.task_type not in allowed_tasks:
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_outside_task_batch",
                        ("semantic_requirements", requirement.requirement_id),
                        (
                            "Framework batch assignment is inconsistent for this semantic "
                            f"requirement ({requirement_summary}); do not retry the Challenger "
                            "until the frozen batch plan is repaired."
                        ),
                        retryable=False,
                    )
                )
                continue
            matches: list[tuple[BoundVerifierCaseIntent, int, bool]] = []
            for case in bound_cases:
                if requirement.task_type is not None and case.task_type != requirement.task_type:
                    continue
                for expectation in case.expectations:
                    if expectation.requirement_id != requirement.requirement_id:
                        continue
                    if expectation.kind != requirement.property_kind:
                        continue
                    if expectation.action_index >= len(case.actions):
                        continue
                    action_tool = case.actions[expectation.action_index].tool_id
                    if requirement.tool_ids and action_tool not in requirement.tool_ids:
                        continue
                    if (
                        requirement.property_kind == "error_semantics"
                        and expectation.error_code is not None
                        and expectation.error_code != requirement.error_code
                    ):
                        continue
                    matches.append((case, expectation.action_index, expectation.expected))
            partitions = {case.partition for case, _index, expected in matches if expected}
            if "sealed" not in partitions or not partitions & {"public", "repair"}:
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_positive_partition_coverage",
                        ("semantic_requirements", requirement.requirement_id),
                        (
                            "This semantic requirement needs a positive expectation in a "
                            f"compatible semantic trajectory ({requirement_summary}). The "
                            "framework will pair that trajectory into sealed and public "
                            "obligations."
                        ),
                        expected_category=(
                            "an expectations entry with this requirement_id, expected=true, and "
                            "after_action_ordinal pointing to a compatible requirement tool"
                        ),
                        remediation=(
                            "Add an expectation that copies this requirement_id with "
                            "expected=true; when it lists tool_ids, point its ordinal at one "
                            "of those tool actions."
                        ),
                    )
                )
            if rule.case_sensitivity == "positive_and_negative" and not any(
                not expected for _case, _index, expected in matches
            ):
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_negative_obligation_missing",
                        ("semantic_requirements", requirement.requirement_id),
                        (
                            "This semantic requirement also needs at least one compatible negative "
                            f"expectation ({requirement_summary})."
                        ),
                        expected_category=(
                            "an expectations entry with this requirement_id, expected=false, and "
                            "after_action_ordinal pointing to a compatible requirement tool"
                        ),
                        remediation=(
                            "Add an expected=false expectation for this requirement_id in a "
                            "separate "
                            "negative semantic trajectory whose action or reset input can really "
                            "produce the opposite outcome; when it lists tool_ids, point its "
                            "ordinal "
                            "at one of those tool actions."
                        ),
                    )
                )
            for ordinal, (case, action_index, expected) in enumerate(matches):
                assertion_digest = sha256_digest(
                    canonical_json_bytes((rule_id, case.case_id, action_index, expected, ordinal))
                ).removeprefix("sha256:")[:24]
                assertion = VerifierAssertion(
                    assertion_id=f"assert:{assertion_digest}",
                    rule_id=rule_id,
                    action_index=action_index,
                    expected=expected,
                )
                case_assertions[case.case_id].append(assertion)
                property_cases[rule_id].add(case.case_id)

        cases: list[VerifierCase] = []
        for case_index_value, case in enumerate(bound_cases):
            assertions = tuple(case_assertions[case.case_id])
            if not assertions:
                binding_issues.append(
                    SafeValidationIssue(
                        "case_rule_binding_missing",
                        ("cases", case_index_value, "expectations"),
                        "Make this trajectory bind at least one required Rule obligation.",
                    )
                )
                continue
            cases.append(
                VerifierCase(
                    case_id=case.case_id,
                    partition=case.partition,
                    task_type=case.task_type,
                    evaluator_goal=case.evaluator_goal,
                    seed=case.seed,
                    actor=case.actor,
                    reset_config=case.reset_config,
                    actions=case.actions,
                    assertions=assertions,
                )
            )

        if binding_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="rule_binding",
                    frontier_ordinal=30,
                    issues=tuple(binding_issues),
                )
            )

        properties: list[VerifierProperty] = [
            VerifierProperty(
                property_id=f"property:{rule_id}",
                kind=cast(Any, _CANONICAL_PROPERTY_KIND[rules[rule_id].family]),
                rule_ids=(rule_id,),
                case_ids=tuple(sorted(property_cases[rule_id])),
                description=f"Framework-compiled obligations for {rule_id}.",
            )
            for rule_id in required
        ]
        case_index = {item.case_id: item for item in cases}
        required_auxiliary = set(required_property_families) - {item.kind for item in properties}
        if require_metamorphic:
            required_auxiliary.add("metamorphic")
        auxiliary_issues: list[SafeValidationIssue] = []
        for auxiliary_index, kind in enumerate(sorted(required_auxiliary)):
            allowed_families = _AUXILIARY_PROPERTY_RULE_FAMILIES.get(kind)
            if allowed_families is None:
                raise ValueError(f"unsupported auxiliary property intention: {kind}")
            intended_cases = {
                case.case_id
                for case in bound_cases
                if any(item.kind == kind for item in case.expectations)
            }
            bound_rules = tuple(
                rule_id
                for rule_id in required
                if rules[rule_id].family in allowed_families
                and any(
                    assertion.rule_id == rule_id
                    for case_id in intended_cases
                    if case_id in case_index
                    for assertion in case_index[case_id].assertions
                )
            )
            auxiliary_case_ids = tuple(
                sorted(
                    case_id
                    for case_id in intended_cases
                    if any(
                        assertion.rule_id in set(bound_rules)
                        for assertion in case_index[case_id].assertions
                    )
                )
            )
            if not bound_rules or not auxiliary_case_ids:
                auxiliary_issues.append(
                    SafeValidationIssue(
                        "auxiliary_rule_binding_missing",
                        ("auxiliary_properties", auxiliary_index),
                        "Bind this required auxiliary property to compatible Rule obligations "
                        "and trajectory cases.",
                    )
                )
                continue
            properties.append(
                VerifierProperty(
                    property_id=f"property:aux:{kind}",
                    kind=cast(Any, kind),
                    rule_ids=bound_rules,
                    case_ids=auxiliary_case_ids,
                    description=f"Framework-compiled {kind} relation.",
                )
            )
        if auxiliary_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="auxiliary_binding",
                    frontier_ordinal=35,
                    issues=tuple(auxiliary_issues),
                )
            )
        return VerifierDraft(
            properties=tuple(properties),
            cases=tuple(cases),
            solve_recipes=intent.solve_recipes,
        )

    @staticmethod
    def _bind_intent_cases(intent: VerifierIntent) -> tuple[BoundVerifierCaseIntent, ...]:
        """Bind disclosure identity and seed in deterministic framework code.

        The Challenger supplies one semantic trajectory.  The framework creates
        paired public and sealed executions with separate uint64 seeds, so no
        Agent-authored field can select or relabel the hidden partition.
        """

        if len(intent.cases) > MAX_VERIFIER_CASES // 2:
            raise ValueError(
                "VerifierIntent exceeds framework semantic case capacity before pairing"
            )
        bound: list[BoundVerifierCaseIntent] = []
        for case_index, case in enumerate(intent.cases):
            semantic = case.model_dump(mode="json")
            for partition in ("public", "sealed"):
                binding_bytes = canonical_json_bytes(
                    {
                        "binding_version": "agent-world.verifier-case-binding.v1",
                        "case_index": case_index,
                        "partition": partition,
                        "semantic": semantic,
                    }
                )
                digest = sha256_digest(binding_bytes).removeprefix("sha256:")
                bound.append(
                    BoundVerifierCaseIntent(
                        case_id=f"case:{digest[:24]}:{partition}",
                        partition=cast(Any, partition),
                        task_type=case.task_type,
                        evaluator_goal=case.evaluator_goal,
                        seed=int(digest[-16:], 16),
                        actor=case.actor,
                        reset_config=case.reset_config,
                        actions=case.actions,
                        expectations=case.expectations,
                    )
                )
        return tuple(bound)

    def _persist_intent_checkpoint(
        self,
        *,
        lineage_id: str,
        batch_index: int,
        context: Mapping[str, JsonValue],
        intent: VerifierIntent,
        invocation_results: Sequence[InvocationResult],
        design_ref: ArtifactRef,
        world_spec_ref: ArtifactRef,
        plan_ref: ArtifactRef | None = None,
    ) -> ArtifactRef:
        bound_cases = self._bind_intent_cases(intent)
        sealed = tuple(item for item in bound_cases if item.partition == "sealed")
        checkpoint = VerifierIntentCheckpoint(
            checkpoint_id=f"checkpoint:{lineage_id}:batch:{batch_index}",
            batch_index=batch_index,
            context_hash=sha256_digest(canonical_json_bytes(context)),
            public_and_repair_cases=tuple(
                item for item in bound_cases if item.partition != "sealed"
            ),
            sealed_case_count=len(sealed),
            sealed_commitment=sha256_digest(
                canonical_json_bytes([item.model_dump(mode="json") for item in sealed])
            ),
            solve_recipe_count=len(intent.solve_recipes),
            invocation_result_count=len(invocation_results),
        )
        return self.artifacts.put_json(
            artifact_id=f"{lineage_id}:verifier-intent-batch:{batch_index}",
            artifact_type="judge.verifier_intent_checkpoint",
            value=checkpoint,
            dependencies=(
                design_ref,
                world_spec_ref,
                *((plan_ref,) if plan_ref is not None else ()),
            ),
        )

    @staticmethod
    def _validate_draft(
        draft: VerifierDraft,
        design: EnvironmentDesign,
        *,
        allowed_task_types: Sequence[str] | None = None,
        required_rule_ids: Sequence[str] | None = None,
        required_property_families: Sequence[str] | None = None,
        require_metamorphic: bool | None = None,
    ) -> None:
        world = design.world_spec
        tools = {tool.surface.tool_id: tool for tool in world.tools}
        all_tasks = {task.task_type: task for task in design.curriculum.task_types}
        allowed_tasks = set(all_tasks) if allowed_task_types is None else set(allowed_task_types)
        unknown_task_scope = allowed_tasks - set(all_tasks)
        if unknown_task_scope:
            raise ValueError(f"VerifierDraft task scope is unknown: {sorted(unknown_task_scope)}")
        tasks = {
            task_type: requirement
            for task_type, requirement in all_tasks.items()
            if task_type in allowed_tasks
        }
        rules = design_rule_index(design)
        requested_rule_ids = (
            design.verification.required_rule_ids
            if required_rule_ids is None
            else required_rule_ids
        )
        required_rules = set(VerifierCompiler._runtime_case_rule_ids(design, requested_rule_ids))
        unknown_required_rules = required_rules - set(rules)
        if unknown_required_rules:
            raise ValueError(
                f"VerifierDraft requires unknown Rules: {sorted(unknown_required_rules)}"
            )
        task_rule_owners = {
            rule.rule_id: task.task_type
            for task in design.curriculum.task_types
            for rule in (
                *task.initial_state_constraints,
                *task.success_conditions,
                *task.failure_conditions,
                *task.terminal_conditions,
            )
        }
        rule_tools: dict[str, set[str]] = {rule_id: set() for rule_id in rules}
        for tool in world.tools:
            semantics = tool.semantics
            for rule in (
                *semantics.preconditions,
                *semantics.transition,
                *semantics.postconditions,
            ):
                rule_tools[rule.rule_id].add(tool.surface.tool_id)
            for error in semantics.errors:
                rule_tools[error.when.rule_id].add(tool.surface.tool_id)
            if semantics.permission.condition is not None:
                rule_tools[semantics.permission.condition.rule_id].add(tool.surface.tool_id)

        partitions = {case.partition for case in draft.cases}
        if "public" not in partitions or "sealed" not in partitions:
            raise ValueError("VerifierDraft requires both public and sealed cases")
        cases_by_id = {case.case_id: case for case in draft.cases}
        obligations: dict[str, list[tuple[str, bool]]] = {}
        trajectory_polarities: dict[tuple[str, str, int, str], bool] = {}
        trajectory_issues: list[SafeValidationIssue] = []
        for case_index_value, case in enumerate(draft.cases):
            requirement = tasks.get(case.task_type)
            if requirement is None:
                raise ValueError(
                    f"case {case.case_id} references task type outside this shard: {case.task_type}"
                )
            if case.actor not in requirement.allowed_actor_ids:
                raise ValueError(
                    f"case {case.case_id} actor {case.actor} is not allowed for task "
                    f"{case.task_type}"
                )
            goal_errors = tuple(
                Draft202012Validator(requirement.evaluator_goal_schema).iter_errors(
                    case.evaluator_goal
                )
            )
            if goal_errors:
                path = "/".join(str(item) for item in goal_errors[0].absolute_path) or "<root>"
                raise ValueError(
                    f"case {case.case_id} evaluator_goal violates {case.task_type} schema at {path}"
                )
            reset_errors = tuple(
                Draft202012Validator(requirement.initial_config_schema).iter_errors(
                    case.reset_config
                )
            )
            if reset_errors:
                path = "/".join(str(item) for item in reset_errors[0].absolute_path) or "<root>"
                raise ValueError(
                    f"case {case.case_id} reset_config violates {case.task_type} schema at {path}"
                )
            unknown_tools = {action.tool_id for action in case.actions} - set(tools)
            if unknown_tools:
                raise ValueError(
                    f"case {case.case_id} invokes unknown tools: {sorted(unknown_tools)}"
                )
            for action in case.actions:
                if case.actor not in tools[action.tool_id].semantics.permission.allowed_actors:
                    raise ValueError(
                        f"case {case.case_id} invokes {action.tool_id} with actor {case.actor} "
                        "without frozen tool permission"
                    )
                errors = tuple(
                    Draft202012Validator(tools[action.tool_id].surface.input_schema).iter_errors(
                        action.arguments
                    )
                )
                if errors:
                    path = "/".join(str(item) for item in errors[0].absolute_path) or "<root>"
                    raise ValueError(
                        f"case {case.case_id} action {action.tool_id} violates input schema "
                        f"at {path}"
                    )
            for assertion in case.assertions:
                if assertion.rule_id not in rules:
                    raise ValueError(
                        f"assertion {assertion.assertion_id} references unknown Rule "
                        f"{assertion.rule_id}"
                    )
                if assertion.rule_id not in required_rules:
                    raise ValueError(
                        f"assertion {assertion.assertion_id} references Rule outside this "
                        f"VerifierDraft shard: {assertion.rule_id}"
                    )
                rule = rules[assertion.rule_id]
                task_owner = task_rule_owners.get(assertion.rule_id)
                if task_owner is not None and task_owner != case.task_type:
                    raise ValueError(
                        f"assertion {assertion.assertion_id} binds task {case.task_type} "
                        f"to {task_owner}'s Rule {assertion.rule_id}"
                    )
                if rule.family.startswith("task_"):
                    task_rule_ids = {
                        item.rule_id
                        for item in (
                            *requirement.success_conditions,
                            *requirement.failure_conditions,
                            *requirement.terminal_conditions,
                        )
                    }
                    if assertion.rule_id not in task_rule_ids:
                        raise ValueError(
                            f"assertion {assertion.assertion_id} binds task {case.task_type} "
                            f"to another task's Rule {assertion.rule_id}"
                        )
                allowed_tools = rule_tools[assertion.rule_id]
                action_tool = case.actions[assertion.action_index].tool_id
                if allowed_tools and action_tool not in allowed_tools:
                    raise ValueError(
                        f"assertion {assertion.assertion_id} binds {assertion.rule_id} to "
                        f"unrelated tool {action_tool}"
                    )
                trajectory_identity = sha256_digest(
                    canonical_json_bytes(
                        {
                            "task_type": case.task_type,
                            "evaluator_goal": case.evaluator_goal,
                            "actor": case.actor,
                            "reset_config": case.reset_config,
                            "actions": [action.model_dump(mode="json") for action in case.actions],
                        }
                    )
                )
                polarity_key = (
                    trajectory_identity,
                    assertion.rule_id,
                    assertion.action_index,
                    str(rules[assertion.rule_id].family),
                )
                previous_expected = trajectory_polarities.get(polarity_key)
                if (
                    polarity_key in trajectory_polarities
                    and previous_expected != assertion.expected
                ):
                    trajectory_issues.append(
                        SafeValidationIssue(
                            "draft_assertion_polarity_conflict",
                            ("cases", case_index_value, "assertions", "expected"),
                            "Paired copies of one semantic trajectory cannot require opposite "
                            "outcomes for the same Rule action.",
                            violated_condition=(
                                "one semantic trajectory has one expected polarity for each "
                                "Rule/action binding"
                            ),
                            expected_category=(
                                "separate positive and negative trajectories with distinct "
                                "domain actions or reset inputs"
                            ),
                            remediation=(
                                "Keep one polarity for this trajectory and bind the opposite "
                                "polarity to a distinct, compatible negative trajectory."
                            ),
                        )
                    )
                else:
                    trajectory_polarities[polarity_key] = assertion.expected
                obligations.setdefault(assertion.rule_id, []).append(
                    (case.partition, assertion.expected)
                )
        if trajectory_issues:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="rule_binding",
                    frontier_ordinal=30,
                    issues=tuple(trajectory_issues),
                )
            )
        for task_type, requirement in tasks.items():
            task_cases = [case for case in draft.cases if case.task_type == task_type]
            covered_tools = {action.tool_id for case in task_cases for action in case.actions}
            missing_tools = set(requirement.required_tool_ids) - covered_tools
            if missing_tools:
                raise ValueError(
                    f"VerifierDraft task {task_type} omits required tools: {sorted(missing_tools)}"
                )
            if not any(len(case.actions) >= requirement.minimum_tool_calls for case in task_cases):
                raise ValueError(
                    f"VerifierDraft task {task_type} has no trajectory meeting minimum_tool_calls"
                )
        recipe_ids = [recipe.recipe_id for recipe in draft.solve_recipes]
        if len(set(recipe_ids)) != len(recipe_ids):
            raise ValueError("VerifierDraft solve recipe ids must be unique")
        preferred = [recipe.task_type for recipe in draft.solve_recipes if recipe.preferred]
        if len(set(preferred)) != len(preferred):
            raise ValueError("each task type may have at most one preferred solve recipe")
        for recipe_index, recipe in enumerate(draft.solve_recipes):
            requirement = tasks.get(recipe.task_type)
            if requirement is None:
                raise ValueError(
                    f"solve recipe {recipe.recipe_id} references unknown task type "
                    f"{recipe.task_type}"
                )
            _validate_solve_recipe(
                recipe,
                requirement=requirement,
                design=design,
                location=("draft", "solve_recipes", recipe_index),
            )
        missing_preferred_recipes = set(tasks) - set(preferred)
        if missing_preferred_recipes:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="verifier",
                    validation_phase="solve_recipe",
                    frontier_ordinal=25,
                    issues=(
                        SafeValidationIssue(
                            "draft_release_recipe_missing",
                            ("draft", "solve_recipes"),
                            "The frozen release path has no interactive solver, so every task "
                            "needs one preferred ParameterizedSolveRecipe.",
                            violated_condition=(
                                "every task in this verifier shard has exactly one preferred "
                                "solve recipe"
                            ),
                            expected_category=(
                                "one preferred ParameterizedSolveRecipe for each task type in "
                                "this shard"
                            ),
                            remediation=(
                                "Regenerate or repair the Verifier Intent with public-input-only "
                                "preferred recipes for every task."
                            ),
                        ),
                    ),
                )
            )
        for prop in draft.properties:
            if not set(prop.case_ids) <= set(cases_by_id):
                raise ValueError(f"property {prop.property_id} references unknown cases")
            if not set(prop.rule_ids) <= set(rules):
                raise ValueError(f"property {prop.property_id} references unknown rules")
            if not set(prop.rule_ids) <= required_rules:
                raise ValueError(f"property {prop.property_id} references Rules outside this shard")
            allowed_families = _AUXILIARY_PROPERTY_RULE_FAMILIES.get(prop.kind)
            for rule_id in prop.rule_ids:
                family = rules[rule_id].family
                expected_kind = _CANONICAL_PROPERTY_KIND[family]
                if prop.kind != expected_kind and (
                    allowed_families is None or family not in allowed_families
                ):
                    raise ValueError(
                        f"property {prop.property_id} kind {prop.kind} cannot claim "
                        f"{family} Rule {rule_id}"
                    )
                if not any(
                    assertion.rule_id == rule_id
                    for case_id in prop.case_ids
                    for assertion in cases_by_id[case_id].assertions
                ):
                    raise ValueError(
                        f"property {prop.property_id} has no real obligation for Rule {rule_id}"
                    )
        missing = required_rules - set(obligations)
        if missing:
            raise ValueError(f"VerifierDraft leaves required rules uncovered: {sorted(missing)}")
        for rule_id in required_rules:
            observed = obligations[rule_id]
            partitions_for_rule = {partition for partition, _expected in observed}
            if "sealed" not in partitions_for_rule or not partitions_for_rule & {
                "public",
                "repair",
            }:
                raise ValueError(
                    f"Rule {rule_id} requires both sealed and public/repair obligations"
                )
            expectations = {expected for _partition, expected in observed}
            if True not in expectations:
                raise ValueError(f"Rule {rule_id} has no positive obligation")
            if rules[rule_id].case_sensitivity == "positive_and_negative" and expectations != {
                False,
                True,
            }:
                raise ValueError(f"Rule {rule_id} requires positive and negative cases")

            canonical_kind = _CANONICAL_PROPERTY_KIND[rules[rule_id].family]
            if not any(
                canonical_kind == prop.kind and rule_id in prop.rule_ids
                for prop in draft.properties
            ):
                raise ValueError(
                    f"Rule {rule_id} lacks canonical {canonical_kind} property binding"
                )
        property_kinds: set[str] = {str(item.kind) for item in draft.properties}
        effective_property_families: set[str] = {
            str(item)
            for item in (
                design.verification.required_property_families
                if required_property_families is None
                else required_property_families
            )
            if item != "sampling"
        }
        missing_families = effective_property_families - property_kinds
        if missing_families:
            raise ValueError(
                f"VerifierDraft omits required property families: {sorted(missing_families)}"
            )
        metamorphic_required = (
            bool(design.verification.required_metamorphic_relations)
            if require_metamorphic is None
            else require_metamorphic
        )
        if metamorphic_required and "metamorphic" not in property_kinds:
            raise ValueError("VerifierDraft requires a metamorphic property")

    @staticmethod
    def _prompt(context: Mapping[str, JsonValue]) -> str:
        context_json = canonical_json_bytes(context).decode("utf-8")
        return (
            """  # noqa: S608 - static model instruction, not a database query.
You are the Challenger inside Agent World Foundry.
Project purpose: prove that an untrusted generated Runtime implements the evidence-backed
WorldSpec with real programmatic state transitions, without sharing expected answers with it.

The framework has already compiled the only information you need into the compact JSON context
below. You have no tools and must not request files, shell commands, source code, or more context.
Produce exactly one compact VerifierIntent structured output. Return one syntactically valid RFC
8259 JSON object only: no Markdown, prose, `NaN`, `Infinity`, or `-Infinity` literals.
You propose only domain reset configs, tool-action trajectories, and expectations that select one
published semantic requirement. Never enumerate framework Rule ids or properties. Framework code
uses the selected opaque requirement_id to bind each expectation to exactly one frozen Rule and
rejects any uncovered requirement deterministically.
The verifier context and requested output are different schemas. The context's `schema_version`
is context data only: never copy it into VerifierIntent. The top-level VerifierIntent v2
`schema_version` may be omitted when the output schema permits its default; if emitted, it must be
the literal `"v2"`.
Each item in `cases` must use the literal `expectations` field, never aliases such as `checks`,
`assertions`, or `properties`. Each expectation item must copy exactly one `requirement_id` from
`semantic_requirements`, then supply its matching `kind`, one-based `after_action_ordinal`, and
boolean `expected` according to the supplied logical output schema. `requirement_id` is an opaque
selector, not a Rule id: do not invent, omit, or transform it.
For `error_semantics`, select the path using `error_code`: when the selected tool has more than
one entry in `tools[].error_codes`, it is required; otherwise it may be omitted. Never emit
`error_code` for another kind, and do not add unrecognized case fields.
Each tool's `precondition_summaries` and `error_paths` are the public semantic guide for choosing
a legitimate reset/action path. For an error trajectory, choose its `error_code` and make the
reset/action match that path's `trigger`; do not label a normal successful transition as an error
just to cover a requirement.
Before answering, perform a two-pass feasibility and coverage audit over every item in
`semantic_requirements`. This is the complete requirement ledger. In pass one, choose a concrete
`(requirement_id, kind, error_code when supplied, expected, after_action_ordinal, action tool_id)`
mapping for each requirement before composing cases. Use its `summary` as the semantic condition
that must really hold (or fail) after the selected action; do not treat a matching property kind as
proof that distinct terminal, success, or error conditions are interchangeable.

In pass two, scan the completed `cases` against every requirement again. Each expectation selects
exactly one requirement_id; do not merge different requirement_ids merely because their kind or
tool is alike. Every requirement needs a compatible positive (`expected=true`) expectation. When
`positive_and_negative` is true, it also needs an `expected=false` expectation in a separate,
semantically distinct trajectory whose reset/action can really produce the opposite outcome. If a
requirement lists tool_ids, its expectation ordinal must point to one of those tool actions; merely
including the tool elsewhere in the trajectory does not cover it. For `error_semantics`, copy the
requirement's `error_code` exactly and make reset/action satisfy the matching error-path trigger.
For a requirement with no tool_ids, use a compatible action in the selected task. Do not put both
polarities of the same `(requirement_id, after_action_ordinal)` in one case. Framework code pairs
every semantic trajectory into public and sealed cases and assigns private case ids and seeds; you
must not propose or infer those values. Requirements with `scope="world_shared"` and
`task_type=null` apply across the assigned real tasks; `world_shared` is never a case task_type.
Choose case task_type only from `tasks`. Do not return while any requirement lacks its mapped,
feasible expectation.
Use meaningful multi-action trajectories, error paths, idempotency, permissions, rollback, and
ordering/concurrency where applicable. Obligations stay Judge-side, while actions/reset_config
contain only legitimate domain input. Never put expected values, verifier metadata, release
labels, Python code, expressions, reward targets, or shell commands into Runtime inputs. You
cannot see Runtime source and do not decide release.
The context field `semantic_case_limit` is a hard framework capacity. Return no more cases than
that value; public/sealed pairing happens after your output and consumes two execution cases per
semantic trajectory. It is not a target count: return the fewest distinct trajectories needed for
complete semantic coverage, and attach multiple compatible expectations to one trajectory instead
of repeating the same full reset state.

Each case must declare a real task_type and evaluator_goal satisfying that task's
evaluator_goal_schema, plus one actor from that task's allowed_actor_ids. Actor is bound once by
reset and cannot appear in an action's arguments. Never include evaluator_goal in reset_config or
action arguments.

Actor/action audit is mandatory before returning: every action in a case must use a tool whose
`allowed_actor_ids` includes that case's single bound actor. A workflow that needs another actor
is not one mixed-actor trajectory: split it into separate actor-bound cases. Feasibility audit is
also mandatory: when a first action has a positive `precondition`, make its reset_config and
arguments satisfy that tool's `precondition_summaries`; when a first action has positive
`error_semantics`, make them satisfy the selected `error_paths` trigger. Do not call a `planned`,
`running`, or other lifecycle equivalent to a stated `ready`/`interrupted` requirement. For later
actions, choose a preceding real transition that establishes the needed state; do not merely label
an expectation as true.

Action-input schema audit is mandatory before returning: for every
`cases[].actions[]`, find its selected `tool_id` in `tools` and make `arguments` validate against
that exact tool's `input_schema`. Include every field named by `required`; when that schema has
`additionalProperties=false`, emit no other argument fields; and satisfy its declared value types,
enums, formats, and bounds. This is a per-action check: do not reuse arguments from a different
tool merely because the domain meaning sounds similar.

`after_action_ordinal` is one-based: the first action is 1, the second is 2, and a case containing
one action permits only ordinal 1. Never use zero and never use an ordinal larger than the number
of actions in that case. Framework code deterministically converts the ordinal to its private
zero-based Verifier IR index.

This release path intentionally has no hidden interactive solver. `solve_recipes` is therefore
required: return exactly one `preferred=true` ParameterizedSolveRecipe for each assigned task type.
It is a public-input-only solving plan, not an expected answer or proof. Do not omit it, return an
empty list, or rely on public/sealed case pairing as a solve recipe.

Solve-recipe binding audit is mandatory before returning. A matching field name is not proof that a
pointer is valid: a `number` source cannot fill an `integer` tool argument. For each required
recipe argument, consult `solve_recipe_binding_guide`; it lists the CLOSED enumeration of every
legal `public_goal` pointer already derivable from this context, including deep pointers. The guide
is not a value source and is exhaustive for public_goal: use a pointer only if it appears in the
guide. If the guide lists no compatible pointer for an argument, use a schema-valid
`{"kind":"literal","value":...}` or an earlier compatible public tool result/observation. Never
cast, round, parse, or otherwise transform
a pointer value inside a recipe. A literal must also satisfy the selected field's enum, format, and
bounds. Every RFC 6901 pointer segment must descend through a structured source node: each object
key must select an object property and each index must select an array item. A pointer may stop at a
scalar leaf but must never traverse a segment beyond one; if the source value is a scalar, stop the
pointer there or select a shorter, structured source rather than adding another segment.

Before returning, verify that every bounded ParameterizedSolveRecipe uses every tool required by its
task,
meets its minimum_tool_calls, and that each literal and each RFC 6901 pointer is valid for the
selected input or visible source schema. A recipe may reference public_goal, reset_observation, or
earlier public tool results/observations only. It cannot reference initial_config, evaluator_goal,
Rule IR, snapshots, source code, or release policy. Use at most one preferred recipe per task type;
every recipe must use only tools available to every allowed task actor and satisfy tool input
schemas.

`reset_config_schema_id` is a context reference to one item in `reset_config_schemas`, not a
Runtime field. Never copy it into reset_config. Keep trajectories on their exact task type.

<verifier_context_json>
"""
            + context_json
            + """
</verifier_context_json>
"""
        )

    @staticmethod
    def _challenger_context(
        design: EnvironmentDesign,
        *,
        task_types: Sequence[str] | None = None,
        required_rule_ids: Sequence[str] | None = None,
        required_property_families: Sequence[str] | None = None,
        require_metamorphic: bool | None = None,
    ) -> dict[str, JsonValue]:
        """Project the frozen design into a compact, tool-free Challenger contract.

        The full EnvironmentDesign repeats the root reset schema once per task and contains
        evidence/Rule expression material the Challenger is neither allowed nor required to
        reinterpret. This projection deduplicates reset schemas and exposes only legitimate
        domain inputs plus model-visible coverage metadata; framework Rule ids stay Judge-side.
        """

        selected_task_types = (
            {task.task_type for task in design.curriculum.task_types}
            if task_types is None
            else set(task_types)
        )
        selected_tasks = tuple(
            task for task in design.curriculum.task_types if task.task_type in selected_task_types
        )
        if len(selected_tasks) != len(selected_task_types):
            raise ValueError("Challenger context references an unknown task type")
        selected_rule_ids = VerifierCompiler._runtime_case_rule_ids(
            design,
            (
                design.verification.required_rule_ids
                if required_rule_ids is None
                else required_rule_ids
            ),
        )
        semantic_requirements = VerifierCompiler._semantic_requirements(
            design,
            selected_rule_ids,
        )
        out_of_scope_requirements = tuple(
            item
            for item in semantic_requirements
            if item.task_type is not None and item.task_type not in selected_task_types
        )
        if out_of_scope_requirements:
            raise ValueError("Challenger context assigns a task Rule outside this batch")
        reset_schemas: dict[str, JsonValue] = {}
        task_schema_ids: dict[str, str] = {}
        for task in selected_tasks:
            schema_id = sha256_digest(canonical_json_bytes(task.initial_config_schema))
            reset_schemas.setdefault(schema_id, task.initial_config_schema)
            task_schema_ids[task.task_type] = schema_id

        relevant_tool_ids = {
            tool_id for task in selected_tasks for tool_id in task.required_tool_ids
        }
        relevant_tool_ids.update(
            tool_id for requirement in semantic_requirements for tool_id in requirement.tool_ids
        )

        return {
            "schema_version": "agent-world.challenger-context.v8",
            "reset_config_schemas": [
                {"schema_id": schema_id, "schema": schema}
                for schema_id, schema in sorted(reset_schemas.items())
            ],
            "tools": [
                {
                    "tool_id": tool.surface.tool_id,
                    "description": tool.surface.description,
                    "input_schema": tool.surface.input_schema,
                    "allowed_actor_ids": list(tool.semantics.permission.allowed_actors),
                    "precondition_summaries": [
                        rule.description for rule in tool.semantics.preconditions
                    ],
                    "error_codes": [error.error_code for error in tool.semantics.errors],
                    "error_paths": [
                        {
                            "error_code": error.error_code,
                            "trigger": error.when.description,
                            "state_effect": error.state_effect,
                        }
                        for error in tool.semantics.errors
                    ],
                }
                for tool in design.world_spec.tools
                if tool.surface.tool_id in relevant_tool_ids
            ],
            "solve_recipe_binding_guide": _solve_recipe_binding_guide(
                selected_tasks,
                design.world_spec.tools,
            ),
            "tasks": [
                {
                    "task_type": task.task_type,
                    "objective": task.objective,
                    "allowed_actor_ids": list(task.allowed_actor_ids),
                    "reset_config_schema_id": task_schema_ids[task.task_type],
                    "public_goal_schema": task.public_goal_schema,
                    "evaluator_goal_schema": task.evaluator_goal_schema,
                    "required_tool_ids": list(task.required_tool_ids),
                    "minimum_tool_calls": task.minimum_tool_calls,
                }
                for task in selected_tasks
            ],
            "semantic_requirements": [
                _semantic_requirement_projection(item)
                for item in sorted(
                    semantic_requirements,
                    key=lambda item: item.requirement_id,
                )
            ],
            "required_property_families": [
                cast(JsonValue, str(item))
                for item in (
                    design.verification.required_property_families
                    if required_property_families is None
                    else required_property_families
                )
                if item != "sampling"
            ],
            "required_metamorphic_relations": list(
                design.verification.required_metamorphic_relations
                if (
                    bool(design.verification.required_metamorphic_relations)
                    if require_metamorphic is None
                    else require_metamorphic
                )
                else ()
            ),
        }

    @staticmethod
    def _assign_required_rules(
        design: EnvironmentDesign,
    ) -> dict[str, tuple[str, ...]]:
        """Assign every required Rule to exactly one independently generated task shard."""

        tasks = design.curriculum.task_types
        assignments: dict[str, list[str]] = {task.task_type: [] for task in tasks}
        task_order = {task.task_type: index for index, task in enumerate(tasks)}
        task_rule_owners = {
            rule.rule_id: task.task_type
            for task in tasks
            for rule in (
                *task.initial_state_constraints,
                *task.success_conditions,
                *task.failure_conditions,
                *task.terminal_conditions,
            )
        }
        rules = design_rule_index(design)
        rule_tools: dict[str, set[str]] = {rule_id: set() for rule_id in rules}
        for tool in design.world_spec.tools:
            semantics = tool.semantics
            for rule in (
                *semantics.preconditions,
                *semantics.transition,
                *semantics.postconditions,
            ):
                rule_tools[rule.rule_id].add(tool.surface.tool_id)
            for error in semantics.errors:
                rule_tools[error.when.rule_id].add(tool.surface.tool_id)
            if semantics.permission.condition is not None:
                rule_tools[semantics.permission.condition.rule_id].add(tool.surface.tool_id)

        for rule_id in VerifierCompiler._runtime_case_rule_ids(
            design,
            design.verification.required_rule_ids,
        ):
            owner = task_rule_owners.get(rule_id)
            if owner is None:
                associated_tools = rule_tools[rule_id]
                candidates = [
                    task.task_type
                    for task in tasks
                    if associated_tools & set(task.required_tool_ids)
                ]
                if not candidates:
                    candidates = [task.task_type for task in tasks]
                owner = min(
                    candidates,
                    key=lambda item: (len(assignments[item]), task_order[item]),
                )
            assignments[owner].append(rule_id)
        return {task_type: tuple(rule_ids) for task_type, rule_ids in assignments.items()}

    @staticmethod
    def _assign_required_property_families(
        design: EnvironmentDesign,
        rule_assignments: Mapping[str, Sequence[str]],
    ) -> dict[str, tuple[str, ...]]:
        rules = design_rule_index(design)
        assignments: dict[str, set[str]] = {
            task.task_type: {
                str(_CANONICAL_PROPERTY_KIND[rules[rule_id].family])
                for rule_id in rule_assignments[task.task_type]
            }
            for task in design.curriculum.task_types
        }
        covered: set[str] = set().union(*assignments.values()) if assignments else set()
        missing = {
            str(item)
            for item in design.verification.required_property_families
            if item != "sampling"
        } - covered
        if missing:
            first_task = design.curriculum.task_types[0].task_type
            assignments[first_task].update(missing)
        return {
            task.task_type: tuple(sorted(assignments[task.task_type]))
            for task in design.curriculum.task_types
        }

    @staticmethod
    def _runtime_case_rule_ids(
        design: EnvironmentDesign,
        rule_ids: Sequence[str],
    ) -> tuple[str, ...]:
        """Keep action-case coverage separate from task-materialization sampling.

        ``VerificationRequirements`` deliberately names the complete Rule closure. Curriculum
        sampling constraints are still hard-gated by task materialization/reset, where their
        inputs exist; binding them to arbitrary Runtime actions makes a valid Candidate
        impossible to judge. The Verifier IR therefore owns every non-sampling Rule only.
        """

        rules = design_rule_index(design)
        unknown = set(rule_ids) - set(rules)
        if unknown:
            raise ValueError(f"Verifier runtime case scope has unknown Rules: {sorted(unknown)}")
        return tuple(rule_id for rule_id in rule_ids if rules[rule_id].family != "sampling")

    @staticmethod
    def _semantic_requirements(
        design: EnvironmentDesign,
        rule_ids: Sequence[str],
    ) -> tuple[_SemanticRequirement, ...]:
        """Project exact frozen Rules into opaque Challenger-selectable requirements.

        A property-family label is not enough to bind a trajectory when several
        Rules share that label but have incompatible conditions.  The
        ``requirement_id`` is a framework-derived selector copied from the
        current context, never a Rule id the model has to invent.
        """

        rules = design_rule_index(design)
        runtime_rule_ids = VerifierCompiler._runtime_case_rule_ids(design, rule_ids)
        task_rule_owners = {
            rule.rule_id: task.task_type
            for task in design.curriculum.task_types
            for rule in (
                *task.initial_state_constraints,
                *task.success_conditions,
                *task.failure_conditions,
                *task.terminal_conditions,
            )
        }
        rule_tools: dict[str, set[str]] = {rule_id: set() for rule_id in rules}
        error_code_by_rule: dict[str, str] = {}
        for tool in design.world_spec.tools:
            semantics = tool.semantics
            for rule in (
                *semantics.preconditions,
                *semantics.transition,
                *semantics.postconditions,
            ):
                rule_tools[rule.rule_id].add(tool.surface.tool_id)
            for error in semantics.errors:
                rule_tools[error.when.rule_id].add(tool.surface.tool_id)
                error_code_by_rule[error.when.rule_id] = error.error_code
            if semantics.permission.condition is not None:
                rule_tools[semantics.permission.condition.rule_id].add(tool.surface.tool_id)
        return tuple(
            _SemanticRequirement(
                requirement_id=_semantic_requirement_id(rule_id),
                rule_id=rule_id,
                scope="task" if task_rule_owners.get(rule_id) is not None else "world_shared",
                task_type=task_rule_owners.get(rule_id),
                property_kind=str(_CANONICAL_PROPERTY_KIND[rules[rule_id].family]),
                tool_ids=tuple(sorted(rule_tools[rule_id])),
                positive_and_negative=(rules[rule_id].case_sensitivity == "positive_and_negative"),
                error_code=(
                    error_code_by_rule.get(rule_id)
                    if rules[rule_id].family == "error_condition"
                    else None
                ),
                summary=rules[rule_id].description,
            )
            for rule_id in runtime_rule_ids
        )

    def _batch_budgets(self, budget: Budget, batch_count: int) -> tuple[Budget, ...]:
        if batch_count < 1 or batch_count > self.maximum_task_shards:
            raise VerifierCompilationError("Verifier batch count is outside policy")
        if budget.agent_turns < batch_count:
            raise VerifierCompilationError(
                f"Verifier compilation requires at least {batch_count} Agent turns"
            )
        turn_token_limit = budget.llm_tokens // budget.agent_turns
        if turn_token_limit < 1:
            raise VerifierCompilationError("Verifier per-turn token budget is empty")
        correction_capacity = min(
            batch_count * self.maximum_structured_reworks,
            budget.repair_attempts,
            budget.agent_turns - batch_count,
            budget.llm_tokens // turn_token_limit - batch_count,
        )
        quotient, remainder = divmod(correction_capacity, batch_count)
        turns = tuple(
            1 + quotient + (1 if index < remainder else 0) for index in range(batch_count)
        )
        total_turns = sum(turns)
        return tuple(
            Budget(
                llm_tokens=turn_token_limit * batch_turns,
                agent_turns=batch_turns,
                repair_attempts=batch_turns - 1,
                wall_seconds=budget.wall_seconds,
                monetary_cost=(
                    budget.monetary_cost * batch_turns / total_turns if total_turns else 0
                ),
            )
            for batch_turns in turns
        )

    @staticmethod
    def _semantic_case_quotas(batch_count: int) -> tuple[int, ...]:
        """Allocate global paired-case capacity before any Agent invocation."""

        if batch_count < 1 or batch_count > VerifierCompiler.maximum_task_shards:
            raise VerifierCompilationError("Verifier batch count is outside case-capacity policy")
        semantic_capacity = MAX_VERIFIER_CASES // 2
        quotient, remainder = divmod(semantic_capacity, batch_count)
        quotas = tuple(quotient + (1 if index < remainder else 0) for index in range(batch_count))
        if any(item < 2 for item in quotas):
            raise VerifierCompilationError(
                "Verifier batch count cannot satisfy minimum semantic case capacity"
            )
        return quotas

    @staticmethod
    def _merge_batch_drafts(drafts: Sequence[VerifierDraft]) -> VerifierDraft:
        """Namespace capacity-batch ids before enforcing the global closure."""

        properties: list[VerifierProperty] = []
        cases: list[VerifierCase] = []
        recipes: list[ParameterizedSolveRecipe] = []
        for batch_index, draft in enumerate(drafts):
            case_ids = {
                case.case_id: f"case:batch:{batch_index}:{case_index}"
                for case_index, case in enumerate(draft.cases)
            }
            for case_index, case in enumerate(draft.cases):
                cases.append(
                    case.model_copy(
                        update={
                            "case_id": case_ids[case.case_id],
                            "assertions": tuple(
                                assertion.model_copy(
                                    update={
                                        "assertion_id": (
                                            f"assertion:batch:{batch_index}:"
                                            f"{case_index}:{assertion_index}"
                                        )
                                    }
                                )
                                for assertion_index, assertion in enumerate(case.assertions)
                            ),
                        }
                    )
                )
            properties.extend(
                prop.model_copy(
                    update={
                        "property_id": f"property:batch:{batch_index}:{property_index}",
                        "case_ids": tuple(case_ids[case_id] for case_id in prop.case_ids),
                    }
                )
                for property_index, prop in enumerate(draft.properties)
            )
            recipes.extend(
                recipe.model_copy(
                    update={
                        "recipe_id": f"recipe:batch:{batch_index}:{recipe_index}",
                        "steps": tuple(
                            step.model_copy(
                                update={
                                    "step_id": (
                                        f"step:batch:{batch_index}:{recipe_index}:{step_index}"
                                    )
                                }
                            )
                            for step_index, step in enumerate(recipe.steps)
                        ),
                    }
                )
                for recipe_index, recipe in enumerate(draft.solve_recipes)
            )
        return VerifierDraft(
            properties=tuple(properties),
            cases=tuple(cases),
            solve_recipes=tuple(recipes),
        )

    @staticmethod
    def _write_json(path: Path, value: object) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)


__all__ = [
    "ChallengerProfileProvider",
    "CompiledVerifier",
    "CompiledVerifierBatch",
    "VerifierCompilationError",
    "VerifierCompiler",
]


def _validate_solve_recipe(
    recipe: ParameterizedSolveRecipe,
    *,
    requirement: TaskRequirement,
    design: EnvironmentDesign,
    location: tuple[str | int, ...],
) -> None:
    tools = {tool.surface.tool_id: tool for tool in design.world_spec.tools}
    required_tools = set(requirement.required_tool_ids)
    used_tools = {step.tool_id for step in recipe.steps}
    missing = required_tools - used_tools
    if missing:
        _raise_solve_recipe_issue(
            code="recipe_required_tool_coverage_missing",
            location=(*location, "steps"),
            message="The recipe does not use every tool required by its assigned task.",
            violated_condition="each recipe must cover every tool required by its task",
            expected_category="a recipe covering the task's required tools",
            remediation="Add steps using each required tool for this task.",
        )
    if len(recipe.steps) < requirement.minimum_tool_calls:
        _raise_solve_recipe_issue(
            code="recipe_minimum_step_count_missing",
            location=(*location, "steps"),
            message="The recipe has fewer steps than its assigned task requires.",
            violated_condition="each recipe must meet its task's minimum tool-call count",
            expected_category="a recipe with at least the task's required number of steps",
            remediation="Add valid steps until the task's minimum tool-call count is met.",
        )

    boundary_by_actor = {
        actor.actor: actor for actor in design.world_spec.boundary.actors_and_authority
    }
    for step_index, step in enumerate(recipe.steps):
        step_location = (*location, "steps", step_index)
        tool = tools.get(step.tool_id)
        if tool is None:
            _raise_solve_recipe_issue(
                code="recipe_tool_unknown",
                location=(*step_location, "tool_id"),
                message="This recipe step selects no tool from the frozen ToolContractSet.",
                violated_condition="each recipe step must reference a frozen tool",
                expected_category="a step whose tool_id is declared in the ToolContractSet",
                remediation="Replace this step's tool with a tool declared by the frozen design.",
            )
        denied = set(requirement.allowed_actor_ids) - set(tool.semantics.permission.allowed_actors)
        if denied:
            _raise_solve_recipe_issue(
                code="recipe_tool_actor_permission_denied",
                location=(*step_location, "tool_id"),
                message="This step's tool is unavailable to an actor assigned to the task.",
                violated_condition="a selected tool must be available to every assigned actor",
                expected_category="a step using a tool permitted for the task actors",
                remediation="Choose a task-permitted tool for this step.",
            )
        input_schema = tool.surface.input_schema
        properties = input_schema.get("properties")
        required = input_schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            _raise_solve_recipe_issue(
                code="recipe_tool_input_schema_unavailable",
                location=(*step_location, "arguments"),
                message="The frozen tool input contract is not a closed object schema.",
                violated_condition="the frozen tool input contract must be a closed object schema",
                expected_category="a repaired frozen ToolContractSet",
                remediation="Repair the frozen tool input contract before retrying the recipe.",
                retryable=False,
            )
        required_names = {item for item in required if isinstance(item, str)}
        if len(required_names) != len(required):
            _raise_solve_recipe_issue(
                code="recipe_tool_required_fields_invalid",
                location=(*step_location, "arguments"),
                message="The frozen tool input contract has invalid required-field metadata.",
                violated_condition="the frozen tool input contract must declare required names",
                expected_category="a repaired frozen ToolContractSet",
                remediation="Repair the frozen tool input contract before retrying the recipe.",
                retryable=False,
            )
        unknown_arguments = set(step.arguments) - set(properties)
        missing_arguments = required_names - set(step.arguments)
        if unknown_arguments or missing_arguments:
            _raise_solve_recipe_issue(
                code="recipe_argument_names_mismatch",
                location=(*step_location, "arguments"),
                message="This step's argument names do not match the selected tool contract.",
                violated_condition="a step must have required, declared arguments only",
                expected_category="an arguments object matching the selected tool fields",
                remediation="Use exactly the selected tool's required and declared fields.",
            )
        for argument_index, (name, argument) in enumerate(step.arguments.items()):
            argument_location = (*step_location, "arguments", argument_index)
            target_schema = properties[name]
            if not isinstance(target_schema, dict):
                _raise_solve_recipe_issue(
                    code="recipe_tool_argument_schema_invalid",
                    location=argument_location,
                    message="The selected tool's frozen argument schema is invalid.",
                    violated_condition="each frozen tool argument must have a valid schema",
                    expected_category="a repaired frozen ToolContractSet",
                    remediation="Repair the frozen tool argument schema before retrying.",
                    retryable=False,
                )
            if isinstance(argument, RecipeLiteral):
                errors = tuple(Draft202012Validator(target_schema).iter_errors(argument.value))
                if errors:
                    _raise_solve_recipe_issue(
                        code="recipe_literal_schema_mismatch",
                        location=argument_location,
                        message="This literal does not satisfy the selected tool argument schema.",
                        violated_condition="a literal must satisfy its selected argument schema",
                        expected_category="a schema-compatible literal",
                        remediation="Use a schema-compatible literal.",
                    )
                continue
            assert isinstance(argument, RecipePointer)
            source_schema = _recipe_pointer_schema(
                argument,
                step_index=step_index,
                recipe=recipe,
                requirement=requirement,
                design=design,
                tools=tools,
                boundary_by_actor=boundary_by_actor,
                location=argument_location,
            )
            if not _schemas_compatible(source_schema, target_schema):
                _raise_solve_recipe_issue(
                    code="recipe_pointer_type_mismatch",
                    location=argument_location,
                    message=(
                        "This pointer's resolved source has type "
                        f"`{_schema_type_label(source_schema)}`, but selected tool argument "
                        f"`{name}` requires `{_schema_type_label(target_schema)}`."
                    ),
                    violated_condition="a pointer source type must fit its selected argument type",
                    expected_category=(
                        "a pointer whose resolved source type fits the selected tool argument type"
                    ),
                    remediation=(
                        "Use a compatible pointer source, or replace this binding with a "
                        "literal that validates against the selected tool argument schema."
                    ),
                )


def _recipe_pointer_schema(
    pointer: RecipePointer,
    *,
    step_index: int,
    recipe: ParameterizedSolveRecipe,
    requirement: TaskRequirement,
    design: EnvironmentDesign,
    tools: Mapping[str, ToolContract],
    boundary_by_actor: Mapping[str, ActorBoundary],
    location: tuple[str | int, ...],
) -> Mapping[str, JsonValue]:
    if pointer.source == "public_goal":
        schema: Mapping[str, JsonValue] = requirement.public_goal_schema
        visible_fields: set[str] | None = None
    elif pointer.source == "reset_observation":
        schema = design.world_spec.state.root_state_schema
        visibility_sets = [
            set(boundary_by_actor[actor].visibility) for actor in requirement.allowed_actor_ids
        ]
        visible_fields = set.intersection(*visibility_sets) if visibility_sets else set()
    else:
        previous_index = pointer.previous_step_index
        if previous_index is None or previous_index >= step_index:
            _raise_solve_recipe_issue(
                code="recipe_pointer_previous_step_invalid",
                location=location,
                message="This pointer does not reference an earlier recipe step.",
                violated_condition="a previous-step pointer may reference only an earlier step",
                expected_category="a pointer to a preceding recipe step",
                remediation="Point to an earlier step or a public goal/reset observation.",
            )
        previous_tool = tools[recipe.steps[previous_index].tool_id]
        if pointer.source == "previous_tool_result":
            schema = previous_tool.surface.output_schema
            visible_fields = None
        else:
            schema = previous_tool.surface.observation_schema
            visibility_sets = [
                set(previous_tool.semantics.observation.visible_fields_by_actor[actor])
                for actor in requirement.allowed_actor_ids
            ]
            visible_fields = set.intersection(*visibility_sets) if visibility_sets else set()
    return _schema_at_pointer(
        schema,
        pointer.pointer,
        visible_fields=visible_fields,
        location=location,
    )


def _schema_at_pointer(
    schema: Mapping[str, JsonValue],
    pointer: str,
    *,
    visible_fields: set[str] | None,
    location: tuple[str | int, ...],
) -> Mapping[str, JsonValue]:
    current: Mapping[str, JsonValue] = schema
    for index, raw in enumerate(pointer.split("/")[1:]):
        token = raw.replace("~1", "/").replace("~0", "~")
        if index == 0 and visible_fields is not None and token not in visible_fields:
            _raise_solve_recipe_issue(
                code="recipe_pointer_actor_visibility_denied",
                location=location,
                message="This pointer reads a field hidden from an actor assigned to the task.",
                violated_condition="a pointer may read only fields visible to every assigned actor",
                expected_category="a pointer to a field visible to every assigned actor",
                remediation="Use a public goal, visible observation, or previous public result.",
            )
        schema_type = current.get("type")
        if schema_type == "object":
            properties = current.get("properties")
            if not isinstance(properties, dict) or not isinstance(properties.get(token), dict):
                _raise_solve_recipe_issue(
                    code="recipe_pointer_path_absent",
                    location=location,
                    message="This pointer path is absent from its selected source schema.",
                    violated_condition="a pointer path must exist in its selected source schema",
                    expected_category="a pointer path declared by the selected source schema",
                    remediation="Use a path that exists in the selected source schema.",
                )
            current = cast(Mapping[str, JsonValue], properties[token])
            continue
        if schema_type == "array":
            if not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
                _raise_solve_recipe_issue(
                    code="recipe_pointer_array_index_noncanonical",
                    location=location,
                    message="This pointer uses a non-canonical array index.",
                    violated_condition="array pointer segments must be canonical decimal indexes",
                    expected_category="a pointer with canonical array indexes",
                    remediation="Use canonical non-negative decimal array indexes.",
                )
            items = current.get("items")
            if not isinstance(items, dict):
                _raise_solve_recipe_issue(
                    code="recipe_pointer_array_schema_invalid",
                    location=location,
                    message="The selected frozen array source has no item schema.",
                    violated_condition="a frozen array source must declare an item schema",
                    expected_category="a repaired frozen source schema",
                    remediation="Repair the frozen source schema before retrying the recipe.",
                    retryable=False,
                )
            current = items
            continue
        _raise_solve_recipe_issue(
            code="recipe_pointer_traverses_scalar",
            location=location,
            message="This pointer traverses beyond a scalar value in its selected source schema.",
            violated_condition="a pointer may traverse only object properties or array items",
            expected_category="a pointer that stops at or traverses a structured source value",
            remediation="Use a shorter pointer or select a structured source value.",
        )
    return current


def _raise_solve_recipe_issue(
    *,
    code: str,
    location: tuple[str | int, ...],
    message: str,
    violated_condition: str,
    expected_category: str,
    remediation: str,
    retryable: bool = True,
) -> NoReturn:
    """Raise one framework-authored, candidate-safe solve-recipe diagnostic.

    Recipe text comes from the Challenger and can be both wrong and sensitive.
    The correction loop therefore receives only a structural location and a
    closed explanation authored here; it never gets a stringified rejected
    identifier, pointer, literal, or schema error.
    """

    raise StructuredValidationError(
        ValidationDiagnostic(
            owner_component="verifier",
            validation_phase="solve_recipe",
            frontier_ordinal=25,
            issues=(
                SafeValidationIssue(
                    code,
                    location,
                    message,
                    retryable=retryable,
                    violated_condition=violated_condition,
                    expected_category=expected_category,
                    remediation=remediation,
                ),
            ),
        )
    )


def _schemas_compatible(
    source: Mapping[str, JsonValue],
    target: Mapping[str, JsonValue],
) -> bool:
    source_type = source.get("type")
    target_type = target.get("type")
    if source_type == target_type:
        return True
    return source_type == "integer" and target_type == "number"


def _schema_type_label(schema: Mapping[str, JsonValue]) -> str:
    """Return one bounded, model-visible label for a JSON-schema value type."""

    schema_type = schema.get("type")
    if isinstance(schema_type, str):
        return schema_type
    return "schema-defined value"


def _enumerate_legal_pointers(
    schema: Mapping[str, JsonValue],
    *,
    visible_fields: set[str] | None = None,
) -> list[tuple[str, Mapping[str, JsonValue]]]:
    """Enumerate every legal RFC 6901 pointer derivable from a JSON schema.

    Mirrors ``_schema_at_pointer`` branch logic exactly: an object node emits
    one pointer per declared ``properties`` key (segment 0 respects the
    actor-visibility filter) and recurses; an array node emits ``/0`` (the
    canonical representative index) and recurses into ``items``; a scalar or
    type-less node stops (never descends through a scalar).  The emitted set is
    therefore a *superset* of what the pointer validator accepts for structured
    values and a precise subset for the scalar-traversal trap, so a model
    picking from this closed set can never trigger ``recipe_pointer_traverses_scalar``.
    Returns ``(pointer, node_schema)`` pairs in breadth-first order.
    """

    results: list[tuple[str, Mapping[str, JsonValue]]] = []

    def _visit(
        current: Mapping[str, JsonValue],
        *,
        tokens: list[str],
        depth: int,
    ) -> None:
        if depth > 32:  # _MAX_POINTER_SEGMENTS alignment (contracts/reachability.py)
            return
        schema_type = current.get("type")
        if schema_type == "object":
            properties = current.get("properties")
            if not isinstance(properties, dict):
                return
            for key in properties:
                child = properties[key]
                if not isinstance(child, dict):
                    continue
                if depth == 0 and visible_fields is not None and key not in visible_fields:
                    continue  # actor-visibility gate (segment 0)
                next_tokens = [*tokens, key]
                pointer = "/" + "/".join(
                    tok.replace("~", "~0").replace("/", "~1") for tok in next_tokens
                )
                results.append((pointer, child))
                _visit(child, tokens=next_tokens, depth=depth + 1)
        elif schema_type == "array":
            items = current.get("items")
            if not isinstance(items, dict):
                return
            next_tokens = [*tokens, "0"]
            pointer = "/" + "/".join(
                tok.replace("~", "~0").replace("/", "~1") for tok in next_tokens
            )
            results.append((pointer, items))
            _visit(items, tokens=next_tokens, depth=depth + 1)
        # scalar or missing type: stop, do not descend.

    _visit(schema, tokens=[], depth=0)
    return results


def _solve_recipe_binding_guide(
    tasks: Sequence[TaskRequirement],
    tools: Sequence[ToolContract],
) -> list[JsonValue]:
    """Project type-compatible public-goal bindings into the Direct Agent view.

    The guide is now a CLOSED enumeration of every legal pointer derivable from
    the frozen ``public_goal`` schema (including deep pointers), per tool
    argument, across every frozen tool a task may use.  A model picking a
    pointer only from this set can never hit ``recipe_pointer_traverses_scalar``:
    the enumerator mirrors ``_schema_at_pointer`` exactly, so every emitted
    pointer passes the pointer validator.  An empty candidate list means the
    argument must be a schema-valid literal (or an earlier public result).
    """

    tools_by_id = {tool.surface.tool_id: tool for tool in tools}
    guide: list[JsonValue] = []
    for task in tasks:
        # Enumerate the closed legal-pointer set for this task's public_goal
        # once; every tool argument filters this set by type compatibility.
        goal_pointers = _enumerate_legal_pointers(task.public_goal_schema)
        # Enumerate ALL frozen tools a task may bind, not just required ones:
        # the validator checks every step for every tool the Challenger uses,
        # so a guide that omits a tool leaves that argument with no candidates.
        for tool_id in sorted(tools_by_id):
            tool = tools_by_id[tool_id]
            input_schema = tool.surface.input_schema
            input_properties = input_schema.get("properties")
            required = input_schema.get("required")
            if not isinstance(input_properties, dict) or not isinstance(required, list):
                continue
            arguments: list[JsonValue] = []
            for argument_name in sorted(item for item in required if isinstance(item, str)):
                target_schema = input_properties.get(argument_name)
                if not isinstance(target_schema, dict):
                    continue
                candidates: list[JsonValue] = []
                for pointer, source_schema in goal_pointers:
                    if not _schemas_compatible(source_schema, target_schema):
                        continue
                    candidates.append(
                        {
                            "source": "public_goal",
                            "pointer": pointer,
                            "value_type": _schema_type_label(source_schema),
                        }
                    )
                arguments.append(
                    {
                        "argument": argument_name,
                        "target_type": _schema_type_label(target_schema),
                        "candidates": candidates,
                    }
                )
            guide.append(
                {
                    "task_type": task.task_type,
                    "tool_id": tool_id,
                    "required_arguments": arguments,
                }
            )
    return guide

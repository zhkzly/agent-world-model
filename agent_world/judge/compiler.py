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
from typing import Any, Protocol, TypeVar, cast

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
    InvocationRequest,
    InvocationResult,
    NodeCapabilityRequirement,
    ResolvedAgentProfile,
    assert_agent_output_advisory,
)

from .models import (
    BoundVerifierCaseIntent,
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


@dataclass(frozen=True, slots=True)
class CompiledVerifier:
    verifier: VerifierIR
    verifier_ref: ArtifactRef
    invocation_results: tuple[InvocationResult, ...]
    checkpoint_refs: tuple[ArtifactRef, ...] = ()


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
                    bool(design.verification.required_metamorphic_relations)
                    and batch_index == 0
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
        session = None
        immutable_prompt = prompt
        current_prompt = prompt
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
                    continued_session=True,
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
                active_repair_entry = await repair_authority.authorize(
                    owner_node="verifier",
                    lineage_id=lineage_id,
                    role="challenger",
                    repair_mode=repair_mode,
                    issue_codes=issue_codes,
                    continued_session=True,
                    diagnostic=diagnostic,
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
                            metadata={
                                "role": "challenger",
                                "lineage_id": lineage_id,
                                "attempt": attempt,
                            },
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
                if (
                    result.error is not None
                    and result.error.retryable
                    and attempt < self.maximum_structured_reworks
                    and attempt + 1 < budget.agent_turns
                ):
                    # Provider/transport failures are code-routed local retries, not
                    # semantic corrections. Restart from the immutable batch prompt in
                    # a fresh session so partial provider state cannot affect VerifierIR.
                    await authorize_repair(
                        (backend_issue,),
                        repair_mode=StructuredRepairMode.BACKEND_RETRY,
                    )
                    session = None
                    current_prompt = immutable_prompt
                    continue
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
                if attempt >= self.maximum_structured_reworks or result.session is None:
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
                session = result.session
                current_prompt = (
                    "The previous VerifierIntent violated the framework contract. Correct the "
                    "same private verifier proposal without reading or changing Runtime code. "
                    f"Framework-authored safe diagnostics:\n{diagnostic.feedback}"
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
        if len(tasks) != len(set(allowed_task_types)):
            raise ValueError("VerifierIntent task scope is unknown")
        reference_issues: list[SafeValidationIssue] = []
        for case_index, case in enumerate(intent.cases):
            seen_expectations: set[tuple[str, int, bool]] = set()
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
                        )
                    )
                key = (
                    str(expectation.kind),
                    expectation.after_action_ordinal,
                    expectation.expected,
                )
                if key in seen_expectations:
                    reference_issues.append(
                        SafeValidationIssue(
                            "intent_expectation_duplicate",
                            location,
                            "Each (kind, after_action_ordinal, expected) combination may "
                            "appear only once in a case.",
                        )
                    )
                seen_expectations.add(key)
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
                value_schema_issues.extend(
                    VerifierCompiler._json_schema_issues(
                        schema=tools[action.tool_id].surface.input_schema,
                        value=action.arguments,
                        location=("cases", case_index, "actions", action_index, "arguments"),
                        code="intent_action_input_schema_mismatch",
                        value_label="action input",
                    )
                )
            canonical = {
                item.kind
                for item in case.expectations
                if item.kind in _CANONICAL_PROPERTY_KIND.values()
            }
            if not canonical:
                raise ValueError(
                    f"VerifierIntent case at index {case_index} "
                    "requires a canonical expectation"
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
        for recipe in intent.solve_recipes:
            requirement = tasks.get(recipe.task_type)
            if requirement is None:
                raise ValueError(
                    f"VerifierIntent recipe {recipe.recipe_id} is outside this task batch"
                )
            _validate_solve_recipe(recipe, requirement=requirement, design=design)

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
                    f"Add these fields required by the frozen {value_label} schema: "
                    f"{missing_text}."
                    if missing_text
                    else f"Add every field required by the frozen {value_label} schema here."
                )
            elif keyword == "additionalProperties":
                message = (
                    f"Remove fields not declared by the frozen closed {value_label} schema here."
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
        """Expand family-level trajectory labels into exact trusted Rule closure."""

        bound_cases = VerifierCompiler._bind_intent_cases(intent)
        rules = design_rule_index(design)
        required = tuple(dict.fromkeys(required_rule_ids))
        if not set(required) <= set(rules):
            raise ValueError("VerifierIntent compiler received an unknown Rule")
        allowed_tasks = set(allowed_task_types)
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

        case_assertions: dict[str, list[VerifierAssertion]] = {
            item.case_id: [] for item in bound_cases
        }
        property_cases: dict[str, set[str]] = {rule_id: set() for rule_id in required}
        binding_issues: list[SafeValidationIssue] = []
        for rule_index, rule_id in enumerate(required):
            rule = rules[rule_id]
            canonical_kind = _CANONICAL_PROPERTY_KIND[rule.family]
            owner = task_rule_owners.get(rule_id)
            if owner is not None and owner not in allowed_tasks:
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_outside_task_batch",
                        ("required_rules", rule_index),
                        "A required Rule belongs to a task outside this capacity batch.",
                    )
                )
                continue
            matches: list[tuple[BoundVerifierCaseIntent, int, bool]] = []
            for case in bound_cases:
                if owner is not None and case.task_type != owner:
                    continue
                for expectation in case.expectations:
                    if expectation.kind != canonical_kind:
                        continue
                    action_tool = case.actions[expectation.action_index].tool_id
                    if rule_tools[rule_id] and action_tool not in rule_tools[rule_id]:
                        continue
                    matches.append((case, expectation.action_index, expectation.expected))
            partitions = {case.partition for case, _index, expected in matches if expected}
            if "sealed" not in partitions or not partitions & {"public", "repair"}:
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_positive_partition_coverage",
                        ("required_rules", rule_index),
                        "Bind this Rule to positive obligations in both sealed and "
                        "public-or-repair trajectories.",
                    )
                )
            if rule.case_sensitivity == "positive_and_negative" and not any(
                not expected for _case, _index, expected in matches
            ):
                binding_issues.append(
                    SafeValidationIssue(
                        "rule_negative_obligation_missing",
                        ("required_rules", rule_index),
                        "Bind this positive-and-negative Rule to at least one negative obligation.",
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
            dependencies=(design_ref, world_spec_ref),
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
        required_rules = (
            set(design.verification.required_rule_ids)
            if required_rule_ids is None
            else set(required_rule_ids)
        )
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
        for case in draft.cases:
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
                obligations.setdefault(assertion.rule_id, []).append(
                    (case.partition, assertion.expected)
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
        for recipe in draft.solve_recipes:
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
        effective_property_families: set[str] = (
            set(str(item) for item in design.verification.required_property_families)
            if required_property_families is None
            else set(str(item) for item in required_property_families)
        )
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
            """You are the isolated Challenger inside Agent World Foundry.
Project purpose: prove that an untrusted generated Runtime implements the evidence-backed
WorldSpec with real programmatic state transitions, without sharing expected answers with it.

The framework has already compiled the only information you need into the compact JSON context
below. You have no tools and must not request files, shell commands, source code, or more context.
Produce exactly one compact VerifierIntent structured output. You propose only domain reset
configs, tool-action trajectories, and family-level expectations such as "transition after action
N should be true". Never enumerate Rule ids or properties: framework code expands each family
expectation to the complete frozen Rule closure and rejects uncovered rules deterministically.
For every coverage requirement provide a positive semantic expectation; when
positive_and_negative is true, also provide a negative expectation. Framework code pairs every
semantic trajectory into public and sealed cases and assigns both case ids and independent uint64
seeds. You must not propose or infer disclosure partitions, ids, or seeds.
Coverage requirements with `scope="world_shared"` and `task_type=null` apply across the assigned
real tasks; `world_shared` is never a case task_type. Choose case task_type only from `tasks`.
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

`after_action_ordinal` is one-based: the first action is 1, the second is 2, and a case containing
one action permits only ordinal 1. Never use zero and never use an ordinal larger than the number
of actions in that case. Framework code deterministically converts the ordinal to its private
zero-based Verifier IR index.

You may also propose bounded ParameterizedSolveRecipe values. A recipe is only a solving
accelerator, never an expected answer or proof. It may reference public_goal, reset_observation,
or earlier public tool results/observations through strict RFC 6901 pointers. It cannot reference
initial_config, evaluator_goal, Rule IR, snapshots, source code, or release policy. Use at most one
preferred recipe per task type. Every recipe must use only tools available to every allowed task
actor, satisfy tool input schemas, include all required tools, and meet minimum_tool_calls.

`reset_config_schema_id` selects a schema from `reset_config_schemas`; it is a context reference,
not a Runtime field. Never copy it into reset_config. Keep trajectories on their exact task type.

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
        reinterpret.  This projection deduplicates reset schemas and exposes only legitimate
        domain inputs plus framework-owned Rule identities and coverage metadata.
        """

        rules = design_rule_index(design)
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
        selected_rule_ids = (
            set(design.verification.required_rule_ids)
            if required_rule_ids is None
            else set(required_rule_ids)
        )
        if not selected_rule_ids <= set(rules):
            raise ValueError("Challenger context references an unknown Rule")
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
            tool_id for rule_id in selected_rule_ids for tool_id in rule_tools[rule_id]
        )
        coverage_groups: dict[tuple[str, str, str, tuple[str, ...], bool], int] = {}
        for rule_id in sorted(selected_rule_ids):
            rule = rules[rule_id]
            task_owner = task_rule_owners.get(rule_id)
            key = (
                "task" if task_owner is not None else "world_shared",
                task_owner or "",
                str(_CANONICAL_PROPERTY_KIND[rule.family]),
                tuple(sorted(rule_tools[rule_id])),
                rule.case_sensitivity == "positive_and_negative",
            )
            coverage_groups[key] = coverage_groups.get(key, 0) + 1

        return {
            "schema_version": "agent-world.challenger-context.v3",
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
                }
                for tool in design.world_spec.tools
                if tool.surface.tool_id in relevant_tool_ids
            ],
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
                    "initial_rule_ids": [rule.rule_id for rule in task.initial_state_constraints],
                    "success_rule_ids": [rule.rule_id for rule in task.success_conditions],
                    "failure_rule_ids": [rule.rule_id for rule in task.failure_conditions],
                    "terminal_rule_ids": [rule.rule_id for rule in task.terminal_conditions],
                }
                for task in selected_tasks
            ],
            "coverage_requirements": [
                {
                    "scope": scope,
                    "task_type": task_type or None,
                    "property_kind": property_kind,
                    "tool_ids": list(tool_ids),
                    "positive_and_negative": positive_and_negative,
                    "rule_count": count,
                }
                for (
                    scope,
                    task_type,
                    property_kind,
                    tool_ids,
                    positive_and_negative,
                ), count in sorted(coverage_groups.items())
            ],
            "required_property_families": list(
                design.verification.required_property_families
                if required_property_families is None
                else required_property_families
            ),
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
        rule_tools: dict[str, set[str]] = {rule_id: set() for rule_id in design_rule_index(design)}
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

        for rule_id in design.verification.required_rule_ids:
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
        missing = {str(item) for item in design.verification.required_property_families} - covered
        if missing:
            first_task = design.curriculum.task_types[0].task_type
            assignments[first_task].update(missing)
        return {
            task.task_type: tuple(sorted(assignments[task.task_type]))
            for task in design.curriculum.task_types
        }

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
        quotas = tuple(
            quotient + (1 if index < remainder else 0) for index in range(batch_count)
        )
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
    "VerifierCompilationError",
    "VerifierCompiler",
]


def _validate_solve_recipe(
    recipe: ParameterizedSolveRecipe,
    *,
    requirement: TaskRequirement,
    design: EnvironmentDesign,
) -> None:
    tools = {tool.surface.tool_id: tool for tool in design.world_spec.tools}
    required_tools = set(requirement.required_tool_ids)
    used_tools = {step.tool_id for step in recipe.steps}
    missing = required_tools - used_tools
    if missing:
        raise ValueError(f"solve recipe {recipe.recipe_id} omits required tools: {sorted(missing)}")
    if len(recipe.steps) < requirement.minimum_tool_calls:
        raise ValueError(f"solve recipe {recipe.recipe_id} does not meet minimum_tool_calls")

    boundary_by_actor = {
        actor.actor: actor for actor in design.world_spec.boundary.actors_and_authority
    }
    for step_index, step in enumerate(recipe.steps):
        tool = tools.get(step.tool_id)
        if tool is None:
            raise ValueError(
                f"solve recipe {recipe.recipe_id} references unknown tool {step.tool_id}"
            )
        denied = set(requirement.allowed_actor_ids) - set(tool.semantics.permission.allowed_actors)
        if denied:
            raise ValueError(
                f"solve recipe {recipe.recipe_id} uses {step.tool_id}, unavailable to task "
                f"actors {sorted(denied)}"
            )
        input_schema = tool.surface.input_schema
        properties = input_schema.get("properties")
        required = input_schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ValueError(f"tool {step.tool_id} has no closed object input schema")
        required_names = {item for item in required if isinstance(item, str)}
        if len(required_names) != len(required):
            raise ValueError(f"tool {step.tool_id} required fields must be strings")
        unknown_arguments = set(step.arguments) - set(properties)
        missing_arguments = required_names - set(step.arguments)
        if unknown_arguments or missing_arguments:
            raise ValueError(
                f"solve recipe {recipe.recipe_id} step {step.step_id} arguments do not match "
                f"{step.tool_id}; missing={sorted(missing_arguments)}, "
                f"unknown={sorted(unknown_arguments)}"
            )
        for name, argument in step.arguments.items():
            target_schema = properties[name]
            if not isinstance(target_schema, dict):
                raise ValueError(f"tool {step.tool_id} argument schema {name} is invalid")
            if isinstance(argument, RecipeLiteral):
                errors = tuple(Draft202012Validator(target_schema).iter_errors(argument.value))
                if errors:
                    raise ValueError(
                        f"solve recipe {recipe.recipe_id} literal for {step.tool_id}.{name} "
                        "violates the tool input schema"
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
            )
            if not _schemas_compatible(source_schema, target_schema):
                raise ValueError(
                    f"solve recipe {recipe.recipe_id} pointer for {step.tool_id}.{name} "
                    "has an incompatible declared type"
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
            raise ValueError(f"solve recipe {recipe.recipe_id} reads a non-previous step")
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
    return _schema_at_pointer(schema, pointer.pointer, visible_fields=visible_fields)


def _schema_at_pointer(
    schema: Mapping[str, JsonValue],
    pointer: str,
    *,
    visible_fields: set[str] | None,
) -> Mapping[str, JsonValue]:
    current: Mapping[str, JsonValue] = schema
    for index, raw in enumerate(pointer.split("/")[1:]):
        token = raw.replace("~1", "/").replace("~0", "~")
        if index == 0 and visible_fields is not None and token not in visible_fields:
            raise ValueError(f"recipe pointer reads an actor-invisible field: {pointer}")
        schema_type = current.get("type")
        if schema_type == "object":
            properties = current.get("properties")
            if not isinstance(properties, dict) or not isinstance(properties.get(token), dict):
                raise ValueError(f"recipe pointer is absent from its source schema: {pointer}")
            current = cast(Mapping[str, JsonValue], properties[token])
            continue
        if schema_type == "array":
            if not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
                raise ValueError(f"recipe pointer has a non-canonical array index: {pointer}")
            items = current.get("items")
            if not isinstance(items, dict):
                raise ValueError(f"recipe pointer array source has no item schema: {pointer}")
            current = items
            continue
        raise ValueError(f"recipe pointer traverses a scalar schema: {pointer}")
    return current


def _schemas_compatible(
    source: Mapping[str, JsonValue],
    target: Mapping[str, JsonValue],
) -> bool:
    source_type = source.get("type")
    target_type = target.get("type")
    if source_type == target_type:
        return True
    return source_type == "integer" and target_type == "number"

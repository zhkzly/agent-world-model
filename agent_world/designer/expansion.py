"""Replaceable ask/tell policies for tool-first environment expansion.

Policies choose immutable parents, admitted clues, an operator, and bounded
parameters.  They never synthesize WorldSpec, edit a workspace, call Judge, or
make a release decision.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from collections.abc import Sequence
from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    Budget,
    CandidateOutcome,
    Identifier,
    KeyValue,
    MutationIntent,
    NonEmptyStr,
    V2Contract,
)

OperatorKind = Literal[
    "tool_surface",
    "tool_semantics",
    "transition_constraint",
    "task_scope",
    "composite",
]


class ParentDescriptor(V2Contract):
    package_ref: ArtifactRef
    coverage_dimensions: tuple[Identifier, ...] = ()
    behavior_dimensions: tuple[Identifier, ...] = ()


class OperatorDescriptor(V2Contract):
    kind: OperatorKind
    version: NonEmptyStr = "1"
    weight: Annotated[float, Field(gt=0)] = 1
    requires_clue: bool = False
    minimum_parents: Annotated[int, Field(ge=1, le=4)] = 1
    maximum_parents: Annotated[int, Field(ge=1, le=4)] = 1
    parameter_axes: dict[Identifier, tuple[NonEmptyStr, ...]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_parent_range(self) -> OperatorDescriptor:
        if self.maximum_parents < self.minimum_parents:
            raise ValueError("maximum_parents cannot be smaller than minimum_parents")
        return self


class OperatorCatalog(V2Contract):
    operators: Annotated[tuple[OperatorDescriptor, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_operators(self) -> OperatorCatalog:
        kinds = [operator.kind for operator in self.operators]
        if len(set(kinds)) != len(kinds):
            raise ValueError("operator kinds must be unique")
        return self

    @classmethod
    def tool_first_default(cls) -> OperatorCatalog:
        return cls(
            operators=(
                OperatorDescriptor(
                    kind="tool_surface",
                    weight=1.4,
                    parameter_axes={
                        "operation": ("add", "replace", "split", "merge", "remove"),
                        "focus": ("schema", "namespace", "composition", "visibility"),
                    },
                ),
                OperatorDescriptor(
                    kind="tool_semantics",
                    weight=1.8,
                    parameter_axes={
                        "focus": (
                            "errors",
                            "permissions",
                            "observations",
                            "idempotency",
                            "transactions",
                            "rollback",
                            "concurrency",
                        ),
                    },
                ),
                OperatorDescriptor(
                    kind="transition_constraint",
                    weight=1.5,
                    parameter_axes={
                        "focus": ("precondition", "postcondition", "invariant", "time", "resource"),
                    },
                ),
                OperatorDescriptor(
                    kind="task_scope",
                    weight=1,
                    parameter_axes={
                        "focus": (
                            "goal_distribution",
                            "horizon",
                            "entity_cardinality",
                            "partial_observability",
                            "multi_tool",
                        ),
                    },
                ),
                OperatorDescriptor(
                    kind="composite",
                    weight=0.6,
                    requires_clue=False,
                    minimum_parents=1,
                    maximum_parents=3,
                    parameter_axes={
                        "focus": ("cross_system", "adjacent_workflow", "tool_migration"),
                    },
                ),
            )
        )


class ExpansionContext(V2Contract):
    context_id: Identifier
    snapshot_ref: ArtifactRef
    parents: Annotated[tuple[ParentDescriptor, ...], Field(min_length=1)]
    anchor_parent_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    clue_refs: tuple[ArtifactRef, ...] = ()
    target_coverage_dimensions: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    operator_catalog: OperatorCatalog = Field(default_factory=OperatorCatalog.tool_first_default)
    campaign_seed: Annotated[int, Field(ge=0)]
    maximum_iterations: Annotated[int, Field(ge=1)] = 20
    maximum_no_release_iterations: Annotated[int, Field(ge=1)] = 8

    @model_validator(mode="after")
    def validate_parent_universe(self) -> ExpansionContext:
        parents_by_revision: dict[str, ArtifactRef] = {}
        for parent in self.parents:
            existing = parents_by_revision.get(parent.package_ref.revision_id)
            if existing is not None:
                raise ValueError("ExpansionContext parents must have unique revisions")
            parents_by_revision[parent.package_ref.revision_id] = parent.package_ref
        anchor_revisions: set[str] = set()
        for anchor in self.anchor_parent_refs:
            if anchor.revision_id in anchor_revisions:
                raise ValueError("anchor_parent_refs must have unique revisions")
            anchor_revisions.add(anchor.revision_id)
            if parents_by_revision.get(anchor.revision_id) != anchor:
                raise ValueError("Every anchor_parent_ref must be an exact member of parents")
        return self


class AskBudget(V2Contract):
    maximum_intents: Annotated[int, Field(ge=1, le=128)] = 1
    remaining: Budget = Field(default_factory=Budget)


class PolicyCheckpoint(V2Contract):
    policy_id: Identifier
    policy_version: NonEmptyStr
    iteration: Annotated[int, Field(ge=0)] = 0
    seen_outcome_ids: tuple[Identifier, ...] = ()
    terminal_counts: dict[Identifier, Annotated[int, Field(ge=0)]] = Field(default_factory=dict)
    archive_parent_refs: tuple[ArtifactRef, ...] = ()
    archive_behavior_dimensions: tuple[Identifier, ...] = ()
    no_release_iterations: Annotated[int, Field(ge=0)] = 0


class StopDecision(V2Contract):
    stop: bool
    reason: Literal[
        "continue",
        "iteration_limit",
        "no_release_progress",
        "budget_exhausted",
        "no_admissible_operator",
    ]


class EnvironmentExpansionPolicy(Protocol):
    policy_id: str
    version: str

    async def ask(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint | None,
        budget: AskBudget,
    ) -> tuple[MutationIntent, ...]: ...

    async def tell(
        self,
        checkpoint: PolicyCheckpoint | None,
        outcomes: Sequence[CandidateOutcome],
    ) -> PolicyCheckpoint: ...

    def should_stop(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint,
        remaining: Budget,
    ) -> StopDecision: ...


def _seed(context: ExpansionContext, policy_id: str, iteration: int, index: int) -> int:
    material = f"{context.context_id}:{context.campaign_seed}:{policy_id}:{iteration}:{index}"
    return int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big")


def _intent_id(
    *,
    context: ExpansionContext,
    policy_id: str,
    iteration: int,
    index: int,
) -> str:
    material = f"{context.content_digest()}:{policy_id}:{iteration}:{index}"
    return f"intent:{hashlib.sha256(material.encode()).hexdigest()[:24]}"


def _parameters(operator: OperatorDescriptor, rng: random.Random) -> tuple[KeyValue, ...]:
    return tuple(
        KeyValue(key=axis, value=rng.choice(values))
        for axis, values in sorted(operator.parameter_axes.items())
        if values
    )


def _choose_parents(
    parents: Sequence[ArtifactRef],
    operator: OperatorDescriptor,
    rng: random.Random,
    *,
    preferred_parent_refs: Sequence[ArtifactRef] = (),
    minimum_parents: int | None = None,
) -> tuple[ArtifactRef, ...]:
    maximum = min(operator.maximum_parents, len(parents))
    minimum = max(operator.minimum_parents, minimum_parents or 0)
    if maximum < minimum:
        raise ValueError("The parent pool cannot satisfy the operator's parent requirement")
    count = rng.randint(minimum, maximum)
    preferred_revisions = {item.revision_id for item in preferred_parent_refs}
    remaining = list(parents)
    selected: list[ArtifactRef] = []
    for _ in range(count):
        weights = [
            2.0 if item.revision_id in preferred_revisions else 1.0
            for item in remaining
        ]
        selected_index = rng.choices(range(len(remaining)), weights=weights, k=1)[0]
        selected.append(remaining.pop(selected_index))
    return tuple(selected)


def _unique_parent_pool(*groups: Sequence[ArtifactRef]) -> tuple[ArtifactRef, ...]:
    """Combine exact immutable parents without silently aliasing a revision."""

    by_revision: dict[str, ArtifactRef] = {}
    for group in groups:
        for parent in group:
            existing = by_revision.get(parent.revision_id)
            if existing is not None and existing != parent:
                raise ValueError("Parent revision resolves to conflicting ArtifactRefs")
            by_revision.setdefault(parent.revision_id, parent)
    return tuple(by_revision.values())


class _PolicyBase:
    policy_id = "base"
    version = "1"

    def _checkpoint(self, checkpoint: PolicyCheckpoint | None) -> PolicyCheckpoint:
        if checkpoint is None:
            return PolicyCheckpoint(policy_id=self.policy_id, policy_version=self.version)
        if checkpoint.policy_id != self.policy_id or checkpoint.policy_version != self.version:
            raise ValueError("checkpoint belongs to a different policy implementation")
        return checkpoint

    async def tell(
        self,
        checkpoint: PolicyCheckpoint | None,
        outcomes: Sequence[CandidateOutcome],
    ) -> PolicyCheckpoint:
        current = self._checkpoint(checkpoint)
        seen = set(current.seen_outcome_ids)
        new_outcomes = [outcome for outcome in outcomes if outcome.outcome_id not in seen]
        counts = Counter(current.terminal_counts)
        released_refs = list(current.archive_parent_refs)
        behavior = set(current.archive_behavior_dimensions)
        released = False
        fitness_eligible = False
        for outcome in new_outcomes:
            seen.add(outcome.outcome_id)
            counts[outcome.terminal_status] += 1
            if outcome.terminal_status != "infrastructure_error":
                fitness_eligible = True
            if (
                outcome.terminal_status == "released"
                and outcome.released_package_ref is not None
            ):
                released = True
                if outcome.released_package_ref not in released_refs:
                    released_refs.append(outcome.released_package_ref)
                behavior.update(item.descriptor for item in outcome.behavior_descriptors)
        return PolicyCheckpoint(
            policy_id=self.policy_id,
            policy_version=self.version,
            iteration=current.iteration + (1 if new_outcomes else 0),
            seen_outcome_ids=tuple(sorted(seen)),
            terminal_counts=dict(sorted(counts.items())),
            archive_parent_refs=tuple(released_refs),
            archive_behavior_dimensions=tuple(sorted(behavior)),
            no_release_iterations=0
            if released
            else current.no_release_iterations + (1 if fitness_eligible else 0),
        )

    def should_stop(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint,
        remaining: Budget,
    ) -> StopDecision:
        if checkpoint.iteration >= context.maximum_iterations:
            return StopDecision(stop=True, reason="iteration_limit")
        if checkpoint.no_release_iterations >= context.maximum_no_release_iterations:
            return StopDecision(stop=True, reason="no_release_progress")
        if remaining.agent_turns == 0 or remaining.wall_seconds == 0:
            return StopDecision(stop=True, reason="budget_exhausted")
        return StopDecision(stop=False, reason="continue")

    @staticmethod
    def _eligible_operators(
        context: ExpansionContext,
        *,
        parent_count: int | None = None,
        clue_available: bool | None = None,
    ) -> tuple[OperatorDescriptor, ...]:
        available_parents = len(context.parents) if parent_count is None else parent_count
        has_clue = bool(context.clue_refs) if clue_available is None else clue_available

        def eligible(operator: OperatorDescriptor) -> bool:
            if operator.requires_clue and not has_clue:
                return False
            minimum = operator.minimum_parents
            if operator.kind == "composite" and not has_clue:
                minimum = max(2, minimum)
            return minimum <= available_parents and minimum <= operator.maximum_parents

        return tuple(
            operator
            for operator in context.operator_catalog.operators
            if eligible(operator)
        )

    def _make_intent(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint,
        index: int,
        operator: OperatorDescriptor,
        rng: random.Random,
        *,
        parent_pool: Sequence[ArtifactRef] | None = None,
        clue: ArtifactRef | None = None,
        choose_random_clue: bool = True,
    ) -> MutationIntent:
        parents = (
            tuple(parent_pool)
            if parent_pool is not None
            else tuple(item.package_ref for item in context.parents)
        )
        selected_clue = clue
        if selected_clue is None and choose_random_clue and context.clue_refs:
            selected_clue = rng.choice(context.clue_refs)
        if operator.requires_clue and selected_clue is None:
            raise ValueError("The selected operator requires an admitted clue")
        minimum_parents = operator.minimum_parents
        if operator.kind == "composite" and selected_clue is None:
            minimum_parents = max(2, minimum_parents)
        selected_parents = _choose_parents(
            parents,
            operator,
            rng,
            preferred_parent_refs=context.anchor_parent_refs,
            minimum_parents=minimum_parents,
        )
        return MutationIntent(
            intent_id=_intent_id(
                context=context,
                policy_id=self.policy_id,
                iteration=checkpoint.iteration,
                index=index,
            ),
            parent_refs=selected_parents,
            primary_parent_ref=selected_parents[0],
            clue_refs=(selected_clue,) if selected_clue else (),
            operator=operator.kind,
            operator_version=operator.version,
            parameters=_parameters(operator, rng),
            seed=rng.getrandbits(63),
            target_coverage_dimensions=context.target_coverage_dimensions,
        )


class RandomSearchPolicy(_PolicyBase):
    policy_id = "random-search"

    async def ask(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint | None,
        budget: AskBudget,
    ) -> tuple[MutationIntent, ...]:
        current = self._checkpoint(checkpoint)
        parent_pool = _unique_parent_pool(
            tuple(item.package_ref for item in context.parents),
            current.archive_parent_refs,
        )
        operators = self._eligible_operators(
            context,
            parent_count=len(parent_pool),
        )
        if not operators:
            return ()
        weights = [operator.weight for operator in operators]
        intents = []
        for index in range(budget.maximum_intents):
            rng = random.Random(  # noqa: S311 - reproducible campaign sampling, not security
                _seed(context, self.policy_id, current.iteration, index)
            )
            operator = rng.choices(operators, weights=weights, k=1)[0]
            intents.append(
                self._make_intent(
                    context,
                    current,
                    index,
                    operator,
                    rng,
                    parent_pool=parent_pool,
                )
            )
        return tuple(intents)


class WideSearchPolicy(_PolicyBase):
    """Systematically covers clue/operator/parent combinations before repeating."""

    policy_id = "wide-search"

    async def ask(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint | None,
        budget: AskBudget,
    ) -> tuple[MutationIntent, ...]:
        current = self._checkpoint(checkpoint)
        clues: tuple[ArtifactRef | None, ...] = context.clue_refs or (None,)
        snapshot_parents = tuple(item.package_ref for item in context.parents)
        anchor_revisions = {item.revision_id for item in context.anchor_parent_refs}
        parent_pool = _unique_parent_pool(
            context.anchor_parent_refs,
            tuple(
                item
                for item in snapshot_parents
                if item.revision_id not in anchor_revisions
            ),
            current.archive_parent_refs,
        )
        operators = self._eligible_operators(
            context,
            parent_count=len(parent_pool),
        )
        if not operators:
            return ()
        intents = []
        for index in range(budget.maximum_intents):
            cursor = current.iteration * budget.maximum_intents + index
            operator = operators[cursor % len(operators)]
            clue = clues[(cursor // len(operators)) % len(clues)]
            parent_index = (cursor // (len(operators) * len(clues))) % len(parent_pool)
            parent = parent_pool[parent_index]
            selected_parent_pool = (
                parent_pool
                if operator.kind == "composite" and clue is None
                else (parent,)
            )
            rng = random.Random(  # noqa: S311 - reproducible campaign sampling, not security
                _seed(context, self.policy_id, current.iteration, index)
            )
            intents.append(
                self._make_intent(
                    context,
                    current,
                    index,
                    operator,
                    rng,
                    parent_pool=selected_parent_pool,
                    clue=clue,
                    choose_random_clue=False,
                )
            )
        return tuple(intents)


class EvolutionaryArchivePolicy(_PolicyBase):
    """Prefer released archive members while preserving external clue injection."""

    policy_id = "evolutionary-archive"

    def __init__(self, *, external_injection_rate: float = 0.25) -> None:
        if not 0 <= external_injection_rate <= 1:
            raise ValueError("external_injection_rate must be in [0, 1]")
        self.external_injection_rate = external_injection_rate

    async def ask(
        self,
        context: ExpansionContext,
        checkpoint: PolicyCheckpoint | None,
        budget: AskBudget,
    ) -> tuple[MutationIntent, ...]:
        current = self._checkpoint(checkpoint)
        snapshot_pool = tuple(item.package_ref for item in context.parents)
        archive_pool = _unique_parent_pool(current.archive_parent_refs)
        parent_universe = _unique_parent_pool(snapshot_pool, archive_pool)
        intents = []
        for index in range(budget.maximum_intents):
            rng = random.Random(  # noqa: S311 - reproducible campaign sampling, not security
                _seed(context, self.policy_id, current.iteration, index)
            )
            inject_external = (
                bool(context.clue_refs) and rng.random() < self.external_injection_rate
            )
            parent_pool = parent_universe if inject_external or not archive_pool else archive_pool
            clue = rng.choice(context.clue_refs) if inject_external else None
            operators = self._eligible_operators(
                context,
                parent_count=len(parent_pool),
                clue_available=clue is not None,
            )
            if not operators:
                continue
            operator_weights = [
                operator.weight
                * (1.5 if operator.kind not in current.archive_behavior_dimensions else 1)
                for operator in operators
            ]
            operator = rng.choices(operators, weights=operator_weights, k=1)[0]
            intents.append(
                self._make_intent(
                    context,
                    current,
                    index,
                    operator,
                    rng,
                    parent_pool=parent_pool,
                    clue=clue,
                    choose_random_clue=False,
                )
            )
        return tuple(intents)


__all__ = [
    "AskBudget",
    "EnvironmentExpansionPolicy",
    "EvolutionaryArchivePolicy",
    "ExpansionContext",
    "OperatorCatalog",
    "OperatorDescriptor",
    "ParentDescriptor",
    "PolicyCheckpoint",
    "RandomSearchPolicy",
    "StopDecision",
    "WideSearchPolicy",
]

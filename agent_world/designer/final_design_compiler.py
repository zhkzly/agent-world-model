"""Pure compilers for the final Scheduler-owned Design suffix.

The historic :mod:`designer.service` bundled these deterministic transforms
with multi-turn Agent orchestration.  The final WorkGraph reuses only their
typed compiler rules: no Artifact store, invocation backend, workspace,
FeedbackContract, repair ledger, or retry state is reachable here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NoReturn

from pydantic import ValidationError

from agent_world.contracts import ArtifactRef, EvidenceGraph, TaskRequirement
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
)

from .models import (
    CurriculumPlanDraft,
    CurriculumPlanSourceDraft,
    EnvironmentDesignDraft,
    EnvironmentSemanticSourceDraft,
    RuleDraft,
    SharedToolSemanticsContract,
    SharedToolSemanticsSourceDraft,
    TaskRequirementDraft,
    TaskRequirementSourceDraft,
    ToolCouplingGroupPlan,
    ToolSemanticsBatchSourceDraft,
    ToolSemanticsDraft,
    TrainingSemanticSourceDraft,
    WorldArchitectureSourceDraft,
    WorldClosureSourceDraft,
    WorldModelDraft,
    WorldRuleSemanticsSourceDraft,
    WorldSemanticSourceIRDraft,
    WorldSkeletonDraft,
)
from .rule_context import RuleContextCatalog, materialize_tool_semantics_bindings
from .service import EnvironmentDesigner
from .validation import StructuredSemanticError


@dataclass(frozen=True, slots=True)
class CompiledWorldRules:
    """Exact world source and executable model derived from one rules draft."""

    # This is the durable Agent-source artifact.  It deliberately has no
    # Agent-provided Rule IR identities: those are framework-derived mechanics,
    # not WorldRules semantics.
    canonical_source: WorldRuleSemanticsSourceDraft
    source: WorldSemanticSourceIRDraft
    world: WorldModelDraft


@dataclass(frozen=True, slots=True)
class CompiledTrainingSemantics:
    """Exact whole-design semantic source and framework-composed Design draft."""

    # Durable TaskCurriculum source retains only Agent-authored meaning.  Rule
    # identities are deterministic framework IR mechanics and must never be
    # persisted as values the Agent was asked to guess.
    canonical_source: TrainingSemanticSourceDraft
    source: EnvironmentSemanticSourceDraft
    design: EnvironmentDesignDraft


@dataclass(frozen=True, slots=True)
class CompiledCurriculumPlan:
    """One canonical, world-bound curriculum topology.

    This deliberately stops before any task-family Rule IR exists.  The
    committed plan is the only authority that may determine the later physical
    ``TaskRequirement`` WorkDefinitions.
    """

    canonical_source: CurriculumPlanSourceDraft
    plan: CurriculumPlanDraft


@dataclass(frozen=True, slots=True)
class CompiledTaskRequirement:
    """One canonical task-family source checked against its frozen plan entry."""

    canonical_source: TaskRequirementSourceDraft
    plan: CurriculumPlanDraft
    target_task_type: str
    source: TaskRequirementDraft
    task: TaskRequirement


def coverage_rule_catalog(world: WorldModelDraft) -> tuple[dict[str, str], ...]:
    """Project the exact existing Rule identities usable by curriculum coverage.

    The source schema cannot express a per-world enum, so the runtime Agent
    receives this small frozen catalog alongside the full WorldModel.  It is a
    navigation projection only: the existing compiler remains the authority
    that validates every submitted reference.
    """

    return tuple(
        {"rule_id": rule.rule_id, "family": rule.family}
        for rule in EnvironmentDesigner._world_rule_sequence(world)
    )


def compile_curriculum_plan_semantics(
    source: CurriculumPlanSourceDraft,
    *,
    world: WorldModelDraft,
    evidence_graph: EvidenceGraph,
) -> CompiledCurriculumPlan:
    """Compile the bounded plan before any task-family Agent call exists.

    A plan is semantic output, but Rule identities inside its sampling section
    are framework mechanics.  Canonicalizing them here makes the committed
    plan safe to use as the sole fan-out authority in a later graph epoch.
    """

    try:
        canonical_source = _canonicalize_curriculum_plan_source(source)
        plan = EnvironmentDesigner._compile_curriculum_plan_source(canonical_source)
        EnvironmentDesigner._validate_curriculum_plan(
            plan,
            world=world,
            evidence_graph=evidence_graph,
        )
    except (StructuredSemanticError, StructuredValidationError, ValidationError, ValueError) as exc:
        _raise_compiler_diagnostic(exc, phase="curriculum_plan_preflight")
    return CompiledCurriculumPlan(
        canonical_source=canonical_source,
        plan=plan,
    )


def compile_task_requirement_semantics(
    source: TaskRequirementSourceDraft,
    *,
    curriculum_plan: CurriculumPlanSourceDraft,
    target_task_type: str,
    world: WorldModelDraft,
    evidence_graph: EvidenceGraph,
) -> CompiledTaskRequirement:
    """Validate one independently executable task-family boundary.

    The caller supplies the target from the committed plan-derived physical
    coordinate.  This prevents an Agent from changing fan-out identity while
    preserving its ownership of the task's business Rules.
    """

    try:
        compiled_plan = compile_curriculum_plan_semantics(
            curriculum_plan,
            world=world,
            evidence_graph=evidence_graph,
        )
        target = next(
            (item for item in compiled_plan.plan.task_plans if item.task_type == target_task_type),
            None,
        )
        if target is None:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="design",
                    validation_phase="task_requirement_target",
                    frontier_ordinal=40,
                    issues=(
                        SafeValidationIssue(
                            "task_requirement_target_not_planned",
                            ("task_type",),
                            "This task requirement does not have a frozen curriculum-plan target.",
                            retryable=False,
                            violated_condition=(
                                "every task requirement coordinate names one committed "
                                "plan task_type"
                            ),
                            expected_category=(
                                "a task_type present in the committed curriculum plan"
                            ),
                        ),
                    ),
                )
            )
        canonical_source = _canonicalize_task_requirement_source(source)
        authored = EnvironmentDesigner._compile_task_requirement_source(
            canonical_source,
            framework_task_type=target.task_type,
        )
        try:
            initial_config_schema = EnvironmentDesigner._compile_task_initial_config_schema(
                world.state.root_state_schema
            )
        except ValueError as exc:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="design",
                    validation_phase="task_initial_config_projection",
                    frontier_ordinal=40,
                    issues=(
                        SafeValidationIssue(
                            "task_initial_config_projection_invalid",
                            ("world", "state", "root_state_schema"),
                            "The frozen world state cannot be projected into the closed "
                            "task reset schema.",
                            retryable=False,
                            violated_condition=(
                                "the framework can derive a closed task initial-config schema "
                                "from the frozen world state"
                            ),
                            expected_category="a framework-projectable closed world state schema",
                        ),
                    ),
                )
            ) from exc
        task = EnvironmentDesigner._compile_task_requirement_shard(
            authored,
            target=target,
            world=world,
            initial_config_schema=initial_config_schema,
        )
        EnvironmentDesigner._validate_task_requirement_shard(
            task,
            target=target,
            plan=compiled_plan.plan,
            world=world,
            evidence_graph=evidence_graph,
        )
    except (StructuredSemanticError, StructuredValidationError, ValidationError, ValueError) as exc:
        _raise_compiler_diagnostic(exc, phase="task_requirement_preflight")
    return CompiledTaskRequirement(
        canonical_source=canonical_source,
        plan=compiled_plan.plan,
        target_task_type=target_task_type,
        source=authored,
        task=task,
    )


def compile_shared_tool_semantics(
    source: SharedToolSemanticsSourceDraft,
    *,
    group: ToolCouplingGroupPlan,
    evidence_graph: EvidenceGraph,
) -> SharedToolSemanticsContract:
    """Validate one cross-batch policy and derive its closed contract."""

    return EnvironmentDesigner._compile_shared_tool_semantics_contract(
        source,
        group=group,
        evidence_graph=evidence_graph,
    )


def compile_tool_semantics_batch(
    source: ToolSemanticsBatchSourceDraft,
    *,
    expected_tool_ids: tuple[str, ...],
    skeleton: WorldSkeletonDraft,
    evidence_graph: EvidenceGraph,
    contracts: tuple[SharedToolSemanticsContract, ...],
    rule_contexts_by_tool: Mapping[str, RuleContextCatalog] | None = None,
) -> tuple[ToolSemanticsDraft, ...]:
    """Compile one physical batch against frozen local and shared constraints."""

    try:
        materialized = materialize_tool_semantics_bindings(
            source,
            skeleton=skeleton,
            catalogs_by_tool=rule_contexts_by_tool,
        )
        return _pure_compiler()._compile_and_validate_tool_semantics_batch(
            materialized,
            expected_tool_ids=expected_tool_ids,
            skeleton=skeleton,
            evidence_graph=evidence_graph,
            contracts=contracts,
        )
    except (StructuredSemanticError, StructuredValidationError, ValidationError, ValueError) as exc:
        _raise_compiler_diagnostic(exc, phase="tool_semantics_preflight")


def compile_world_rules(
    source: WorldRuleSemanticsSourceDraft,
    *,
    architecture: WorldArchitectureSourceDraft,
    tool_semantics: tuple[ToolSemanticsDraft, ...],
    evidence_graph: EvidenceGraph,
    evidence_graph_ref: ArtifactRef,
) -> CompiledWorldRules:
    """Join frozen Architecture/behavior with one rules source into a WorldModel."""

    try:
        canonical_source = _canonicalize_world_rule_source(source)
        initial_state_rules = EnvironmentDesigner._compile_initial_state_rules_source(
            canonical_source.initial_state_rules
        )
        closure = EnvironmentDesigner._compile_world_closure_source(
            WorldClosureSourceDraft(invariants=canonical_source.invariants)
        )
        boundary = EnvironmentDesigner._compile_architecture_boundary(architecture)
        state_inventory = EnvironmentDesigner._compile_architecture_state_inventory(architecture)
        state_schema_irs, tool_schema_irs = EnvironmentDesigner._compile_architecture_schema_irs(
            architecture
        )
        tool_inventory = EnvironmentDesigner._compile_architecture_tool_inventory(architecture)
        world_source = WorldSemanticSourceIRDraft(
            boundary=boundary,
            state_inventory=state_inventory,
            state_entity_schemas=state_schema_irs,
            initial_state_rules=initial_state_rules,
            tool_inventory=tool_inventory,
            tool_schemas=tool_schema_irs,
            tool_semantics=tool_semantics,
            closure=closure,
        )
        world = EnvironmentDesigner._compile_world_semantic_source(
            world_source,
            evidence_graph=evidence_graph,
            evidence_graph_ref=evidence_graph_ref,
        )
    except (StructuredSemanticError, StructuredValidationError, ValidationError, ValueError) as exc:
        _raise_compiler_diagnostic(exc, phase="world_rules_preflight")
    return CompiledWorldRules(
        canonical_source=canonical_source,
        source=world_source,
        world=world,
    )


def _canonicalize_world_rule_source(
    source: WorldRuleSemanticsSourceDraft,
) -> WorldRuleSemanticsSourceDraft:
    """Discard Agent-supplied names for framework-owned WorldRules IR objects."""

    def without_rule_ids(rules: tuple[RuleDraft, ...]) -> tuple[RuleDraft, ...]:
        return tuple(rule.model_copy(update={"rule_id": None}) for rule in rules)

    return source.model_copy(
        update={
            "initial_state_rules": source.initial_state_rules.model_copy(
                update={
                    "initial_state_constraints": without_rule_ids(
                        source.initial_state_rules.initial_state_constraints
                    )
                }
            ),
            "invariants": without_rule_ids(source.invariants),
        }
    )


def compile_training_semantics(
    source: TrainingSemanticSourceDraft,
    *,
    world_source: WorldSemanticSourceIRDraft,
    world: WorldModelDraft,
    evidence_graph: EvidenceGraph,
) -> CompiledTrainingSemantics:
    """Compile tasks/reward/verification while preserving the frozen WorldModel."""

    try:
        canonical_source = _canonicalize_training_semantics_source(source)
        plan = EnvironmentDesigner._compile_curriculum_plan_source(canonical_source.curriculum_plan)
        EnvironmentDesigner._validate_curriculum_plan(
            plan,
            world=world,
            evidence_graph=evidence_graph,
        )
        if len(canonical_source.task_requirements) != len(plan.task_plans):
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="design",
                    validation_phase="task_curriculum_source_shape",
                    frontier_ordinal=40,
                    issues=(
                        SafeValidationIssue(
                            "task_requirement_count_mismatch",
                            ("task_requirements",),
                            (
                                "Task requirements must contain exactly one entry "
                                "for each curriculum plan."
                            ),
                            violated_condition=(
                                "task_requirements length equals the frozen curriculum "
                                "task-plan length"
                            ),
                            expected_category="one task requirement per curriculum task plan",
                        ),
                    ),
                )
            )
        try:
            initial_config_schema = EnvironmentDesigner._compile_task_initial_config_schema(
                world.state.root_state_schema
            )
        except ValueError as exc:
            raise StructuredValidationError(
                ValidationDiagnostic(
                    owner_component="design",
                    validation_phase="task_initial_config_projection",
                    frontier_ordinal=40,
                    issues=(
                        SafeValidationIssue(
                            "task_initial_config_projection_invalid",
                            ("world", "state", "root_state_schema"),
                            (
                                "The frozen world state cannot be projected into "
                                "the closed task reset schema."
                            ),
                            retryable=False,
                            violated_condition=(
                                "the framework can derive a closed task initial-config schema "
                                "from the frozen world state"
                            ),
                            expected_category="a framework-projectable closed world state schema",
                        ),
                    ),
                )
            ) from exc
        authored_tasks = tuple(
            EnvironmentDesigner._compile_task_requirement_source(
                item,
                framework_task_type=target.task_type,
                path_prefix=("task_requirements", index),
            )
            for index, (target, item) in enumerate(
                zip(
                    plan.task_plans,
                    canonical_source.task_requirements,
                    strict=True,
                )
            )
        )
        tasks = tuple(
            EnvironmentDesigner._compile_task_requirement_shard(
                authored,
                target=target,
                world=world,
                initial_config_schema=initial_config_schema,
                path_prefix=("task_requirements", index),
            )
            for index, (target, authored) in enumerate(
                zip(plan.task_plans, authored_tasks, strict=True)
            )
        )
        for index, (target, task) in enumerate(zip(plan.task_plans, tasks, strict=True)):
            EnvironmentDesigner._validate_task_requirement_shard(
                task,
                target=target,
                plan=plan,
                world=world,
                evidence_graph=evidence_graph,
                path_prefix=("task_requirements", index),
            )
        curriculum = EnvironmentDesigner._compose_curriculum_contract(plan, tasks)
        training = EnvironmentDesigner._compile_training_contract(world, curriculum)
        design = EnvironmentDesigner._compose_design_draft(world, training)
        EnvironmentDesigner._validate_design_draft(design, evidence_graph)
        semantic_source = EnvironmentSemanticSourceDraft(
            world=world_source,
            curriculum_plan=plan,
            task_requirements=authored_tasks,
        )
    except (StructuredSemanticError, StructuredValidationError, ValidationError, ValueError) as exc:
        _raise_compiler_diagnostic(exc, phase="task_curriculum_preflight")
    return CompiledTrainingSemantics(
        canonical_source=canonical_source,
        source=semantic_source,
        design=design,
    )


def _without_rule_ids(rules: tuple[RuleDraft, ...]) -> tuple[RuleDraft, ...]:
    return tuple(rule.model_copy(update={"rule_id": None}) for rule in rules)


def _canonicalize_curriculum_plan_source(
    source: CurriculumPlanSourceDraft,
) -> CurriculumPlanSourceDraft:
    """Remove Agent-authored sampling Rule identities before plan persistence."""

    return source.model_copy(
        update={"sampling_constraints": _without_rule_ids(source.sampling_constraints)}
    )


def _canonicalize_task_requirement_source(
    source: TaskRequirementSourceDraft,
) -> TaskRequirementSourceDraft:
    """Remove Agent-authored task Rule identities before shard persistence."""

    return source.model_copy(
        update={
            "initial_state_constraints": _without_rule_ids(source.initial_state_constraints),
            "success_conditions": _without_rule_ids(source.success_conditions),
            "failure_conditions": _without_rule_ids(source.failure_conditions),
            "terminal_conditions": _without_rule_ids(source.terminal_conditions),
        }
    )


def _canonicalize_training_semantics_source(
    source: TrainingSemanticSourceDraft,
) -> TrainingSemanticSourceDraft:
    """Canonicalize the separately persisted plan and task-family sources."""

    return source.model_copy(
        update={
            "curriculum_plan": _canonicalize_curriculum_plan_source(source.curriculum_plan),
            "task_requirements": tuple(
                _canonicalize_task_requirement_source(task) for task in source.task_requirements
            ),
        }
    )


def _raise_compiler_diagnostic(
    exc: StructuredSemanticError | StructuredValidationError | ValidationError | ValueError,
    *,
    phase: str,
) -> NoReturn:
    """Convert legacy compiler failures to the only repairable safe boundary."""

    issues: tuple[SafeValidationIssue, ...]
    if (
        phase
        in {
            "curriculum_plan_preflight",
            "task_requirement_preflight",
            "task_curriculum_preflight",
        }
        and isinstance(exc, (ValidationError, ValueError))
        and not isinstance(exc, (StructuredSemanticError, StructuredValidationError))
    ):
        boundary = {
            "curriculum_plan_preflight": "CurriculumPlan",
            "task_requirement_preflight": "TaskRequirement",
            "task_curriculum_preflight": "TaskCurriculum",
        }[phase]
        issues = (
            SafeValidationIssue(
                f"{phase.removesuffix('_preflight')}_framework_protocol_invalid",
                ("compiler",),
                f"Framework-generated {boundary} protocol failed its closed contract.",
                retryable=False,
                violated_condition=(
                    "the framework compiles the closed protocol after source validation"
                ),
                expected_category=f"a framework-valid {boundary} protocol",
            ),
        )
    else:
        issues = EnvironmentDesigner._prefixed_validation_issues(exc, prefix=())
    raise StructuredValidationError(
        ValidationDiagnostic(
            owner_component="design",
            validation_phase=phase,
            frontier_ordinal=40,
            issues=issues,
        )
    ) from exc


def _pure_compiler() -> EnvironmentDesigner:
    """Return no-state access to legacy *deterministic* helper methods only.

    ``EnvironmentDesigner.__init__`` owns the retired Agent/retry orchestration
    and must never run for a Scheduler leaf. Its compiler helpers use no
    instance state; this intentionally uninitialized object keeps old tests'
    instance-level monkeypatch seams intact until those helpers are moved out
    of ``service.py`` completely.
    """

    return EnvironmentDesigner.__new__(EnvironmentDesigner)


__all__ = [
    "CompiledCurriculumPlan",
    "CompiledTaskRequirement",
    "CompiledTrainingSemantics",
    "CompiledWorldRules",
    "coverage_rule_catalog",
    "compile_curriculum_plan_semantics",
    "compile_shared_tool_semantics",
    "compile_task_requirement_semantics",
    "compile_tool_semantics_batch",
    "compile_training_semantics",
    "compile_world_rules",
]

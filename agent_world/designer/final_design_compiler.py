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

from agent_world.contracts import ArtifactRef, EvidenceGraph
from agent_world.control.validation import StructuredValidationError, ValidationDiagnostic

from .models import (
    EnvironmentDesignDraft,
    EnvironmentSemanticSourceDraft,
    RuleDraft,
    SharedToolSemanticsContract,
    SharedToolSemanticsSourceDraft,
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

    source: EnvironmentSemanticSourceDraft
    design: EnvironmentDesignDraft


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
        plan = EnvironmentDesigner._compile_curriculum_plan_source(source.curriculum_plan)
        EnvironmentDesigner._validate_curriculum_plan(
            plan,
            world=world,
            evidence_graph=evidence_graph,
        )
        initial_config_schema = EnvironmentDesigner._compile_task_initial_config_schema(
            world.state.root_state_schema
        )
        authored_tasks = tuple(
            EnvironmentDesigner._compile_task_requirement_source(item)
            for item in source.task_requirements
        )
        tasks = tuple(
            EnvironmentDesigner._compile_task_requirement_shard(
                authored,
                target=target,
                world=world,
                initial_config_schema=initial_config_schema,
            )
            for target, authored in zip(plan.task_plans, authored_tasks, strict=True)
        )
        for target, task in zip(plan.task_plans, tasks, strict=True):
            EnvironmentDesigner._validate_task_requirement_shard(
                task,
                target=target,
                plan=plan,
                world=world,
                evidence_graph=evidence_graph,
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
    return CompiledTrainingSemantics(source=semantic_source, design=design)


def _raise_compiler_diagnostic(
    exc: StructuredSemanticError | StructuredValidationError | ValidationError | ValueError,
    *,
    phase: str,
) -> NoReturn:
    """Convert legacy compiler failures to the only repairable safe boundary."""

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
    "CompiledTrainingSemantics",
    "CompiledWorldRules",
    "compile_shared_tool_semantics",
    "compile_tool_semantics_batch",
    "compile_training_semantics",
    "compile_world_rules",
]

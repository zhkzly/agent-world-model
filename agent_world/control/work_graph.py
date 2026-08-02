"""Framework-owned WorkDefinition catalog and dependency/invalidation graph."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import Field, model_validator

from agent_world.contracts import (
    ArtifactRef,
    ContentHash,
    EnvironmentDesign,
    Identifier,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.judge_budgeting import (
    JudgeOperationBudgetRequirements,
    integration_budget_requirements,
    release_without_interactive_budget_requirements,
)

from .code_revision import leaf_code_revision
from .work import (
    ArtifactSlotContract,
    AssurancePolicy,
    OperationBudget,
    ProposalPolicy,
    RepairPolicy,
    ValidationPolicy,
    WorkCoordinate,
    WorkDefinition,
)

if TYPE_CHECKING:
    from agent_world.designer.models import CurriculumPlanSourceDraft, ToolCouplingPlan
    from agent_world.judge.models import VerifierBatchPlan


class WorkGraphError(RuntimeError):
    """The framework WorkGraph is incomplete, cyclic, or identity-conflicting."""


_REQUIRED_PRODUCTION_STAGES = frozenset(
    {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
        ("design", "world_rules"),
        ("design", "curriculum_plan"),
        ("design", "task_requirement"),
        ("design", "task_curriculum"),
        ("design", "modeling_boundary"),
        ("build", "implementation_plan"),
        ("build", "candidate_build"),
        ("verifier", "verifier_intent"),
        ("integration", "runtime_integration"),
        ("judge", "release_assurance"),
        ("release", "observability_closure"),
        ("release", "package"),
        ("registry", "publication"),
    }
)
_BEHAVIOR_STAGES = frozenset({"shared_tool_semantics", "world_behavior", "tool_semantics_batch"})

# Every refreshable leaf is executed and repaired through this shared Scheduler
# boundary.  Its source must participate in each validation revision: otherwise
# a feedback/repair-route change could silently reuse a frozen leaf as though
# the current control-plane behavior were unchanged.
_SHARED_SCHEDULER_FEEDBACK_MODULES = (
    "agent_world.control.leaf_executor",
    "agent_world.control.work_repair",
    "agent_world.control.work_runtime",
    "agent_world.control.work_scheduler",
)

# SEMANTIC IDENTITY vs CONTROL-PLANE VERSION.
#
# ``implementation_revision_id`` flows into ``acceptance_digest``, so any module
# named by a leaf's implementation tuple invalidates every already-committed
# output of that leaf when its source changes.  That is correct for surfaces
# which author *meaning*: the rendered Prompt, the output schema, an Agent's
# mounted Runtime Skill, and the model identity.  Direct LLM leaves deliberately
# have no mounted Skill: their Prompt is their complete semantic surface.  It is
# wrong for the physical
# invocation control plane -- transport adapters, worker lifecycle, liveness
# supervision, retry/fallback routing, ownership and recovery.  Those decide
# only *how* one physical attempt is admitted, observed and settled; a fix
# there cannot make an accepted semantic Artifact retroactively invalid.
#
# Binding them anyway produced a real, mechanical failure mode: every
# invocation-layer repair marked committed upstream nodes stale and forced a
# full regeneration, so no run could converge while the control plane was still
# being fixed.  Invocation modules are therefore deliberately excluded from
# every ``*_IMPLEMENTATION_MODULES`` tuple below.  They remain observable
# through the durable Invocation Control Store and telemetry, which is where a
# physical-attempt change belongs.
#
# The rule for adding a module here: include it only if changing it can change
# what a correct model would be asked to produce, or what counts as a correct
# answer.  Never include it merely because the leaf calls into it.
# ``leaf_code_revision`` enforces this mechanically.

_RESEARCH_PLAN_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
    "agent_world.designer.research_leaf",
)
_RESEARCH_PLAN_VALIDATOR_MODULES = (
    "agent_world.designer.models",
    "agent_world.designer.research_leaf",
    "agent_world.designer.validators",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_EVIDENCE_SYNTHESIS_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.evidence_synthesis_leaf",
    "agent_world.designer.evidence_synthesis_compiler",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_EVIDENCE_SYNTHESIS_VALIDATOR_MODULES = (
    "agent_world.designer.evidence_synthesis_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validators",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_WORLD_ARCHITECTURE_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
    "agent_world.designer.world_architecture_leaf",
)
_WORLD_ARCHITECTURE_VALIDATOR_MODULES = (
    "agent_world.designer.architecture_compiler",
    "agent_world.designer.models",
    "agent_world.designer.world_architecture_leaf",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_SHARED_TOOL_SEMANTICS_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_SHARED_TOOL_SEMANTICS_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_TOOL_SEMANTICS_BATCH_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.compact_rule_protocol",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
    "agent_world.designer.rule_context",
)
_TOOL_SEMANTICS_BATCH_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.rule_context",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_WORLD_RULES_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_WORLD_RULES_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_LEGACY_CURRICULUM_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_LEGACY_CURRICULUM_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_CURRICULUM_PLAN_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_CURRICULUM_PLAN_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_TASK_REQUIREMENT_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.designer.final_design_leaves",
    "agent_world.designer.models",
    "agent_world.designer.one_shot",
)
_TASK_REQUIREMENT_VALIDATOR_MODULES = (
    "agent_world.designer.final_design_compiler",
    "agent_world.designer.models",
    "agent_world.designer.validation",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_VERIFIER_INTENT_BATCH_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.judge.compiler",
    "agent_world.judge.models",
)
_VERIFIER_INTENT_BATCH_VALIDATOR_MODULES = (
    "agent_world.judge.compiler",
    "agent_world.judge.leaf",
    "agent_world.judge.models",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_VERIFIER_PLAN_IMPLEMENTATION_MODULES = (
    "agent_world.judge.compiler",
    "agent_world.judge.leaf",
    "agent_world.judge.models",
)
_VERIFIER_PLAN_VALIDATOR_MODULES = (
    "agent_world.judge.compiler",
    "agent_world.judge.leaf",
    "agent_world.judge.models",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_IMPLEMENTATION_PLAN_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.builder.leaf",
    "agent_world.builder.models",
    "agent_world.builder.service",
    "agent_world.designer.one_shot",
)
_IMPLEMENTATION_PLAN_VALIDATOR_MODULES = (
    "agent_world.builder.leaf",
    "agent_world.builder.models",
    "agent_world.control.leaf_executor",
    "agent_world.designer.one_shot",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_IMPLEMENTATION_PLAN_SKILL = (
    Path(__file__).resolve().parents[1]
    / "agent_assets"
    / "skills"
    / "engineer-build-planning"
)
_CANDIDATE_BUILD_IMPLEMENTATION_MODULES = (
    "agent_world.agent_profiles",
    "agent_world.builder.leaf",
    "agent_world.builder.models",
    "agent_world.builder.service",
)
_CANDIDATE_BUILD_VALIDATOR_MODULES = (
    "agent_world.builder.leaf",
    "agent_world.builder.models",
    "agent_world.builder.precommit",
    "agent_world.builder.service",
    "agent_world.builder.workspace",
    "agent_world.control.leaf_executor",
    "agent_world.control.validation",
    "agent_world.judge.supervisor",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_CANDIDATE_BUILD_SKILL = (
    Path(__file__).resolve().parents[1]
    / "agent_assets"
    / "skills"
    / "engineer-environment-codegen"
)
# CandidateBuild is a Code Agent's bounded development cycle: one initial
# build/test turn and one same-workspace pre-commit correction when framework
# validation gives it actionable feedback.  This is distinct from Scheduler
# RepairAction budget and must remain shared with diagnostic current-runtime
# refreshes.
CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS = 2
_RUNTIME_INTEGRATION_IMPLEMENTATION_MODULES = (
    "agent_world.control.direct_runner",
    "agent_world.control.leaf_executor",
    "agent_world.judge.assurance",
    "agent_world.judge_budgeting",
    "agent_world.judge.leaf",
    "agent_world.judge.service",
    "agent_world.judge.supervisor",
    "agent_world.judge.visibility",
)
_RUNTIME_INTEGRATION_VALIDATOR_MODULES = (
    "agent_world.control.leaf_executor",
    "agent_world.control.validation",
    "agent_world.judge.assurance",
    "agent_world.judge_budgeting",
    "agent_world.judge.leaf",
    "agent_world.judge.service",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)
_RELEASE_ASSURANCE_IMPLEMENTATION_MODULES = (
    "agent_world.control.direct_runner",
    "agent_world.control.leaf_executor",
    "agent_world.judge.assurance",
    "agent_world.judge_budgeting",
    "agent_world.judge.compiler",
    "agent_world.judge.leaf",
    "agent_world.judge.reachability",
    "agent_world.judge.service",
    "agent_world.judge.supervisor",
    "agent_world.judge.visibility",
)
_RELEASE_ASSURANCE_VALIDATOR_MODULES = (
    "agent_world.control.leaf_executor",
    "agent_world.control.validation",
    "agent_world.judge.compiler",
    "agent_world.judge_budgeting",
    "agent_world.judge.leaf",
    "agent_world.judge.service",
    *_SHARED_SCHEDULER_FEEDBACK_MODULES,
)


def research_plan_implementation_revision() -> Identifier:
    """Hash the complete direct ResearchPlan Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_RESEARCH_PLAN_IMPLEMENTATION_MODULES,
        label="research-plan",
    )


def research_plan_validator_revision() -> Identifier:
    """Hash ResearchPlan semantic admission and its Scheduler feedback route."""

    return leaf_code_revision(
        *_RESEARCH_PLAN_VALIDATOR_MODULES,
        label="validator-research-plan",
    )


def evidence_synthesis_implementation_revision() -> Identifier:
    """Hash the exact direct Prompt/profile/schema surface for EvidenceSynthesis."""

    return leaf_code_revision(
        *_EVIDENCE_SYNTHESIS_IMPLEMENTATION_MODULES,
        label="research-evidence-synthesis",
    )


def evidence_synthesis_validator_revision() -> Identifier:
    """Hash the deterministic source-to-canonical EvidenceGraph boundary."""

    return leaf_code_revision(
        *_EVIDENCE_SYNTHESIS_VALIDATOR_MODULES,
        label="validator-evidence-synthesis",
    )


def world_architecture_implementation_revision() -> Identifier:
    """Hash the complete direct Architecture Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_WORLD_ARCHITECTURE_IMPLEMENTATION_MODULES,
        label="design-world-architecture",
    )


def world_architecture_validator_revision() -> Identifier:
    """Hash Architecture compilation and its Scheduler feedback route."""

    return leaf_code_revision(
        *_WORLD_ARCHITECTURE_VALIDATOR_MODULES,
        label="validator-world-architecture",
    )


def shared_tool_semantics_implementation_revision() -> Identifier:
    """Hash the direct SharedToolSemantics Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_SHARED_TOOL_SEMANTICS_IMPLEMENTATION_MODULES,
        label="design-shared-tool-semantics",
    )


def shared_tool_semantics_validator_revision() -> Identifier:
    """Hash shared-contract compilation and its Scheduler feedback route."""

    return leaf_code_revision(
        *_SHARED_TOOL_SEMANTICS_VALIDATOR_MODULES,
        label="validator-shared-tool-semantics",
    )


def tool_semantics_batch_implementation_revision() -> Identifier:
    """Hash the complete direct Prompt/profile/schema surface for ToolSemantics."""

    return leaf_code_revision(
        *_TOOL_SEMANTICS_BATCH_IMPLEMENTATION_MODULES,
        label="design-tool-semantics-batch",
    )


def tool_semantics_batch_validator_revision() -> Identifier:
    """Hash the deterministic ToolSemantics source compiler boundary."""

    return leaf_code_revision(
        *_TOOL_SEMANTICS_BATCH_VALIDATOR_MODULES,
        label="validator-tool-semantics-batch",
    )


def world_rules_implementation_revision() -> Identifier:
    """Hash the direct WorldRules Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_WORLD_RULES_IMPLEMENTATION_MODULES,
        label="design-world-rules",
    )


def world_rules_validator_revision() -> Identifier:
    """Hash WorldRules compilation and its Scheduler feedback route."""

    return leaf_code_revision(
        *_WORLD_RULES_VALIDATOR_MODULES,
        label="validator-world-rules",
    )


def legacy_curriculum_implementation_revision() -> Identifier:
    """Hash the retired aggregate Curriculum prompt if a diagnostic graph uses it."""

    return leaf_code_revision(
        *_LEGACY_CURRICULUM_IMPLEMENTATION_MODULES,
        label="design-task-curriculum-legacy",
    )


def legacy_curriculum_validator_revision() -> Identifier:
    """Hash retired aggregate Curriculum admission and feedback handling."""

    return leaf_code_revision(
        *_LEGACY_CURRICULUM_VALIDATOR_MODULES,
        label="validator-task-curriculum-legacy",
    )


def curriculum_plan_implementation_revision() -> Identifier:
    """Hash the direct CurriculumPlan Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_CURRICULUM_PLAN_IMPLEMENTATION_MODULES,
        label="design-curriculum-plan",
    )


def curriculum_plan_validator_revision() -> Identifier:
    """Hash CurriculumPlan compilation and its Scheduler feedback route."""

    return leaf_code_revision(
        *_CURRICULUM_PLAN_VALIDATOR_MODULES,
        label="validator-curriculum-plan",
    )


def task_requirement_implementation_revision() -> Identifier:
    """Hash the direct TaskRequirement Prompt, profile, and schema surface."""

    return leaf_code_revision(
        *_TASK_REQUIREMENT_IMPLEMENTATION_MODULES,
        label="design-task-requirement",
    )


def task_requirement_validator_revision() -> Identifier:
    """Hash TaskRequirement compilation and its Scheduler feedback route."""

    return leaf_code_revision(
        *_TASK_REQUIREMENT_VALIDATOR_MODULES,
        label="validator-task-requirement",
    )


def verifier_intent_batch_implementation_revision() -> Identifier:
    """Hash the Challenger's direct Prompt/profile/schema authoring surface."""

    return leaf_code_revision(
        *_VERIFIER_INTENT_BATCH_IMPLEMENTATION_MODULES,
        label="verifier-intent-batch",
    )


def verifier_intent_batch_validator_revision() -> Identifier:
    """Hash the deterministic verifier-intent validation and binding boundary."""

    return leaf_code_revision(
        *_VERIFIER_INTENT_BATCH_VALIDATOR_MODULES,
        label="validator-verifier-intent-batch",
    )


def verifier_plan_implementation_revision() -> Identifier:
    """Hash the code-owned VerifierPlan context and partition compiler.

    ``VerifierBatchPlan.context_hash`` binds the exact Challenger context that
    follows.  A compiler change is therefore also a change to this deterministic
    parent, not merely to the later Agent leaf.
    """

    return leaf_code_revision(
        *_VERIFIER_PLAN_IMPLEMENTATION_MODULES,
        label="verifier-plan",
    )


def verifier_plan_validator_revision() -> Identifier:
    """Hash deterministic VerifierPlan admission and its feedback boundary."""

    return leaf_code_revision(
        *_VERIFIER_PLAN_VALIDATOR_MODULES,
        label="validator-verifier-plan",
    )


def implementation_plan_implementation_revision() -> Identifier:
    """Hash the complete Agent authoring surface for BuildImplementationPlan."""

    return leaf_code_revision(
        *_IMPLEMENTATION_PLAN_IMPLEMENTATION_MODULES,
        assets={"runtime-skill:engineer-build-planning": _IMPLEMENTATION_PLAN_SKILL},
        label="build-implementation-plan",
    )


def implementation_plan_validator_revision() -> Identifier:
    """Hash the deterministic planning-output validation and Scheduler route."""

    return leaf_code_revision(
        *_IMPLEMENTATION_PLAN_VALIDATOR_MODULES,
        label="validator-build-implementation-plan",
    )


def candidate_build_implementation_revision() -> Identifier:
    """Hash the complete Agent authoring surface for CandidateBuild."""

    return leaf_code_revision(
        *_CANDIDATE_BUILD_IMPLEMENTATION_MODULES,
        assets={"runtime-skill:engineer-environment-codegen": _CANDIDATE_BUILD_SKILL},
        label="build-candidate",
    )


def candidate_build_validator_revision() -> Identifier:
    """Hash Candidate workspace validation plus its safe feedback route."""

    return leaf_code_revision(
        *_CANDIDATE_BUILD_VALIDATOR_MODULES,
        label="validator-build-candidate",
    )


def runtime_integration_implementation_revision() -> Identifier:
    """Hash the complete isolated Integration execution path."""

    return leaf_code_revision(
        *_RUNTIME_INTEGRATION_IMPLEMENTATION_MODULES,
        label="integration-runtime",
    )


def runtime_integration_validator_revision() -> Identifier:
    """Hash Integration report-to-safe-feedback validation and routing."""

    return leaf_code_revision(
        *_RUNTIME_INTEGRATION_VALIDATOR_MODULES,
        label="validator-runtime-integration",
    )


def release_assurance_implementation_revision() -> Identifier:
    """Hash the complete isolated ReleaseAssurance execution path."""

    return leaf_code_revision(
        *_RELEASE_ASSURANCE_IMPLEMENTATION_MODULES,
        label="judge-release-assurance",
    )


def release_assurance_validator_revision() -> Identifier:
    """Hash ReleaseAssurance report-to-safe-feedback validation and routing."""

    return leaf_code_revision(
        *_RELEASE_ASSURANCE_VALIDATOR_MODULES,
        label="validator-release-assurance",
    )


def current_runtime_revisions_for_definition(
    definition: WorkDefinition,
) -> tuple[Identifier, Identifier] | None:
    """Return current executable revisions for one known refreshable leaf.

    A frozen diagnostic graph is intentionally historical.  ``test-node`` may
    therefore refresh only an explicitly registered current implementation
    identity; it cannot invent a new topology, input closure, prompt payload,
    Skill, or acceptance rule.  New leaf kinds must opt in here with their own
    complete authoring/validation revision sources.
    """

    coordinate = definition.coordinate
    if (
        coordinate.component == "research"
        and coordinate.stage == "research_plan"
        and coordinate.artifact_slot == "research_plan"
        and definition.proposal_policy.output_contract_id == "contract:research-plan"
    ):
        return (
            research_plan_implementation_revision(),
            research_plan_validator_revision(),
        )
    if (
        coordinate.component == "research"
        and coordinate.stage == "evidence_synthesis"
        and coordinate.artifact_slot == "evidence_synthesis"
        and definition.proposal_policy.output_contract_id == "contract:evidence-synthesis"
    ):
        return (
            evidence_synthesis_implementation_revision(),
            evidence_synthesis_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "world_architecture"
        and coordinate.artifact_slot == "world_architecture"
        and definition.proposal_policy.output_contract_id == "contract:world-architecture-source.v3"
    ):
        return (
            world_architecture_implementation_revision(),
            world_architecture_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "shared_tool_semantics"
        and coordinate.artifact_slot == "shared_tool_semantics"
        and definition.proposal_policy.output_contract_id
        == "contract:shared-tool-semantics-source.v3"
    ):
        return (
            shared_tool_semantics_implementation_revision(),
            shared_tool_semantics_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "world_behavior"
        and coordinate.artifact_slot == "tool_semantics_batch"
        and definition.proposal_policy.output_contract_id
        == "contract:tool-semantics-batch-source.v7"
    ):
        return (
            tool_semantics_batch_implementation_revision(),
            tool_semantics_batch_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "world_rules"
        and coordinate.artifact_slot == "world_rules"
        and definition.proposal_policy.output_contract_id == "contract:world-rules-source.v3"
    ):
        return (
            world_rules_implementation_revision(),
            world_rules_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "task_curriculum"
        and coordinate.artifact_slot == "task_curriculum"
        and definition.proposal_policy.output_contract_id == "contract:task-curriculum-source.v3"
    ):
        return (
            legacy_curriculum_implementation_revision(),
            legacy_curriculum_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "curriculum_plan"
        and coordinate.artifact_slot == "curriculum_plan"
        and definition.proposal_policy.output_contract_id == "contract:curriculum-plan-source.v1"
    ):
        return (
            curriculum_plan_implementation_revision(),
            curriculum_plan_validator_revision(),
        )
    if (
        coordinate.component == "design"
        and coordinate.stage == "task_requirement"
        and coordinate.artifact_slot == "task_requirement_source"
        and definition.proposal_policy.output_contract_id == "contract:task-requirement-source.v1"
    ):
        return (
            task_requirement_implementation_revision(),
            task_requirement_validator_revision(),
        )
    if (
        coordinate.component == "verifier"
        and coordinate.stage == "verifier_plan"
        and coordinate.artifact_slot == "verifier_batch_plan"
        and definition.proposal_policy.executor == "code"
        and definition.proposal_policy.operation == "verifier.verifier_plan"
        and definition.validation_policy.validator_id == "validator:verifier_plan"
    ):
        return (
            verifier_plan_implementation_revision(),
            verifier_plan_validator_revision(),
        )
    if (
        coordinate.component == "verifier"
        and coordinate.stage == "verifier_intent_batch"
        and coordinate.artifact_slot == "verifier_intent_checkpoint"
        and definition.proposal_policy.output_contract_id == "contract:verifier-intent-batch.v3"
    ):
        return (
            verifier_intent_batch_implementation_revision(),
            verifier_intent_batch_validator_revision(),
        )
    if (
        coordinate.component == "build"
        and coordinate.stage == "implementation_plan"
        and coordinate.artifact_slot == "implementation_plan"
        and definition.proposal_policy.output_contract_id == "contract:implementation-plan.v1"
    ):
        return (
            implementation_plan_implementation_revision(),
            implementation_plan_validator_revision(),
        )
    if (
        coordinate.component == "build"
        and coordinate.stage == "candidate_build"
        and coordinate.artifact_slot == "environment_candidate"
        and definition.proposal_policy.output_contract_id == "contract:environment-candidate.v3"
    ):
        return (
            candidate_build_implementation_revision(),
            candidate_build_validator_revision(),
        )
    if (
        coordinate.component == "integration"
        and coordinate.stage == "runtime_integration"
        and coordinate.artifact_slot == "integration_report"
        and definition.proposal_policy.executor == "code"
        and definition.proposal_policy.operation == "integration.runtime_integration.execute"
        and definition.validation_policy.validator_id == "validator:runtime_integration"
    ):
        return (
            runtime_integration_implementation_revision(),
            runtime_integration_validator_revision(),
        )
    if (
        coordinate.component == "judge"
        and coordinate.stage == "release_assurance"
        and coordinate.artifact_slot == "judge_report"
        and definition.proposal_policy.executor == "code"
        and definition.proposal_policy.operation == "judge.release_assurance.execute"
        and definition.validation_policy.validator_id == "validator:release_assurance"
    ):
        return (
            release_assurance_implementation_revision(),
            release_assurance_validator_revision(),
        )
    return None


def _has_complete_production_topology(
    coordinates: Iterable[WorkCoordinate],
    terminals: Iterable[WorkCoordinate],
) -> bool:
    """Return whether the only releasable shape has every causal product stage.

    A milestone name is not evidence that its work happened.  Release eligibility
    therefore derives from the frozen coordinates themselves, including actual
    behavior work, and from a sole Registry publication terminal.
    """

    items = tuple(coordinates)
    stage_pairs = {(item.component, item.stage) for item in items}
    terminal_pairs = {(item.component, item.stage) for item in terminals}
    return (
        _REQUIRED_PRODUCTION_STAGES <= stage_pairs
        and any(item.component == "design" and item.stage in _BEHAVIOR_STAGES for item in items)
        and terminal_pairs == {("registry", "publication")}
    )


def _stable_work_identity_digest(coordinate: WorkCoordinate) -> str:
    """Derive logical Work identity only from its stable scheduling coordinate."""

    return coordinate.coordinate_key.removeprefix("sha256:")[:24]


class WorkGraphNodeBinding(V2Contract):
    coordinate: WorkCoordinate
    work_id: Identifier
    definition_digest: ContentHash


class JoinPolicy(V2Contract):
    """Deterministic aggregate readiness for one bounded physical group."""

    # Threshold joins are deliberately not exposed until the runtime can bind
    # the exact selected child-commit set.  Advertising ``at_least`` while the
    # aggregate WorkDefinition still depends on every member made the contract
    # impossible to execute.
    mode: Literal["all"] = "all"
    retain_successful_siblings: Literal[True] = True
    cancel_running_on_failure: Literal[False] = False


class WorkGroupDefinition(V2Contract):
    """Frozen member set and aggregate coordinate for dynamic physical work."""

    group_id: Identifier
    scope_id: Identifier
    member_coordinates: Annotated[tuple[WorkCoordinate, ...], Field(min_length=1)]
    aggregate_coordinate: WorkCoordinate
    join_policy: JoinPolicy = Field(default_factory=JoinPolicy)

    @model_validator(mode="after")
    def validate_group(self) -> WorkGroupDefinition:
        keys = tuple(item.coordinate_key for item in self.member_coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("WorkGroup members must be unique")
        if self.aggregate_coordinate.coordinate_key in keys:
            raise ValueError("WorkGroup aggregate cannot also be a physical member")
        if any(item.scope_id != self.scope_id for item in self.member_coordinates) or (
            self.aggregate_coordinate.scope_id != self.scope_id
        ):
            raise ValueError("WorkGroup cannot mix scopes")
        if any(item.group_id != self.group_id for item in self.member_coordinates):
            raise ValueError("WorkGroup member coordinates must bind the group id")
        if any(item.shard_id is None for item in self.member_coordinates):
            raise ValueError("WorkGroup members must be physical shards")
        if self.aggregate_coordinate.shard_id is not None:
            raise ValueError("WorkGroup aggregate cannot be a shard")
        return self


class WorkGraphGroupBinding(V2Contract):
    group_id: Identifier
    group_digest: ContentHash
    aggregate_coordinate: WorkCoordinate
    member_coordinates: tuple[WorkCoordinate, ...]


class WorkGraphMilestone(V2Contract):
    """Named readiness milestone; publication and release-candidate readiness differ."""

    milestone_id: Identifier
    kind: Literal["progress", "release_candidate", "released"] = "progress"
    required_coordinates: Annotated[tuple[WorkCoordinate, ...], Field(min_length=1)]
    establishes: Identifier

    @model_validator(mode="after")
    def validate_milestone(self) -> WorkGraphMilestone:
        keys = tuple(item.coordinate_key for item in self.required_coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("WorkGraph milestone coordinates must be unique")
        return self


class WorkGraphMilestoneBinding(V2Contract):
    milestone_id: Identifier
    milestone_digest: ContentHash
    kind: Literal["progress", "release_candidate", "released"]
    required_coordinates: tuple[WorkCoordinate, ...]
    establishes: Identifier


class WorkGraphManifest(V2Contract):
    """Persistent topology identity; readiness and release bind this exact graph."""

    graph_id: Identifier
    scope_id: Identifier
    topology_id: Identifier
    mode: Literal["diagnostic", "production"]
    node_bindings: tuple[WorkGraphNodeBinding, ...]
    group_bindings: tuple[WorkGraphGroupBinding, ...] = ()
    milestone_bindings: tuple[WorkGraphMilestoneBinding, ...] = ()
    required_terminal_coordinates: tuple[WorkCoordinate, ...]
    external_root_refs: tuple[ArtifactRef, ...] = ()
    diagnostic_only: bool
    releasable: bool

    @model_validator(mode="after")
    def validate_manifest(self) -> WorkGraphManifest:
        if not self.node_bindings or not self.required_terminal_coordinates:
            raise ValueError("WorkGraphManifest requires nodes and terminals")
        coordinate_keys = tuple(item.coordinate.coordinate_key for item in self.node_bindings)
        if len(set(coordinate_keys)) != len(coordinate_keys):
            raise ValueError("WorkGraphManifest node coordinates must be unique")
        if len({item.work_id for item in self.node_bindings}) != len(self.node_bindings):
            raise ValueError("WorkGraphManifest work ids must be unique")
        if len({item.group_id for item in self.group_bindings}) != len(self.group_bindings):
            raise ValueError("WorkGraphManifest group ids must be unique")
        for group in self.group_bindings:
            group_keys = {
                group.aggregate_coordinate.coordinate_key,
                *(item.coordinate_key for item in group.member_coordinates),
            }
            if not group_keys <= set(coordinate_keys):
                raise ValueError("WorkGraphManifest group references unregistered nodes")
        if len({item.milestone_id for item in self.milestone_bindings}) != len(
            self.milestone_bindings
        ):
            raise ValueError("WorkGraphManifest milestone ids must be unique")
        for kind in ("release_candidate", "released"):
            if sum(item.kind == kind for item in self.milestone_bindings) > 1:
                raise ValueError(f"WorkGraphManifest has duplicate {kind} milestones")
        if any(
            coordinate.coordinate_key not in set(coordinate_keys)
            for milestone in self.milestone_bindings
            for coordinate in milestone.required_coordinates
        ):
            raise ValueError("WorkGraphManifest milestone references unregistered nodes")
        terminal_keys = tuple(item.coordinate_key for item in self.required_terminal_coordinates)
        if len(set(terminal_keys)) != len(terminal_keys) or not set(terminal_keys) <= set(
            coordinate_keys
        ):
            raise ValueError("WorkGraphManifest terminals must be unique registered nodes")
        if len(set(self.external_root_refs)) != len(self.external_root_refs):
            raise ValueError("WorkGraphManifest external roots must be unique")
        release_kinds = {item.kind for item in self.milestone_bindings}
        has_complete_release_milestones = {
            "release_candidate",
            "released",
        } <= release_kinds
        publication_terminal = any(
            item.component == "registry" and item.stage == "publication"
            for item in self.required_terminal_coordinates
        )
        if self.mode == "diagnostic":
            if not self.diagnostic_only or self.releasable:
                raise ValueError("diagnostic WorkGraphManifest cannot be releasable")
        elif self.diagnostic_only:
            raise ValueError("production WorkGraphManifest cannot be diagnostic")
        complete_topology = _has_complete_production_topology(
            (item.coordinate for item in self.node_bindings),
            self.required_terminal_coordinates,
        )
        if self.releasable != (
            self.mode == "production"
            and has_complete_release_milestones
            and publication_terminal
            and complete_topology
        ):
            raise ValueError(
                "WorkGraphManifest releasable flag must bind complete publication topology"
            )
        if any(item.coordinate.scope_id != self.scope_id for item in self.node_bindings):
            raise ValueError("WorkGraphManifest cannot mix scopes")
        return self

    @property
    def graph_digest(self) -> ContentHash:
        return self.content_digest()


class WorkGraphEpoch(V2Contract):
    """One immutable topology freeze for a single GenerationContext.

    Dynamic behavior, task-family, and verifier groups are materialized only
    after grounded Architecture, a committed CurriculumPlan, and the compiled
    curriculum reveal three different bounded physical member sets.
    ``bootstrap`` therefore freezes Research through Architecture, ``world``
    freezes behavior, WorldRules and the small CurriculumPlan, ``design``
    freezes the plan-derived TaskRequirement children through deterministic
    VerifierPlan, and only ``final`` retains all prior closures before it
    appends Build through Registry.  These are graph-freezing boundaries within
    one Job and one budget ledger, never separate pipelines or authorities.
    """

    epoch_id: Identifier
    scope_id: Identifier
    epoch_kind: Literal["bootstrap", "world", "design", "final"]
    context_ref: ArtifactRef
    manifest_ref: ArtifactRef
    predecessor_epoch_ref: ArtifactRef | None = None
    retained_commit_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_epoch(self) -> WorkGraphEpoch:
        if self.context_ref.artifact_type != "control.generation_context":
            raise ValueError("WorkGraphEpoch must bind a GenerationContext Artifact")
        if self.manifest_ref.artifact_type != "control.work_graph_manifest":
            raise ValueError("WorkGraphEpoch must bind a WorkGraphManifest Artifact")
        if any(ref.artifact_type != "control.work_commit" for ref in self.retained_commit_refs):
            raise ValueError("WorkGraphEpoch retained refs must be WorkCommits")
        if len(set(self.retained_commit_refs)) != len(self.retained_commit_refs):
            raise ValueError("WorkGraphEpoch retained commits must be unique")
        if self.epoch_kind == "bootstrap":
            if self.predecessor_epoch_ref is not None or self.retained_commit_refs:
                raise ValueError("bootstrap WorkGraphEpoch cannot retain a predecessor closure")
        elif self.predecessor_epoch_ref is None or not self.retained_commit_refs:
            raise ValueError(
                "non-bootstrap WorkGraphEpoch requires predecessor and retained commits"
            )
        elif self.predecessor_epoch_ref.artifact_type != "control.work_graph_epoch":
            raise ValueError("non-bootstrap WorkGraphEpoch predecessor has the wrong artifact type")
        return self


class ResolvedWorkInputs(V2Contract):
    """Framework-derived immutable inputs for one exact graph coordinate."""

    coordinate: WorkCoordinate
    graph_digest: ContentHash
    external_input_refs: tuple[ArtifactRef, ...] = ()
    parent_commit_refs: tuple[ArtifactRef, ...] = ()
    parent_output_refs: tuple[ArtifactRef, ...] = ()
    input_fingerprint: ContentHash

    @model_validator(mode="after")
    def validate_inputs(self) -> ResolvedWorkInputs:
        for refs in (
            self.external_input_refs,
            self.parent_commit_refs,
            self.parent_output_refs,
        ):
            if len(set(refs)) != len(refs):
                raise ValueError("resolved work input refs must be unique")
        if any(ref.artifact_type != "control.work_commit" for ref in self.parent_commit_refs):
            raise ValueError("resolved parent refs must be WorkCommit Artifacts")
        expected = sha256_digest(
            canonical_json_bytes(
                {
                    "graph_digest": self.graph_digest,
                    "coordinate": self.coordinate.model_dump(mode="json"),
                    "external_input_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.external_input_refs
                    ),
                    "parent_commit_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.parent_commit_refs
                    ),
                    "parent_output_refs": tuple(
                        ref.model_dump(mode="json") for ref in self.parent_output_refs
                    ),
                }
            )
        )
        if self.input_fingerprint != expected:
            raise ValueError("resolved work input fingerprint mismatch")
        return self

    @property
    def all_input_refs(self) -> tuple[ArtifactRef, ...]:
        return tuple(dict.fromkeys((*self.external_input_refs, *self.parent_output_refs)))


@dataclass(frozen=True, slots=True)
class GenerationWorkGraph:
    """Immutable, digest-bound topology authority for one generation scope.

    A diagnostic graph can exercise an isolated slice but can never be projected
    as release-ready.  A production graph freezes its required terminal
    coordinates so deleting a node cannot silently weaken readiness.
    """

    _definitions: tuple[WorkDefinition, ...]
    _groups: tuple[WorkGroupDefinition, ...]
    _milestones: tuple[WorkGraphMilestone, ...]
    mode: Literal["diagnostic", "production"]
    required_terminal_coordinates: tuple[WorkCoordinate, ...]

    @classmethod
    def compile(
        cls,
        definitions: Iterable[WorkDefinition],
        *,
        mode: Literal["diagnostic", "production"],
        strict_input_contracts: bool = False,
        required_terminal_coordinates: Iterable[WorkCoordinate] | None = None,
        groups: Iterable[WorkGroupDefinition] = (),
        milestones: Iterable[WorkGraphMilestone] = (),
    ) -> GenerationWorkGraph:
        items = tuple(
            WorkDefinition.model_validate(item.model_dump(mode="python")) for item in definitions
        )
        if not items:
            raise WorkGraphError("WorkGraph cannot be empty")
        by_key = {item.coordinate.coordinate_key: item for item in items}
        if len(by_key) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate coordinates")
        if len({item.work_id for item in items}) != len(items):
            raise WorkGraphError("WorkGraph contains duplicate work ids")
        scopes = {item.coordinate.scope_id for item in items}
        if len(scopes) > 1:
            raise WorkGraphError("one WorkGraph cannot mix generation scopes")
        group_items = tuple(
            WorkGroupDefinition.model_validate(item.model_dump(mode="python")) for item in groups
        )
        if len({item.group_id for item in group_items}) != len(group_items):
            raise WorkGraphError("WorkGraph contains duplicate group ids")
        registered_keys = set(by_key)
        for group in group_items:
            if group.scope_id not in scopes:
                raise WorkGraphError("WorkGroup scope differs from its WorkGraph")
            group_keys = {
                group.aggregate_coordinate.coordinate_key,
                *(item.coordinate_key for item in group.member_coordinates),
            }
            if not group_keys <= registered_keys:
                raise WorkGraphError("WorkGroup references unregistered coordinates")
            aggregate = by_key[group.aggregate_coordinate.coordinate_key]
            member_keys = {item.coordinate_key for item in group.member_coordinates}
            dependency_keys = {item.coordinate_key for item in aggregate.dependency_coordinates}
            if member_keys != dependency_keys:
                raise WorkGraphError(
                    "WorkGroup aggregate dependencies must equal its frozen members"
                )
        milestone_items = tuple(
            WorkGraphMilestone.model_validate(item.model_dump(mode="python")) for item in milestones
        )
        if len({item.milestone_id for item in milestone_items}) != len(milestone_items):
            raise WorkGraphError("WorkGraph contains duplicate milestone ids")
        for kind in ("release_candidate", "released"):
            if sum(item.kind == kind for item in milestone_items) > 1:
                raise WorkGraphError(f"WorkGraph contains duplicate {kind} milestones")
        if any(
            coordinate.coordinate_key not in registered_keys
            for milestone in milestone_items
            for coordinate in milestone.required_coordinates
        ):
            raise WorkGraphError("WorkGraph milestone references unregistered coordinates")
        for item in items:
            missing = tuple(
                dependency
                for dependency in item.dependency_coordinates
                if dependency.coordinate_key not in by_key
            )
            if missing:
                raise WorkGraphError(
                    f"WorkGraph dependency is not registered: {missing[0].coordinate_key}"
                )
            missing_repair_targets = tuple(
                target
                for target in item.repair_target_coordinates
                if target.coordinate_key not in by_key
            )
            if missing_repair_targets:
                raise WorkGraphError(
                    "WorkGraph repair target is not registered: "
                    f"{missing_repair_targets[0].coordinate_key}"
                )
            ancestors = cls._ancestor_keys(item.coordinate, by_key)
            invalid_repair_targets = tuple(
                target
                for target in item.repair_target_coordinates
                if target.coordinate_key not in ancestors
            )
            if invalid_repair_targets:
                raise WorkGraphError(
                    "WorkGraph repair target must be a causal dependency ancestor: "
                    f"{invalid_repair_targets[0].coordinate_key}"
                )
        cls._assert_acyclic(items, by_key)
        if strict_input_contracts:
            cls._assert_declared_input_sources(items, by_key)
        terminals = tuple(
            WorkCoordinate.model_validate(item.model_dump(mode="python"))
            for item in (
                required_terminal_coordinates
                if required_terminal_coordinates is not None
                else cls._terminal_coordinates(items)
            )
        )
        if not terminals or len({item.coordinate_key for item in terminals}) != len(terminals):
            raise WorkGraphError("WorkGraph requires unique terminal coordinates")
        unknown = tuple(item for item in terminals if item.coordinate_key not in by_key)
        if unknown:
            raise WorkGraphError(
                f"WorkGraph terminal is not registered: {unknown[0].coordinate_key}"
            )
        actual_terminal_keys = {item.coordinate_key for item in cls._terminal_coordinates(items)}
        if any(item.coordinate_key not in actual_terminal_keys for item in terminals):
            raise WorkGraphError("required WorkGraph terminals must be dependency leaves")
        if mode == "production":
            if {item.coordinate_key for item in terminals} != actual_terminal_keys:
                raise WorkGraphError(
                    "production WorkGraph must freeze every dependency leaf as required"
                )
            if not _has_complete_production_topology(
                (item.coordinate for item in items), terminals
            ):
                raise WorkGraphError(
                    "production WorkGraph requires the complete generation topology"
                )
        return cls(
            tuple(sorted(items, key=lambda item: item.coordinate.coordinate_key)),
            tuple(sorted(group_items, key=lambda item: item.group_id)),
            tuple(sorted(milestone_items, key=lambda item: item.milestone_id)),
            mode,
            tuple(sorted(terminals, key=lambda item: item.coordinate_key)),
        )

    @staticmethod
    def _ancestor_keys(
        coordinate: WorkCoordinate,
        by_key: dict[str, WorkDefinition],
    ) -> set[str]:
        """Return transitive readiness ancestors for repair-edge validation."""

        ancestors: set[str] = set()
        pending = deque(by_key[coordinate.coordinate_key].dependency_coordinates)
        while pending:
            parent = pending.popleft()
            if parent.coordinate_key in ancestors:
                continue
            ancestors.add(parent.coordinate_key)
            pending.extend(by_key[parent.coordinate_key].dependency_coordinates)
        return ancestors

    @staticmethod
    def _terminal_coordinates(
        definitions: tuple[WorkDefinition, ...],
    ) -> tuple[WorkCoordinate, ...]:
        dependency_keys = {
            dependency.coordinate_key
            for item in definitions
            for dependency in item.dependency_coordinates
        }
        return tuple(
            item.coordinate
            for item in definitions
            if item.coordinate.coordinate_key not in dependency_keys
        )

    @staticmethod
    def _assert_acyclic(
        definitions: tuple[WorkDefinition, ...],
        by_key: dict[str, WorkDefinition],
    ) -> None:
        indegree = {item.coordinate.coordinate_key: 0 for item in definitions}
        children: dict[str, list[str]] = {key: [] for key in indegree}
        for item in definitions:
            child_key = item.coordinate.coordinate_key
            for dependency in item.dependency_coordinates:
                parent_key = dependency.coordinate_key
                indegree[child_key] += 1
                children[parent_key].append(child_key)
        ready = deque(key for key, degree in indegree.items() if degree == 0)
        visited = 0
        while ready:
            key = ready.popleft()
            visited += 1
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    ready.append(child)
        if visited != len(by_key):
            raise WorkGraphError("WorkGraph contains a dependency cycle")

    @staticmethod
    def _assert_declared_input_sources(
        definitions: tuple[WorkDefinition, ...],
        by_key: dict[str, WorkDefinition],
    ) -> None:
        """Prove every declared non-root input can come from a direct parent.

        A dependency is a *causal* edge: changing that parent invalidates the
        child.  An input slot is a separate, least-privilege disclosure edge:
        it names exactly which parent Artifacts may enter the leaf.  Keeping
        these two relations distinct lets a code-only observer depend on a
        completed Judge without receiving its sealed report, while a Builder
        receives only the EnvironmentDesign it actually needs.

        This check catches the opposite error at graph-freeze time: a leaf
        declaring an Artifact that no direct producer can supply.  Runtime
        then filters parent consumer refs through these slots and keeps its
        strict unexpected-ref check as a final fence.
        """

        for definition in definitions:
            parents = tuple(
                by_key[parent.coordinate_key] for parent in definition.dependency_coordinates
            )
            if parents and not definition.input_slots:
                raise WorkGraphError(
                    "strict WorkGraph requires an explicit input disclosure contract: "
                    f"{definition.coordinate.coordinate_key}"
                )
            for slot in definition.input_slots:
                if slot.producer_component == "external":
                    continue
                matching_output_slots = tuple(
                    output_slot
                    for parent in parents
                    if parent.coordinate.component == slot.producer_component
                    for output_slot in parent.output_slots
                    if set(output_slot.artifact_types) & set(slot.artifact_types)
                )
                maximum_available = sum(
                    output_slot.maximum_count for output_slot in matching_output_slots
                )
                minimum_available = sum(
                    output_slot.minimum_count for output_slot in matching_output_slots
                )
                if not matching_output_slots or slot.minimum_count > maximum_available:
                    raise WorkGraphError(
                        "WorkGraph input slot has no sufficient direct parent output: "
                        f"{definition.coordinate.coordinate_key}:{slot.slot_id}"
                    )
                if slot.maximum_count < minimum_available:
                    raise WorkGraphError(
                        "WorkGraph input slot cannot accept every required direct parent output: "
                        f"{definition.coordinate.coordinate_key}:{slot.slot_id}"
                    )

    @property
    def definitions(self) -> tuple[WorkDefinition, ...]:
        return self._definitions

    @property
    def groups(self) -> tuple[WorkGroupDefinition, ...]:
        return self._groups

    @property
    def milestones(self) -> tuple[WorkGraphMilestone, ...]:
        return self._milestones

    @property
    def graph_digest(self) -> ContentHash:
        return self.manifest(topology_id="topology:unpersisted").graph_digest

    @property
    def release_eligible(self) -> bool:
        return (
            self.mode == "production"
            and {item.kind for item in self._milestones} >= {"release_candidate", "released"}
            and _has_complete_production_topology(
                (item.coordinate for item in self._definitions),
                self.required_terminal_coordinates,
            )
        )

    def manifest(
        self,
        *,
        topology_id: Identifier,
        external_root_refs: tuple[ArtifactRef, ...] = (),
    ) -> WorkGraphManifest:
        scope_id = self._definitions[0].coordinate.scope_id
        bindings = tuple(
            WorkGraphNodeBinding(
                coordinate=item.coordinate,
                work_id=item.work_id,
                definition_digest=item.definition_digest,
            )
            for item in self._definitions
        )
        group_bindings = tuple(
            WorkGraphGroupBinding(
                group_id=item.group_id,
                group_digest=item.content_digest(),
                aggregate_coordinate=item.aggregate_coordinate,
                member_coordinates=item.member_coordinates,
            )
            for item in self._groups
        )
        milestone_bindings = tuple(
            WorkGraphMilestoneBinding(
                milestone_id=item.milestone_id,
                milestone_digest=item.content_digest(),
                kind=item.kind,
                required_coordinates=item.required_coordinates,
                establishes=item.establishes,
            )
            for item in self._milestones
        )
        identity = sha256_digest(
            canonical_json_bytes(
                {
                    "scope_id": scope_id,
                    "topology_id": topology_id,
                    "mode": self.mode,
                    "node_bindings": tuple(item.model_dump(mode="json") for item in bindings),
                    "group_bindings": tuple(
                        item.model_dump(mode="json") for item in group_bindings
                    ),
                    "milestone_bindings": tuple(
                        item.model_dump(mode="json") for item in milestone_bindings
                    ),
                    "required_terminal_coordinates": tuple(
                        item.model_dump(mode="json") for item in self.required_terminal_coordinates
                    ),
                    "external_root_refs": tuple(
                        item.model_dump(mode="json") for item in external_root_refs
                    ),
                }
            )
        ).removeprefix("sha256:")[:24]
        return WorkGraphManifest(
            graph_id=f"work-graph:{identity}",
            scope_id=scope_id,
            topology_id=topology_id,
            mode=self.mode,
            node_bindings=bindings,
            group_bindings=group_bindings,
            milestone_bindings=milestone_bindings,
            required_terminal_coordinates=self.required_terminal_coordinates,
            external_root_refs=external_root_refs,
            diagnostic_only=self.mode == "diagnostic",
            releasable=self.release_eligible,
        )

    def topological_definitions(self) -> tuple[WorkDefinition, ...]:
        """Return parents before consumers using deterministic coordinate order."""

        by_key = {item.coordinate.coordinate_key: item for item in self._definitions}
        indegree = {key: 0 for key in by_key}
        children: dict[str, list[str]] = {key: [] for key in by_key}
        for item in self._definitions:
            child_key = item.coordinate.coordinate_key
            for dependency in item.dependency_coordinates:
                indegree[child_key] += 1
                children[dependency.coordinate_key].append(child_key)
        ready = sorted(key for key, degree in indegree.items() if degree == 0)
        ordered: list[WorkDefinition] = []
        while ready:
            key = ready.pop(0)
            ordered.append(by_key[key])
            for child_key in sorted(children[key]):
                indegree[child_key] -= 1
                if indegree[child_key] == 0:
                    ready.append(child_key)
                    ready.sort()
        return tuple(ordered)

    def require(self, coordinate: WorkCoordinate) -> WorkDefinition:
        definition = next(
            (item for item in self._definitions if item.coordinate == coordinate),
            None,
        )
        if definition is None:
            raise WorkGraphError(f"unknown WorkCoordinate: {coordinate.coordinate_key}")
        return definition

    def descendants(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return all and only transitive consumers in deterministic topological order."""

        self.require(coordinate)
        reached: set[str] = set()
        queue = deque((coordinate.coordinate_key,))
        ordered: list[WorkCoordinate] = []
        while queue:
            parent_key = queue.popleft()
            children = sorted(
                (
                    item
                    for item in self._definitions
                    if any(
                        dependency.coordinate_key == parent_key
                        for dependency in item.dependency_coordinates
                    )
                ),
                key=lambda item: item.coordinate.coordinate_key,
            )
            for child in children:
                key = child.coordinate.coordinate_key
                if key in reached:
                    continue
                reached.add(key)
                ordered.append(child.coordinate)
                queue.append(key)
        return tuple(ordered)

    def ancestors(self, coordinate: WorkCoordinate) -> tuple[WorkCoordinate, ...]:
        """Return transitive producers in deterministic topological order."""

        self.require(coordinate)
        by_key = {item.coordinate.coordinate_key: item for item in self._definitions}
        ancestor_keys = self._ancestor_keys(coordinate, by_key)
        return tuple(
            item.coordinate
            for item in self.topological_definitions()
            if item.coordinate.coordinate_key in ancestor_keys
        )

    def automatic_repair_target(
        self,
        *,
        current: WorkCoordinate,
        proposed_target: WorkCoordinate,
    ) -> WorkDefinition:
        """Permit local or one declared causal repair edge only."""

        current_definition = self.require(current)
        target = self.require(proposed_target)
        if proposed_target == current:
            return target
        if proposed_target not in current_definition.repair_target_coordinates:
            raise WorkGraphError("automatic repair target is not a declared causal edge")
        if current_definition.repair_policy.maximum_automatic_backjump < 1:
            raise WorkGraphError("this WorkDefinition forbids automatic parent correction")
        return target


def tool_semantics_batch_definition(
    *,
    job_id: Identifier,
    group_id: Identifier,
    batch_id: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    agent_wall_seconds: float,
    agent_token_limit: int,
    agent_monetary_limit: float = 0.0,
    validation_wall_seconds: float = 10.0,
) -> WorkDefinition:
    """Compile framework policy for one real ToolSemanticsBatch shard."""

    coordinate = WorkCoordinate(
        scope_id=job_id,
        component="design",
        stage="world_behavior",
        artifact_slot="tool_semantics_batch",
        group_id=group_id,
        shard_id=batch_id,
    )
    digest = _stable_work_identity_digest(coordinate)
    claim_id = "design.tool_semantics.compiles"
    return WorkDefinition(
        work_id=f"work:tool-semantics:{digest}",
        coordinate=coordinate,
        claim=(
            "The exact tool batch compiles against the frozen world schema, "
            "Rule IR context, and shared multi-tool constraints."
        ),
        timing_reason=(
            "World rules and task materialization may consume this batch only after "
            "its deterministic semantic frontier closes."
        ),
        dependency_coordinates=dependency_coordinates,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:tool-semantics:{digest}",
            executor="agent",
            operation="design.tool_semantics_batch",
            budget=OperationBudget(
                wall_seconds=agent_wall_seconds,
                llm_tokens=agent_token_limit,
                agent_turns=1,
                monetary_cost=agent_monetary_limit,
            ),
            agent_role="environment_engineer",
            capability_profile_id="profile:environment-engineer",
            output_contract_id="contract:tool-semantics-batch-source.v7",
            implementation_revision_id=tool_semantics_batch_implementation_revision(),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:tool-semantics:{digest}",
            validator_id="validator:tool-semantics-batch",
            validator_revision_id=tool_semantics_batch_validator_revision(),
            validation_phase="tool_semantics",
            frontier_ordinal=20,
            claim_id=claim_id,
            effect="block_compile",
            budget=OperationBudget(wall_seconds=validation_wall_seconds),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:tool-semantics:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_model_fallbacks=1,
            maximum_automatic_backjump=0,
            # The post-fix repair chain is local correction + strict-progress
            # bonus + one same-model infrastructure retry + one model fallback
            # (4 charged attempts); 3 structurally excluded the fallback.
            maximum_total_repair_attempts=5,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=("/tools",),
        success_maturity="semantic_compiled",
    )


def structured_agent_work_definition(
    *,
    scope_id: Identifier,
    component: Literal["research", "design", "build"] = "design",
    stage: Identifier,
    artifact_slot: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    output_contract_id: Identifier,
    acceptance_transform_id: Identifier | None = None,
    executor_revision_id: Identifier = "framework.executor.v1",
    implementation_revision_id: Identifier = "framework.impl.unversioned.v0",
    validator_revision_id: Identifier | None = None,
    agent_role: Literal["researcher", "environment_engineer"] = "environment_engineer",
    allowed_mutation_roots: tuple[str, ...],
    agent_wall_seconds: float,
    agent_token_limit: int,
    session_token_limit: int | None = None,
    session_wall_seconds: float | None = None,
    replay_mode: Literal[
        "deterministic", "idempotent_with_key", "queryable", "non_replayable"
    ] = "non_replayable",
    maximum_local_corrections: int = 1,
    strict_progress_bonus_corrections: int = 1,
    maximum_infrastructure_retries: int = 1,
    maximum_model_fallbacks: int = 1,
    maximum_session_continuations: int = 0,
    maximum_process_recoveries: int = 2,
    maximum_automatic_backjump: int = 0,
    # Sized for the full post-fix chain (local + bonus + infra + fallback) plus
    # one quality-loop margin; 3 made the model fallback structurally impossible.
    maximum_total_repair_attempts: int = 5,
    group_id: Identifier | None = None,
    shard_id: Identifier | None = None,
    success_maturity: Identifier = "semantic_compiled",
    input_slots: tuple[ArtifactSlotContract, ...] = (),
    output_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    """Compile one explicit, bounded semantic Agent transaction policy."""

    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
        group_id=group_id,
        shard_id=shard_id,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependency_coordinates,
        input_slots=input_slots,
        output_slots=output_slots,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="agent",
            executor_revision_id=executor_revision_id,
            implementation_revision_id=implementation_revision_id,
            operation=f"design.{stage}",
            replay_mode=replay_mode,
            budget=OperationBudget(
                wall_seconds=agent_wall_seconds,
                llm_tokens=agent_token_limit,
                agent_turns=1,
            ),
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            agent_role=agent_role,
            capability_profile_id=f"profile:{agent_role.replace('_', '-')}",
            output_contract_id=output_contract_id,
            acceptance_transform_id=acceptance_transform_id,
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=(validator_revision_id or f"framework.validator.{stage}.v1"),
            validation_phase=stage,
            frontier_ordinal=10,
            claim_id=claim_id,
            effect="block_compile",
            budget=OperationBudget(wall_seconds=30.0),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=maximum_local_corrections,
            strict_progress_bonus_corrections=strict_progress_bonus_corrections,
            maximum_infrastructure_retries=maximum_infrastructure_retries,
            maximum_model_fallbacks=maximum_model_fallbacks,
            maximum_session_continuations=maximum_session_continuations,
            maximum_process_recoveries=maximum_process_recoveries,
            maximum_automatic_backjump=maximum_automatic_backjump,
            maximum_total_repair_attempts=maximum_total_repair_attempts,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def bind_model_route_recovery_policy(
    definitions: Iterable[WorkDefinition],
    *,
    model_routes: tuple[str, ...],
    maximum_same_model_infrastructure_retries: int = 1,
) -> tuple[WorkDefinition, ...]:
    """Bind Agent recovery authority to the complete configured model order.

    A non-zero ``maximum_model_fallbacks`` declares that a node may use the
    configured model-route policy.  The concrete count cannot be known inside
    a static WorkDefinition factory: it is supplied only by the composition
    root, before the graph is frozen.  Keeping that binding here means the
    effective route chain is identity-bound and visible in the durable
    definition rather than being a hidden scheduler override.

    Nodes that explicitly declare zero infrastructure authority remain
    unchanged. For an eligible Agent/Direct node, the configured number of
    fresh infrastructure retries is available per configured model and each
    transition to a later configured model consumes one repair action. The
    total ceiling therefore also covers the semantic allowance plus that
    finite route chain.
    """

    items = tuple(definitions)
    if maximum_same_model_infrastructure_retries < 1:
        raise WorkGraphError("same-model infrastructure retry limit must be positive")
    if not model_routes:
        return items
    if len(set(model_routes)) != len(model_routes) or any(
        not model or model != model.strip() for model in model_routes
    ):
        raise WorkGraphError("model recovery binding requires unique canonical model routes")

    fallback_count = len(model_routes) - 1
    rebound: list[WorkDefinition] = []
    for definition in items:
        policy = definition.repair_policy
        if (
            definition.proposal_policy.executor != "agent"
            or policy.maximum_infrastructure_retries == 0
        ):
            rebound.append(definition)
            continue
        semantic_allowance = (
            policy.maximum_local_corrections + policy.strict_progress_bonus_corrections
        )
        route_recovery_allowance = (
            maximum_same_model_infrastructure_retries * len(model_routes)
            + (
                fallback_count
                if policy.maximum_model_fallbacks > 0
                else 0
            )
        )
        rebound_policy = policy.model_copy(
            update={
                "maximum_infrastructure_retries": (
                    maximum_same_model_infrastructure_retries
                ),
                "maximum_model_fallbacks": (
                    fallback_count
                    if policy.maximum_model_fallbacks > 0
                    else 0
                ),
                "maximum_total_repair_attempts": max(
                    policy.maximum_total_repair_attempts,
                    semantic_allowance + route_recovery_allowance,
                ),
            }
        )
        rebound.append(definition.model_copy(update={"repair_policy": rebound_policy}))
    return tuple(rebound)


def research_plan_work_definition(
    *,
    scope_id: Identifier,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the root ResearchPlan claim with no implicit Controller inputs."""

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim=(
            "The bounded research plan covers workflow, tools, state, authority, errors, and "
            "risks before any real search is spent."
        ),
        timing_reason="Real search must consume one validated bounded query plan.",
        output_contract_id="contract:research-plan",
        acceptance_transform_id="framework.direct-structured-output.v3",
        implementation_revision_id=research_plan_implementation_revision(),
        validator_revision_id=research_plan_validator_revision(),
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-plan",
                direction="output",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        success_maturity="research_planned",
    )


def research_synthesis_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the one tool-free claim that turns admitted bodies into an EvidenceGraph."""

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="research",
        stage="evidence_synthesis",
        artifact_slot="evidence_synthesis",
        dependency_coordinates=(dependency_coordinate,),
        claim_id="research.evidence.grounded",
        claim=(
            "Observed claims bind real fetched passages while conflicts and unknowns remain "
            "explicit."
        ),
        timing_reason="World architecture may consume only one grounded EvidenceGraph.",
        output_contract_id="contract:evidence-synthesis",
        acceptance_transform_id="framework.direct-structured-output.v3",
        implementation_revision_id=evidence_synthesis_implementation_revision(),
        validator_revision_id=evidence_synthesis_validator_revision(),
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:research-acquisition",
                direction="input",
                artifact_types=("design.research_acquisition",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-passage-pack",
                direction="input",
                artifact_types=("design.evidence_passage_pack",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:research-source-closure",
                direction="input",
                artifact_types=(
                    "evidence.raw_content",
                    "evidence.response_metadata",
                    "evidence.extracted_content",
                ),
                minimum_count=3,
                maximum_count=96,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:evidence-synthesis",
                direction="output",
                artifact_types=("design.evidence_synthesis",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:evidence-graph",
                direction="output",
                artifact_types=("design.evidence_graph",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        success_maturity="research_synthesized",
    )


def world_architecture_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Compile the single Architecture transaction after grounded evidence.

    This is a semantic boundary, not a second verification loop.  The Agent
    describes domain meaning once; framework code immediately compiles the
    state/tool schema closure and deterministic coupling plan that downstream
    nodes must consume unchanged.
    """

    return structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        artifact_slot="world_architecture",
        dependency_coordinates=(dependency_coordinate,),
        claim_id="design.architecture.closed",
        claim=(
            "One evidence-bound world boundary, state inventory, and public tool surface "
            "compile into a closed skeleton before behavior is authored."
        ),
        timing_reason=(
            "Rules, tool behavior, tasks, and runtime code must share one compiled world "
            "identity rather than independently infer an environment."
        ),
        output_contract_id="contract:world-architecture-source.v3",
        acceptance_transform_id="framework.architecture-compiler.v3",
        implementation_revision_id=world_architecture_implementation_revision(),
        validator_revision_id=world_architecture_validator_revision(),
        agent_role="environment_engineer",
        allowed_mutation_roots=("/boundary", "/state_entities", "/tool_inventory"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-graph",
                direction="input",
                artifact_types=("design.evidence_graph",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="input:evidence-synthesis-lineage",
                direction="input",
                artifact_types=("design.evidence_synthesis",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:world-architecture-source",
                direction="output",
                artifact_types=("design.world_architecture_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-skeleton",
                direction="output",
                artifact_types=("design.world_skeleton",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:tool-coupling-plan",
                direction="output",
                artifact_types=("design.tool_coupling_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="architecture_compiled",
    )


def deterministic_boundary_work_definition(
    *,
    scope_id: Identifier,
    component: Literal["design", "integration", "release", "registry", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependency_coordinates: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_compile", "block_integration", "block_release", "quarantine"],
    success_maturity: Identifier,
    wall_seconds: float = 30.0,
) -> WorkDefinition:
    """Compile a code-owned Claim boundary with no Agent repair authority."""

    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependency_coordinates,
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="code",
            operation=f"{component}.{stage}",
            budget=OperationBudget(wall_seconds=wall_seconds),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=f"framework.validator.{stage}.v1",
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=effect,
            budget=OperationBudget(wall_seconds=wall_seconds),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_model_fallbacks=0,
            maximum_automatic_backjump=0,
            maximum_total_repair_attempts=0,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=(),
        success_maturity=success_maturity,
    )


def research_acquisition_work_definition(
    *,
    scope_id: Identifier,
    dependency_coordinate: WorkCoordinate,
    wall_seconds: float,
    maximum_search_calls: int,
    maximum_tool_calls: int,
) -> WorkDefinition:
    """Compile the real search/fetch/extract boundary between plan and synthesis.

    Search is neither an implicit side effect of EvidenceSynthesis nor an LLM
    action.  It has its own real-tools proposal, deterministic evidence
    admission and infrastructure-only recovery policy.
    """

    if maximum_search_calls < 1 or maximum_tool_calls < maximum_search_calls + 2:
        raise ValueError(
            "research acquisition requires bounded search, fetch, and extract capacity"
        )
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="research",
        stage="evidence_acquisition",
        artifact_slot="research_acquisition",
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:evidence-acquisition:{digest}",
        coordinate=coordinate,
        claim=(
            "The frozen ResearchPlan produced bounded real source bodies whose provenance "
            "can be admitted as evidence."
        ),
        timing_reason=(
            "Evidence synthesis must not infer claims from search snippets or unfetched URLs."
        ),
        dependency_coordinates=(dependency_coordinate,),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:research-plan",
                direction="input",
                artifact_types=("design.research_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:research-acquisition",
                direction="output",
                artifact_types=("design.research_acquisition",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:evidence-passage-pack",
                direction="output",
                artifact_types=("design.evidence_passage_pack",),
                minimum_count=1,
                maximum_count=1,
                producer_component="research",
            ),
            ArtifactSlotContract(
                slot_id="output:research-source-closure",
                direction="output",
                artifact_types=(
                    "evidence.raw_content",
                    "evidence.response_metadata",
                    "evidence.extracted_content",
                ),
                minimum_count=3,
                maximum_count=96,
                producer_component="research",
                confidentiality="framework_private",
            ),
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:evidence-acquisition:{digest}",
            executor="real_tools",
            operation="research.search_fetch_extract",
            # Search/fetch/extract are read-only, source-addressed queries.
            # An interrupted operation is still charged as unknown, but one
            # policy-authorized fresh query may be attempted on recovery.
            replay_mode="queryable",
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                first_progress_seconds=min(30.0, wall_seconds),
                search_calls=maximum_search_calls,
                tool_calls=maximum_tool_calls,
            ),
            capability_profile_id="profile:researcher-tools",
            tool_ids=("research.search", "research.fetch", "research.extract"),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:evidence-acquisition:{digest}",
            validator_id="validator:evidence-acquisition",
            validator_revision_id="framework.validator.evidence-acquisition.v1",
            validation_phase="evidence_acquisition",
            frontier_ordinal=20,
            claim_id="research.evidence.acquired",
            effect="block_compile",
            budget=OperationBudget(wall_seconds=min(60.0, wall_seconds)),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:evidence-acquisition:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=1,
            maximum_model_fallbacks=0,
            maximum_process_recoveries=1,
            maximum_total_repair_attempts=1,
        ),
        required_claim_id="research.evidence.acquired",
        success_maturity="research_acquired",
    )


def compile_world_work_graph(
    *,
    scope_id: Identifier,
    world_definitions: Iterable[WorkDefinition],
    strict_input_contracts: bool = False,
) -> GenerationWorkGraph:
    """Freeze behavior, WorldRules, and one small CurriculumPlan.

    ``CurriculumPlan`` is the task-family cardinality discovery boundary.  It
    is deliberately terminal here: no TaskRequirement coordinate can exist
    until the Agent has committed the ordered plan it will be bound to.
    """

    definitions = tuple(world_definitions)
    if any(item.coordinate.scope_id != scope_id for item in definitions):
        raise WorkGraphError("World definitions cannot mix generation scopes")
    stages = {(item.coordinate.component, item.coordinate.stage) for item in definitions}
    required = {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
        ("design", "world_rules"),
        ("design", "curriculum_plan"),
    }
    if not required <= stages or not any(
        item.coordinate.component == "design" and item.coordinate.stage in _BEHAVIOR_STAGES
        for item in definitions
    ):
        raise WorkGraphError(
            "world graph requires Research, behavior, WorldRules, and CurriculumPlan"
        )
    planners = tuple(
        item
        for item in definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "curriculum_plan")
    )
    world_rules = tuple(
        item
        for item in definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "world_rules")
    )
    if (
        len(planners) != 1
        or len(world_rules) != 1
        or world_rules[0].coordinate not in planners[0].dependency_coordinates
    ):
        raise WorkGraphError("world graph requires one CurriculumPlan directly bound to WorldRules")
    return GenerationWorkGraph.compile(
        definitions,
        mode="diagnostic",
        strict_input_contracts=strict_input_contracts,
        required_terminal_coordinates=(planners[0].coordinate,),
    )


def compile_design_work_graph(
    *,
    scope_id: Identifier,
    design_definitions: Iterable[WorkDefinition],
    modeling_definition: WorkDefinition,
    verifier_plan_definition: WorkDefinition,
    groups: Iterable[WorkGroupDefinition] = (),
    strict_input_contracts: bool = False,
) -> GenerationWorkGraph:
    """Freeze the non-releasable semantic prefix through VerifierPlan.

    Tool behavior is derived from Architecture and task cardinality only becomes
    known after Modeling.  The deterministic VerifierPlan is therefore the
    exact terminal of the intermediate graph; it commits the one fact needed
    to derive final Challenger physical work without hiding Agent calls.
    """

    upstream = tuple(design_definitions)
    if modeling_definition.coordinate.scope_id != scope_id:
        raise WorkGraphError("ModelingBoundary scope differs from generation scope")
    if modeling_definition.coordinate.stage != "modeling_boundary":
        raise WorkGraphError("design graph requires ModelingBoundary")
    if verifier_plan_definition.coordinate.scope_id != scope_id:
        raise WorkGraphError("VerifierPlan scope differs from generation scope")
    if (
        verifier_plan_definition.coordinate.component != "verifier"
        or verifier_plan_definition.coordinate.stage != "verifier_plan"
        or verifier_plan_definition.dependency_coordinates != (modeling_definition.coordinate,)
    ):
        raise WorkGraphError("design graph requires VerifierPlan directly after ModelingBoundary")
    if any(item.coordinate.scope_id != scope_id for item in upstream):
        raise WorkGraphError("Design definitions cannot mix generation scopes")
    upstream_by_key = {item.coordinate.coordinate_key: item for item in upstream}
    if modeling_definition.coordinate.coordinate_key in upstream_by_key:
        raise WorkGraphError("ModelingBoundary must be appended exactly once")
    if verifier_plan_definition.coordinate.coordinate_key in upstream_by_key:
        raise WorkGraphError("VerifierPlan must be appended exactly once")
    for dependency in modeling_definition.dependency_coordinates:
        if dependency.coordinate_key not in upstream_by_key:
            raise WorkGraphError("ModelingBoundary depends on an unregistered Design coordinate")
    upstream_stage_pairs = {(item.coordinate.component, item.coordinate.stage) for item in upstream}
    required_upstream = {
        ("research", "research_plan"),
        ("research", "evidence_acquisition"),
        ("research", "evidence_synthesis"),
        ("design", "world_architecture"),
        ("design", "world_rules"),
        ("design", "task_curriculum"),
    }
    if not required_upstream <= upstream_stage_pairs or not any(
        item.coordinate.component == "design" and item.coordinate.stage in _BEHAVIOR_STAGES
        for item in upstream
    ):
        raise WorkGraphError(
            "design graph requires Research and full semantic Design closure "
            "before ModelingBoundary"
        )
    modern_task_fanout = {
        ("design", "curriculum_plan"),
        ("design", "task_requirement"),
    }
    present_fanout_stages = modern_task_fanout & upstream_stage_pairs
    if present_fanout_stages and present_fanout_stages != modern_task_fanout:
        raise WorkGraphError(
            "design graph must retain both CurriculumPlan and TaskRequirement fan-out stages"
        )
    if present_fanout_stages:
        planners = tuple(
            item
            for item in upstream
            if (item.coordinate.component, item.coordinate.stage) == ("design", "curriculum_plan")
        )
        requirements = tuple(
            item
            for item in upstream
            if (item.coordinate.component, item.coordinate.stage) == ("design", "task_requirement")
        )
        curriculum = tuple(
            item
            for item in upstream
            if (item.coordinate.component, item.coordinate.stage) == ("design", "task_curriculum")
        )
        if (
            len(planners) != 1
            or not requirements
            or len(curriculum) != 1
            or planners[0].coordinate not in curriculum[0].dependency_coordinates
            or any(
                item.coordinate not in curriculum[0].dependency_coordinates for item in requirements
            )
        ):
            raise WorkGraphError(
                "TaskCurriculum join must retain the exact plan-derived TaskRequirement set"
            )
    return GenerationWorkGraph.compile(
        (*upstream, modeling_definition, verifier_plan_definition),
        mode="diagnostic",
        strict_input_contracts=strict_input_contracts,
        required_terminal_coordinates=(verifier_plan_definition.coordinate,),
        groups=groups,
    )


def _physical_session_envelope(
    *,
    node_name: str,
    physical_turn_token_limit: int,
    physical_turn_wall_seconds: float,
    session_token_limit: int | None,
    session_wall_seconds: float | None,
) -> tuple[int, float, int]:
    """Compile a logical Agent session into visible physical-turn reservations.

    A configured Provider output ceiling is not a smaller user budget.  When a
    logical session is declared, it selects the number of durable physical
    turns and each turn receives an equal token/wall reservation.  The
    Scheduler can then resume only after an observed closed output-ceiling
    terminal, rather than treating a short Provider response as completion or
    silently looping inside a node.
    """

    if (session_token_limit is None) != (session_wall_seconds is None):
        raise WorkGraphError(
            f"{node_name} logical session token and wall limits must be declared together"
        )
    if session_token_limit is None:
        return physical_turn_token_limit, physical_turn_wall_seconds, 0

    if (
        isinstance(physical_turn_token_limit, bool)
        or physical_turn_token_limit <= 0
        or physical_turn_wall_seconds <= 0
        or session_wall_seconds is None
    ):
        raise WorkGraphError(f"{node_name} physical and logical session limits must be positive")
    if (
        session_token_limit < physical_turn_token_limit
        or session_wall_seconds < physical_turn_wall_seconds
    ):
        raise WorkGraphError(
            f"{node_name} logical session envelope cannot be smaller than one physical turn"
        )

    physical_turn_count = ceil(session_token_limit / physical_turn_token_limit)
    return (
        ceil(session_token_limit / physical_turn_count),
        session_wall_seconds / physical_turn_count,
        physical_turn_count - 1,
    )


def complete_generation_work_graph(
    *,
    scope_id: Identifier,
    design_graph: GenerationWorkGraph,
    implementation_plan_wall_seconds: float = 300.0,
    implementation_plan_token_limit: int = 16_384,
    implementation_plan_session_token_limit: int | None = None,
    implementation_plan_session_wall_seconds: float | None = None,
    builder_wall_seconds: float = 1_200.0,
    builder_token_limit: int = 64_000,
    builder_session_token_limit: int | None = None,
    builder_session_wall_seconds: float | None = None,
    verifier_wall_seconds: float = 900.0,
    verifier_token_limit: int = 48_000,
    verifier_batch_count: int,
    environment_design: EnvironmentDesign | None = None,
    verifier_batch_plan: VerifierBatchPlan | None = None,
    integration_wall_seconds: float = 600.0,
    release_wall_seconds: float = 900.0,
    strict_input_contracts: bool = False,
) -> GenerationWorkGraph:
    """Compile the one releasable Direct/Evolve topology.

    The function accepts the exact intermediate ``design_graph`` rather than a
    loose list of definitions.  A real final graph additionally receives the
    committed Design and VerifierPlan used to derive finite Judge reservations.
    That avoids treating a fixed probe count as a surrogate for the actual
    task-materialization and verifier work.  Structural graph tests may omit
    those inputs only while ``strict_input_contracts`` is false; no normal
    Direct or diagnostic execution may do so.
    """

    if design_graph.mode != "diagnostic" or design_graph.release_eligible:
        raise WorkGraphError("final graph requires the diagnostic Design predecessor graph")
    upstream = design_graph.definitions
    if not upstream or upstream[0].coordinate.scope_id != scope_id:
        raise WorkGraphError("Design predecessor graph scope differs from generation scope")
    modeling = tuple(
        item
        for item in upstream
        if (item.coordinate.component, item.coordinate.stage) == ("design", "modeling_boundary")
    )
    verifier_plans = tuple(
        item
        for item in upstream
        if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_plan")
    )
    if len(modeling) != 1 or len(verifier_plans) != 1:
        raise WorkGraphError("final graph requires one retained ModelingBoundary and VerifierPlan")
    modeling_definition = modeling[0]
    verifier_plan = verifier_plans[0]
    if design_graph.required_terminal_coordinates != (verifier_plan.coordinate,):
        raise WorkGraphError("Design predecessor must terminate exactly at VerifierPlan")

    if not 1 <= verifier_batch_count <= 8:
        raise WorkGraphError("Verifier batch count must be within the fixed 1..8 capacity")
    if (environment_design is None) != (verifier_batch_plan is None):
        raise WorkGraphError(
            "final graph Judge budget derivation requires both EnvironmentDesign and VerifierPlan"
        )
    if strict_input_contracts and environment_design is None:
        raise WorkGraphError(
            "strict final graph requires committed EnvironmentDesign and VerifierPlan "
            "for Judge budgets"
        )
    if verifier_batch_plan is not None and len(verifier_batch_plan.batches) != verifier_batch_count:
        raise WorkGraphError(
            "final graph verifier batch count does not match the committed VerifierPlan"
        )
    integration_budget = (
        integration_budget_requirements(environment_design)
        if environment_design is not None
        else None
    )
    release_budget = (
        release_without_interactive_budget_requirements(environment_design, verifier_batch_plan)
        if environment_design is not None and verifier_batch_plan is not None
        else None
    )

    (
        physical_implementation_plan_token_limit,
        physical_implementation_plan_wall_seconds,
        maximum_implementation_plan_session_continuations,
    ) = _physical_session_envelope(
        node_name="BuildImplementationPlan",
        physical_turn_token_limit=implementation_plan_token_limit,
        physical_turn_wall_seconds=implementation_plan_wall_seconds,
        session_token_limit=implementation_plan_session_token_limit,
        session_wall_seconds=implementation_plan_session_wall_seconds,
    )
    (
        physical_builder_token_limit,
        physical_builder_wall_seconds,
        maximum_builder_session_continuations,
    ) = _physical_session_envelope(
        node_name="CandidateBuild",
        physical_turn_token_limit=builder_token_limit,
        physical_turn_wall_seconds=builder_wall_seconds,
        session_token_limit=builder_session_token_limit,
        session_wall_seconds=builder_session_wall_seconds,
    )

    implementation_plan = _agent_component_definition(
        scope_id=scope_id,
        component="build",
        stage="implementation_plan",
        artifact_slot="implementation_plan",
        dependencies=(modeling_definition.coordinate,),
        claim_id="build.implementation.plan.ready",
        claim=(
            "Exact frozen Design bytes are translated into an advisory implementation plan "
            "for one later CandidateBuild turn."
        ),
        timing_reason=(
            "CandidateBuild receives a focused, read-only Agent planning boundary before it "
            "writes one complete source closure."
        ),
        role="environment_engineer",
        operation="build.implementation_plan",
        output_contract_id="contract:implementation-plan.v1",
        implementation_revision_id=implementation_plan_implementation_revision(),
        validator_revision_id=implementation_plan_validator_revision(),
        validation_effect="block_integration",
        success_maturity="implementation_planned",
        wall_seconds=physical_implementation_plan_wall_seconds,
        token_limit=physical_implementation_plan_token_limit,
        session_token_limit=implementation_plan_session_token_limit,
        session_wall_seconds=implementation_plan_session_wall_seconds,
        maximum_session_continuations=maximum_implementation_plan_session_continuations,
        # This names advisory Artifact replacement, not a filesystem grant.
        # The actual profile is read-only and has no Candidate mutation root.
        allowed_mutation_roots=("/implementation-plan",),
        output_types=("build.implementation_contract", "build.implementation_plan"),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
    )
    build = _agent_component_definition(
        scope_id=scope_id,
        component="build",
        stage="candidate_build",
        artifact_slot="environment_candidate",
        dependencies=(modeling_definition.coordinate, implementation_plan.coordinate),
        claim_id="build.candidate.valid",
        claim="Exact frozen Design bytes are implemented as a closed executable Candidate.",
        timing_reason="Integration can execute only a committed Candidate source closure.",
        role="environment_engineer",
        operation="build.environment_candidate",
        output_contract_id="contract:environment-candidate.v3",
        implementation_revision_id=candidate_build_implementation_revision(),
        validator_revision_id=candidate_build_validator_revision(),
        validation_effect="block_integration",
        success_maturity="candidate_built",
        wall_seconds=physical_builder_wall_seconds,
        token_limit=physical_builder_token_limit,
        session_token_limit=builder_session_token_limit,
        session_wall_seconds=builder_session_wall_seconds,
        maximum_session_continuations=maximum_builder_session_continuations,
        # A completion/build failure is a design-quality verdict: the builder
        # has no mutation root of its own, so the only repair is a causal
        # rework of the frozen EnvironmentDesign parent.
        repair_targets=(modeling_definition.coordinate,),
        allowed_mutation_roots=("/source", "/dependencies", "/runtime", "/materializer"),
        output_types=(
            "build.source_workspace_snapshot",
            "build.implementation_lineage",
            "build.candidate_manifest",
            "build.record",
            "build.environment_candidate",
        ),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-contract",
                direction="input",
                artifact_types=("build.implementation_contract",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-plan",
                direction="input",
                artifact_types=("build.implementation_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    verifier_batches, verifier_group, verifier = _verifier_intent_group(
        scope_id=scope_id,
        verifier_plan_coordinate=verifier_plan.coordinate,
        batch_count=verifier_batch_count,
        wall_seconds=verifier_wall_seconds,
        token_limit=verifier_token_limit,
    )
    integration = _assured_code_definition(
        scope_id=scope_id,
        component="integration",
        stage="runtime_integration",
        artifact_slot="integration_report",
        dependencies=(build.coordinate,),
        repair_targets=(build.coordinate,),
        claim_id="integration.runtime.executable",
        claim="Candidate installs, starts, materializes tasks, resets and steps in isolation.",
        timing_reason="Release assurance may consume only fresh Candidate execution evidence.",
        effect="block_release",
        success_maturity="integration_passed",
        wall_seconds=integration_wall_seconds,
        probe_ids=(
            "clean-install",
            "runtime-handshake",
            "task-materialization",
            "reset-step",
            "restart-teardown",
        ),
        output_types=("judge.integration_report",),
        allowed_mutation_roots=("/source", "/dependencies", "/runtime", "/materializer"),
        implementation_revision_id=runtime_integration_implementation_revision(),
        validator_revision_id=runtime_integration_validator_revision(),
        proposal_budget_requirements=integration_budget,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
        ),
    )
    release_assurance = _assured_code_definition(
        scope_id=scope_id,
        component="judge",
        stage="release_assurance",
        artifact_slot="judge_report",
        # Release probes may expose a causal Candidate defect that integration's
        # public smoke did not reach.  Build is consequently a direct readiness
        # and one-hop repair edge, not an implicit two-hop ancestor hidden behind
        # Integration.  Exact Integration evidence is still consumed to avoid
        # rerunning its matching checks under another name.
        dependencies=(
            build.coordinate,
            integration.coordinate,
            verifier.coordinate,
            *(item.coordinate for item in verifier_batches),
        ),
        repair_targets=(build.coordinate,),
        claim_id="release.assurance.passed",
        claim="Exact Candidate and Verifier bytes satisfy every required hard release claim.",
        timing_reason="Packaging is forbidden until independent additive release probes pass.",
        effect="block_release",
        success_maturity="release_assured",
        wall_seconds=release_wall_seconds,
        probe_ids=(
            "task-reachability",
            "rule-properties",
            "sealed-cases",
            "fresh-deployment",
        ),
        output_types=("judge_report",),
        allowed_mutation_roots=("/verifier", "/source", "/runtime"),
        implementation_revision_id=release_assurance_implementation_revision(),
        validator_revision_id=release_assurance_validator_revision(),
        proposal_budget_requirements=release_budget,
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:release-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:integration-report",
                direction="input",
                artifact_types=("judge.integration_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="integration",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-ir",
                direction="input",
                artifact_types=("judge.verifier_ir_projection",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-batch-draft",
                direction="input",
                artifact_types=("judge.verifier_batch_draft",),
                minimum_count=verifier_batch_count,
                maximum_count=verifier_batch_count,
                producer_component="verifier",
                confidentiality="sealed",
            ),
        ),
    )
    observability = _code_component_definition(
        scope_id=scope_id,
        component="release",
        stage="observability_closure",
        artifact_slot="telemetry_release_summary",
        dependencies=(release_assurance.coordinate,),
        claim_id="release.observability.closed",
        claim="The run exposes complete typed time, usage, tool, process and repair accounting.",
        timing_reason="An unauditable Candidate cannot enter an experimental release package.",
        effect="block_release",
        success_maturity="observability_closed",
        # This is the immutable pre-package trace cut consumed by the Dossier,
        # envpkg metadata and Registry.  A post-publish trace is operational
        # telemetry only: it cannot be a dependency of the package it observes.
        output_types=("release.telemetry_summary",),
        # Declaring the common root explicitly means this observer receives no
        # Judge artifact bytes from its causal predecessor; it reads only the
        # telemetry store under its own framework capability.
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:generation-context",
                direction="input",
                artifact_types=("control.generation_context",),
                minimum_count=1,
                maximum_count=1,
                producer_component="external",
                confidentiality="framework_private",
            ),
        ),
    )
    package = _code_component_definition(
        scope_id=scope_id,
        component="release",
        stage="package",
        artifact_slot="environment_package",
        # Package assembly is an explicit closure consumer.  It receives the
        # exact active Design, Candidate, Verifier and independent reports
        # rather than reaching into unrelated Work heads behind the Scheduler.
        dependencies=(
            modeling_definition.coordinate,
            build.coordinate,
            verifier.coordinate,
            integration.coordinate,
            release_assurance.coordinate,
            observability.coordinate,
        ),
        claim_id="release.package.closed",
        claim="The exact assured Candidate is assembled as a canonical movable envpkg v3 closure.",
        timing_reason="Registry may inspect only immutable package bytes and their manifest.",
        effect="block_release",
        success_maturity="release_candidate_ready",
        output_types=("environment_package_manifest",),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:environment-design",
                direction="input",
                artifact_types=("design.environment_design",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:world-spec",
                direction="input",
                artifact_types=("design.world_spec",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:environment-candidate",
                direction="input",
                artifact_types=("build.environment_candidate",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:candidate-manifest",
                direction="input",
                artifact_types=("build.candidate_manifest",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:build-record",
                direction="input",
                artifact_types=("build.record",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:implementation-lineage",
                direction="input",
                artifact_types=("build.implementation_lineage",),
                minimum_count=1,
                maximum_count=1,
                producer_component="build",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-ir",
                direction="input",
                artifact_types=("judge.verifier_ir_projection",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
            ArtifactSlotContract(
                slot_id="input:integration-report",
                direction="input",
                artifact_types=("judge.integration_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="integration",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:judge-report",
                direction="input",
                artifact_types=("judge_report",),
                minimum_count=1,
                maximum_count=1,
                producer_component="judge",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:telemetry-summary",
                direction="input",
                artifact_types=("release.telemetry_summary",),
                minimum_count=1,
                maximum_count=1,
                producer_component="release",
                confidentiality="framework_private",
            ),
        ),
    )
    registry = _code_component_definition(
        scope_id=scope_id,
        component="registry",
        stage="publication",
        artifact_slot="registry_publication",
        dependencies=(package.coordinate,),
        claim_id="registry.publication.committed",
        claim="Registry atomically published and reread the exact envpkg bytes.",
        timing_reason="Only atomic Registry truth establishes a released EnvironmentPackage.",
        effect="block_release",
        success_maturity="released",
        output_types=("release.record",),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:package-manifest",
                direction="input",
                artifact_types=("environment_package_manifest",),
                minimum_count=1,
                maximum_count=1,
                producer_component="release",
            ),
        ),
    )
    milestones = (
        WorkGraphMilestone(
            milestone_id="milestone:release-candidate",
            kind="release_candidate",
            required_coordinates=(package.coordinate,),
            establishes="release_candidate_ready",
        ),
        WorkGraphMilestone(
            milestone_id="milestone:released",
            kind="released",
            required_coordinates=(registry.coordinate,),
            establishes="released",
        ),
    )
    return GenerationWorkGraph.compile(
        (
            *upstream,
            implementation_plan,
            build,
            *verifier_batches,
            verifier,
            integration,
            release_assurance,
            observability,
            package,
            registry,
        ),
        mode="production",
        strict_input_contracts=strict_input_contracts,
        required_terminal_coordinates=(registry.coordinate,),
        groups=(*design_graph.groups, verifier_group),
        milestones=milestones,
    )


def derive_final_design_definitions(
    *,
    scope_id: Identifier,
    bootstrap_definitions: tuple[WorkDefinition, ...],
    architecture_source_ref: ArtifactRef,
    coupling_plan: ToolCouplingPlan,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkDefinition]:
    """Freeze the only final Design suffix from a committed coupling plan.

    Architecture is the one deliberate topology-discovery boundary: it fixes
    the actual tool batches and any cross-batch shared-semantics transactions.
    This compiler turns that immutable plan into physical WorkDefinitions. It
    never invokes an Agent, reads a workspace, or reaches into the legacy
    Designer. Direct Generation and Evolve both call this exact compiler after
    adapting their respective frozen ``GenerationContext``.

    The `ToolCouplingPlan` import is type-only: the control layer never calls
    Designer code. Its closed `groups` expose `group_id`, `mode` and
    `ordered_tool_ids`; `execution_batches` contains every tool exactly once
    in frozen order.
    """

    if agent_wall_seconds <= 0 or agent_token_limit <= 0:
        raise WorkGraphError("final Design Agent budgets must be positive")
    if not bootstrap_definitions:
        raise WorkGraphError("final Design derivation requires retained bootstrap definitions")
    if any(item.coordinate.scope_id != scope_id for item in bootstrap_definitions):
        raise WorkGraphError("bootstrap definitions mix a different generation scope")

    architecture = tuple(
        item
        for item in bootstrap_definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "world_architecture")
    )
    if len(architecture) != 1:
        raise WorkGraphError("final Design derivation requires exactly one Architecture definition")
    architecture_coordinate = architecture[0].coordinate
    if architecture_source_ref.artifact_type != "design.world_architecture_source":
        raise WorkGraphError("final Design derivation requires a WorldArchitecture source Artifact")
    if coupling_plan.architecture_ref != architecture_source_ref:
        raise WorkGraphError(
            "ToolCouplingPlan is not bound to the committed WorldArchitecture source"
        )
    synthesis = tuple(
        item
        for item in bootstrap_definitions
        if (item.coordinate.component, item.coordinate.stage) == ("research", "evidence_synthesis")
    )
    if len(synthesis) != 1:
        raise WorkGraphError(
            "final Design derivation requires exactly one EvidenceSynthesis definition"
        )
    synthesis_coordinate = synthesis[0].coordinate

    groups = coupling_plan.groups
    execution_batches = coupling_plan.execution_batches
    if not groups or not execution_batches:
        raise WorkGraphError("ToolCouplingPlan must contain groups and execution batches")

    declared_tool_ids = tuple(tool_id for group in groups for tool_id in group.ordered_tool_ids)
    scheduled_tool_ids = tuple(tool_id for batch in execution_batches for tool_id in batch)
    if (
        not declared_tool_ids
        or len(set(declared_tool_ids)) != len(declared_tool_ids)
        or tuple(sorted(scheduled_tool_ids)) != tuple(sorted(declared_tool_ids))
        or len(scheduled_tool_ids) != len(declared_tool_ids)
    ):
        raise WorkGraphError("ToolCouplingPlan does not freeze an exact tool-batch partition")
    # Defense in depth for unvalidated/model-constructed coupling plans.  A
    # historical wider plan remains inspectable, but no new graph may execute
    # it: one complete tool is the current physical Provider boundary.
    if any(len(batch) != 1 for batch in execution_batches):
        raise WorkGraphError("ToolCouplingPlan requires singleton physical tool shards")

    context_slot = ArtifactSlotContract(
        slot_id="input:generation-context",
        direction="input",
        artifact_types=("control.generation_context",),
        minimum_count=1,
        maximum_count=1,
        producer_component="external",
        confidentiality="framework_private",
    )
    architecture_input_slots = (
        context_slot,
        ArtifactSlotContract(
            slot_id="input:world-architecture-source",
            direction="input",
            artifact_types=("design.world_architecture_source",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:world-skeleton",
            direction="input",
            artifact_types=("design.world_skeleton",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:tool-coupling-plan",
            direction="input",
            artifact_types=("design.tool_coupling_plan",),
            minimum_count=1,
            maximum_count=1,
            producer_component="design",
        ),
        ArtifactSlotContract(
            slot_id="input:evidence-graph",
            direction="input",
            artifact_types=("design.evidence_graph",),
            minimum_count=1,
            maximum_count=1,
            producer_component="research",
        ),
    )

    shared_definitions: list[WorkDefinition] = []
    shared_coordinates: dict[str, WorkCoordinate] = {}
    for group in groups:
        group_id = group.group_id
        if group.mode != "multi_batch":
            continue
        coordinate = WorkCoordinate(
            scope_id=scope_id,
            component="design",
            stage="shared_tool_semantics",
            artifact_slot="shared_tool_semantics",
            group_id=group_id,
        )
        shared_coordinates[group_id] = coordinate
        shared_definitions.append(
            structured_agent_work_definition(
                scope_id=scope_id,
                component="design",
                stage="shared_tool_semantics",
                artifact_slot="shared_tool_semantics",
                group_id=group_id,
                dependency_coordinates=(architecture_coordinate, synthesis_coordinate),
                claim_id="design.shared_behavior.closed",
                claim=(
                    "Cross-batch atomicity, ordering, compensation, idempotency and error "
                    "policy are fixed before their physical tool batches execute."
                ),
                timing_reason=(
                    "A coupled group may not author incompatible local retry or rollback "
                    "behavior in separate Agent calls."
                ),
                output_contract_id="contract:shared-tool-semantics-source.v3",
                acceptance_transform_id="framework.shared-tool-semantics-compiler.v3",
                implementation_revision_id=shared_tool_semantics_implementation_revision(),
                validator_revision_id=shared_tool_semantics_validator_revision(),
                agent_role="environment_engineer",
                allowed_mutation_roots=(
                    "/atomicity_domains",
                    "/concurrency_domains",
                    "/idempotency_domains",
                    "/ordering_constraints",
                    "/compensation_edges",
                    "/error_policies",
                ),
                agent_wall_seconds=agent_wall_seconds,
                agent_token_limit=agent_token_limit,
                input_slots=architecture_input_slots,
                output_slots=(
                    ArtifactSlotContract(
                        slot_id="output:shared-tool-semantics-source",
                        direction="output",
                        artifact_types=("design.shared_tool_semantics_source",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="design",
                    ),
                    ArtifactSlotContract(
                        slot_id="output:shared-tool-semantics-contract",
                        direction="output",
                        artifact_types=("design.shared_tool_semantics_contract",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="design",
                    ),
                ),
                success_maturity="shared_behavior_compiled",
            )
        )

    multi_batch_members = {
        tool_id: group.group_id
        for group in groups
        if group.mode == "multi_batch"
        for tool_id in group.ordered_tool_ids
    }
    behavior_definitions: list[WorkDefinition] = []
    for batch_index, tool_ids in enumerate(execution_batches, start=1):
        shared_dependencies = tuple(
            dict.fromkeys(
                shared_coordinates[multi_batch_members[tool_id]]
                for tool_id in tool_ids
                if tool_id in multi_batch_members
            )
        )
        batch_input_slots = architecture_input_slots + (
            (
                ArtifactSlotContract(
                    slot_id="input:shared-tool-semantics-contract",
                    direction="input",
                    artifact_types=("design.shared_tool_semantics_contract",),
                    minimum_count=len(shared_dependencies),
                    maximum_count=len(shared_dependencies),
                    producer_component="design",
                ),
            )
            if shared_dependencies
            else ()
        )
        base = tool_semantics_batch_definition(
            job_id=scope_id,
            group_id="tool-semantics-batches",
            batch_id=f"tool-batch-{batch_index}",
            dependency_coordinates=(
                architecture_coordinate,
                synthesis_coordinate,
                *shared_dependencies,
            ),
            agent_wall_seconds=agent_wall_seconds,
            agent_token_limit=agent_token_limit,
        )
        behavior_definitions.append(
            base.model_copy(
                update={
                    "input_slots": batch_input_slots,
                    "output_slots": (
                        ArtifactSlotContract(
                            slot_id="output:tool-semantics-batch-source",
                            direction="output",
                            artifact_types=("design.tool_semantics_batch_source",),
                            minimum_count=1,
                            maximum_count=1,
                            producer_component="design",
                        ),
                        ArtifactSlotContract(
                            slot_id="output:tool-semantics",
                            direction="output",
                            artifact_types=("design.tool_semantics",),
                            minimum_count=len(tool_ids),
                            maximum_count=len(tool_ids),
                            producer_component="design",
                        ),
                    ),
                }
            )
        )

    behavior_coordinates = tuple(item.coordinate for item in behavior_definitions)
    world_rules = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
        dependency_coordinates=(
            architecture_coordinate,
            synthesis_coordinate,
            *behavior_coordinates,
        ),
        claim_id="design.world_rules.compiles",
        claim="Reset rules and cross-tool invariants compile over the exact committed behavior.",
        timing_reason="Task generation needs an executable, invariant-closed world.",
        output_contract_id="contract:world-rules-source.v3",
        acceptance_transform_id="framework.world-rules-compiler.v4",
        implementation_revision_id=world_rules_implementation_revision(),
        validator_revision_id=world_rules_validator_revision(),
        agent_role="environment_engineer",
        allowed_mutation_roots=("/initial_state_rules", "/invariants"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            *architecture_input_slots,
            ArtifactSlotContract(
                slot_id="input:tool-semantics",
                direction="input",
                artifact_types=("design.tool_semantics",),
                minimum_count=len(declared_tool_ids),
                maximum_count=len(declared_tool_ids),
                producer_component="design",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:world-rules-source",
                direction="output",
                artifact_types=("design.world_rules_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-semantic-source",
                direction="output",
                artifact_types=("design.world_semantic_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="output:world-model",
                direction="output",
                artifact_types=("design.world_model",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="world_rules_compiled",
    )
    curriculum = structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="task_curriculum",
        artifact_slot="task_curriculum",
        dependency_coordinates=(
            synthesis_coordinate,
            architecture_coordinate,
            world_rules.coordinate,
        ),
        claim_id="design.curriculum.compiles",
        claim="Bounded task requirements compile against the exact executable world.",
        timing_reason="Builder and Verifier require one frozen curriculum and task protocol.",
        output_contract_id="contract:task-curriculum-source.v3",
        acceptance_transform_id="framework.training-semantics-compiler.v3",
        implementation_revision_id=legacy_curriculum_implementation_revision(),
        validator_revision_id=legacy_curriculum_validator_revision(),
        agent_role="environment_engineer",
        allowed_mutation_roots=("/curriculum_plan", "/task_requirements"),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=(
            *architecture_input_slots,
            ArtifactSlotContract(
                slot_id="input:world-semantic-source",
                direction="input",
                artifact_types=("design.world_semantic_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
            ArtifactSlotContract(
                slot_id="input:world-model",
                direction="input",
                artifact_types=("design.world_model",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:task-curriculum-source",
                direction="output",
                artifact_types=("design.task_curriculum_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="curriculum_compiled",
    )
    modeling = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
        dependency_coordinates=(
            synthesis_coordinate,
            architecture_coordinate,
            world_rules.coordinate,
            curriculum.coordinate,
        ),
        claim_id="design.modeling.closed",
        claim="The exact world and curriculum compile into a complete EnvironmentDesign closure.",
        timing_reason="Build cannot consume partial semantic sources or unbound task policy.",
        effect="block_integration",
        success_maturity="design_compiled",
        wall_seconds=60.0,
    ).model_copy(
        update={
            "input_slots": (
                *architecture_input_slots,
                ArtifactSlotContract(
                    slot_id="input:world-semantic-source",
                    direction="input",
                    artifact_types=("design.world_semantic_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:world-model",
                    direction="input",
                    artifact_types=("design.world_model",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:task-curriculum-source",
                    direction="input",
                    artifact_types=("design.task_curriculum_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:coverage-map",
                    direction="output",
                    artifact_types=("design.coverage_map",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:world-spec",
                    direction="output",
                    artifact_types=("design.world_spec",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:environment-design",
                    direction="output",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:modeling-gate",
                    direction="output",
                    artifact_types=("control.modeling_gate",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="output:design-baseline",
                    direction="output",
                    artifact_types=("design.baseline_checkpoint",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )
    return (
        (
            *bootstrap_definitions,
            *shared_definitions,
            *behavior_definitions,
            world_rules,
            curriculum,
        ),
        modeling,
    )


def curriculum_plan_work_definition(
    *,
    scope_id: Identifier,
    task_curriculum_template: WorkDefinition,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> WorkDefinition:
    """Replace one historical whole-curriculum turn with a compact plan turn.

    The replacement deliberately retains the historical node's exact input
    closure.  In normal Direct execution that template is freshly derived from
    the frozen Architecture.  A marked diagnostic migration can also supply an
    immutable historical template, preserving every already-committed parent
    definition rather than re-deriving it under newer implementation code.
    """

    template = task_curriculum_template
    if template.coordinate.scope_id != scope_id:
        raise WorkGraphError("CurriculumPlan template scope differs from generation scope")
    if (template.coordinate.component, template.coordinate.stage) != (
        "design",
        "task_curriculum",
    ):
        raise WorkGraphError("CurriculumPlan requires one historical TaskCurriculum template")
    if template.proposal_policy.executor != "agent":
        raise WorkGraphError("CurriculumPlan template must be an Agent proposal boundary")
    if agent_wall_seconds <= 0 or agent_token_limit <= 0:
        raise WorkGraphError("CurriculumPlan Agent budgets must be positive")
    return structured_agent_work_definition(
        scope_id=scope_id,
        component="design",
        stage="curriculum_plan",
        artifact_slot="curriculum_plan",
        dependency_coordinates=template.dependency_coordinates,
        claim_id="design.curriculum_plan.compiles",
        claim=(
            "One compact curriculum plan fixes the exact ordered task-family topology before "
            "any task Rule semantics are authored."
        ),
        timing_reason=(
            "The framework must freeze real TaskRequirement coordinates from a committed plan, "
            "not conceal variable Agent calls in one curriculum transaction."
        ),
        output_contract_id="contract:curriculum-plan-source.v1",
        acceptance_transform_id="framework.curriculum-plan-compiler.v1",
        implementation_revision_id=curriculum_plan_implementation_revision(),
        validator_revision_id=curriculum_plan_validator_revision(),
        agent_role="environment_engineer",
        allowed_mutation_roots=(
            "/coverage_dimensions",
            "/task_plans",
            "/difficulty_dimensions",
            "/generation_seed_space",
            "/minimum_distinct_initial_states",
            "/minimum_distinct_tasks_per_type",
            "/sampling_constraints",
            "/unresolved_questions",
        ),
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
        input_slots=template.input_slots,
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:curriculum-plan-source",
                direction="output",
                artifact_types=("design.curriculum_plan_source",),
                minimum_count=1,
                maximum_count=1,
                producer_component="design",
            ),
        ),
        success_maturity="curriculum_plan_compiled",
    )


def derive_world_plan_definitions(
    *,
    scope_id: Identifier,
    bootstrap_definitions: tuple[WorkDefinition, ...],
    architecture_source_ref: ArtifactRef,
    coupling_plan: ToolCouplingPlan,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkDefinition]:
    """Derive the world-plus-plan epoch without creating task-family calls.

    The existing coupling-plan compiler remains the one authority for physical
    behavior shards.  This wrapper replaces only its historical monolithic
    curriculum Agent definition with a compact CurriculumPlan definition and
    returns the deterministic Modeling template for the later plan-derived
    graph.  The returned graph never contains the old whole-curriculum node.
    """

    legacy_definitions, modeling_template = derive_final_design_definitions(
        scope_id=scope_id,
        bootstrap_definitions=bootstrap_definitions,
        architecture_source_ref=architecture_source_ref,
        coupling_plan=coupling_plan,
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
    )
    legacy_curriculum = tuple(
        item
        for item in legacy_definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "task_curriculum")
    )
    if len(legacy_curriculum) != 1:
        raise WorkGraphError("world-plan derivation requires one historical curriculum template")
    template = legacy_curriculum[0]
    curriculum_plan = curriculum_plan_work_definition(
        scope_id=scope_id,
        task_curriculum_template=template,
        agent_wall_seconds=agent_wall_seconds,
        agent_token_limit=agent_token_limit,
    )
    return (
        tuple(item for item in legacy_definitions if item != template) + (curriculum_plan,),
        modeling_template,
    )


def derive_task_requirement_design_definitions(
    *,
    scope_id: Identifier,
    world_definitions: tuple[WorkDefinition, ...],
    curriculum_plan_ref: ArtifactRef,
    curriculum_plan: CurriculumPlanSourceDraft,
    modeling_template: WorkDefinition,
    agent_wall_seconds: float,
    agent_token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkDefinition]:
    """Freeze one TaskRequirement WorkDefinition per committed plan entry.

    The plan source is already a committed, compiler-validated artifact.  Its
    ordered ``task_plans`` are the only fan-out input; code does not invent a
    task type, output, or hidden iteration.  The returned TaskCurriculum node
    is deterministic and retains the old downstream artifact boundary.
    """

    if agent_wall_seconds <= 0 or agent_token_limit <= 0:
        raise WorkGraphError("task requirement Agent budgets must be positive")
    if curriculum_plan_ref.artifact_type != "design.curriculum_plan_source":
        raise WorkGraphError(
            "task requirement derivation requires a CurriculumPlan source Artifact"
        )
    if not world_definitions:
        raise WorkGraphError("task requirement derivation requires a committed world graph")
    if any(item.coordinate.scope_id != scope_id for item in world_definitions):
        raise WorkGraphError("world definitions mix a different generation scope")
    if modeling_template.coordinate.scope_id != scope_id:
        raise WorkGraphError("Modeling template scope differs from generation scope")
    planners = tuple(
        item
        for item in world_definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "curriculum_plan")
    )
    world_rules = tuple(
        item
        for item in world_definitions
        if (item.coordinate.component, item.coordinate.stage) == ("design", "world_rules")
    )
    if len(planners) != 1 or len(world_rules) != 1:
        raise WorkGraphError(
            "task requirement derivation requires one WorldRules and CurriculumPlan"
        )
    planner = planners[0]
    task_types = tuple(item.task_type for item in curriculum_plan.task_plans)
    if not task_types or len(set(task_types)) != len(task_types):
        raise WorkGraphError("committed CurriculumPlan does not have unique non-empty task types")
    required_dependencies = (*planner.dependency_coordinates, planner.coordinate)
    plan_input = ArtifactSlotContract(
        slot_id="input:curriculum-plan-source",
        direction="input",
        artifact_types=("design.curriculum_plan_source",),
        minimum_count=1,
        maximum_count=1,
        producer_component="design",
    )
    task_definitions = tuple(
        structured_agent_work_definition(
            scope_id=scope_id,
            component="design",
            stage="task_requirement",
            artifact_slot="task_requirement_source",
            group_id="task-requirements",
            shard_id=task_type,
            dependency_coordinates=required_dependencies,
            claim_id="design.task_requirement.compiles",
            claim=(
                "One plan-derived task family compiles executable initial, success, failure and "
                "terminal Rule semantics against the exact frozen world."
            ),
            timing_reason=(
                "Each task family needs independent provenance, feedback, repair and budget "
                "accounting before deterministic curriculum closure."
            ),
            output_contract_id="contract:task-requirement-source.v1",
            acceptance_transform_id="framework.task-requirement-compiler.v1",
            implementation_revision_id=task_requirement_implementation_revision(),
            validator_revision_id=task_requirement_validator_revision(),
            agent_role="environment_engineer",
            allowed_mutation_roots=(
                "/task_type",
                "/objective",
                "/allowed_actor_ids",
                "/required_tool_ids",
                "/initial_state_constraints",
                "/success_conditions",
                "/failure_conditions",
                "/terminal_conditions",
                "/difficulty_dimensions",
                "/minimum_tool_calls",
            ),
            agent_wall_seconds=agent_wall_seconds,
            agent_token_limit=agent_token_limit,
            input_slots=(*planner.input_slots, plan_input),
            output_slots=(
                ArtifactSlotContract(
                    slot_id="output:task-requirement-source",
                    direction="output",
                    artifact_types=("design.task_requirement_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            success_maturity="task_requirement_compiled",
        )
        for task_type in task_types
    )
    curriculum = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="design",
        stage="task_curriculum",
        artifact_slot="task_curriculum",
        dependency_coordinates=(
            *required_dependencies,
            *(item.coordinate for item in task_definitions),
        ),
        claim_id="design.curriculum.compiles",
        claim=(
            "The exact committed CurriculumPlan and every ordered TaskRequirement source compile "
            "into one complete task curriculum."
        ),
        timing_reason="Builder and Verifier require one closed curriculum and task protocol.",
        effect="block_compile",
        success_maturity="curriculum_compiled",
        wall_seconds=60.0,
    ).model_copy(
        update={
            "input_slots": (
                *planner.input_slots,
                plan_input,
                ArtifactSlotContract(
                    slot_id="input:task-requirement-source",
                    direction="input",
                    artifact_types=("design.task_requirement_source",),
                    minimum_count=len(task_definitions),
                    maximum_count=len(task_definitions),
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:task-curriculum-source",
                    direction="output",
                    artifact_types=("design.task_curriculum_source",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
        }
    )
    template_curriculum = tuple(
        item
        for item in modeling_template.dependency_coordinates
        if item.component == "design" and item.stage == "task_curriculum"
    )
    if len(template_curriculum) != 1:
        raise WorkGraphError("Modeling template must retain one TaskCurriculum boundary")
    expected_template_dependencies = (
        *planner.dependency_coordinates,
        template_curriculum[0],
    )
    if modeling_template.dependency_coordinates != expected_template_dependencies:
        raise WorkGraphError("Modeling template does not retain the expected curriculum boundary")
    modeling = modeling_template.model_copy(
        update={
            "dependency_coordinates": (*planner.dependency_coordinates, curriculum.coordinate),
        }
    )
    return (*world_definitions, *task_definitions, curriculum), modeling


def _verifier_intent_group(
    *,
    scope_id: Identifier,
    verifier_plan_coordinate: WorkCoordinate,
    batch_count: int,
    wall_seconds: float,
    token_limit: int,
) -> tuple[tuple[WorkDefinition, ...], WorkGroupDefinition, WorkDefinition]:
    """Freeze each real Challenger turn before code aggregates the final IR.

    Verifier task batches are not an implementation detail of one nominal Agent
    node: each has its own retry budget, invocation accounting and WorkCommit.
    The aggregate coordinate remains ``verifier_intent`` so the release dossier
    binds one complete, framework-merged Verifier IR rather than a partial shard.
    """

    group_id = "verifier-intent-batches"
    per_batch_wall = wall_seconds / batch_count
    per_batch_tokens = token_limit // batch_count
    if per_batch_wall <= 0 or per_batch_tokens < 1:
        raise WorkGraphError("Verifier batch budget cannot be split into real Agent turns")
    batches: list[WorkDefinition] = []
    for index in range(batch_count):
        coordinate = WorkCoordinate(
            scope_id=scope_id,
            component="verifier",
            stage="verifier_intent_batch",
            artifact_slot="verifier_intent_checkpoint",
            group_id=group_id,
            shard_id=f"batch-{index + 1}",
        )
        digest = _stable_work_identity_digest(coordinate)
        batches.append(
            WorkDefinition(
                work_id=f"work:verifier-intent-batch:{digest}",
                coordinate=coordinate,
                claim=(
                    "One bounded Challenger batch compiles adversarial verifier intent for its "
                    "exact frozen task partition."
                ),
                timing_reason=(
                    "The final Verifier IR may include only individually validated task-batch "
                    "intent commitments."
                ),
                dependency_coordinates=(verifier_plan_coordinate,),
                input_slots=(
                    ArtifactSlotContract(
                        slot_id="input:verifier-batch-plan",
                        direction="input",
                        artifact_types=("judge.verifier_batch_plan",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                        confidentiality="framework_private",
                    ),
                ),
                output_slots=(
                    ArtifactSlotContract(
                        slot_id="output:verifier-intent-checkpoint",
                        direction="output",
                        artifact_types=("judge.verifier_intent_checkpoint",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                    ),
                    ArtifactSlotContract(
                        slot_id="output:verifier-batch-draft",
                        direction="output",
                        artifact_types=("judge.verifier_batch_draft",),
                        minimum_count=1,
                        maximum_count=1,
                        producer_component="verifier",
                        confidentiality="sealed",
                    ),
                ),
                proposal_policy=ProposalPolicy(
                    policy_id=f"proposal:verifier-intent-batch:{digest}",
                    executor="agent",
                    operation="verifier.compile_intent_batch",
                    budget=OperationBudget(
                        wall_seconds=per_batch_wall,
                        llm_tokens=per_batch_tokens,
                        agent_turns=1,
                    ),
                    agent_role="challenger",
                    capability_profile_id="profile:challenger",
                    output_contract_id="contract:verifier-intent-batch.v3",
                    implementation_revision_id=verifier_intent_batch_implementation_revision(),
                ),
                validation_policy=ValidationPolicy(
                    policy_id=f"validation:verifier-intent-batch:{digest}",
                    validator_id="validator:verifier-intent-batch",
                    validator_revision_id=verifier_intent_batch_validator_revision(),
                    validation_phase="verifier_intent_batch",
                    frontier_ordinal=100,
                    claim_id="verifier.intent.batch.valid",
                    effect="block_release",
                    budget=OperationBudget(wall_seconds=min(120.0, per_batch_wall)),
                ),
                repair_policy=RepairPolicy(
                    policy_id=f"repair:verifier-intent-batch:{digest}",
                    policy_revision_id="framework.repair-authority.v2",
                    maximum_local_corrections=1,
                    strict_progress_bonus_corrections=1,
                    maximum_infrastructure_retries=1,
                    maximum_model_fallbacks=1,
                    maximum_process_recoveries=1,
                    maximum_total_repair_attempts=5,
                ),
                required_claim_id="verifier.intent.batch.valid",
                allowed_mutation_roots=("/cases", "/properties", "/coverage"),
                success_maturity="verifier_batch_compiled",
            )
        )
    aggregate_coordinate = WorkCoordinate(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_bundle",
        group_id=group_id,
    )
    aggregate = _code_component_definition(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_bundle",
        dependencies=tuple(item.coordinate for item in batches),
        claim_id="verifier.intent.valid",
        claim=(
            "Exact validated Verifier batches aggregate to one framework-owned public "
            "and sealed IR."
        ),
        timing_reason=(
            "Release assurance requires a complete independently compiled verifier closure."
        ),
        effect="block_release",
        success_maturity="verifier_compiled",
        output_types=("judge.verifier_ir_projection",),
    ).model_copy(
        update={
            "coordinate": aggregate_coordinate,
            "work_id": (
                f"work:verifier-intent:{_stable_work_identity_digest(aggregate_coordinate)}"
            ),
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:verifier-batch-draft",
                    direction="input",
                    artifact_types=("judge.verifier_batch_draft",),
                    minimum_count=batch_count,
                    maximum_count=batch_count,
                    producer_component="verifier",
                    confidentiality="sealed",
                ),
            ),
        }
    )
    group = WorkGroupDefinition(
        group_id=group_id,
        scope_id=scope_id,
        member_coordinates=tuple(item.coordinate for item in batches),
        aggregate_coordinate=aggregate_coordinate,
    )
    return tuple(batches), group, aggregate


def verifier_plan_work_definition(
    *,
    scope_id: Identifier,
    modeling_coordinate: WorkCoordinate,
) -> WorkDefinition:
    """Materialize the exact deterministic task partition before any Challenger turn.

    The final graph has to know how many physical batches exist, but the per-batch
    task/rule/property scope must also survive process recovery.  This small code
    boundary writes that framework-private plan from the frozen EnvironmentDesign;
    batch Agents may read it but cannot redefine it.
    """

    definition = _code_component_definition(
        scope_id=scope_id,
        component="verifier",
        stage="verifier_plan",
        artifact_slot="verifier_batch_plan",
        dependencies=(modeling_coordinate,),
        claim_id="verifier.plan.frozen",
        claim=(
            "The exact task, Rule, property and case-quota partition is frozen before any "
            "Challenger invocation."
        ),
        timing_reason=(
            "Physical Challenger batches need immutable semantic scope for provenance, "
            "local repair and restart."
        ),
        effect="block_release",
        success_maturity="verifier_plan_frozen",
        output_types=("judge.verifier_batch_plan",),
    )
    return definition.model_copy(
        update={
            "proposal_policy": definition.proposal_policy.model_copy(
                update={"implementation_revision_id": verifier_plan_implementation_revision()}
            ),
            "validation_policy": definition.validation_policy.model_copy(
                update={"validator_revision_id": verifier_plan_validator_revision()}
            ),
            "input_slots": (
                ArtifactSlotContract(
                    slot_id="input:environment-design",
                    direction="input",
                    artifact_types=("design.environment_design",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
                ArtifactSlotContract(
                    slot_id="input:world-spec",
                    direction="input",
                    artifact_types=("design.world_spec",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="design",
                ),
            ),
            "output_slots": (
                ArtifactSlotContract(
                    slot_id="output:verifier-batch-plan",
                    direction="output",
                    artifact_types=("judge.verifier_batch_plan",),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component="verifier",
                    confidentiality="framework_private",
                ),
            ),
        }
    )


def _agent_component_definition(
    *,
    scope_id: Identifier,
    component: Literal["build", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    role: Literal["environment_engineer", "challenger"],
    operation: Identifier,
    output_contract_id: Identifier,
    implementation_revision_id: Identifier = "framework.impl.unversioned.v0",
    validator_revision_id: Identifier | None = None,
    validation_effect: Literal["block_integration", "block_release"],
    success_maturity: Identifier,
    wall_seconds: float,
    token_limit: int,
    allowed_mutation_roots: tuple[str, ...],
    output_types: tuple[Identifier, ...],
    input_slots: tuple[ArtifactSlotContract, ...] = (),
    assurance: AssurancePolicy | None = None,
    session_token_limit: int | None = None,
    session_wall_seconds: float | None = None,
    maximum_session_continuations: int = 0,
    repair_targets: tuple[WorkCoordinate, ...] = (),
) -> WorkDefinition:
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    is_candidate_build = component == "build" and stage == "candidate_build"
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependencies,
        repair_target_coordinates=repair_targets,
        input_slots=input_slots,
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component=component,
            )
            for artifact_type in output_types
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="agent",
            implementation_revision_id=implementation_revision_id,
            operation=operation,
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                # EnvironmentBuilder owns a real candidate workspace and
                # explicitly refuses a zero build-time lease. The read-only
                # implementation-plan boundary and Challenger batches do not
                # consume that dimension.
                build_seconds=(wall_seconds if is_candidate_build else 0),
                llm_tokens=token_limit,
                # CandidateBuild is a Code Agent, not a one-shot text
                # emitter.  Reserve one same-workspace pre-commit correction
                # after its real local/framework validation.  This is part of
                # the original proposal's development cycle; Scheduler
                # semantic repairs remain a separate, explicitly charged
                # policy path.
                agent_turns=CANDIDATE_BUILD_DEVELOPMENT_AGENT_TURNS if is_candidate_build else 1,
            ),
            session_token_limit=session_token_limit,
            session_wall_seconds=session_wall_seconds,
            agent_role=role,
            capability_profile_id=f"profile:{role.replace('_', '-')}",
            output_contract_id=output_contract_id,
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=(validator_revision_id or f"framework.validator.{stage}.v1"),
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=validation_effect,
            budget=OperationBudget(wall_seconds=min(120.0, wall_seconds), process_calls=2),
        ),
        assurance_policy=assurance,
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_model_fallbacks=1,
            maximum_session_continuations=maximum_session_continuations,
            maximum_process_recoveries=1,
            maximum_total_repair_attempts=5,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def _assured_code_definition(
    *,
    scope_id: Identifier,
    component: Literal["integration", "judge"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    repair_targets: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_release"],
    success_maturity: Identifier,
    wall_seconds: float,
    probe_ids: tuple[Identifier, ...],
    output_types: tuple[Identifier, ...],
    allowed_mutation_roots: tuple[str, ...],
    implementation_revision_id: Identifier,
    validator_revision_id: Identifier,
    proposal_budget_requirements: JudgeOperationBudgetRequirements | None = None,
    input_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    coordinate = WorkCoordinate(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
    )
    digest = _stable_work_identity_digest(coordinate)
    return WorkDefinition(
        work_id=f"work:{stage}:{digest}",
        coordinate=coordinate,
        claim=claim,
        timing_reason=timing_reason,
        dependency_coordinates=dependencies,
        repair_target_coordinates=repair_targets,
        input_slots=input_slots,
        output_slots=tuple(
            ArtifactSlotContract(
                slot_id=f"output:{artifact_type}",
                direction="output",
                artifact_types=(artifact_type,),
                minimum_count=1,
                maximum_count=1,
                producer_component=component,
            )
            for artifact_type in output_types
        ),
        proposal_policy=ProposalPolicy(
            policy_id=f"proposal:{stage}:{digest}",
            executor="code",
            # The code proposal is the single real isolated execution (clean
            # build/runtime/Judge), not a cheap preflight that later repeats
            # the same probe under a second control operation.  Validation
            # only maps that immutable report to the declared Claim.
            operation=f"{component}.{stage}.execute",
            implementation_revision_id=implementation_revision_id,
            budget=OperationBudget(
                wall_seconds=wall_seconds,
                llm_tokens=(
                    proposal_budget_requirements.llm_tokens
                    if proposal_budget_requirements is not None
                    else 0
                ),
                agent_turns=(
                    proposal_budget_requirements.agent_turns
                    if proposal_budget_requirements is not None
                    else 0
                ),
                tool_calls=(
                    proposal_budget_requirements.tool_calls
                    if proposal_budget_requirements is not None
                    else max(16, len(probe_ids) * 8)
                ),
                process_calls=max(1, len(probe_ids) * 2),
                build_seconds=wall_seconds,
                evaluation_episodes=(
                    proposal_budget_requirements.evaluation_episodes
                    if proposal_budget_requirements is not None
                    else max(64, len(probe_ids) * 16)
                ),
                container_seconds=wall_seconds,
            ),
        ),
        validation_policy=ValidationPolicy(
            policy_id=f"validation:{stage}:{digest}",
            validator_id=f"validator:{stage}",
            validator_revision_id=validator_revision_id,
            validation_phase=stage,
            frontier_ordinal=100,
            claim_id=claim_id,
            effect=effect,
            budget=OperationBudget(wall_seconds=min(60.0, wall_seconds), process_calls=1),
        ),
        repair_policy=RepairPolicy(
            policy_id=f"repair:{stage}:{digest}",
            policy_revision_id="framework.repair-authority.v2",
            # These are diagnostic code leaves.  They cannot edit Candidate or
            # Verifier bytes; semantic failure is routed by Scheduler to the
            # declared causal target.  Only transport/infrastructure recovery
            # may re-run this exact physical probe locally.
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=1,
            maximum_model_fallbacks=0,
            maximum_process_recoveries=1,
            maximum_automatic_backjump=1,
            maximum_total_repair_attempts=2,
        ),
        required_claim_id=claim_id,
        allowed_mutation_roots=allowed_mutation_roots,
        success_maturity=success_maturity,
    )


def _code_component_definition(
    *,
    scope_id: Identifier,
    component: Literal["release", "registry", "verifier"],
    stage: Identifier,
    artifact_slot: Identifier,
    dependencies: tuple[WorkCoordinate, ...],
    claim_id: Identifier,
    claim: str,
    timing_reason: str,
    effect: Literal["block_release"],
    success_maturity: Identifier,
    output_types: tuple[Identifier, ...],
    input_slots: tuple[ArtifactSlotContract, ...] = (),
) -> WorkDefinition:
    definition = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component=component,
        stage=stage,
        artifact_slot=artifact_slot,
        dependency_coordinates=dependencies,
        claim_id=claim_id,
        claim=claim,
        timing_reason=timing_reason,
        effect=effect,
        success_maturity=success_maturity,
        wall_seconds=120.0,
    )
    return definition.model_copy(
        update={
            "input_slots": input_slots,
            "output_slots": tuple(
                ArtifactSlotContract(
                    slot_id=f"output:{artifact_type}",
                    direction="output",
                    artifact_types=(artifact_type,),
                    minimum_count=1,
                    maximum_count=1,
                    producer_component=component,
                )
                for artifact_type in output_types
            ),
        }
    )


__all__ = [
    "GenerationWorkGraph",
    "JoinPolicy",
    "ResolvedWorkInputs",
    "WorkGraphGroupBinding",
    "WorkGraphManifest",
    "WorkGraphMilestone",
    "WorkGraphMilestoneBinding",
    "WorkGraphNodeBinding",
    "WorkGraphError",
    "WorkGraphEpoch",
    "WorkGroupDefinition",
    "bind_model_route_recovery_policy",
    "compile_design_work_graph",
    "compile_world_work_graph",
    "complete_generation_work_graph",
    "curriculum_plan_work_definition",
    "derive_final_design_definitions",
    "derive_task_requirement_design_definitions",
    "derive_world_plan_definitions",
    "deterministic_boundary_work_definition",
    "research_acquisition_work_definition",
    "research_plan_work_definition",
    "research_synthesis_work_definition",
    "structured_agent_work_definition",
    "tool_semantics_batch_definition",
    "verifier_plan_work_definition",
    "world_architecture_work_definition",
]

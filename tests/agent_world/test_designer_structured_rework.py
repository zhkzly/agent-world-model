from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    Claim,
    DesignPhaseCheckpoint,
    EnvironmentJob,
    EnvironmentRequest,
    Evidence,
    EvidenceGraph,
    KeyValue,
    PermissionScope,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.control import StructuredRepairMode
from agent_world.control.feedback import RepairTargetRef
from agent_world.control.validation import (
    SafeValidationIssue,
    StructuredValidationError,
    ValidationDiagnostic,
)
from agent_world.designer.budget import DesignerInvocationBudget
from agent_world.designer.models import (
    EvidenceSynthesis,
    ObservationSemanticsSourceDraft,
    PermissionRuleSourceDraft,
    RuleArithmeticDraft,
    RuleConstantDraft,
    RuleDraft,
    RuleReferenceDraft,
    SchemaArrayNodeDraft,
    SchemaIntegerNodeDraft,
    SchemaNullNodeDraft,
    SchemaNumberNodeDraft,
    SchemaObjectNodeDraft,
    SchemaPropertyDraft,
    SchemaStringNodeDraft,
    SchemaUnionNodeDraft,
    StateEntityPlan,
    StateEntitySchemaIRDraft,
    ToolAccessObservationSourceDraft,
    ToolConditionsSourceDraft,
)
from agent_world.designer.service import (
    _DESIGN_REPAIR_AUTHORITY,
    _DESIGN_RESEARCH_USAGE,
    AgentProfileProvider,
    DesignerError,
    EnvironmentDesigner,
    RootSectionRepairProjection,
    ToolSemanticsRepairProjection,
    _gather_independent,
)
from agent_world.designer.validation import (
    StructuredSemanticError,
    StructuredSemanticIssue,
)
from agent_world.invocation import (
    InvocationBackend,
    InvocationError,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    ResolvedAgentProfile,
    TokenBreakdown,
)
from agent_world.invocation.authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    register_agent_output_contract,
)
from agent_world.research import ResearchToolchain


class _Output(SemanticAdvisoryOutput, BaseModel):
    value: str


class _SectionOutput(SemanticAdvisoryOutput, BaseModel):
    state: str
    tools: str


class _ToolParts(BaseModel):
    conditions: str
    access_observation: str


class _ToolBatchOutput(SemanticAdvisoryOutput, BaseModel):
    tools: tuple[_ToolParts, ...]


register_agent_output_contract(
    _Output,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)
register_agent_output_contract(
    _ToolBatchOutput,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


def test_rule_source_rejects_ordering_type_mismatch_at_clause_path() -> None:
    rule = RuleDraft.model_validate(
        {
                "rule_id": "rule:hotel.search:result_count",
                "family": "transition",
                "description": "Result count is non-negative.",
                "boolean_operator": "all",
                "clauses": [
                    {
                        "clause_id": "result_count_nonnegative",
                        "operator": "greater_or_equal",
                        "ordering": "number",
                        "left": {
                            "kind": "reference",
                            "source": "post_state",
                            "pointer": "/offers",
                            "value_type": "array",
                        },
                        "right": {
                            "kind": "constant",
                            "value_type": "number",
                            "value": 0,
                        },
                    }
                ],
                "case_sensitivity": "positive_only",
                "evidence_claim_ids": [],
        }
    )

    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_rule_source_draft(rule)

    assert captured.value.issues[0].code == "rule_ordering_type_mismatch"
    assert captured.value.issues[0].location == ("clauses", 0)


def test_rule_source_rejects_non_numeric_arithmetic_and_zero_divisor() -> None:
    def rule_with(term: RuleArithmeticDraft) -> RuleDraft:
        return RuleDraft.model_validate(
            {
                "rule_id": "rule:arithmetic",
                "family": "transition",
                "description": "Validate an arithmetic term.",
                "boolean_operator": "all",
                "clauses": [
                    {
                        "clause_id": "arithmetic_equal",
                        "operator": "equal",
                        "left": term.model_dump(mode="json"),
                        "right": {
                            "kind": "constant",
                            "value_type": "number",
                            "value": 1,
                        },
                    }
                ],
                "case_sensitivity": "positive_only",
                "evidence_claim_ids": [],
            }
        )

    non_numeric = RuleArithmeticDraft(
        kind="arithmetic",
        operator="add",
        left=RuleReferenceDraft(
            kind="reference",
            source="args",
            pointer="/name",
            value_type="string",
        ),
        right=RuleConstantDraft(kind="constant", value_type="number", value=1),
    )
    zero_divisor = RuleArithmeticDraft(
        kind="arithmetic",
        operator="divide",
        left=RuleConstantDraft(kind="constant", value_type="number", value=1),
        right=RuleConstantDraft(kind="constant", value_type="number", value=0),
    )

    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_rule_source_draft(rule_with(non_numeric))
    assert "rule_arithmetic_operand_type" in {issue.code for issue in captured.value.issues}
    with pytest.raises(StructuredSemanticError) as captured:
        EnvironmentDesigner._validate_rule_source_draft(rule_with(zero_divisor))
    assert "rule_arithmetic_zero_divisor" in {issue.code for issue in captured.value.issues}


def test_rule_compiler_preserves_live_relative_pointer_paths_and_expectations() -> None:
    source = ToolConditionsSourceDraft.model_validate(
        {
            "tool_id": "hotel.booking.get",
            "preconditions": [
                {
                    "rule_id": "rule:hotel.booking.get:exists",
                    "family": "precondition",
                    "description": "The booking exists.",
                    "boolean_operator": "all",
                    "clauses": [
                        {
                            "clause_id": "booking_exists",
                            "operator": "exists",
                            "left": {
                                "kind": "reference",
                                "source": "pre_state",
                                "pointer": "bookings/booking_id",
                                "value_type": "string",
                            },
                            "negate": False,
                        }
                    ],
                    "case_sensitivity": "positive_only",
                    "evidence_claim_ids": [],
                }
            ],
        }
    )

    with pytest.raises(StructuredValidationError) as captured:
        EnvironmentDesigner._compile_tool_conditions_source(source)

    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "rule_pointer_not_absolute"
    assert issue.location[:2] == ("preconditions", 0)
    assert "clauses" in issue.location
    assert "left" in issue.location
    assert issue.retryable
    assert issue.violated_condition == "closed schema constraint rule_pointer_not_absolute"
    assert issue.expected_category == "an empty or absolute RFC 6901 pointer"


register_agent_output_contract(
    _SectionOutput,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


class _RecordingBackend:
    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        value = "invalid" if len(self.requests) == 1 else "valid"
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=f"turn-{len(self.requests)}",
            final_text=None,
            structured_output={"value": value},
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=10)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


class _SequenceBackend:
    def __init__(self, outputs: tuple[dict[str, object], ...]) -> None:
        self.outputs = outputs
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        output = self.outputs[len(self.requests) - 1]
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=f"turn-{len(self.requests)}",
            final_text=None,
            structured_output=cast(Any, output),
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=10)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


class _RecordingRepairAuthority:
    def __init__(self) -> None:
        self.authorizations: list[dict[str, object]] = []
        self.completions: list[tuple[str, tuple[str, ...], bool]] = []
        self.completion_diagnostics: list[ValidationDiagnostic | None] = []

    async def authorize(self, **kwargs: object) -> str:
        self.authorizations.append(dict(kwargs))
        return f"repair-entry:{len(self.authorizations)}"

    async def complete(
        self,
        entry_id: str,
        *,
        remaining_issue_codes: tuple[str, ...],
        continued_session: bool,
        remaining_diagnostic: ValidationDiagnostic | None = None,
    ) -> None:
        self.completions.append((entry_id, remaining_issue_codes, continued_session))
        self.completion_diagnostics.append(remaining_diagnostic)


class _ProfileProvider:
    def resolve(self, **_: object) -> ResolvedAgentProfile:
        # The recording backend deliberately does not inspect provider-specific
        # profile material. The production InvocationBackend still receives a
        # fully resolved profile through this exact interface.
        return cast(ResolvedAgentProfile, object())


@pytest.mark.asyncio
async def test_independent_gather_preserves_successful_sibling_before_leaf_error() -> None:
    settled: list[str] = []

    async def success() -> str:
        await asyncio.sleep(0.01)
        settled.append("committed")
        return "ok"

    async def failure() -> str:
        await asyncio.sleep(0)
        raise RuntimeError("leaf failure")

    with pytest.raises(RuntimeError, match="leaf failure"):
        await _gather_independent(success(), failure())

    assert settled == ["committed"]


class _InvalidTransportBackend:
    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        output = (
            {"artifact_json": "{TOP_SECRET_REJECTED"}
            if len(self.requests) == 1
            else {"value": "valid"}
        )
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=f"turn-{len(self.requests)}",
            final_text=None,
            structured_output=output,
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=10)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


class _TransportShapeSequenceBackend:
    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        outputs: tuple[dict[str, object], ...] = (
            {"artifact_json": "{TOP_SECRET_REJECTED"},
            {"wrong_field": "still rejected"},
            {"value": "valid"},
        )
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=f"turn-{len(self.requests)}",
            final_text=None,
            structured_output=cast(Any, outputs[len(self.requests) - 1]),
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=10)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


class _RetryableBackend:
    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        if len(self.requests) == 1:
            return InvocationResult(
                invocation_id=request.invocation_id,
                status=InvocationStatus.FAILED,
                session=None,
                turn_id="turn-network-failed",
                final_text=None,
                structured_output=None,
                usage=InvocationUsage(turn=TokenBreakdown(total_tokens=0)),
                events=(),
                error=InvocationError(
                    code="turn_failed",
                    message="transient provider transport failure",
                    retryable=True,
                ),
                duration_ms=1,
            )
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id="turn-retry-completed",
            final_text=None,
            structured_output={"value": "valid"},
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=10)),
            events=(),
            error=None,
            duration_ms=1,
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_untyped_semantic_error_never_spends_a_repair_turn(
    tmp_path: Path,
) -> None:
    backend = _RecordingBackend()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )

    def require_valid(output: _Output) -> None:
        if output.value != "valid":
            raise ValueError("value must equal valid")

    with pytest.raises(DesignerError) as captured:
        await designer.run_structured_agent(
            role="environment-engineer",
            lineage_id="lineage:test",
            workspace=tmp_path,
            model=_Output,
            prompt="Create the complete artifact from immutable input.",
            permissions=PermissionScope(),
            budget=DesignerInvocationBudget(
                Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=30)
            ),
            semantic_validator=require_valid,
        )

    assert captured.value.stage == "agent.environment-engineer.framework_diagnostic"
    assert captured.value.validation_issues == (
        "framework_diagnostic_incomplete@semantic_output",
    )
    assert len(captured.value.results) == 1
    assert len(backend.requests) == 1
    assert backend.requests[0].metadata["repair_mode"] == "initial"


@pytest.mark.asyncio
async def test_section_scoped_correction_freezes_unrelated_valid_roots(
    tmp_path: Path,
) -> None:
    backend = _SequenceBackend(
        (
            {"state": "valid", "tools": "invalid"},
            # A full rewrite fixes tools but regresses state.  Code must accept
            # only the diagnostic-authorized tools root.
            {"state": "regressed", "tools": "valid"},
        )
    )
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="section_test",
        frontier_ordinal=10,
        issues=(
            SafeValidationIssue(
                "tools_invalid",
                ("tools",),
                "The tools section must be valid.",
            ),
        ),
    )

    def validate(output: _SectionOutput) -> None:
        if output.tools != "valid":
            raise StructuredValidationError(diagnostic)
        if output.state != "valid":
            raise AssertionError("an unrelated root regression reached semantic validation")

    output, results = await designer.run_structured_agent(
        role="environment-engineer",
        lineage_id="lineage:section-projection",
        workspace=tmp_path,
        model=_SectionOutput,
        prompt="Create a two-section artifact.",
        permissions=PermissionScope(),
        budget=DesignerInvocationBudget(
            Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=30)
        ),
        semantic_validator=validate,
        repair_projection=RootSectionRepairProjection(
            allowed_roots=frozenset({"state", "tools"}),
            resolve_roots=lambda _diagnostic: ("tools",),
        ),
        feedback_contract_id="feedback.test.section_projection",
        repair_target=RepairTargetRef(
            target_id="repair:section-projection",
            component="design",
            artifact_slot="section_output",
            lineage_id="lineage:section-projection",
            allowed_mutation_paths=("/state", "/tools"),
        ),
    )

    assert output == _SectionOutput(state="valid", tools="valid")
    assert len(results) == 2
    assert "('tools',)" in backend.requests[1].prompt


@pytest.mark.asyncio
async def test_tool_subcomponent_correction_freezes_other_tools_and_sections(
    tmp_path: Path,
) -> None:
    backend = _SequenceBackend(
        (
            {
                "tools": [
                    {"conditions": "stable-0", "access_observation": "invalid"},
                    {"conditions": "stable-1", "access_observation": "stable-1"},
                ]
            },
            {
                "tools": [
                    {"conditions": "regressed-0", "access_observation": "valid"},
                    {"conditions": "regressed-1", "access_observation": "regressed-1"},
                ]
            },
        )
    )
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="tool_semantics_batch_preflight",
        frontier_ordinal=30,
        issues=(
            SafeValidationIssue(
                "observation_field_unknown",
                ("tools", 0, "access_observation", "observation"),
                "Use only frozen observation fields.",
            ),
        ),
    )

    def validate(output: _ToolBatchOutput) -> None:
        if output.tools[0].access_observation != "valid":
            raise StructuredValidationError(diagnostic)
        assert output.tools[0].conditions == "stable-0"
        assert output.tools[1] == _ToolParts(
            conditions="stable-1",
            access_observation="stable-1",
        )

    output, _results = await designer.run_structured_agent(
        role="environment-engineer",
        lineage_id="lineage:tool-section-projection",
        workspace=tmp_path,
        model=_ToolBatchOutput,
        prompt="Create a tool batch.",
        permissions=PermissionScope(),
        budget=DesignerInvocationBudget(
            Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=30)
        ),
        semantic_validator=validate,
        repair_projection=ToolSemanticsRepairProjection(),
        feedback_contract_id="feedback.test.tool_section_projection",
        repair_target=RepairTargetRef(
            target_id="repair:tool-section-projection",
            component="design",
            artifact_slot="tool_batch_output",
            lineage_id="lineage:tool-section-projection",
            allowed_mutation_paths=("/tools",),
        ),
    )

    assert output.tools[0] == _ToolParts(
        conditions="stable-0",
        access_observation="valid",
    )
    assert "tools/0/access_observation" in backend.requests[1].prompt


def test_observation_source_derives_redacted_complement() -> None:
    source = ToolAccessObservationSourceDraft(
        tool_id="hotel.search",
        permission=PermissionRuleSourceDraft(
            permission_id="permission:hotel.search",
            allowed_actors=("traveler", "auditor"),
            required_scopes_by_actor={"traveler": (), "auditor": ()},
            denied_observation="Caller is not permitted.",
        ),
        observation=ObservationSemanticsSourceDraft(
            visible_fields_by_actor={
                "traveler": ("public_result",),
                "auditor": ("public_result", "audit_trace"),
            },
            consistency="strong",
            staleness_bound_seconds=0,
        ),
    )

    compiled = EnvironmentDesigner._compile_tool_access_observation_source(
        source,
        observation_fields=("public_result", "audit_trace"),
    )

    assert compiled.observation.redacted_fields_by_actor == {
        "traveler": ("audit_trace",),
        "auditor": (),
    }


@pytest.mark.asyncio
async def test_structured_correction_uses_one_shared_repair_authority(
    tmp_path: Path,
) -> None:
    backend = _RecordingBackend()
    authority = _RecordingRepairAuthority()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="typed_value_semantics",
        frontier_ordinal=20,
        issues=(
            SafeValidationIssue(
                "output_value_invalid",
                ("value",),
                "The value must satisfy the frozen semantic category.",
                violated_condition="value is outside the frozen semantic category",
                expected_category="the literal valid",
            ),
        ),
    )

    def require_valid(output: _Output) -> None:
        if output.value != "valid":
            raise StructuredValidationError(diagnostic)

    token = _DESIGN_REPAIR_AUTHORITY.set(authority)
    try:
        output, _results = await designer.run_structured_agent(
            role="environment-engineer",
            lineage_id="lineage:authorized-repair",
            workspace=tmp_path,
            model=_Output,
            prompt="Create a typed artifact.",
            permissions=PermissionScope(),
            budget=DesignerInvocationBudget(
                Budget(
                    llm_tokens=1_000,
                    agent_turns=2,
                    repair_attempts=1,
                    wall_seconds=30,
                )
            ),
            semantic_validator=require_valid,
        )
    finally:
        _DESIGN_REPAIR_AUTHORITY.reset(token)

    assert output.value == "valid"
    assert len(authority.authorizations) == 1
    authorization = authority.authorizations[0]
    assert authorization == {
        "owner_node": "design",
        "lineage_id": "lineage:authorized-repair",
        "role": "environment-engineer",
        "repair_mode": StructuredRepairMode.CONTRACT_CORRECTION,
        "issue_codes": ("output_value_invalid@value",),
        "continued_session": False,
        "diagnostic": diagnostic,
    }
    assert authority.completions == [("repair-entry:1", (), False)]


def test_known_tool_identity_drift_is_typed_and_unknown_value_error_is_not_retryable() -> None:
    known = EnvironmentDesigner._typed_value_error_issues(
        ValueError("tool reliability must target hotel.search, got hotel.reserve"),
        prefix=("tools", 0, "reliability"),
    )
    unknown = EnvironmentDesigner._typed_value_error_issues(
        ValueError("new validator condition without typed mapping"),
        prefix=("tools", 0, "reliability"),
    )

    assert known[0].issue_code == (
        "reliability_tool_identity_drift@tools.0.reliability.tool_id"
    )
    assert known[0].actionable_for_agent
    assert known[0].expected_category == "tool_id equal to the assigned batch tool_id"
    assert unknown[0].code == "framework_diagnostic_incomplete"
    assert not unknown[0].retryable
    assert not unknown[0].actionable_for_agent


@pytest.mark.asyncio
async def test_typed_inventory_diagnostic_reaches_prompt_and_repair_authority(
    tmp_path: Path,
) -> None:
    backend = _RecordingBackend()
    authority = _RecordingRepairAuthority()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )
    diagnostic = ValidationDiagnostic(
        owner_component="design",
        validation_phase="state_inventory_semantics",
        frontier_ordinal=20,
        issues=tuple(
            SafeValidationIssue(
                "state_inventory_lifecycle_mutability",
                ("entities", index, "lifecycle_field"),
                "lifecycle_field must exactly name one mutable_fields entry.",
            )
            for index in (6, 7, 8, 9, 11)
        ),
    )

    def require_valid(output: _Output) -> None:
        if output.value != "valid":
            raise StructuredValidationError(diagnostic)

    token = _DESIGN_REPAIR_AUTHORITY.set(authority)
    try:
        output, _results = await designer.run_structured_agent(
            role="environment-engineer",
            lineage_id="lineage:hotel-state-entity-inventory",
            workspace=tmp_path,
            model=_Output,
            prompt="Create a frozen state inventory.",
            permissions=PermissionScope(),
            budget=DesignerInvocationBudget(
                Budget(
                    llm_tokens=1_000,
                    agent_turns=2,
                    repair_attempts=1,
                    wall_seconds=30,
                )
            ),
            semantic_validator=require_valid,
        )
    finally:
        _DESIGN_REPAIR_AUTHORITY.reset(token)

    assert output.value == "valid"
    correction = backend.requests[1].prompt
    for index in (6, 7, 8, 9, 11):
        assert (
            f"state_inventory_lifecycle_mutability at entities.{index}.lifecycle_field"
        ) in correction
    authorization = authority.authorizations[0]
    assert authorization["issue_codes"] == diagnostic.issue_codes
    assert authorization["diagnostic"] == diagnostic


@pytest.mark.asyncio
async def test_schema_preflight_reports_graph_and_plan_failures_before_one_rework(
    tmp_path: Path,
) -> None:
    plan = StateEntityPlan(
        entity="search_catalog",
        purpose="Searchable hotel resources.",
        root_field="search_catalog",
        storage="collection",
        system_of_record="search_catalog",
        boundary_resource_ids=("properties", "room_types", "rate_plans"),
        primary_key_fields=("resource_kind", "resource_id"),
        mutable_fields=("properties", "room_types", "rate_plans", "last_indexed_at"),
        evidence_claim_ids=("claim:catalog",),
    )

    def string_node(node_id: str) -> SchemaStringNodeDraft:
        return SchemaStringNodeDraft(node_id=node_id, kind="string")

    invalid = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="search_catalog",
                        node_id="container",
                        required=True,
                    ),
                ),
            ),
            SchemaObjectNodeDraft(
                node_id="container",
                kind="object",
                properties=(
                    SchemaPropertyDraft(name="properties", node_id="properties", required=True),
                    SchemaPropertyDraft(name="room_types", node_id="room_types", required=True),
                    SchemaPropertyDraft(name="rate_plans", node_id="rate_plans", required=True),
                    SchemaPropertyDraft(
                        name="last_indexed_at",
                        node_id="rejected-node-id",
                        required=True,
                    ),
                ),
            ),
            string_node("properties"),
            string_node("room_types"),
            string_node("rate_plans"),
            string_node("last_indexed_at"),
        ),
    )
    partial = invalid.model_copy(
        update={
            "nodes": (
                invalid.nodes[0],
                SchemaObjectNodeDraft(
                    node_id="container",
                    kind="object",
                    properties=(
                        *cast(SchemaObjectNodeDraft, invalid.nodes[1]).properties[:-1],
                        SchemaPropertyDraft(
                            name="last_indexed_at",
                            node_id="last_indexed_at",
                            required=True,
                        ),
                    ),
                ),
                *invalid.nodes[2:],
            )
        }
    )
    valid = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=tuple(
                    SchemaPropertyDraft(name=field, node_id=field, required=True)
                    for field in (*plan.primary_key_fields, *plan.mutable_fields)
                ),
            ),
            *(string_node(field) for field in (*plan.primary_key_fields, *plan.mutable_fields)),
        ),
    )
    backend = _SequenceBackend(
        (
            cast(dict[str, object], invalid.model_dump(mode="json")),
            cast(dict[str, object], partial.model_dump(mode="json")),
            cast(dict[str, object], valid.model_dump(mode="json")),
        )
    )
    authority = _RecordingRepairAuthority()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=2,
    )

    def validate(value: StateEntitySchemaIRDraft) -> None:
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(value, plan=plan)

    token = _DESIGN_REPAIR_AUTHORITY.set(authority)
    try:
        output, _results = await designer.run_structured_agent(
            role="environment-engineer",
            lineage_id="lineage:hotel-search-catalog-schema",
            workspace=tmp_path,
            model=StateEntitySchemaIRDraft,
            prompt="Create field semantics for the frozen state entity plan.",
            permissions=PermissionScope(),
            budget=DesignerInvocationBudget(
                Budget(
                    llm_tokens=10_000,
                    agent_turns=3,
                    repair_attempts=2,
                    wall_seconds=30,
                )
            ),
            semantic_validator=validate,
        )
    finally:
        _DESIGN_REPAIR_AUTHORITY.reset(token)

    assert output == valid
    diagnostic = cast(ValidationDiagnostic, authority.authorizations[0]["diagnostic"])
    assert diagnostic.validation_phase == "state_entity_schema_ir_semantics"
    assert diagnostic.frontier_ordinal == 30
    assert set(diagnostic.issue_codes) == {
        "schema_graph_unknown_reference@nodes.1.properties.3.node_id",
        "schema_graph_node_unreachable@nodes.5.node_id",
        "state_schema_primary_key_missing@nodes.0.properties",
        "state_schema_mutable_field_missing@nodes.0.properties",
        "state_schema_root_property_unplanned@nodes.0.properties.0.name",
    }
    first_correction = backend.requests[1].prompt
    assert "Every schema reference must name one declared node_id." in first_correction
    assert "do not add a root-field wrapper" in first_correction
    assert "rejected-node-id" not in first_correction
    remaining = cast(ValidationDiagnostic, authority.completion_diagnostics[0])
    assert remaining.frontier_ordinal == 30
    assert set(remaining.issue_codes) == {
        "state_schema_primary_key_missing@nodes.0.properties",
        "state_schema_mutable_field_missing@nodes.0.properties",
        "state_schema_root_property_unplanned@nodes.0.properties.0.name",
    }
    assert set(remaining.issue_codes) < set(diagnostic.issue_codes)
    second_correction = backend.requests[2].prompt
    assert "do not add a root-field wrapper" in second_correction
    assert "schema_graph_unknown_reference" not in second_correction
    assert authority.completions == [
        ("repair-entry:1", remaining.issue_codes, False),
        ("repair-entry:2", (), False),
    ]
    assert authority.completion_diagnostics == [remaining, None]


def test_state_schema_root_correction_advances_to_frozen_plan_frontier() -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="One hotel reservation.",
        root_field="reservations",
        storage="collection",
        system_of_record="reservation_service",
        boundary_resource_ids=("reservations",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("status",),
        lifecycle_field="status",
        lifecycle_states=("pending", "confirmed"),
        evidence_claim_ids=("claim:reservation",),
    )
    unknown_root = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="missing-root",
        nodes=(SchemaStringNodeDraft(node_id="status", kind="string"),),
    )
    with pytest.raises(StructuredValidationError) as unknown_exc:
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(unknown_root, plan=plan)
    assert unknown_exc.value.diagnostic.frontier_ordinal == 20
    assert "schema_graph_root_unknown@root_node_id" in unknown_exc.value.diagnostic.issue_codes

    wrapper_root = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            _schema_root("status"),
            SchemaStringNodeDraft(
                node_id="status",
                kind="string",
                enum_values=("pending",),
            ),
        ),
    )
    with pytest.raises(StructuredValidationError) as plan_exc:
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(wrapper_root, plan=plan)
    assert plan_exc.value.diagnostic.frontier_ordinal == 30
    assert {
        "state_schema_primary_key_missing@nodes.0.properties",
        "state_schema_mutable_field_missing@nodes.0.properties",
        "state_schema_root_property_unplanned@nodes.0.properties.0.name",
    } <= set(plan_exc.value.diagnostic.issue_codes)


@pytest.mark.parametrize(
    ("status_node_id", "expected_code", "forbidden_code"),
    (
        (
            "status",
            "state_schema_lifecycle_enum_drift@nodes.2.enum_values",
            "schema_graph_unknown_reference@nodes.0.properties.1.node_id",
        ),
        (
            "missing-status",
            "schema_graph_unknown_reference@nodes.0.properties.1.node_id",
            "state_schema_lifecycle_not_string@nodes.0.kind",
        ),
    ),
)
def test_state_schema_lifecycle_diagnostics_are_direct_and_non_dependent(
    status_node_id: str,
    expected_code: str,
    forbidden_code: str,
) -> None:
    plan = StateEntityPlan(
        entity="reservation",
        purpose="One hotel reservation.",
        root_field="reservations",
        storage="collection",
        system_of_record="reservation_service",
        boundary_resource_ids=("reservations",),
        primary_key_fields=("reservation_id",),
        mutable_fields=("status",),
        lifecycle_field="status",
        lifecycle_states=("pending", "confirmed"),
        evidence_claim_ids=("claim:reservation",),
    )
    draft = StateEntitySchemaIRDraft(
        entity=plan.entity,
        root_node_id="root",
        nodes=(
            SchemaObjectNodeDraft(
                node_id="root",
                kind="object",
                properties=(
                    SchemaPropertyDraft(
                        name="reservation_id", node_id="reservation_id", required=True
                    ),
                    SchemaPropertyDraft(name="status", node_id=status_node_id, required=True),
                ),
            ),
            SchemaStringNodeDraft(node_id="reservation_id", kind="string"),
            SchemaStringNodeDraft(node_id="status", kind="string", enum_values=("pending",)),
        ),
    )

    with pytest.raises(StructuredValidationError) as exc_info:
        EnvironmentDesigner._validate_state_entity_schema_ir_draft(draft, plan=plan)

    assert expected_code in exc_info.value.diagnostic.issue_codes
    assert forbidden_code not in exc_info.value.diagnostic.issue_codes


@pytest.mark.asyncio
async def test_invalid_transport_json_gets_safe_specific_rework_feedback(
    tmp_path: Path,
) -> None:
    backend = _InvalidTransportBackend()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )

    output, _ = await designer.run_structured_agent(
        role="environment-engineer",
        lineage_id="lineage:transport-rework",
        workspace=tmp_path,
        model=_Output,
        prompt="Create the complete artifact from immutable input.",
        permissions=PermissionScope(),
        budget=DesignerInvocationBudget(
            Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=30)
        ),
    )

    assert output == _Output(value="valid")
    correction = backend.requests[1].prompt
    assert "transport artifact_json must contain one valid JSON object" in correction
    assert "TOP_SECRET_REJECTED" not in correction


@pytest.mark.asyncio
async def test_transport_to_shape_uses_monotonic_typed_frontiers(tmp_path: Path) -> None:
    backend = _TransportShapeSequenceBackend()
    authority = _RecordingRepairAuthority()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=2,
    )

    token = _DESIGN_REPAIR_AUTHORITY.set(authority)
    try:
        output, _ = await designer.run_structured_agent(
            role="environment-engineer",
            lineage_id="lineage:transport-shape-frontiers",
            workspace=tmp_path,
            model=_Output,
            prompt="Create the complete artifact from immutable input.",
            permissions=PermissionScope(),
            budget=DesignerInvocationBudget(
                Budget(
                    llm_tokens=1_000,
                    agent_turns=3,
                    repair_attempts=2,
                    wall_seconds=30,
                )
            ),
        )
    finally:
        _DESIGN_REPAIR_AUTHORITY.reset(token)

    assert output == _Output(value="valid")
    first = cast(ValidationDiagnostic, authority.authorizations[0]["diagnostic"])
    shape = cast(ValidationDiagnostic, authority.completion_diagnostics[0])
    assert first.validation_phase == "structured_output_transport"
    assert first.frontier_ordinal == 0
    assert first.issue_codes == ("transport_invalid_json@artifact_json",)
    assert shape.frontier_ordinal == 10
    assert authority.authorizations[1]["diagnostic"] == shape
    assert authority.completion_diagnostics == [shape, None]
    assert "TOP_SECRET_REJECTED" not in backend.requests[1].prompt


def _schema_root(child_node_id: str) -> SchemaObjectNodeDraft:
    return SchemaObjectNodeDraft(
        node_id="root",
        kind="object",
        properties=(SchemaPropertyDraft(name="value", node_id=child_node_id, required=True),),
    )


@pytest.mark.parametrize(
    ("expected_code", "root_node_id", "nodes"),
    (
        (
            "schema_graph_node_id_duplicate",
            "root",
            (
                _schema_root("leaf"),
                SchemaStringNodeDraft(node_id="leaf", kind="string"),
                SchemaStringNodeDraft(node_id="leaf", kind="string"),
            ),
        ),
        (
            "schema_object_property_duplicate",
            "root",
            (
                SchemaObjectNodeDraft(
                    node_id="root",
                    kind="object",
                    properties=(
                        SchemaPropertyDraft(name="value", node_id="leaf", required=True),
                        SchemaPropertyDraft(name="value", node_id="leaf", required=False),
                    ),
                ),
                SchemaStringNodeDraft(node_id="leaf", kind="string"),
            ),
        ),
        (
            "schema_array_bounds_inverted",
            "root",
            (
                _schema_root("array"),
                SchemaArrayNodeDraft(
                    node_id="array",
                    kind="array",
                    items_node_id="leaf",
                    min_items=2,
                    max_items=1,
                ),
                SchemaStringNodeDraft(node_id="leaf", kind="string"),
            ),
        ),
        (
            "schema_string_enum_duplicate",
            "root",
            (
                _schema_root("leaf"),
                SchemaStringNodeDraft(node_id="leaf", kind="string", enum_values=("a", "a")),
            ),
        ),
        (
            "schema_string_constraints_unsatisfiable",
            "root",
            (
                _schema_root("leaf"),
                SchemaStringNodeDraft(
                    node_id="leaf", kind="string", enum_values=("a",), const_value="b"
                ),
            ),
        ),
        (
            "schema_string_bounds_inverted",
            "root",
            (
                _schema_root("leaf"),
                SchemaStringNodeDraft(node_id="leaf", kind="string", min_length=2, max_length=1),
            ),
        ),
        (
            "schema_integer_enum_duplicate",
            "root",
            (
                _schema_root("leaf"),
                SchemaIntegerNodeDraft(node_id="leaf", kind="integer", enum_values=(1, 1)),
            ),
        ),
        (
            "schema_integer_constraints_unsatisfiable",
            "root",
            (
                _schema_root("leaf"),
                SchemaIntegerNodeDraft(
                    node_id="leaf", kind="integer", enum_values=(1,), const_value=2
                ),
            ),
        ),
        (
            "schema_integer_bounds_inverted",
            "root",
            (
                _schema_root("leaf"),
                SchemaIntegerNodeDraft(node_id="leaf", kind="integer", minimum=2, maximum=1),
            ),
        ),
        (
            "schema_number_bounds_inverted",
            "root",
            (
                _schema_root("leaf"),
                SchemaNumberNodeDraft(node_id="leaf", kind="number", minimum=2.0, maximum=1.0),
            ),
        ),
        (
            "schema_union_variant_duplicate",
            "root",
            (
                _schema_root("union"),
                SchemaUnionNodeDraft(
                    node_id="union", kind="union", variant_node_ids=("leaf", "leaf")
                ),
                SchemaNullNodeDraft(node_id="leaf", kind="null"),
            ),
        ),
        (
            "schema_graph_root_unknown",
            "missing",
            (SchemaObjectNodeDraft(node_id="root", kind="object"),),
        ),
        (
            "schema_graph_root_not_object",
            "root",
            (SchemaStringNodeDraft(node_id="root", kind="string"),),
        ),
    ),
)
def test_schema_ir_preflight_covers_each_framework_owned_invariant(
    expected_code: str,
    root_node_id: str,
    nodes: tuple[object, ...],
) -> None:
    issues = EnvironmentDesigner._schema_ir_validation_issues(
        root_node_id=root_node_id,
        nodes=cast(Any, nodes),
    )

    assert expected_code in {issue.code for issue in issues}


def test_schema_ir_compiler_canonicalizes_satisfiable_enum_const_intersections() -> None:
    nodes = (
        SchemaObjectNodeDraft(
            node_id="root",
            kind="object",
            properties=(
                SchemaPropertyDraft(name="status", node_id="status", required=True),
                SchemaPropertyDraft(name="ordinal", node_id="ordinal", required=True),
            ),
        ),
        SchemaStringNodeDraft(
            node_id="status",
            kind="string",
            enum_values=("pending", "cancelled"),
            const_value="cancelled",
        ),
        SchemaIntegerNodeDraft(
            node_id="ordinal",
            kind="integer",
            enum_values=(1, 2),
            const_value=2,
        ),
    )

    issues = EnvironmentDesigner._schema_ir_validation_issues(
        root_node_id="root",
        nodes=nodes,
    )
    compiled = EnvironmentDesigner._compile_schema_ir(
        root_node_id="root",
        nodes=nodes,
    )

    assert issues == ()
    assert compiled["properties"] == {
        "status": {"type": "string", "const": "cancelled"},
        "ordinal": {"type": "integer", "const": 2},
    }


@pytest.mark.asyncio
async def test_retryable_backend_failure_replays_immutable_node_in_fresh_session(
    tmp_path: Path,
) -> None:
    backend = _RetryableBackend()
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, backend),
        profile_provider=cast(AgentProfileProvider, _ProfileProvider()),
        research_toolchain=cast(ResearchToolchain, object()),
        maximum_structured_reworks=1,
    )

    output, results = await designer.run_structured_agent(
        role="environment-engineer",
        lineage_id="lineage:backend-retry",
        workspace=tmp_path,
        model=_Output,
        prompt="Create the artifact from the immutable node inputs.",
        permissions=PermissionScope(),
        budget=DesignerInvocationBudget(
            Budget(llm_tokens=1_000, agent_turns=2, repair_attempts=1, wall_seconds=30)
        ),
    )

    assert output == _Output(value="valid")
    assert [result.status for result in results] == [
        InvocationStatus.FAILED,
        InvocationStatus.COMPLETED,
    ]
    assert backend.requests[1].session is None
    assert backend.requests[1].prompt == backend.requests[0].prompt
    assert backend.requests[1].metadata["repair_mode"] == "backend_retry"


def test_resumable_node_uses_latest_committed_valid_revision(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="designer-resume-test",
        allowed_artifact_type_prefixes=("control.", "design."),
        allowed_event_type_prefixes=("design_",),
    )
    designer = EnvironmentDesigner(
        artifact_store=writer,
        research_artifact_store=writer,
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=ResearchToolchain(
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
        ),
    )
    job_ref = writer.put_json(
        artifact_id="job:resume-test",
        artifact_type="control.test_job",
        value={"kind": "test"},
    )
    dependency_ref = writer.put_json(
        artifact_id="dependency:resume-test",
        artifact_type="design.test_dependency",
        value={"version": 1},
    )
    first_ref = writer.put_json(
        artifact_id="node:resume-test",
        artifact_type="design.test_output",
        value={"value": "first"},
        dependencies=(dependency_ref,),
    )
    writer.record_event(
        event_type="design_node_completed",
        subject_ref=first_ref,
        related_refs=(job_ref,),
        details=(
            KeyValue(key="node", value="test_node"),
            KeyValue(key="detail", value="test_detail"),
        ),
    )
    designer._commit_semantic_node(
        job_ref=job_ref,
        node="test_node",
        detail="test_detail",
        subject_ref=first_ref,
        immutable_input_refs=(dependency_ref,),
        derived_refs=(),
        model=_Output,
    )
    second_ref = writer.put_json(
        artifact_id="node:resume-test",
        artifact_type="design.test_output",
        value={"value": "second"},
        dependencies=(dependency_ref,),
    )
    writer.record_event(
        event_type="design_node_completed",
        subject_ref=second_ref,
        related_refs=(job_ref,),
        details=(
            KeyValue(key="node", value="test_node"),
            KeyValue(key="detail", value="test_detail"),
        ),
    )
    designer._commit_semantic_node(
        job_ref=job_ref,
        node="test_node",
        detail="test_detail",
        subject_ref=second_ref,
        immutable_input_refs=(dependency_ref,),
        derived_refs=(),
        model=_Output,
    )

    reused = designer._load_validated_design_node(
        artifact_id="node:resume-test",
        artifact_type="design.test_output",
        model=_Output,
        required_dependencies=(dependency_ref,),
        semantic_validator=lambda output: None,
        job_ref=job_ref,
        node="test_node",
        detail="test_detail",
    )

    assert reused == (_Output(value="second"), second_ref)
    reuse_event = store.list_events()[-1]
    assert reuse_event.event_type == "design_node_reused"
    assert reuse_event.subject_ref == second_ref
    assert {item.key: item.value for item in reuse_event.details}["valid_candidate_count"] == 2


def test_resumable_single_candidate_requires_authenticated_completion(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="designer-single-resume-test",
        allowed_artifact_type_prefixes=("control.", "design."),
        allowed_event_type_prefixes=("design_",),
    )
    designer = EnvironmentDesigner(
        artifact_store=writer,
        research_artifact_store=writer,
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=cast(ResearchToolchain, object()),
    )
    job_ref = writer.put_json(
        artifact_id="job:single-resume-test",
        artifact_type="control.test_job",
        value={"kind": "test"},
    )
    dependency_ref = writer.put_json(
        artifact_id="dependency:single-resume-test",
        artifact_type="design.test_dependency",
        value={"version": 1},
    )
    node_ref = writer.put_json(
        artifact_id="node:single-resume-test",
        artifact_type="design.test_output",
        value={"value": "only"},
        dependencies=(dependency_ref,),
    )

    reused = designer._load_validated_design_node(
        artifact_id="node:single-resume-test",
        artifact_type="design.test_output",
        model=_Output,
        required_dependencies=(dependency_ref,),
        semantic_validator=lambda output: None,
        job_ref=job_ref,
        node="single_node",
        detail="single_detail",
    )

    assert reused is None

    wrong_completion = writer.record_event(
        event_type="design_node_completed",
        subject_ref=node_ref,
        related_refs=(job_ref,),
        details=(KeyValue(key="node", value="different_node"),),
    )
    assert wrong_completion.event_type == "design_node_completed"
    assert (
        designer._load_validated_design_node(
            artifact_id="node:single-resume-test",
            artifact_type="design.test_output",
            model=_Output,
            required_dependencies=(dependency_ref,),
            semantic_validator=lambda output: None,
            job_ref=job_ref,
            node="single_node",
            detail="single_detail",
        )
        is None
    )

    completion = writer.record_event(
        event_type="design_node_completed",
        subject_ref=node_ref,
        related_refs=(job_ref,),
        details=(
            KeyValue(key="node", value="single_node"),
            KeyValue(key="detail", value="single_detail"),
        ),
    )
    assert completion.event_type == "design_node_completed"

    # Completion events are audit records, not resumability authority.
    assert (
        designer._load_validated_design_node(
            artifact_id="node:single-resume-test",
            artifact_type="design.test_output",
            model=_Output,
            required_dependencies=(dependency_ref,),
            semantic_validator=lambda output: None,
            job_ref=job_ref,
            node="single_node",
            detail="single_detail",
        )
        is None
    )
    designer._commit_semantic_node(
        job_ref=job_ref,
        node="single_node",
        detail="single_detail",
        subject_ref=node_ref,
        immutable_input_refs=(dependency_ref,),
        derived_refs=(),
        model=_Output,
    )

    reused = designer._load_validated_design_node(
        artifact_id="node:single-resume-test",
        artifact_type="design.test_output",
        model=_Output,
        required_dependencies=(dependency_ref,),
        semantic_validator=lambda output: None,
        job_ref=job_ref,
        node="single_node",
        detail="single_detail",
    )

    assert reused == (_Output(value="only"), node_ref)


def test_resumable_multi_candidate_nodes_use_latest_semantic_commit(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="designer-indexed-resume-test",
        allowed_artifact_type_prefixes=("control.", "design."),
        allowed_event_type_prefixes=("design_",),
    )
    designer = EnvironmentDesigner(
        artifact_store=writer,
        research_artifact_store=writer,
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=cast(ResearchToolchain, object()),
    )
    job_ref = writer.put_json(
        artifact_id="job:indexed-resume-test",
        artifact_type="control.test_job",
        value={"kind": "test"},
    )
    dependency_ref = writer.put_json(
        artifact_id="dependency:indexed-resume-test",
        artifact_type="design.test_dependency",
        value={"version": 1},
    )
    expected: dict[str, ArtifactRef] = {}
    for node_name in ("alpha", "beta"):
        for value in ("first", "second"):
            ref = writer.put_json(
                artifact_id=f"node:indexed-resume-test:{node_name}",
                artifact_type="design.test_output",
                value={"value": value},
                dependencies=(dependency_ref,),
            )
            designer._commit_semantic_node(
                job_ref=job_ref,
                node=node_name,
                detail=node_name,
                subject_ref=ref,
                immutable_input_refs=(dependency_ref,),
                derived_refs=(),
                model=_Output,
            )
            expected[node_name] = ref
    for node_name in ("alpha", "beta"):
        reused = designer._load_validated_design_node(
            artifact_id=f"node:indexed-resume-test:{node_name}",
            artifact_type="design.test_output",
            model=_Output,
            required_dependencies=(dependency_ref,),
            semantic_validator=lambda output: None,
            job_ref=job_ref,
            node=node_name,
            detail=node_name,
        )
        assert reused == (_Output(value="second"), expected[node_name])


@pytest.mark.asyncio
async def test_evidence_checkpoint_resume_reuses_exact_graph_without_research(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="designer-evidence-resume-test",
        allowed_artifact_type_prefixes=("control.", "design."),
        allowed_event_type_prefixes=("design_",),
    )
    profile = ReleaseProfile(profile_id="release:test")
    request = EnvironmentRequest(
        request_id="request:evidence-resume",
        need="Generate a real local booking environment.",
        budget=Budget(agent_turns=32, search_calls=2, tool_calls=4, wall_seconds=120),
        release_profile=profile,
    )
    request_ref = writer.put_json(
        artifact_id="request:evidence-resume",
        artifact_type="control.environment_request",
        value=request,
    )
    job = EnvironmentJob(
        job_id="job:evidence-resume",
        kind="generate",
        request_ref=request_ref,
        budget=request.budget,
        release_profile=profile,
    )
    job_ref = writer.put_json(
        artifact_id="job:evidence-resume",
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    content_hash = sha256_digest(b"observed booking workflow")
    graph = EvidenceGraph(
        graph_id="graph:evidence-resume",
        revision=1,
        evidence=(
            Evidence(
                evidence_id="evidence:booking",
                source_kind="web",
                source_uri="https://example.invalid/booking",
                retrieved_at=datetime.now(UTC),
                retrieval_status="success",
                raw_content_hash=content_hash,
                content_hash=content_hash,
                fetcher="test-fetcher",
                fetcher_version="1",
                extractor="test-extractor",
                extractor_version="1",
                observed_summary="A fetched source describes a booking workflow.",
            ),
        ),
        claims=(
            Claim(
                claim_id="claim:booking",
                kind="observed",
                statement="The workflow creates a reservation after availability checks.",
                confidence=0.9,
                evidence_ids=("evidence:booking",),
                status="supported",
            ),
        ),
    )
    graph_ref = writer.put_json(
        artifact_id="job:evidence-resume:evidence-graph",
        artifact_type="design.evidence_graph",
        value=graph,
        dependencies=(request_ref,),
    )
    designer = EnvironmentDesigner(
        artifact_store=writer,
        research_artifact_store=writer,
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=ResearchToolchain(
            cast(Any, object()),
            cast(Any, object()),
            cast(Any, object()),
        ),
    )

    checkpoint_ref = designer.adopt_latest_phase_checkpoint(
        job=job,
        job_ref=job_ref,
        request=request,
        request_ref=request_ref,
    )
    checkpoint = writer.get_json(checkpoint_ref, DesignPhaseCheckpoint)
    assert checkpoint.phase == "evidence_graph"
    assert checkpoint.evidence_graph_ref == graph_ref

    workspace = tmp_path / "resume"
    workspace.mkdir()
    resumed = await designer._prepare_evidence_phase(  # noqa: SLF001
        job=job,
        job_ref=job_ref,
        request=request,
        request_ref=request_ref,
        workspace=workspace,
        meter=DesignerInvocationBudget(Budget(llm_tokens=100, agent_turns=1, wall_seconds=30)),
        fetch_budget=0,
        phase_checkpoint_ref=checkpoint_ref,
    )

    assert resumed.evidence_graph == graph
    assert resumed.evidence_graph_ref == graph_ref
    assert resumed.research_usage == BudgetUsage()
    assert resumed.invocation_results == ()
    assert (workspace / "resumed-evidence-checkpoint.json").is_file()
    assert store.list_events()[-1].event_type == "design_phase_resumed"


def test_access_semantic_failure_is_classified_without_generated_values() -> None:
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError("observation visibility must cover exactly every boundary actor")
    ) == ("observation_actor_coverage",)
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError("allowed actors lack required scopes: generated details")
    ) == ("access_scope_authority",)


def test_state_schema_repairs_distinguish_real_semantic_progress() -> None:
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError("state entity payment_state schema must declare top-level type=object")
    ) == ("schema_root_object",)
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError(
            "state entity payment_state object schema must set additionalProperties=false at $"
        )
    ) == ("schema_object_not_closed",)
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError(
            "state schema unions must contain exactly one scalar and null so the "
            "framework can compile task reset schemas: payment_authorization"
        )
    ) == ("state_schema_union_task_subset",)


def test_task_schema_composition_issue_keeps_safe_field_path() -> None:
    assert EnvironmentDesigner._validation_issue_codes(
        ValueError(
            "task task:hotel-booking.search_quote "
            "initial_config_schema.payment_state[].authorization_id uses unsupported "
            "open/composed schema keywords: ['anyOf']"
        )
    ) == ("task_initial_schema_composition:payment_state.items.authorization_id",)


def test_evidence_synthesis_reports_all_unknown_references_with_safe_paths() -> None:
    content_hash = sha256_digest(b"allowed evidence")
    evidence = (
        Evidence(
            evidence_id="evidence:allowed",
            source_kind="web",
            source_uri="https://example.invalid/allowed",
            retrieved_at=datetime.now(UTC),
            retrieval_status="success",
            raw_content_hash=content_hash,
            content_hash=content_hash,
            fetcher="test-fetcher",
            fetcher_version="1",
            extractor="test-extractor",
            extractor_version="1",
            observed_summary="A real fetched source body is available.",
        ),
    )
    synthesis = EvidenceSynthesis(
        claims=(
            Claim(
                claim_id="claim:one",
                kind="observed",
                statement="First claim with a mistyped evidence id.",
                confidence=0.8,
                evidence_ids=(
                    "evidence:mistyped-one",
                    "evidence:mistyped-three",
                    "sk-secret-rejected-value",
                ),
                status="supported",
            ),
            Claim(
                claim_id="claim:two",
                kind="observed",
                statement="Second claim with another mistyped evidence id.",
                confidence=0.8,
                evidence_ids=("evidence:mistyped-two",),
                status="supported",
            ),
        )
    )

    with pytest.raises(ValueError) as captured:
        EnvironmentDesigner._validate_evidence_synthesis_references(  # noqa: SLF001
            synthesis,
            evidence,
        )

    assert EnvironmentDesigner._validation_issue_codes(captured.value) == (  # noqa: SLF001
        "evidence_reference_unknown@claims.claim:one.evidence_ids.0",
        "evidence_reference_unknown@claims.claim:one.evidence_ids.1",
        "evidence_reference_unknown@claims.claim:one.evidence_ids.2",
        "evidence_reference_unknown@claims.claim:two.evidence_ids.0",
    )
    feedback = EnvironmentDesigner._structured_repair_feedback(captured.value)  # noqa: SLF001
    assert "claims.claim:one.evidence_ids.0" in feedback
    assert "claims.claim:two.evidence_ids.0" in feedback
    assert "mistyped-one" not in feedback
    assert "mistyped-two" not in feedback
    assert "sk-secret" not in feedback


def test_semantic_feedback_marks_prompt_overflow_but_keeps_all_safe_issue_codes() -> None:
    error = StructuredSemanticError(
        tuple(
            StructuredSemanticIssue(
                code="reference_unknown",
                location=("claims", index, "evidence_ids", 0),
                message="reference is outside the framework allowlist",
            )
            for index in range(35)
        )
    )

    issue_codes = EnvironmentDesigner._validation_issue_codes(error)  # noqa: SLF001
    feedback = EnvironmentDesigner._structured_repair_feedback(error)  # noqa: SLF001
    diagnostic = EnvironmentDesigner._validation_diagnostic(  # noqa: SLF001
        error,
        model=EvidenceSynthesis,
        validation_stage="semantic",
    )

    assert len(issue_codes) == 35
    assert issue_codes[-1] == "reference_unknown@claims.34.evidence_ids.0"
    assert "diagnostics_overflow" in feedback
    assert "3 additional safe issues" in feedback
    assert diagnostic is not None
    assert diagnostic.validation_phase == "evidencesynthesis_semantic"
    assert diagnostic.frontier_ordinal == 20
    assert diagnostic.issue_codes == issue_codes


@pytest.mark.asyncio
async def test_direct_designer_failure_preserves_already_spent_research_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=cast(ResearchToolchain, object()),
    )

    async def fail_after_research(**_: object) -> object:
        _DESIGN_RESEARCH_USAGE.set(BudgetUsage(search_calls=3, tool_calls=9))
        raise DesignerError("agent.environment-engineer.output", "invalid")

    monkeypatch.setattr(designer, "_generate", fail_after_research)
    with pytest.raises(DesignerError) as captured:
        await designer.generate(
            job=cast(EnvironmentJob, object()),
            job_ref=cast(ArtifactRef, object()),
            request=cast(EnvironmentRequest, object()),
            request_ref=cast(ArtifactRef, object()),
            workspace=tmp_path,
            invocation_budget=Budget(),
        )

    assert captured.value.research_usage == BudgetUsage(search_calls=3, tool_calls=9)


@pytest.mark.asyncio
async def test_direct_designer_does_not_overwrite_failure_owned_research_usage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    designer = EnvironmentDesigner(
        artifact_store=cast(ArtifactWriter, object()),
        research_artifact_store=cast(ArtifactWriter, object()),
        invocation_backend=cast(InvocationBackend, object()),
        profile_provider=cast(AgentProfileProvider, object()),
        research_toolchain=cast(ResearchToolchain, object()),
    )

    async def fail_during_research(**_: object) -> object:
        raise DesignerError(
            "research.fetch",
            "safe aggregate",
            research_usage=BudgetUsage(search_calls=2, tool_calls=5),
            failure_code="research_infrastructure_upstream_unavailable",
            infrastructure_error=True,
        )

    monkeypatch.setattr(designer, "_generate", fail_during_research)
    with pytest.raises(DesignerError) as captured:
        await designer.generate(
            job=cast(EnvironmentJob, object()),
            job_ref=cast(ArtifactRef, object()),
            request=cast(EnvironmentRequest, object()),
            request_ref=cast(ArtifactRef, object()),
            workspace=tmp_path,
            invocation_budget=Budget(),
        )

    assert captured.value.research_usage == BudgetUsage(search_calls=2, tool_calls=5)
    assert captured.value.failure_code == "research_infrastructure_upstream_unavailable"
    assert captured.value.infrastructure_error is True

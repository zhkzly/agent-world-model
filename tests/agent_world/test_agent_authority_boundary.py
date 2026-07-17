"""Executable proof that real Agents cannot acquire Foundry control authority."""

from __future__ import annotations

import inspect
from typing import ClassVar, Literal

import pytest
from pydantic import BaseModel, ConfigDict

from agent_world.builder.models import CandidateCompletion, ImplementationContract
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CandidateManifest,
    EnvironmentJob,
    Finding,
    GateResult,
    IntegrationReport,
    JudgeReport,
    PermissionScope,
    ReleaseProfile,
)
from agent_world.contracts.reachability import InteractiveSolveDecision
from agent_world.control.models import (
    BudgetLease,
    JobRunSnapshot,
    NodeAttempt,
    RepairDirective,
    RepairLedgerEntry,
)
from agent_world.designer import models as designer_models
from agent_world.invocation.authority import (
    EXECUTION_AUTHORITY_MODELS,
    AgentAuthorityViolation,
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    assert_agent_output_advisory,
    register_agent_output_contract,
    registered_agent_output_contracts,
)
from agent_world.judge.models import VerifierIntent
from agent_world.registry.models import ReleaseDossier, ReleaseRecord


def test_authority_inventory_is_bound_to_real_framework_contracts() -> None:
    concrete_types = {
        ArtifactRef,
        Budget,
        BudgetLease,
        BudgetUsage,
        CandidateManifest,
        EnvironmentJob,
        Finding,
        GateResult,
        IntegrationReport,
        JobRunSnapshot,
        JudgeReport,
        NodeAttempt,
        PermissionScope,
        ReleaseDossier,
        ReleaseProfile,
        ReleaseRecord,
        RepairDirective,
        RepairLedgerEntry,
        ImplementationContract,
    }

    assert {
        (item.__module__, item.__qualname__) for item in concrete_types
    } == EXECUTION_AUTHORITY_MODELS


def test_every_real_agent_output_root_is_non_executive() -> None:
    production_roots = {
        model: authority
        for model, authority in registered_agent_output_contracts().items()
        if model.__module__.startswith("agent_world.")
    }
    assert CandidateCompletion in production_roots
    assert InteractiveSolveDecision in production_roots
    assert VerifierIntent in production_roots
    assert {
        model
        for _name, model in inspect.getmembers(designer_models, inspect.isclass)
        if model in production_roots
    }

    for model, authority in production_roots.items():
        assert_agent_output_advisory(
            model,
            authority=authority,
        )


def test_agent_output_cannot_embed_a_framework_decision_contract() -> None:
    class BadSemanticOutput(SemanticAdvisoryOutput, BaseModel):
        model_config = ConfigDict(extra="forbid")
        rationale: str
        directive: RepairDirective

    register_agent_output_contract(
        BadSemanticOutput,
        authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
    )

    with pytest.raises(AgentAuthorityViolation, match="RepairDirective"):
        assert_agent_output_advisory(
            BadSemanticOutput,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_agent_output_cannot_choose_control_flow_with_plain_fields() -> None:
    class BadSemanticOutput(SemanticAdvisoryOutput, BaseModel):
        model_config = ConfigDict(extra="forbid")
        rationale: str
        owner_node: Literal["design", "build"]
        jump_distance: int
        release_verdict: Literal["pass", "fail"]

    register_agent_output_contract(
        BadSemanticOutput,
        authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
    )

    with pytest.raises(
        AgentAuthorityViolation,
        match="jump_distance.*owner_node.*release_verdict",
    ):
        assert_agent_output_advisory(
            BadSemanticOutput,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_framework_finding_is_not_a_valid_llm_output_root() -> None:
    with pytest.raises(AgentAuthorityViolation, match="unregistered"):
        assert_agent_output_advisory(
            Finding,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_output_capabilities_are_not_interchangeable() -> None:
    with pytest.raises(AgentAuthorityViolation, match="workspace_proposal"):
        assert_agent_output_advisory(
            CandidateCompletion,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )
    with pytest.raises(AgentAuthorityViolation, match="episode_action_proposal"):
        assert_agent_output_advisory(
            InteractiveSolveDecision,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_unregistered_permission_contract_cannot_be_an_agent_output() -> None:
    with pytest.raises(AgentAuthorityViolation, match="unregistered"):
        assert_agent_output_advisory(
            PermissionScope,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_nested_plain_control_fields_are_rejected() -> None:
    class NestedControl(BaseModel):
        owner: str
        budget: int

    class BadSemanticOutput(SemanticAdvisoryOutput, BaseModel):
        decision: NestedControl

    register_agent_output_contract(
        BadSemanticOutput,
        authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
    )

    with pytest.raises(AgentAuthorityViolation, match="NestedControl.budget"):
        assert_agent_output_advisory(
            BadSemanticOutput,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_string_spoof_cannot_impersonate_an_agent_output_capability() -> None:
    class SpoofedSemantic(BaseModel):
        agent_output_authority: ClassVar[str] = "semantic_advisory"
        rationale: str

    with pytest.raises(AgentAuthorityViolation, match="unregistered"):
        assert_agent_output_advisory(
            SpoofedSemantic,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )


def test_registered_semantic_output_rejects_operational_payload_fields() -> None:
    class OperationalPayload(BaseModel):
        action: str
        command: str
        argv: tuple[str, ...]
        path: str
        permissions: tuple[str, ...]
        status: str

    class BadSemanticOutput(SemanticAdvisoryOutput, BaseModel):
        proposal: OperationalPayload

    register_agent_output_contract(
        BadSemanticOutput,
        authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
    )
    with pytest.raises(AgentAuthorityViolation, match="OperationalPayload.action"):
        assert_agent_output_advisory(
            BadSemanticOutput,
            authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
        )

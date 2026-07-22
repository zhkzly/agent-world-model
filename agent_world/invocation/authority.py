"""Enforce that Agent outputs are proposals, never workflow decisions.

The Foundry intentionally gives real Agents broad semantic and implementation
capabilities. That must not accidentally grant them Controller authority. An
output schema handed to an ``InvocationBackend`` may describe a world, a
verifier proposal, a candidate-local workspace declaration, or one episode
action; it may not contain records that route repair, consume budgets, decide
gates, invalidate nodes, or publish a release.

This module stays independent of Controller imports. It runs at the invocation
boundary and rejects authority-bearing model names and root fields before a
profile can be materialized. Static tests bind the names below to the actual
framework-owned contract classes.
"""

from __future__ import annotations

from typing import get_args

from pydantic import BaseModel

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    EpisodeActionProposalOutput,
    SemanticAdvisoryOutput,
    WorkspaceProposalOutput,
    authority_marker,
    register_agent_output_contract,
    registered_agent_output_authority,
    registered_agent_output_contracts,
)


class AgentAuthorityViolation(ValueError):
    """An Agent output contract attempted to cross the control-plane boundary."""


# Framework-authored records, identified by exact module + qualname rather than
# a spoofable short class name. Tests bind this inventory to concrete classes.
EXECUTION_AUTHORITY_MODELS = frozenset(
    {
        ("agent_world.builder.models", "ImplementationContract"),
        ("agent_world.contracts.base", "ArtifactRef"),
        ("agent_world.contracts.jobs", "Budget"),
        ("agent_world.contracts.jobs", "BudgetUsage"),
        ("agent_world.contracts.jobs", "EnvironmentJob"),
        ("agent_world.contracts.jobs", "PermissionScope"),
        ("agent_world.contracts.jobs", "ReleaseProfile"),
        ("agent_world.contracts.judging", "Finding"),
        ("agent_world.contracts.judging", "GateResult"),
        ("agent_world.contracts.judging", "IntegrationReport"),
        ("agent_world.contracts.judging", "JudgeReport"),
        ("agent_world.contracts.package", "CandidateManifest"),
        ("agent_world.control.models", "BudgetLease"),
        ("agent_world.control.models", "JobRunSnapshot"),
        ("agent_world.control.models", "NodeAttempt"),
        ("agent_world.control.models", "RepairDirective"),
        ("agent_world.control.models", "RepairLedgerEntry"),
        ("agent_world.control.release_dossier", "ReleaseDossier"),
        ("agent_world.registry.models", "ReleaseRecord"),
    }
)

# Nested domain contracts may legitimately contain retry.maximum_attempts or a
# candidate-local argv. Every other occurrence below chooses Foundry flow.
EXECUTION_AUTHORITY_FIELDS = frozenset(
    {
        "blocks_release",
        "budget",
        "budget_lease",
        "budget_usage",
        "current_node",
        "destination",
        "gate_results",
        "hard",
        "invalidates",
        "jump_distance",
        "ledger_entry_id",
        "maximum_attempts",
        "next_node",
        "next_stage",
        "owner",
        "owner_node",
        "publish",
        "release_authorized",
        "release_ref",
        "release_verdict",
        "repair_action",
        "repair_attempts",
        "target_node",
        "verdict",
    }
)

_DOMAIN_FIELD_ALLOWLIST = frozenset(
    {
        ("agent_world.contracts.evidence", "Claim", "status"),
        ("agent_world.contracts.world", "RetrySemantics", "maximum_attempts"),
    }
)

_CAPABILITY_FORBIDDEN_FIELDS = {
    AgentOutputAuthority.SEMANTIC_ADVISORY: frozenset(
        {"action", "argv", "command", "path", "permissions", "status"}
    ),
    AgentOutputAuthority.WORKSPACE_PROPOSAL: frozenset(),
    AgentOutputAuthority.EPISODE_ACTION_PROPOSAL: frozenset(),
}


def _reachable_models(root: type[BaseModel]) -> tuple[type[BaseModel], ...]:
    pending = [root]
    seen: set[type[BaseModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        for field in model.model_fields.values():
            annotations = [field.annotation]
            while annotations:
                annotation = annotations.pop()
                if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                    pending.append(annotation)
                annotations.extend(get_args(annotation))
    return tuple(seen)


def assert_agent_output_advisory(
    model: type[BaseModel],
    *,
    authority: AgentOutputAuthority,
) -> None:
    """Fail closed before exposing an authority-bearing schema to an Agent.

    ``authority`` is mandatory so each exceptional proposal capability remains
    explicit: only Builder proposes candidate-local files/argv, and only the
    reachability Challenger proposes a Runtime action. Neither controls flow.
    """

    if not isinstance(model, type) or not issubclass(model, BaseModel):
        raise TypeError("Agent output must be a Pydantic model type")
    if not isinstance(authority, AgentOutputAuthority):
        raise TypeError("Agent output authority must use AgentOutputAuthority")

    registered = registered_agent_output_authority(model)
    if registered is not authority:
        actual = registered.value if registered is not None else "unregistered"
        raise AgentAuthorityViolation(
            f"{model.__name__} is registered for {actual}, not {authority.value}"
        )
    marker = authority_marker(authority)
    if not issubclass(model, marker):
        raise AgentAuthorityViolation(
            f"{model.__name__} does not inherit the {marker.__name__} capability marker"
        )

    reachable = _reachable_models(model)
    forbidden_models = sorted(
        f"{item.__module__}.{item.__qualname__}"
        for item in reachable
        if (item.__module__, item.__qualname__) in EXECUTION_AUTHORITY_MODELS
    )
    if forbidden_models:
        joined = ", ".join(dict.fromkeys(forbidden_models))
        raise AgentAuthorityViolation(
            f"{model.__name__} reaches framework execution contracts: {joined}"
        )

    forbidden_paths: list[str] = []
    for reachable_model in reachable:
        for field_name in reachable_model.model_fields:
            field_identity = (
                reachable_model.__module__,
                reachable_model.__qualname__,
                field_name,
            )
            if (
                field_name
                in (
                    EXECUTION_AUTHORITY_FIELDS
                    | _CAPABILITY_FORBIDDEN_FIELDS[authority]
                )
                and field_identity not in _DOMAIN_FIELD_ALLOWLIST
            ):
                forbidden_paths.append(
                    f"{reachable_model.__module__}.{reachable_model.__qualname__}.{field_name}"
                )
    forbidden_fields = sorted(set(forbidden_paths))
    if forbidden_fields:
        joined = ", ".join(forbidden_fields)
        raise AgentAuthorityViolation(
            f"{model.__name__} exposes framework execution fields: {joined}"
        )

__all__ = [
    "AgentAuthorityViolation",
    "AgentOutputAuthority",
    "EXECUTION_AUTHORITY_FIELDS",
    "EXECUTION_AUTHORITY_MODELS",
    "EpisodeActionProposalOutput",
    "SemanticAdvisoryOutput",
    "WorkspaceProposalOutput",
    "assert_agent_output_advisory",
    "register_agent_output_contract",
    "registered_agent_output_contracts",
]

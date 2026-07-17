"""Cycle-free identity registry for Agent-authored output capabilities."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel


class AgentOutputAuthority(StrEnum):
    """Closed proposal capabilities available to a real Agent invocation."""

    SEMANTIC_ADVISORY = "semantic_advisory"
    WORKSPACE_PROPOSAL = "workspace_proposal"
    EPISODE_ACTION_PROPOSAL = "episode_action_proposal"


class SemanticAdvisoryOutput:
    agent_output_authority: ClassVar[AgentOutputAuthority] = (
        AgentOutputAuthority.SEMANTIC_ADVISORY
    )


class WorkspaceProposalOutput:
    agent_output_authority: ClassVar[AgentOutputAuthority] = (
        AgentOutputAuthority.WORKSPACE_PROPOSAL
    )


class EpisodeActionProposalOutput:
    agent_output_authority: ClassVar[AgentOutputAuthority] = (
        AgentOutputAuthority.EPISODE_ACTION_PROPOSAL
    )


_AUTHORITY_MARKERS = {
    AgentOutputAuthority.SEMANTIC_ADVISORY: SemanticAdvisoryOutput,
    AgentOutputAuthority.WORKSPACE_PROPOSAL: WorkspaceProposalOutput,
    AgentOutputAuthority.EPISODE_ACTION_PROPOSAL: EpisodeActionProposalOutput,
}
_REGISTERED_OUTPUTS: dict[type[BaseModel], AgentOutputAuthority] = {}


def authority_marker(authority: AgentOutputAuthority) -> type[object]:
    return _AUTHORITY_MARKERS[authority]


def register_agent_output_contract(
    model: type[BaseModel],
    *,
    authority: AgentOutputAuthority,
) -> None:
    """Explicitly register one exact root model for one proposal capability."""

    if not isinstance(authority, AgentOutputAuthority):
        raise TypeError("Agent output authority must use AgentOutputAuthority")
    marker = authority_marker(authority)
    if not issubclass(model, marker):
        raise TypeError(
            f"{model.__module__}.{model.__qualname__} must inherit {marker.__name__}"
        )
    previous = _REGISTERED_OUTPUTS.get(model)
    if previous is not None and previous is not authority:
        raise ValueError(
            f"{model.__module__}.{model.__qualname__} is already registered for {previous.value}"
        )
    _REGISTERED_OUTPUTS[model] = authority


def registered_agent_output_authority(
    model: type[BaseModel],
) -> AgentOutputAuthority | None:
    return _REGISTERED_OUTPUTS.get(model)


def registered_agent_output_contracts() -> dict[type[BaseModel], AgentOutputAuthority]:
    return dict(_REGISTERED_OUTPUTS)


__all__ = [
    "AgentOutputAuthority",
    "EpisodeActionProposalOutput",
    "SemanticAdvisoryOutput",
    "WorkspaceProposalOutput",
    "authority_marker",
    "register_agent_output_contract",
    "registered_agent_output_authority",
    "registered_agent_output_contracts",
]

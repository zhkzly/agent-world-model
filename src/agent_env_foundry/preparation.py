"""EnvironmentRelease v2 preparation identities and projection protocols.

Checkpoint 1 freezes only the identity/projection contract.  Checkpoint 2 owns
locked installation, child processes, private transport and lifecycle behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Protocol, Self, runtime_checkable

from agent_env_foundry.environment import Environment, JSONObject
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.release import DESCRIPTOR_FORMAT_V2
from agent_env_foundry.semantics import TaskSemantics

ENVIRONMENT_RELEASE_V2_FORMAT = DESCRIPTOR_FORMAT_V2
_HEX = frozenset("0123456789abcdef")


class PreparationContractError(ValueError):
    """A prepared release/session value violates the v2 trust contract."""


@dataclass(frozen=True, slots=True)
class PublicReleaseIdentity:
    format: str
    release_id: str

    def __post_init__(self) -> None:
        _format(self.format)
        _digest(self.release_id, "release_id")

    def to_document(self) -> JSONObject:
        return {"format": self.format, "release_id": self.release_id}


@dataclass(frozen=True, slots=True)
class PreparedReleaseIdentity:
    format: str
    release_id: str
    actor_digest: str
    semantics_digest: str

    def __post_init__(self) -> None:
        _format(self.format)
        _digest(self.release_id, "release_id")
        _digest(self.actor_digest, "actor_digest")
        _digest(self.semantics_digest, "semantics_digest")

    def public_document(self) -> JSONObject:
        return PublicReleaseIdentity(self.format, self.release_id).to_document()

    def trusted_document(self) -> JSONObject:
        return {
            "format": self.format,
            "release_id": self.release_id,
            "actor_digest": self.actor_digest,
            "semantics_digest": self.semantics_digest,
        }


@dataclass(frozen=True, slots=True)
class PreparedSessionIdentity:
    release_id: str
    actor_digest: str
    semantics_digest: str
    materialization_id: str

    def __post_init__(self) -> None:
        _digest(self.release_id, "release_id")
        _digest(self.actor_digest, "actor_digest")
        _digest(self.semantics_digest, "semantics_digest")
        _digest(self.materialization_id, "materialization_id")

    def to_document(self) -> JSONObject:
        return {
            "release_id": self.release_id,
            "actor_digest": self.actor_digest,
            "semantics_digest": self.semantics_digest,
            "materialization_id": self.materialization_id,
        }


TrustedOperation = Literal[
    "start_cases",
    "inspect",
    "capabilities",
    "enumerate_bindings",
    "evaluate_atom",
    "evaluate_condition",
]
_TRUSTED_OPERATIONS = frozenset(
    {
        "start_cases",
        "inspect",
        "capabilities",
        "enumerate_bindings",
        "evaluate_atom",
        "evaluate_condition",
    }
)


@dataclass(frozen=True, slots=True)
class TrustedCallEvent:
    seq: int
    session: PreparedSessionIdentity
    operation: TrustedOperation
    request_digest: str
    response_digest: str
    before_tree_digest: str
    after_tree_digest: str

    def __post_init__(self) -> None:
        if self.seq <= 0:
            raise PreparationContractError("trusted call seq must be positive")
        if self.operation not in _TRUSTED_OPERATIONS:
            raise PreparationContractError("trusted call operation is invalid")
        for name in (
            "request_digest",
            "response_digest",
            "before_tree_digest",
            "after_tree_digest",
        ):
            _digest(getattr(self, name), name)

    @property
    def unchanged(self) -> bool:
        return self.before_tree_digest == self.after_tree_digest

    def to_document(self) -> JSONObject:
        return {
            "seq": self.seq,
            "session": self.session.to_document(),
            "operation": self.operation,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "before_tree_digest": self.before_tree_digest,
            "after_tree_digest": self.after_tree_digest,
            "unchanged": self.unchanged,
        }


@runtime_checkable
class PreparedSession(Protocol):
    identity: PreparedSessionIdentity
    actor: Environment
    trusted: TaskSemantics

    def close(self) -> None: ...
    def __enter__(self) -> Self: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


@runtime_checkable
class PreparedRelease(Protocol):
    identity: PreparedReleaseIdentity

    def open(self, instance_directory: Path) -> PreparedSession: ...


def parse_public_release_identity(document: Any) -> PublicReleaseIdentity:
    """Decode only the actor-visible identity; trusted fields are rejected."""

    if not is_json_object(document) or set(document) != {"format", "release_id"}:
        raise PreparationContractError(
            "public release identity must contain exactly format and release_id"
        )
    format_value = document["format"]
    release_id = document["release_id"]
    if not isinstance(format_value, str) or not isinstance(release_id, str):
        raise PreparationContractError("public release identity fields must be strings")
    return PublicReleaseIdentity(format_value, release_id)


def _format(value: str) -> None:
    if value != ENVIRONMENT_RELEASE_V2_FORMAT:
        raise PreparationContractError(
            f"prepared release format must be {ENVIRONMENT_RELEASE_V2_FORMAT!r}"
        )


def _digest(value: str, role: str) -> None:
    if len(value) != 64 or any(character not in _HEX for character in value):
        raise PreparationContractError(f"{role} must be a lowercase SHA-256 digest")

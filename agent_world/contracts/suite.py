"""Immutable consumption contracts for released EnvironmentPackages."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from .base import ContentHash, Identifier, NonEmptyStr, V2Contract


class CurriculumSamplingPolicy(V2Contract):
    """A small, executable policy whose result depends only on package data and seed."""

    protocol: Literal["agent-world.curriculum-policy.v2"] = "agent-world.curriculum-policy.v2"
    task_type_sampling: Literal["seeded_uniform"] = "seeded_uniform"
    actor_sampling: Literal["seeded_uniform"] = "seeded_uniform"
    difficulty_sampling: Literal["seeded_uniform"] = "seeded_uniform"
    maximum_steps: Annotated[int, Field(ge=1, le=10_000)] = 128


class SuiteSelectionRequest(V2Contract):
    """User selection before Registry binds immutable release hashes."""

    package_id: Identifier
    version: NonEmptyStr
    weight: Annotated[Decimal, Field(gt=0, max_digits=24, decimal_places=12)] = Decimal("1")
    curriculum_policy: CurriculumSamplingPolicy = Field(default_factory=CurriculumSamplingPolicy)


class SuitePackageSelection(SuiteSelectionRequest):
    """One exact immutable package member of a Suite snapshot."""

    package_digest: ContentHash
    manifest_hash: ContentHash


class _SuiteSnapshotBody(V2Contract):
    format: Literal["environment-suite-snapshot-v3"] = "environment-suite-snapshot-v3"
    created_at: AwareDatetime
    consumer_protocol: Literal["agent-world.local-consumer.v3"] = (
        "agent-world.local-consumer.v3"
    )
    packages: Annotated[tuple[SuitePackageSelection, ...], Field(min_length=1)]


class EnvironmentSuiteSnapshot(_SuiteSnapshotBody):
    """Content-addressed, immutable input to rollout/evaluation/training consumers."""

    snapshot_id: Identifier
    snapshot_digest: ContentHash

    @classmethod
    def create(
        cls,
        *,
        created_at: datetime,
        packages: tuple[SuitePackageSelection, ...],
    ) -> EnvironmentSuiteSnapshot:
        body = _SuiteSnapshotBody(created_at=created_at, packages=packages)
        digest = body.content_digest()
        return cls(
            **body.model_dump(mode="python"),
            snapshot_id=f"suite_{digest.removeprefix('sha256:')}",
            snapshot_digest=digest,
        )

    @model_validator(mode="after")
    def validate_identity(self) -> EnvironmentSuiteSnapshot:
        coordinates = [(item.package_id, item.version) for item in self.packages]
        if len(set(coordinates)) != len(coordinates):
            raise ValueError("Suite snapshot package coordinates must be unique")
        expected = _SuiteSnapshotBody(
            created_at=self.created_at,
            consumer_protocol=self.consumer_protocol,
            packages=self.packages,
        ).content_digest()
        expected_id = f"suite_{expected.removeprefix('sha256:')}"
        if self.snapshot_digest != expected or self.snapshot_id != expected_id:
            raise ValueError("Suite snapshot id/digest does not match canonical content")
        return self


class RolloutAction(V2Contract):
    tool_id: Identifier
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class PublicTask(V2Contract):
    """The only generated task projection visible to an Agent consumer."""

    task_schema_version: Literal["public-task-v3"] = "public-task-v3"
    seed: Annotated[int, Field(ge=0, le=2**64 - 1)]
    task_type: Identifier
    actor: Identifier
    public_instruction: NonEmptyStr
    public_goal: dict[str, JsonValue]
    difficulty: dict[str, JsonValue] = Field(default_factory=dict)


class RolloutReset(V2Contract):
    agent_view: JsonValue
    tools: tuple[dict[str, JsonValue], ...]
    state_digest: ContentHash
    reward: Annotated[float, Field(ge=0, le=0, allow_inf_nan=False)] = 0.0
    terminated: bool = False
    truncated: bool = False


class RolloutStep(V2Contract):
    step_index: Annotated[int, Field(ge=0)]
    action: RolloutAction
    agent_view: JsonValue
    state_digest: ContentHash
    reward: Annotated[float, Field(allow_inf_nan=False)]
    terminated: bool
    truncated: bool
    succeeded: bool
    failed: bool
    runtime_ok: bool
    runtime_error_code: str | None = None


class LocalEpisodeStart(V2Contract):
    protocol: Literal["agent-world.local-consumer.v3"] = "agent-world.local-consumer.v3"
    episode_id: Identifier
    snapshot_id: Identifier
    package: SuitePackageSelection
    task: PublicTask
    reset: RolloutReset


class LocalRolloutResult(V2Contract):
    protocol: Literal["agent-world.local-consumer.v3"] = "agent-world.local-consumer.v3"
    episode_id: Identifier
    snapshot_id: Identifier
    package: SuitePackageSelection
    task: PublicTask
    reset: RolloutReset
    steps: tuple[RolloutStep, ...]
    terminated: bool
    truncated: bool
    succeeded: bool
    failed: bool


class LocalEnvRpcError(V2Contract):
    code: Identifier
    message: NonEmptyStr


class LocalEnvRpcRequest(V2Contract):
    """One authenticated, bounded request to the single-session local env service."""

    protocol: Literal["agent-world.local-env-rpc.v3"] = "agent-world.local-env-rpc.v3"
    request_id: Identifier
    auth_token: Annotated[
        str,
        Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$"),
    ]
    operation: Literal["start", "step", "result", "close"]
    payload: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_operation_payload(self) -> LocalEnvRpcRequest:
        if self.operation == "step":
            RolloutAction.model_validate(self.payload)
        elif self.payload:
            raise ValueError(f"{self.operation} RPC payload must be empty")
        return self


class LocalEnvRpcResponse(V2Contract):
    """Response envelope that never carries service-owned private episode data."""

    protocol: Literal["agent-world.local-env-rpc.v3"] = "agent-world.local-env-rpc.v3"
    request_id: Identifier
    ok: bool
    result: JsonValue = None
    error: LocalEnvRpcError | None = None

    @model_validator(mode="after")
    def validate_result_or_error(self) -> LocalEnvRpcResponse:
        if self.ok:
            if self.result is None or self.error is not None:
                raise ValueError("successful RPC response requires only a result")
        elif self.result is not None or self.error is None:
            raise ValueError("failed RPC response requires only an error")
        return self


__all__ = [
    "CurriculumSamplingPolicy",
    "EnvironmentSuiteSnapshot",
    "LocalEnvRpcError",
    "LocalEnvRpcRequest",
    "LocalEnvRpcResponse",
    "LocalEpisodeStart",
    "LocalRolloutResult",
    "PublicTask",
    "RolloutAction",
    "RolloutReset",
    "RolloutStep",
    "SuitePackageSelection",
    "SuiteSelectionRequest",
]

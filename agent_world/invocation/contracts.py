"""Backend-neutral contracts for real Agent invocations.

This module deliberately contains no Codex SDK types.  The Foundry controller
owns workflow, repair, budget reservation, gates, and release decisions; an
``InvocationBackend`` only executes one already-resolved Agent turn and returns
auditable evidence about that execution.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .capabilities import EffectiveCapabilityPlan

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class SandboxMode(StrEnum):
    """The two sandbox modes production Agent profiles may request."""

    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"


class ReasoningEffort(StrEnum):
    """Backend-neutral reasoning effort supported by the pinned Codex SDK."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class InvocationStatus(StrEnum):
    """Terminal status of one backend invocation."""

    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    """Hard local limits enforced by the backend process supervisor."""

    timeout_seconds: float = 600.0
    interrupt_grace_seconds: float = 5.0
    kill_grace_seconds: float = 2.0
    max_events: int = 20_000
    max_protocol_bytes: int = 32 * 1024 * 1024
    max_stderr_bytes: int = 256 * 1024

    def __post_init__(self) -> None:
        for label, value in (
            ("timeout_seconds", self.timeout_seconds),
            ("interrupt_grace_seconds", self.interrupt_grace_seconds),
            ("kill_grace_seconds", self.kill_grace_seconds),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and positive")
        if not isinstance(self.max_events, int) or self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if not isinstance(self.max_protocol_bytes, int) or self.max_protocol_bytes < 128 * 1024:
            raise ValueError("max_protocol_bytes must be at least 128 KiB")
        if not isinstance(self.max_stderr_bytes, int) or self.max_stderr_bytes <= 0:
            raise ValueError("max_stderr_bytes must be positive")

    @property
    def supervisor_wall_ceiling_seconds(self) -> float:
        """Worst-case worker wall time including bounded termination handshakes."""

        return (
            self.timeout_seconds
            + self.interrupt_grace_seconds
            + 0.5
            + 2 * self.kill_grace_seconds
        )


@dataclass(frozen=True, slots=True)
class ResolvedBundle:
    """A content-addressed skill or hook bundle copied into CODEX_HOME."""

    kind: str
    name: str
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        if self.kind not in {"skill", "hook"}:
            raise ValueError(f"unsupported bundle kind: {self.kind!r}")
        if not self.name:
            raise ValueError("bundle name must not be empty")
        if len(self.sha256) != 64:
            raise ValueError("bundle sha256 must contain 64 hexadecimal characters")


@dataclass(frozen=True, slots=True)
class CredentialDescriptor:
    """Non-secret record of one credential made available to the worker."""

    handle: str
    target_environment: str | None
    purpose: str


@dataclass(frozen=True, slots=True)
class ResolvedAgentProfile:
    """Immutable, materialized execution profile.

    ``_credential_environment`` is intentionally private, omitted from
    ``to_public_dict`` and hidden from ``repr``.  It is a short-lived credential
    lease for the backend supervisor, not an artifact and not profile metadata.
    """

    profile_id: str
    profile_version: str
    profile_hash: str
    backend: str
    model: str
    model_provider: str | None
    openai_base_url: str | None
    reasoning_effort: ReasoningEffort
    base_instructions: str
    developer_instructions: str | None
    lineage_id: str
    materialization_root: Path
    home: Path
    codex_home: Path
    workspace: Path
    effective_capability_plan: EffectiveCapabilityPlan
    sandbox: SandboxMode
    allowed_builtin_tools: tuple[str, ...]
    allowed_network_domains: tuple[str, ...]
    skills: tuple[ResolvedBundle, ...]
    hooks: tuple[ResolvedBundle, ...]
    credential_descriptors: tuple[CredentialDescriptor, ...]
    authentication_kind: str
    authentication_environment: str | None
    codex_bin: Path | None
    codex_bin_sha256: str | None
    output_schema: JsonObject | None
    rollout_token_limit: int | None
    tool_output_token_limit: int
    limits: InvocationLimits
    codex_config_sha256: str
    hooks_config_sha256: str | None
    _credential_environment: Mapping[str, str] = field(repr=False, compare=False)
    _base_environment: Mapping[str, str] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.backend != "codex_sdk":
            raise ValueError("ResolvedAgentProfile only supports the codex_sdk backend")
        for label, value in (
            ("profile_id", self.profile_id),
            ("profile_version", self.profile_version),
            ("profile_hash", self.profile_hash),
            ("model", self.model),
            ("lineage_id", self.lineage_id),
        ):
            if not value:
                raise ValueError(f"{label} must not be empty")
        if len(self.profile_hash) != 64 or len(self.codex_config_sha256) != 64:
            raise ValueError("profile/config hashes must be sha256 hex digests")
        if self.hooks_config_sha256 is not None and len(self.hooks_config_sha256) != 64:
            raise ValueError("hooks config hash must be a sha256 hex digest")
        if bool(self.hooks) != (self.hooks_config_sha256 is not None):
            raise ValueError("hooks and hooks_config_sha256 must be present together")
        if (self.codex_bin is None) != (self.codex_bin_sha256 is None):
            raise ValueError("codex_bin and codex_bin_sha256 must be present together")
        if self.codex_bin is not None and not self.codex_bin.is_absolute():
            raise ValueError("configured Codex binary path must be absolute")
        if self.codex_bin_sha256 is not None and len(self.codex_bin_sha256) != 64:
            raise ValueError("Codex binary digest must be a sha256 hex digest")
        if self.authentication_kind not in {"api_key", "chatgpt"}:
            raise ValueError("authentication_kind must be api_key or chatgpt")
        if self.authentication_kind == "api_key" and not self.authentication_environment:
            raise ValueError("api_key authentication requires an environment name")
        if self.authentication_kind == "chatgpt" and self.authentication_environment is not None:
            raise ValueError("chatgpt authentication must not expose an environment name")
        if self.rollout_token_limit is not None and self.rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive when configured")
        if self.tool_output_token_limit <= 0:
            raise ValueError("tool_output_token_limit must be positive")
        if self.effective_capability_plan.role != self.profile_id:
            raise ValueError("effective capability role must match profile_id")
        if self.effective_capability_plan.sandbox is not self.sandbox:
            raise ValueError("effective capability sandbox must match the resolved profile")
        if self.effective_capability_plan.intrinsic_builtin_tools != self.allowed_builtin_tools:
            raise ValueError("effective intrinsic tools must match the resolved profile")
        if (
            self.effective_capability_plan.external.network_domains
            != self.allowed_network_domains
        ):
            raise ValueError("effective network domains must match the resolved profile")
        for root in (self.materialization_root, self.home, self.codex_home, self.workspace):
            if not root.is_absolute():
                raise ValueError(f"resolved path must be absolute: {root}")

    @property
    def secret_values(self) -> tuple[str, ...]:
        """Return redaction material to the backend without exposing it in repr."""

        return tuple(value for value in self._credential_environment.values() if value)

    def worker_environment(self) -> dict[str, str]:
        """Build the exact worker environment; no other ambient variables enter."""

        environment = dict(self._base_environment)
        environment.update(self._credential_environment)
        environment.update(
            {
                "HOME": str(self.home),
                "CODEX_HOME": str(self.codex_home),
                "AGENT_WORLD_PROFILE_HASH": self.profile_hash,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
            }
        )
        return environment

    def to_public_dict(self) -> JsonObject:
        """Serialize profile evidence without credential values."""

        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "profile_hash": self.profile_hash,
            "backend": self.backend,
            "model": self.model,
            "model_provider": self.model_provider,
            "openai_base_url": self.openai_base_url,
            "reasoning_effort": self.reasoning_effort.value,
            "lineage_id": self.lineage_id,
            "materialization_root": str(self.materialization_root),
            "home": str(self.home),
            "codex_home": str(self.codex_home),
            "workspace": str(self.workspace),
            "effective_capability_plan": self.effective_capability_plan.to_public_dict(),
            "sandbox": self.sandbox.value,
            "allowed_builtin_tools": list(self.allowed_builtin_tools),
            "allowed_network_domains": list(self.allowed_network_domains),
            "skills": [
                {"name": item.name, "path": str(item.path), "sha256": item.sha256}
                for item in self.skills
            ],
            "hooks": [
                {"name": item.name, "path": str(item.path), "sha256": item.sha256}
                for item in self.hooks
            ],
            "credential_handles": [item.handle for item in self.credential_descriptors],
            "authentication_kind": self.authentication_kind,
            "codex_bin": str(self.codex_bin) if self.codex_bin is not None else None,
            "codex_bin_sha256": self.codex_bin_sha256,
            "output_schema": self.output_schema,
            "rollout_token_limit": self.rollout_token_limit,
            "tool_output_token_limit": self.tool_output_token_limit,
            "codex_config_sha256": self.codex_config_sha256,
            "hooks_config_sha256": self.hooks_config_sha256,
        }


@dataclass(frozen=True, slots=True)
class InvocationSession:
    """Durable continuation reference bound to one workspace lineage."""

    thread_id: str
    lineage_id: str
    workspace: Path
    profile_hash: str
    codex_config_sha256: str

    def __post_init__(self) -> None:
        if not self.thread_id:
            raise ValueError("thread_id must not be empty")
        if not self.lineage_id:
            raise ValueError("lineage_id must not be empty")
        if not self.workspace.is_absolute():
            raise ValueError("session workspace must be absolute")
        if len(self.profile_hash) != 64 or len(self.codex_config_sha256) != 64:
            raise ValueError("session profile/config hashes must be sha256 hex digests")


@dataclass(frozen=True, slots=True)
class InvocationRequest:
    """One turn request sent to a resolved real-Agent profile."""

    invocation_id: str
    prompt: str
    profile: ResolvedAgentProfile
    session: InvocationSession | None = None
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.invocation_id:
            raise ValueError("invocation_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if self.session is not None:
            if self.session.lineage_id != self.profile.lineage_id:
                raise ValueError("continued session belongs to a different lineage")
            if self.session.workspace.resolve() != self.profile.workspace.resolve():
                raise ValueError("continued session must use the exact same workspace")
            if self.session.profile_hash != self.profile.profile_hash:
                raise ValueError("continued session must use the same resolved profile")
            if self.session.codex_config_sha256 != self.profile.codex_config_sha256:
                raise ValueError("continued session must use the exact same Codex configuration")


@dataclass(frozen=True, slots=True)
class TokenBreakdown:
    cached_input_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_output_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class InvocationUsage:
    turn: TokenBreakdown | None = None
    thread_total: TokenBreakdown | None = None
    model_context_window: int | None = None
    # Compatibility providers frequently expose token usage but no trustworthy
    # price.  `None` is intentional: callers must preserve it as unknown,
    # rather than manufacturing a zero-dollar observation.
    monetary_cost: float | None = None

    def __post_init__(self) -> None:
        if self.monetary_cost is not None and (
            not math.isfinite(self.monetary_cost) or self.monetary_cost < 0
        ):
            raise ValueError("monetary_cost must be finite and non-negative when reported")


@dataclass(frozen=True, slots=True)
class InvocationEvent:
    sequence: int
    method: str
    payload: JsonObject


@dataclass(frozen=True, slots=True)
class InvocationError:
    code: str
    message: str
    retryable: bool = False
    details: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class InvocationResult:
    """Auditable terminal result returned by a backend adapter."""

    invocation_id: str
    status: InvocationStatus
    session: InvocationSession | None
    turn_id: str | None
    final_text: str | None
    structured_output: JsonValue | None
    usage: InvocationUsage | None
    events: tuple[InvocationEvent, ...]
    error: InvocationError | None
    duration_ms: int
    backend_version: str | None = None
    worker_exit_code: int | None = None

    @property
    def succeeded(self) -> bool:
        return self.status is InvocationStatus.COMPLETED


@runtime_checkable
class InvocationBackend(Protocol):
    """Contract implemented by real Agent adapters only."""

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        """Framework execution protocols the adapter can actually honor."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        """Execute one new or continued Agent turn."""

    async def cancel(self, invocation_id: str) -> bool:
        """Cancel a live invocation, returning whether it existed."""


def json_compatible(value: Any) -> JsonValue:
    """Validate and normalize the small JSON value domain used by contracts."""

    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, list) or isinstance(value, tuple):
        return [json_compatible(item) for item in value]
    if isinstance(value, Mapping):
        output: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            output[key] = json_compatible(item)
        return output
    raise TypeError(f"value is not JSON-compatible: {type(value).__name__}")

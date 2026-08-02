"""Backend-neutral contracts for real Agent invocations.

This module deliberately contains no Codex SDK types.  The Foundry controller
owns workflow, repair, budget reservation, gates, and release decisions; an
``InvocationBackend`` only executes one already-resolved Agent turn and returns
auditable evidence about that execution.
"""

from __future__ import annotations

import math
import re
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

_SAFE_CONTROL_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class SandboxMode(StrEnum):
    """The one Codex SDK execution mode used by production Agent profiles.

    Agent World no longer implements a filesystem namespace or a workspace
    sandbox.  The SDK still requires an explicit execution-mode value, so every
    tool-enabled Agent turn uses its supported full-host mode.
    """

    FULL_ACCESS = "full-access"


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


class InvocationExecutionMode(StrEnum):
    """The declared interaction shape for one invocation request.

    The default is deliberately agentic and therefore routes to the Codex SDK.
    A caller must opt in to ``SINGLE_SHOT_STRUCTURED`` before a profile with no
    tools can use the direct Responses adapter; this prevents a first turn of a
    future continuation from silently losing its session semantics.
    """

    AGENTIC = "agentic"
    SINGLE_SHOT_STRUCTURED = "single_shot_structured"


class InvocationLifecycleSupervision(StrEnum):
    """Which trusted parent owns the declared physical lifecycle wall.

    Adapters retain a self-supervised mode for direct, standalone use.  Once a
    request is admitted by :class:`InvocationControlPlane`, however, that
    control plane is the *only* parent-side lifecycle supervisor.  This is
    private execution wiring, never runtime-Agent input or worker payload.
    """

    ADAPTER = "adapter"
    CONTROL_PLANE = "control_plane"


class InvocationOwnerKind(StrEnum):
    """The durable authority that owns one physical invocation attempt.

    This is deliberately about execution ownership, not Agent semantics.  It
    lets the invocation layer leave a safe recovery fact without exposing a
    Prompt, private session, workspace path, or provider response.
    """

    WORK_OPERATION = "work_operation"
    DIAGNOSTIC_AUDIT = "diagnostic_audit"
    STANDALONE_COMPONENT = "standalone_component"


class InvocationLifecyclePhase(StrEnum):
    """Closed local lifecycle facts emitted independently of Provider events."""

    QUEUED = "queued"
    ADMITTED = "admitted"
    PROFILE_VERIFYING = "profile_verifying"
    PROFILE_VERIFIED = "profile_verified"
    WORKER_SPAWNED = "worker_spawned"
    PAYLOAD_DISPATCHED = "payload_dispatched"
    SDK_SESSION_OPEN = "sdk_session_open"
    THREAD_START = "thread_start"
    THREAD_RESUME = "thread_resume"
    TURN_START = "turn_start"
    TURN_STREAM = "turn_stream"
    PARENT_WAITING = "parent_waiting"
    WORKER_EXITED = "worker_exited"
    DIRECT_DISPATCHED = "direct_dispatched"
    DIRECT_AWAITING_RESPONSE = "direct_awaiting_response"
    DIRECT_STREAM_OPENED = "direct_stream_opened"
    DIRECT_AWAITING_STREAM_EVENT = "direct_awaiting_stream_event"
    CANCEL_REQUESTED = "cancel_requested"
    DECLARED_WALL_EXPIRED = "declared_wall_expired"
    CLEANUP_RUNNING = "cleanup_running"
    CLEANUP_FINISHED = "cleanup_finished"
    TERMINAL_RECEIVED = "terminal_received"
    OWNER_LOST = "owner_lost"


@dataclass(frozen=True, slots=True)
class InvocationOwnership:
    """Safe identity of the controller-side owner of one physical turn.

    ``owner_id`` and ``scope_id`` are framework identifiers, not user text or
    provider/session identifiers.  The optional closure digest lets retry and
    fallback policy later prove that a current node retained its committed
    parent closure without putting those Artifacts into a provider request.
    """

    owner_kind: InvocationOwnerKind
    owner_id: str
    scope_id: str
    coordinate: str | None = None
    immutable_input_closure_digest: str | None = None

    def __post_init__(self) -> None:
        for label, value in (("owner_id", self.owner_id), ("scope_id", self.scope_id)):
            if not _SAFE_CONTROL_IDENTIFIER.fullmatch(value):
                raise ValueError(f"{label} must be a safe bounded framework identifier")
        if self.coordinate is not None and not _SAFE_CONTROL_IDENTIFIER.fullmatch(self.coordinate):
            raise ValueError("coordinate must be a safe bounded framework identifier when present")
        digest = self.immutable_input_closure_digest
        if digest is not None and (
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("immutable_input_closure_digest must be a sha256 hex digest")

    def to_safe_dict(self) -> JsonObject:
        """Return only the durable ownership facts safe for a control record."""

        return {
            "owner_kind": self.owner_kind.value,
            "owner_id": self.owner_id,
            "scope_id": self.scope_id,
            "coordinate": self.coordinate,
            "immutable_input_closure_digest": self.immutable_input_closure_digest,
        }


@runtime_checkable
class InvocationLifecycleSink(Protocol):
    """Receive framework-local lifecycle facts without entering model input."""

    def local(self, phase: InvocationLifecyclePhase) -> None:
        """Record one closed local adapter/supervisor phase."""

    def provider_progress(self, activity: str = "provider_event") -> None:
        """Record a real Provider event without its payload or text."""


@dataclass(frozen=True, slots=True)
class InvocationLimits:
    """Hard local limits enforced by the backend process supervisor."""

    timeout_seconds: float = 600.0
    # This is deliberately not a second logical-turn or output-token ceiling.
    # Every Provider adapter applies it only after a Provider stream has
    # already emitted an event and then goes silent.  ``None`` retains the
    # declared lifecycle behavior for that stream.
    provider_stream_idle_timeout_seconds: float | None = 300.0
    # Time-to-first-Provider-event is a TRANSPORT liveness bound shared by the
    # Direct and Codex adapters, not a limit on how long a model may think.
    # Before the first validated event nothing has been produced to wait for:
    # a stream or worker that opens and never speaks is indistinguishable from
    # a dropped transport, and previously held an 8h logical wall with no
    # retryable terminal.  Once an event arrives this bound retires; reasoning
    # and post-progress work remain governed by ``timeout_seconds`` and any
    # adapter-specific idle policy.  ``None`` restores the old behavior.
    provider_first_event_timeout_seconds: float | None = 120.0
    interrupt_grace_seconds: float = 5.0
    kill_grace_seconds: float = 2.0
    max_events: int = 20_000
    max_protocol_bytes: int = 32 * 1024 * 1024
    max_stderr_bytes: int = 256 * 1024
    # Bounded provider-level transport retries the backend SDK may spend before
    # a Provider event is observed.  See ``AgentConfig.provider_transport_max_retries``.
    provider_transport_max_retries: int = 0

    def __post_init__(self) -> None:
        for label, value in (
            ("timeout_seconds", self.timeout_seconds),
            ("interrupt_grace_seconds", self.interrupt_grace_seconds),
            ("kill_grace_seconds", self.kill_grace_seconds),
        ):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and positive")
        for optional_label, optional_value in (
            ("provider_stream_idle_timeout_seconds", self.provider_stream_idle_timeout_seconds),
            ("provider_first_event_timeout_seconds", self.provider_first_event_timeout_seconds),
        ):
            if optional_value is not None and (
                not isinstance(optional_value, (int, float))
                or not math.isfinite(optional_value)
                or optional_value <= 0
            ):
                raise ValueError(f"{optional_label} must be finite and positive")
        if not isinstance(self.max_events, int) or self.max_events <= 0:
            raise ValueError("max_events must be positive")
        if (
            not isinstance(self.provider_transport_max_retries, int)
            or isinstance(self.provider_transport_max_retries, bool)
            or self.provider_transport_max_retries < 0
        ):
            raise ValueError("provider_transport_max_retries must be a non-negative integer")
        if not isinstance(self.max_protocol_bytes, int) or self.max_protocol_bytes < 128 * 1024:
            raise ValueError("max_protocol_bytes must be at least 128 KiB")
        if not isinstance(self.max_stderr_bytes, int) or self.max_stderr_bytes <= 0:
            raise ValueError("max_stderr_bytes must be positive")

    @property
    def supervisor_wall_ceiling_seconds(self) -> float:
        """Worst-case worker wall time including bounded termination handshakes."""

        return (
            self.timeout_seconds + self.interrupt_grace_seconds + 0.5 + 2 * self.kill_grace_seconds
        )


@dataclass(frozen=True, slots=True)
class ResolvedBundle:
    """One content-addressed Runtime Skill copied into CODEX_HOME."""

    kind: str
    name: str
    path: Path
    sha256: str

    def __post_init__(self) -> None:
        if self.kind != "skill":
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
    openai_base_url_environment: str | None
    reasoning_effort: ReasoningEffort
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
    credential_descriptors: tuple[CredentialDescriptor, ...]
    authentication_kind: str
    authentication_environment: str | None
    codex_bin: Path | None
    codex_bin_sha256: str | None
    output_schema: JsonObject | None
    rollout_token_limit: int | None
    # Optional Direct Responses API request cap.  Unlike the framework rollout
    # budget this is omitted from the HTTP request when ``None``.
    direct_provider_max_output_tokens: int | None
    tool_output_token_limit: int
    limits: InvocationLimits
    codex_config_sha256: str
    _credential_environment: Mapping[str, str] = field(repr=False, compare=False)
    _base_environment: Mapping[str, str] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.backend not in {"codex_sdk", "direct_llm"}:
            raise ValueError("ResolvedAgentProfile backend must be codex_sdk or direct_llm")
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
        if (self.codex_bin is None) != (self.codex_bin_sha256 is None):
            raise ValueError("codex_bin and codex_bin_sha256 must be present together")
        if self.codex_bin is not None and not self.codex_bin.is_absolute():
            raise ValueError("configured Codex binary path must be absolute")
        if self.codex_bin_sha256 is not None and len(self.codex_bin_sha256) != 64:
            raise ValueError("Codex binary digest must be a sha256 hex digest")
        if self.authentication_kind != "api_key":
            raise ValueError(
                "ResolvedAgentProfile only supports API-key environment authentication"
            )
        if not self.authentication_environment:
            raise ValueError("api_key authentication requires an environment name")
        if (
            self.openai_base_url_environment is not None
            and self.openai_base_url_environment != "OPENAI_BASE_URL"
        ):
            raise ValueError("openai_base_url_environment must be OPENAI_BASE_URL")
        if self.rollout_token_limit is not None and self.rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive when configured")
        if (
            self.direct_provider_max_output_tokens is not None
            and self.direct_provider_max_output_tokens <= 0
        ):
            raise ValueError("direct_provider_max_output_tokens must be positive when configured")
        if self.tool_output_token_limit <= 0:
            raise ValueError("tool_output_token_limit must be positive")
        if self.effective_capability_plan.role != self.profile_id:
            raise ValueError("effective capability role must match profile_id")
        if self.sandbox is not SandboxMode.FULL_ACCESS:
            raise ValueError("Agent profiles must use Codex full-access execution")
        if self.effective_capability_plan.sandbox is not self.sandbox:
            raise ValueError("effective capability execution mode must match the resolved profile")
        if self.effective_capability_plan.intrinsic_builtin_tools != self.allowed_builtin_tools:
            raise ValueError("effective intrinsic tools must match the resolved profile")
        if self.effective_capability_plan.external.network_domains != self.allowed_network_domains:
            raise ValueError("effective network domains must match the resolved profile")
        for root in (self.materialization_root, self.home, self.codex_home, self.workspace):
            if not root.is_absolute():
                raise ValueError(f"resolved path must be absolute: {root}")

    @property
    def secret_values(self) -> tuple[str, ...]:
        """Return redaction material to the backend without exposing it in repr."""

        return tuple(value for value in self._credential_environment.values() if value)

    @property
    def sensitive_environment_names(self) -> tuple[str, ...]:
        """Return only safe names for worker-side redaction materialization."""

        return tuple(sorted(self._credential_environment))

    def worker_environment(self) -> dict[str, str]:
        """Build the exact worker environment; no other ambient variables enter."""

        environment = dict(self._base_environment)
        environment.update(self._credential_environment)
        if self.backend == "direct_llm":
            # The Direct adapter runs in-process and passes model credentials
            # to the Provider client explicitly. It never starts Codex, so a
            # HOME/CODEX_HOME pair would be unused ambient-looking state.
            return environment
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
            "openai_base_url_environment": self.openai_base_url_environment,
            "reasoning_effort": self.reasoning_effort.value,
            "lineage_id": self.lineage_id,
            "materialization_root": str(self.materialization_root),
            "home": str(self.home) if self.backend == "codex_sdk" else None,
            "codex_home": str(self.codex_home) if self.backend == "codex_sdk" else None,
            "workspace": str(self.workspace),
            "effective_capability_plan": self.effective_capability_plan.to_public_dict(),
            "sandbox": self.sandbox.value,
            "allowed_builtin_tools": list(self.allowed_builtin_tools),
            "allowed_network_domains": list(self.allowed_network_domains),
            "skills": [
                {"name": item.name, "path": str(item.path), "sha256": item.sha256}
                for item in self.skills
            ],
            "credential_handles": [item.handle for item in self.credential_descriptors],
            "authentication_kind": self.authentication_kind,
            "codex_bin": (
                str(self.codex_bin)
                if self.backend == "codex_sdk" and self.codex_bin is not None
                else None
            ),
            "codex_bin_sha256": self.codex_bin_sha256 if self.backend == "codex_sdk" else None,
            "output_schema": self.output_schema,
            "rollout_token_limit": self.rollout_token_limit,
            "direct_provider_max_output_tokens": self.direct_provider_max_output_tokens,
            "tool_output_token_limit": self.tool_output_token_limit,
            "codex_config_sha256": (
                self.codex_config_sha256 if self.backend == "codex_sdk" else None
            ),
        }


@dataclass(frozen=True, slots=True)
class InvocationSession:
    """Continuation reference bound to one workspace lineage.

    The reference itself may be retained in framework-private recovery state,
    but a Codex thread id alone is not proof that a newly created adapter can
    resume it. The adapter must also possess the matching private runtime
    checkpoint; otherwise it returns a typed unavailable result and the
    control plane may choose an explicit fresh-session repair, if authorized.
    """

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
    execution_mode: InvocationExecutionMode = InvocationExecutionMode.AGENTIC
    ownership: InvocationOwnership | None = None
    # This callback is private parent-side control-plane wiring.  It is not
    # serialized into the worker payload and never becomes runtime Agent input.
    lifecycle_sink: InvocationLifecycleSink | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    lifecycle_supervision: InvocationLifecycleSupervision = field(
        default=InvocationLifecycleSupervision.ADAPTER,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if not self.invocation_id:
            raise ValueError("invocation_id must not be empty")
        if not self.prompt.strip():
            raise ValueError("prompt must not be empty")
        if self.execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED:
            if self.session is not None:
                raise ValueError("single-shot structured requests cannot resume a session")
            if self.profile.allowed_builtin_tools:
                raise ValueError("single-shot structured requests cannot declare builtin tools")
            if self.profile.output_schema is None:
                raise ValueError("single-shot structured requests require an output schema")
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

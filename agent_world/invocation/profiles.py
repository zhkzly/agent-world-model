"""Agent profile recipes and materialization.

``ProfileResolver`` is the only place where host paths and credential handles
become an executable profile. It uses a private ``CODEX_HOME`` to keep
credentials off disk and to mount the selected Runtime Skill; it does not
create a filesystem namespace or a workspace sandbox.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlparse

from .capabilities import EffectiveCapabilityPlan
from .contracts import (
    CredentialDescriptor,
    InvocationLimits,
    JsonObject,
    ReasoningEffort,
    ResolvedAgentProfile,
    ResolvedBundle,
    SandboxMode,
    json_compatible,
)
from .runtime_provider import API_KEY_RUNTIME_PROVIDER, OPENAI_BASE_URL_ENVIRONMENT

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DOMAIN = re.compile(r"^(?:\*|(?:(?:\*|\*\*)\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")
_SENSITIVE_NAME = re.compile(
    r"(?:api[_-]?key|auth(?:entication|orization)?|bearer|cookie|credential|password|private[_-]?key|secret|session|token)",
    re.IGNORECASE,
)
_SAFE_BASE_ENVIRONMENT_NAMES = frozenset(
    {"PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR"}
)
_SUPPORTED_BUILTIN_TOOLS = frozenset({"shell", "workspace_edit"})
_CONTROL_PATHS = (".codex", ".agents", "AGENTS.md")
_PROJECT_ROOT_MARKER = ".agent-world-project-root"


class ProfileResolutionError(RuntimeError):
    """Raised when a requested profile cannot be materialized safely."""


class CredentialResolutionError(ProfileResolutionError):
    """Raised for missing, undeclared, or conflicting credential handles."""


def safe_profile_resolution_category(error: ProfileResolutionError) -> str:
    """Project a local profile failure into a closed, message-free category.

    Profile resolution runs before an invocation exists, so its exception cannot
    be handed to the Provider-terminal diagnostic path. Raw messages can
    include workspace paths or credential-handle names, while an opaque type is
    too weak to tell a project-execution Agent which control-plane surface to
    inspect. Keep only the few categories that change that next investigation.
    """

    if isinstance(error, CredentialResolutionError):
        return "credential_binding"
    message = str(error)
    if message == "Direct profile cannot declare a Codex runtime":
        return "direct_inherited_agent_runtime"
    if message.startswith("Direct profile cannot declare") or message.startswith(
        "Direct profile must not request"
    ):
        return "direct_capability_boundary"
    if message.startswith("Direct profile requires"):
        return "direct_runtime_contract"
    if message.startswith("Direct workspace") or message.startswith("Direct profile workspace"):
        return "direct_workspace_integrity"
    if message.startswith("Direct profile root") or message.startswith(
        "materialization root is already bound"
    ):
        return "profile_materialization_binding"
    if "control path" in message or "configuration" in message:
        return "profile_configuration_binding"
    if "modified" in message or "changed" in message or "unavailable" in message:
        return "profile_integrity"
    return "profile_resolution_other"


class McpTransport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


@dataclass(frozen=True, slots=True)
class SkillBundleSpec:
    name: str
    source: Path
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_name("skill", self.name)


@dataclass(frozen=True, slots=True)
class CredentialBinding:
    """Map a logical handle to one explicitly allowed host environment value."""

    handle: str
    source_environment: str
    target_environment: str
    purpose: str

    def __post_init__(self) -> None:
        _validate_name("credential handle", self.handle)
        for label, value in (
            ("source_environment", self.source_environment),
            ("target_environment", self.target_environment),
        ):
            if not _ENVIRONMENT_NAME.fullmatch(value):
                raise ValueError(f"invalid {label}: {value!r}")
        if self.purpose not in {"model_api_key", "mcp", "tool"}:
            raise ValueError(f"unsupported credential purpose: {self.purpose!r}")


@dataclass(frozen=True, slots=True)
class CodexLoginBinding:
    """Legacy file-backed login descriptor.

    It remains import-compatible only so callers receive a deterministic
    fail-closed error from :class:`ProfileResolver`.  Agent World no longer
    materializes auth files: credentials and routing are environment-handle
    only.
    """

    handle: str
    source: Path = field(repr=False)
    purpose: str = "codex_login"

    def __post_init__(self) -> None:
        _validate_name("credential handle", self.handle)
        if self.purpose != "codex_login":
            raise ValueError("CodexLoginBinding purpose must be codex_login")


@dataclass(frozen=True, slots=True)
class McpServerSpec:
    """Typed, allowlisted MCP server configuration."""

    name: str
    transport: McpTransport
    enabled_tools: tuple[str, ...]
    command: str | None = None
    args: tuple[str, ...] = ()
    url: str | None = None
    cwd: str | None = None
    credential_handles: tuple[str, ...] = ()
    bearer_token_handle: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    required: bool = True
    startup_timeout_seconds: float = 10.0
    tool_timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        _validate_name("MCP server", self.name)
        if not self.enabled_tools:
            raise ValueError(f"MCP server {self.name!r} requires a non-empty tool allowlist")
        _ensure_unique(f"MCP {self.name} enabled tool", self.enabled_tools)
        _ensure_unique(f"MCP {self.name} credential handle", self.credential_handles)
        if self.transport is McpTransport.STDIO:
            if not self.command or self.url is not None or self.bearer_token_handle is not None:
                raise ValueError("stdio MCP requires command and forbids url/bearer_token_handle")
            if any(_SENSITIVE_NAME.search(argument) for argument in self.args):
                raise ValueError(
                    "MCP command arguments must not embed authentication options; use handles"
                )
        elif self.transport is McpTransport.HTTP:
            if not self.url or self.command is not None or self.args or self.cwd is not None:
                raise ValueError("HTTP MCP requires url and forbids command/args/cwd")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"https", "http"} or not parsed.hostname:
                raise ValueError(f"invalid MCP HTTP URL: {self.url!r}")
            if parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError(
                    "MCP HTTP URL must not contain userinfo, query credentials, or fragments"
                )
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
            for value in (self.startup_timeout_seconds, self.tool_timeout_seconds)
        ):
            raise ValueError("MCP timeouts must be finite and positive")
        for key, value in self.environment.items():
            if not _ENVIRONMENT_NAME.fullmatch(key):
                raise ValueError(f"invalid MCP environment name: {key!r}")
            if _SENSITIVE_NAME.search(key) or _looks_secret(value):
                raise ValueError(
                    "MCP static environment must not contain secrets; use credential handles"
                )


@dataclass(frozen=True, slots=True)
class AgentProfileSpec:
    """Unresolved, versioned recipe for one dedicated Agent role."""

    profile_id: str
    profile_version: str
    model: str
    authentication_handle: str
    effective_capability_plan: EffectiveCapabilityPlan
    codex_bin: Path | None = None
    codex_bin_sha256: str | None = None
    model_provider: str | None = None
    openai_base_url_environment: str | None = None
    reasoning_effort: ReasoningEffort = ReasoningEffort.HIGH
    sandbox: SandboxMode = SandboxMode.FULL_ACCESS
    allowed_builtin_tools: tuple[str, ...] = ()
    allowed_network_domains: tuple[str, ...] = ()
    skills: tuple[SkillBundleSpec, ...] = ()
    mcp_servers: tuple[McpServerSpec, ...] = ()
    credential_handles: tuple[str, ...] = ()
    output_schema: JsonObject | None = None
    rollout_token_limit: int | None = None
    # An optional physical Provider request cap.  This is intentionally
    # separate from ``rollout_token_limit``, which stays framework-owned.
    direct_provider_max_output_tokens: int | None = None
    tool_output_token_limit: int = 2_048
    limits: InvocationLimits = field(default_factory=InvocationLimits)

    def __post_init__(self) -> None:
        _validate_name("profile_id", self.profile_id)
        _validate_name("profile_version", self.profile_version)
        if not self.model:
            raise ValueError("model must not be empty")
        if self.effective_capability_plan.role != self.profile_id:
            raise ValueError("effective capability role must match profile_id")
        if (self.codex_bin is None) != (self.codex_bin_sha256 is None):
            raise ValueError("codex_bin and codex_bin_sha256 must be present together")
        if self.codex_bin is not None and not self.codex_bin.is_absolute():
            raise ValueError("codex_bin must be absolute")
        if self.codex_bin_sha256 is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.codex_bin_sha256
        ):
            raise ValueError("codex_bin_sha256 must be lowercase sha256 hex")
        if self.openai_base_url_environment is not None:
            if self.openai_base_url_environment != OPENAI_BASE_URL_ENVIRONMENT:
                raise ValueError(
                    "openai_base_url_environment must be the OPENAI_BASE_URL environment name"
                )
            if self.model_provider != API_KEY_RUNTIME_PROVIDER:
                raise ValueError(
                    "a runtime base-URL environment requires the framework-owned API-key provider"
                )
        _ensure_unique("builtin tool", self.allowed_builtin_tools)
        unknown_tools = set(self.allowed_builtin_tools) - _SUPPORTED_BUILTIN_TOOLS
        if unknown_tools:
            raise ValueError(f"unsupported builtin tools: {sorted(unknown_tools)!r}")
        if self.sandbox is not SandboxMode.FULL_ACCESS:
            raise ValueError("Agent profiles must use Codex full-access execution")
        if self.sandbox is not self.effective_capability_plan.sandbox:
            raise ValueError("execution mode must equal the effective capability plan")
        if self.allowed_builtin_tools != (self.effective_capability_plan.intrinsic_builtin_tools):
            raise ValueError("builtin tools must equal the effective intrinsic capability set")
        if self.allowed_network_domains != (
            self.effective_capability_plan.external.network_domains
        ):
            raise ValueError("network domains must equal the effective capability set")
        external_handles = set(self.credential_handles) - {self.authentication_handle}
        if external_handles != set(self.effective_capability_plan.external.credential_handles):
            raise ValueError("external credential handles must equal the effective capability set")
        if self.mcp_servers or self.effective_capability_plan.external.tool_allowlist:
            raise ValueError(
                "external Agent tools require a framework ToolBroker mapping; none is configured"
            )
        unsupported_external = self.effective_capability_plan.external
        if (
            unsupported_external.filesystem_read_roots
            or unsupported_external.filesystem_write_roots
            or unsupported_external.executable_allowlist
            or unsupported_external.allow_external_side_effects
        ):
            raise ValueError(
                "external filesystem, executable, and side-effect capabilities require a "
                "framework broker mapping; none is configured"
            )
        _ensure_unique("network domain", self.allowed_network_domains)
        for domain in self.allowed_network_domains:
            if not _DOMAIN.fullmatch(domain):
                raise ValueError(f"invalid network domain: {domain!r}")
        _ensure_unique("skill", (item.name for item in self.skills))
        _ensure_unique("MCP server", (item.name for item in self.mcp_servers))
        _ensure_unique("credential handle", self.credential_handles)
        if self.authentication_handle not in self.credential_handles:
            raise ValueError("authentication_handle must be present in credential_handles")
        referenced_handles = {
            handle
            for server in self.mcp_servers
            for handle in (*server.credential_handles, server.bearer_token_handle)
            if handle is not None
        }
        missing = referenced_handles - set(self.credential_handles)
        if missing:
            raise ValueError(
                f"MCP servers reference undeclared credential handles: {sorted(missing)}"
            )
        if self.output_schema is not None:
            normalized = json_compatible(self.output_schema)
            if not isinstance(normalized, dict):
                raise TypeError("output_schema must be a JSON object")
        if self.rollout_token_limit is not None and self.rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive when configured")
        if (
            self.direct_provider_max_output_tokens is not None
            and self.direct_provider_max_output_tokens <= 0
        ):
            raise ValueError("direct_provider_max_output_tokens must be positive when configured")
        if self.tool_output_token_limit <= 0:
            raise ValueError("tool_output_token_limit must be positive")


class ProfileResolver:
    """Materialize one hermetic profile and its private worker environment."""

    def __init__(
        self,
        *,
        credential_bindings: Mapping[str, CredentialBinding | CodexLoginBinding],
        allowed_credential_handles: tuple[str, ...] | list[str] | set[str],
        base_environment_names: tuple[str, ...] = (
            "PATH",
            "LANG",
            "LC_ALL",
            "TZ",
            "SSL_CERT_FILE",
            "SSL_CERT_DIR",
        ),
        max_bundle_files: int = 2_000,
        max_bundle_bytes: int = 32 * 1024 * 1024,
    ) -> None:
        self._bindings: dict[str, CredentialBinding | CodexLoginBinding] = dict(credential_bindings)
        self._allowed_handles = frozenset(allowed_credential_handles)
        self._base_environment_names = tuple(base_environment_names)
        self._max_bundle_files = max_bundle_files
        self._max_bundle_bytes = max_bundle_bytes
        if any(isinstance(binding, CodexLoginBinding) for binding in self._bindings.values()):
            raise ValueError(
                "file-backed Codex login is forbidden; use an API-key environment handle"
            )
        if not self._allowed_handles:
            raise ValueError("allowed_credential_handles must be explicit and non-empty")
        unknown_environment_names = set(self._base_environment_names) - _SAFE_BASE_ENVIRONMENT_NAMES
        if unknown_environment_names:
            raise ValueError(
                "base_environment_names contains values outside the fixed non-secret allowlist: "
                f"{sorted(unknown_environment_names)!r}"
            )
        if self._allowed_handles - self._bindings.keys():
            raise ValueError("allowed credential handle has no binding")
        target_names = [
            binding.target_environment
            for item in self._allowed_handles
            if isinstance((binding := self._bindings[item]), CredentialBinding)
        ]
        _ensure_unique("credential target environment", target_names)
        if max_bundle_files <= 0 or max_bundle_bytes <= 0:
            raise ValueError("bundle limits must be positive")

    def resolve(
        self,
        spec: AgentProfileSpec,
        *,
        lineage_id: str,
        materialization_root: Path,
        workspace: Path | None = None,
        source_environment: Mapping[str, str] | None = None,
    ) -> ResolvedAgentProfile:
        """Resolve paths, bundles, config and credential handles without fallback."""

        _validate_name("lineage_id", lineage_id)
        source_environment = os.environ if source_environment is None else source_environment
        requested_handles = set(spec.credential_handles)
        forbidden = requested_handles - self._allowed_handles
        if forbidden:
            raise CredentialResolutionError(
                "profile requested credential handles outside the resolver policy: "
                f"{sorted(forbidden)}"
            )

        root = materialization_root.expanduser().resolve()
        resolved_workspace = (workspace or root / "workspace").expanduser().resolve()
        if not resolved_workspace.is_relative_to(root):
            raise ProfileResolutionError("workspace must be inside materialization_root")
        workspace_relative = resolved_workspace.relative_to(root)
        if not workspace_relative.parts or workspace_relative.parts[0] in {
            "home",
            "codex-home",
        }:
            raise ProfileResolutionError(
                "workspace must be a dedicated descendant outside reserved runtime directories"
            )
        self._reject_ambient_configuration(root)
        self._make_private_directory(root)
        home = root / "home"
        codex_home = root / "codex-home"
        self._make_private_directory(home)
        self._make_private_directory(codex_home)
        self._make_private_directory(resolved_workspace)
        self._make_private_directory(resolved_workspace / ".agent-world-tmp")
        self._make_private_directory(resolved_workspace / ".agent-world-tmp" / "home")
        self._make_private_directory(resolved_workspace / ".agent-world-tmp" / "cache")
        self._make_private_directory(resolved_workspace / ".agent-world-tmp" / "uv-cache")
        self._reject_workspace_configuration(resolved_workspace)
        root_marker = resolved_workspace / _PROJECT_ROOT_MARKER
        if root_marker.exists():
            if root_marker.is_symlink() or not root_marker.is_file():
                raise ProfileResolutionError("workspace root marker was replaced")
            if root_marker.read_bytes():
                raise ProfileResolutionError("workspace root marker was modified")
        else:
            _atomic_write_bytes(root_marker, b"", mode=0o400)

        source_skills: list[tuple[str, Path, str]] = []
        for skill_bundle in spec.skills:
            digest = self._hash_bundle(skill_bundle.source)
            self._check_expected_hash(
                "skill", skill_bundle.name, digest, skill_bundle.expected_sha256
            )
            source_skills.append((skill_bundle.name, skill_bundle.source, digest))

        bindings = {handle: self._bindings[handle] for handle in spec.credential_handles}
        auth_binding = bindings[spec.authentication_handle]
        if (
            not isinstance(auth_binding, CredentialBinding)
            or auth_binding.purpose != "model_api_key"
        ):
            raise CredentialResolutionError(
                "authentication_handle must resolve to a model_api_key environment binding"
            )
        credential_environment: dict[str, str] = {}
        for handle, binding in bindings.items():
            if isinstance(binding, CodexLoginBinding):
                raise CredentialResolutionError(
                    "file-backed Codex login is forbidden; use an API-key environment handle"
                )
            value = source_environment.get(binding.source_environment)
            if value is None or not value:
                raise CredentialResolutionError(
                    f"credential handle {handle!r} is unavailable from its configured source"
                )
            if len(value) < 5:
                raise CredentialResolutionError(
                    f"credential handle {handle!r} is too short for safe redaction"
                )
            credential_environment[binding.target_environment] = value

        base_url_digest: str | None = None
        if spec.openai_base_url_environment is not None:
            base_url = source_environment.get(spec.openai_base_url_environment)
            if base_url is None or not base_url:
                raise CredentialResolutionError(
                    "configured API base-URL environment is unavailable"
                )
            _validate_runtime_base_url(base_url)
            credential_environment[spec.openai_base_url_environment] = base_url
            base_url_digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()

        for server in spec.mcp_servers:
            for referenced_handle in (
                *server.credential_handles,
                server.bearer_token_handle,
            ):
                if referenced_handle is None:
                    continue
                binding = bindings[referenced_handle]
                if not isinstance(binding, CredentialBinding) or binding.purpose not in {
                    "mcp",
                    "tool",
                }:
                    raise CredentialResolutionError(
                        f"MCP server {server.name!r} requires an mcp/tool environment binding"
                    )

        profile_hash = _canonical_hash(
            {
                "profile_id": spec.profile_id,
                "profile_version": spec.profile_version,
                "model": spec.model,
                "model_provider": spec.model_provider,
                "openai_base_url_environment": spec.openai_base_url_environment,
                "openai_base_url_value_digest": base_url_digest,
                "reasoning_effort": spec.reasoning_effort.value,
                "effective_capability_plan": (spec.effective_capability_plan.to_public_dict()),
                "sandbox": spec.sandbox.value,
                "allowed_builtin_tools": list(spec.allowed_builtin_tools),
                "allowed_network_domains": list(spec.allowed_network_domains),
                "bundles": [
                    {"kind": "skill", "name": name, "sha256": digest}
                    for name, _source, digest in source_skills
                ],
                "mcp_servers": [_mcp_public_dict(server) for server in spec.mcp_servers],
                "credential_handles": list(spec.credential_handles),
                "authentication_handle": spec.authentication_handle,
                "codex_bin_sha256": spec.codex_bin_sha256,
                "authentication_kind": "api_key",
                "output_schema": spec.output_schema,
                "rollout_token_limit": spec.rollout_token_limit,
                "direct_provider_max_output_tokens": spec.direct_provider_max_output_tokens,
                "tool_output_token_limit": spec.tool_output_token_limit,
                "limits": {
                    "timeout_seconds": spec.limits.timeout_seconds,
                    "provider_stream_idle_timeout_seconds": (
                        spec.limits.provider_stream_idle_timeout_seconds
                    ),
                    "provider_first_event_timeout_seconds": (
                        spec.limits.provider_first_event_timeout_seconds
                    ),
                    "interrupt_grace_seconds": spec.limits.interrupt_grace_seconds,
                    "kill_grace_seconds": spec.limits.kill_grace_seconds,
                    "max_events": spec.limits.max_events,
                    "max_protocol_bytes": spec.limits.max_protocol_bytes,
                    "max_stderr_bytes": spec.limits.max_stderr_bytes,
                },
            }
        )

        marker_path = root / "resolved-profile.json"
        if marker_path.exists():
            marker = _read_json_object(marker_path)
            expected = {
                "profile_hash": profile_hash,
                "lineage_id": lineage_id,
                "workspace": str(resolved_workspace),
            }
            actual = {key: marker.get(key) for key in expected}
            if actual != expected:
                raise ProfileResolutionError(
                    "materialization root is already bound to a different profile or lineage"
                )

        resolved_skills: list[ResolvedBundle] = []
        for name, source, digest in source_skills:
            # Codex discovers local Skills from its own home ``skills/`` tree.
            # ``skills.config`` only controls an already discovered Skill; it
            # does not make an arbitrary external bundle a model-visible
            # Skill.  Materialize the verified read-only bundle at the actual
            # discovery root so the runtime Agent receives its name,
            # description, and SKILL.md path in the turn's Skill catalog.
            destination = codex_home / "skills" / name
            self._copy_verified_bundle(source, destination, digest)
            resolved = ResolvedBundle(kind="skill", name=name, path=destination, sha256=digest)
            if not (destination / "SKILL.md").is_file():
                raise ProfileResolutionError(f"skill {name!r} has no SKILL.md")
            resolved_skills.append(resolved)

        shell_environment = self._base_environment(source_environment)
        shell_environment.update(
            {
                "HOME": str(resolved_workspace / ".agent-world-tmp" / "home"),
                "TMPDIR": str(resolved_workspace / ".agent-world-tmp"),
                "UV_CACHE_DIR": str(resolved_workspace / ".agent-world-tmp" / "uv-cache"),
                "XDG_CACHE_HOME": str(resolved_workspace / ".agent-world-tmp" / "cache"),
            }
        )
        config_text = _render_codex_config(
            spec,
            workspace=resolved_workspace,
            bindings={
                handle: binding
                for handle, binding in bindings.items()
                if isinstance(binding, CredentialBinding)
            },
            shell_environment=shell_environment,
        )
        config_path = codex_home / "config.toml"
        _atomic_write_text(config_path, config_text, mode=0o600)
        config_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest()

        base_environment = self._base_environment(source_environment)
        base_environment["TMPDIR"] = str(resolved_workspace / ".agent-world-tmp")
        descriptors = tuple(
            CredentialDescriptor(
                handle=handle,
                target_environment=(
                    binding.target_environment if isinstance(binding, CredentialBinding) else None
                ),
                purpose=binding.purpose,
            )
            for handle, binding in bindings.items()
        )
        resolved_profile = ResolvedAgentProfile(
            profile_id=spec.profile_id,
            profile_version=spec.profile_version,
            profile_hash=profile_hash,
            backend="codex_sdk",
            model=spec.model,
            model_provider=spec.model_provider,
            openai_base_url_environment=spec.openai_base_url_environment,
            reasoning_effort=spec.reasoning_effort,
            lineage_id=lineage_id,
            materialization_root=root,
            home=home,
            codex_home=codex_home,
            workspace=resolved_workspace,
            effective_capability_plan=spec.effective_capability_plan,
            sandbox=spec.sandbox,
            allowed_builtin_tools=tuple(spec.allowed_builtin_tools),
            allowed_network_domains=tuple(spec.allowed_network_domains),
            skills=tuple(resolved_skills),
            credential_descriptors=descriptors,
            authentication_kind="api_key",
            authentication_environment=auth_binding.target_environment,
            codex_bin=spec.codex_bin,
            codex_bin_sha256=spec.codex_bin_sha256,
            output_schema=spec.output_schema,
            rollout_token_limit=spec.rollout_token_limit,
            direct_provider_max_output_tokens=spec.direct_provider_max_output_tokens,
            tool_output_token_limit=spec.tool_output_token_limit,
            limits=spec.limits,
            codex_config_sha256=config_hash,
            _credential_environment=MappingProxyType(credential_environment),
            _base_environment=MappingProxyType(base_environment),
        )
        _atomic_write_json(
            marker_path,
            {
                "schema_version": "agent-world.resolved-agent-profile.v1",
                "profile_hash": profile_hash,
                "lineage_id": lineage_id,
                "workspace": str(resolved_workspace),
                "profile": resolved_profile.to_public_dict(),
            },
            mode=0o600,
        )
        return resolved_profile

    def resolve_direct(
        self,
        spec: AgentProfileSpec,
        *,
        lineage_id: str,
        materialization_root: Path,
        workspace: Path | None = None,
        source_environment: Mapping[str, str] | None = None,
    ) -> ResolvedAgentProfile:
        """Resolve a prompt-only Direct LLM profile without a Codex runtime.

        A Direct turn needs a model route, a rendered Prompt, a native output
        schema, and the model credential. It must not silently acquire a
        CODEX_HOME, Skill bundle, workspace input copy, hook, or
        Codex executable merely because both execution forms share control
        plane provenance. The tiny marker below is integrity evidence for the
        framework; it is never model-visible configuration.
        """

        _validate_name("lineage_id", lineage_id)
        source_environment = os.environ if source_environment is None else source_environment
        if spec.allowed_builtin_tools:
            raise ProfileResolutionError("Direct profile cannot declare builtin tools")
        if spec.skills or spec.mcp_servers:
            raise ProfileResolutionError("Direct profile cannot declare runtime bundles or MCP")
        if spec.codex_bin is not None or spec.codex_bin_sha256 is not None:
            raise ProfileResolutionError("Direct profile cannot declare a Codex runtime")
        if spec.sandbox is not SandboxMode.FULL_ACCESS:
            raise ProfileResolutionError("Direct profile must use the shared full-access mode")
        if any(spec.effective_capability_plan.external.to_public_dict().values()):
            raise ProfileResolutionError("Direct profile cannot declare external capabilities")
        if spec.output_schema is None:
            raise ProfileResolutionError("Direct profile requires an output schema")
        if spec.model_provider != API_KEY_RUNTIME_PROVIDER:
            raise ProfileResolutionError("Direct profile requires the API-key runtime provider")
        if tuple(spec.credential_handles) != (spec.authentication_handle,):
            raise CredentialResolutionError(
                "Direct profile may expose only its model authentication handle"
            )

        binding = self._bindings.get(spec.authentication_handle)
        if (
            not isinstance(binding, CredentialBinding)
            or binding.purpose != "model_api_key"
            or spec.authentication_handle not in self._allowed_handles
        ):
            raise CredentialResolutionError(
                "Direct authentication handle must resolve to an allowed model API-key binding"
            )
        api_key = source_environment.get(binding.source_environment)
        if api_key is None or not api_key:
            raise CredentialResolutionError(
                f"credential handle {binding.handle!r} is unavailable from its configured source"
            )
        if len(api_key) < 5:
            raise CredentialResolutionError(
                f"credential handle {binding.handle!r} is too short for safe redaction"
            )
        base_url: str | None = None
        base_url_digest: str | None = None
        if spec.openai_base_url_environment is not None:
            base_url = source_environment.get(spec.openai_base_url_environment)
            if base_url is None or not base_url:
                raise CredentialResolutionError(
                    "configured API base-URL environment is unavailable"
                )
            _validate_runtime_base_url(base_url)
            base_url_digest = hashlib.sha256(base_url.encode("utf-8")).hexdigest()

        root = materialization_root.expanduser().resolve()
        resolved_workspace = (workspace or root / "workspace").expanduser().resolve()
        if not resolved_workspace.is_relative_to(root):
            raise ProfileResolutionError("Direct workspace must be inside materialization_root")
        if resolved_workspace == root:
            raise ProfileResolutionError("Direct workspace must be a dedicated descendant")
        workspace_relative = resolved_workspace.relative_to(root)
        if workspace_relative.parts[0] in {"home", "codex-home", "bundles"}:
            raise ProfileResolutionError("Direct workspace uses a reserved runtime directory")
        self._reject_ambient_configuration(root)
        self._make_private_directory(root)
        for unused_runtime_path in (
            root / "home",
            root / "codex-home",
            root / "bundles",
        ):
            if unused_runtime_path.exists() or unused_runtime_path.is_symlink():
                raise ProfileResolutionError(
                    "Direct profile root contains unexpected Agent runtime material"
                )
        self._make_private_directory(resolved_workspace)
        if any(resolved_workspace.iterdir()):
            raise ProfileResolutionError("Direct profile workspace must remain empty")
        for control_path in _CONTROL_PATHS:
            if (root / control_path).exists() or (resolved_workspace / control_path).exists():
                raise ProfileResolutionError("Direct profile cannot inherit Agent control files")

        direct_runtime_hash = _canonical_hash(
            {
                "runtime": "direct_llm.prompt_only.v1",
                "model": spec.model,
                "model_provider": spec.model_provider,
                "openai_base_url_environment": spec.openai_base_url_environment,
                "openai_base_url_value_digest": base_url_digest,
                "reasoning_effort": spec.reasoning_effort.value,
                "effective_capability_plan": spec.effective_capability_plan.to_public_dict(),
                "output_schema": spec.output_schema,
                "rollout_token_limit": spec.rollout_token_limit,
                "direct_provider_max_output_tokens": spec.direct_provider_max_output_tokens,
                "limits": {
                    "timeout_seconds": spec.limits.timeout_seconds,
                    "provider_stream_idle_timeout_seconds": (
                        spec.limits.provider_stream_idle_timeout_seconds
                    ),
                    "provider_first_event_timeout_seconds": (
                        spec.limits.provider_first_event_timeout_seconds
                    ),
                    "max_events": spec.limits.max_events,
                },
            }
        )
        profile_hash = _canonical_hash(
            {
                "profile_id": spec.profile_id,
                "profile_version": spec.profile_version,
                # A Direct profile has no session or workspace capability.  Its
                # profile hash must therefore identify the stable prompt-only
                # runtime configuration, not this physical WorkAttempt's
                # lineage.  The resolved-profile marker below still binds the
                # exact lineage and workspace.  Keeping lineage in this hash
                # made a fresh, Scheduler-authorized semantic repair reject a
                # valid parsed seed before the model was called, despite the
                # model, response schema, and Direct runtime all matching.
                "direct_runtime_hash": direct_runtime_hash,
                "credential_handles": [spec.authentication_handle],
            }
        )
        marker_path = root / "resolved-profile.json"
        if marker_path.exists():
            marker = _read_json_object(marker_path)
            expected = {
                "profile_hash": profile_hash,
                "lineage_id": lineage_id,
                "workspace": str(resolved_workspace),
            }
            if {key: marker.get(key) for key in expected} != expected:
                raise ProfileResolutionError(
                    "materialization root is already bound to a different Direct profile or lineage"
                )

        profile = ResolvedAgentProfile(
            profile_id=spec.profile_id,
            profile_version=spec.profile_version,
            profile_hash=profile_hash,
            backend="direct_llm",
            model=spec.model,
            model_provider=spec.model_provider,
            openai_base_url_environment=spec.openai_base_url_environment,
            reasoning_effort=spec.reasoning_effort,
            lineage_id=lineage_id,
            materialization_root=root,
            # Kept as inert absolute paths while Agent and Direct share the
            # profile record type. DirectLlmBackend never exports or opens
            # either path; direct verification asserts they do not exist.
            home=root / "home",
            codex_home=root / "codex-home",
            workspace=resolved_workspace,
            effective_capability_plan=spec.effective_capability_plan,
            sandbox=spec.sandbox,
            allowed_builtin_tools=(),
            allowed_network_domains=(),
            skills=(),
            credential_descriptors=(
                CredentialDescriptor(
                    handle=spec.authentication_handle,
                    target_environment=binding.target_environment,
                    purpose=binding.purpose,
                ),
            ),
            authentication_kind="api_key",
            authentication_environment=binding.target_environment,
            codex_bin=None,
            codex_bin_sha256=None,
            output_schema=spec.output_schema,
            rollout_token_limit=spec.rollout_token_limit,
            direct_provider_max_output_tokens=spec.direct_provider_max_output_tokens,
            tool_output_token_limit=spec.tool_output_token_limit,
            limits=spec.limits,
            # This is an inert direct-runtime fingerprint kept only because
            # the shared immutable profile record has an Agent session binding
            # field. It is never exposed as a Codex configuration or used by a
            # Direct request.
            codex_config_sha256=direct_runtime_hash,
            _credential_environment=MappingProxyType(
                {
                    binding.target_environment: api_key,
                    **(
                        {spec.openai_base_url_environment: base_url}
                        if spec.openai_base_url_environment is not None and base_url is not None
                        else {}
                    ),
                }
            ),
            _base_environment=MappingProxyType({}),
        )
        _atomic_write_json(
            marker_path,
            {
                "schema_version": "agent-world.resolved-direct-profile.v1",
                "profile_hash": profile_hash,
                "lineage_id": lineage_id,
                "workspace": str(resolved_workspace),
                "profile": profile.to_public_dict(),
            },
            mode=0o600,
        )
        return profile

    def _base_environment(self, source: Mapping[str, str]) -> dict[str, str]:
        return {
            name: source[name]
            for name in self._base_environment_names
            if name in source and source[name]
        }

    def _reject_ambient_configuration(self, root: Path) -> None:
        # The custom marker written into the workspace terminates Codex project
        # discovery before any ancestor can participate.  Reject control files
        # already present in the materialization root itself, but do not reject
        # an otherwise safe root merely because a shared ancestor (for example
        # /tmp) contains an unrelated project.
        for name in _CONTROL_PATHS:
            if (root / name).exists():
                raise ProfileResolutionError(
                    f"materialization root contains an undeclared Agent control path: {root / name}"
                )

    @staticmethod
    def _reject_workspace_configuration(workspace: Path) -> None:
        for name in _CONTROL_PATHS:
            if (workspace / name).exists():
                raise ProfileResolutionError(
                    f"workspace contains undeclared Agent control path: {workspace / name}"
                )

    @staticmethod
    def _make_private_directory(path: Path) -> None:
        if path.is_symlink():
            raise ProfileResolutionError(f"profile directory must not be a symlink: {path}")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.chmod(0o700)

    def _hash_bundle(self, source: Path) -> str:
        source = source.expanduser().resolve()
        if not source.is_dir() or source.is_symlink():
            raise ProfileResolutionError(f"bundle source must be a real directory: {source}")
        digest = hashlib.sha256()
        file_count = 0
        total_bytes = 0
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            if path.is_symlink():
                raise ProfileResolutionError(f"bundle may not contain symlinks: {path}")
            relative = path.relative_to(source).as_posix()
            if path.is_dir():
                digest.update(f"D\0{relative}\0".encode())
                continue
            if not path.is_file():
                raise ProfileResolutionError(
                    f"bundle contains unsupported filesystem entry: {path}"
                )
            file_count += 1
            size = path.stat().st_size
            total_bytes += size
            if file_count > self._max_bundle_files or total_bytes > self._max_bundle_bytes:
                raise ProfileResolutionError("bundle exceeds configured file or byte limits")
            digest.update(f"F\0{relative}\0{size}\0".encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _check_expected_hash(kind: str, name: str, actual: str, expected: str | None) -> None:
        if expected is not None and actual != expected:
            raise ProfileResolutionError(
                f"{kind} bundle {name!r} hash mismatch: expected {expected}, got {actual}"
            )

    def _copy_verified_bundle(self, source: Path, destination: Path, digest: str) -> None:
        if destination.exists():
            if destination.is_symlink() or self._hash_bundle(destination) != digest:
                raise ProfileResolutionError(f"materialized bundle was modified: {destination}")
            return
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = destination.with_name(f".{destination.name}.copying")
        if temporary.exists():
            shutil.rmtree(temporary)
        shutil.copytree(source.resolve(), temporary, symlinks=False)
        for path in (temporary, *temporary.rglob("*")):
            if path.is_symlink():
                shutil.rmtree(temporary)
                raise ProfileResolutionError(f"copied bundle contains a symlink: {path}")
            if path.is_dir():
                path.chmod(0o500)
            elif path.is_file():
                executable = bool(path.stat().st_mode & 0o111)
                path.chmod(0o500 if executable else 0o400)
        temporary.replace(destination)


def _render_codex_config(
    spec: AgentProfileSpec,
    *,
    workspace: Path,
    bindings: Mapping[str, CredentialBinding],
    shell_environment: Mapping[str, str],
) -> str:
    # KEEP THIS FILE SMALL. Codex ships working defaults for its tools and
    # permissions; every line written here overrides one of them, and each
    # override is a place where a generated profile can disagree with the runtime
    # that actually executes it.  A previous version emitted ~83 lines -- 21
    # feature flags, a hand-rebuilt shell environment, and a domain allowlist --
    # and the observable result was tools that existed but could not work,
    # which failed silently and had to be
    # re-diagnosed per node.  Runtime tools are never named here at all: the Codex
    # runtime owns which of its tools exist, and a second copy of that decision in
    # generated config can only disagree with it.
    #
    # Only three things justify an override, because the framework's own
    # guarantees depend on them:
    #   1. no interactive approval -- there is no human at this terminal;
    #   2. credentials never reach disk -- the provider key stays in the worker's
    #      memory and must not be materialized into a Codex auth file;
    #   3. plugin discovery stays off -- verified Runtime Skills live directly
    #      under this private CODEX_HOME's local Skill discovery root, while
    #      ambient plugin marketplaces must never synchronize or execute.
    #      Besides widening the effective Agent surface, the latter has
    #      produced a real app-server startup liveness failure.
    # Everything else is the SDK's business.  Do not re-add flags defensively.
    lines = [
        'approval_policy = "never"',
        # The worker supplies its custom provider through the per-thread SDK
        # request config.  Disallow Codex's file credential store so an
        # accidental login path cannot materialize auth.json here.
        'cli_auth_credentials_store = "keyring"',
        # These two define where the workspace *is*.  Without them Codex walks up
        # from cwd, finds the checkout that launched it, and treats that as the
        # project -- it then reports the repository's .codex as untrusted project
        # config and the session fails to open.  The marker names the disposable
        # workspace as its own project root so nothing above it is in scope.
        f"project_root_markers = [{_toml_string(_PROJECT_ROOT_MARKER)}]",
        "project_doc_max_bytes = 0",
        "",
        "[features]",
        "plugins = false",
    ]
    if spec.rollout_token_limit is not None:
        reminder_thresholds = (
            [] if spec.rollout_token_limit == 1 else [max(1, spec.rollout_token_limit // 10)]
        )
        lines.extend(
            [
                "rollout_budget.enabled = true",
                f"rollout_budget.limit_tokens = {spec.rollout_token_limit}",
                "rollout_budget.reminder_at_remaining_tokens = "
                f"{json.dumps(reminder_thresholds, separators=(',', ':'))}",
                "rollout_budget.sampling_token_weight = 1.0",
                "rollout_budget.prefill_token_weight = 1.0",
            ]
        )
    # The shell keeps ``inherit = "none"`` for one non-negotiable reason: the
    # parent environment holds the provider credential, which must never reach a
    # subprocess or a snapshot.  The few values below are what a shell needs to
    # function at all (a normal host PATH and a writable temp/cache inside the
    # workspace), not a policy.
    lines.extend(
        [
            "",
            "[shell_environment_policy]",
            'inherit = "none"',
            "",
            "[shell_environment_policy.set]",
        ]
    )
    for name, value in sorted(shell_environment.items()):
        lines.append(f"{_toml_key(name)} = {_toml_string(value)}")

    # Declaring the workspace as a project prevents Codex from treating the
    # Foundry checkout as the Agent's project. It is orientation only: the
    # worker selects SDK ``Sandbox.full_access`` explicitly for every Agent turn.
    lines.extend(
        [
            "",
            f"[projects.{_toml_string(str(workspace))}]",
            'trust_level = "untrusted"',
        ]
    )

    for server in spec.mcp_servers:
        lines.extend(["", f"[mcp_servers.{_toml_key(server.name)}]"])
        if server.transport is McpTransport.STDIO:
            lines.append(f"command = {_toml_string(str(server.command))}")
            if server.args:
                args = [_expand_workspace(item, workspace) for item in server.args]
                lines.append(f"args = {_toml_array(args)}")
            if server.cwd:
                cwd = Path(_expand_workspace(server.cwd, workspace)).expanduser().resolve()
                if not cwd.is_relative_to(workspace):
                    raise ProfileResolutionError(
                        f"MCP server {server.name!r} cwd must remain within the workspace"
                    )
                lines.append(f"cwd = {_toml_string(str(cwd))}")
            credential_environment = [
                bindings[handle].target_environment for handle in server.credential_handles
            ]
            if credential_environment:
                lines.append(f"env_vars = {_toml_array(credential_environment)}")
        else:
            parsed = urlparse(str(server.url))
            if not _domain_allowed(parsed.hostname or "", spec.allowed_network_domains):
                raise ProfileResolutionError(
                    f"MCP server {server.name!r} URL is outside allowed_network_domains"
                )
            lines.append(f"url = {_toml_string(str(server.url))}")
            if server.bearer_token_handle:
                lines.append(
                    "bearer_token_env_var = "
                    + _toml_string(bindings[server.bearer_token_handle].target_environment)
                )
        lines.extend(
            [
                f"enabled_tools = {_toml_array(server.enabled_tools)}",
                f"required = {_toml_bool(server.required)}",
                f"startup_timeout_sec = {server.startup_timeout_seconds}",
                f"tool_timeout_sec = {server.tool_timeout_seconds}",
                'default_tools_approval_mode = "approve"',
            ]
        )
        if server.environment:
            lines.extend(["", f"[mcp_servers.{_toml_key(server.name)}.env]"])
            for name, value in sorted(server.environment.items()):
                lines.append(f"{_toml_key(name)} = {_toml_string(value)}")

    return "\n".join(lines) + "\n"


def _mcp_public_dict(server: McpServerSpec) -> JsonObject:
    return {
        "name": server.name,
        "transport": server.transport.value,
        "enabled_tools": list(server.enabled_tools),
        "command": server.command,
        "args": list(server.args),
        "url": server.url,
        "cwd": server.cwd,
        "credential_handles": list(server.credential_handles),
        "bearer_token_handle": server.bearer_token_handle,
        "environment": dict(server.environment),
        "required": server.required,
        "startup_timeout_seconds": server.startup_timeout_seconds,
        "tool_timeout_seconds": server.tool_timeout_seconds,
    }


def _domain_allowed(hostname: str, allowed: tuple[str, ...]) -> bool:
    hostname = hostname.lower().rstrip(".")
    for rule in allowed:
        normalized = rule.lower().rstrip(".")
        if normalized == "*":
            return True
        if normalized.startswith("**."):
            suffix = normalized[3:]
            if hostname == suffix or hostname.endswith(f".{suffix}"):
                return True
        elif normalized.startswith("*."):
            suffix = normalized[1:]
            if hostname.endswith(suffix) and hostname != suffix[1:]:
                return True
        elif hostname == normalized:
            return True
    return False


def _expand_workspace(value: str, workspace: Path) -> str:
    return value.replace("${WORKSPACE}", str(workspace))


def _validate_name(label: str, value: str) -> None:
    if not _SAFE_NAME.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")


def _ensure_unique(label: str, values: Iterable[str]) -> None:
    sequence: tuple[str, ...] = tuple(values)
    if len(set(sequence)) != len(sequence):
        raise ValueError(f"duplicate {label}")


def _looks_secret(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("sk-") or lowered.startswith("bearer ") or "private key" in lowered


def _canonical_hash(value: Mapping[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _read_json_object(path: Path) -> JsonObject:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ProfileResolutionError(f"cannot read JSON object {path}: {exc}") from exc
    try:
        normalized = json_compatible(value)
    except TypeError as exc:
        raise ProfileResolutionError(f"invalid JSON object {path}: {exc}") from exc
    if not isinstance(normalized, dict):
        raise ProfileResolutionError(f"expected JSON object in {path}")
    return normalized


def _atomic_write_text(path: Path, content: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.chmod(mode)
    temporary.replace(path)


def _atomic_write_bytes(path: Path, content: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(content)
    temporary.chmod(mode)
    temporary.replace(path)


def _validate_runtime_base_url(value: str) -> None:
    """Validate a routing value without ever reflecting it in diagnostics."""

    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise CredentialResolutionError("configured API base URL has an invalid port") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port is not None
        and not 0 < port < 65536
    ):
        raise CredentialResolutionError("configured API base URL has an unsafe shape")


def _atomic_write_json(path: Path, content: Mapping[str, object], *, mode: int) -> None:
    _atomic_write_text(
        path,
        json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        mode=mode,
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_key(value: str) -> str:
    return value if _SAFE_NAME.fullmatch(value) else _toml_string(value)


def _toml_array(values: tuple[str, ...] | list[str]) -> str:
    return "[" + ", ".join(_toml_string(value) for value in values) + "]"


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def verify_resolved_profile(profile: ResolvedAgentProfile) -> None:
    """Fail if materialized capabilities or control files changed after resolution."""

    root = profile.materialization_root.resolve()
    if root != profile.materialization_root or root.is_symlink():
        raise ProfileResolutionError("materialization root identity changed")
    if not profile.workspace.resolve().is_relative_to(root):
        raise ProfileResolutionError("resolved workspace escaped its materialization root")
    if profile.backend == "direct_llm":
        _verify_direct_profile(profile, root)
        return
    if profile.backend != "codex_sdk":  # pragma: no cover - dataclass already closes this value
        raise ProfileResolutionError("resolved profile has an unsupported backend")
    for path in (profile.home, profile.codex_home, profile.workspace):
        if not path.is_dir() or path.is_symlink():
            raise ProfileResolutionError(f"resolved directory is missing or replaced: {path}")
    for name in _CONTROL_PATHS:
        if (profile.workspace / name).exists():
            raise ProfileResolutionError(
                f"workspace contains an undeclared Agent control path: {profile.workspace / name}"
            )
        if (root / name).exists():
            raise ProfileResolutionError(
                f"materialization root contains an undeclared Agent control path: {root / name}"
            )
    root_marker = profile.workspace / _PROJECT_ROOT_MARKER
    if not root_marker.is_file() or root_marker.is_symlink() or root_marker.read_bytes():
        raise ProfileResolutionError("workspace root marker is missing or modified")

    config_path = profile.codex_home / "config.toml"
    try:
        config_hash = hashlib.sha256(config_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProfileResolutionError(f"cannot read materialized Codex config: {exc}") from exc
    if config_hash != profile.codex_config_sha256:
        raise ProfileResolutionError("materialized Codex config was modified")
    auth_path = profile.codex_home / "auth.json"
    if auth_path.exists() or auth_path.is_symlink():
        raise ProfileResolutionError("file-backed Codex authentication is forbidden")
    if profile.codex_bin is not None:
        if profile.codex_bin.is_symlink() or not profile.codex_bin.is_file():
            raise ProfileResolutionError("configured Codex binary is unavailable")
        if not os.access(profile.codex_bin, os.X_OK):
            raise ProfileResolutionError("configured Codex binary is not executable")
        if _hash_file(profile.codex_bin) != profile.codex_bin_sha256:
            raise ProfileResolutionError("configured Codex binary changed after resolution")

    marker = _read_json_object(root / "resolved-profile.json")
    expected_marker = {
        "schema_version": "agent-world.resolved-agent-profile.v1",
        "profile_hash": profile.profile_hash,
        "lineage_id": profile.lineage_id,
        "workspace": str(profile.workspace),
        "profile": profile.to_public_dict(),
    }
    if {key: marker.get(key) for key in expected_marker} != expected_marker:
        raise ProfileResolutionError("resolved profile marker was modified")

    for bundle in profile.skills:
        actual = _hash_existing_bundle(bundle.path)
        if actual != bundle.sha256:
            raise ProfileResolutionError(
                f"materialized {bundle.kind} bundle {bundle.name!r} was modified"
            )


def _verify_direct_profile(profile: ResolvedAgentProfile, root: Path) -> None:
    """Verify a Direct profile without treating it as a stripped Codex home."""

    if not profile.workspace.is_dir() or profile.workspace.is_symlink():
        raise ProfileResolutionError("Direct profile workspace is missing or replaced")
    if profile.home.exists() or profile.codex_home.exists():
        raise ProfileResolutionError(
            "Direct profile unexpectedly materialized Agent runtime directories"
        )
    if any(profile.workspace.iterdir()):
        raise ProfileResolutionError("Direct profile workspace was modified")
    if any((root / name).exists() for name in (*_CONTROL_PATHS, "bundles")):
        raise ProfileResolutionError("Direct profile acquired Agent runtime material")
    expected_root_entries = {"workspace", "resolved-profile.json"}
    if {path.name for path in root.iterdir()} != expected_root_entries:
        raise ProfileResolutionError("Direct profile root contains unexpected material")
    marker = _read_json_object(root / "resolved-profile.json")
    expected_marker = {
        "schema_version": "agent-world.resolved-direct-profile.v1",
        "profile_hash": profile.profile_hash,
        "lineage_id": profile.lineage_id,
        "workspace": str(profile.workspace),
        "profile": profile.to_public_dict(),
    }
    if {key: marker.get(key) for key in expected_marker} != expected_marker:
        raise ProfileResolutionError("resolved Direct profile marker was modified")


def _hash_existing_bundle(source: Path) -> str:
    if not source.is_dir() or source.is_symlink():
        raise ProfileResolutionError(f"materialized bundle is missing: {source}")
    digest = hashlib.sha256()
    for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
        if path.is_symlink():
            raise ProfileResolutionError(f"materialized bundle contains a symlink: {path}")
        relative = path.relative_to(source).as_posix()
        if path.is_dir():
            digest.update(f"D\0{relative}\0".encode())
        elif path.is_file():
            size = path.stat().st_size
            digest.update(f"F\0{relative}\0{size}\0".encode())
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        else:
            raise ProfileResolutionError(f"unsupported bundle entry: {path}")
    return digest.hexdigest()


def _hash_file(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

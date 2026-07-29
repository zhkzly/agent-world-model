"""Hermetic Agent profile recipes and materialization.

``ProfileResolver`` is the only place where host paths and credential handles
become an executable profile.  It copies explicitly selected capabilities into
an isolated ``CODEX_HOME`` and never copies ambient user/repository Codex
configuration.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
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
    JsonValue,
    ReasoningEffort,
    ResolvedAgentProfile,
    ResolvedBundle,
    ResolvedRuntimeInterpreter,
    ResolvedRuntimeTool,
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
_SENSITIVE_HOOK_FIELD = re.compile(
    r"^(?:api[_-]?key|auth(?:entication|orization)?|bearer(?:[_-]?token)?|cookie|"
    r"credentials?|password|private[_-]?key|secrets?|session(?:[_-]?(?:id|key|token))?|token)$",
    re.IGNORECASE,
)
_SAFE_BASE_ENVIRONMENT_NAMES = frozenset(
    {"PATH", "LANG", "LC_ALL", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR"}
)
_SUPPORTED_BUILTIN_TOOLS = frozenset({"shell", "workspace_edit"})
_CONTROL_PATHS = (".codex", ".agents", "AGENTS.md")
_PROJECT_ROOT_MARKER = ".agent-world-project-root"
_PERMISSIONS_PROFILE = "agent_world_isolated"
_WORKSPACE_TOOLCHAIN_DIRECTORY = ".agent-world-tools"


class ProfileResolutionError(RuntimeError):
    """Raised when a requested profile cannot be materialized safely."""


class CredentialResolutionError(ProfileResolutionError):
    """Raised for missing, undeclared, or conflicting credential handles."""


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
class HookBundleSpec:
    """A hook directory containing a complete ``hooks.json`` fragment.

    Hook commands may use ``${BUNDLE_ROOT}``; the resolver replaces it with the
    content-addressed copied directory.  Other top-level keys are rejected.
    """

    name: str
    source: Path
    config_filename: str = "hooks.json"
    expected_sha256: str | None = None

    def __post_init__(self) -> None:
        _validate_name("hook", self.name)
        if Path(self.config_filename).name != self.config_filename:
            raise ValueError("hook config_filename must be a plain filename")


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
    base_instructions: str
    authentication_handle: str
    effective_capability_plan: EffectiveCapabilityPlan
    codex_bin: Path | None = None
    codex_bin_sha256: str | None = None
    model_provider: str | None = None
    openai_base_url_environment: str | None = None
    reasoning_effort: ReasoningEffort = ReasoningEffort.HIGH
    developer_instructions: str | None = None
    sandbox: SandboxMode = SandboxMode.READ_ONLY
    allowed_builtin_tools: tuple[str, ...] = ()
    allowed_network_domains: tuple[str, ...] = ()
    skills: tuple[SkillBundleSpec, ...] = ()
    hooks: tuple[HookBundleSpec, ...] = ()
    mcp_servers: tuple[McpServerSpec, ...] = ()
    credential_handles: tuple[str, ...] = ()
    output_schema: JsonObject | None = None
    structured_output_transport: str = "provider_schema"
    rollout_token_limit: int | None = None
    tool_output_token_limit: int = 2_048
    limits: InvocationLimits = field(default_factory=InvocationLimits)
    # Framework-owned build executables are not ambient shell capabilities.
    # They are resolved from the explicit source environment, copied below the
    # private profile root, and mounted only from that isolated location.
    required_runtime_tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_name("profile_id", self.profile_id)
        _validate_name("profile_version", self.profile_version)
        if not self.model:
            raise ValueError("model must not be empty")
        if not self.base_instructions.strip():
            raise ValueError("base_instructions must not be empty")
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
        if self.sandbox is SandboxMode.READ_ONLY and "workspace_edit" in self.allowed_builtin_tools:
            raise ValueError("read-only profiles cannot allow workspace_edit")
        if (
            self.sandbox is SandboxMode.WORKSPACE_WRITE
            and "workspace_edit" not in self.allowed_builtin_tools
        ):
            raise ValueError("workspace-write profiles must explicitly allow workspace_edit")
        if self.sandbox is not self.effective_capability_plan.sandbox:
            raise ValueError("sandbox must equal the effective capability plan")
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
        _ensure_unique("hook", (item.name for item in self.hooks))
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
        if self.structured_output_transport not in {
            "provider_schema",
            "json_envelope",
            "json_object",
        }:
            raise ValueError("unsupported structured output transport")
        if self.rollout_token_limit is not None and self.rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive when configured")
        if self.tool_output_token_limit <= 0:
            raise ValueError("tool_output_token_limit must be positive")
        _ensure_unique("required runtime tool", self.required_runtime_tools)
        for name in self.required_runtime_tools:
            _validate_name("required runtime tool", name)


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

        source_bundles: list[tuple[str, str, Path, str, str | None]] = []
        for skill_bundle in spec.skills:
            digest = self._hash_bundle(skill_bundle.source)
            self._check_expected_hash(
                "skill", skill_bundle.name, digest, skill_bundle.expected_sha256
            )
            source_bundles.append(("skill", skill_bundle.name, skill_bundle.source, digest, None))
        for hook_bundle in spec.hooks:
            digest = self._hash_bundle(hook_bundle.source)
            self._check_expected_hash("hook", hook_bundle.name, digest, hook_bundle.expected_sha256)
            source_bundles.append(
                (
                    "hook",
                    hook_bundle.name,
                    hook_bundle.source,
                    digest,
                    hook_bundle.config_filename,
                )
            )

        runtime_tool_sources, missing_runtime_tools = self._resolve_runtime_tool_sources(
            spec.required_runtime_tools,
            source_environment,
        )
        runtime_interpreter = (
            self._resolve_runtime_interpreter() if spec.required_runtime_tools else None
        )

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

        non_auth_handles = set(spec.credential_handles) - {spec.authentication_handle}
        if spec.hooks and non_auth_handles:
            raise CredentialResolutionError(
                "profiles with hooks cannot expose non-auth credentials until a credential broker "
                "isolates hook subprocesses"
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
                "base_instructions": spec.base_instructions,
                "developer_instructions": spec.developer_instructions,
                "effective_capability_plan": (spec.effective_capability_plan.to_public_dict()),
                "sandbox": spec.sandbox.value,
                "allowed_builtin_tools": list(spec.allowed_builtin_tools),
                "allowed_network_domains": list(spec.allowed_network_domains),
                "bundles": [
                    {"kind": kind, "name": name, "sha256": digest}
                    for kind, name, _source, digest, _config in source_bundles
                ],
                "runtime_tools": [
                    {"name": name, "sha256": digest}
                    for name, _source, digest in runtime_tool_sources
                ],
                "missing_runtime_tools": list(missing_runtime_tools),
                "runtime_interpreter": (
                    runtime_interpreter.to_safe_dict() if runtime_interpreter is not None else None
                ),
                "mcp_servers": [_mcp_public_dict(server) for server in spec.mcp_servers],
                "credential_handles": list(spec.credential_handles),
                "authentication_handle": spec.authentication_handle,
                "codex_bin_sha256": spec.codex_bin_sha256,
                "authentication_kind": "api_key",
                "output_schema": spec.output_schema,
                "structured_output_transport": spec.structured_output_transport,
                "rollout_token_limit": spec.rollout_token_limit,
                "tool_output_token_limit": spec.tool_output_token_limit,
                "limits": {
                    "timeout_seconds": spec.limits.timeout_seconds,
                    "direct_stream_idle_timeout_seconds": (
                        spec.limits.direct_stream_idle_timeout_seconds
                    ),
                    "direct_first_event_timeout_seconds": (
                        spec.limits.direct_first_event_timeout_seconds
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
        resolved_hooks: list[ResolvedBundle] = []
        hook_fragments: list[JsonObject] = []
        for kind, name, source, digest, config_filename in source_bundles:
            if kind == "skill":
                destination = root / "bundles" / "skills" / name
            else:
                destination = root / "bundles" / "hooks" / name
            self._copy_verified_bundle(source, destination, digest)
            resolved = ResolvedBundle(kind=kind, name=name, path=destination, sha256=digest)
            if kind == "skill":
                if not (destination / "SKILL.md").is_file():
                    raise ProfileResolutionError(f"skill {name!r} has no SKILL.md")
                resolved_skills.append(resolved)
            else:
                config_path = destination / str(config_filename)
                fragment = _read_json_object(config_path)
                if set(fragment) != {"hooks"} or not isinstance(fragment.get("hooks"), dict):
                    raise ProfileResolutionError(
                        f"hook bundle {name!r} must contain only a hooks object"
                    )
                _reject_sensitive_keys(fragment)
                hook_fragments.append(
                    {
                        key: _replace_bundle_root(value, destination)
                        for key, value in fragment.items()
                    }
                )
                resolved_hooks.append(resolved)

        runtime_tools = (
            self._materialize_runtime_tools(root, runtime_tool_sources)
            if spec.required_runtime_tools
            else ()
        )
        if runtime_tools:
            assert runtime_interpreter is not None
            self._materialize_workspace_tool_facades(
                resolved_workspace,
                runtime_tools=runtime_tools,
                interpreter=runtime_interpreter,
            )

        hooks_json = _merge_hook_fragments(hook_fragments)
        hooks_path = codex_home / "hooks.json"
        hooks_config_hash: str | None = None
        if hooks_json:
            _atomic_write_json(hooks_path, {"hooks": hooks_json}, mode=0o600)
            hooks_config_hash = hashlib.sha256(hooks_path.read_bytes()).hexdigest()
        elif hooks_path.exists():
            raise ProfileResolutionError("unexpected hooks.json exists for a hook-free profile")

        shell_environment = self._base_environment(source_environment)
        if spec.required_runtime_tools:
            assert runtime_interpreter is not None
            shell_environment["PATH"] = self._isolated_tool_path(root, runtime_interpreter)
        shell_environment.update(
            {
                "HOME": str(resolved_workspace / ".agent-world-tmp" / "home"),
                "TMPDIR": str(resolved_workspace / ".agent-world-tmp"),
                "UV_CACHE_DIR": str(resolved_workspace / ".agent-world-tmp" / "uv-cache"),
                "XDG_CACHE_HOME": str(resolved_workspace / ".agent-world-tmp" / "cache"),
            }
        )
        runtime_read_roots = (
            [runtime_interpreter.root]
            if runtime_interpreter is not None
            else [Path(sys.prefix).resolve()]
        )
        if spec.required_runtime_tools:
            # This directory contains only the declared, copied executables.
            # Mounting it permits shell PATH lookup without granting the Agent
            # its ambient host bin directory.
            runtime_read_roots.append(root / "toolchain" / "bin")
        if spec.codex_bin is not None:
            # The Codex app-server re-executes its own runtime inside the Linux
            # sandbox when it services shell/workspace tools.  A custom binary
            # can start successfully in the outer worker while being absent
            # from the inner bwrap mount, causing every Agent tool call to fail
            # with ENOENT.  Bind only the already content-pinned executable,
            # never its ambient parent directory.
            runtime_read_roots.append(spec.codex_bin)
        config_text = _render_codex_config(
            spec,
            codex_home=codex_home,
            workspace=resolved_workspace,
            skills=tuple(resolved_skills),
            hooks=tuple(resolved_hooks),
            runtime_read_roots=tuple(runtime_read_roots),
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
        if spec.required_runtime_tools:
            assert runtime_interpreter is not None
            base_environment["PATH"] = self._isolated_tool_path(root, runtime_interpreter)
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
            base_instructions=spec.base_instructions,
            developer_instructions=spec.developer_instructions,
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
            hooks=tuple(resolved_hooks),
            runtime_tools=runtime_tools,
            missing_runtime_tools=missing_runtime_tools,
            runtime_interpreter=runtime_interpreter,
            credential_descriptors=descriptors,
            authentication_kind="api_key",
            authentication_environment=auth_binding.target_environment,
            codex_bin=spec.codex_bin,
            codex_bin_sha256=spec.codex_bin_sha256,
            output_schema=spec.output_schema,
            structured_output_transport=spec.structured_output_transport,
            rollout_token_limit=spec.rollout_token_limit,
            tool_output_token_limit=spec.tool_output_token_limit,
            limits=spec.limits,
            codex_config_sha256=config_hash,
            hooks_config_sha256=hooks_config_hash,
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

    def _base_environment(self, source: Mapping[str, str]) -> dict[str, str]:
        return {
            name: source[name]
            for name in self._base_environment_names
            if name in source and source[name]
        }

    @staticmethod
    def _isolated_tool_path(
        root: Path,
        interpreter: ResolvedRuntimeInterpreter,
    ) -> str:
        """Return the small truthful PATH for a provisioned shell profile."""

        candidates = (
            root / "toolchain" / "bin",
            interpreter.executable.parent,
            Path("/usr/bin"),
            Path("/bin"),
        )
        entries: list[str] = []
        for candidate in candidates:
            text = str(candidate)
            if text not in entries:
                entries.append(text)
        return os.pathsep.join(entries)

    @staticmethod
    def _resolve_runtime_interpreter() -> ResolvedRuntimeInterpreter:
        """Pin the framework Python used by offline ``uv`` Candidate builds.

        The old profile exposed ``sys.prefix`` (normally a virtual environment
        whose Python entries are symlinks outside the sandbox).  That makes a
        readable but non-executable interpreter appear to the Agent.  Resolve
        the real interpreter and mount its actual prefix instead.
        """

        try:
            executable = Path(sys.executable).resolve(strict=True)
        except OSError as exc:
            raise ProfileResolutionError("framework Python runtime is unavailable") from exc
        if (
            not executable.is_file()
            or executable.is_symlink()
            or not os.access(executable, os.X_OK)
        ):
            raise ProfileResolutionError("framework Python runtime is not executable")
        version = f"{sys.version_info.major}.{sys.version_info.minor}"
        if version != "3.12":
            raise ProfileResolutionError(
                "isolated Candidate toolchains require the framework to run under Python 3.12"
            )
        root = executable.parent.parent
        if not (root / "bin").is_dir() or not executable.is_relative_to(root):
            raise ProfileResolutionError("framework Python runtime root is invalid")
        return ResolvedRuntimeInterpreter(
            version=version,
            executable=executable,
            root=root,
            sha256=_hash_file(executable),
        )

    def _materialize_workspace_tool_facades(
        self,
        workspace: Path,
        *,
        runtime_tools: tuple[ResolvedRuntimeTool, ...],
        interpreter: ResolvedRuntimeInterpreter,
    ) -> None:
        """Expose declared build tools through stable workspace-relative commands.

        Current Codex app-server sandboxes can ignore a configured shell PATH
        even though the tool directory is mounted.  The Agent must not have to
        discover a private absolute profile path, so provide explicit relative
        executable copies under the framework-owned workspace root.  They are
        direct executables rather than shell wrappers, removing an additional
        wrapper-interpreter dependency; the later real audit still proves
        whether their runtime can start in the active sandbox.  The copies are
        not Candidate output and are never trusted by a later framework gate.
        """

        tool_root = workspace / _WORKSPACE_TOOLCHAIN_DIRECTORY
        self._make_private_directory(tool_root)
        by_name = {tool.name: tool for tool in runtime_tools}
        for tool in runtime_tools:
            self._copy_workspace_tool_executable(
                source=tool.path,
                destination=tool_root / tool.name,
                digest=tool.sha256,
                description=f"runtime tool {tool.name!r}",
            )
        if "uv" in by_name and "python3.12" not in by_name:
            self._copy_workspace_tool_executable(
                source=interpreter.executable,
                destination=tool_root / "python3.12",
                digest=interpreter.sha256,
                description="Python 3.12 interpreter",
            )

    @staticmethod
    def _copy_workspace_tool_executable(
        source: Path,
        destination: Path,
        *,
        digest: str,
        description: str,
    ) -> None:
        """Materialize one hash-pinned, directly executable workspace tool."""

        if (
            source.is_symlink()
            or not source.is_file()
            or not os.access(source, os.X_OK)
            or _hash_file(source) != digest
        ):
            raise ProfileResolutionError(f"pinned {description} is unavailable")
        if destination.exists() or destination.is_symlink():
            if (
                destination.is_symlink()
                or not destination.is_file()
                or not os.access(destination, os.X_OK)
                or _hash_file(destination) != digest
            ):
                raise ProfileResolutionError(f"workspace copy of {description} was modified")
            return

        temporary = destination.with_name(f".{destination.name}.copying")
        if temporary.exists() or temporary.is_symlink():
            if temporary.is_dir() and not temporary.is_symlink():
                raise ProfileResolutionError(
                    f"workspace copy staging path is unexpectedly a directory: {temporary}"
                )
            temporary.unlink()
        shutil.copyfile(source, temporary)
        temporary.chmod(0o500)
        if _hash_file(temporary) != digest:
            temporary.unlink()
            raise ProfileResolutionError(f"{description} changed while materializing workspace")
        temporary.replace(destination)

    @staticmethod
    def _resolve_runtime_tool_sources(
        names: tuple[str, ...],
        source_environment: Mapping[str, str],
    ) -> tuple[list[tuple[str, Path, str]], tuple[str, ...]]:
        """Pin declared tool binaries without exposing ambient PATH at runtime."""

        path_value = source_environment.get("PATH", "")
        search_roots = tuple(
            Path(item).expanduser()
            for item in path_value.split(os.pathsep)
            if item and Path(item).is_absolute()
        )
        resolved: list[tuple[str, Path, str]] = []
        missing: list[str] = []
        for name in names:
            executable: Path | None = None
            for directory in search_roots:
                candidate = directory / name
                try:
                    target = candidate.resolve(strict=True)
                except OSError:
                    continue
                if not target.is_file() or target.is_symlink() or not os.access(target, os.X_OK):
                    continue
                executable = target
                break
            if executable is None:
                missing.append(name)
                continue
            resolved.append((name, executable, _hash_file(executable)))
        return resolved, tuple(missing)

    def _materialize_runtime_tools(
        self,
        root: Path,
        sources: list[tuple[str, Path, str]],
    ) -> tuple[ResolvedRuntimeTool, ...]:
        """Copy each pinned executable into the profile-owned toolchain."""

        toolchain = root / "toolchain"
        tool_bin = toolchain / "bin"
        self._make_private_directory(toolchain)
        self._make_private_directory(tool_bin)
        resolved: list[ResolvedRuntimeTool] = []
        for name, source, digest in sources:
            destination = tool_bin / name
            if destination.exists():
                if (
                    destination.is_symlink()
                    or not destination.is_file()
                    or not os.access(destination, os.X_OK)
                    or _hash_file(destination) != digest
                ):
                    raise ProfileResolutionError(f"materialized runtime tool {name!r} was modified")
            else:
                temporary = tool_bin / f".{name}.copying"
                if temporary.exists():
                    temporary.unlink()
                shutil.copyfile(source, temporary)
                temporary.chmod(0o500)
                if _hash_file(temporary) != digest:
                    temporary.unlink()
                    raise ProfileResolutionError(
                        f"runtime tool {name!r} changed while materializing"
                    )
                temporary.replace(destination)
            resolved.append(ResolvedRuntimeTool(name=name, path=destination, sha256=digest))
        return tuple(resolved)

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
            raise ProfileResolutionError(f"isolated directory must not be a symlink: {path}")
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
    codex_home: Path,
    workspace: Path,
    skills: tuple[ResolvedBundle, ...],
    hooks: tuple[ResolvedBundle, ...],
    runtime_read_roots: tuple[Path, ...],
    bindings: Mapping[str, CredentialBinding],
    shell_environment: Mapping[str, str],
) -> str:
    # KEEP THIS FILE SMALL.  Codex ships working defaults for its tools, sandbox
    # and permissions; every line written here overrides one of them, and each
    # override is a place where a generated profile can disagree with the runtime
    # that actually executes it.  A previous version emitted ~83 lines -- 21
    # feature flags, a hand-rebuilt shell environment, and a domain allowlist --
    # and the observable result was tools that existed but could not work
    # tools that existed but could not work, which failed silently and had to be
    # re-diagnosed per node.  Runtime tools are never named here at all: the Codex
    # runtime owns which of its tools exist, and a second copy of that decision in
    # generated config can only disagree with it.
    #
    # Only three things justify an override, because the framework's own
    # guarantees depend on them:
    #   1. no interactive approval -- there is no human at this terminal;
    #   2. credentials never reach disk -- the provider key stays in the worker's
    #      memory and must not be materialized into a Codex auth file;
    #   3. writes stay inside the isolated workspace -- Judge and Registry
    #      evidence is only meaningful if a candidate cannot write elsewhere.
    # Everything else is the SDK's business.  Do not re-add flags defensively.
    lines = [
        'approval_policy = "never"',
        f"default_permissions = {_toml_string(_PERMISSIONS_PROFILE)}",
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
    # The Agent runs inside a disposable workspace with full authority over it:
    # network on, filesystem write, no domain allowlist, no per-path rules.  The
    # containment that matters is the workspace itself -- it is created per
    # invocation, nothing outside it is an input to Judge or Registry, and a
    # candidate becomes real only by passing validation and an immutable commit.
    # Writing per-path filesystem rules here bought nothing and cost correctness:
    # a tool could exist and still be unable to work, which fails silently and
    # has to be re-diagnosed at every node.
    #
    # The shell keeps ``inherit = "none"`` for one non-negotiable reason: the
    # parent environment holds the provider credential, which must never reach a
    # subprocess or a snapshot.  The few values below are what a shell needs to
    # function at all (its pinned toolchain and a writable temp/cache inside the
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

    lines.extend(
        [
            "",
            f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}]",
            'description = "Agent World disposable invocation workspace"',
            "",
            f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.filesystem]",
            # ``:root`` is Codex's own name for the whole tree.  ``:all`` is not a
            # key it recognizes and made the app-server fail at session open --
            # a reminder that inventing config vocabulary fails later and less
            # legibly than using the runtime's.
            '":root" = "write"',
            "",
            f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.network]",
            "enabled = true",
        ]
    )

    # Declaring the workspace as a project keeps Codex from resolving a project
    # above it.  ``untrusted`` refers to project-local config/hooks, not to the
    # Agent's authority inside the workspace, which is full.
    lines.extend(
        [
            "",
            f"[projects.{_toml_string(str(workspace))}]",
            'trust_level = "untrusted"',
        ]
    )

    for skill in skills:
        lines.extend(
            [
                "",
                "[[skills.config]]",
                f"path = {_toml_string(str(skill.path))}",
                "enabled = true",
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


def _merge_hook_fragments(fragments: list[JsonObject]) -> dict[str, JsonValue]:
    merged: dict[str, JsonValue] = {}
    for fragment in fragments:
        hooks = fragment["hooks"]
        if not isinstance(hooks, dict):
            raise ProfileResolutionError("hook fragment hooks must be an object")
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                raise ProfileResolutionError(f"hook event {event!r} must contain a list")
            current = merged.setdefault(event, [])
            if not isinstance(current, list):
                raise AssertionError("merged hook event unexpectedly changed type")
            current.extend(groups)
    return merged


def _replace_bundle_root(value: JsonValue, root: Path) -> JsonValue:
    if isinstance(value, str):
        return value.replace("${BUNDLE_ROOT}", str(root))
    if isinstance(value, list):
        return [_replace_bundle_root(item, root) for item in value]
    if isinstance(value, dict):
        return {key: _replace_bundle_root(item, root) for key, item in value.items()}
    return value


def _reject_sensitive_keys(value: JsonValue) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            # Hook event names such as ``SessionStart`` are ordinary schema
            # keys.  Reject credential-shaped field names exactly instead of
            # treating every occurrence of the word "session" as a secret.
            if _SENSITIVE_HOOK_FIELD.fullmatch(key):
                raise ProfileResolutionError(
                    f"hook configuration contains a sensitive field {key!r}; use credential handles"
                )
            _reject_sensitive_keys(item)
    elif isinstance(value, list):
        for item in value:
            _reject_sensitive_keys(item)
    elif isinstance(value, str) and _looks_secret(value):
        raise ProfileResolutionError("hook configuration appears to contain secret material")


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
    hooks_path = profile.codex_home / "hooks.json"
    if profile.hooks_config_sha256 is None:
        if hooks_path.exists():
            raise ProfileResolutionError("unexpected hooks.json exists for a hook-free profile")
    else:
        try:
            hooks_hash = hashlib.sha256(hooks_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise ProfileResolutionError("cannot read materialized hooks config") from exc
        if hooks_path.is_symlink() or hooks_hash != profile.hooks_config_sha256:
            raise ProfileResolutionError("materialized hooks config was modified")
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

    tool_bin = profile.materialization_root / "toolchain" / "bin"
    expected_tools = {tool.name: tool for tool in profile.runtime_tools}
    if profile.runtime_tools or profile.missing_runtime_tools:
        if not tool_bin.is_dir() or tool_bin.is_symlink():
            raise ProfileResolutionError("isolated runtime toolchain is unavailable")
        actual_names = {path.name for path in tool_bin.iterdir()}
        if actual_names != set(expected_tools):
            raise ProfileResolutionError("isolated runtime toolchain contents changed")
    for name, tool in expected_tools.items():
        if tool.path != tool_bin / name:
            raise ProfileResolutionError("resolved runtime tool escaped its isolated toolchain")
        if tool.path.is_symlink() or not tool.path.is_file() or not os.access(tool.path, os.X_OK):
            raise ProfileResolutionError("resolved runtime tool is unavailable")
        if _hash_file(tool.path) != tool.sha256:
            raise ProfileResolutionError("resolved runtime tool changed after resolution")

    interpreter = profile.runtime_interpreter
    if interpreter is not None:
        if (
            interpreter.executable.is_symlink()
            or not interpreter.executable.is_file()
            or not os.access(interpreter.executable, os.X_OK)
            or not interpreter.executable.is_relative_to(interpreter.root)
            or _hash_file(interpreter.executable) != interpreter.sha256
        ):
            raise ProfileResolutionError("resolved runtime interpreter changed after resolution")
    if expected_tools:
        assert interpreter is not None
        facade_root = profile.workspace / _WORKSPACE_TOOLCHAIN_DIRECTORY
        if not facade_root.is_dir() or facade_root.is_symlink():
            raise ProfileResolutionError("workspace runtime tool facades are unavailable")
        expected_facades = set(expected_tools)
        if "uv" in expected_tools and "python3.12" not in expected_tools:
            expected_facades.add("python3.12")
        if {path.name for path in facade_root.iterdir()} != expected_facades:
            raise ProfileResolutionError("workspace runtime tool facades changed")
        for name, tool in expected_tools.items():
            facade = facade_root / name
            if (
                facade.is_symlink()
                or not facade.is_file()
                or not os.access(facade, os.X_OK)
                or _hash_file(facade) != tool.sha256
            ):
                raise ProfileResolutionError("workspace runtime tool facade changed")
        python_facade = facade_root / "python3.12"
        expected_python_facade_digest = (
            expected_tools["python3.12"].sha256
            if "python3.12" in expected_tools
            else interpreter.sha256
        )
        if "python3.12" in expected_facades and (
            python_facade.is_symlink()
            or not python_facade.is_file()
            or not os.access(python_facade, os.X_OK)
            or _hash_file(python_facade) != expected_python_facade_digest
        ):
            raise ProfileResolutionError("workspace Python tool facade changed")

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

    for bundle in (*profile.skills, *profile.hooks):
        actual = _hash_existing_bundle(bundle.path)
        if actual != bundle.sha256:
            raise ProfileResolutionError(
                f"materialized {bundle.kind} bundle {bundle.name!r} was modified"
            )


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

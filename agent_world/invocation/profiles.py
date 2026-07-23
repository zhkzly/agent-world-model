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
    SandboxMode,
    json_compatible,
)

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
_SUPPORTED_BUILTIN_TOOLS = frozenset({"shell", "workspace_edit", "web_search", "multi_agent"})
_CONTROL_PATHS = (".codex", ".agents", "AGENTS.md")
_PROJECT_ROOT_MARKER = ".agent-world-project-root"
_PERMISSIONS_PROFILE = "agent_world_isolated"


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
    """Explicit authorization to copy one existing Codex ``auth.json`` file.

    The source path and file contents remain resolver-private.  They are never
    included in profile hashes, public metadata, worker requests, or logs.
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
    openai_base_url: str | None = None
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
        if self.openai_base_url is not None:
            parsed_base_url = urlparse(self.openai_base_url)
            if (
                parsed_base_url.scheme not in {"http", "https"}
                or not parsed_base_url.hostname
                or parsed_base_url.username is not None
                or parsed_base_url.password is not None
                or parsed_base_url.query
                or parsed_base_url.fragment
            ):
                raise ValueError("openai_base_url must be a credential-free HTTP(S) origin/path")
            if self.model_provider not in {None, "openai"}:
                raise ValueError(
                    "openai_base_url only overrides the built-in openai model provider"
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
        if self.allowed_builtin_tools != (
            self.effective_capability_plan.intrinsic_builtin_tools
        ):
            raise ValueError("builtin tools must equal the effective intrinsic capability set")
        if self.allowed_network_domains != (
            self.effective_capability_plan.external.network_domains
        ):
            raise ValueError("network domains must equal the effective capability set")
        external_handles = set(self.credential_handles) - {self.authentication_handle}
        if external_handles != set(
            self.effective_capability_plan.external.credential_handles
        ):
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
        if self.structured_output_transport not in {"provider_schema", "json_envelope"}:
            raise ValueError("unsupported structured output transport")
        if self.rollout_token_limit is not None and self.rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive when configured")
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

        bindings = {handle: self._bindings[handle] for handle in spec.credential_handles}
        auth_binding = bindings[spec.authentication_handle]
        if auth_binding.purpose not in {"model_api_key", "codex_login"}:
            raise CredentialResolutionError(
                "authentication_handle must resolve to a model_api_key or codex_login binding"
            )
        if spec.openai_base_url is not None and isinstance(auth_binding, CodexLoginBinding):
            raise CredentialResolutionError(
                "openai_base_url requires an API-key authentication binding"
            )
        credential_environment: dict[str, str] = {}
        for handle, binding in bindings.items():
            if isinstance(binding, CodexLoginBinding):
                if handle != spec.authentication_handle:
                    raise CredentialResolutionError(
                        "CodexLoginBinding may only be used as authentication_handle"
                    )
                continue
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
                "openai_base_url": spec.openai_base_url,
                "reasoning_effort": spec.reasoning_effort.value,
                "base_instructions": spec.base_instructions,
                "developer_instructions": spec.developer_instructions,
                "effective_capability_plan": (
                    spec.effective_capability_plan.to_public_dict()
                ),
                "sandbox": spec.sandbox.value,
                "allowed_builtin_tools": list(spec.allowed_builtin_tools),
                "allowed_network_domains": list(spec.allowed_network_domains),
                "bundles": [
                    {"kind": kind, "name": name, "sha256": digest}
                    for kind, name, _source, digest, _config in source_bundles
                ],
                "mcp_servers": [_mcp_public_dict(server) for server in spec.mcp_servers],
                "credential_handles": list(spec.credential_handles),
                "authentication_handle": spec.authentication_handle,
                "codex_bin_sha256": spec.codex_bin_sha256,
                "authentication_kind": (
                    "chatgpt" if isinstance(auth_binding, CodexLoginBinding) else "api_key"
                ),
                "output_schema": spec.output_schema,
                "structured_output_transport": spec.structured_output_transport,
                "rollout_token_limit": spec.rollout_token_limit,
                "tool_output_token_limit": spec.tool_output_token_limit,
                "limits": {
                    "timeout_seconds": spec.limits.timeout_seconds,
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

        hooks_json = _merge_hook_fragments(hook_fragments)
        hooks_path = codex_home / "hooks.json"
        hooks_config_hash: str | None = None
        if hooks_json:
            _atomic_write_json(hooks_path, {"hooks": hooks_json}, mode=0o600)
            hooks_config_hash = hashlib.sha256(hooks_path.read_bytes()).hexdigest()
        elif hooks_path.exists():
            raise ProfileResolutionError("unexpected hooks.json exists for a hook-free profile")

        if isinstance(auth_binding, CodexLoginBinding):
            _copy_codex_login(auth_binding.source, codex_home / "auth.json")

        shell_environment = self._base_environment(source_environment)
        shell_environment.update(
            {
                "HOME": str(resolved_workspace / ".agent-world-tmp" / "home"),
                "TMPDIR": str(resolved_workspace / ".agent-world-tmp"),
                "UV_CACHE_DIR": str(resolved_workspace / ".agent-world-tmp" / "uv-cache"),
                "XDG_CACHE_HOME": str(resolved_workspace / ".agent-world-tmp" / "cache"),
            }
        )
        runtime_read_roots = [Path(sys.prefix).resolve()]
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
            authentication_kind=(
                "chatgpt" if isinstance(auth_binding, CodexLoginBinding) else "api_key"
            ),
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
            openai_base_url=spec.openai_base_url,
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
            credential_descriptors=descriptors,
            authentication_kind=(
                "chatgpt" if isinstance(auth_binding, CodexLoginBinding) else "api_key"
            ),
            authentication_environment=(
                None
                if isinstance(auth_binding, CodexLoginBinding)
                else auth_binding.target_environment
            ),
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
    authentication_kind: str,
    shell_environment: Mapping[str, str],
) -> str:
    login_method = "chatgpt" if authentication_kind == "chatgpt" else "api"
    web_search_mode = "live" if "web_search" in spec.allowed_builtin_tools else "disabled"
    lines = [
        'approval_policy = "never"',
        f"default_permissions = {_toml_string(_PERMISSIONS_PROFILE)}",
        f"forced_login_method = {_toml_string(login_method)}",
        f"web_search = {_toml_string(web_search_mode)}",
        'file_opener = "none"',
        "hide_agent_reasoning = true",
        "show_raw_agent_reasoning = false",
        "project_doc_max_bytes = 0",
        "project_doc_fallback_filenames = []",
        f"tool_output_token_limit = {spec.tool_output_token_limit}",
        f"project_root_markers = [{_toml_string(_PROJECT_ROOT_MARKER)}]",
        f"sqlite_home = {_toml_string(str(codex_home / 'state'))}",
        f"log_dir = {_toml_string(str(codex_home / 'logs'))}",
    ]
    if spec.openai_base_url is not None:
        lines.append(f"openai_base_url = {_toml_string(spec.openai_base_url)}")
    lines.extend([
        "",
        "[history]",
        'persistence = "save-all"',
        "max_bytes = 16777216",
        "",
        "[analytics]",
        "enabled = false",
        "",
        "[feedback]",
        "enabled = false",
        "",
        "[features]",
        # A generated role profile is a capability allowlist.  Stable Codex
        # desktop integrations are otherwise enabled by default and can expose
        # remote plugins, app tools or browser surfaces that were never granted
        # by ``allowed_builtin_tools``.  Keep those surfaces off here; explicit
        # MCP servers and the one bundled role Skill are materialized below.
        "apps = false",
        "auth_elicitation = false",
        "browser_use = false",
        "browser_use_external = false",
        "computer_use = false",
        "enable_mcp_apps = false",
        f"hooks = {_toml_bool(bool(spec.hooks))}",
        "image_generation = false",
        "in_app_browser = false",
        "memories = false",
        "goals = false",
        f"multi_agent = {_toml_bool('multi_agent' in spec.allowed_builtin_tools)}",
        "plugin_sharing = false",
        "plugins = false",
        "remote_plugin = false",
        f"shell_tool = {_toml_bool('shell' in spec.allowed_builtin_tools)}",
        "skill_mcp_dependency_install = false",
        "tool_call_mcp_elicitation = false",
        "tool_suggest = false",
        "workspace_dependencies = false",
    ])
    if spec.rollout_token_limit is not None:
        reminder_thresholds = (
            []
            if spec.rollout_token_limit == 1
            else [max(1, spec.rollout_token_limit // 10)]
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
    lines.extend(
        [
            "",
            "[shell_environment_policy]",
            'inherit = "none"',
            "experimental_use_profile = false",
            "ignore_default_excludes = false",
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
            'description = "Agent World isolated invocation workspace"',
            "",
            f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.filesystem]",
            '":root" = "deny"',
            '":minimal" = "read"',
        ]
    )
    lines.extend(
        [
            f'{_toml_string(str(codex_home.parent / "home"))} = "deny"',
            f'{_toml_string(str(codex_home))} = "deny"',
        ]
    )
    for runtime_root in runtime_read_roots:
        lines.append(f'{_toml_string(str(runtime_root))} = "read"')
    for bundle in skills:
        lines.append(f'{_toml_string(str(bundle.path))} = "read"')
    for hook in hooks:
        lines.append(f'{_toml_string(str(hook.path))} = "read"')
    lines.extend(
        [
            "",
            f'[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.filesystem.":workspace_roots"]',
            f'"." = {_toml_string("read" if spec.sandbox is SandboxMode.READ_ONLY else "write")}',
            f'{_toml_string(_PROJECT_ROOT_MARKER)} = "read"',
            "",
            f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.network]",
            f"enabled = {_toml_bool(bool(spec.allowed_network_domains))}",
        ]
    )
    if spec.allowed_network_domains:
        lines.extend(
            [
                "",
                f"[permissions.{_toml_key(_PERMISSIONS_PROFILE)}.network.domains]",
            ]
        )
        for domain in spec.allowed_network_domains:
            lines.append(f'{_toml_string(domain)} = "allow"')

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


def _copy_codex_login(source: Path, destination: Path) -> None:
    """Copy an explicitly authorized login file without hashing or identifying it."""

    if not source.is_absolute():
        raise CredentialResolutionError("CodexLoginBinding source must be an absolute path")
    try:
        if source.is_symlink() or not source.is_file():
            raise CredentialResolutionError("authorized Codex login file is unavailable")
        stat = source.stat()
    except OSError:
        raise CredentialResolutionError("authorized Codex login file is unavailable") from None
    if stat.st_size <= 0 or stat.st_size > 4 * 1024 * 1024:
        raise CredentialResolutionError("authorized Codex login file has an invalid size")
    if os.name != "nt" and stat.st_mode & 0o077:
        raise CredentialResolutionError("authorized Codex login file permissions are too broad")
    try:
        content = source.read_bytes()
        parsed = json.loads(content, parse_constant=_reject_json_constant)
    except (OSError, json.JSONDecodeError, ValueError):
        # Do not retain a chained exception that may contain the private source
        # path.  The handle is the only login identity allowed in public state.
        raise CredentialResolutionError("authorized Codex login file is invalid") from None
    if not isinstance(parsed, dict):
        raise CredentialResolutionError("authorized Codex login file is invalid")
    _atomic_write_bytes(destination, content, mode=0o600)


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
    if profile.authentication_kind == "chatgpt":
        auth_path = profile.codex_home / "auth.json"
        if not auth_path.is_file() or auth_path.is_symlink():
            raise ProfileResolutionError("materialized ChatGPT login is unavailable")
        if os.name != "nt" and auth_path.stat().st_mode & 0o077:
            raise ProfileResolutionError("materialized ChatGPT login permissions changed")
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

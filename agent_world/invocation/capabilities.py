"""Framework-owned capability plans for specialized Agent invocations.

The request/job permission contract authorizes external capabilities.  Codex
Agents run with the one full-host SDK execution mode chosen by this project;
the plan still records the tools a node expects, without introducing a second
filesystem namespace or workspace sandbox.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .contracts import JsonObject, SandboxMode

_CAPABILITY_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
# Intrinsic tools record the node's expected Codex tools. The runtime owns its
# actual tool catalog; this metadata must not become a second restrictive
# filesystem or command policy.
_INTRINSIC_BUILTIN_TOOLS = frozenset({"shell", "workspace_edit"})
_DOMAIN = re.compile(r"^(?:\*|(?:(?:\*|\*\*)\.)?[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?)$")


class CapabilityResolutionError(RuntimeError):
    """A required node capability is not authorized by every policy layer."""

    def __init__(self, node_id: str, missing_dimensions: tuple[str, ...]) -> None:
        self.node_id = node_id
        self.missing_dimensions = tuple(sorted(set(missing_dimensions)))
        joined = ", ".join(self.missing_dimensions)
        super().__init__(
            f"node {node_id!r} requires capabilities outside its effective grant: {joined}"
        )


class ExternalPermissionGrant(Protocol):
    """Structural view of the public ``PermissionScope`` contract."""

    filesystem_read_roots: tuple[str, ...]
    filesystem_write_roots: tuple[str, ...]
    network_domains: tuple[str, ...]
    executable_allowlist: tuple[str, ...]
    tool_allowlist: tuple[str, ...]
    credential_handles: tuple[str, ...]
    allow_external_side_effects: bool


@dataclass(frozen=True, slots=True)
class ExternalCapabilitySet:
    """External resources that may cross the hermetic profile boundary."""

    filesystem_read_roots: tuple[str, ...] = ()
    filesystem_write_roots: tuple[str, ...] = ()
    network_domains: tuple[str, ...] = ()
    executable_allowlist: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    credential_handles: tuple[str, ...] = ()
    allow_external_side_effects: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "filesystem_read_roots",
            "filesystem_write_roots",
            "network_domains",
            "executable_allowlist",
            "tool_allowlist",
            "credential_handles",
        ):
            values = tuple(getattr(self, field_name))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must not contain duplicates")
            if tuple(sorted(values)) != values:
                raise ValueError(f"{field_name} must use canonical sorted order")
            if any(not value or value != value.strip() for value in values):
                raise ValueError(f"{field_name} contains an invalid empty value")
        for domain in self.network_domains:
            if _DOMAIN.fullmatch(domain) is None:
                raise ValueError(f"invalid network domain: {domain!r}")
        for value in (*self.tool_allowlist, *self.credential_handles):
            if _CAPABILITY_NAME.fullmatch(value) is None:
                raise ValueError(f"invalid capability identifier: {value!r}")

    @classmethod
    def from_permission_scope(cls, scope: ExternalPermissionGrant) -> ExternalCapabilitySet:
        return cls(
            filesystem_read_roots=tuple(sorted(scope.filesystem_read_roots)),
            filesystem_write_roots=tuple(sorted(scope.filesystem_write_roots)),
            network_domains=tuple(sorted(scope.network_domains)),
            executable_allowlist=tuple(sorted(scope.executable_allowlist)),
            tool_allowlist=tuple(sorted(scope.tool_allowlist)),
            credential_handles=tuple(sorted(scope.credential_handles)),
            allow_external_side_effects=scope.allow_external_side_effects,
        )

    def to_public_dict(self) -> JsonObject:
        return {
            "filesystem_read_roots": list(self.filesystem_read_roots),
            "filesystem_write_roots": list(self.filesystem_write_roots),
            "network_domains": list(self.network_domains),
            "executable_allowlist": list(self.executable_allowlist),
            "tool_allowlist": list(self.tool_allowlist),
            "credential_handles": list(self.credential_handles),
            "allow_external_side_effects": self.allow_external_side_effects,
        }


@dataclass(frozen=True, slots=True)
class RoleCapabilityMaximum:
    """Framework/operator capability declaration for one specialized role."""

    role: str
    policy_version: str
    maximum_sandbox: SandboxMode
    intrinsic_builtin_tools: tuple[str, ...]
    external: ExternalCapabilitySet = ExternalCapabilitySet()

    def __post_init__(self) -> None:
        _validate_identity("role", self.role)
        _validate_identity("policy_version", self.policy_version)
        _validate_intrinsic_tools(self.intrinsic_builtin_tools)

    def to_public_dict(self) -> JsonObject:
        return {
            "role": self.role,
            "policy_version": self.policy_version,
            "maximum_sandbox": self.maximum_sandbox.value,
            "intrinsic_builtin_tools": list(self.intrinsic_builtin_tools),
            "external": self.external.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class NodeCapabilityRequirement:
    """Exact capabilities a single semantic work node needs to execute."""

    node_id: str
    role: str
    sandbox: SandboxMode
    intrinsic_builtin_tools: tuple[str, ...]
    external: ExternalCapabilitySet = ExternalCapabilitySet()

    def __post_init__(self) -> None:
        _validate_identity("node_id", self.node_id)
        _validate_identity("role", self.role)
        _validate_intrinsic_tools(self.intrinsic_builtin_tools)

    @classmethod
    def structured_read(
        cls,
        *,
        node_id: str,
        role: str,
    ) -> NodeCapabilityRequirement:
        """Read framework-staged files and return typed output.

        The runtime's full-host SDK mode is invariant; this requirement only
        names whether the node expects a shell tool.
        """

        return cls(
            node_id=node_id,
            role=role,
            sandbox=SandboxMode.FULL_ACCESS,
            intrinsic_builtin_tools=("shell",),
        )

    @classmethod
    def structured_output(
        cls,
        *,
        node_id: str,
        role: str,
    ) -> NodeCapabilityRequirement:
        """Return typed output from prompt-bounded artifacts without any tools."""

        return cls(
            node_id=node_id,
            role=role,
            sandbox=SandboxMode.FULL_ACCESS,
            intrinsic_builtin_tools=(),
        )

    @classmethod
    def host_build(
        cls,
        *,
        node_id: str,
        external: ExternalCapabilitySet | None = None,
    ) -> NodeCapabilityRequirement:
        """Edit and test a Candidate in its direct host working directory."""

        return cls(
            node_id=node_id,
            role="environment-engineer",
            sandbox=SandboxMode.FULL_ACCESS,
            intrinsic_builtin_tools=("shell", "workspace_edit"),
            external=external if external is not None else ExternalCapabilitySet(),
        )

    def to_public_dict(self) -> JsonObject:
        return {
            "node_id": self.node_id,
            "role": self.role,
            "sandbox": self.sandbox.value,
            "intrinsic_builtin_tools": list(self.intrinsic_builtin_tools),
            "external": self.external.to_public_dict(),
        }


@dataclass(frozen=True, slots=True)
class EffectiveCapabilityPlan:
    """Immutable result of role ceiling x job grant x exact node requirement."""

    schema_version: str
    node_id: str
    role: str
    sandbox: SandboxMode
    intrinsic_builtin_tools: tuple[str, ...]
    external: ExternalCapabilitySet
    role_maximum_hash: str
    job_permission_hash: str
    node_requirement_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != "agent-world.effective-capability-plan.v1":
            raise ValueError("unsupported EffectiveCapabilityPlan schema version")
        _validate_identity("node_id", self.node_id)
        _validate_identity("role", self.role)
        _validate_intrinsic_tools(self.intrinsic_builtin_tools)
        for label, value in (
            ("role_maximum_hash", self.role_maximum_hash),
            ("job_permission_hash", self.job_permission_hash),
            ("node_requirement_hash", self.node_requirement_hash),
        ):
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{label} must be lowercase sha256 hex")

    @property
    def plan_hash(self) -> str:
        return _canonical_hash(self.to_public_dict(include_plan_hash=False))

    def to_public_dict(self, *, include_plan_hash: bool = True) -> JsonObject:
        value: JsonObject = {
            "schema_version": self.schema_version,
            "node_id": self.node_id,
            "role": self.role,
            "sandbox": self.sandbox.value,
            "intrinsic_builtin_tools": list(self.intrinsic_builtin_tools),
            "external": self.external.to_public_dict(),
            "role_maximum_hash": self.role_maximum_hash,
            "job_permission_hash": self.job_permission_hash,
            "node_requirement_hash": self.node_requirement_hash,
        }
        if include_plan_hash:
            value["plan_hash"] = self.plan_hash
        return value


def compile_effective_capability_plan(
    *,
    role_maximum: RoleCapabilityMaximum,
    job_permission: ExternalPermissionGrant,
    requirement: NodeCapabilityRequirement,
) -> EffectiveCapabilityPlan:
    """Resolve an exact plan or fail before any credential/workspace materialization.

    The effective external set is the node requirement after proving that every
    item is present in both the role declaration and the job grant. Broader
    grants are intentionally discarded. The Codex execution mode is invariant
    and therefore has no read/write rank or namespace policy.
    """

    missing: list[str] = []
    if requirement.role != role_maximum.role:
        missing.append("role")
    if requirement.sandbox is not SandboxMode.FULL_ACCESS:
        missing.append("intrinsic.execution_mode")
    if role_maximum.maximum_sandbox is not SandboxMode.FULL_ACCESS:
        missing.append("role_maximum.execution_mode")
    if not set(requirement.intrinsic_builtin_tools) <= set(role_maximum.intrinsic_builtin_tools):
        missing.append("intrinsic.builtin_tools")

    granted = ExternalCapabilitySet.from_permission_scope(job_permission)
    for field_name in (
        "filesystem_read_roots",
        "filesystem_write_roots",
        "network_domains",
        "executable_allowlist",
        "tool_allowlist",
        "credential_handles",
    ):
        requested = set(getattr(requirement.external, field_name))
        maximum_values = tuple(getattr(role_maximum.external, field_name))
        granted_values = tuple(getattr(granted, field_name))
        maximum_allows = (
            _domains_cover(requested, maximum_values)
            if field_name == "network_domains"
            else requested <= set(maximum_values)
        )
        job_allows = (
            _domains_cover(requested, granted_values)
            if field_name == "network_domains"
            else requested <= set(granted_values)
        )
        if not maximum_allows:
            missing.append(f"role_maximum.external.{field_name}")
        if not job_allows:
            missing.append(f"job_permission.external.{field_name}")
    if requirement.external.allow_external_side_effects:
        if not role_maximum.external.allow_external_side_effects:
            missing.append("role_maximum.external.side_effects")
        if not granted.allow_external_side_effects:
            missing.append("job_permission.external.side_effects")
    if missing:
        raise CapabilityResolutionError(requirement.node_id, tuple(missing))

    return EffectiveCapabilityPlan(
        schema_version="agent-world.effective-capability-plan.v1",
        node_id=requirement.node_id,
        role=requirement.role,
        sandbox=requirement.sandbox,
        intrinsic_builtin_tools=requirement.intrinsic_builtin_tools,
        external=requirement.external,
        role_maximum_hash=_canonical_hash(role_maximum.to_public_dict()),
        job_permission_hash=_canonical_hash(granted.to_public_dict()),
        node_requirement_hash=_canonical_hash(requirement.to_public_dict()),
    )


def _domains_cover(requested: set[str], allowed: tuple[str, ...]) -> bool:
    return all(any(_domain_rule_matches(domain, rule) for rule in allowed) for domain in requested)


def _domain_rule_matches(domain: str, rule: str) -> bool:
    domain = domain.lower().rstrip(".")
    normalized = rule.lower().rstrip(".")
    if normalized == "*":
        return True
    if normalized.startswith("**."):
        suffix = normalized[3:]
        return domain == suffix or domain.endswith(f".{suffix}")
    if normalized.startswith("*."):
        suffix = normalized[1:]
        return domain.endswith(suffix) and domain != suffix[1:]
    return domain == normalized


def _validate_intrinsic_tools(values: tuple[str, ...]) -> None:
    if len(values) != len(set(values)):
        raise ValueError("intrinsic_builtin_tools must not contain duplicates")
    if any(value not in _INTRINSIC_BUILTIN_TOOLS for value in values):
        raise ValueError("intrinsic_builtin_tools contains an external/unsupported tool")
    if "workspace_edit" in values and "shell" not in values:
        raise ValueError("workspace_edit requires the intrinsic shell capability")


def _validate_identity(label: str, value: str) -> None:
    if _CAPABILITY_NAME.fullmatch(value) is None:
        raise ValueError(f"invalid {label}: {value!r}")


def _canonical_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CapabilityResolutionError",
    "EffectiveCapabilityPlan",
    "ExternalCapabilitySet",
    "NodeCapabilityRequirement",
    "RoleCapabilityMaximum",
    "compile_effective_capability_plan",
]

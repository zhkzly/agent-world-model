"""Three hermetic Agent profiles used by every semantic pipeline node."""

from __future__ import annotations

import copy
import hashlib
import os
import shutil
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]

from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.invocation import (
    AgentProfileSpec,
    CapabilityResolutionError,
    CodexLoginBinding,
    CredentialBinding,
    EffectiveCapabilityPlan,
    ExternalCapabilitySet,
    InvocationLimits,
    NodeCapabilityRequirement,
    ReasoningEffort,
    ResolvedAgentProfile,
    RoleCapabilityMaximum,
    SandboxMode,
    SkillBundleSpec,
    compile_effective_capability_plan,
)
from agent_world.invocation.contracts import JsonObject
from agent_world.invocation.profiles import ProfileResolver

_ROLES = frozenset({"researcher", "environment-engineer", "challenger"})
_SOLVER_NODE_ID = "challenger.reachability-solver"
_SOLVER_RUNTIME_DIRECTORY = ".agent-solver-runtimes"


class IsolatedAgentProfileProvider:
    """Resolve exactly three roles; no ambient profile, skill, hook or MCP fallback."""

    def __init__(
        self,
        config: AgentBackendConfig,
        *,
        assets_root: Path | None = None,
        source_environment: dict[str, str] | None = None,
    ) -> None:
        self.config = config
        self.assets_root = (
            assets_root or Path(__file__).with_name("agent_assets") / "skills"
        ).resolve(strict=True)
        self.source_environment = dict(
            os.environ if source_environment is None else source_environment
        )
        self.codex_bin = config.codex_bin
        self.codex_bin_sha256: str | None = None
        if self.codex_bin is not None:
            if (
                self.codex_bin.is_symlink()
                or not self.codex_bin.is_file()
                or not os.access(self.codex_bin, os.X_OK)
            ):
                raise ValueError("configured codex_bin must be a real executable file")
            self.codex_bin_sha256 = _sha256(self.codex_bin)
        handle = "model-auth"
        if config.chatgpt_auth_file is not None:
            binding: CredentialBinding | CodexLoginBinding = CodexLoginBinding(
                handle=handle,
                source=config.chatgpt_auth_file,
            )
        else:
            assert config.api_key_environment is not None
            binding = CredentialBinding(
                handle=handle,
                source_environment=config.api_key_environment,
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        self.resolver = ProfileResolver(
            credential_bindings={handle: binding},
            allowed_credential_handles=(handle,),
        )

    def resolve(
        self,
        *,
        role: str,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
        rollout_token_limit: int | None = None,
        invocation_timeout_seconds: float | None = None,
    ) -> ResolvedAgentProfile:
        return self._resolve(
            role=role,
            lineage_id=lineage_id,
            workspace=workspace,
            output_schema=output_schema,
            permissions=permissions,
            requirement=requirement,
            rollout_token_limit=rollout_token_limit,
            invocation_timeout_seconds=invocation_timeout_seconds,
        )

    def _resolve(
        self,
        *,
        role: str,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
        rollout_token_limit: int | None,
        invocation_timeout_seconds: float | None,
    ) -> ResolvedAgentProfile:
        if role not in _ROLES:
            raise ValueError(f"unsupported Agent role: {role}")
        if requirement.role != role:
            raise CapabilityResolutionError(requirement.node_id, ("role",))
        capability_plan = compile_effective_capability_plan(
            role_maximum=self._role_maximum(role),
            job_permission=permissions,
            requirement=requirement,
        )
        logical_workspace = workspace.expanduser().resolve()
        logical_workspace.mkdir(parents=True, exist_ok=True)
        materialization_root = logical_workspace / ".agent-runtime"
        agent_workspace = materialization_root / "workspace"
        resolved = self.resolver.resolve(
            self._spec(
                role,
                cast(JsonObject, output_schema),
                capability_plan=capability_plan,
                rollout_token_limit=rollout_token_limit,
                invocation_timeout_seconds=invocation_timeout_seconds,
            ),
            # Framework artifact/job ids intentionally use typed ``:``
            # separators, while ProfileResolver requires an identity that is
            # safe to place in Codex configuration and local runtime paths.
            # Keep already-safe ids readable and bind every other logical id
            # through a full collision-resistant digest.  This conversion is
            # centralized here so Direct, Discovery, Evolve, Judge and repair
            # continuations cannot disagree about session identity.
            lineage_id=_profile_lineage_id(lineage_id),
            materialization_root=materialization_root,
            workspace=agent_workspace,
            source_environment=self.source_environment,
        )
        self._copy_framework_inputs(logical_workspace, resolved.workspace)
        return resolved

    def resolve_solver(
        self,
        *,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        rollout_token_limit: int,
    ) -> ResolvedAgentProfile:
        """Materialize Challenger's tool-free interactive reachability mode.

        The supplied ``workspace`` is only a framework-owned parent for private
        runtime directories.  Its contents are deliberately not staged or
        mounted into the Agent workspace: task, observation and tool schemas
        reach the solver exclusively through the invocation prompt.  A fresh
        materialization root on every call also prevents one sampled episode
        from inheriting another episode's Codex state or history.
        """

        if isinstance(rollout_token_limit, bool) or not isinstance(
            rollout_token_limit, int
        ):
            raise TypeError("rollout_token_limit must be an integer")
        if rollout_token_limit <= 0:
            raise ValueError("rollout_token_limit must be positive")
        if not lineage_id or lineage_id != lineage_id.strip():
            raise ValueError("lineage_id must be non-empty and canonical")
        solver_schema = copy.deepcopy(output_schema)
        _validate_closed_output_envelope(solver_schema)

        logical_workspace = workspace.expanduser()
        if logical_workspace.is_symlink():
            raise ValueError("reachability workspace must not be a symlink")
        logical_workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        logical_workspace = logical_workspace.resolve(strict=True)
        runtime_parent = logical_workspace / _SOLVER_RUNTIME_DIRECTORY
        if runtime_parent.is_symlink():
            raise ValueError("reachability solver runtime directory must not be a symlink")
        runtime_parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        runtime_parent.chmod(0o700)
        full_lineage_digest = hashlib.sha256(lineage_id.encode("utf-8")).hexdigest()
        lineage_digest = full_lineage_digest[:16]
        materialization_root = runtime_parent / f"{lineage_digest}-{uuid.uuid4().hex}"
        agent_workspace = materialization_root / "workspace"

        requirement = NodeCapabilityRequirement(
            node_id=_SOLVER_NODE_ID,
            role="challenger",
            sandbox=SandboxMode.READ_ONLY,
            intrinsic_builtin_tools=(),
            external=ExternalCapabilitySet(),
        )
        capability_plan = compile_effective_capability_plan(
            role_maximum=self._role_maximum("challenger"),
            job_permission=PermissionScope(),
            requirement=requirement,
        )
        return self.resolver.resolve(
            self._solver_spec(
                cast(JsonObject, solver_schema),
                capability_plan=capability_plan,
                rollout_token_limit=rollout_token_limit,
            ),
            # Judge lineage ids intentionally carry typed ':' separators, while
            # ProfileResolver accepts filesystem-safe identities only.  Bind the
            # full caller identity through a collision-resistant digest instead
            # of weakening the resolver's global name policy.
            lineage_id=f"reachability-{full_lineage_digest}",
            materialization_root=materialization_root,
            workspace=agent_workspace,
            source_environment=self.source_environment,
        )

    def profile_descriptor(
        self,
        role: str,
        *,
        permissions: PermissionScope,
        requirement: NodeCapabilityRequirement,
    ) -> dict[str, object]:
        if role not in _ROLES:
            raise ValueError(f"unsupported Agent role: {role}")
        capability_plan = compile_effective_capability_plan(
            role_maximum=self._role_maximum(role),
            job_permission=permissions,
            requirement=requirement,
        )
        spec = self._spec(role, None, capability_plan=capability_plan)
        return {
            "profile_id": spec.profile_id,
            "profile_version": spec.profile_version,
            "backend": "codex_sdk",
            "model": spec.model,
            "model_provider": spec.model_provider,
            "openai_base_url": spec.openai_base_url,
            "codex_bin_sha256": spec.codex_bin_sha256,
            "reasoning_effort": spec.reasoning_effort.value,
            "sandbox": spec.sandbox.value,
            "allowed_builtin_tools": list(spec.allowed_builtin_tools),
            "allowed_network_domains": list(spec.allowed_network_domains),
            "skills": [item.name for item in spec.skills],
            "hooks": [],
            "mcp_servers": [],
            "authentication_kind": (
                "chatgpt" if self.config.chatgpt_auth_file is not None else "api_key"
            ),
            "effective_capability_plan": capability_plan.to_public_dict(),
        }

    def _spec(
        self,
        role: str,
        output_schema: JsonObject | None,
        *,
        capability_plan: EffectiveCapabilityPlan,
        rollout_token_limit: int | None = None,
        invocation_timeout_seconds: float | None = None,
    ) -> AgentProfileSpec:
        skill_names = {
            "researcher": "research-world-evidence",
            "environment-engineer": "engineer-agent-world",
            "challenger": "challenge-agent-world",
        }
        reasoning = {
            "researcher": self.config.reasoning_researcher,
            "environment-engineer": self.config.reasoning_engineer,
            "challenger": self.config.reasoning_challenger,
        }
        instructions = {
            "researcher": (
                "Research and synthesize only from framework-provided fetched evidence. "
                "Never claim a search or fetch occurred merely from model memory."
            ),
            "environment-engineer": (
                "Design or implement the complete executable programmatic world in the isolated "
                "workspace. WorldSpec owns semantics; never invent sealed evaluation data."
            ),
            "challenger": (
                "Challenge evidence, design and black-box behavior without editing candidate code "
                "or deciding release. Produce only the requested typed verifier proposal."
            ),
        }
        skill_source = self.assets_root / skill_names[role]
        tool_free = not capability_plan.intrinsic_builtin_tools
        role_timeout = (
            self.config.environment_codegen_invocation_timeout_seconds
            if role == "environment-engineer"
            else self.config.structured_invocation_timeout_seconds
        )
        default_limits = InvocationLimits()
        structured_event_limit = (
            max(default_limits.max_events, rollout_token_limit)
            if output_schema is not None and rollout_token_limit is not None
            else default_limits.max_events
        )
        return AgentProfileSpec(
            profile_id=role,
            profile_version="3",
            model=self.config.model,
            model_provider=self.config.model_provider,
            openai_base_url=(
                str(self.config.openai_base_url)
                if self.config.openai_base_url is not None
                else None
            ),
            reasoning_effort=ReasoningEffort(reasoning[role]),
            base_instructions=(
                "Agent World Foundry turns a short human need into a real executable environment "
                "whose program code owns state transitions and whose release is decided by "
                "framework gates. " + instructions[role]
            ),
            developer_instructions=(
                skill_source.joinpath("SKILL.md").read_text(encoding="utf-8")
                if tool_free
                else None
            ),
            authentication_handle="model-auth",
            effective_capability_plan=capability_plan,
            codex_bin=self.codex_bin,
            codex_bin_sha256=self.codex_bin_sha256,
            sandbox=capability_plan.sandbox,
            allowed_builtin_tools=capability_plan.intrinsic_builtin_tools,
            allowed_network_domains=capability_plan.external.network_domains,
            skills=()
            if tool_free
            else (
                SkillBundleSpec(
                    name=skill_names[role],
                    source=skill_source,
                ),
            ),
            hooks=(),
            mcp_servers=(),
            credential_handles=(
                "model-auth",
                *capability_plan.external.credential_handles,
            ),
            output_schema=output_schema,
            rollout_token_limit=rollout_token_limit,
            tool_output_token_limit=self.config.tool_output_token_limit,
            limits=InvocationLimits(
                timeout_seconds=min(
                    self.config.invocation_timeout_seconds,
                    role_timeout,
                    invocation_timeout_seconds
                    if invocation_timeout_seconds is not None
                    else self.config.invocation_timeout_seconds,
                ),
                max_events=structured_event_limit,
            ),
        )

    def _solver_spec(
        self,
        output_schema: JsonObject,
        *,
        capability_plan: EffectiveCapabilityPlan,
        rollout_token_limit: int,
    ) -> AgentProfileSpec:
        return AgentProfileSpec(
            profile_id="challenger",
            profile_version="reachability-solver-1",
            model=self.config.model,
            model_provider=self.config.model_provider,
            openai_base_url=(
                str(self.config.openai_base_url)
                if self.config.openai_base_url is not None
                else None
            ),
            reasoning_effort=ReasoningEffort(self.config.reasoning_challenger),
            base_instructions=(
                "Agent World Foundry turns a short human need into a real executable "
                "environment whose program code owns state transitions. You are Challenger "
                "in isolated reachability-solver mode. Use only the PublicTask, public "
                "observations, public tool schemas, and public tool results present in the "
                "invocation conversation. Select one public tool action at a time. You have "
                "no authority to determine reward, termination, reachability, or release. "
                "Never request or infer candidate source, sealed cases, EvaluatorGoal, Rule "
                "IR, verifier internals, or release policy."
            ),
            authentication_handle="model-auth",
            effective_capability_plan=capability_plan,
            codex_bin=self.codex_bin,
            codex_bin_sha256=self.codex_bin_sha256,
            sandbox=SandboxMode.READ_ONLY,
            allowed_builtin_tools=(),
            allowed_network_domains=(),
            skills=(),
            hooks=(),
            mcp_servers=(),
            credential_handles=("model-auth",),
            output_schema=output_schema,
            rollout_token_limit=rollout_token_limit,
            tool_output_token_limit=self.config.tool_output_token_limit,
            limits=InvocationLimits(timeout_seconds=self.config.invocation_timeout_seconds),
        )

    def _role_maximum(self, role: str) -> RoleCapabilityMaximum:
        write = role == "environment-engineer"
        network_domains = (
            tuple(sorted(self.config.engineer_network_domain_ceiling)) if write else ()
        )
        return RoleCapabilityMaximum(
            role=role,
            policy_version="1",
            maximum_sandbox=(
                SandboxMode.WORKSPACE_WRITE if write else SandboxMode.READ_ONLY
            ),
            intrinsic_builtin_tools=("shell", "workspace_edit") if write else ("shell",),
            external=ExternalCapabilitySet(network_domains=network_domains),
        )

    @staticmethod
    def _copy_framework_inputs(source: Path, destination: Path) -> None:
        file_count = 0
        total_bytes = 0
        for path in sorted(source.rglob("*"), key=lambda item: item.relative_to(source).as_posix()):
            relative = path.relative_to(source)
            if not relative.parts or relative.parts[0] == ".agent-runtime":
                continue
            if path.is_symlink():
                raise ValueError(f"Agent input may not be a symlink: {relative}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError(f"Agent input must be a regular file: {relative}")
            file_count += 1
            total_bytes += path.stat().st_size
            if file_count > 10_000 or total_bytes > 512 * 1024 * 1024:
                raise ValueError("Agent inputs exceed the fixed staging limit")
            target = destination / relative
            if target.exists():
                if target.is_symlink() or not target.is_file():
                    raise ValueError(f"Agent workspace input was replaced: {relative}")
                if _sha256(target) != _sha256(path):
                    raise ValueError(
                        f"Agent workspace input changed during one lineage: {relative}"
                    )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target, follow_symlinks=False)
            target.chmod(0o400)


def _profile_lineage_id(value: str) -> str:
    """Map one logical framework lineage to ProfileResolver's safe namespace."""

    if not value or value != value.strip():
        raise ValueError("lineage_id must be non-empty and canonical")
    if (
        len(value) <= 128
        and value.isascii()
        and value[0].isalnum()
        and all(character.isalnum() or character in "_.-" for character in value)
    ):
        return value
    return f"lineage-{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_closed_output_envelope(schema: Mapping[str, Any]) -> None:
    """Require a valid object envelope with no implicit object-key expansion.

    Solver decisions contain a dictionary of runtime tool arguments, so an
    explicitly schema-valued ``additionalProperties`` is allowed there.  What
    is forbidden is an object schema that omits its closure policy or sets it
    to ``true``.  This preserves an exact decision envelope while allowing the
    per-tool argument payload validated later by the real Runtime surface.
    """

    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise ValueError(f"solver output_schema is invalid: {exc.message}") from exc
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError(
            "solver output_schema must be a closed object with additionalProperties=false"
        )

    def visit(node: object, *, location: str) -> None:
        if isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, location=f"{location}/{index}")
            return
        if not isinstance(node, Mapping):
            return
        reference = node.get("$ref")
        if reference is not None and (
            not isinstance(reference, str) or not reference.startswith("#/")
        ):
            raise ValueError(
                f"solver output_schema contains a non-local $ref at {location}"
            )
        if "$dynamicRef" in node:
            raise ValueError(
                f"solver output_schema contains unsupported $dynamicRef at {location}"
            )
        declared_type = node.get("type")
        declares_object = declared_type == "object" or (
            isinstance(declared_type, list) and "object" in declared_type
        )
        if declares_object:
            additional = node.get("additionalProperties")
            if additional is None or additional is True:
                raise ValueError(
                    "solver output_schema object nodes must explicitly forbid or schema-bind "
                    f"additionalProperties at {location}"
                )
            if node.get("unevaluatedProperties") is True or node.get("patternProperties"):
                raise ValueError(
                    f"solver output_schema contains open object-key rules at {location}"
                )
        for key, child in node.items():
            if key in {"default", "const", "enum", "examples"}:
                continue
            visit(child, location=f"{location}/{key}")

    visit(schema, location="#")


__all__ = ["IsolatedAgentProfileProvider"]

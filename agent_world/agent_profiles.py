"""Private invocation profiles for Direct LLM and real Codex Agent nodes."""

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
from agent_world.invocation.codex_runtime import CodexRuntimeUnavailable, resolve_codex_runtime
from agent_world.invocation.contracts import JsonObject
from agent_world.invocation.profiles import API_KEY_RUNTIME_PROVIDER, ProfileResolver

_ROLES = frozenset({"researcher", "environment-engineer", "challenger"})
_SOLVER_NODE_ID = "challenger.reachability-solver"
_SOLVER_RUNTIME_DIRECTORY = ".agent-solver-runtimes"
_FALLBACK_ROUTE_DIRECTORY_PREFIX = "route-"
_FALLBACK_ROUTE_DIGEST_LENGTH = 64


def logical_workspace_for_agent_workspace(workspace: Path) -> Path:
    """Recover the frozen input root from one Agent profile workspace.

    Primary profiles live directly below ``.agent-runtime``.  A selected
    fallback model uses a child route root so it cannot overwrite the primary
    profile marker/configuration.  Continuation callers receive only the
    private Agent workspace, so this shared parser keeps Builder and legacy
    Designer resumption aligned with the materialization policy.
    """

    requested = workspace.expanduser()
    if requested.is_symlink():
        raise ValueError("Agent workspace must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir() or resolved.name != "workspace":
        raise ValueError("Agent workspace has an invalid layout")
    materialization_root = resolved.parent
    runtime_root = materialization_root
    if materialization_root.name != ".agent-runtime":
        route_name = materialization_root.name
        route_digest = route_name.removeprefix(_FALLBACK_ROUTE_DIRECTORY_PREFIX)
        if (
            not route_name.startswith(_FALLBACK_ROUTE_DIRECTORY_PREFIX)
            or len(route_digest) != _FALLBACK_ROUTE_DIGEST_LENGTH
            or any(character not in "0123456789abcdef" for character in route_digest)
            or materialization_root.parent.name != ".agent-runtime"
        ):
            raise ValueError("Agent fallback workspace has an invalid layout")
        runtime_root = materialization_root.parent
    if runtime_root.is_symlink() or runtime_root.parent.is_symlink():
        raise ValueError("Agent runtime layout must not contain symlinks")
    return runtime_root.parent


class AgentProfileProvider:
    """Resolve exactly three roles; no ambient profile, Skill, or MCP fallback."""

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
        # A prompt-only Direct LLM must not resolve, pin, or materialize the
        # Codex runtime at all. Resolve that executable lazily only for a node
        # that actually asks for Agent tools.
        self.codex_bin: Path | None = None
        self.codex_bin_sha256: str | None = None
        handle = "model-auth"
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

    def _ensure_codex_runtime(self) -> None:
        """Resolve the pinned SDK executable only for a real Codex Agent."""

        if self.codex_bin is not None:
            return
        try:
            codex_runtime = resolve_codex_runtime(self.config.codex_bin)
        except CodexRuntimeUnavailable as exc:
            raise ValueError(str(exc)) from exc
        self.codex_bin = codex_runtime.path
        self.codex_bin_sha256 = codex_runtime.sha256

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
        model_override: str | None = None,
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
            model_override=model_override,
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
        model_override: str | None,
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
        agentic = bool(capability_plan.intrinsic_builtin_tools)
        if agentic:
            self._ensure_codex_runtime()
        logical_workspace = workspace.expanduser().resolve()
        logical_workspace.mkdir(parents=True, exist_ok=True)
        materialization_root = logical_workspace / ".agent-runtime"
        resolved_model = self._configured_model(model_override)
        if resolved_model != self.config.model:
            # A selected fallback is a new physical node session.  It must not
            # overwrite the primary profile marker/configuration in the same
            # logical frozen-input root, while it must still stage that exact
            # root's immutable inputs.  The directory uses only a digest of a
            # configured non-secret model name; no Provider/session identity
            # reaches the filesystem layout.
            route_digest = hashlib.sha256(resolved_model.encode("utf-8")).hexdigest()
            materialization_root = materialization_root / (
                f"{_FALLBACK_ROUTE_DIRECTORY_PREFIX}{route_digest}"
            )
        agent_workspace = materialization_root / "workspace"
        spec = self._spec(
            role,
            cast(JsonObject, output_schema),
            capability_plan=capability_plan,
            rollout_token_limit=rollout_token_limit,
            invocation_timeout_seconds=invocation_timeout_seconds,
            model_override=model_override,
        )
        resolve_profile = self.resolver.resolve if agentic else self.resolver.resolve_direct
        resolved = resolve_profile(
            spec,
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
        if agentic:
            self._copy_framework_inputs(logical_workspace, resolved.workspace)
        return resolved

    def resolve_solver(
        self,
        *,
        lineage_id: str,
        workspace: Path,
        output_schema: dict[str, object],
        rollout_token_limit: int,
        invocation_timeout_seconds: float | None = None,
        model_override: str | None = None,
    ) -> ResolvedAgentProfile:
        """Materialize a source-blind, prompt-only public episode solver.

        The interactive Challenger does not receive a Codex tool, workspace
        input, Runtime source, or private evaluator state.  It is therefore a
        Direct LLM loop, not a tool-free pseudo-Agent session.  Each turn gets
        its complete public episode trace from the node Prompt.  The supplied
        ``workspace`` remains only a framework-owned parent for an empty,
        per-run profile root, so no candidate or Judge-private file can be
        copied into the Direct profile by accident.
        """

        if isinstance(rollout_token_limit, bool) or not isinstance(rollout_token_limit, int):
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

        # ``resolve`` stages framework input files below the logical workspace.
        # Give it a new empty child rather than the caller's Judge workspace so
        # this Direct LLM can never inherit candidate or evaluator files.
        direct_logical_workspace = agent_workspace / "prompt-only"
        return self.resolve(
            role="challenger",
            lineage_id=f"reachability-{full_lineage_digest}",
            workspace=direct_logical_workspace,
            output_schema=cast(dict[str, object], solver_schema),
            permissions=PermissionScope(),
            requirement=NodeCapabilityRequirement.structured_output(
                node_id=_SOLVER_NODE_ID,
                role="challenger",
            ),
            rollout_token_limit=rollout_token_limit,
            invocation_timeout_seconds=invocation_timeout_seconds,
            model_override=model_override,
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
        if capability_plan.intrinsic_builtin_tools:
            self._ensure_codex_runtime()
        spec = self._spec(role, None, capability_plan=capability_plan)
        agentic = bool(capability_plan.intrinsic_builtin_tools)
        return {
            "profile_id": spec.profile_id,
            "profile_version": spec.profile_version,
            "backend": "codex_sdk" if agentic else "direct_llm",
            "model": spec.model,
            "model_provider": spec.model_provider,
            "openai_base_url_environment": spec.openai_base_url_environment,
            "codex_bin_sha256": spec.codex_bin_sha256 if agentic else None,
            "reasoning_effort": spec.reasoning_effort.value,
            "sandbox": spec.sandbox.value,
            "allowed_builtin_tools": list(spec.allowed_builtin_tools),
            "allowed_network_domains": list(spec.allowed_network_domains),
            "skills": [item.name for item in spec.skills],
            "mcp_servers": [],
            "authentication_kind": "api_key",
            "direct_provider_max_output_tokens": spec.direct_provider_max_output_tokens,
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
        model_override: str | None = None,
    ) -> AgentProfileSpec:
        skill_names: dict[str, tuple[str, ...]] = {
            "researcher": ("research-world-evidence",),
            "environment-engineer": ("engineer-agent-world",),
            "challenger": ("challenge-agent-world",),
        }
        reasoning = {
            "researcher": self.config.reasoning_researcher,
            "environment-engineer": self.config.reasoning_engineer,
            "challenger": self.config.reasoning_challenger,
        }
        selected_skill_names = skill_names[role]
        if role == "environment-engineer":
            engineer_node_modes = {
                "environment-engineer.implementation-plan": ("engineer-build-planning",),
                "environment-engineer.runtime-build": ("engineer-environment-codegen",),
            }
            selected_skill_names = engineer_node_modes.get(
                capability_plan.node_id,
                selected_skill_names,
            )
        agentic = bool(capability_plan.intrinsic_builtin_tools)
        # Never even select a Runtime Skill for a Direct LLM route.  Its only
        # semantic input is the node's rendered Prompt; a path that happens to
        # exist must not become an implicit instruction dependency later.
        skills = (
            tuple(
                SkillBundleSpec(name=skill_name, source=self.assets_root / skill_name)
                for skill_name in selected_skill_names
            )
            if agentic
            else ()
        )
        # Role is a capability boundary, not a timeout class.  Environment
        # Engineer serves both structured Designer transactions and Builder
        # codegen: the latter already passes its own immutable per-turn budget
        # from ``EnvironmentBuilder``.  Capping every Engineer call here by
        # the codegen setting would silently truncate a structured node even
        # when its Scheduler policy and configured structured limit allow it.
        operation_timeout = (
            invocation_timeout_seconds
            if invocation_timeout_seconds is not None
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
            profile_version="12",
            model=self._configured_model(model_override),
            model_provider=API_KEY_RUNTIME_PROVIDER,
            openai_base_url_environment=self.config.openai_base_url_environment,
            reasoning_effort=ReasoningEffort(reasoning[role]),
            # There is intentionally no profile-owned instruction field. A
            # Direct LLM receives its rendered Prompt; a Codex Agent receives
            # only the focused mounted Skills for its node plus the visible
            # Prompt that names the turn-specific work.
            authentication_handle="model-auth",
            effective_capability_plan=capability_plan,
            # ``self.codex_bin`` is a lazy cache for real Codex Agent nodes.
            # A Direct profile can be resolved after an Agent node in the same
            # process, but it must remain prompt-only: carrying that cache into
            # the Direct spec makes ``ProfileResolver.resolve_direct`` reject
            # an otherwise valid profile as a pseudo-Agent runtime.
            codex_bin=self.codex_bin if agentic else None,
            codex_bin_sha256=self.codex_bin_sha256 if agentic else None,
            sandbox=capability_plan.sandbox,
            allowed_builtin_tools=capability_plan.intrinsic_builtin_tools,
            allowed_network_domains=capability_plan.external.network_domains,
            skills=skills,
            mcp_servers=(),
            credential_handles=(
                "model-auth",
                *capability_plan.external.credential_handles,
            ),
            output_schema=output_schema,
            rollout_token_limit=rollout_token_limit,
            direct_provider_max_output_tokens=(self.config.direct_provider_max_output_tokens),
            tool_output_token_limit=self.config.tool_output_token_limit,
            limits=InvocationLimits(
                timeout_seconds=min(
                    self.config.invocation_timeout_seconds,
                    operation_timeout,
                ),
                provider_stream_idle_timeout_seconds=(
                    self.config.provider_stream_idle_timeout_seconds
                ),
                provider_first_event_timeout_seconds=(
                    self.config.provider_first_event_timeout_seconds
                ),
                max_events=structured_event_limit,
                provider_transport_max_retries=(self.config.provider_transport_max_retries),
            ),
        )

    def _role_maximum(self, role: str) -> RoleCapabilityMaximum:
        """Return the widest capability set a role may ever request.

        A ceiling, not a grant: a node still has to request a capability and the
        job permission still has to allow it. Runtime tools are not modelled here, so a
        role cannot end up holding a tool the runtime withholds or vice versa.
        """

        write = role == "environment-engineer"
        # Egress is not per-role guesswork.  An Agent that can look things up but
        # can only write its disposable workspace cannot affect anything the Judge
        # evaluates, so every role shares the configured lookup ceiling and the
        # Engineer adds its dependency-install ceiling on top.
        lookup_domains = set(self.config.research_network_domain_ceiling)
        network_domains = tuple(
            sorted(
                lookup_domains | set(self.config.engineer_network_domain_ceiling)
                if write
                else lookup_domains
            )
        )
        intrinsic: tuple[str, ...] = ("shell", "workspace_edit") if write else ("shell",)
        return RoleCapabilityMaximum(
            role=role,
            policy_version="2",
            maximum_sandbox=SandboxMode.FULL_ACCESS,
            intrinsic_builtin_tools=intrinsic,
            external=ExternalCapabilitySet(network_domains=network_domains),
        )

    @property
    def model_routes(self) -> tuple[str, ...]:
        """The non-secret configured route order, including the primary model."""

        return self.config.model_routes

    def _configured_model(self, model_override: str | None) -> str:
        """Reject an undeclared route before materializing a private profile."""

        if model_override is None:
            return self.config.model
        if model_override not in self.config.model_routes:
            raise ValueError("model_override is not an explicitly configured fallback route")
        return model_override

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
    """Map one logical framework lineage to ProfileResolver's private layout."""

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
            raise ValueError(f"solver output_schema contains a non-local $ref at {location}")
        if "$dynamicRef" in node:
            raise ValueError(f"solver output_schema contains unsupported $dynamicRef at {location}")
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


__all__ = ["AgentProfileProvider", "logical_workspace_for_agent_workspace"]

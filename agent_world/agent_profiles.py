"""Three hermetic Agent profiles used by every semantic pipeline node."""

from __future__ import annotations

import copy
import hashlib
import json
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


def logical_workspace_for_isolated_agent_workspace(workspace: Path) -> Path:
    """Recover the frozen input root from one isolated profile workspace.

    Primary profiles live directly below ``.agent-runtime``.  A selected
    fallback model uses a child route root so it cannot overwrite the primary
    profile marker/configuration.  Continuation callers receive only the
    private Agent workspace, so this shared parser keeps Builder and legacy
    Designer resumption aligned with the materialization policy.
    """

    requested = workspace.expanduser()
    if requested.is_symlink():
        raise ValueError("isolated Agent workspace must not be a symlink")
    resolved = requested.resolve(strict=True)
    if not resolved.is_dir() or resolved.name != "workspace":
        raise ValueError("isolated Agent workspace has an invalid layout")
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
            raise ValueError("isolated Agent fallback workspace has an invalid layout")
        runtime_root = materialization_root.parent
    if runtime_root.is_symlink() or runtime_root.parent.is_symlink():
        raise ValueError("isolated Agent runtime layout must not contain symlinks")
    return runtime_root.parent


def _logical_output_schema_instructions(
    output_schema: JsonObject | None,
    *,
    transport: str,
) -> str | None:
    """Render the logical contract when a Direct transport cannot carry it.

    ``json_envelope`` deliberately asks the Provider to enforce only a small
    outer object.  The model still needs the complete inner artifact contract;
    otherwise it can produce a syntactically valid envelope whose payload uses
    plausible but wrong field names.  ``json_object`` has the same need because
    its compatible-gateway response mode carries no JSON Schema at all.
    """

    if output_schema is None or transport == "provider_schema":
        return None
    schema_json = json.dumps(
        output_schema,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if transport == "json_envelope":
        transport_instruction = (
            "Return only the outer JSON object with the one field artifact_json. "
            "Its string value must decode to one JSON value that satisfies the "
            "logical schema below; the small outer envelope is not the artifact schema."
        )
    elif transport == "json_object":
        transport_instruction = "Return one direct JSON value satisfying the logical schema below."
    else:
        raise ValueError(f"unsupported structured output transport: {transport}")
    return "\n".join(
        (
            "## Logical structured output contract",
            transport_instruction,
            "Use the literal property names and closed-object rules in this schema. "
            "Do not substitute aliases, add prose, Markdown fences, or extra fields.",
            "Input/context documents may have their own schema_version or similarly named "
            "fields; they are data for the task, not fields to copy into this output. When this "
            "logical schema declares a const value, emit exactly that value if you include the "
            "field; otherwise omit a defaulted field only when this schema permits omission.",
            "<logical_output_schema_json>",
            schema_json,
            "</logical_output_schema_json>",
        )
    )


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
        try:
            codex_runtime = resolve_codex_runtime(config.codex_bin)
        except CodexRuntimeUnavailable as exc:
            raise ValueError(str(exc)) from exc
        # The outer worker and its inner bwrap command sandbox must use this
        # same pinned executable.  Materializing it on every profile prevents
        # the worker's bundled-runtime fallback from becoming an invisible
        # unmounted dependency at command execution time.
        self.codex_bin = codex_runtime.path
        self.codex_bin_sha256 = codex_runtime.sha256
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
        resolved = self.resolver.resolve(
            self._spec(
                role,
                cast(JsonObject, output_schema),
                capability_plan=capability_plan,
                rollout_token_limit=rollout_token_limit,
                invocation_timeout_seconds=invocation_timeout_seconds,
                model_override=model_override,
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
        model_override: str | None = None,
    ) -> ResolvedAgentProfile:
        """Materialize Challenger's tool-free interactive reachability mode.

        The supplied ``workspace`` is only a framework-owned parent for private
        runtime directories.  Its contents are deliberately not staged or
        mounted into the Agent workspace: task, observation and tool schemas
        reach the solver exclusively through the invocation prompt.  A fresh
        materialization root on every call also prevents one sampled episode
        from inheriting another episode's Codex state or history.
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
                model_override=model_override,
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
            "openai_base_url_environment": spec.openai_base_url_environment,
            "codex_bin_sha256": spec.codex_bin_sha256,
            "reasoning_effort": spec.reasoning_effort.value,
            "sandbox": spec.sandbox.value,
            "allowed_builtin_tools": list(spec.allowed_builtin_tools),
            "allowed_network_domains": list(spec.allowed_network_domains),
            "skills": [item.name for item in spec.skills],
            "hooks": [],
            "mcp_servers": [],
            "authentication_kind": "api_key",
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
                "workspace. WorldSpec owns semantics; implement only declared Candidate surfaces."
            ),
            "challenger": (
                "Challenge evidence, design and black-box behavior without editing candidate code "
                "or deciding release. Produce only the requested typed verifier proposal."
            ),
        }
        skill_name = skill_names[role]
        instruction = instructions[role]
        if role == "environment-engineer":
            engineer_node_modes = {
                "environment-engineer.implementation-plan": (
                    "engineer-build-planning",
                    (
                        "Read the frozen implementation inputs and produce one compact advisory "
                        "implementation map, not an exhaustive rule transcription. Do not write "
                        "candidate source."
                    ),
                ),
                "environment-engineer.runtime-build": (
                    "engineer-environment-codegen",
                    (
                        "Implement one complete executable Candidate in the isolated workspace. "
                        "Frozen WorldSpec and the implementation contract own semantics; use only "
                        "declared Candidate interfaces."
                    ),
                ),
            }
            selected = engineer_node_modes.get(capability_plan.node_id)
            if selected is not None:
                skill_name, instruction = selected
        skill_source = self.assets_root / skill_name
        tool_free = not capability_plan.intrinsic_builtin_tools
        workspace_toolchain = (
            role == "environment-engineer"
            and capability_plan.sandbox is SandboxMode.WORKSPACE_WRITE
            and "shell" in capability_plan.intrinsic_builtin_tools
        )
        runtime_build = (
            role == "environment-engineer"
            and capability_plan.node_id == "environment-engineer.runtime-build"
        )
        structured_output_transport = self.config.structured_output_transport
        if structured_output_transport == "json_object" and not tool_free:
            # ``json_object`` is deliberately a DirectLlmBackend transport:
            # it eliminates a fragile double-serialization task for one-shot
            # Designer proposals.  A workspace Agent turn continues to use
            # the Codex SDK's native schema channel, while its logical Builder
            # budget and continuation policy remain unchanged.
            structured_output_transport = "provider_schema"
        developer_instruction_parts: list[str] = []
        if tool_free or runtime_build:
            developer_instruction_parts.append(
                skill_source.joinpath("SKILL.md").read_text(encoding="utf-8")
            )
        if runtime_build:
            developer_instruction_parts.append(
                "\n".join(
                    (
                        "## Isolated CandidateBuild working context",
                        "You are already at the isolated workspace root. Use relative paths such "
                        "as `inputs/...` and `candidate/...`; never reconstruct or search for "
                        "host, Codex, or profile absolute paths.",
                        "Use `./.agent-world-tools/uv` for every uv operation and "
                        "`./.agent-world-tools/python3.12` for compact JSON inspection. Bare "
                        "`uv`, bare `python`, and a generation-workspace `.venv` are not "
                        "provisioned interfaces. For uv commands that select or create a Python "
                        "runtime, pass `--python ./.agent-world-tools/python3.12` explicitly; "
                        "do not rely on PATH or `UV_PYTHON`.",
                        "Read every frozen input through focused fields rather than dumping full "
                        "JSON into tool output. After the initial concise pass, create the "
                        "`candidate/` project skeleton before any further deep schema lookup, "
                        "then validate incrementally.",
                        "If one shell command fails, first run `pwd` and retry the intended "
                        "relative command. Do not spend the turn scanning parent directories or "
                        "guessing an alternate host toolchain.",
                    )
                )
            )
        logical_output_schema_instructions = _logical_output_schema_instructions(
            output_schema,
            transport=structured_output_transport,
        )
        if logical_output_schema_instructions is not None:
            developer_instruction_parts.append(logical_output_schema_instructions)
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
            profile_version="7",
            model=self._configured_model(model_override),
            model_provider=API_KEY_RUNTIME_PROVIDER,
            openai_base_url_environment=self.config.openai_base_url_environment,
            reasoning_effort=ReasoningEffort(reasoning[role]),
            base_instructions=(
                "Agent World Foundry turns a short human need into a real executable environment "
                "whose program code owns state transitions and whose release is decided by "
                "framework gates. " + instruction
            ),
            developer_instructions=("\n\n".join(developer_instruction_parts) or None),
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
                    name=skill_name,
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
            structured_output_transport=structured_output_transport,
            rollout_token_limit=rollout_token_limit,
            tool_output_token_limit=self.config.tool_output_token_limit,
            required_runtime_tools=("uv",) if workspace_toolchain else (),
            limits=InvocationLimits(
                timeout_seconds=min(
                    self.config.invocation_timeout_seconds,
                    operation_timeout,
                ),
                direct_stream_idle_timeout_seconds=self.config.direct_stream_idle_timeout_seconds,
                max_events=structured_event_limit,
            ),
        )

    def _solver_spec(
        self,
        output_schema: JsonObject,
        *,
        capability_plan: EffectiveCapabilityPlan,
        rollout_token_limit: int,
        model_override: str | None = None,
    ) -> AgentProfileSpec:
        return AgentProfileSpec(
            profile_id="challenger",
            profile_version="reachability-solver-1",
            model=self._configured_model(model_override),
            model_provider=API_KEY_RUNTIME_PROVIDER,
            openai_base_url_environment=self.config.openai_base_url_environment,
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
            # The reachability solver has no tools, but it is not a Direct
            # one-shot proposal: its interactive loop is an Agentic Codex
            # session and resumes that session for later public actions.
            # ``json_object`` is only implemented by DirectLlmBackend, so
            # retain Codex's native schema transport for this profile.
            structured_output_transport=(
                "provider_schema"
                if self.config.structured_output_transport == "json_object"
                else self.config.structured_output_transport
            ),
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
            maximum_sandbox=(SandboxMode.WORKSPACE_WRITE if write else SandboxMode.READ_ONLY),
            intrinsic_builtin_tools=("shell", "workspace_edit") if write else ("shell",),
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


__all__ = ["IsolatedAgentProfileProvider"]

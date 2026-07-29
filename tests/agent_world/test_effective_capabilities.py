from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import HttpUrl

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.builder import BuilderError
from agent_world.cli import _job_permissions
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import PermissionScope
from agent_world.controller import FoundryController
from agent_world.designer import DesignerError
from agent_world.invocation import (
    CapabilityResolutionError,
    ExternalCapabilitySet,
    NodeCapabilityRequirement,
    RoleCapabilityMaximum,
    SandboxMode,
    compile_effective_capability_plan,
)
from agent_world.judge import VerifierCompilationError
from agent_world.research import ResearchAccessPolicy


def _engineer_maximum() -> RoleCapabilityMaximum:
    return RoleCapabilityMaximum(
        role="environment-engineer",
        policy_version="1",
        maximum_sandbox=SandboxMode.WORKSPACE_WRITE,
        intrinsic_builtin_tools=("shell", "workspace_edit"),
        external=ExternalCapabilitySet(
            network_domains=("files.pythonhosted.org", "pypi.org"),
        ),
    )


def _provider() -> IsolatedAgentProfileProvider:
    return IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )


def test_resolved_profile_clamps_timeout_to_node_budget(tmp_path: Path) -> None:
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            direct_stream_idle_timeout_seconds=321,
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )
    profile = provider.resolve(
        role="challenger",
        lineage_id="timeout-clamp",
        workspace=tmp_path / "challenger",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="challenger.verifier-compile",
            role="challenger",
        ),
        rollout_token_limit=65_536,
        invocation_timeout_seconds=900,
    )

    assert profile.limits.timeout_seconds == 900
    assert profile.limits.direct_stream_idle_timeout_seconds == 321
    assert profile.limits.max_events == 65_536
    assert profile.allowed_builtin_tools == ()


def test_environment_engineer_timeout_uses_explicit_operation_budget(
    tmp_path: Path,
) -> None:
    """Structured design must not inherit the unrelated Builder codegen cap."""

    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            invocation_timeout_seconds=2_700,
            structured_invocation_timeout_seconds=900,
            environment_codegen_invocation_timeout_seconds=120,
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )
    structured = provider.resolve(
        role="environment-engineer",
        lineage_id="task-curriculum-structured-timeout",
        workspace=tmp_path / "task-curriculum",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="environment-engineer.task-curriculum",
            role="environment-engineer",
        ),
        invocation_timeout_seconds=900,
    )
    codegen = provider.resolve(
        role="environment-engineer",
        lineage_id="runtime-build-codegen-timeout",
        workspace=tmp_path / "runtime-build",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.isolated_build(
            node_id="environment-engineer.runtime-build"
        ),
        invocation_timeout_seconds=120,
    )

    assert structured.limits.timeout_seconds == 900
    assert codegen.limits.timeout_seconds == 120


def test_structured_environment_engineer_event_budget_tracks_token_budget(
    tmp_path: Path,
) -> None:
    profile = _provider().resolve(
        role="environment-engineer",
        lineage_id="engineer-event-budget",
        workspace=tmp_path / "environment-engineer",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="environment-engineer.event-budget",
            role="environment-engineer",
        ),
        rollout_token_limit=65_536,
    )

    assert profile.limits.max_events == 65_536


def test_exact_node_requirement_discards_broader_external_job_grants() -> None:
    requirement = NodeCapabilityRequirement.isolated_build(
        node_id="environment-engineer.runtime-build"
    )

    plan = compile_effective_capability_plan(
        role_maximum=_engineer_maximum(),
        job_permission=PermissionScope(
            network_domains=("pypi.org",),
            tool_allowlist=("some.unused.external-tool",),
        ),
        requirement=requirement,
    )

    assert plan.sandbox is SandboxMode.WORKSPACE_WRITE
    assert plan.intrinsic_builtin_tools == ("shell", "workspace_edit")
    assert plan.external.network_domains == ()
    assert plan.external.tool_allowlist == ()
    assert len(plan.plan_hash) == 64


def test_required_external_domain_needs_both_role_ceiling_and_job_permission() -> None:
    requirement = NodeCapabilityRequirement(
        node_id="environment-engineer.dependency-inspection",
        role="environment-engineer",
        sandbox=SandboxMode.READ_ONLY,
        intrinsic_builtin_tools=("shell",),
        external=ExternalCapabilitySet(network_domains=("pypi.org",)),
    )

    with pytest.raises(
        CapabilityResolutionError,
        match="job_permission.external.network_domains",
    ):
        compile_effective_capability_plan(
            role_maximum=_engineer_maximum(),
            job_permission=PermissionScope(),
            requirement=requirement,
        )

    plan = compile_effective_capability_plan(
        role_maximum=_engineer_maximum(),
        job_permission=PermissionScope(network_domains=("pypi.org",)),
        requirement=requirement,
    )
    assert plan.external.network_domains == ("pypi.org",)


def test_job_cannot_grant_an_external_tool_absent_from_role_maximum() -> None:
    requirement = NodeCapabilityRequirement(
        node_id="environment-engineer.external-tool",
        role="environment-engineer",
        sandbox=SandboxMode.READ_ONLY,
        intrinsic_builtin_tools=("shell",),
        external=ExternalCapabilitySet(tool_allowlist=("mcp.package-inspect",)),
    )

    with pytest.raises(
        CapabilityResolutionError,
        match="role_maximum.external.tool_allowlist",
    ):
        compile_effective_capability_plan(
            role_maximum=_engineer_maximum(),
            job_permission=PermissionScope(tool_allowlist=("mcp.package-inspect",)),
            requirement=requirement,
        )


def test_engineer_profile_keeps_intrinsic_build_tools_but_gets_no_implicit_network(
    tmp_path: Path,
) -> None:
    profile = _provider().resolve(
        role="environment-engineer",
        lineage_id="capability-plan-no-implicit-network",
        workspace=tmp_path / "engineer",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.isolated_build(
            node_id="environment-engineer.runtime-build"
        ),
    )

    assert profile.sandbox is SandboxMode.WORKSPACE_WRITE
    assert profile.allowed_builtin_tools == ("shell", "workspace_edit")
    assert profile.allowed_network_domains == ()
    assert profile.effective_capability_plan.external.network_domains == ()
    assert set(profile.to_public_dict()) >= {"effective_capability_plan", "profile_hash"}
    # Runtime tools are not enumerated in generated configuration at all.  The
    # framework models only the sandbox primitives that decide whether an Agent
    # can change something; which tools the Codex runtime offers is its own
    # decision, and a second copy of it here could only disagree.
    assert "web_search" not in (profile.codex_home / "config.toml").read_text()


def test_engineer_runtime_skills_are_selected_by_exact_build_node(tmp_path: Path) -> None:
    """Planning stays read-only while CandidateBuild receives only codegen guidance."""

    provider = _provider()
    planning = provider.resolve(
        role="environment-engineer",
        lineage_id="implementation-plan-skill",
        workspace=tmp_path / "planning",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_read(
            node_id="environment-engineer.implementation-plan",
            role="environment-engineer",
        ),
    )
    codegen = provider.resolve(
        role="environment-engineer",
        lineage_id="candidate-build-skill",
        workspace=tmp_path / "codegen",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.isolated_build(
            node_id="environment-engineer.runtime-build"
        ),
    )

    assert planning.sandbox is SandboxMode.READ_ONLY
    assert planning.allowed_builtin_tools == ("shell",)
    assert tuple(bundle.name for bundle in planning.skills) == ("engineer-build-planning",)
    assert codegen.sandbox is SandboxMode.WORKSPACE_WRITE
    assert codegen.allowed_builtin_tools == ("shell", "workspace_edit")
    assert tuple(bundle.name for bundle in codegen.skills) == ("engineer-environment-codegen",)
    assert codegen.developer_instructions is not None
    assert "Engineer Environment Codegen" in codegen.developer_instructions
    assert "Isolated CandidateBuild working context" in codegen.developer_instructions
    assert "Use relative paths such as `inputs/...` and `candidate/...`" in (
        codegen.developer_instructions
    )
    assert "./.agent-world-tools/uv" in codegen.developer_instructions
    assert "./.agent-world-tools/python3.12" in codegen.developer_instructions
    assert "--python ./.agent-world-tools/python3.12" in codegen.developer_instructions
    instructions = " ".join(codegen.developer_instructions.split())
    assert "Component source visibility" in instructions
    assert "A `runtime` source may import only files declared `runtime`" in instructions


def test_profile_provider_binds_typed_framework_lineage_to_stable_safe_identity(
    tmp_path: Path,
) -> None:
    logical_lineage = "generate-job:9672429137878fa1d73e3c71.research-plan"
    profile = _provider().resolve(
        role="researcher",
        lineage_id=logical_lineage,
        workspace=tmp_path / "researcher",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement(
            node_id="researcher.requirement-research",
            role="researcher",
            sandbox=SandboxMode.READ_ONLY,
            intrinsic_builtin_tools=("shell",),
            external=ExternalCapabilitySet(),
        ),
    )

    assert profile.lineage_id == (
        "lineage-" + hashlib.sha256(logical_lineage.encode("utf-8")).hexdigest()
    )


def test_tool_free_structured_profile_injects_role_skill_without_shell(
    tmp_path: Path,
) -> None:
    profile = _provider().resolve(
        role="researcher",
        lineage_id="tool-free-evidence-synthesis",
        workspace=tmp_path / "tool-free-researcher",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="researcher.evidence-synthesis",
            role="researcher",
        ),
    )

    assert profile.allowed_builtin_tools == ()
    assert profile.skills == ()
    assert profile.developer_instructions is not None
    assert "Research World Evidence" in profile.developer_instructions
    assert "Citation catalog ownership" in profile.developer_instructions
    assert "`evidence_catalog_indexes`" in profile.developer_instructions
    # Tool-free is expressed by the resolved profile, asserted above, not by a
    # feature flag in generated configuration.  This profile is routed to the
    # Direct transport, which has no tool surface to disable in the first place.
    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert "[features]" not in config_text


def test_tool_free_challenger_profile_loads_action_input_schema_audit(
    tmp_path: Path,
) -> None:
    profile = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            structured_output_transport="json_envelope",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    ).resolve(
        role="challenger",
        lineage_id="tool-free-challenger-action-schema-audit",
        workspace=tmp_path / "tool-free-challenger",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="challenger.verifier-compile-batch",
            role="challenger",
        ),
    )

    assert profile.allowed_builtin_tools == ()
    assert profile.developer_instructions is not None
    assert "Action-input schema audit" in profile.developer_instructions
    assert "additionalProperties` is `false`" in profile.developer_instructions
    assert "Positive means one `expectations` item" in profile.developer_instructions
    assert "`expected=true`" in profile.developer_instructions
    assert "two-pass internal" in profile.developer_instructions
    assert "coverage audit" in profile.developer_instructions
    assert "positive_only` `error_semantics` row" in profile.developer_instructions
    assert "merely including the tool elsewhere" in profile.developer_instructions
    assert (
        "Input/context documents may have their own schema_version"
        in profile.developer_instructions
    )
    assert "The Challenger context and the requested `VerifierIntent` are different documents" in (
        profile.developer_instructions
    )
    assert 'literal `"v2"`' in profile.developer_instructions


def test_tool_free_engineer_profile_requires_closed_evidence_claim_catalog(
    tmp_path: Path,
) -> None:
    """BC-17/T1 guard: semantic authors may copy, never mint, evidence IDs."""

    profile = _provider().resolve(
        role="environment-engineer",
        lineage_id="tool-free-architecture-claim-binding",
        workspace=tmp_path / "tool-free-engineer",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="environment-engineer.world-architecture",
            role="environment-engineer",
        ),
    )

    assert profile.allowed_builtin_tools == ()
    assert profile.developer_instructions is not None
    assert "Closed evidence-claim binding" in profile.developer_instructions
    assert "closed enum" in profile.developer_instructions
    assert "Never mint, rename, infer, or describe a claim id" in profile.developer_instructions
    assert "Tool-semantics scalar observations" in profile.developer_instructions
    assert "errors.errors[*].observation" in profile.developer_instructions
    assert "one concrete user-visible sentence" in profile.developer_instructions
    assert "Tool-semantics representation audit" in profile.developer_instructions
    assert "`reliability.rollback.guarantees`" in profile.developer_instructions
    assert "never a list or object" in profile.developer_instructions
    assert "`reliability.tool_id`" in profile.developer_instructions
    assert "Tool-semantics Rule clause closure" in profile.developer_instructions
    assert "they **must omit** `ordering`" in profile.developer_instructions
    assert "Lookup keys use one flat, closed variant" in profile.developer_instructions
    assert "a nested `key`, arithmetic as a key" in profile.developer_instructions
    assert "WorldRules semantic ownership" in profile.developer_instructions
    assert "Omit this optional field" in profile.developer_instructions
    assert "WorldRules even if it appears in the output schema" in profile.developer_instructions
    assert "rule:state:<ordinal>" in profile.developer_instructions
    assert "rule:world:<ordinal>" in profile.developer_instructions
    assert "CurriculumPlan semantic ownership" in profile.developer_instructions
    assert "`difficulty_dimensions` is also a closed top-level catalog" in (
        profile.developer_instructions
    )
    assert "`task_dimension_catalog`" in profile.developer_instructions
    assert "do not add, remove, rename," in profile.developer_instructions
    assert "or reorder any id" in profile.developer_instructions
    assert "rule:sampling:<ordinal>" in profile.developer_instructions
    assert "rule:task:<task_type>:<section>:<ordinal>" in profile.developer_instructions
    assert "`terminal_conditions` (non-empty)" in profile.developer_instructions
    assert "Every task has at least one success Rule and at least one terminal Rule" in (
        profile.developer_instructions
    )
    assert "Evaluator Rules never read Runtime-reported `terminated` or `truncated`" in (
        profile.developer_instructions
    )


def test_task_curriculum_agent_view_remains_tool_free_and_deny_by_default(
    tmp_path: Path,
) -> None:
    """TaskCurriculum receives its frozen facts in the prompt, not broad workspace access."""

    profile = _provider().resolve(
        role="environment-engineer",
        lineage_id="tool-free-task-curriculum-view",
        workspace=tmp_path / "task-curriculum",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(
            network_domains=("pypi.org",),
            tool_allowlist=("unused.external-tool",),
        ),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="environment-engineer.task-curriculum",
            role="environment-engineer",
        ),
    )

    assert profile.allowed_builtin_tools == ()
    assert profile.skills == ()
    assert profile.effective_capability_plan.intrinsic_builtin_tools == ()
    assert profile.effective_capability_plan.external == ExternalCapabilitySet()
    assert profile.developer_instructions is not None
    instructions = " ".join(profile.developer_instructions.split())
    assert "TaskRequirement semantic ownership" in instructions
    assert "`coverage_dimensions[*].rule_ids`" in instructions
    assert "`coverage_rule_catalog`" in instructions
    assert "Do not mint an ID or use a task/sampling Rule ID" in instructions


def test_profile_identity_binds_even_unused_job_permission_scope(tmp_path: Path) -> None:
    requirement = NodeCapabilityRequirement.isolated_build(
        node_id="environment-engineer.runtime-build"
    )
    provider = _provider()
    narrow = provider.resolve(
        role="environment-engineer",
        lineage_id="capability-plan-narrow",
        workspace=tmp_path / "narrow",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=requirement,
    )
    broad = provider.resolve(
        role="environment-engineer",
        lineage_id="capability-plan-broad",
        workspace=tmp_path / "broad",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(network_domains=("pypi.org",)),
        requirement=requirement,
    )

    assert narrow.allowed_network_domains == broad.allowed_network_domains == ()
    assert narrow.effective_capability_plan.job_permission_hash != (
        broad.effective_capability_plan.job_permission_hash
    )
    assert narrow.profile_hash != broad.profile_hash


def test_provider_rejects_external_network_before_materializing_workspace(
    tmp_path: Path,
) -> None:
    logical_workspace = tmp_path / "must-not-exist"
    requirement = NodeCapabilityRequirement(
        node_id="environment-engineer.dependency-inspection",
        role="environment-engineer",
        sandbox=SandboxMode.READ_ONLY,
        intrinsic_builtin_tools=("shell",),
        external=ExternalCapabilitySet(network_domains=("pypi.org",)),
    )

    with pytest.raises(CapabilityResolutionError):
        _provider().resolve(
            role="environment-engineer",
            lineage_id="capability-plan-denied",
            workspace=logical_workspace,
            output_schema={"type": "object", "additionalProperties": False},
            permissions=PermissionScope(),
            requirement=requirement,
        )

    assert not logical_workspace.exists()


def test_cli_dependency_grant_preserves_public_research_and_profiles_exact_builder_domains(
    tmp_path: Path,
) -> None:
    agent = AgentBackendConfig(
        model="configured-real-model",
        api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        engineer_dependency_network_domains=("pypi.org",),
    )
    config = FoundryConfig(
        state_root=tmp_path / "state",
        agent=agent,
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )
    permissions = _job_permissions(config)
    access = ResearchAccessPolicy.create(
        request_permissions=permissions,
        run_permissions=permissions,
        allowed_source_kinds=("web",),
    )
    requirement = NodeCapabilityRequirement.isolated_build(
        node_id="environment-engineer.runtime-build",
        external=ExternalCapabilitySet(network_domains=("pypi.org",)),
    )
    profile = IsolatedAgentProfileProvider(
        agent,
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    ).resolve(
        role="environment-engineer",
        lineage_id="capability-plan-explicit-dependency-network",
        workspace=tmp_path / "networked-engineer",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=permissions,
        requirement=requirement,
    )

    assert "*" in permissions.network_domains
    assert all("*" in patterns for patterns in access.source_policy._allowed_domain_sets)
    assert access.source_policy._matches("docs.example.org", "*")
    assert profile.allowed_network_domains == ("pypi.org",)


def test_capability_denials_map_to_needs_human_in_every_agent_branch() -> None:
    designer_status = FoundryController._designer_failure_status(
        DesignerError(
            "agent.permissions",
            "required capability denied",
            requires_permission=True,
        ),
        default_code="design_failed",
    )
    verifier_code, verifier_status = FoundryController._verifier_error(
        VerifierCompilationError(
            "required capability denied",
            permission_denied=True,
        )
    )
    builder_code, builder_status, state = FoundryController._builder_error(
        BuilderError(
            "permissions",
            "required capability denied",
            permission_denied=True,
        )
    )

    assert designer_status == ("needs_human", "agent_permission_required")
    assert (verifier_code, verifier_status) == (
        "verifier_permission_required",
        "needs_human",
    )
    assert (builder_code, builder_status, state) == (
        "builder_permission_required",
        "needs_human",
        None,
    )

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from pydantic import HttpUrl

from agent_world.agent_profiles import AgentProfileProvider
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
    verify_resolved_profile,
)
from agent_world.judge import VerifierCompilationError
from agent_world.research import ResearchAccessPolicy


def _engineer_maximum() -> RoleCapabilityMaximum:
    return RoleCapabilityMaximum(
        role="environment-engineer",
        policy_version="1",
        maximum_sandbox=SandboxMode.FULL_ACCESS,
        intrinsic_builtin_tools=("shell", "workspace_edit"),
        external=ExternalCapabilitySet(
            network_domains=("files.pythonhosted.org", "pypi.org"),
        ),
    )


def _provider() -> AgentProfileProvider:
    return AgentProfileProvider(
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
    provider = AgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            provider_stream_idle_timeout_seconds=321,
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
    assert profile.limits.provider_stream_idle_timeout_seconds == 321
    assert profile.limits.max_events == 65_536
    assert profile.allowed_builtin_tools == ()


def test_environment_engineer_timeout_uses_explicit_operation_budget(
    tmp_path: Path,
) -> None:
    """Structured design must not inherit the unrelated Builder codegen cap."""

    provider = AgentProfileProvider(
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
        requirement=NodeCapabilityRequirement.host_build(
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
    requirement = NodeCapabilityRequirement.host_build(node_id="environment-engineer.runtime-build")

    plan = compile_effective_capability_plan(
        role_maximum=_engineer_maximum(),
        job_permission=PermissionScope(
            network_domains=("pypi.org",),
            tool_allowlist=("some.unused.external-tool",),
        ),
        requirement=requirement,
    )

    assert plan.sandbox is SandboxMode.FULL_ACCESS
    assert plan.intrinsic_builtin_tools == ("shell", "workspace_edit")
    assert plan.external.network_domains == ()
    assert plan.external.tool_allowlist == ()
    assert len(plan.plan_hash) == 64


def test_required_external_domain_needs_both_role_ceiling_and_job_permission() -> None:
    requirement = NodeCapabilityRequirement(
        node_id="environment-engineer.dependency-inspection",
        role="environment-engineer",
        sandbox=SandboxMode.FULL_ACCESS,
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
        sandbox=SandboxMode.FULL_ACCESS,
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
        requirement=NodeCapabilityRequirement.host_build(
            node_id="environment-engineer.runtime-build"
        ),
    )

    assert profile.sandbox is SandboxMode.FULL_ACCESS
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
    """CandidateBuild mounts one focused Skill with progressive resources."""

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
        requirement=NodeCapabilityRequirement.host_build(
            node_id="environment-engineer.runtime-build"
        ),
    )

    assert planning.sandbox is SandboxMode.FULL_ACCESS
    assert planning.allowed_builtin_tools == ("shell",)
    assert tuple(bundle.name for bundle in planning.skills) == ("engineer-build-planning",)
    assert not hasattr(planning, "base_instructions")
    assert not hasattr(planning, "developer_instructions")
    assert codegen.sandbox is SandboxMode.FULL_ACCESS
    assert codegen.allowed_builtin_tools == ("shell", "workspace_edit")
    assert tuple(bundle.name for bundle in codegen.skills) == ("engineer-environment-codegen",)
    assert not hasattr(codegen, "base_instructions")
    assert not hasattr(codegen, "developer_instructions")
    codegen_skill = (codegen.skills[0].path / "SKILL.md").read_text(encoding="utf-8")
    normalized_codegen_skill = " ".join(codegen_skill.split())
    assert "Engineer Environment Codegen" in codegen_skill
    assert "Work in the supplied workspace" in codegen_skill
    assert "`inputs/...` contains immutable framework inputs" in codegen_skill
    assert "`candidate/...` is the only project you may create or edit" in codegen_skill
    assert "normal host `uv` and Python" in codegen_skill
    assert "direct host workspace" in codegen_skill
    assert "do not depend on a parent checkout" in normalized_codegen_skill
    assert ".agent-world-tools" not in codegen_skill
    assert "AGENT_WORLD_PYTHON_RUNTIME" not in codegen_skill
    assert "`sys.executable`" in codegen_skill
    assert "Load detail progressively" in codegen_skill
    runtime_reference = (
        codegen.skills[0].path / "references" / "runtime-and-materializer.md"
    ).read_text(encoding="utf-8")
    assert "Component visibility" in runtime_reference
    assert "A `runtime` source may import only files declared `runtime`" in runtime_reference
    delivery_reference = (
        codegen.skills[0].path / "references" / "python-project-delivery.md"
    ).read_text(encoding="utf-8")
    assert '`license-files = ["LICENSE"]` is only a' in delivery_reference
    assert "--project candidate" in delivery_reference
    assert "`pip freeze`" in delivery_reference
    preflight = codegen.skills[0].path / "scripts" / "check_candidate_tree.py"
    assert preflight.is_file()
    assert "Deterministic preflight" in preflight.read_text(encoding="utf-8")
    contract_map = codegen.skills[0].path / "scripts" / "candidate_contract_map.py"
    assert contract_map.is_file()
    assert "frozen CandidateBuild acceptance map" in contract_map.read_text(encoding="utf-8")
    materializer_campaign = codegen.skills[0].path / "scripts" / "check_materializer_campaign.py"
    assert materializer_campaign.is_file()
    assert "Candidate-owned" in materializer_campaign.read_text(encoding="utf-8")
    runtime_handshake = codegen.skills[0].path / "scripts" / "check_runtime_handshake_contract.py"
    assert runtime_handshake.is_file()
    assert "frozen WorldSpec surface" in runtime_handshake.read_text(encoding="utf-8")
    public_tests = codegen.skills[0].path / "scripts" / "check_public_tests.py"
    assert public_tests.is_file()
    assert "clean frozen offline project copy" in public_tests.read_text(encoding="utf-8")


def test_direct_profiles_have_no_skill_and_agent_profiles_mount_one_skill(
    tmp_path: Path,
) -> None:
    """Direct routes stay prompt-only while Agent routes own their one Skill."""

    provider = AgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )
    direct = provider.resolve(
        role="environment-engineer",
        lineage_id="direct-native-schema",
        workspace=tmp_path / "direct",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="environment-engineer.tool-semantics-batch",
            role="environment-engineer",
        ),
    )
    agent = provider.resolve(
        role="environment-engineer",
        lineage_id="agent-native-schema",
        workspace=tmp_path / "agent",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.host_build(
            node_id="invocation-audit.engineer-workspace-write"
        ),
    )

    assert direct.skills == ()
    assert tuple(bundle.name for bundle in agent.skills) == ("engineer-agent-world",)


@pytest.mark.parametrize(
    ("role", "node_id", "skill_name"),
    (
        ("researcher", "researcher.evidence-acquisition", "research-world-evidence"),
        ("environment-engineer", "environment-engineer.workspace-review", "engineer-agent-world"),
        ("challenger", "challenger.public-review", "challenge-agent-world"),
    ),
)
def test_other_tool_enabled_agents_mount_one_role_skill(
    tmp_path: Path,
    role: str,
    node_id: str,
    skill_name: str,
) -> None:
    """A tool-enabled Codex turn has one matching Skill, not hidden role prose."""

    profile = _provider().resolve(
        role=role,
        lineage_id=f"agent-skill-{node_id}",
        workspace=tmp_path / node_id.replace(".", "-"),
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_read(node_id=node_id, role=role),
    )

    assert profile.allowed_builtin_tools == ("shell",)
    assert tuple(bundle.name for bundle in profile.skills) == (skill_name,)
    assert not hasattr(profile, "base_instructions")
    assert not hasattr(profile, "developer_instructions")


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
            sandbox=SandboxMode.FULL_ACCESS,
            intrinsic_builtin_tools=("shell",),
            external=ExternalCapabilitySet(),
        ),
    )

    assert profile.lineage_id == (
        "lineage-" + hashlib.sha256(logical_lineage.encode("utf-8")).hexdigest()
    )


@pytest.mark.parametrize(
    ("role", "node_id"),
    (
        ("researcher", "researcher.research-plan"),
        ("researcher", "researcher.evidence-synthesis"),
        ("environment-engineer", "environment-engineer.world-architecture"),
        ("environment-engineer", "environment-engineer.shared-tool-semantics"),
        ("environment-engineer", "environment-engineer.tool-semantics-batch"),
        ("environment-engineer", "environment-engineer.world-rules"),
        ("environment-engineer", "environment-engineer.curriculum-plan"),
        ("environment-engineer", "environment-engineer.task-requirement"),
        ("environment-engineer", "environment-engineer.task-curriculum"),
        ("environment-engineer", "environment-engineer.semantic-revision"),
        ("challenger", "challenger.verifier-compile-batch"),
    ),
)
def test_direct_structured_profiles_have_only_model_and_rendered_prompt(
    tmp_path: Path,
    role: str,
    node_id: str,
) -> None:
    """A Direct LLM must never inherit a role Skill or hidden semantic prompt."""

    provider = _provider()
    profile = provider.resolve(
        role=role,
        lineage_id=f"direct-prompt-only-{node_id}",
        workspace=tmp_path / node_id.replace(".", "-"),
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(
            network_domains=("pypi.org",),
            tool_allowlist=("unused.external-tool",),
        ),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id=node_id,
            role=role,
        ),
    )

    assert profile.allowed_builtin_tools == ()
    assert profile.skills == ()
    assert not hasattr(profile, "hooks")
    assert not hasattr(profile, "base_instructions")
    assert not hasattr(profile, "developer_instructions")
    assert profile.effective_capability_plan.intrinsic_builtin_tools == ()
    assert profile.effective_capability_plan.external == ExternalCapabilitySet()
    assert profile.backend == "direct_llm"
    assert profile.codex_bin is None
    assert provider.codex_bin is None
    assert not profile.home.exists()
    assert not profile.codex_home.exists()
    assert list(profile.workspace.iterdir()) == []
    assert "HOME" not in profile.worker_environment()
    assert "CODEX_HOME" not in profile.worker_environment()
    assert profile.to_public_dict()["home"] is None
    assert profile.to_public_dict()["codex_home"] is None
    verify_resolved_profile(profile)


def test_runtime_skills_have_no_secondary_default_prompt_surface() -> None:
    """A mounted runtime Skill is one SKILL.md, never a sidecar default Prompt."""

    assets_root = Path("agent_world/agent_assets/skills")
    for skill_file in sorted(assets_root.glob("*/SKILL.md")):
        skill_root = skill_file.parent
        assert (skill_root / "SKILL.md").is_file()
        agent_metadata = skill_root / "agents"
        assert not agent_metadata.exists() or not tuple(agent_metadata.iterdir())


def test_profile_identity_binds_even_unused_job_permission_scope(tmp_path: Path) -> None:
    requirement = NodeCapabilityRequirement.host_build(node_id="environment-engineer.runtime-build")
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
        sandbox=SandboxMode.FULL_ACCESS,
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
    requirement = NodeCapabilityRequirement.host_build(
        node_id="environment-engineer.runtime-build",
        external=ExternalCapabilitySet(network_domains=("pypi.org",)),
    )
    profile = AgentProfileProvider(
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

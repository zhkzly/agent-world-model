from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from agent_world.invocation import (
    AgentProfileSpec,
    CodexLoginBinding,
    CredentialBinding,
    CredentialResolutionError,
    EffectiveCapabilityPlan,
    ExternalCapabilitySet,
    ProfileResolutionError,
    ProfileResolver,
    SandboxMode,
    SkillBundleSpec,
    verify_resolved_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_SKILL = (
    PROJECT_ROOT / "agent_world" / "agent_assets" / "skills" / "research-world-evidence"
)


def _authorized_login(path: Path) -> bytes:
    content = json.dumps(
        {
            "auth_contract": "profile-materialization-only",
            "tokens": {"access_token": "contract-value-never-sent"},
        },
        sort_keys=True,
    ).encode()
    path.write_bytes(content)
    path.chmod(0o600)
    return content


def _profile_spec() -> AgentProfileSpec:
    capabilities = EffectiveCapabilityPlan(
        schema_version="agent-world.effective-capability-plan.v1",
        node_id="researcher.test-resolution",
        role="researcher",
        sandbox=SandboxMode.READ_ONLY,
        intrinsic_builtin_tools=("shell",),
        external=ExternalCapabilitySet(),
        role_maximum_hash="1" * 64,
        job_permission_hash="2" * 64,
        node_requirement_hash="3" * 64,
    )
    return AgentProfileSpec(
        profile_id="researcher",
        profile_version="2",
        model="gpt-5.4",
        base_instructions="Use only framework-provided evidence and return typed output.",
        authentication_handle="model-auth",
        effective_capability_plan=capabilities,
        sandbox=SandboxMode.READ_ONLY,
        allowed_builtin_tools=("shell",),
        skills=(
            SkillBundleSpec(
                name="research-world-evidence",
                source=RESEARCH_SKILL,
            ),
        ),
        credential_handles=("model-auth",),
        output_schema={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
            "additionalProperties": False,
        },
        rollout_token_limit=12_345,
    )


def test_profile_resolver_materializes_private_capabilities_without_ambient_inheritance(
    tmp_path: Path,
) -> None:
    login_path = tmp_path / "authorized-login.json"
    login_bytes = _authorized_login(login_path)
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CodexLoginBinding(handle="model-auth", source=login_path.resolve())
        },
        allowed_credential_handles=("model-auth",),
    )
    root = tmp_path / "researcher-runtime"
    workspace = root / "workspace"

    profile = resolver.resolve(
        _profile_spec(),
        lineage_id="research-lineage-1",
        materialization_root=root,
        workspace=workspace,
        source_environment={
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "UNDECLARED_SECRET": "must-not-cross-the-profile-boundary",
        },
    )

    assert profile.authentication_kind == "chatgpt"
    assert profile.workspace == workspace.resolve()
    assert profile.home != Path.home()
    assert profile.codex_home != Path.home() / ".codex"
    assert profile.skills[0].path.is_relative_to(
        profile.materialization_root / "bundles" / "skills"
    )
    assert profile.skills[0].path != RESEARCH_SKILL
    assert profile.hooks == ()
    assert profile.allowed_network_domains == ()
    assert "UNDECLARED_SECRET" not in profile.worker_environment()
    assert profile.secret_values == ()

    copied_login = profile.codex_home / "auth.json"
    assert copied_login.read_bytes() == login_bytes
    if os.name != "nt":
        assert copied_login.stat().st_mode & 0o077 == 0
        assert profile.home.stat().st_mode & 0o077 == 0
        assert profile.codex_home.stat().st_mode & 0o077 == 0
        assert profile.workspace.stat().st_mode & 0o077 == 0

    public_profile = json.dumps(profile.to_public_dict(), sort_keys=True)
    config_text = (profile.codex_home / "config.toml").read_text()
    assert "contract-value-never-sent" not in public_profile
    assert str(login_path) not in public_profile
    assert "contract-value-never-sent" not in config_text
    assert 'web_search = "disabled"' in config_text
    assert 'inherit = "none"' in config_text
    assert f'"{profile.codex_home}" = "deny"' in config_text
    assert f'"{profile.skills[0].path}" = "read"' in config_text
    assert "rollout_budget.enabled = true" in config_text
    assert "rollout_budget.limit_tokens = 12345" in config_text
    assert "tool_output_token_limit = 2048" in config_text
    assert profile.rollout_token_limit == 12_345
    assert profile.tool_output_token_limit == 2_048
    verify_resolved_profile(profile)

    config_path = profile.codex_home / "config.toml"
    config_path.write_text(config_text + "# changed after resolution\n")
    with pytest.raises(ProfileResolutionError, match="Codex config was modified"):
        verify_resolved_profile(profile)


def test_profile_resolver_mounts_only_the_pinned_custom_codex_runtime(
    tmp_path: Path,
) -> None:
    login_path = tmp_path / "authorized-login.json"
    _authorized_login(login_path)
    codex_bin = tmp_path / "codex-runtime" / "codex"
    codex_bin.parent.mkdir()
    codex_bin.write_bytes(b"pinned custom codex runtime")
    codex_bin.chmod(0o700)
    codex_digest = hashlib.sha256(codex_bin.read_bytes()).hexdigest()
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CodexLoginBinding(handle="model-auth", source=login_path.resolve())
        },
        allowed_credential_handles=("model-auth",),
    )
    spec = replace(
        _profile_spec(),
        codex_bin=codex_bin.resolve(),
        codex_bin_sha256=codex_digest,
    )

    profile = resolver.resolve(
        spec,
        lineage_id="research-custom-runtime",
        materialization_root=tmp_path / "research-custom-runtime",
        source_environment={"PATH": "/usr/bin:/bin"},
    )

    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert f'"{codex_bin.resolve()}" = "read"' in config_text
    assert f'"{codex_bin.parent.resolve()}" = "read"' not in config_text
    verify_resolved_profile(profile)


def test_profile_resolver_materializes_explicit_openai_compatible_base_url(
    tmp_path: Path,
) -> None:
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="COMPATIBLE_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        },
        allowed_credential_handles=("model-auth",),
    )
    spec = replace(
        _profile_spec(),
        openai_base_url="https://provider.example.test/v1",
    )

    profile = resolver.resolve(
        spec,
        lineage_id="research-compatible-provider",
        materialization_root=tmp_path / "research-compatible-provider",
        source_environment={
            "PATH": "/usr/bin:/bin",
            "COMPATIBLE_API_KEY": "redacted-test-key",
        },
    )

    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert 'openai_base_url = "https://provider.example.test/v1"' in config_text
    assert profile.openai_base_url == "https://provider.example.test/v1"
    assert profile.worker_environment()["OPENAI_API_KEY"] == "redacted-test-key"
    assert "redacted-test-key" not in config_text
    assert "redacted-test-key" not in json.dumps(profile.to_public_dict(), sort_keys=True)
    verify_resolved_profile(profile)


def test_profile_resolver_rejects_login_files_with_broad_permissions(tmp_path: Path) -> None:
    login_path = tmp_path / "broad-login.json"
    _authorized_login(login_path)
    if os.name == "nt":
        pytest.skip("POSIX file-mode enforcement is not available on Windows")
    login_path.chmod(0o644)
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CodexLoginBinding(handle="model-auth", source=login_path.resolve())
        },
        allowed_credential_handles=("model-auth",),
    )

    with pytest.raises(CredentialResolutionError, match="permissions are too broad"):
        resolver.resolve(
            _profile_spec(),
            lineage_id="research-lineage-2",
            materialization_root=tmp_path / "runtime",
            source_environment={"PATH": "/usr/bin:/bin"},
        )


def test_profile_resolver_rejects_undeclared_agent_control_paths(tmp_path: Path) -> None:
    login_path = tmp_path / "authorized-login.json"
    _authorized_login(login_path)
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "AGENTS.md").write_text("ambient instructions")
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CodexLoginBinding(handle="model-auth", source=login_path.resolve())
        },
        allowed_credential_handles=("model-auth",),
    )

    with pytest.raises(ProfileResolutionError, match="undeclared Agent control path"):
        resolver.resolve(
            _profile_spec(),
            lineage_id="research-lineage-3",
            materialization_root=root,
            source_environment={"PATH": "/usr/bin:/bin"},
        )

from __future__ import annotations

import hashlib
import json
import os
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest

from agent_world.invocation import (
    AgentProfileSpec,
    CodexLoginBinding,
    CredentialBinding,
    EffectiveCapabilityPlan,
    ExternalCapabilitySet,
    ProfileResolutionError,
    ProfileResolver,
    SandboxMode,
    SkillBundleSpec,
    verify_resolved_profile,
)
from agent_world.invocation.profiles import API_KEY_RUNTIME_PROVIDER

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESEARCH_SKILL = (
    PROJECT_ROOT / "agent_world" / "agent_assets" / "skills" / "research-world-evidence"
)


def _profile_spec() -> AgentProfileSpec:
    capabilities = EffectiveCapabilityPlan(
        schema_version="agent-world.effective-capability-plan.v1",
        node_id="researcher.test-resolution",
        role="researcher",
        sandbox=SandboxMode.FULL_ACCESS,
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
        model_provider=API_KEY_RUNTIME_PROVIDER,
        openai_base_url_environment="OPENAI_BASE_URL",
        authentication_handle="model-auth",
        effective_capability_plan=capabilities,
        sandbox=SandboxMode.FULL_ACCESS,
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
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
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
            "MODEL_API_KEY": "contract-key-never-sent",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
            "UNDECLARED_SECRET": "must-not-cross-the-profile-boundary",
        },
    )

    assert profile.authentication_kind == "api_key"
    assert profile.workspace == workspace.resolve()
    assert profile.home != Path.home()
    assert profile.codex_home != Path.home() / ".codex"
    assert profile.skills[0].path == (profile.codex_home / "skills" / "research-world-evidence")
    assert profile.skills[0].path != RESEARCH_SKILL
    assert not hasattr(profile, "hooks")
    assert profile.allowed_network_domains == ()
    assert "UNDECLARED_SECRET" not in profile.worker_environment()
    assert profile.secret_values == (
        "contract-key-never-sent",
        "https://provider.example.test/v1",
    )
    assert not (profile.codex_home / "auth.json").exists()
    if os.name != "nt":
        assert profile.home.stat().st_mode & 0o077 == 0
        assert profile.codex_home.stat().st_mode & 0o077 == 0
        assert profile.workspace.stat().st_mode & 0o077 == 0

    public_profile = json.dumps(profile.to_public_dict(), sort_keys=True)
    config_text = (profile.codex_home / "config.toml").read_text()
    parsed_config = tomllib.loads(config_text)
    assert "contract-key-never-sent" not in public_profile
    assert "https://provider.example.test/v1" not in public_profile
    assert "contract-key-never-sent" not in config_text
    assert "https://provider.example.test/v1" not in config_text
    # Generated configuration is deliberately minimal.  It asserts only the
    # overrides the framework's own guarantees depend on -- no interactive
    # approval, credentials never on disk, a shell that cannot inherit the
    # provider key, the workspace as its own project root, and no ambient
    # plugin discovery/synchronization.  The explicit Runtime Skill remains
    # discoverable from this private CODEX_HOME's local ``skills/`` root; it is
    # not a marketplace plugin or an arbitrary external config path.  Codex
    # itself owns the full-access tool configuration, so this generated profile
    # must not recreate a second permission or virtual-toolchain policy.
    assert 'cli_auth_credentials_store = "keyring"' in config_text
    assert "sqlite_home =" not in config_text
    assert "log_dir =" not in config_text
    assert "[permissions" not in config_text
    assert str(profile.skills[0].path) not in config_text
    assert 'inherit = "none"' in config_text
    assert "[features]" in config_text
    assert "plugins = false" in config_text
    assert "[[skills.config]]" not in config_text
    assert "web_search" not in config_text
    assert f'"{profile.workspace}"' in config_text
    assert parsed_config["projects"][str(profile.workspace)]["trust_level"] == "untrusted"
    assert "rollout_budget.enabled = true" in config_text
    assert "rollout_budget.limit_tokens = 12345" in config_text
    assert profile.rollout_token_limit == 12_345
    assert profile.tool_output_token_limit == 2_048
    verify_resolved_profile(profile)

    auth_path = profile.codex_home / "auth.json"
    auth_path.write_text("forbidden-runtime-cache", encoding="utf-8")
    with pytest.raises(
        ProfileResolutionError,
        match="file-backed Codex authentication is forbidden",
    ):
        verify_resolved_profile(profile)
    auth_path.unlink()

    config_path = profile.codex_home / "config.toml"
    config_path.write_text(config_text + "# changed after resolution\n")
    with pytest.raises(ProfileResolutionError, match="Codex config was modified"):
        verify_resolved_profile(profile)


def test_profile_hash_is_stable_while_codex_config_hash_tracks_workspace(
    tmp_path: Path,
) -> None:
    """Fresh Agent workspaces keep semantic profile identity, not config bytes.

    The generated config correctly contains each workspace's sandbox/project
    paths. A workspace-recovery turn must compare the profile closure rather
    than requiring a fresh child workspace to reproduce those source-path
    bytes.
    """

    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        },
        allowed_credential_handles=("model-auth",),
    )
    environment = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "MODEL_API_KEY": "contract-key-never-sent",
        "OPENAI_BASE_URL": "https://provider.example.test/v1",
    }
    source = resolver.resolve(
        _profile_spec(),
        lineage_id="workspace-recovery-lineage",
        materialization_root=tmp_path / "source-profile",
        source_environment=environment,
    )
    fresh = resolver.resolve(
        _profile_spec(),
        lineage_id="workspace-recovery-lineage",
        materialization_root=tmp_path / "fresh-profile",
        source_environment=environment,
    )

    assert source.profile_hash == fresh.profile_hash
    assert source.codex_config_sha256 != fresh.codex_config_sha256
    assert source.workspace != fresh.workspace


def test_profile_resolver_pins_the_custom_codex_runtime_outside_generated_config(
    tmp_path: Path,
) -> None:
    codex_bin = tmp_path / "codex-runtime" / "codex"
    codex_bin.parent.mkdir()
    codex_bin.write_bytes(b"pinned custom codex runtime")
    codex_bin.chmod(0o700)
    codex_digest = hashlib.sha256(codex_bin.read_bytes()).hexdigest()
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
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
        source_environment={
            "PATH": "/usr/bin:/bin",
            "MODEL_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    # The profile pins the SDK executable for the trusted worker.  Codex config
    # does not need an extra virtual mount or path declaration for it.
    assert profile.codex_bin == codex_bin.resolve()
    assert profile.codex_bin.parent == codex_bin.parent.resolve()
    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert str(codex_bin.resolve()) not in config_text
    assert "[permissions" not in config_text
    verify_resolved_profile(profile)


def test_profile_resolver_uses_codex_full_access_without_a_duplicate_permission_config(
    tmp_path: Path,
) -> None:
    base = _profile_spec()
    capabilities = replace(
        base.effective_capability_plan,
        node_id="environment-engineer.test-resolution",
        role="environment-engineer",
        sandbox=SandboxMode.FULL_ACCESS,
        intrinsic_builtin_tools=("shell", "workspace_edit"),
    )
    spec = replace(
        base,
        profile_id="environment-engineer",
        profile_version="3",
        effective_capability_plan=capabilities,
        sandbox=SandboxMode.FULL_ACCESS,
        allowed_builtin_tools=("shell", "workspace_edit"),
        skills=(),
    )
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        },
        allowed_credential_handles=("model-auth",),
    )

    profile = resolver.resolve(
        spec,
        lineage_id="environment-engineer-write",
        materialization_root=tmp_path / "environment-engineer-write",
        source_environment={
            "PATH": "/usr/bin:/bin",
            "MODEL_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert 'approval_policy = "never"' in config_text
    assert "[permissions" not in config_text
    assert "web_search" not in config_text
    verify_resolved_profile(profile)


def test_profile_resolver_preserves_normal_host_path_without_a_tool_facade(
    tmp_path: Path,
) -> None:
    host_bin = tmp_path / "host-bin"
    host_bin.mkdir()
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        },
        allowed_credential_handles=("model-auth",),
    )

    profile = resolver.resolve(
        _profile_spec(),
        lineage_id="research-normal-host-path",
        materialization_root=tmp_path / "research-normal-host-path",
        source_environment={
            "PATH": f"{host_bin}:/usr/bin:/bin",
            "MODEL_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    worker_environment = profile.worker_environment()
    assert worker_environment["PATH"] == f"{host_bin}:/usr/bin:/bin"
    assert "AGENT_WORLD_PYTHON_RUNTIME" not in worker_environment
    assert not (profile.workspace / ".agent-world-tools").exists()
    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert f'PATH = "{host_bin}:/usr/bin:/bin"' in config_text
    assert "toolchain" not in config_text
    assert "AGENT_WORLD_PYTHON_RUNTIME" not in config_text
    verify_resolved_profile(profile)


def test_profile_resolver_keeps_runtime_base_url_out_of_materialized_files(
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
    profile = resolver.resolve(
        _profile_spec(),
        lineage_id="research-compatible-provider",
        materialization_root=tmp_path / "research-compatible-provider",
        source_environment={
            "PATH": "/usr/bin:/bin",
            "COMPATIBLE_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert "https://provider.example.test/v1" not in config_text
    assert profile.openai_base_url_environment == "OPENAI_BASE_URL"
    assert profile.worker_environment()["OPENAI_API_KEY"] == ("test-placeholder-not-a-real-key")
    assert profile.worker_environment()["OPENAI_BASE_URL"] == "https://provider.example.test/v1"
    assert "test-placeholder-not-a-real-key" not in config_text
    assert "https://provider.example.test/v1" not in json.dumps(
        profile.to_public_dict(), sort_keys=True
    )
    verify_resolved_profile(profile)


def test_profile_resolver_rejects_file_backed_codex_login() -> None:
    with pytest.raises(ValueError, match="file-backed Codex login is forbidden"):
        ProfileResolver(
            credential_bindings={
                "model-auth": CodexLoginBinding(
                    handle="model-auth",
                    source=Path("/nonexistent/auth.json"),
                )
            },
            allowed_credential_handles=("model-auth",),
        )


def test_profile_resolver_rejects_undeclared_agent_control_paths(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir()
    (root / "AGENTS.md").write_text("ambient instructions")
    resolver = ProfileResolver(
        credential_bindings={
            "model-auth": CredentialBinding(
                handle="model-auth",
                source_environment="MODEL_API_KEY",
                target_environment="OPENAI_API_KEY",
                purpose="model_api_key",
            )
        },
        allowed_credential_handles=("model-auth",),
    )

    with pytest.raises(ProfileResolutionError, match="undeclared Agent control path"):
        resolver.resolve(
            _profile_spec(),
            lineage_id="research-lineage-3",
            materialization_root=root,
            source_environment={
                "PATH": "/usr/bin:/bin",
                "MODEL_API_KEY": "test-placeholder-not-a-real-key",
                "OPENAI_BASE_URL": "https://provider.example.test/v1",
            },
        )

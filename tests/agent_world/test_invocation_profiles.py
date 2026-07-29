from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
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
        model_provider=API_KEY_RUNTIME_PROVIDER,
        openai_base_url_environment="OPENAI_BASE_URL",
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
    assert profile.skills[0].path.is_relative_to(
        profile.materialization_root / "bundles" / "skills"
    )
    assert profile.skills[0].path != RESEARCH_SKILL
    assert profile.hooks == ()
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
    assert "contract-key-never-sent" not in public_profile
    assert "https://provider.example.test/v1" not in public_profile
    assert "contract-key-never-sent" not in config_text
    assert "https://provider.example.test/v1" not in config_text
    assert 'cli_auth_credentials_store = "keyring"' in config_text
    assert 'persistence = "none"' in config_text
    assert "shell_snapshot = false" in config_text
    assert "sqlite_home =" not in config_text
    assert "log_dir =" not in config_text
    assert 'web_search = "disabled"' in config_text
    assert 'default_permissions = "agent_world_isolated"' in config_text
    assert 'inherit = "none"' in config_text
    assert f'"{profile.codex_home}" = "deny"' in config_text
    assert f'"{profile.skills[0].path}" = "read"' in config_text
    assert "rollout_budget.enabled = true" in config_text
    assert "rollout_budget.limit_tokens = 12345" in config_text
    assert "tool_output_token_limit = 2048" in config_text
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


def test_profile_resolver_mounts_only_the_pinned_custom_codex_runtime(
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

    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert f'"{codex_bin.resolve()}" = "read"' in config_text
    assert f'"{codex_bin.parent.resolve()}" = "read"' not in config_text
    verify_resolved_profile(profile)


def test_profile_resolver_materializes_a_pinned_isolated_runtime_tool(
    tmp_path: Path,
) -> None:
    host_bin = tmp_path / "host-bin"
    host_bin.mkdir()
    source_uv = host_bin / "uv"
    # The workspace command is a direct content-pinned executable copy, not a
    # wrapper whose interpreter would become an extra runtime dependency.
    source_uv.write_bytes(Path(sys.executable).resolve(strict=True).read_bytes())
    source_uv.chmod(0o500)
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
        replace(_profile_spec(), required_runtime_tools=("uv",)),
        lineage_id="research-runtime-toolchain",
        materialization_root=tmp_path / "research-runtime-toolchain",
        source_environment={
            "PATH": f"{host_bin}:/usr/bin:/bin",
            "MODEL_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    assert profile.missing_runtime_tools == ()
    assert tuple(tool.name for tool in profile.runtime_tools) == ("uv",)
    assert profile.runtime_interpreter is not None
    assert profile.runtime_interpreter.version == "3.12"
    resolved_uv = profile.runtime_tools[0]
    assert resolved_uv.path == profile.materialization_root / "toolchain" / "bin" / "uv"
    assert resolved_uv.path.read_bytes() == source_uv.read_bytes()
    assert profile.worker_environment()["PATH"].split(os.pathsep)[0] == str(
        resolved_uv.path.parent
    )
    config_text = (profile.codex_home / "config.toml").read_text(encoding="utf-8")
    assert str(resolved_uv.path.parent) in config_text
    assert str(source_uv) not in config_text
    public_profile = json.dumps(profile.to_public_dict(), sort_keys=True)
    assert str(source_uv) not in public_profile
    assert {"name": "uv", "sha256": resolved_uv.sha256} in profile.to_public_dict()[
        "runtime_tools"
    ]
    assert profile.runtime_interpreter.to_safe_dict() == profile.to_public_dict()[
        "runtime_interpreter"
    ]
    assert str(profile.runtime_interpreter.executable) not in public_profile
    assert str(profile.runtime_interpreter.root) not in public_profile
    facade_root = profile.workspace / ".agent-world-tools"
    facade_uv = facade_root / "uv"
    facade_python = facade_root / "python3.12"
    assert facade_uv.is_file() and facade_python.is_file()
    assert facade_uv.read_bytes() == resolved_uv.path.read_bytes()
    assert facade_python.read_bytes() == profile.runtime_interpreter.executable.read_bytes()
    assert not facade_uv.read_bytes().startswith(b"#!")
    assert not facade_python.read_bytes().startswith(b"#!")
    assert subprocess.run(  # noqa: S603 -- resolver-created facade is the test subject.
        [str(facade_uv), "--version"],
        cwd=profile.workspace,
        check=False,
    ).returncode == 0
    python_version = subprocess.run(  # noqa: S603 -- resolver-created facade is the test subject.
        [str(facade_python), "--version"],
        cwd=profile.workspace,
        check=True,
        capture_output=True,
        text=True,
    )
    assert python_version.stdout.startswith("Python 3.12.")
    assert f'"{profile.runtime_interpreter.root}" = "read"' in config_text
    assert f'"{Path(sys.prefix).resolve()}" = "read"' not in config_text
    verify_resolved_profile(profile)

    facade_uv.chmod(0o700)
    facade_uv.write_bytes(b"tampered")
    with pytest.raises(ProfileResolutionError, match="workspace runtime tool facade changed"):
        verify_resolved_profile(profile)
    facade_uv.write_bytes(resolved_uv.path.read_bytes())
    facade_uv.chmod(0o500)

    resolved_uv.path.chmod(0o700)
    resolved_uv.path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ProfileResolutionError, match="runtime tool changed"):
        verify_resolved_profile(profile)


def test_profile_resolver_records_a_missing_declared_runtime_tool_without_host_fallback(
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
    missing_name = "agent-world-test-missing-tool"
    profile = resolver.resolve(
        replace(_profile_spec(), required_runtime_tools=(missing_name,)),
        lineage_id="research-missing-runtime-tool",
        materialization_root=tmp_path / "research-missing-runtime-tool",
        source_environment={
            "PATH": str(tmp_path / "empty-bin"),
            "MODEL_API_KEY": "test-placeholder-not-a-real-key",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
        },
    )

    assert profile.runtime_tools == ()
    assert profile.missing_runtime_tools == (missing_name,)
    assert missing_name in profile.to_public_dict()["missing_runtime_tools"]
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
    assert profile.worker_environment()["OPENAI_API_KEY"] == (
        "test-placeholder-not-a-real-key"
    )
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

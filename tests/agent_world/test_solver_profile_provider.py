from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_world.agent_profiles import AgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.invocation import (
    NodeCapabilityRequirement,
    ProfileResolutionError,
    SandboxMode,
    safe_profile_resolution_category,
    verify_resolved_profile,
)
from agent_world.judge.reachability import InteractiveSolveDecision, SolverProfileProvider


def _provider(
    *,
    fallback_models: tuple[str, ...] = (),
) -> AgentProfileProvider:
    return AgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            fallback_models=fallback_models,
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "LANG": "C.UTF-8",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
            "AMBIENT_SECRET": "must-not-cross-solver-boundary",
        },
    )


def _solver_schema() -> dict[str, object]:
    return InteractiveSolveDecision.model_json_schema(mode="validation")


def _requires_solver_provider(provider: SolverProfileProvider) -> None:
    """Static assertion that the application provider satisfies Judge's protocol."""


def test_solver_profile_is_fresh_source_blind_and_capability_empty(tmp_path: Path) -> None:
    framework_workspace = tmp_path / "judge-private"
    framework_workspace.mkdir()
    private_names = {
        "candidate-source.py",
        "sealed-cases.json",
        "evaluator-goal.json",
        "rule-ir.json",
    }
    for name in private_names:
        (framework_workspace / name).write_text("private", encoding="utf-8")
    (framework_workspace / "AGENTS.md").write_text(
        "ambient instructions must not be discovered", encoding="utf-8"
    )
    ambient_codex = framework_workspace / ".codex"
    ambient_codex.mkdir()
    (ambient_codex / "config.toml").write_text('web_search = "live"\n', encoding="utf-8")

    provider = _provider()
    _requires_solver_provider(provider)
    first = provider.resolve_solver(
        lineage_id="judge-run:reachability:inventory-task",
        workspace=framework_workspace,
        output_schema=_solver_schema(),
        rollout_token_limit=4_096,
    )
    second = provider.resolve_solver(
        lineage_id="judge-run:reachability:inventory-task",
        workspace=framework_workspace,
        output_schema=_solver_schema(),
        rollout_token_limit=4_096,
    )

    assert first.profile_id == "challenger"
    # The episode solver is a normal prompt-only Challenger profile, not a
    # special tool-free Codex session profile.
    assert first.profile_version == "12"
    assert first.sandbox is SandboxMode.FULL_ACCESS
    assert first.allowed_builtin_tools == ()
    assert first.allowed_network_domains == ()
    assert first.skills == ()
    assert not hasattr(first, "hooks")
    assert not hasattr(first, "base_instructions")
    assert not hasattr(first, "developer_instructions")
    assert first.effective_capability_plan.node_id == "challenger.reachability-solver"
    assert first.effective_capability_plan.intrinsic_builtin_tools == ()
    assert first.effective_capability_plan.external.to_public_dict() == {
        "filesystem_read_roots": [],
        "filesystem_write_roots": [],
        "network_domains": [],
        "executable_allowlist": [],
        "tool_allowlist": [],
        "credential_handles": [],
        "allow_external_side_effects": False,
    }
    assert [(item.handle, item.purpose) for item in first.credential_descriptors] == [
        ("model-auth", "model_api_key")
    ]
    assert first.output_schema == _solver_schema()
    assert first.rollout_token_limit == 4_096
    assert first.workspace != framework_workspace
    assert first.workspace.is_relative_to(framework_workspace / ".agent-solver-runtimes")
    assert first.home != second.home
    assert first.codex_home != second.codex_home
    assert first.workspace != second.workspace
    assert first.materialization_root != second.materialization_root

    staged_names = {item.name for item in first.workspace.rglob("*")}
    assert private_names.isdisjoint(staged_names)
    assert "AGENTS.md" not in staged_names
    assert ".codex" not in staged_names
    assert list(first.workspace.iterdir()) == []

    worker_environment = first.worker_environment()
    assert "HOME" not in worker_environment
    assert "CODEX_HOME" not in worker_environment
    assert worker_environment["OPENAI_API_KEY"] == "test-model-credential"
    assert "AMBIENT_SECRET" not in worker_environment
    public_profile = json.dumps(first.to_public_dict(), sort_keys=True)
    assert "test-model-credential" not in public_profile
    assert "must-not-cross-solver-boundary" not in public_profile
    assert first.backend == "direct_llm"
    assert first.codex_bin is None
    assert not first.home.exists()
    assert not first.codex_home.exists()
    assert first.to_public_dict()["codex_home"] is None
    assert not (first.workspace / "AGENTS.md").exists()
    assert not (first.workspace / ".codex").exists()
    verify_resolved_profile(first)
    verify_resolved_profile(second)


def test_solver_profile_model_override_is_explicit_and_profile_hashed(tmp_path: Path) -> None:
    provider = _provider(fallback_models=("grok-4.5", "gpt-5.3-codex-spark"))

    primary = provider.resolve_solver(
        lineage_id="judge-run:primary",
        workspace=tmp_path / "primary",
        output_schema=_solver_schema(),
        rollout_token_limit=4_096,
    )
    fallback = provider.resolve_solver(
        lineage_id="judge-run:fallback",
        workspace=tmp_path / "fallback",
        output_schema=_solver_schema(),
        rollout_token_limit=4_096,
        model_override="grok-4.5",
    )

    assert provider.model_routes == (
        "configured-real-model",
        "grok-4.5",
        "gpt-5.3-codex-spark",
    )
    assert primary.model == "configured-real-model"
    assert fallback.model == "grok-4.5"
    assert fallback.profile_hash != primary.profile_hash
    with pytest.raises(ValueError, match="explicitly configured fallback route"):
        provider.resolve_solver(
            lineage_id="judge-run:undeclared",
            workspace=tmp_path / "undeclared",
            output_schema=_solver_schema(),
            rollout_token_limit=4_096,
            model_override="undeclared-model",
        )


@pytest.mark.parametrize("token_limit", [0, -1, True, 1.5])
def test_solver_profile_rejects_invalid_token_caps(
    tmp_path: Path,
    token_limit: object,
) -> None:
    with pytest.raises((TypeError, ValueError), match="rollout_token_limit"):
        _provider().resolve_solver(
            lineage_id="invalid-token-limit",
            workspace=tmp_path / "solver",
            output_schema=_solver_schema(),
            rollout_token_limit=token_limit,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "object"},
        {"type": "object", "additionalProperties": True},
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"payload": {"type": "object"}},
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {"payload": {"$ref": "https://example.invalid/schema.json"}},
        },
    ],
)
def test_solver_profile_rejects_open_or_external_output_schemas(
    tmp_path: Path,
    schema: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="solver output_schema"):
        _provider().resolve_solver(
            lineage_id="invalid-solver-schema",
            workspace=tmp_path / "solver",
            output_schema=schema,
            rollout_token_limit=1_024,
        )


def test_solver_profile_defensively_copies_output_schema(tmp_path: Path) -> None:
    schema = _solver_schema()
    profile = _provider().resolve_solver(
        lineage_id="defensive-schema-copy",
        workspace=tmp_path / "solver",
        output_schema=schema,
        rollout_token_limit=2_048,
    )

    schema.clear()

    assert profile.output_schema == _solver_schema()
    verify_resolved_profile(profile)


def test_solver_and_direct_profile_are_prompt_only(tmp_path: Path) -> None:
    provider = _provider()

    direct = provider.resolve(
        role="challenger",
        lineage_id="direct-prompt-only",
        workspace=tmp_path / "direct",
        output_schema=_solver_schema(),
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="challenger.direct-prompt-only",
            role="challenger",
        ),
        rollout_token_limit=2_048,
    )
    solver = provider.resolve_solver(
        lineage_id="solver-prompt-only",
        workspace=tmp_path / "solver",
        output_schema=_solver_schema(),
        rollout_token_limit=2_048,
    )

    assert direct.backend == "direct_llm"
    assert solver.backend == "direct_llm"
    assert direct.skills == ()
    assert solver.skills == ()


def test_direct_profile_ignores_a_cached_codex_agent_runtime(tmp_path: Path) -> None:
    """A Direct node may follow a real Agent node in one scheduler process."""

    provider = _provider()
    provider.codex_bin = tmp_path / "cached-codex" / "codex"
    provider.codex_bin_sha256 = "a" * 64

    direct = provider.resolve(
        role="challenger",
        lineage_id="direct-after-agent",
        workspace=tmp_path / "direct-after-agent",
        output_schema=_solver_schema(),
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="challenger.direct-after-agent",
            role="challenger",
        ),
        rollout_token_limit=2_048,
    )

    assert direct.backend == "direct_llm"
    assert direct.codex_bin is None
    assert direct.codex_bin_sha256 is None
    verify_resolved_profile(direct)
    assert (
        safe_profile_resolution_category(
            ProfileResolutionError("Direct profile cannot declare a Codex runtime")
        )
        == "direct_inherited_agent_runtime"
    )


def test_single_token_solver_budget_stays_direct_without_a_codex_config(
    tmp_path: Path,
) -> None:
    profile = _provider().resolve_solver(
        lineage_id="single-token-budget",
        workspace=tmp_path / "solver",
        output_schema=_solver_schema(),
        rollout_token_limit=1,
    )

    assert profile.rollout_token_limit == 1
    assert profile.backend == "direct_llm"
    assert not profile.codex_home.exists()
    verify_resolved_profile(profile)

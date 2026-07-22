from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import HttpUrl, ValidationError

from agent_world.config import (
    AgentBackendConfig,
    ExpansionConfig,
    ExpansionSourceConfig,
    FoundryConfig,
    ResearchConfig,
    load_foundry_config,
)
from agent_world.contracts import Budget
from agent_world.designer import (
    DIRECT_DESIGN_BASE_TURNS,
    DIRECT_DESIGN_MAX_CORRECTIONS,
    DIRECT_DESIGN_MAX_TURNS,
)
from agent_world.designer.budget import derive_designer_invocation_budget


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path / "state",
        agent=AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )


def test_production_defaults_reserve_full_v3_judge_capacity(tmp_path: Path) -> None:
    config = _config(tmp_path)
    direct = config.generation_budget
    candidate = config.expansion.candidate_budget
    campaign = config.expansion.campaign_budget

    assert config.agent.structured_turn_token_limit == 65_536

    assert direct.llm_tokens == 10_000_000
    assert candidate.llm_tokens == 1_200_000
    assert direct.agent_turns == candidate.agent_turns == 128
    assert direct.tool_calls == candidate.tool_calls == 512
    assert direct.evaluation_episodes == candidate.evaluation_episodes == 128
    assert direct.container_seconds == candidate.container_seconds == 3_600
    assert direct.wall_seconds == 28_800
    assert candidate.wall_seconds == 7_200
    assert direct.repair_attempts == 15
    direct_designer = derive_designer_invocation_budget(
        direct,
        base_turns=DIRECT_DESIGN_BASE_TURNS,
        maximum_corrections=min(DIRECT_DESIGN_MAX_CORRECTIONS, direct.repair_attempts),
        rollout_token_limit=config.agent.structured_turn_token_limit,
    )
    assert direct_designer.agent_turns == (
        DIRECT_DESIGN_MAX_TURNS
    )
    assert direct_designer.llm_tokens <= direct.llm_tokens

    for dimension in (
        "llm_tokens",
        "agent_turns",
        "search_calls",
        "tool_calls",
        "build_seconds",
        "evaluation_episodes",
        "container_seconds",
        "live_probe_cost",
        "repair_attempts",
        "monetary_cost",
    ):
        assert getattr(campaign, dimension) >= 5 * getattr(candidate, dimension)

    assert tuple(item.kind for item in config.expansion.sources) == (
        "tool_ecosystem",
        "pool_neighborhood",
        "random_theme",
    )
    assert all(item.descriptor().budget.agent_turns >= 2 for item in config.expansion.sources)


def test_openai_base_url_requires_api_key_mode(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="requires API-key authentication"):
        AgentBackendConfig(
            model="gpt-5.4-mini",
            chatgpt_auth_file=tmp_path / "codex-auth.json",
            openai_base_url=HttpUrl("https://provider.example.test/v1"),
        )

    config = AgentBackendConfig(
        model="gpt-5.4-mini",
        api_key_environment="COMPATIBLE_API_KEY",
        openai_base_url=HttpUrl("https://provider.example.test/v1"),
    )
    assert str(config.openai_base_url) == "https://provider.example.test/v1"


def test_expansion_config_reserves_source_intake_and_one_real_candidate() -> None:
    with pytest.raises(ValidationError, match="Source intake plus one real candidate"):
        ExpansionConfig(
            sources=(
                ExpansionSourceConfig(
                    source_id="source:too-large",
                    kind="random_theme",
                    budget=Budget(
                        llm_tokens=100,
                        agent_turns=2,
                        search_calls=3,
                        tool_calls=5,
                        wall_seconds=50,
                    ),
                ),
            ),
            default_source_ids=("source:too-large",),
            campaign_budget=Budget(
                llm_tokens=150,
                agent_turns=3,
                search_calls=3,
                tool_calls=5,
                wall_seconds=100,
            ),
            candidate_budget=Budget(
                llm_tokens=100,
                agent_turns=2,
                search_calls=1,
                tool_calls=2,
                wall_seconds=60,
            ),
        )


def test_toml_release_profile_arrays_are_explicitly_adapted_to_strict_contracts(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                'state_root = "state"',
                "",
                "[agent]",
                'model = "configured-real-model"',
                'api_key_environment = "AGENT_WORLD_TEST_MODEL_KEY"',
                "",
                "[research]",
                'provider = "searxng"',
                'searxng_base_url = "http://127.0.0.1:18080"',
                "searxng_allow_private_endpoint = true",
                "use_jina_reader_fallback = false",
                "",
                "[release_profile]",
                'profile_id = "strict-toml-release"',
                'required_hard_gates = ["schema", "runtime_protocol"]',
                'minimum_coverage_dimensions = ["tool_semantics"]',
            )
        ),
        encoding="utf-8",
    )

    config = load_foundry_config(config_path)

    assert config.release_profile.required_hard_gates == (
        "schema",
        "runtime_protocol",
    )
    assert config.release_profile.minimum_coverage_dimensions == ("tool_semantics",)

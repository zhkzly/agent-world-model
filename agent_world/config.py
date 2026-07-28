"""Non-secret configuration for the Agent World Foundry."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from agent_world.contracts import (
    Budget,
    ExpansionSourceDescriptor,
    ExpansionSourceKind,
    KeyValue,
    ReleaseProfile,
)
from agent_world.invocation.runtime_provider import (
    API_KEY_RUNTIME_PROVIDER,
    OPENAI_BASE_URL_ENVIRONMENT,
)


class ConfigError(RuntimeError):
    pass


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class AgentBackendConfig(ConfigModel):
    model: str = Field(min_length=1)
    model_provider: str | None = None
    # The actual routing value is intentionally never admitted into TOML,
    # resolved-profile metadata, or generated Codex configuration.  The
    # InvocationBackend reads this named environment handle only in its
    # private worker environment and supplies it through an in-memory SDK
    # thread override.  It is never serialized into generated Codex config or
    # passed as a command-line argument.
    openai_base_url_environment: str | None = None
    codex_bin: Path | None = None
    reasoning_researcher: Literal["low", "medium", "high", "xhigh"] = "medium"
    reasoning_engineer: Literal["low", "medium", "high", "xhigh"] = "medium"
    reasoning_challenger: Literal["low", "medium", "high", "xhigh"] = "medium"
    api_key_environment: str
    engineer_network_domain_ceiling: tuple[str, ...] = (
        "pypi.org",
        "files.pythonhosted.org",
    )
    engineer_dependency_network_domains: tuple[str, ...] = ()
    invocation_timeout_seconds: float = Field(default=2_700, gt=0)
    structured_invocation_timeout_seconds: float = Field(default=2_700, gt=0)
    # A Provider stream that has started but stops yielding events is a
    # transport-liveness condition, not an output-token cap.  Direct calls
    # retain their declared logical timeout until the stream has made real
    # progress; set this to ``None`` only when an external supervisor owns
    # that post-progress liveness decision.
    direct_stream_idle_timeout_seconds: float | None = Field(default=300, gt=0)
    # These two values are the logical Environment Builder session envelope.
    # A provider can still stop one SDK turn at its own smaller output ceiling;
    # the WorkGraph turns that ceiling into explicit resumable physical turns.
    environment_codegen_invocation_timeout_seconds: float = Field(default=2_700, gt=0)
    max_concurrent_invocations: int = Field(default=1, ge=1, le=32)
    # ``json_object`` is the Direct, tool-free structured-node transport.  It
    # asks the provider for one JSON object without making the model manually
    # serialize a second JSON document into a string.  Local Pydantic and
    # semantic validation remain the acceptance path.  Agentic Builder turns
    # retain their provider-schema protocol and their resumable logical
    # session envelope.
    structured_output_transport: Literal[
        "provider_schema", "json_envelope", "json_object"
    ] = "provider_schema"
    tool_output_token_limit: int = Field(default=2_048, ge=512, le=32_768)
    # A real isolated structured-node diagnostic can need the same long
    # observation envelope as CandidateBuild.  Keep this finite so leases,
    # recovery, and aggregate budgets remain accountable, but do not silently
    # reintroduce a short one-million-token ceiling below an explicitly
    # authorized five-million-token proof.
    structured_turn_token_limit: int = Field(default=65_536, ge=16_384, le=5_000_000)
    environment_codegen_turn_token_limit: int = Field(
        default=262_144,
        ge=32_768,
        # Logical session ceiling.  This is intentionally not represented as
        # a promise that one Provider response can emit this many tokens.
        le=10_000_000,
    )
    environment_codegen_physical_turn_token_limit: int = Field(
        default=128_000,
        ge=32_768,
        # A diagnostic proof may deliberately use the full logical session as
        # one live Agent turn.  Keep the physical field wide enough to express
        # that real 5M-token observation instead of silently reinstating a
        # smaller test-only ceiling.
        le=10_000_000,
    )

    @model_validator(mode="after")
    def api_key_environment_contract(self) -> AgentBackendConfig:
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_environment) is None:
            raise ValueError("api_key_environment must be an environment-variable name")
        if (
            self.openai_base_url_environment is not None
            and self.openai_base_url_environment != OPENAI_BASE_URL_ENVIRONMENT
        ):
            raise ValueError("openai_base_url_environment must be OPENAI_BASE_URL")
        if self.openai_base_url_environment is not None and self.model_provider not in {
            None,
            API_KEY_RUNTIME_PROVIDER,
        }:
            raise ValueError("API-key profiles use the framework-owned runtime model provider")
        if len(self.engineer_network_domain_ceiling) != len(
            set(self.engineer_network_domain_ceiling)
        ):
            raise ValueError("engineer_network_domain_ceiling must not contain duplicates")
        if len(self.engineer_dependency_network_domains) != len(
            set(self.engineer_dependency_network_domains)
        ):
            raise ValueError("engineer_dependency_network_domains must not contain duplicates")
        if not set(self.engineer_dependency_network_domains) <= set(
            self.engineer_network_domain_ceiling
        ):
            raise ValueError(
                "engineer_dependency_network_domains must be contained by the role ceiling"
            )
        return self


class ResearchConfig(ConfigModel):
    provider: Literal["searxng", "jina", "bing_rss"]
    bing_search_url: HttpUrl = HttpUrl("https://www.bing.com/search")
    searxng_base_url: HttpUrl | None = None
    searxng_allow_private_endpoint: bool = False
    allow_rfc2544_synthetic_egress: bool = False
    jina_search_url: HttpUrl = HttpUrl("https://s.jina.ai")
    jina_reader_url: HttpUrl = HttpUrl("https://r.jina.ai")
    jina_api_key_environment: str | None = None
    jina_credential_handle: str = Field(
        default="jina-api-key",
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$",
    )
    use_jina_reader_fallback: bool = True
    request_timeout_seconds: float = Field(default=30, gt=0)
    max_response_bytes: int = Field(default=8 * 1024 * 1024, gt=0, le=8 * 1024 * 1024)
    max_parallel_searches: int = Field(default=4, ge=1, le=32)
    max_parallel_fetches: int = Field(default=4, ge=1, le=32)

    @model_validator(mode="after")
    def provider_requirements(self) -> ResearchConfig:
        if self.provider == "searxng" and self.searxng_base_url is None:
            raise ValueError("searxng provider requires searxng_base_url")
        if self.provider == "jina" and self.jina_api_key_environment is None:
            raise ValueError("jina search requires jina_api_key_environment")
        parsed_bing = urlsplit(str(self.bing_search_url))
        if (
            parsed_bing.scheme != "https"
            or parsed_bing.hostname != "www.bing.com"
            or parsed_bing.port is not None
            or parsed_bing.path != "/search"
            or parsed_bing.username is not None
            or parsed_bing.password is not None
            or parsed_bing.query
            or parsed_bing.fragment
        ):
            raise ValueError("bing_search_url must be the exact credential-free Bing HTTPS origin")
        if (
            self.jina_api_key_environment is not None
            and re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                self.jina_api_key_environment,
            )
            is None
        ):
            raise ValueError("jina_api_key_environment must be an environment-variable name")
        _require_exact_jina_origin(self.jina_search_url, official_host="s.jina.ai")
        _require_exact_jina_origin(self.jina_reader_url, official_host="r.jina.ai")
        return self


def _require_exact_jina_origin(value: HttpUrl, *, official_host: str) -> None:
    parsed = urlsplit(str(value))
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Jina endpoint has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != official_host
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"Jina endpoint must be exactly https://{official_host} on port 443")


class JudgeConfig(ConfigModel):
    clean_build_timeout_seconds: float = Field(default=600, gt=0)
    uv_cache_dir: Path | None = None
    maximum_tasks_per_verifier_batch: int = Field(default=2, ge=1, le=8)
    maximum_structured_reworks: int = Field(default=3, ge=0, le=8)


class ObservabilityConfig(ConfigModel):
    """Production telemetry policy; secrets and sealed content are never captured."""

    commit_batch_size: int = Field(default=32, ge=1, le=4096)
    tier_a_keep_last_scopes: int = Field(default=64, ge=1, le=4096)


def _expansion_campaign_budget() -> Budget:
    return Budget(
        llm_tokens=6_000_000,
        agent_turns=640,
        search_calls=30,
        tool_calls=2_560,
        build_seconds=4_500,
        evaluation_episodes=640,
        container_seconds=18_000,
        repair_attempts=15,
        wall_seconds=36_000,
    )


def _expansion_candidate_budget() -> Budget:
    return Budget(
        llm_tokens=1_200_000,
        agent_turns=128,
        search_calls=6,
        tool_calls=512,
        build_seconds=900,
        evaluation_episodes=128,
        container_seconds=3_600,
        repair_attempts=3,
        wall_seconds=7_200,
    )


def _expansion_source_budget() -> Budget:
    return Budget(
        llm_tokens=80_000,
        agent_turns=4,
        search_calls=3,
        tool_calls=12,
        wall_seconds=900,
    )


class ExpansionSourceConfig(ConfigModel):
    """One replaceable evidence source frozen into each Campaign catalog."""

    source_id: str = Field(
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    engine: str = Field(
        default="evidence-backed-web",
        min_length=1,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    version: str = Field(min_length=1, max_length=80, default="1")
    kind: ExpansionSourceKind
    parameters: tuple[KeyValue, ...] = ()
    budget: Budget = Field(default_factory=_expansion_source_budget)
    maximum_hypotheses: int = Field(default=4, ge=1, le=32)
    maximum_clues: int = Field(default=4, ge=1, le=32)
    maximum_parents: int = Field(default=8, ge=1, le=64)
    maximum_context_bytes: int = Field(
        default=524_288,
        ge=16_384,
        le=4 * 1024 * 1024,
    )

    def descriptor(self) -> ExpansionSourceDescriptor:
        return ExpansionSourceDescriptor(
            source_id=self.source_id,
            engine=self.engine,
            kind=self.kind,
            version=self.version,
            parameters=self.parameters,
            budget=self.budget,
            maximum_hypotheses=self.maximum_hypotheses,
            maximum_clues=self.maximum_clues,
            maximum_parents=self.maximum_parents,
            maximum_context_bytes=self.maximum_context_bytes,
        )


def _default_expansion_sources() -> tuple[ExpansionSourceConfig, ...]:
    return (
        ExpansionSourceConfig(
            source_id="source:tool-ecosystem",
            kind="tool_ecosystem",
        ),
        ExpansionSourceConfig(
            source_id="source:pool-neighborhood",
            kind="pool_neighborhood",
        ),
        ExpansionSourceConfig(
            source_id="source:random-theme",
            kind="random_theme",
        ),
    )


def _default_expansion_source_ids() -> tuple[str, ...]:
    return (
        "source:tool-ecosystem",
        "source:pool-neighborhood",
        "source:random-theme",
    )


class ExpansionConfig(ConfigModel):
    """Default resource/search policy for an explicitly started campaign."""

    policy: Literal["random-search", "wide-search", "evolutionary-archive"] = "evolutionary-archive"
    sources: tuple[ExpansionSourceConfig, ...] = Field(default_factory=_default_expansion_sources)
    default_source_ids: tuple[str, ...] = Field(
        default_factory=_default_expansion_source_ids,
        min_length=1,
    )
    campaign_budget: Budget = Field(default_factory=_expansion_campaign_budget)
    candidate_budget: Budget = Field(default_factory=_expansion_candidate_budget)
    maximum_intents_per_iteration: int = Field(default=2, ge=1, le=128)
    maximum_iterations: int = Field(default=5, ge=1, le=1_000)
    maximum_no_release_iterations: int = Field(default=3, ge=1, le=1_000)
    maximum_infrastructure_error_iterations: int = Field(default=3, ge=1, le=100)
    max_in_flight: int = Field(default=2, ge=1, le=32)
    external_injection_rate: float = Field(default=0.25, ge=0, le=1)
    version_reservation_ttl_seconds: float = Field(default=86_400, ge=60, le=604_800)

    @model_validator(mode="after")
    def budgets_can_start_one_real_candidate(self) -> ExpansionConfig:
        if not self.sources:
            raise ValueError("Expansion requires at least one configured evidence Source")
        source_ids = [item.source_id for item in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("Expansion Source ids must be unique")
        if len(set(self.default_source_ids)) != len(self.default_source_ids):
            raise ValueError("default_source_ids must be unique")
        unknown_defaults = sorted(set(self.default_source_ids) - set(source_ids))
        if unknown_defaults:
            raise ValueError(
                f"default_source_ids are not in the Source catalog: {unknown_defaults}"
            )
        # Constructing the public descriptor here applies the same closed budget
        # and parameter rules used by the durable Campaign artifact.
        for source in self.sources:
            source.descriptor()
        if self.max_in_flight > self.maximum_intents_per_iteration:
            raise ValueError("max_in_flight cannot exceed maximum_intents_per_iteration")
        if self.candidate_budget.agent_turns < 1 or self.candidate_budget.wall_seconds <= 0:
            raise ValueError("candidate_budget requires positive Agent-turn and wall reservations")
        for field_name in Budget.model_fields:
            if field_name == "schema_version" or field_name == "wall_seconds":
                continue
            if getattr(self.candidate_budget, field_name) > getattr(
                self.campaign_budget, field_name
            ):
                raise ValueError(
                    f"candidate_budget.{field_name} exceeds the whole campaign reservation"
                )
        if self.candidate_budget.wall_seconds > self.campaign_budget.wall_seconds:
            raise ValueError("candidate wall timeout exceeds the campaign deadline")
        default_sources = tuple(
            source for source in self.sources if source.source_id in self.default_source_ids
        )
        for source in default_sources:
            if source.budget.wall_seconds > self.campaign_budget.wall_seconds:
                raise ValueError(f"Source {source.source_id} timeout exceeds the campaign deadline")
        for field_name in Budget.model_fields:
            if field_name in {"schema_version", "wall_seconds"}:
                continue
            required = getattr(self.candidate_budget, field_name) + sum(
                getattr(source.budget, field_name) for source in default_sources
            )
            if required > getattr(self.campaign_budget, field_name):
                raise ValueError(
                    "default Source intake plus one real candidate exceeds "
                    f"campaign_budget.{field_name}"
                )
        return self


def _generation_budget() -> Budget:
    return Budget(
        llm_tokens=10_000_000,
        agent_turns=128,
        search_calls=6,
        tool_calls=512,
        # The Direct Builder session is permitted to consume the configured
        # outer eight-hour wall envelope through explicit physical turns.
        build_seconds=28_800,
        evaluation_episodes=128,
        container_seconds=3_600,
        repair_attempts=15,
        wall_seconds=28_800,
    )


def _discovery_budget() -> Budget:
    return Budget(
        # Four independent structured turns at the default hard per-turn cap.
        # This lane never borrows capacity from Direct Generation.
        llm_tokens=262_144,
        agent_turns=4,
        search_calls=3,
        tool_calls=12,
        wall_seconds=900,
    )


class FoundryConfig(ConfigModel):
    state_root: Path
    agent: AgentBackendConfig
    research: ResearchConfig
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    expansion: ExpansionConfig = Field(default_factory=ExpansionConfig)
    generation_budget: Budget = Field(default_factory=_generation_budget)
    discovery_budget: Budget = Field(default_factory=_discovery_budget)
    release_profile: ReleaseProfile = Field(
        default_factory=lambda: ReleaseProfile(profile_id="default-release")
    )

    @model_validator(mode="after")
    def discovery_budget_can_admit_its_base_work(self) -> FoundryConfig:
        budget = self.discovery_budget
        configured = any(
            getattr(budget, field_name) > 0
            for field_name in Budget.model_fields
            if field_name != "schema_version"
        )
        if not configured:
            return self
        minimum_turns = 2
        if budget.agent_turns < minimum_turns:
            raise ValueError("discovery_budget requires at least two base Agent turns")
        minimum_tokens = minimum_turns * self.agent.structured_turn_token_limit
        if budget.llm_tokens < minimum_tokens:
            raise ValueError(
                "discovery_budget.llm_tokens cannot reserve two structured turns at "
                "agent.structured_turn_token_limit"
            )
        if budget.wall_seconds <= 0:
            raise ValueError("discovery_budget requires positive wall_seconds")
        return self


_SENSITIVE_CONFIG_KEYS = re.compile(
    r"(?:^|[_-])(?:password|secret|access_token|refresh_token|private_key)(?:$|[_-])",
    re.IGNORECASE,
)


def load_foundry_config(path: str | os.PathLike[str] | None = None) -> FoundryConfig:
    """Load one explicit TOML config without accepting embedded credential values."""

    selected = path or os.environ.get("AGENT_WORLD_CONFIG")
    if selected is None:
        selected_path = Path.home() / ".config" / "agent-world" / "config.toml"
    else:
        selected_path = Path(selected).expanduser()
    try:
        raw = selected_path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"cannot read Foundry config {selected_path}: {exc}") from exc
    try:
        value = tomllib.loads(raw.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"invalid Foundry TOML {selected_path}: {exc}") from exc
    _reject_file_backed_agent_credentials(value)
    _reject_embedded_secrets(value)
    value = _normalise_toml_contract_fields(value)
    try:
        config = FoundryConfig.model_validate(value)
    except Exception as exc:
        raise ConfigError(f"invalid Foundry config {selected_path}: {exc}") from exc

    base = selected_path.resolve().parent
    state_root = _resolve_config_path(config.state_root, base)
    agent = config.agent
    codex_bin = _resolve_config_path(agent.codex_bin, base) if agent.codex_bin is not None else None
    judge_cache = (
        _resolve_config_path(config.judge.uv_cache_dir, base)
        if config.judge.uv_cache_dir is not None
        else None
    )
    return config.model_copy(
        update={
            "state_root": state_root,
            "agent": agent.model_copy(update={"codex_bin": codex_bin}),
            "judge": config.judge.model_copy(update={"uv_cache_dir": judge_cache}),
        }
    )


def _reject_file_backed_agent_credentials(value: dict[str, object]) -> None:
    """Reject legacy config keys without ever reflecting their values.

    An endpoint is deployment routing material under the same no-persistence
    policy as an API credential.  Accepting the old literal field, even only
    long enough to transform it, would make a config file a secret-bearing
    artifact.  The migration is deliberately explicit and value-free.
    """

    agent = value.get("agent")
    if not isinstance(agent, dict):
        return
    if "openai_base_url" in agent:
        raise ConfigError(
            "agent.openai_base_url is forbidden; use "
            'agent.openai_base_url_environment = "OPENAI_BASE_URL"'
        )
    if "chatgpt_auth_file" in agent:
        raise ConfigError("agent.chatgpt_auth_file is forbidden; use an API-key environment handle")


def _resolve_config_path(path: Path, base: Path) -> Path:
    expanded = path.expanduser()
    combined = base / expanded if not expanded.is_absolute() else expanded
    return Path(os.path.abspath(combined))


def _normalise_toml_contract_fields(value: dict[str, object]) -> dict[str, object]:
    """Adapt TOML arrays at the config boundary without weakening strict contracts."""

    release_profile = value.get("release_profile")
    if not isinstance(release_profile, dict):
        return value
    normalised_profile = dict(release_profile)
    for field_name in ("required_hard_gates", "minimum_coverage_dimensions"):
        field_value = normalised_profile.get(field_name)
        if isinstance(field_value, list):
            normalised_profile[field_name] = tuple(field_value)
    return {**value, "release_profile": normalised_profile}


def _reject_embedded_secrets(value: object, *, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if _SENSITIVE_CONFIG_KEYS.search(key_text):
                raise ConfigError(f"secret-valued config key is prohibited: {path}.{key_text}")
            _reject_embedded_secrets(child, path=f"{path}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_embedded_secrets(child, path=f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if lowered.startswith("sk-") or "-----begin private key-----" in lowered:
            raise ConfigError(f"credential-like value is prohibited in {path}")


__all__ = [
    "AgentBackendConfig",
    "ConfigError",
    "ExpansionConfig",
    "ExpansionSourceConfig",
    "FoundryConfig",
    "JudgeConfig",
    "ResearchConfig",
    "load_foundry_config",
]

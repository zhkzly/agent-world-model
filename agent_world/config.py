from __future__ import annotations

from dataclasses import asdict, dataclass
import os
from pathlib import Path
import re
from typing import Any, Mapping

import yaml


DEFAULT_AGENT_BACKEND = "llm"
DEFAULT_IMPLEMENTATION_AGENT_BACKEND = "codex_sdk"
DEFAULT_OPENAI_BASE_URL = "https://blog.r78xoaxrk.nyat.app:50903/v1"
DEFAULT_OPENAI_MODEL = "gpt-5.3-codex-spark"
DEFAULT_OPENAI_MODEL_CANDIDATES = [
    "gpt-5.3-codex-spark",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
]
DEFAULT_AGENT_NETWORK = True
DEFAULT_AGENT_TIMEOUT_MS = 60000
DEFAULT_AGENT_MAX_TOKENS = 4096
DEFAULT_AGENT_MAX_ATTEMPTS = 3
DEFAULT_CODE_REPAIR_THREAD_MODE = "stateless"
DEFAULT_CODEX_SANDBOX = "workspace-write"
SEMANTIC_AGENT_PROFILE = "semantic"
IMPLEMENTATION_AGENT_PROFILE = "implementation"
KNOWN_PIPELINE_STAGES = [
    "PLAN",
    "SELECT",
    "S0",
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S7",
    "S8",
    "S9",
    "IMPLEMENT",
    "S10",
    "S11",
]
DEFAULT_STAGE_AGENT_PROFILES = {stage: SEMANTIC_AGENT_PROFILE for stage in KNOWN_PIPELINE_STAGES}
DEFAULT_STAGE_AGENT_PROFILES["IMPLEMENT"] = IMPLEMENTATION_AGENT_PROFILE


@dataclass(frozen=True)
class ResearchConfig:
    backend: str
    searxng_url: str
    jina_search_url: str
    jina_reader_url: str
    jina_api_key_env: str
    process_command: str
    max_queries: int
    max_results: int


@dataclass(frozen=True)
class NodeExecutionConfig:
    mode: str
    research: ResearchConfig


@dataclass(frozen=True)
class AgentProfileConfig:
    profile_id: str
    backend_kind: str
    provider: str
    model: str
    smoke_model: str
    model_candidates: list[str]
    base_url: str
    api_version: str
    api_key_env: str
    auth_env_refs: list[str]
    agent_auth: bool
    command_value: str
    allowlist_value: str
    command_cwd: str
    timeout_ms: int
    max_attempts: int
    max_tokens: int
    network: bool
    codex_sandbox: str
    code_repair_thread_mode: str


@dataclass(frozen=True)
class AgentWorldConfig:
    node_execution_mode: str
    research: ResearchConfig
    agent_profiles: dict[str, AgentProfileConfig]
    stage_agent_profiles: dict[str, str]
    config_path: str = ""

    def profile_for_stage(self, stage: str) -> AgentProfileConfig:
        profile_id = self.stage_agent_profiles.get(stage, SEMANTIC_AGENT_PROFILE)
        if profile_id not in self.agent_profiles:
            raise KeyError(f"Stage {stage} references unknown agent profile: {profile_id}")
        return self.agent_profiles[profile_id]

    def to_redacted_dict(self) -> dict[str, Any]:
        return {
            "node_execution_mode": self.node_execution_mode,
            "research": asdict(self.research),
            "agent_profiles": {
                profile_id: asdict(profile)
                for profile_id, profile in self.agent_profiles.items()
            },
            "stage_agent_profiles": dict(self.stage_agent_profiles),
            "config_path": self.config_path,
        }


def load_node_execution_config(env: Mapping[str, str] | None = None) -> NodeExecutionConfig:
    config = load_agent_world_config(env)
    return NodeExecutionConfig(
        mode=config.node_execution_mode,
        research=config.research,
    )


def load_agent_world_config(env: Mapping[str, str] | None = None) -> AgentWorldConfig:
    values = os.environ if env is None else env
    file_config, config_path = _load_config_file(values)
    semantic = _resolve_agent_profile(
        values,
        file_config,
        profile_id=SEMANTIC_AGENT_PROFILE,
        env_scope="",
        base=None,
        default_backend_kind=DEFAULT_AGENT_BACKEND,
    )
    implementation = _resolve_agent_profile(
        values,
        file_config,
        profile_id=IMPLEMENTATION_AGENT_PROFILE,
        env_scope="IMPLEMENT",
        base=semantic,
        default_backend_kind=_implementation_default_backend_kind(values, file_config),
    )
    profiles = {
        SEMANTIC_AGENT_PROFILE: semantic,
        IMPLEMENTATION_AGENT_PROFILE: implementation,
    }
    for profile_id in sorted(_configured_profile_ids(file_config) - set(profiles)):
        base_profile = profiles.get(_profile_parent(file_config, profile_id), semantic)
        profiles[profile_id] = _resolve_agent_profile(
            values,
            file_config,
            profile_id=profile_id,
            env_scope=_profile_env_scope(profile_id),
            base=base_profile,
            default_backend_kind=base_profile.backend_kind,
        )
    return AgentWorldConfig(
        node_execution_mode=str(_env_or_config(values, file_config, "AGENT_WORLD_NODE_EXECUTION", ["node_execution", "mode"], "agent")),
        research=_load_research_config(values, file_config=file_config),
        agent_profiles=profiles,
        stage_agent_profiles=_stage_agent_profiles(values, file_config),
        config_path=config_path,
    )


def load_research_config(env: Mapping[str, str] | None = None) -> ResearchConfig:
    return _load_research_config(env, file_config=None)


def _load_research_config(env: Mapping[str, str] | None = None, *, file_config: Mapping[str, Any] | None = None) -> ResearchConfig:
    values = os.environ if env is None else env
    research = _mapping_at(file_config or {}, ["research"])
    return ResearchConfig(
        backend=str(_env_or_mapping(values, research, "AGENT_WORLD_RESEARCH_BACKEND", "backend", "local")),
        searxng_url=str(_env_or_mapping(values, research, "AGENT_WORLD_SEARXNG_URL", "searxng_url", "")),
        jina_search_url=str(_env_or_mapping(values, research, "AGENT_WORLD_JINA_SEARCH_URL", "jina_search_url", "https://s.jina.ai")),
        jina_reader_url=str(_env_or_mapping(values, research, "AGENT_WORLD_JINA_READER_URL", "jina_reader_url", "https://r.jina.ai")),
        jina_api_key_env=_jina_api_key_env(values),
        process_command=str(_env_or_mapping(values, research, "AGENT_WORLD_RESEARCH_CMD", "process_command", "")),
        max_queries=max(1, int(_env_or_mapping(values, research, "AGENT_WORLD_RESEARCH_MAX_QUERIES", "max_queries", "5"))),
        max_results=max(1, int(_env_or_mapping(values, research, "AGENT_WORLD_RESEARCH_MAX_RESULTS", "max_results", "10"))),
    )


def _jina_api_key_env(values: Mapping[str, str]) -> str:
    if values.get("AGENT_WORLD_JINA_API_KEY_ENV"):
        return str(values["AGENT_WORLD_JINA_API_KEY_ENV"])
    if values.get("AGENT_WORLD_JINA_API_KEY"):
        return "AGENT_WORLD_JINA_API_KEY"
    return "JINA_API_KEY"


def _resolve_agent_profile(
    values: Mapping[str, str],
    file_config: Mapping[str, Any],
    *,
    profile_id: str,
    env_scope: str,
    base: AgentProfileConfig | None,
    default_backend_kind: str,
) -> AgentProfileConfig:
    profile = _profile_mapping(file_config, profile_id)
    backend_kind = str(_scoped_value(values, env_scope, "AGENT_BACKEND", profile.get("backend_kind", default_backend_kind)))
    base_url = str(_scoped_value(values, env_scope, "OPENAI_BASE_URL", profile.get("base_url", base.base_url if base else DEFAULT_OPENAI_BASE_URL), external_names=["OPENAI_BASE_URL"]))
    model = str(_scoped_value(values, env_scope, "OPENAI_MODEL", profile.get("model", base.model if base else DEFAULT_OPENAI_MODEL), external_names=["OPENAI_MODEL"]))
    smoke_model = str(_scoped_value(values, env_scope, "SMOKE_OPENAI_MODEL", profile.get("smoke_model", model)))
    candidates_raw = _scoped_value(values, env_scope, "OPENAI_MODEL_CANDIDATES", profile.get("model_candidates", base.model_candidates if base else DEFAULT_OPENAI_MODEL_CANDIDATES))
    model_candidates = _model_candidates(candidates_raw)
    api_version = str(_scoped_value(values, env_scope, "OPENAI_API_VERSION", profile.get("api_version", _infer_api_version(base_url, backend_kind))))
    api_key_env = _api_key_env(values, env_scope, profile.get("api_key_env", base.api_key_env if base else ""))
    auth_env_refs = _auth_env_refs(values, env_scope, api_key_env)
    command_value = _command_value(values, profile, env_scope, backend_kind, base)
    allowlist_value = str(_scoped_value(values, env_scope, "PROCESS_AGENT_ALLOWLIST", profile.get("allowlist_value", base.allowlist_value if base else ""), fallback_suffixes=["CODEX_ALLOWLIST"]))
    command_cwd = str(_scoped_value(values, env_scope, "PROCESS_AGENT_CWD", profile.get("command_cwd", base.command_cwd if base else ".")))
    return AgentProfileConfig(
        profile_id=profile_id,
        backend_kind=backend_kind,
        provider=str(profile.get("provider") or _provider_for_backend(backend_kind)),
        model=model,
        smoke_model=smoke_model,
        model_candidates=model_candidates,
        base_url=base_url,
        api_version=api_version,
        api_key_env=api_key_env,
        auth_env_refs=auth_env_refs,
        agent_auth=_scoped_flag(values, env_scope, "AGENT_AUTH", _scoped_flag(values, env_scope, "CODEX_AUTH", bool(profile.get("agent_auth", base.agent_auth if base else False)))),
        command_value=command_value,
        allowlist_value=allowlist_value,
        command_cwd=command_cwd,
        timeout_ms=int(_scoped_value(values, env_scope, "AGENT_TIMEOUT_MS", profile.get("timeout_ms", base.timeout_ms if base else DEFAULT_AGENT_TIMEOUT_MS))),
        max_attempts=int(_scoped_value(values, env_scope, "AGENT_MAX_ATTEMPTS", profile.get("max_attempts", base.max_attempts if base else DEFAULT_AGENT_MAX_ATTEMPTS))),
        max_tokens=int(_scoped_value(values, env_scope, "AGENT_MAX_TOKENS", profile.get("max_tokens", base.max_tokens if base else DEFAULT_AGENT_MAX_TOKENS))),
        network=_scoped_flag(values, env_scope, "AGENT_NETWORK", bool(profile.get("network", base.network if base else DEFAULT_AGENT_NETWORK))),
        codex_sandbox=str(_scoped_value(values, env_scope, "CODEX_SANDBOX", profile.get("codex_sandbox", base.codex_sandbox if base else DEFAULT_CODEX_SANDBOX))),
        code_repair_thread_mode=_code_repair_thread_mode(str(_scoped_value(values, env_scope, "CODE_REPAIR_THREAD_MODE", profile.get("code_repair_thread_mode", base.code_repair_thread_mode if base else DEFAULT_CODE_REPAIR_THREAD_MODE)))),
    )


def _implementation_default_backend_kind(values: Mapping[str, str], file_config: Mapping[str, Any]) -> str:
    profile = _profile_mapping(file_config, IMPLEMENTATION_AGENT_PROFILE)
    if values.get("AGENT_WORLD_IMPLEMENT_AGENT_BACKEND"):
        return str(values["AGENT_WORLD_IMPLEMENT_AGENT_BACKEND"])
    if profile.get("backend_kind"):
        return str(profile["backend_kind"])
    if values.get("AGENT_WORLD_AGENT_BACKEND"):
        return str(values["AGENT_WORLD_AGENT_BACKEND"])
    return DEFAULT_IMPLEMENTATION_AGENT_BACKEND


def _command_value(
    values: Mapping[str, str],
    profile: Mapping[str, Any],
    env_scope: str,
    backend_kind: str,
    base: AgentProfileConfig | None,
) -> str:
    default = str(profile.get("command_value", base.command_value if base else ""))
    if backend_kind in {"codex_cli", "codex_cli_runner"}:
        return str(_scoped_value(values, env_scope, "CODEX_CMD", default))
    return str(_scoped_value(values, env_scope, "CODE_AGENT_CMD", default, fallback_suffixes=["CODEX_CMD"]))


def _stage_agent_profiles(values: Mapping[str, str], file_config: Mapping[str, Any]) -> dict[str, str]:
    stage_config = _mapping_at(file_config, ["stages"])
    if stage_config:
        default_profile = str(stage_config.get("default_agent_profile", SEMANTIC_AGENT_PROFILE))
        bindings = {stage: default_profile for stage in KNOWN_PIPELINE_STAGES}
    else:
        bindings = dict(DEFAULT_STAGE_AGENT_PROFILES)
    configured = stage_config.get("agent_profiles", {})
    if isinstance(configured, Mapping):
        bindings.update({str(stage): str(profile_id) for stage, profile_id in configured.items()})
    for key, value in stage_config.items():
        if str(key).upper() in KNOWN_PIPELINE_STAGES and isinstance(value, str):
            bindings[str(key).upper()] = value
    for stage in KNOWN_PIPELINE_STAGES:
        env_name = f"AGENT_WORLD_STAGE_{stage}_AGENT_PROFILE"
        if values.get(env_name):
            bindings[stage] = str(values[env_name])
    return bindings


def _load_config_file(values: Mapping[str, str]) -> tuple[dict[str, Any], str]:
    path_text = str(values.get("AGENT_WORLD_CONFIG", "")).strip()
    if not path_text:
        return {}, ""
    path = Path(path_text).expanduser()
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("AGENT_WORLD_CONFIG must point to a YAML object")
    _reject_secret_material(payload)
    return payload, str(path)


def _reject_secret_material(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).lower() in {"api_key", "secret", "token"}:
                raise ValueError("Agent World config must reference secret env names, not secret values")
            _reject_secret_material(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secret_material(item)


def _configured_profile_ids(file_config: Mapping[str, Any]) -> set[str]:
    profiles = _mapping_at(file_config, ["agent_profiles"])
    return {str(profile_id) for profile_id in profiles}


def _profile_mapping(file_config: Mapping[str, Any], profile_id: str) -> dict[str, Any]:
    profiles = _mapping_at(file_config, ["agent_profiles"])
    value = profiles.get(profile_id, {})
    return dict(value) if isinstance(value, Mapping) else {}


def _profile_parent(file_config: Mapping[str, Any], profile_id: str) -> str:
    parent = _profile_mapping(file_config, profile_id).get("inherits", SEMANTIC_AGENT_PROFILE)
    return str(parent or SEMANTIC_AGENT_PROFILE)


def _profile_env_scope(profile_id: str) -> str:
    if profile_id == SEMANTIC_AGENT_PROFILE:
        return ""
    if profile_id == IMPLEMENTATION_AGENT_PROFILE:
        return "IMPLEMENT"
    return re.sub(r"[^A-Z0-9]+", "_", profile_id.upper()).strip("_")


def _mapping_at(value: Mapping[str, Any], path: list[str]) -> dict[str, Any]:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key, {})
    return dict(current) if isinstance(current, Mapping) else {}


def _env_or_config(values: Mapping[str, str], file_config: Mapping[str, Any], env_name: str, path: list[str], default: Any) -> Any:
    if values.get(env_name) not in {None, ""}:
        return values[env_name]
    current: Any = file_config
    for key in path:
        if not isinstance(current, Mapping) or key not in current:
            return default
        current = current[key]
    return current


def _env_or_mapping(values: Mapping[str, str], mapping: Mapping[str, Any], env_name: str, key: str, default: Any) -> Any:
    if values.get(env_name) not in {None, ""}:
        return values[env_name]
    return mapping.get(key, default)


def _scoped_value(
    values: Mapping[str, str],
    env_scope: str,
    suffix: str,
    default: Any,
    *,
    fallback_suffixes: list[str] | None = None,
    external_names: list[str] | None = None,
) -> Any:
    names = []
    suffixes = [suffix] + list(fallback_suffixes or [])
    if env_scope:
        for item in suffixes:
            names.append(f"AGENT_WORLD_{env_scope}_{item}")
    for item in suffixes:
        names.append(f"AGENT_WORLD_{item}")
    names.extend(external_names or [])
    for name in names:
        if values.get(name) not in {None, ""}:
            return values[name]
    return default


def _scoped_flag(values: Mapping[str, str], env_scope: str, suffix: str, default: bool) -> bool:
    value = _scoped_value(values, env_scope, suffix, None)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _api_key_env(values: Mapping[str, str], env_scope: str, configured: str) -> str:
    names = []
    if env_scope:
        names.append(f"AGENT_WORLD_{env_scope}_OPENAI_API_KEY")
    names.extend(["AGENT_WORLD_OPENAI_API_KEY", "OPENAI_API_KEY"])
    for name in names:
        if values.get(name):
            return name
    return str(configured or "")


def _auth_env_refs(values: Mapping[str, str], env_scope: str, api_key_env: str) -> list[str]:
    names = []
    if env_scope:
        names.append(f"AGENT_WORLD_{env_scope}_OPENAI_API_KEY")
    names.extend(["AGENT_WORLD_OPENAI_API_KEY", "OPENAI_API_KEY"])
    if api_key_env:
        names.append(api_key_env)
    return list(dict.fromkeys(name for name in names if values.get(name) or name == api_key_env))


def _model_candidates(raw: Any) -> list[str]:
    if isinstance(raw, list):
        values = [str(item).strip().lstrip("-") for item in raw if str(item).strip()]
    else:
        values = [item.strip().lstrip("-") for item in str(raw or "").split(",") if item.strip()]
    return values or list(DEFAULT_OPENAI_MODEL_CANDIDATES)


def _code_repair_thread_mode(raw: str) -> str:
    mode = str(raw or DEFAULT_CODE_REPAIR_THREAD_MODE).strip().lower()
    return mode if mode in {"stateless", "continue"} else DEFAULT_CODE_REPAIR_THREAD_MODE


def _infer_api_version(base_url: str, backend_kind: str) -> str:
    if backend_kind in {"llm", "llm_file_codegen"} and str(base_url).rstrip("/").endswith("/v1"):
        return "v1"
    return ""


def _provider_for_backend(backend_kind: str) -> str:
    if backend_kind in {"process_agent", "code_agent_runner"}:
        return "local_process"
    if backend_kind in {"codex_cli", "codex_cli_runner", "codex_sdk"}:
        return "codex"
    if backend_kind == "manual":
        return "manual"
    if backend_kind == "mock":
        return "mock"
    if backend_kind in {"llm", "llm_file_codegen"}:
        return "openai_compatible"
    return "custom"
